#!/usr/bin/env python3
"""
Query Google Play Developer Reporting API for various vitals metrics.

Requires authentication: 
  gcloud auth application-default login --scopes=https://www.googleapis.com/auth/playdeveloperreporting
"""

import argparse
import json
import math
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta, UTC
from typing import Dict, List, Any, Optional, Tuple

import google.auth
from googleapiclient.discovery import build


# ---------------------------------------------------------------------------
# Version code resolution
# ---------------------------------------------------------------------------
# Fenix v1 version code scheme (from Config.kt in mozilla-central):
#   Format: 0111 1000 0010 tttt tttt tttt tttt txpg
#   t = hours since V1_CUTOFF, x = x86, p = 64-bit, g = AAB/universal
#
# Epoch from Config.kt: 20141228000000
# (Note: differs from the old Fennec python epoch of 20150801 for historical reasons.)

V1_CUTOFF = 20141228000000  # YYYYmmddHHMMSS
V1_BASE = 0b1111000001000000000000000000000

# Minimum version code to include in results.  Builds before this are
# too old to be interesting.  Corresponds to Nov 1, 2025 00:00 UTC.
MIN_VERSION_CODE = 2016123584

PRODUCT_DETAILS_URL = "https://product-details.mozilla.org/1.0/mobile_android.json"


def reverse_version_code(version_code: int) -> Tuple[str, str, datetime]:
    """Reverse a Fenix v1 android:versionCode to build info.

    Format: 0111 1000 0010 tttt tttt tttt tttt txpg
    t = hours since V1_CUTOFF, x = x86, p = 64-bit, g = AAB/universal flag.
    Returns (build_id, cpu_arch, build_datetime).
    """
    stripped = version_code - V1_BASE

    # Low 3 bits: x (bit 2), p (bit 1), g (bit 0)
    x_bit = (stripped >> 2) & 1
    p_bit = (stripped >> 1) & 1

    if x_bit and p_bit:
        arch = "x86_64"
    elif x_bit:
        arch = "x86"
    elif p_bit:
        arch = "arm64-v8a"
    else:
        arch = "armeabi-v7a"

    hours = stripped >> 3

    fmt = "%Y%m%d%H%M%S"
    cutoff_time = time.mktime(time.strptime(str(V1_CUTOFF), fmt))
    build_time = cutoff_time + (hours * 3600)
    build_dt = datetime.fromtimestamp(build_time)
    build_id = build_dt.strftime(fmt)

    return build_id, arch, build_dt


