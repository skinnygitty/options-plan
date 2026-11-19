#!/bin/bash
# Optional: run the 10:00 check on this Mac instead of GitHub Actions.
cd "$(dirname "$0")"
mkdir -p reports
./.venv/bin/python nightly_scanner.py --check >> reports/scanner.log 2>&1
[ -f .push_from_mac ] && ./publish_github.sh >> reports/scanner.log 2>&1
exit 0
