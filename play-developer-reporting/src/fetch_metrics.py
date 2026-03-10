#!/usr/bin/env python3
"""
Query Google Play Developer Reporting API for various vitals metrics.

Requires authentication:
  gcloud auth application-default login --scopes=https://www.googleapis.com/auth/playdeveloperreporting
"""

import argparse
import calendar
import csv
import json
import os
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from typing import Any

import google.auth
from google.oauth2 import service_account
from googleapiclient.discovery import build
from tabulate import tabulate


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
MOBILE_DETAILS_URL = "https://product-details.mozilla.org/1.0/mobile_details.json"
REPORTING_SCOPE = "https://www.googleapis.com/auth/playdeveloperreporting"

# Pre-computed UTC epoch for the V1 version code cutoff date.
_V1_CUTOFF_EPOCH: int = calendar.timegm(
    time.strptime(str(V1_CUTOFF), "%Y%m%d%H%M%S")
)


def reverse_version_code(version_code: int) -> tuple[str, str, datetime]:
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

    build_dt = datetime.fromtimestamp(
        _V1_CUTOFF_EPOCH + hours * 3600, tz=timezone.utc
    )
    build_id = build_dt.strftime("%Y%m%d%H%M%S")

    return build_id, arch, build_dt


def fetch_release_versions(
    include_betas: bool = False,
) -> list[tuple[date, str]]:
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
    releases: list[tuple[date, str]],
    nightly_version: str | None = None,
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
    for rel_date, version in releases:
        if rel_date >= build_d:
            return version

    # Build is newer than all known releases — use nightly version if
    # available (for org.mozilla.fenix), otherwise infer next major.
    if nightly_version:
        return nightly_version
    if releases:
        latest_version = releases[-1][1]
        try:
            major = int(latest_version.split(".")[0])
            return f"{major + 1}.0b"
        except (ValueError, IndexError):
            return latest_version
    return "unknown"


def fetch_nightly_version() -> str | None:
    """Fetch the current Firefox nightly version from mobile_details.json."""
    try:
        with urllib.request.urlopen(MOBILE_DETAILS_URL, timeout=15) as resp:
            data = json.loads(resp.read())
        return data.get("nightly_version") or data.get("alpha_version")
    except Exception:
        return None


def build_nightly_timeline(
    releases: list[tuple[date, str]],
    current_nightly: str | None,
) -> list[tuple[date, str]]:
    """Build a timeline of nightly version transitions from beta b1 dates.

    When X.0b1 is released, nightly bumps from X.0a1 to (X+1).0a1.
    Returns a sorted list of (merge_date, nightly_version) where each
    entry means "from this date onward, nightly was this version".
    """
    # Find all b1 releases — each marks when nightly bumped to the next major
    b1_dates = {}  # major -> date
    for rel_date, version in releases:
        if "b1" in version and version.endswith("b1"):
            try:
                major = int(version.split(".")[0])
                b1_dates[major] = rel_date
            except (ValueError, IndexError):
                continue

    # Build timeline: when X.0b1 ships on date D, nightly becomes (X+1).0a1
    timeline = []
    for major, merge_date in sorted(b1_dates.items()):
        nightly_version = f"{major + 1}.0a1"
        timeline.append((merge_date, nightly_version))

    # If we have the current nightly version but it's not yet in the timeline
    # (the latest b1 hasn't been released yet), add it using the last known
    # merge date or today as fallback
    if current_nightly and timeline:
        latest_in_timeline = timeline[-1][1]
        if current_nightly != latest_in_timeline:
            # Current nightly is newer — the merge must have happened
            # after the last b1 we know about. Use the last b1 date
            # as an approximation (it's close enough).
            try:
                current_major = int(current_nightly.split(".")[0])
                prev_b1_major = current_major - 1
                if prev_b1_major in b1_dates:
                    timeline.append((b1_dates[prev_b1_major], current_nightly))
                    timeline.sort(key=lambda x: x[0])
            except (ValueError, IndexError):
                pass

    return timeline


def resolve_nightly_version(
    build_dt: datetime,
    timeline: list[tuple[date, str]],
    current_nightly: str | None,
) -> str:
    """Resolve a nightly build timestamp to its nightly version.

    Walks the timeline backwards to find which nightly cycle the build
    belongs to.
    """
    build_d = build_dt.date()

    # Walk backwards through timeline to find the matching cycle
    for merge_date, nightly_version in reversed(timeline):
        if build_d >= merge_date:
            return nightly_version

    # Build is older than our timeline — fall back to current or unknown
    return current_nightly or "unknown"


