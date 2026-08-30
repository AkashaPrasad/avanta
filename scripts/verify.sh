#!/usr/bin/env bash
# The self-repair loop's outer shell. Every stage writes machine-readable output
# to reports/verification/<timestamp>/ so a failure can be diagnosed after the
# fact rather than re-run to be seen.
#
# Stages fail independently: the script runs them all and reports which failed,
# because stopping at the first failure hides how much else is broken.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="reports/verification/$STAMP"
mkdir -p "$OUT"

PY="${PY:-./.venv/bin/python}"
[ -x "$PY" ] || PY="python3"

FAILED=()
run_stage() {
  local name="$1"; shift
  echo ""
  echo "── $name ──────────────────────────────────────────────"
  if "$@" > "$OUT/$name.log" 2>&1; then
    echo "   PASS   (log: $OUT/$name.log)"
  else
    echo "   FAIL   (log: $OUT/$name.log)"
    tail -20 "$OUT/$name.log" | sed 's/^/     /'
    FAILED+=("$name")
  fi
}

echo "AVANTA verification — $STAMP"
echo "output: $OUT"

# Stage 1: environment. Skipped rather than failed when Docker is not running,
# because the science stages are still worth running on a dev machine.
if docker info >/dev/null 2>&1; then
  run_stage "01-environment" docker compose config --quiet
else
  echo ""
  echo "── 01-environment ──────────────────────────────────────"
  echo "   SKIP   Docker is not available on this host"
fi

run_stage "02-static-ruff"   "$PY" -m ruff check core api scripts tests
run_stage "03-static-mypy"   "$PY" -m mypy --ignore-missing-imports core
run_stage "04-unit"          "$PY" -m pytest tests/unit -q
run_stage "05-integration"   "$PY" -m pytest tests/integration -q
run_stage "06-science"       "$PY" scripts/selfcheck.py --json "$OUT/selfcheck.json"
run_stage "07-matrix"        "$PY" scripts/selfcheck.py --matrix

if [ -d web/node_modules ]; then
  run_stage "08-typecheck"   npx --prefix web tsc --noEmit -p web/tsconfig.json
  if [ -f web/playwright.config.ts ]; then
    run_stage "09-e2e"       npx --prefix web playwright test --config web/playwright.config.ts
  fi
else
  echo ""
  echo "── 08-frontend ─────────────────────────────────────────"
  echo "   SKIP   web/node_modules is missing; run 'npm install' in web/"
fi

echo ""
echo "════════════════════════════════════════════════════════"
if [ ${#FAILED[@]} -eq 0 ]; then
  echo "ALL STAGES PASSED"
  echo "reports: $OUT"
  exit 0
fi
echo "FAILED STAGES: ${FAILED[*]}"
echo "reports: $OUT"
exit 1
