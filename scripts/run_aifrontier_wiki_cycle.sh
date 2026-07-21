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

if [ -f "${ROOT}/config/local.env" ]; then
  set -a
  source "${ROOT}/config/local.env"
  set +a
fi

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

# Live path: real weekly incremental driver.
# Network/LLM are used here intentionally (this is the automation surface), but
# the whole wrapper stays gated by scheduler-state.enabled / --force, and extract
# only runs when an LLM endpoint is configured.
echo "[cycle] live: validate"
${CLI} validate || { echo "[cycle] validate failed; aborting"; exit 1; }
echo "[cycle] live: fetch-index"
${CLI} fetch-index --allow-network || { echo "[cycle] fetch-index failed; aborting"; exit 1; }
echo "[cycle] live: fetch-pages (incremental; text-hash skips unchanged)"
${CLI} fetch-pages --allow-network --refresh --limit 50
if [ -n "${AIFRONTIER_LLM_BASE_URL:-}" ]; then
  echo "[cycle] live: extract (deepseek)"
  ${CLI} extract --allow-llm --adapter deepseek --limit 50
else
  echo "[cycle] live: AIFRONTIER_LLM_BASE_URL unset -> skipping extract (set config/local.env to enable)"
fi
${CLI} build-keyword-index
${CLI} render-wiki
echo "[cycle] live: post-cycle consistency check"
${CLI} validate
${CLI} selfcheck
echo "[cycle] live complete. (review git diff; commit per operating rules)"
exit 0
