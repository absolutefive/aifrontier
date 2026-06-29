#!/usr/bin/env bash
# Weekly cycle wrapper for aifrontier-wiki.
# Disabled-by-default via state/scheduler-state.json. Dry-run unless --force.
# Does NOT enable network/LLM by itself; pass-through flags must be explicit.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI="python3 ${ROOT}/scripts/aifrontier_wiki.py"
STATE="${ROOT}/state/scheduler-state.json"
LOG_DIR="${ROOT}/logs/scheduler"
mkdir -p "${LOG_DIR}"

FORCE=0
DRY_RUN=1
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    --run) DRY_RUN=0 ;;
  esac
done

enabled="$(python3 -c "import json,sys;print(json.load(open('${STATE}')).get('enabled'))" 2>/dev/null || echo "False")"
if [ "${enabled}" != "True" ] && [ "${FORCE}" -ne 1 ]; then
  echo "scheduler disabled (state/scheduler-state.json enabled=false). Use --force to override."
  exit 0
fi

echo "[cycle] validate"
${CLI} validate

if [ "${DRY_RUN}" -eq 1 ]; then
  echo "[cycle] dry-run: skipping fetch/extract. Rendering from existing extracts only."
  ${CLI} build-keyword-index
  ${CLI} render-wiki
  echo "[cycle] post-render consistency check"
  ${CLI} validate
  ${CLI} selfcheck
  echo "[cycle] dry-run complete. (no network, no LLM, no commit)"
  exit 0
fi

# Live path (Phase 1+). Network/LLM stages still require their own opt-in flags
# and are not implemented in the Phase 0 scaffold.
echo "[cycle] live path is not enabled in Phase 0 scaffold."
exit 0
