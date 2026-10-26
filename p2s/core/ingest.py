"""S0 — ingest (spec §3, FR-01).

Validate the container with ffprobe, enforce the input limits, decode to a
44.1 kHz stereo WAV, apply optional two-pass EBU R128 loudness normalisation in
linear mode, trim to the requested range with `atrim`, and record the sha256 of
the *raw* input. All times stay relative to the original file: the start of the
selected range becomes `AudioRef.origin_offset_s`.

The ffmpeg build string is the S0 engine version.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from p2s.core.cache import sha256_file
from p2s.core.errors import CorruptInput, InputTooLong, UnsupportedInput
from p2s.core.schemas import AudioRef, IngestOptions

MAX_BYTES = 500 * 1024 * 1024
MAX_DURATION_S = 20 * 60.0
TARGET_SR = 44100
TARGET_CHANNELS = 2

_AUDIO_CODECS = {
    "mp3",
    "aac",
    "opus",
    "vorbis",
    "flac",
    "pcm_s16le",
    "pcm_s24le",
    "pcm_s32le",
    "pcm_f32le",
    "alac",
}


@dataclass(frozen=True)
class MediaInfo:
    duration_s: float
    sample_rate: int
    channels: int
    codec: str


def ffmpeg_version() -> str:
    out = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, check=False).stdout
    first = out.splitlines()[0] if out else "ffmpeg unknown"
    return first.strip()


def _probe_with_soundfile(path: Path) -> MediaInfo:
    """Minimal probe for environments without ffprobe (WAV/FLAC/OGG)."""
    try:
        import soundfile

        info = soundfile.info(str(path))
    except Exception as exc:  # noqa: BLE001 - unreadable input is a corrupt input
        raise CorruptInput(f"neither ffprobe nor soundfile can read {path.name}: {exc}") from exc
    return MediaInfo(
        duration_s=float(info.duration),
        sample_rate=int(info.samplerate),
        channels=int(info.channels),
        codec=(info.format or "").lower(),
    )


def probe(path: Path, *, allow_long: bool = False) -> MediaInfo:
    if not path.exists():
        raise UnsupportedInput(f"input not found: {path}")
    if path.stat().st_size == 0:
        raise CorruptInput(f"input is empty: {path}")
    if path.stat().st_size > MAX_BYTES:
        raise UnsupportedInput(f"input is larger than 500 MB: {path}")
    if shutil.which("ffprobe") is None:
        # ffprobe is not always installed (a static ffmpeg build ships one binary):
        # fall back to soundfile/librosa metadata for the formats it can open.
        return _probe_with_soundfile(path)
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise CorruptInput(f"ffprobe cannot read {path.name}: {proc.stderr.strip()[:300]}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise CorruptInput(f"ffprobe returned invalid JSON for {path.name}") from exc
    streams = [s for s in data.get("streams", []) if s.get("codec_type") == "audio"]
    if not streams:
        raise UnsupportedInput(f"{path.name} has no audio stream")
    stream = streams[0]
    codec = str(stream.get("codec_name", ""))
    if codec not in _AUDIO_CODECS:
        raise UnsupportedInput(f"{path.name}: unsupported audio codec {codec!r}")
    duration = float(data.get("format", {}).get("duration") or stream.get("duration") or 0.0)
    if duration <= 0:
        raise CorruptInput(f"{path.name}: cannot determine duration")
    if duration > MAX_DURATION_S + 0.5 and not allow_long:
        raise InputTooLong(f"{path.name}: {duration / 60:.1f} min exceeds the 20-minute limit")
    return MediaInfo(
        duration_s=duration,
        sample_rate=int(stream.get("sample_rate", 0)),
        channels=int(stream.get("channels", 0)),
        codec=codec,
    )


def _loudness_filter(start: float | None, end: float | None) -> str:
    filters = []
    if start is not None or end is not None:
        start_s = f"{start or 0.0:.6f}"
        end_s = f"{end:.6f}" if end is not None else ""
        filters.append(
            f"atrim=start={start_s}" + (f":end={end_s}" if end_s else "") + ",asetpts=PTS-STARTPTS"
        )
    return ",".join(filters)


def _measure_loudness(src: Path, pre_filter: str) -> dict[str, str] | None:
    chain = (pre_filter + "," if pre_filter else "") + "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json"
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(src), "-af", chain, "-f", "null", "-"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise CorruptInput(f"ffmpeg cannot decode {src.name}: {proc.stderr.strip()[-300:]}")
    match = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", proc.stderr, re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _usable_loudness(stats: dict[str, str]) -> bool:
    """Silence yields -inf/NaN measurements; loudnorm then fails on the second pass."""
    for key in ("input_i", "input_tp", "input_thresh", "target_offset"):
        value = str(stats.get(key, "")).strip().lower()
        if value in ("", "-inf", "inf", "nan", "-nan"):
            return False
    return True


def decode(src: Path, out_wav: Path, opts: IngestOptions) -> AudioRef:
    """Decode + trim + normalise `src` into `out_wav`; returns the AudioRef."""
    # A selected range is what the job processes, so the FR-01 length limit applies
    # to the range, not to the whole file (FR-02 lets users pick a passage).
    ranged = opts.start_s is not None or opts.end_s is not None
    info = probe(src, allow_long=ranged)
    start = opts.start_s or 0.0
    if start >= info.duration_s:
        raise UnsupportedInput(f"start {start:.2f}s is beyond the file duration {info.duration_s:.2f}s")
    end = opts.end_s
    if end is not None and end > info.duration_s + 0.01:
        raise UnsupportedInput(f"end {end:.2f}s is beyond the file duration {info.duration_s:.2f}s")
    effective_end = end if end is not None else info.duration_s
    if effective_end - start > MAX_DURATION_S + 0.5:
        raise InputTooLong(
            f"{src.name}: selected range is {(effective_end - start) / 60:.1f} min; the limit is 20 minutes"
        )
    pre = _loudness_filter(opts.start_s, end)

    args = ["ffmpeg", "-hide_banner", "-nostats", "-loglevel", "error", "-y", "-i", str(src)]
    if opts.normalize_loudness:
        stats = _measure_loudness(src, pre)
        if stats and _usable_loudness(stats):
            norm = (
                "loudnorm=I=-16:TP=-1.5:LRA=11"
                f":measured_I={stats['input_i']}:measured_TP={stats['input_tp']}"
                f":measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}"
                f":offset={stats['target_offset']}:linear=true"
            )
            chain = ",".join(x for x in (pre, norm) if x)
        else:
            chain = pre
    else:
        chain = pre
    if chain:
        args += ["-af", chain]
    args += [
        "-ar",
        str(TARGET_SR),
        "-ac",
        str(TARGET_CHANNELS),
        "-c:a",
        "pcm_s16le",
        "-bitexact",
        "-fflags",
        "+bitexact",
        "-map_metadata",
        "-1",
        str(out_wav),
    ]
    proc = subprocess.run(args, capture_output=True, text=True, check=False)
    if proc.returncode != 0 or not out_wav.exists():
        raise CorruptInput(f"ffmpeg failed to decode {src.name}: {proc.stderr.strip()[-300:]}")
    ref = probe(out_wav)
    return AudioRef(
        path=str(out_wav),
        sha256=sha256_file(src),
        sample_rate=ref.sample_rate,
        channels=ref.channels,
        duration_s=ref.duration_s,
        origin_offset_s=start,
    )
