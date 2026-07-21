#!/usr/bin/env bash
# Run the AI Frontier wiki live cycle, commit generated changes, and push to GitHub.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${ROOT}/logs/scheduler"
mkdir -p "${LOG_DIR}"
LOG="${LOG_DIR}/weekly-publish-$(date -u +%Y%m%dT%H%M%SZ).log"

exec > >(tee -a "${LOG}") 2>&1
cd "${ROOT}"

echo "[publish] start $(date -u +%Y-%m-%dT%H:%M:%SZ)"
git fetch origin main
if ! git diff --quiet HEAD origin/main; then
  echo "[publish] local HEAD differs from origin/main; aborting to avoid overwriting remote changes"
  exit 1
fi

./scripts/run_aifrontier_wiki_cycle.sh --run

if git diff --quiet -- .    && [ -z "$(git ls-files --others --exclude-standard)" ]; then
  echo "[publish] no changes to commit"
  exit 0
fi

python3 scripts/aifrontier_wiki.py validate
python3 scripts/aifrontier_wiki.py selfcheck

git add 2.wiki data state config/local.env.example scripts/run_aifrontier_wiki_cycle.sh scripts/publish_aifrontier_wiki_weekly.sh
if git diff --cached --quiet; then
  echo "[publish] no tracked publish changes staged"
  exit 0
fi

git commit -m "Update AI Frontier wiki"
git push origin main

echo "[publish] pushed $(git rev-parse --short HEAD)"
echo "[publish] log ${LOG}"
