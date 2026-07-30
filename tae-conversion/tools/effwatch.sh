#!/usr/bin/env bash
# effwatch — run this ONCE on YOUR machine to close the conversion loop.
#
# It polls a shared queue folder; when Claude drops a build/run request, it runs effloop on YOUR
# toolchain + connected device and writes the reports back. Execution stays entirely on your side —
# this script only ever runs the fixed effloop command with a whitelisted test-class name; it never
# executes arbitrary text from the request file.
#
# Usage:  ./effwatch.sh            # then leave it running (device/emulator attached, adb on PATH)
# Stop:   Ctrl-C
#
# Protocol (both sides agree on this):
#   Claude writes  conversion-runs/_queue/<id>.request.json   = { "test_class": "...", "batch": "..." }
#   effwatch runs effloop, writes reports to conversion-runs/<batch>/, then
#            writes conversion-runs/_queue/<id>.done.json      = { id, test, batch, effloop_exit, reports, ts }
#   Claude polls for <id>.done.json, then reads the reports.
set -uo pipefail
TOOLS="$(cd "$(dirname "$0")" && pwd)"
RUNS="${RUNS:-$(cd "$TOOLS/.." && pwd)/conversion-runs}"   # default: tae-conversion/conversion-runs
QUEUE="$RUNS/_queue"
POLL="${POLL:-4}"
mkdir -p "$QUEUE"
field() { python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get(sys.argv[2],''))" "$1" "$2" 2>/dev/null; }

echo "effwatch: watching $QUEUE every ${POLL}s. Leave running. Ctrl-C to stop."
while true; do
  shopt -s nullglob
  for req in "$QUEUE"/*.request.json; do
    id="$(basename "$req" .request.json)"
    claimed="$QUEUE/$id.claimed"; done="$QUEUE/$id.done.json"
    mv "$req" "$claimed" 2>/dev/null || continue          # claim it (idempotent if two watchers)
    # ── git request? (has a "git" field) → effgit; else it's a test run → effloop ──
    GITACT="$(field "$claimed" git)"
    if [ -n "$GITACT" ]; then
      mkdir -p "$RUNS/_git"
      echo "effwatch: [$id] git: $GITACT"
      REPO="${REPO:-$HOME/Workspace/firefox}" RUNS="$RUNS" python3 "$TOOLS/effgit.py" "$claimed" "$RUNS/_git/$id.git-report.txt"; gx=$?
      printf '{ "id":"%s","kind":"git","action":"%s","exit":%s,"report":"conversion-runs/_git/%s.git-report.txt","ts":"%s" }\n' \
        "$id" "$GITACT" "$gx" "$id" "$(date -u +%FT%TZ)" > "$done"
      rm -f "$claimed"; echo "effwatch: [$id] git done → $(basename "$done")"; continue
    fi
    # ── bugzilla request? (has a "bug" field) → effbug (needs BUGZILLA_API_KEY in this shell) ──
    BUGACT="$(field "$claimed" bug)"
    if [ -n "$BUGACT" ]; then
      mkdir -p "$RUNS/_bug"
      echo "effwatch: [$id] bug: $BUGACT"
      RUNS="$RUNS" python3 "$TOOLS/effbug.py" "$claimed" "$RUNS/_bug/$id.bug-report.txt"; bx=$?
      printf '{ "id":"%s","kind":"bug","action":"%s","exit":%s,"report":"conversion-runs/_bug/%s.bug-report.txt","result":"conversion-runs/_bug/%s.bug-result.json","ts":"%s" }\n' \
        "$id" "$BUGACT" "$bx" "$id" "$id" "$(date -u +%FT%TZ)" > "$done"
      rm -f "$claimed"; echo "effwatch: [$id] bug done → $(basename "$done")"; continue
    fi
    CLASS="$(field "$claimed" test_class)"; BATCH="$(field "$claimed" batch)"
    BATCH="${BATCH:-adhoc}"
    if ! [[ "$CLASS" =~ ^[A-Za-z0-9_.#]+$ ]]; then     # allow FQN and #method targeting
      printf '{ "id":"%s","error":"invalid test_class" }\n' "$id" > "$done"; rm -f "$claimed"; continue
    fi
    [[ "$BATCH" =~ ^[A-Za-z0-9_-]+$ ]] || BATCH="adhoc"
    echo "effwatch: [$id] running $CLASS (batch=$BATCH)…"
    # optional mach_args passthrough (e.g. parameterized runs / effdump). Whitelisted chars only —
    # never contains shell metacharacters; passed as the MACH_ARGS env effloop already honors.
    MA="$(field "$claimed" mach_args)"
    if [ -n "$MA" ] && ! [[ "$MA" =~ ^[A-Za-z0-9\ ._=:/-]+$ ]]; then
      printf '{ "id":"%s","error":"invalid mach_args" }\n' "$id" > "$done"; rm -f "$claimed"; continue
    fi
    if [ -n "$MA" ]; then
      MACH_ARGS="$MA" "$TOOLS/effloop.sh" "$CLASS" "$BATCH"; exit_code=$?
    else
      "$TOOLS/effloop.sh" "$CLASS" "$BATCH"; exit_code=$?
    fi
    printf '{ "id":"%s","test":"%s","batch":"%s","effloop_exit":%s,"reports":"conversion-runs/%s","ts":"%s" }\n' \
      "$id" "$CLASS" "$BATCH" "$exit_code" "$BATCH" "$(date -u +%FT%TZ)" > "$done"
    rm -f "$claimed"
    echo "effwatch: [$id] done → $(basename "$done")"
  done
  sleep "$POLL"
done
