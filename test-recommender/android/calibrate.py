"""
Recompute the measurements the tuning constants rest on.

    python3 -m android.calibrate --repo /path/to/firefox

Every threshold in this package — the budget tiers, `MATERIAL_CHURN`, the
decision to treat a quiet app diff as normal rather than exceptional — came
from measuring real ranges. Those measurements used to be quoted in module
docstrings, where they rotted: a TestRail re-export or a new cycle silently
turned them into confident-sounding lies, and they had to be hand-corrected
four times in the first month.

So the numbers live here instead, and are regenerated on demand. Run this
after a re-export, after a new cycle ships, or whenever a constant looks
wrong, and compare the output against the constants it justifies.

Nothing in the pipeline imports this module; it is a measuring instrument,
not a dependency.
"""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path
from typing import Optional

from android import budget as bd
from android.build_mapping import (
    MAX_DEPTH, MAX_SECTION_SIZE, TEST_CLASS_MODULES, assign_section_keys,
)
from android.change_extractor import (
    beta_pairs, extract_range, latest_beta, list_tags, resolve_rc,
)
from android.gecko_risk import MATERIAL_CHURN, extract_gecko_risk
from android.testrail_index import build_index

HERE = Path(__file__).parent
DEFAULT_EXPORT = HERE / "config/testrail_export_android.xlsx"


def _ranges(repo: str, cycles: list[int]) -> list[tuple[str, str, str]]:
    """Every beta-to-beta pair plus each final-beta-to-RC, in order."""
    out: list[tuple[str, str, str]] = []
    for major in cycles:
        for a, b in beta_pairs(repo, major):
            out.append((a.raw, b.raw, f"{major} b{a.beta}->b{b.beta}"))
        last, rc = latest_beta(repo, major), resolve_rc(repo, major)
        if last and rc:
            out.append((last.raw, rc.raw, f"{major} b{last.beta}->RC"))
    return out


def _discover_cycles(repo: str) -> list[int]:
    return sorted({t.major for t in list_tags(repo)})


def measure_ranges(repo: str, cycles: list[int], index) -> list[dict]:
    rows = []
    for base, head, label in _ranges(repo, cycles):
        extraction = extract_range(repo, base, head)
        risk = extract_gecko_risk(repo, base, head)
        categories = extraction.counts_by_category()
        ui_tests = [f.path for f in extraction.files if f.category == "test_ui"]
        exact = index.cases_for_files(ui_tests) if index else set()
        signal = bd.from_extraction(extraction, risk, len(exact))
        rows.append({
            "label": label,
            "files": len(extraction.files),
            "product": categories.get("code", 0),
            "test_ui": categories.get("test_ui", 0),
            "test_unit": categories.get("test_unit", 0),
            "bugs": len(extraction.bugs),
            "exact": len(exact),
            "engine_files": risk.product_file_count,
            "engine_churn": risk.product_churn,
            "material": risk.is_material,
            "tier": bd.detect_tier(signal),
            "veto": risk.vetoes_no_regression(signal.app_product_files > 0),
            "phantoms": len(extraction.phantom_commits),
            "unattributed": len(extraction.unattributed),
        })
    return rows


def _pct(n: int, total: int) -> str:
    return f"{n}/{total} ({100 * n / total:.0f}%)" if total else "0/0"


def report_ranges(rows: list[dict]) -> None:
    if not rows:
        print("No ranges found. Fetch the repo, or pass --cycles explicitly.")
        return
    total = len(rows)
    print(f"## Change profile — {total} ranges\n")
    print(f"{'range':14s} {'files':>5s} {'prod':>4s} {'bugs':>4s} "
          f"{'exact':>5s} {'eng_f':>5s} {'eng_ln':>7s} {'tier':12s} veto")
    for r in rows:
        print(f"{r['label']:14s} {r['files']:5d} {r['product']:4d} "
              f"{r['bugs']:4d} {r['exact']:5d} {r['engine_files']:5d} "
              f"{r['engine_churn']:7d} {r['tier']:12s} {r['veto']}")

    product = [r["product"] for r in rows]
    print()
    print(f"  product files .... min {min(product)} / max {max(product)}")
    print(f"  zero product ..... {_pct(sum(1 for p in product if p == 0), total)}"
          "   <- justifies the engine_only tier")
    print(f"  <= 3 product ..... {_pct(sum(1 for p in product if p <= 3), total)}")
    print(f"  exact-match hits . {_pct(sum(1 for r in rows if r['exact']), total)}")
    print(f"  phantom commits .. {sum(r['phantoms'] for r in rows)}")
    print(f"  unattributed ..... {sum(r['unattributed'] for r in rows)}"
          "   <- should be 0")

    tiers: dict[str, int] = {}
    for r in rows:
        tiers[r["tier"]] = tiers.get(r["tier"], 0) + 1
    print(f"  tiers ............ {tiers}")


