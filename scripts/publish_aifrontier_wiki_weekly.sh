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

# Material = rendered wiki, extracts, keyword index, or episodes.json content.
# Bookkeeping (state/*, episodes.json last_seen/updated_at) alone is not.
material_change() {
  git diff --quiet -- 2.wiki data/extracts data/keyword-index.json || return 0
  [ -n "$(git ls-files --others --exclude-standard -- 2.wiki data)" ] && return 0
  python3 - <<'PY'
import json, subprocess, sys
def strip(d):
    d.pop("updated_at", None)
    for e in d.get("episodes", []):
        e.pop("last_seen", None)
    return d
head = json.loads(subprocess.run(["git", "show", "HEAD:data/episodes.json"],
                                 capture_output=True, text=True, check=True).stdout)
work = json.load(open("data/episodes.json", encoding="utf-8"))
sys.exit(0 if strip(head) != strip(work) else 1)
PY
}

if ! material_change; then
  git checkout -- state data
  echo "[publish] no material change"
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
