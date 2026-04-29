#!/bin/bash
set -euo pipefail

counts_file="$1"
slack_file="$2"

suites=(
  "Fenix Browser_Full Functional Tests Suite"
  "Firefox for iOS_Full Functional Tests Suite"
)

echo "Full Functional Test Case Counts (Full Functional Tests Suite)" >> "$GITHUB_STEP_SUMMARY"
[ -f "$counts_file" ] || echo '{}' > "$counts_file"
cd "$filename"

table_rows='[[{"type":"raw_text","text":"Suite"},{"type":"raw_text","text":"Starting Count"},{"type":"raw_text","text":"Current Count"},{"type":"raw_text","text":"Delta"}]]'
updated_counts='{}'

for suite in "${suites[@]}"; do
  csvfile=$(ls "backup_${suite}_"*.csv 2>/dev/null | head -1)
  [ -z "$csvfile" ] && continue

  count=$(awk -F',' 'NR>1 && $1+0>0 {c++} END {print c+0}' "$csvfile")
  display=$(echo "$suite" | sed 's/_/ - /')
  project=$(echo "$suite" | sed 's/_Full Functional Tests Suite//')

  echo "* ${suite}: ${count} test cases" >> "$GITHUB_STEP_SUMMARY"

  prev=$(jq -r --arg key "$display" '.[$key] // empty' "../$counts_file")
  if [ -n "$prev" ]; then
    starting="$prev"
    delta=$((count - prev))
    abs_delta=$(( delta < 0 ? -delta : delta ))
    pct=$(awk "BEGIN {printf \"%.1f\", ($abs_delta / $prev) * 100}")
    if   [ $delta -gt 0 ]; then change="+${delta} / +${pct}%"
    elif [ $delta -lt 0 ]; then change="${delta} / -${pct}%"
    else                        change="no change"
    fi
  else
    starting="-"
    change="-"
  fi

  row=$(jq -n \
    --arg suite    "$project" \
    --arg starting "$starting" \
    --arg count    "$count" \
    --arg change   "$change" \
    '[{"type":"raw_text","text":$suite},{"type":"raw_text","text":$starting},{"type":"raw_text","text":$count},{"type":"raw_text","text":$change}]')
  table_rows=$(echo "$table_rows" | jq --argjson row "$row" '. + [$row]')
  updated_counts=$(echo "$updated_counts" | jq --arg key "$display" --argjson val "$count" '. + {($key): $val}')
done

echo "$updated_counts" > "../$counts_file"
today=$(date "+%Y-%m-%d")
jq -n --argjson rows "$table_rows" --arg date "$today" \
  '{"blocks":[{"type":"header","text":{"type":"plain_text","text":(":testops-testrail:Full Functional Test Case Counts — " + $date)}},{"type":"table","rows":$rows}]}' \
  > "../$slack_file"
