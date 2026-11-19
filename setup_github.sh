#!/bin/bash
# One-time: put this folder on GitHub so Actions runs the scans and Pages hosts the site.
# 1) On github.com create a NEW, EMPTY public repository (no README), e.g. "options-plan".
# 2) Run:  bash setup_github.sh   and paste the repository URL when asked.
set -e
cd "$(dirname "$0")"
read -r -p "Repository URL (e.g. https://github.com/yourname/options-plan.git): " URL
git init -q -b main 2>/dev/null || git init -q
git checkout -q -B main
git add -A
git commit -q -m "Options scanner" || true
git remote remove origin 2>/dev/null || true
git remote add origin "$URL"
git push -u origin main
echo
echo "Pushed. Now on github.com, in this repository:"
echo "  Settings > Pages > Source: Deploy from a branch > Branch: main, folder: /docs > Save"
echo "  Actions > Options scanner > Run workflow (to get a first plan right away)"