def report_engine(rows: list[dict]) -> None:
    churn = [r["engine_churn"] for r in rows if r["engine_churn"]]
    if not churn:
        return
    q = statistics.quantiles(churn, n=4) if len(churn) > 3 else [0, 0, 0]
    print(f"\n## Engine churn — MATERIAL_CHURN is {MATERIAL_CHURN}\n")
    print(f"  min {min(churn)} / p25 {int(q[0])} / median "
          f"{int(statistics.median(churn))} / p75 {int(q[2])} / max {max(churn)}")

    quiet = [r for r in rows if r["product"] == 0]
    fired = [r for r in quiet if r["veto"]]
    print(f"\n  The threshold only decides anything where the app is quiet:")
    print(f"    quiet ranges ... {len(quiet)}")
    print(f"    veto fires ..... {len(fired)}")
    print(f"    veto silent .... {len(quiet) - len(fired)}  "
          f"(churn: {sorted(r['engine_churn'] for r in quiet if not r['veto'])})")
    if quiet and (not fired or len(fired) == len(quiet)):
        print("    WARNING: the veto does not discriminate on this sample — "
              "retune MATERIAL_CHURN.")


def report_testrail(index, repo: str) -> None:
    cases = index.cases
    total = len(cases)
    drift = index.drift
    print(f"\n## TestRail index — {total} cases\n")
    print(f"  mapped to code ... {_pct(len(index.case_to_files), total)}")
    print(f"  @Test methods .... {len(index.methods)}")

    automation: dict[str, int] = {}
    for case in cases.values():
        automation[case.automation or "(blank)"] = \
            automation.get(case.automation or "(blank)", 0) + 1
    print(f"  automation ....... {automation}")

    print(f"\n  drift (all actionable):")
    print(f"    stale declared ......... {len(drift.stale_declared)}")
    print(f"    orphan links ........... {len(drift.orphan_links)}")
    print(f"    unparseable cells ...... {len(drift.unparseable_declared)}")
    print(f"    automation mismatch .... {len(drift.automation_status_mismatch)}"
          "   <- inflated by a stale export")
    print(f"    malformed @Test ........ {len(drift.malformed_methods)}"
          "   <- usually a dirty working tree")

    linked = {}
    for case_id, files in index.case_to_files.items():
        for path in files:
            name = Path(path).stem
            linked[name] = linked.get(name, 0) + 1
    uncurated = [c for c in linked if c not in TEST_CLASS_MODULES]
    pairs = sum(linked.values())
    covered = sum(n for c, n in linked.items() if c in TEST_CLASS_MODULES)
    print(f"\n  test classes with linked cases .. {len(linked)}")
    print(f"  covered by TEST_CLASS_MODULES ... {_pct(covered, pairs)} of pairs")
    if uncurated:
        print(f"  NOT in TEST_CLASS_MODULES ....... {sorted(uncurated)}")


def report_sections(index) -> None:
    keys = assign_section_keys(list(index.cases.values()))
    sizes: dict[str, int] = {}
    for section in keys.values():
        sizes[section] = sizes.get(section, 0) + 1
    over = {n: s for n, s in sizes.items() if s > MAX_SECTION_SIZE}
    print(f"\n## Sections at adaptive depth\n")
    print(f"  sections ......... {len(sizes)}")
    print(f"  target max ....... {MAX_SECTION_SIZE} (descending to depth {MAX_DEPTH})")
    print(f"  actual max ....... {max(sizes.values())}")
    if over:
        print(f"  over target ...... {len(over)} — already at depth {MAX_DEPTH}, "
              f"so they cannot be split further. Not a failure; raise "
              f"MAX_DEPTH only if the deeper names are still meaningful.")
    for name, n in sorted(sizes.items(), key=lambda kv: -kv[1])[:5]:
        print(f"    {n:4d}  {name}")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--export", default=str(DEFAULT_EXPORT))
    parser.add_argument("--cycles", type=int, nargs="*",
                        help="major versions to measure (default: all tagged)")
    parser.add_argument("--skip-ranges", action="store_true",
                        help="TestRail/section stats only; skips the slow part")
    args = parser.parse_args(argv)

    export = Path(args.export)
    index = None
    if export.exists():
        index = build_index(export, args.repo)
    else:
        sys.stderr.write(f"[calibrate] no export at {export}; "
                         f"skipping TestRail stats\n")

    if not args.skip_ranges:
        cycles = args.cycles or _discover_cycles(args.repo)
        rows = measure_ranges(args.repo, cycles, index)
        report_ranges(rows)
        report_engine(rows)

    if index:
        report_testrail(index, args.repo)
        report_sections(index)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
