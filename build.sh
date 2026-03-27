#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

OUT="Auto-Update-Alfred-Workflows.alfredworkflow"
rm -f "$OUT"
zip -r "$OUT" info.plist run.sh update_workflows.py icon.png README.md >/dev/null

echo "Built: $SCRIPT_DIR/$OUT"
