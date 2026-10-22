# Continuous integration

> **English** · [Tiếng Việt](ci.vi.md)

The repository has one required check, `ci`, plus an optional GPU workflow.

| Workflow | Where it runs | What it does |
| --- | --- | --- |
| `ci` (`.github/workflows/ci.yml`) | GitHub-hosted `ubuntu-24.04`, Python 3.11 and Node 22, on every push and pull request | Python job: ruff (lint + format), pyright, licence register, model lockfile check, documentation i18n check, CPU tests. Web job: `pnpm install`, TypeScript build, Vitest |
| `gpu` (`.github/workflows/gpu.yml`) | Manual only (`workflow_dispatch`), on a self-hosted runner labelled `gpu` | `scripts/ci.sh --gpu`: the same checks plus the GPU contract tests (Transkun, Beat This!) and the M2ST sidecar test |

## Run the same checks locally

```bash
pip install -e ".[dev]"
bash scripts/ci.sh            # CPU checks (CUDA hidden, no network, no sidecars)
bash scripts/ci.sh --gpu      # also GPU + sidecar suites, on a machine that has them
```

`scripts/ci.sh` is the single entry point: GitHub Actions runs the same commands in separate steps, so a green local run means a green pull request.

## Why the split

GitHub-hosted runners have no CUDA GPU, no model weights and no sidecar, and the weights are never committed. Downloading the GPU stack (torch, Transkun, Beat This!, M2ST) on every run would cost gigabytes and minutes without adding signal: the CPU layer already exercises the engine contract, the cache, ingest, quantisation, alignment and rendering.

The CPU job therefore installs only what those tests touch — `pydantic`, `PyYAML`, `httpx`, `numpy`, `soundfile`, `verovio`, `pretty_midi`, pytest, ruff, pyright — plus `ffmpeg`. That doubles as a regression test for lazy imports: if a core module starts importing `torch` at module level, CI fails.

## What the CPU job does

1. `ruff check` and `ruff format --check` over `p2s`, `tests`, `scripts`, `bench`.
2. `pyright --pythonpath "$(command -v python)" p2s`. Missing optional imports (torch, fastapi, cairosvg) are warnings, because those dependencies are intentionally absent from the CI image.
3. `scripts/check_licenses.py` — every entry has a licence and evidence, and copyleft entries carry a note.
4. `scripts/check_lock.py` — engines listed in `configs/models.lock` have no `TBD`/`PENDING` field and their hashes are well formed.
5. `scripts/check_docs.py` — every relative link resolves, and every document listed in `docs/i18n.txt` has its English/Vietnamese pair and a language switcher.
6. `pytest -m "not gpu and not sidecar"`, after generating a licence-safe six-second sine fixture under `data/fixtures/smoke/` (fixtures are not committed).

## The web app

`apps/web` builds with `pnpm build` (TypeScript + Vite) and has Vitest unit tests for the playback logic; both run in the `web` job. The Playwright suites (`apps/web/e2e`) need the GPU stack and the M2ST sidecar, so they run on a machine that has them:

```bash
python scripts/make_g2_files.py
cd apps/web && pnpm exec playwright test
```

## Using a self-hosted GPU runner

Register a runner with the labels `self-hosted` and `gpu`, then make sure it has:

- this repository checked out with `data/` and `models/` populated (weights are never committed),
- the Python environments that hold the GPU stack, and the M2ST sidecar reachable on `127.0.0.1:8002`,
- a CUDA GPU; `CUDA_DEVICE_INDEX` selects it.

Then run the `gpu` workflow from the Actions tab. To change the runner labels without editing the file, set the repository variable `GPU_RUNNER_LABELS` to a JSON array, e.g. `["self-hosted","gpu","a100"]`.
