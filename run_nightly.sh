#!/bin/bash
# Optional: run the evening scan on this Mac instead of GitHub Actions.
cd "$(dirname "$0")"
mkdir -p reports
./.venv/bin/python nightly_scanner.py >> reports/scanner.log 2>&1
[ -f .push_from_mac ] && ./publish_github.sh >> reports/scanner.log 2>&1
exit 0