class VersionResolver:
    """Lazily resolves version codes to human-readable Firefox versions."""

    def __init__(self, include_betas: bool = False, package: str = ""):
        self._releases: list[tuple[date, str]] | None = None
        self._include_betas = include_betas
        self._package = package
        self._nightly_version: str | None = None
        self._nightly_timeline: list[tuple[date, str]] | None = None

    def _ensure_releases(self):
        if self._releases is None:
            # For nightly, always fetch betas too (needed for merge dates)
            include_betas = self._include_betas or self._package == "org.mozilla.fenix"
            self._releases = fetch_release_versions(include_betas=include_betas)

            if self._package == "org.mozilla.fenix":
                self._nightly_version = fetch_nightly_version()
                self._nightly_timeline = build_nightly_timeline(
                    self._releases, self._nightly_version
                )

    def resolve(self, version_code: int) -> tuple[str, str]:
        """Return (version_name, cpu_arch) for a version code."""
        self._ensure_releases()
        try:
            _build_id, arch, build_dt = reverse_version_code(version_code)

            # For nightly, use the merge-date timeline
            if self._package == "org.mozilla.fenix" and self._nightly_timeline:
                version = resolve_nightly_version(
                    build_dt, self._nightly_timeline, self._nightly_version
                )
                return version, arch

            version = resolve_version_name(
                build_dt, self._releases, self._nightly_version
            )
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
    "lmkrate": {
        "endpoint": "lmkrate",
        "metric_set_suffix": "lmkRateMetricSet",
        "metrics": [
            "userPerceivedLmkRate",
            "userPerceivedLmkRate7dUserWeighted",
            "userPerceivedLmkRate28dUserWeighted",
            "distinctUsers",
        ],
        "display_name": "Low Memory Kill Rate",
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
    """Authenticate with Google Cloud.

    Checks GOOGLE_SA_VITALS_JSON first (CI/production — service account key
    JSON as a string). Falls back to ADC for local development.
    """
    raw = os.environ.get("GOOGLE_SA_VITALS_JSON")
    if raw:
        info = json.loads(raw)
        return service_account.Credentials.from_service_account_info(
            info, scopes=[REPORTING_SCOPE]
        )
    creds, _ = google.auth.default(scopes=[REPORTING_SCOPE])
    return creds


def build_query_body(
    metrics: list[str],
    dimensions: list[str],
    days: int,
    page_size: int,
) -> dict[str, Any]:
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
    metric_set_config: dict[str, Any],
    body: dict[str, Any],
    max_retries: int = 5,
) -> dict[str, Any]:
    """Query the vitals API with automatic retry for freshness errors.

    Handles pagination via ``nextPageToken`` so that all rows are returned
    regardless of ``pageSize``.
    """
    metric_set_name = f"apps/{package_name}/{metric_set_config['metric_set_suffix']}"
    endpoint_name = metric_set_config["endpoint"]

    # Get the endpoint dynamically
    endpoint = getattr(service.vitals(), endpoint_name)()

    all_rows: list[dict[str, Any]] = []
    page_token: str | None = None
    first_response: dict[str, Any] | None = None

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

                raise

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
    rows: list[dict[str, Any]],
    top_n: int | None = None,
    min_users: int | None = None,
    exclude_zero: bool = False,
    version_codes: list[str] | None = None,
) -> list[dict[str, Any]]:
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
                "rate" in m["metric"].lower()
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


def format_metric_value(metric: dict[str, Any], metric_name: str) -> str:
    """Format a metric value for display."""
    if "decimalValue" in metric:
        value = float(metric["decimalValue"]["value"])
        # If it's a rate metric (not distinctUsers), format as percentage
        if "rate" in metric_name.lower():
            return f"{value * 100:.2f}%"
        # For user counts, format as integer with commas
        elif "users" in metric_name.lower():
            return f"{int(value):,}"
        else:
            return f"{value:.4f}"
    elif "int64Value" in metric:
        return str(metric["int64Value"])
    return "N/A"


