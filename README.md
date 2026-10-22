# P2S Local

[![ci](https://github.com/tunglambk/piano-to-sheet-local/actions/workflows/ci.yml/badge.svg)](https://github.com/tunglambk/piano-to-sheet-local/actions/workflows/ci.yml)

> **English** · [Tiếng Việt](README.vi.md)

Turn piano audio or video (MP3, MP4, WAV, FLAC, OGG…) into two-staff sheet music — MusicXML, PDF and MIDI — entirely on your own machine. No cloud, no telemetry, no upload: the audio never leaves the computer.

Status: **early development**. The core pipeline and the command-line tool work end to end; the local web UI is not built yet.

## What it does

- **Ingest** any common audio/video container with ffmpeg; loudness-normalise to EBU R128 and keep every timestamp relative to the original file.
- **Transcribe** the performance with [Transkun](https://github.com/Yujia-Yan/TransKun) (audio → MIDI notes and pedal), then detect beats and downbeats with [Beat This!](https://github.com/CPJKU/beat_this).
- **Engrave** the notes with the [MIDI2ScoreTransformer](https://github.com/TimFelixBeyer/MIDI2ScoreTransformer) sidecar (or the built-in rule quantiser when the neural model is unavailable), normalise the result, and align score notes to performance time.
- **Render** MusicXML, a compressed `.mxl`, a PDF (MuseScore when installed, otherwise Verovio + cairosvg), MEI, per-page SVG, performance and quantised MIDI, and a timemap of `note id → seconds`.
- **Cache** every stage by content hash, so changing one option re-runs only the stages that depend on it, and **record** a deterministic `manifest.json` for every job.

## Requirements

- Python 3.11, `ffmpeg`/`ffprobe` on `PATH`.
- Optional: MuseScore 4 (better PDF output), a CUDA GPU (much faster), Docker (M2ST sidecar).
- Model weights are **not** in this repository; `configs/models.lock` lists them with URLs, hashes and licences, and `p2s weights verify` checks what you have.

## Install

```bash
git clone https://github.com/tunglambk/piano-to-sheet-local.git
cd piano-to-sheet-local
python3.11 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
p2s --version
```

## Quick start

```bash
# whole file
p2s transcribe sonata.mp3 -o out/ --preset accurate

# an excerpt (times are in the original file)
p2s transcribe recital.m4a -o out/ --start 42 --end 132 --preset fast

# CPU only, no neural score model
p2s transcribe sketch.wav -o out/ --preset fast --device cpu
```

`out/` then contains:

| File | Content |
| --- | --- |
| `score.musicxml`, `score.mxl` | The score, editable in any notation app |
| `score.pdf`, `svg/page-*.svg` | Rendered pages |
| `score.mei` | MEI for the web viewer |
| `performance.mid`, `quantized.mid` | What was heard, and what was engraved |
| `timemap.json` | `note id → onset/offset` in original-file seconds |
| `manifest.json`, `run.json`, `warnings.txt` | Engine versions, cache keys, timings, warnings |

Presets: `accurate` (Transkun + Beat This! + M2ST), `fast` (no GPU model: rule quantiser), `song` (reserved). `p2s cache stats` shows the cache; `p2s weights verify` checks downloaded weights.

## How it works

```
audio/video ──S0 ingest──▶ wav 44.1 kHz
             ──S1 route───▶ "solo piano" + quality warnings
             ──S3 AMT─────▶ notes + pedal      (Transkun v2, GPU)
             ──S4 beats───▶ beat/downbeat grid (Beat This!)
             ──S5 score───▶ MusicXML           (M2ST sidecar, rule-quantiser fallback)
             ──S6 post────▶ validated, single-voice-per-staff score
             ──S7 align───▶ note id → seconds (banded DTW)
             ──S8 render──▶ MusicXML · MXL · PDF · MEI · SVG · MIDI · timemap
```

Every stage is cached by `{input hash, stage, engine version, weights hash, params, parent keys}`, and the same input and versions always produce byte-identical output. The full design — engine contract, metrics, benchmark plan, risks — is in [`docs/p2s-spec.md`](docs/p2s-spec.md) (also available [in Vietnamese](docs/p2s-spec.vi.md)).

## Repository layout

```text
p2s/           the package: core pipeline, engines, post-processing, rendering, CLI
sidecars/m2st/ the MIDI→score model behind an HTTP sidecar (Dockerfile included)
bench/         benchmark harness and dataset builders (no weights, no audio)
configs/       engine registry, presets, model lockfile, licence register
tests/         unit, contract, golden tests
docs/          specification and CI notes
scripts/       CI entry point and checks
data/, models/ local only — never committed
```

## Benchmarks

`p2s-bench` runs a system over a suite and writes OMR-NED with bootstrap confidence intervals; `bench/datasets/p2s_open/build.py` builds the synthetic P2S-Open set from licence-cleared scores, rendered locally. Benchmark data and model weights stay outside the repository (see `configs/models.lock` and `bench/datasets/registry.yaml`).

## Languages

The README, the specification and the CI notes ship in both languages: `X.md` is **English and authoritative**, `X.vi.md` is the Vietnamese translation, and the list lives in [`docs/i18n.txt`](docs/i18n.txt). When the two disagree, the English file wins. `scripts/check_docs.py` (run in CI) fails when a listed document loses its counterpart, its language switcher or a relative link.

## Licence

**PolyForm Noncommercial 1.0.0** (`PolyForm-Noncommercial-1.0.0`) — see [`LICENSE`](LICENSE), canonical text at
[polyformproject.org](https://polyformproject.org/licenses/noncommercial/1.0.0). In short:

- You may **use, change and share it free of charge for noncommercial purposes**: research, study,
  experiments, personal/hobby projects, and also non-profit organisations, schools, public research
  institutes and government bodies.
- **Commercial use is not allowed** (selling it, embedding it in a paid product or service, commercial
  consulting…). Commercial use needs a separate licence from the copyright holder.
- It is not an "open source" licence under the OSI definition, because OSI forbids licences that restrict
  fields of use — "open source but non-commercial" is a contradiction. PolyForm Noncommercial is
  **source-available** (public source, free for noncommercial use), which is what this project wants.

**Third-party components** keep their own licences; the register is `configs/licenses.yaml` and
`configs/models.lock`, summarised in [`NOTICE`](NOTICE):

| Group | Examples | Licence | How it is used |
| --- | --- | --- | --- |
| Called as a subprocess, not shipped | ffmpeg, MuseScore 4, FluidSynth | GPL-2.0-or-later / GPL-3.0 / LGPL-2.1-or-later | The user installs them; P2S does not redistribute them |
| Linked libraries | Verovio, cairosvg, soxr | LGPL-3.0 / LGPL-3.0 / LGPL-2.1-or-later | Dynamic linking; their notices are kept |
| Linked libraries | numpy, music21, httpx, soundfile, pypdf… | BSD-3-Clause | Attributed in `NOTICE` |
| Linked libraries | pydantic, PyYAML, pretty_midi, fastapi… | MIT | Attributed in `NOTICE` |

**Weights and datasets are not in the repository.** They are downloaded separately following
`configs/models.lock` / `bench/datasets/registry.yaml`, under each provider's terms. What matters here:
Transkun and Beat This! are MIT; M2ST **states no licence**, so it is used internally and noncommercially
only; Aria-AMT weights are CC BY-NC-SA 4.0; MAESTRO and ASAP are CC BY-NC-SA 4.0. The project is
therefore noncommercial as a whole; moving to commercial use requires replacing or re-clearing each
engine and dataset first.
