#!/bin/bash
# One-time setup on a Mac: installs Python packages and schedules the scan
# for 6:30 pm every weekday. Run it from this folder:   bash setup_mac.sh
set -e
cd "$(dirname "$0")"
DIR="$(pwd)"

if ! command -v python3 >/dev/null; then
  echo "Python 3 is missing. Run:  xcode-select --install   then run this script again."; exit 1
fi
echo "Creating private Python environment…"
python3 -m venv .venv
./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet yfinance pandas numpy
chmod +x run_nightly.sh

PLIST="$HOME/Library/LaunchAgents/com.optionsscanner.nightly.plist"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.optionsscanner.nightly</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>$DIR/run_nightly.sh</string></array>
  <key>StartCalendarInterval</key><array>
    <dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>18</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Weekday</key><integer>2</integer><key>Hour</key><integer>18</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Weekday</key><integer>3</integer><key>Hour</key><integer>18</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Weekday</key><integer>4</integer><key>Hour</key><integer>18</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Weekday</key><integer>5</integer><key>Hour</key><integer>18</integer><key>Minute</key><integer>30</integer></dict>
  </array>
  <key>StandardErrorPath</key><string>$DIR/reports/launchd.err</string>
</dict></plist>
PL
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

# 10:00 am check (Mon–Fri)
MPLIST="$HOME/Library/LaunchAgents/com.optionsscanner.check.plist"
DAYS=""
for d in 1 2 3 4 5; do DAYS="$DAYS<dict><key>Weekday</key><integer>$d</integer><key>Hour</key><integer>10</integer><key>Minute</key><integer>0</integer></dict>"; done
cat > "$MPLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.optionsscanner.check</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>$DIR/run_check.sh</string></array>
  <key>StartCalendarInterval</key><array>$DAYS</array>
</dict></plist>
PL
launchctl unload "$MPLIST" 2>/dev/null || true
launchctl load "$MPLIST"
chmod +x run_check.sh publish_github.sh
# remove the old 8:30 job if an earlier version installed it
launchctl unload "$HOME/Library/LaunchAgents/com.optionsscanner.morning.plist" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/com.optionsscanner.morning.plist"
mkdir -p reports
echo "Scheduled: evening scan 6:30 pm + 10:00 am check, Mon–Fri. Running a first scan now (takes a few minutes)…"
./.venv/bin/python nightly_scanner.py
open docs/index.html
