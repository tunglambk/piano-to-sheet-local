# beat_dbn sidecar

Runs Beat This! `final0` with both postprocessors (`minimal` and madmom's `dbn`)
and returns the accent-selected grid, so the pipeline can choose the better bar
structure per recording (D-037, D-039).

## Local development

```bash
python3.10 -m venv .envs/beat_dbn
.envs/beat_dbn/bin/pip install -U pip setuptools wheel "Cython<3"
.envs/beat_dbn/bin/pip install --index-url https://download.pytorch.org/whl/cpu torch==2.4.1 torchaudio==2.4.1
.envs/beat_dbn/bin/pip install --no-build-isolation -r sidecars/beat_dbn/requirements.txt
PYTHONPATH=. .envs/beat_dbn/bin/python -m uvicorn sidecars.beat_dbn.server:app --port 8003
```

`madmom` needs the `collections` ABC aliases; `server.py` installs them before
importing it, so no patching of the package is required.

## Container

```bash
docker build -f sidecars/beat_dbn/Dockerfile -t p2s-beat-dbn .
docker run --rm -p 8003:8003 -v "$PWD/models:/models:ro" p2s-beat-dbn
```

The pipeline treats this sidecar as optional: without it, the beat grid choice
(`s4b_grid`) is skipped and sync falls back to the `minimal` grid (4/5 instead
of 5/5 on the P2S-Open dev split).
