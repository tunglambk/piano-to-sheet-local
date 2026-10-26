#!/usr/bin/env bash
# CI entry point. GitHub Actions runs the CPU part of this script (D-026); the
# GPU and sidecar suites need this box and run locally.
#   scripts/ci.sh          CPU suite (CUDA hidden, no network, no sidecars)
#   scripts/ci.sh --gpu    also the GPU + sidecar suites on CUDA_DEVICE_INDEX (default 0)
#   Web checks run when apps/web/node_modules exists (pnpm build + vitest).
#   P2S_PYTHON=python scripts/ci.sh   run against another interpreter (CI)
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
PY=${P2S_PYTHON:-.envs/coinstall/bin/python}
export PYTHONPATH="$PWD"
export MPLCONFIGDIR="$PWD/.cache/mpl"
export P2S_DATA_DIR="$PWD/data"
status=0

echo "== ruff check"
"$PY" -m ruff check p2s tests scripts bench || status=1
echo "== ruff format --check"
"$PY" -m ruff format --check p2s tests scripts bench || status=1
echo "== pyright"
"$PY" -m pyright --pythonpath "$PY" p2s || status=1
echo "== licenses"
"$PY" scripts/check_licenses.py || status=1
echo "== docs i18n"
"$PY" scripts/check_docs.py || status=1
"$PY" scripts/check_report_refs.py || status=1
echo "== models.lock"
"$PY" scripts/check_lock.py || status=1
echo "== pytest (not gpu)"
CUDA_VISIBLE_DEVICES="" "$PY" -m pytest -m "not gpu and not sidecar" || status=1

if command -v pnpm >/dev/null 2>&1 && [[ -d apps/web/node_modules ]]; then
  echo "== web (typecheck, build, unit tests)"
  (cd apps/web && pnpm build >/dev/null && ./node_modules/.bin/vitest run >/dev/null) || status=1
fi

if [[ "${1:-}" == "--gpu" ]]; then
  echo "== pytest (gpu)"
  CUDA_VISIBLE_DEVICES="${CUDA_DEVICE_INDEX:-0}" "$PY" -m pytest -m "gpu" || status=1
  echo "== pytest (sidecar)"
  "$PY" -m pytest -m "sidecar" || status=1
fi

exit $status
