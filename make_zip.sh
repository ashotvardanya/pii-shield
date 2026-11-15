#!/bin/bash
# Build dist/PII-Shield.zip to AirDrop or copy to another Mac. Contains code only, no personal data.
#   bash make_zip.sh
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p dist
rm -f dist/PII-Shield.zip
zip -qr dist/PII-Shield.zip README.md LICENSE install.sh uninstall.sh requirements.txt \
  bin pii_shield scripts skills lmstudio tests \
  -x '*/__pycache__/*' '*.pyc' '*.DS_Store' '*.redacted.*' '*.restored.*'
echo "Built dist/PII-Shield.zip ($(du -h dist/PII-Shield.zip | cut -f1))"
