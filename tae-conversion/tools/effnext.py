#!/usr/bin/env python3
"""
effnext — pick the next legacy test(s) to convert, from LOCAL files only. No Google Sheet, no network.

Source of truth for "what to do next":
  - candidate pool : conversion-runs/testrail_smoke_pool.txt  (prioritized `Class.method<TAB>method` lines)
  - already done   : tools/converted_rows.csv                 (Class,Method,...,Converted,... rows)
The next candidate = first pool entry not marked Converted in converted_rows.csv.

converted_rows.csv is a fast snapshot and can lag reality (the campaign notes warn the "Converted" column is
not authoritative). This tool is only for cheaply *proposing* candidates; gate 1 (`effscaffold`) does the
authoritative "already exists in the efficiency package?" grep before you actually convert.

Usage:
  effnext.py [-n N] [--json]      # print the next N (default 1) unconverted candidates
Exit 0 always (unless files are missing).
"""
import csv, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
POOL = os.path.join(ROOT, "conversion-runs", "testrail_smoke_pool.txt")
DONE = os.path.join(HERE, "converted_rows.csv")


def load_done():
    done = set()
    if not os.path.isfile(DONE):
        return done
    with open(DONE, newline="", encoding="utf-8", errors="ignore") as f:
        for row in csv.DictReader(f):
            if (row.get("Converted") or "").strip().lower() == "converted":
                done.add((row.get("Class", "").strip(), row.get("Method", "").strip()))
    return done


def load_pool():
    out = []
    with open(POOL, encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            fq = line.split("\t")[0].strip()
            if "." not in fq:
                continue
            cls, method = fq.split(".", 1)
            out.append((cls.strip(), method.strip(), fq))
    return out


def main():
    args = sys.argv[1:]
    as_json = "--json" in args
    args = [a for a in args if a != "--json"]
    n = 1
    if "-n" in args:
        i = args.index("-n")
        try:
            n = int(args[i + 1])
        except (IndexError, ValueError):
            print("usage: effnext.py [-n N] [--json]"); sys.exit(2)

    for p in (POOL, DONE):
        if not os.path.isfile(p):
            msg = f"missing required file: {p}"
            print(json.dumps({"tool": "effnext", "ok": False, "error": msg}) if as_json else f"✖ {msg}")
            sys.exit(1)

    done = load_done()
    pool = load_pool()
    pending = [(c, m, fq) for (c, m, fq) in pool if (c, m) not in done]
    picks = pending[:n]

    if as_json:
        print(json.dumps({
            "tool": "effnext", "ok": True,
            "pool_total": len(pool), "done": len(done), "pending": len(pending),
            "next": [{"class": c, "method": m, "fqmethod": fq} for (c, m, fq) in picks],
        }))
    else:
        print(f"effnext — {len(pending)} pending / {len(pool)} pool ({len(done)} converted)")
        for c, m, fq in picks:
            print(f"  → {fq}")
        if not picks:
            print("  (nothing pending — pool exhausted or all marked converted)")
    sys.exit(0)


if __name__ == "__main__":
    main()