def fetch_release_versions(
    include_betas: bool = False,
) -> List[Tuple[date, str]]:
    """Fetch Firefox for Android release history from Mozilla product-details.

    Returns a sorted list of (release_date, version) for releases.
    The endpoint contains both legacy ``fenix`` and current
    ``firefox-android`` product entries.

    When *include_betas* is True, beta versions (category ``dev``) are
    included alongside stable releases.
    """
    try:
        with urllib.request.urlopen(PRODUCT_DETAILS_URL, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(
            f"Warning: Could not fetch product-details ({e}), "
            "version names will not be shown.",
            file=sys.stderr,
        )
        return []

    allowed_categories = {"major", "stability"}
    if include_betas:
        allowed_categories.add("dev")

    releases = []
    for key, info in data.get("releases", {}).items():
        product = info.get("product", "")
        # Accept both legacy "fenix" and current "firefox-android" entries
        if product not in ("fenix", "firefox-android"):
            continue
        version = info.get("version", "")
        if not include_betas:
            # Skip betas / alphas / release candidates for stable queries
            if any(ch in version for ch in ("b", "a", "rc")):
                continue
        else:
            # Even for beta queries, skip alphas and release candidates
            if any(ch in version for ch in ("a", "rc")):
                continue
        category = info.get("category", "")
        if category not in allowed_categories:
            continue
        try:
            rel_date = datetime.strptime(info["date"], "%Y-%m-%d").date()
        except (KeyError, ValueError):
            continue
        # Only keep releases from 2025 onwards (buffer for 2026 boundary)
        if rel_date.year < 2025:
            continue
        releases.append((rel_date, version))

    releases.sort(key=lambda x: x[0])
    return releases


def resolve_version_name(
    build_dt: datetime,
    releases: List[Tuple[date, str]],
) -> str:
    """Find the Firefox version that a build belongs to.

    Builds are compiled *before* their release ships, so a build from
    Dec 29 targets the *next* major release (e.g. 134.0 on Jan 7), not
    the one currently live (133.0.3 from Dec 10).

    Strategy: find the first release whose date is >= the build date
    and return its major version.  If the build date falls between a
    major release and a dot-release of that same major, prefer the
    dot-release.  Fall back to the previous release for very old builds.
    """
    build_d = build_dt.date()

    # Find the first release on or after the build date
    for i, (rel_date, version) in enumerate(releases):
        if rel_date >= build_d:
            return version

    # Build is newer than all known releases — infer the next major version.
    # This typically happens for beta/nightly builds that are ahead of
    # the latest stable release.
    if releases:
        latest_version = releases[-1][1]
        try:
            major = int(latest_version.split(".")[0])
            return f"{major + 1}.0b"
        except (ValueError, IndexError):
            return latest_version
    return "unknown"


class VersionResolver:
    """Lazily resolves version codes to human-readable Firefox versions."""

    def __init__(self, include_betas: bool = False):
        self._releases: Optional[List[Tuple[date, str]]] = None
        self._include_betas = include_betas

    def _ensure_releases(self):
        if self._releases is None:
            self._releases = fetch_release_versions(
                include_betas=self._include_betas
            )

    def resolve(self, version_code: int) -> Tuple[str, str]:
        """Return (version_name, cpu_arch) for a version code."""
        self._ensure_releases()
        try:
            _build_id, arch, build_dt = reverse_version_code(version_code)
            version = resolve_version_name(build_dt, self._releases)
            return version, arch
        except Exception:
            return "unknown", "unknown"


# Metric set configurations
METRIC_SETS = {
    "crashrate": {
        "endpoint": "crashrate",
        "metric_set_suffix": "crashRateMetricSet",
        "metrics": [
            "crashRate",
            "crashRate28dUserWeighted",
            "userPerceivedCrashRate",
            "userPerceivedCrashRate28dUserWeighted",
            "distinctUsers",
        ],
        "display_name": "Crash Rate",
    },
    "anrrate": {
        "endpoint": "anrrate",
        "metric_set_suffix": "anrRateMetricSet",
        "metrics": [
            "anrRate",
            "anrRate28dUserWeighted",
            "userPerceivedAnrRate",
            "userPerceivedAnrRate28dUserWeighted",
            "distinctUsers",
        ],
        "display_name": "ANR Rate",
    },
    "excessivewakeuprate": {
        "endpoint": "excessivewakeuprate",
        "metric_set_suffix": "excessiveWakeupRateMetricSet",
        "metrics": [
            "excessiveWakeupRate",
            "excessiveWakeupRate28dUserWeighted",
            "distinctUsers",
        ],
        "display_name": "Excessive Wakeup Rate",
    },
    "stuckbackgroundwakelockrate": {
        "endpoint": "stuckbackgroundwakelockrate",
        "metric_set_suffix": "stuckBackgroundWakelockRateMetricSet",
        "metrics": [
            "stuckBackgroundWakelockRate",
            "stuckBackgroundWakelockRate28dUserWeighted",
            "distinctUsers",
        ],
        "display_name": "Stuck Background Wakelock Rate",
    },
    "slowrenderingrate": {
        "endpoint": "slowrenderingrate",
        "metric_set_suffix": "slowRenderingRateMetricSet",
        "metrics": [
            "slowRenderingRate",
            "slowRenderingRate28dUserWeighted",
            "distinctUsers",
        ],
        "display_name": "Slow Rendering Rate",
    },
    "slowstartrate": {
        "endpoint": "slowstartrate",
        "metric_set_suffix": "slowStartRateMetricSet",
        "metrics": [
            "slowStartRate",
            "slowStartRate28dUserWeighted",
            "distinctUsers",
        ],
        "display_name": "Slow Start Rate",
    },
    "frozenframerate": {
        "endpoint": "frozenframerate",
        "metric_set_suffix": "frozenFrameRateMetricSet",
        "metrics": [
            "frozenFrameRate",
            "frozenFrameRate28dUserWeighted",
            "distinctUsers",
        ],
        "display_name": "Frozen Frame Rate",
    },
}


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Query Google Play Developer Reporting API for vitals metrics",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Available metric sets:
  {', '.join(METRIC_SETS.keys())}

Examples:
  %(prog)s --package org.mozilla.fenix --metric-set crashrate
  %(prog)s --package com.example.app --metric-set anrrate --days 7
  %(prog)s --package org.mozilla.fenix --metric-set crashrate --metrics crashRate distinctUsers
  %(prog)s --package org.mozilla.firefox_beta --metric-set anrrate --top 5 --exclude-zero
  %(prog)s --package org.mozilla.fenix --metric-set crashrate --min-users 1000 --top 10
  %(prog)s --package org.mozilla.firefox --metric-set crashrate --resolve-versions --top 10
  %(prog)s --package org.mozilla.firefox --anomalies --days 28
  %(prog)s --package org.mozilla.firefox --anomalies --resolve-versions
        """,
    )

    parser.add_argument(
        "--package",
        "-p",
        required=True,
        help="Package name (e.g., org.mozilla.fenix)",
    )

    parser.add_argument(
        "--metric-set",
        "-m",
        required=False,
        default="crashrate",
        choices=list(METRIC_SETS.keys()),
        help="Metric set to query",
    )

    parser.add_argument(
        "--metrics",
        nargs="+",
        help="Specific metrics to query (defaults to all available for the metric set)",
    )

    parser.add_argument(
        "--dimensions",
        "-d",
        nargs="+",
        default=["versionCode"],
        help="Dimensions to group by (default: versionCode)",
    )

    parser.add_argument(
        "--days",
        type=int,
        default=1,
        help="Number of days to query (default: 1, yesterday only)",
    )

    parser.add_argument(
        "--page-size",
        type=int,
        default=5000,
        help="Number of results per page (default: 5000)",
    )

    parser.add_argument(
        "--output-format",
        choices=["pretty", "csv", "json"],
        default="pretty",
        help="Output format (default: pretty)",
    )

    parser.add_argument(
        "--top",
        type=int,
        help="Show only top N versions (by versionCode, descending)",
    )

    parser.add_argument(
        "--min-users",
        type=int,
        help="Filter out versions with fewer than N distinct users",
    )

    parser.add_argument(
        "--exclude-zero",
        action="store_true",
        help="Exclude versions where all rate metrics are 0%%",
    )

    parser.add_argument(
        "--version-code",
        type=str,
        help="Filter to specific versionCode(s), comma-separated (e.g., 2016122735 or 2016122735,2016122159)",
    )

    parser.add_argument(
        "--resolve-versions",
        action="store_true",
        help="Resolve versionCodes to Firefox version names and CPU architectures "
        "(fetches data from product-details.mozilla.org)",
    )

    parser.add_argument(
        "--anomalies",
        action="store_true",
        help="List detected anomalies (crash rate / ANR rate spikes) instead of "
        "querying a metric set. Supports --days to limit the lookback window.",
    )

    return parser.parse_args()


def authenticate():
    """Authenticate with Google Cloud."""
    creds, project_id = google.auth.default(
        scopes=["https://www.googleapis.com/auth/playdeveloperreporting"]
    )
    return creds


def build_query_body(
    metric_set_config: Dict[str, Any],
    metrics: List[str],
    dimensions: List[str],
    days: int,
    page_size: int,
) -> Dict[str, Any]:
    """Build the query request body."""
    # Try to get the most recent data, will auto-retry with older dates if needed
    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    return {
        "timelineSpec": {
            "aggregationPeriod": "DAILY",
            "startTime": {
                "year": start_date.year,
                "month": start_date.month,
                "day": start_date.day,
            },
            "endTime": {
                "year": end_date.year,
                "month": end_date.month,
                "day": end_date.day,
            },
        },
        "metrics": metrics,
        "dimensions": dimensions,
        "pageSize": page_size,
    }


def query_vitals(
    service,
    package_name: str,
    metric_set_config: Dict[str, Any],
    body: Dict[str, Any],
    max_retries: int = 5,
) -> Dict[str, Any]:
    """Query the vitals API with automatic retry for freshness errors.

    Handles pagination via ``nextPageToken`` so that all rows are returned
    regardless of ``pageSize``.
    """
    metric_set_name = f"apps/{package_name}/{metric_set_config['metric_set_suffix']}"
    endpoint_name = metric_set_config["endpoint"]

    # Get the endpoint dynamically
    endpoint = getattr(service.vitals(), endpoint_name)()

    all_rows: List[Dict[str, Any]] = []
    page_token: Optional[str] = None
    first_response: Optional[Dict[str, Any]] = None

    while True:
        request_body = dict(body)
        if page_token:
            request_body["pageToken"] = page_token

        # Try querying with progressively older dates if we hit freshness errors
        response = None
        for retry in range(max_retries):
            try:
                response = endpoint.query(
                    name=metric_set_name, body=request_body
                ).execute()
                break
            except Exception as e:
                error_str = str(e)
                if (
                    "timeline_spec.start_date" in error_str
                    or "timeline_spec.end_date" in error_str
                    or "freshness" in error_str
                ):
                    if "startTime" in request_body["timelineSpec"]:
                        start = request_body["timelineSpec"]["startTime"]
                        start_date = date(
                            start["year"], start["month"], start["day"]
                        )
                        new_start = start_date - timedelta(days=1)
                        request_body["timelineSpec"]["startTime"] = {
                            "year": new_start.year,
                            "month": new_start.month,
                            "day": new_start.day,
                        }
                        # Update the original body too so subsequent pages
                        # use the same adjusted dates
                        body["timelineSpec"]["startTime"] = request_body[
                            "timelineSpec"
                        ]["startTime"]

                    if "endTime" in request_body["timelineSpec"]:
                        end = request_body["timelineSpec"]["endTime"]
                        end_date = date(
                            end["year"], end["month"], end["day"]
                        )
                        new_end = end_date - timedelta(days=1)
                        request_body["timelineSpec"]["endTime"] = {
                            "year": new_end.year,
                            "month": new_end.month,
                            "day": new_end.day,
                        }
                        body["timelineSpec"]["endTime"] = request_body[
                            "timelineSpec"
                        ]["endTime"]

                    if retry < max_retries - 1:
                        print(
                            "Data not yet available, trying 1 day earlier...",
                            file=sys.stderr,
                        )
                        continue

                raise e

        if response is None:
            raise Exception("Failed to query after multiple retries")

        if first_response is None:
            first_response = response

        all_rows.extend(response.get("rows", []))

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    # Return the first response structure with all rows merged
    if first_response is not None:
        first_response["rows"] = all_rows
    else:
        first_response = {"rows": []}
    return first_response


def filter_and_sort_rows(
    rows: List[Dict[str, Any]],
    top_n: Optional[int] = None,
    min_users: Optional[int] = None,
    exclude_zero: bool = False,
    version_codes: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Filter and sort result rows."""

    # Helper to extract the integer versionCode from a row
    def _get_vc(row):
        for dim in row.get("dimensions", []):
            if dim["dimension"] == "versionCode":
                try:
                    return int(
                        dim.get("stringValue") or dim.get("int64Value", 0)
                    )
                except (ValueError, TypeError):
                    pass
        return 0

    # Drop builds older than MIN_VERSION_CODE (pre-2026)
    filtered_rows = [
        row for row in rows if _get_vc(row) >= MIN_VERSION_CODE
    ]

    # Filter by specific version codes
    if version_codes:
        version_codes_set = set(version_codes)
        filtered_rows = [
            row
            for row in filtered_rows
            if any(
                d["dimension"] == "versionCode"
                and (
                    d.get("stringValue") in version_codes_set
                    or str(d.get("int64Value")) in version_codes_set
                )
                for d in row.get("dimensions", [])
            )
        ]

    # Filter by minimum users
    if min_users is not None:
        filtered_rows = [
            row
            for row in filtered_rows
            if any(
                m["metric"] == "distinctUsers"
                and "decimalValue" in m
                and float(m["decimalValue"]["value"]) >= min_users
                for m in row.get("metrics", [])
            )
        ]

    # Exclude rows where all rate metrics are zero
    if exclude_zero:
        filtered_rows = [
            row
            for row in filtered_rows
            if any(
                ("Rate" in m["metric"] or "rate" in m["metric"])
                and "decimalValue" in m
                and float(m["decimalValue"]["value"]) > 0
                for m in row.get("metrics", [])
            )
        ]

    # Sort by build date (descending) decoded from version code.
    # This ensures correct ordering across both the v1 and Gradle
    # version code schemes.
    def get_build_timestamp(row):
        for dim in row.get("dimensions", []):
            if dim["dimension"] == "versionCode":
                try:
                    vc = int(
                        dim.get("stringValue") or dim.get("int64Value", 0)
                    )
                    _bid, _arch, build_dt = reverse_version_code(vc)
                    return build_dt.timestamp()
                except (ValueError, TypeError):
                    return 0.0
        return 0.0

    filtered_rows.sort(key=get_build_timestamp, reverse=True)

    # Limit to top N
    if top_n is not None and top_n > 0:
        filtered_rows = filtered_rows[:top_n]

    return filtered_rows


def format_metric_value(metric: Dict[str, Any], metric_name: str) -> str:
    """Format a metric value for display."""
    if "decimalValue" in metric:
        value = float(metric["decimalValue"]["value"])
        # If it's a rate metric (not distinctUsers), format as percentage
        if "Rate" in metric_name or "rate" in metric_name.lower():
            return f"{value * 100:.2f}%"
        # For user counts, format as integer with commas
        elif "Users" in metric_name or "users" in metric_name.lower():
            return f"{int(value):,}"
        else:
            return f"{value:.4f}"
    elif "int64Value" in metric:
        return str(metric["int64Value"])
    return "N/A"


def output_pretty(
    response: Dict[str, Any],
    metric_set_config: Dict[str, Any],
    package_name: str,
    days: int,
    top_n: int = None,
    min_users: int = None,
    exclude_zero: bool = False,
    version_codes: List[str] = None,
    resolver: Optional[VersionResolver] = None,
):
    """Output results in pretty tabular format."""
    from tabulate import tabulate

    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    print(
        f"\n{metric_set_config['display_name']} — {package_name} (last {days} day(s))\n"
    )

    rows = response.get("rows", [])
    if not rows:
        print("No data available for the specified time period.\n")
        return

    # Apply filters and sorting
    rows = filter_and_sort_rows(rows, top_n, min_users, exclude_zero, version_codes)

    if not rows:
        print("No data matches the specified filters.\n")
        return

    # Build table rows
    table_rows = []
    for row in rows:
        # Extract date from startTime if available
        start_time = row.get("startTime", {})
        row_date = ""
        if start_time:
            row_date = f"{start_time.get('year', '')}-{start_time.get('month', ''):02d}-{start_time.get('day', ''):02d}"

        # Extract dimensions
        dim_values = {}
        for d in row.get("dimensions", []):
            dim_values[d["dimension"]] = d.get(
                "stringValue", d.get("int64Value", "unknown")
            )

        # Extract metrics
        metric_values = {}
        for m in row.get("metrics", []):
            metric_values[m["metric"]] = format_metric_value(m, m["metric"])

        # Build the table row
        table_row = []
        if row_date:
            table_row.append(row_date)
        for dim_name in sorted(dim_values.keys()):
            table_row.append(dim_values[dim_name])

        # Insert resolved version columns after dimensions
        if resolver and "versionCode" in dim_values:
            try:
                vc = int(dim_values["versionCode"])
                version_name, arch = resolver.resolve(vc)
                table_row.append(version_name)
                table_row.append(arch)
            except (ValueError, TypeError):
                table_row.extend(["unknown", "unknown"])

        for metric_name in metric_set_config["metrics"]:
            if metric_name in metric_values:
                table_row.append(metric_values[metric_name])

        table_rows.append(table_row)

    # Build headers
    headers = []
    # Check if we have dates
    first_row = rows[0]
    if first_row.get("startTime"):
        headers.append("date")
    dim_names = sorted(
        d["dimension"] for d in first_row.get("dimensions", [])
    )
    headers.extend(dim_names)
    if resolver and "versionCode" in dim_names:
        headers.extend(["firefoxVersion", "cpuArch"])
    headers.extend(
        m for m in metric_set_config["metrics"]
        if any(
            met["metric"] == m for met in first_row.get("metrics", [])
        )
    )

    print(tabulate(table_rows, headers=headers))


def output_csv(
    response: Dict[str, Any],
    metric_set_config: Dict[str, Any],
    package_name: str,
    top_n: int = None,
    min_users: int = None,
    exclude_zero: bool = False,
    version_codes: List[str] = None,
    resolver: Optional[VersionResolver] = None,
):
    """Output results in CSV format."""
    import csv
    import sys

    rows = response.get("rows", [])
    if not rows:
        print("No data available.", file=sys.stderr)
        return

    # Apply filters and sorting
    rows = filter_and_sort_rows(rows, top_n, min_users, exclude_zero, version_codes)

    if not rows:
        print("No data matches the specified filters.", file=sys.stderr)
        return

    # Collect all dimension and metric names
    first_row = rows[0]
    dimension_names = [d["dimension"] for d in first_row.get("dimensions", [])]
    metric_names = [m["metric"] for m in first_row.get("metrics", [])]

    # Build header — insert version/arch columns after dimensions if resolving
    extra_headers = ["firefoxVersion", "cpuArch"] if resolver else []
    writer = csv.writer(sys.stdout)
    writer.writerow(dimension_names + extra_headers + metric_names)

    # Write data rows
    for row in rows:
        dim_values = [
            d.get("stringValue", d.get("int64Value", ""))
            for d in row.get("dimensions", [])
        ]

        extra_values = []
        if resolver:
            # Try to resolve the versionCode dimension
            vc_str = None
            for d in row.get("dimensions", []):
                if d["dimension"] == "versionCode":
                    vc_str = d.get("stringValue", d.get("int64Value"))
                    break
            if vc_str is not None:
                try:
                    version_name, arch = resolver.resolve(int(vc_str))
                    extra_values = [version_name, arch]
                except (ValueError, TypeError):
                    extra_values = ["unknown", "unknown"]
            else:
                extra_values = ["", ""]

        metric_values = [
            format_metric_value(m, m["metric"]) for m in row.get("metrics", [])
        ]
        writer.writerow(dim_values + extra_values + metric_values)


def output_json(response: Dict[str, Any]):
    """Output results in JSON format."""
    import json

    print(json.dumps(response, indent=2))


# ---------------------------------------------------------------------------
# Anomaly detection
# ---------------------------------------------------------------------------

METRIC_SET_LABELS = {
    "anrRateMetricSet": "ANR Rate",
    "crashRateMetricSet": "Crash Rate",
    "excessiveWakeupRateMetricSet": "Excessive Wakeup Rate",
    "stuckBackgroundWakelockRateMetricSet": "Stuck BG Wakelock Rate",
}


def query_anomalies(
    service,
    package_name: str,
    days: int,
) -> List[Dict[str, Any]]:
    """List anomalies for a package, filtered to the last *days* days."""
    start_dt = datetime.now(UTC) - timedelta(days=days)
    start_rfc = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    filter_str = f'activeBetween("{start_rfc}", UNBOUNDED)'

    parent = f"apps/{package_name}"
    all_anomalies: List[Dict[str, Any]] = []
    page_token: Optional[str] = None

    while True:
        req = service.anomalies().list(
            parent=parent,
            filter=filter_str,
            pageSize=100,
            **({"pageToken": page_token} if page_token else {}),
        )
        resp = req.execute()
        all_anomalies.extend(resp.get("anomalies", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return all_anomalies


def output_anomalies(
    anomalies: List[Dict[str, Any]],
    package_name: str,
    days: int,
    resolver: Optional["VersionResolver"] = None,
):
    """Pretty-print anomalies."""
    from tabulate import tabulate

    if not anomalies:
        print(f"\nNo anomalies detected for {package_name} in the last {days} day(s).\n")
        return

    headers = ["startDate", "endDate", "metricSet", "metric", "value"]
    if resolver:
        headers.extend(["firefoxVersion", "cpuArch"])
    rows = []

    for a in anomalies:
        ts = a.get("timelineSpec", {})
        start = ts.get("startTime", {})
        end = ts.get("endTime", {})
        start_str = f"{start.get('year', '?')}-{start.get('month', '?'):02d}-{start.get('day', '?'):02d}"
        end_str = f"{end.get('year', '?')}-{end.get('month', '?'):02d}-{end.get('day', '?'):02d}"

        metric_set_full = a.get("metricSet", "")
        # Extract the short label: "apps/com.foo/crashRateMetricSet" -> "Crash Rate"
        ms_key = metric_set_full.rsplit("/", 1)[-1] if "/" in metric_set_full else metric_set_full
        ms_label = METRIC_SET_LABELS.get(ms_key, ms_key)

        metric_info = a.get("metric", {})
        metric_name = metric_info.get("metric", "")
        raw_val = metric_info.get("decimalValue", {}).get("value", "")
        try:
            display_val = f"{float(raw_val) * 100:.2f}%"
        except (ValueError, TypeError):
            display_val = raw_val

        row = [start_str, end_str, ms_label, metric_name, display_val]

        # Resolve version from dimensions if present
        if resolver:
            dims = a.get("dimensions", [])
            version_name, arch = "", ""
            for d in dims:
                if d.get("dimension") == "versionCode":
                    try:
                        vc = int(
                            d.get("stringValue") or d.get("int64Value", 0)
                        )
                        version_name, arch = resolver.resolve(vc)
                    except (ValueError, TypeError):
                        pass
            row.extend([version_name, arch])

        rows.append(row)

    # Sort by start date descending
    rows.sort(key=lambda r: r[0], reverse=True)

    title = f"Anomalies — {package_name} (last {days} day(s))"
    print(f"\n{title}\n")
    print(tabulate(rows, headers=headers, tablefmt="simple"))
    print()


def main():
    """Main entry point."""
    args = parse_args()

    try:
        # Authenticate and build service
        creds = authenticate()
        service = build("playdeveloperreporting", "v1beta1", credentials=creds)

        # Set up version resolver if requested
        if args.resolve_versions:
            is_beta = "beta" in args.package
            resolver = VersionResolver(include_betas=is_beta)
        else:
            resolver = None

        # --- Anomalies mode ---
        if args.anomalies:
            anomalies = query_anomalies(service, args.package, args.days)
            if args.output_format == "json":
                output_json({"anomalies": anomalies})
            else:
                output_anomalies(
                    anomalies, args.package, args.days, resolver
                )
            return

        # --- Metric set query mode ---

        # Get metric set configuration
        metric_set_config = METRIC_SETS[args.metric_set]

        # Determine which metrics to query
        metrics = args.metrics if args.metrics else metric_set_config["metrics"]

        # Validate metrics
        available_metrics = metric_set_config["metrics"]
        invalid_metrics = [m for m in metrics if m not in available_metrics]
        if invalid_metrics:
            print(
                f"Error: Invalid metrics for {args.metric_set}: {', '.join(invalid_metrics)}",
                file=sys.stderr,
            )
            print(
                f"Available metrics: {', '.join(available_metrics)}",
                file=sys.stderr,
            )
            sys.exit(1)

        # Build query
        body = build_query_body(
            metric_set_config, metrics, args.dimensions, args.days, args.page_size
        )

        # Execute query
        response = query_vitals(service, args.package, metric_set_config, body)

        # Parse version codes if provided
        version_codes = None
        if args.version_code:
            version_codes = [vc.strip() for vc in args.version_code.split(",")]

        # Output results
        if args.output_format == "pretty":
            output_pretty(
                response,
                metric_set_config,
                args.package,
                args.days,
                args.top,
                args.min_users,
                args.exclude_zero,
                version_codes,
                resolver,
            )
        elif args.output_format == "csv":
            output_csv(
                response,
                metric_set_config,
                args.package,
                args.top,
                args.min_users,
                args.exclude_zero,
                version_codes,
                resolver,
            )
        elif args.output_format == "json":
            output_json(response)

    except google.auth.exceptions.DefaultCredentialsError:
        print(
            "Error: Authentication failed. Please run:",
            file=sys.stderr,
        )
        print(
            "  gcloud auth application-default login --scopes=https://www.googleapis.com/auth/playdeveloperreporting",
            file=sys.stderr,
        )
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
