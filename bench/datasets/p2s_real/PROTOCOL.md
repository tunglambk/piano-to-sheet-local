# P2S-Real collection protocol

Audio and scores stay outside git (`data/p2s_real/`, D-003). This document is the
contract between collection, annotation and scoring so that a number from this set
means the same thing across sessions.

## Composition (D-003)

20 phone recordings, 20 covers, 20 mixed songs; 30–90 s each; solo piano that the
recorder owns the rights to.

## Recording

- Phone or cover recording, one take, no editing beyond trimming the ends.
- Keep the room noise: the set exists to represent real conditions.
- WAV or M4A, 44.1 kHz or better, mono or stereo; store the original file.
- Filename: `p2s_real_<id>_<condition>.wav` with `condition ∈ {phone, cover, mixed}`.

## Rights and consent

- One signed consent/rights form per recording (`consent/<id>.pdf`), stating that the
  performance may be used for evaluation and that the audio stays off the repository.
- Never include commercial recordings.

## Ground truth

- Two annotators transcribe the excerpt in MuseScore into a two-staff MusicXML
  (`scores/<id>.musicxml`), one bar per agreed metre.
- A third pass compares both; disagreements are resolved by ear against the audio and
  recorded in `scores/<id>.notes.md` (who resolved what).
- Bar lines and the metre are part of the ground truth: a score that is right in pitch
  but wrong in metre counts as wrong (that is what sync scoring measures).

## Metadata

`scores/<id>.json` follows the P2S-Open schema (item id, condition, duration, meter,
beats, downbeats, source), so `bench/datasets/p2s_open/build.py` helpers and
`scripts/check_sync.py` work unchanged.

## Splits

Frozen before scoring (D-010): 60 % dev, 40 % test. The test split is scored once per
release with `--final`.
