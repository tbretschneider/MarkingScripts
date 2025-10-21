#!/usr/bin/env bash
# Usage: ./editgrades.sh grades1.csv
if [ $# -ne 1 ]; then
  echo "Usage: $0 path/to/grades.csv"
  exit 1
fi
CSV="$1"
# Resolve absolute path
CSV_ABS="$(readlink -f "$CSV")"
exec python3 "$(dirname "$0")/editgrades.py" "$CSV_ABS"