def output_pretty(
    response: dict[str, Any],
    metric_set_config: dict[str, Any],
    package_name: str,
    days: int,
    top_n: int | None = None,
    min_users: int | None = None,
    exclude_zero: bool = False,
    version_codes: list[str] | None = None,
    resolver: VersionResolver | None = None,
):
    """Output results in pretty tabular format."""

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

    # Compute total distinct users for userShare calculation
    total_users = 0
    for row in rows:
        for m in row.get("metrics", []):
            if m["metric"] == "distinctUsers" and "decimalValue" in m:
                total_users += float(m["decimalValue"]["value"])

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

        # Compute user share
        row_users = 0
        for m in row.get("metrics", []):
            if m["metric"] == "distinctUsers" and "decimalValue" in m:
                row_users = float(m["decimalValue"]["value"])
        user_share = f"{row_users / total_users * 100:.1f}%" if total_users > 0 else "N/A"

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

        table_row.append(user_share)
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
    headers.append("userShare")

    # Compute weighted aggregate summary row
    # Weighted average of rate metrics across all displayed versions
    rate_totals = {}  # metric_name -> weighted sum
    for row in rows:
        row_users = 0
        row_metrics = {}
        for m in row.get("metrics", []):
            if m["metric"] == "distinctUsers" and "decimalValue" in m:
                row_users = float(m["decimalValue"]["value"])
            elif "decimalValue" in m:
                row_metrics[m["metric"]] = float(m["decimalValue"]["value"])
        for mname, mval in row_metrics.items():
            rate_totals.setdefault(mname, 0.0)
            rate_totals[mname] += mval * row_users

    # Build summary row
    num_dim_cols = len(dim_names)
    if first_row.get("startTime"):
        num_dim_cols += 1  # date column
    if resolver and "versionCode" in dim_names:
        num_dim_cols += 2  # firefoxVersion, cpuArch

    summary_row = [""] * (num_dim_cols - 1) + ["AGGREGATE"]
    for metric_name in metric_set_config["metrics"]:
        if not any(met["metric"] == metric_name for met in first_row.get("metrics", [])):
            continue
        if metric_name == "distinctUsers":
            summary_row.append(f"{int(total_users):,}")
        elif total_users > 0 and metric_name in rate_totals:
            weighted_avg = rate_totals[metric_name] / total_users
            summary_row.append(f"{weighted_avg * 100:.2f}%")
        else:
            summary_row.append("N/A")
    summary_row.append("100.0%")

    table_rows.append([""] * len(headers))  # blank separator
    table_rows.append(summary_row)

    print(tabulate(table_rows, headers=headers))


def output_csv(
    response: dict[str, Any],
    metric_set_config: dict[str, Any],
    package_name: str,
    top_n: int | None = None,
    min_users: int | None = None,
    exclude_zero: bool = False,
    version_codes: list[str] | None = None,
    resolver: VersionResolver | None = None,
):
    """Output results in CSV format."""

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


def output_json(
    response: dict[str, Any],
    metric_set_config: dict[str, Any] | None = None,
    top_n: int | None = None,
    min_users: int | None = None,
    exclude_zero: bool = False,
    version_codes: list[str] | None = None,
    resolver: VersionResolver | None = None,
):
    """Output results in JSON format, with an aggregate summary."""

    rows = response.get("rows", [])
    if metric_set_config and rows:
        rows = filter_and_sort_rows(rows, top_n, min_users, exclude_zero, version_codes)

    # Inject resolved version info into each row
    if resolver:
        for row in rows:
            for d in row.get("dimensions", []):
                if d["dimension"] == "versionCode":
                    try:
                        vc = int(d.get("stringValue", d.get("int64Value", "0")))
                        version_name, arch = resolver.resolve(vc)
                        row["firefoxVersion"] = version_name
                        row["cpuArch"] = arch
                    except (ValueError, TypeError):
                        row["firefoxVersion"] = "unknown"
                        row["cpuArch"] = "unknown"

    # Compute aggregate weighted metrics
    total_users = 0
    rate_totals = {}  # metric_name -> weighted sum
    for row in rows:
        row_users = 0
        row_metrics = {}
        for m in row.get("metrics", []):
            if m["metric"] == "distinctUsers" and "decimalValue" in m:
                row_users = float(m["decimalValue"]["value"])
            elif "decimalValue" in m:
                row_metrics[m["metric"]] = float(m["decimalValue"]["value"])
        total_users += row_users
        for mname, mval in row_metrics.items():
            rate_totals.setdefault(mname, 0.0)
            rate_totals[mname] += mval * row_users

    aggregate = {"distinctUsers": total_users}
    for mname, weighted_sum in rate_totals.items():
        aggregate[mname] = weighted_sum / total_users if total_users > 0 else 0.0

    output = dict(response)
    if rows:
        output["rows"] = rows
    output["aggregate"] = aggregate

    print(json.dumps(output, indent=2))


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
) -> list[dict[str, Any]]:
    """List anomalies for a package, filtered to the last *days* days."""
    start_dt = datetime.now(timezone.utc) - timedelta(days=days)
    start_rfc = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    filter_str = f'activeBetween("{start_rfc}", UNBOUNDED)'

    parent = f"apps/{package_name}"
    all_anomalies: list[dict[str, Any]] = []
    page_token: str | None = None

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
    anomalies: list[dict[str, Any]],
    package_name: str,
    days: int,
    resolver: VersionResolver | None = None,
):
    """Pretty-print anomalies."""

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
            resolver = VersionResolver(include_betas=is_beta, package=args.package)
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
            metrics, args.dimensions, args.days, args.page_size
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
            output_json(
                response,
                metric_set_config,
                args.top,
                args.min_users,
                args.exclude_zero,
                version_codes,
                resolver,
            )

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