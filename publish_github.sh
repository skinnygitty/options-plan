#!/bin/bash
# Pushes the latest pages from this Mac to GitHub (only used if you run scans on the Mac).
cd "$(dirname "$0")"
git add -A docs reports snapshots
git diff --cached --quiet && exit 0
git commit -m "mac scan $(date '+%Y-%m-%d %H:%M')"
git pull --rebase --autostash && git push
