# P2S Local

[![ci](https://github.com/tunglambk/piano-to-sheet-local/actions/workflows/ci.yml/badge.svg)](https://github.com/tunglambk/piano-to-sheet-local/actions/workflows/ci.yml)

> [English](README.md) · **Tiếng Việt**

Chuyển audio hoặc video piano (MP3, MP4, WAV, FLAC, OGG…) thành sheet nhạc 2 khuông — MusicXML, PDF và MIDI — ngay trên máy của bạn. Không cloud, không telemetry, không upload: audio không rời khỏi máy.

Trạng thái: **đang phát triển sớm**. Pipeline lõi và công cụ dòng lệnh đã chạy end-to-end; UI web trên máy chưa có.

## Nó làm gì

- **Nhận đầu vào** mọi container audio/video phổ biến bằng ffmpeg; chuẩn hoá độ lớn theo EBU R128 và giữ mọi mốc thời gian theo file gốc.
- **Phiên âm** phần trình diễn bằng [Transkun](https://github.com/Yujia-Yan/TransKun) (audio → nốt MIDI và pedal), rồi dò nhịp/phách mạnh bằng [Beat This!](https://github.com/CPJKU/beat_this).
- **Khắc nhạc** bằng sidecar [MIDI2ScoreTransformer](https://github.com/TimFelixBeyer/MIDI2ScoreTransformer) (hoặc bộ lượng tử hoá theo luật có sẵn khi không có model neural), chuẩn hoá kết quả và căn nốt trên bản nhạc với thời gian trình diễn.
- **Xuất** MusicXML, `.mxl` nén, PDF (MuseScore nếu có, không thì Verovio + cairosvg), MEI, SVG từng trang, MIDI phần trình diễn và MIDI đã lượng tử hoá, cùng timemap `note id → giây`.
- **Cache** mọi stage theo hash nội dung, nên đổi một tuỳ chọn chỉ chạy lại các stage phụ thuộc, và **ghi** `manifest.json` tất định cho mỗi job.

## Yêu cầu

- Python 3.11, `ffmpeg`/`ffprobe` trong `PATH`.
- Tuỳ chọn: MuseScore 4 (PDF đẹp hơn), GPU CUDA (nhanh hơn nhiều), Docker (sidecar M2ST).
- Trọng số model **không** nằm trong repo này; `configs/models.lock` liệt kê URL, hash và license, còn `p2s weights verify` kiểm tra những gì bạn đã tải.

## Cài đặt

```bash
git clone https://github.com/tunglambk/piano-to-sheet-local.git
cd piano-to-sheet-local
python3.11 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
p2s --version
```

## Bắt đầu nhanh

```bash
# cả file
p2s transcribe sonata.mp3 -o out/ --preset accurate

# một đoạn trích (thời gian tính theo file gốc)
p2s transcribe recital.m4a -o out/ --start 42 --end 132 --preset fast

# chỉ CPU, không dùng model neural
p2s transcribe sketch.wav -o out/ --preset fast --device cpu
```

Thư mục `out/` sau đó chứa:

| File | Nội dung |
| --- | --- |
| `score.musicxml`, `score.mxl` | Bản nhạc, mở/sửa được bằng mọi app ký âm |
| `score.pdf`, `svg/page-*.svg` | Các trang đã render |
| `score.mei` | MEI cho web viewer |
| `performance.mid`, `quantized.mid` | Những gì nghe được, và những gì được khắc |
| `timemap.json` | `note id → onset/offset` theo giây của file gốc |
| `manifest.json`, `run.json`, `warnings.txt` | Phiên bản engine, cache key, thời gian chạy, cảnh báo |

Preset: `accurate` (Transkun + Beat This! + M2ST), `fast` (không dùng model GPU: lượng tử hoá theo luật), `song` (để dành). `p2s cache stats` xem cache; `p2s weights verify` kiểm tra trọng số đã tải.

## API và web UI

`p2s serve` chạy API, worker và web app đã build trên cùng một cổng:

```bash
p2s serve --port 8765            # http://127.0.0.1:8765
p2s serve --no-worker            # chỉ API, khi worker chạy ở nơi khác
```

Web app có bốn màn hình: **Thư viện** (danh sách job, tìm kiếm, xoá), **Job mới** (kéo thả, preset, tên), **Đang xử lý** (tiến trình từng stage qua server-sent events, huỷ) và **Workspace** (bản nhạc ngay trên trình duyệt, phát audio khớp với ô nhịp đang chơi, bấm vào nốt để tua, xuất PDF/MusicXML/MIDI). Mọi chuỗi đều có tiếng Việt và tiếng Anh; nút đổi ngôn ngữ ở thanh trên.

- API: `POST /api/v1/jobs`, `GET /api/v1/jobs/{id}`, `GET /api/v1/jobs/{id}/events` (SSE), `POST /api/v1/jobs/{id}/cancel`, `GET /api/v1/jobs/{id}/artifacts/{kind}`, `PATCH`/`DELETE /api/v1/jobs/{id}`, `GET /api/v1/engines`. OpenAPI ở `/api/docs`.
- Dữ liệu đồng bộ: `GET /api/v1/jobs/{id}/sync` trả timemap (note id → giây, kèm onset của mọi ô nhịp) và các trang SVG; trình duyệt tô sáng theo note id nên bản nhạc, audio và timemap luôn khớp nhau.
- Job lưu trong SQLite (`data/p2s.db`) và mỗi job chạy trong process con, nên huỷ là giải phóng GPU.

Frontend ở `apps/web` (React 18 + TypeScript + Vite). Build bằng `pnpm -C apps/web install && pnpm -C apps/web build`; `p2s serve` tự dùng `apps/web/dist` khi thư mục đó tồn tại.

## Cách hoạt động

```
audio/video ──S0 ingest──▶ wav 44.1 kHz
             ──S1 route───▶ "solo piano" + cảnh báo chất lượng
             ──S3 AMT─────▶ nốt + pedal        (Transkun v2, GPU)
             ──S4 beats───▶ lưới nhịp/phách    (Beat This!)
             ──S5 score───▶ MusicXML           (sidecar M2ST, dự phòng lượng tử hoá theo luật)
             ──S6 post────▶ bản nhạc đã kiểm tra, mỗi khuông một voice
             ──S7 align───▶ note id → giây     (DTW có dải)
             ──S8 render──▶ MusicXML · MXL · PDF · MEI · SVG · MIDI · timemap
```

Mỗi stage được cache theo `{hash đầu vào, stage, phiên bản engine, hash weights, params, key của stage trước}`, và cùng đầu vào + cùng phiên bản luôn cho output giống hệt từng byte. Thiết kế đầy đủ — contract engine, metric, kế hoạch benchmark, rủi ro — ở [`docs/p2s-spec.vi.md`](docs/p2s-spec.vi.md) (bản [tiếng Anh](docs/p2s-spec.md)).

## Bố cục repo

```text
p2s/           package: pipeline lõi, engine, hậu xử lý, render, CLI
sidecars/m2st/ model MIDI→score sau một HTTP sidecar (có Dockerfile)
bench/         harness benchmark và builder dataset (không weights, không audio)
configs/       registry engine, preset, lockfile model, sổ license
tests/         unit, contract, golden
docs/          spec và ghi chú CI
scripts/       entry point CI và các check
data/, models/ chỉ ở máy — không bao giờ commit
```

## Benchmark

`p2s-bench` chạy một system trên một suite và ghi OMR-NED kèm khoảng tin cậy bootstrap; `bench/datasets/p2s_open/build.py` dựng tập tổng hợp P2S-Open từ các bản nhạc đã rõ license, render ngay trên máy. Dữ liệu benchmark và trọng số nằm ngoài repo (xem `configs/models.lock` và `bench/datasets/registry.yaml`).

## Ngôn ngữ

README, spec và ghi chú CI có hai bản: `X.md` là **tiếng Anh và là bản chuẩn**, `X.vi.md` là bản dịch tiếng Việt; danh sách nằm ở [`docs/i18n.txt`](docs/i18n.txt). Khi lệch nhau, bản tiếng Anh thắng. `scripts/check_docs.py` (chạy trong CI) báo lỗi khi một tài liệu trong danh sách thiếu bản đối chiếu, thiếu dòng chuyển ngôn ngữ hoặc link tương đối không phân giải.

## Giấy phép

**PolyForm Noncommercial 1.0.0** (`PolyForm-Noncommercial-1.0.0`) — xem [`LICENSE`](LICENSE), bản gốc tại
[polyformproject.org](https://polyformproject.org/licenses/noncommercial/1.0.0). Nói ngắn gọn:

- Được **dùng, sửa, chia sẻ miễn phí cho mục đích phi thương mại**: nghiên cứu, học tập, thử nghiệm,
  dự án cá nhân/hobby, và cả tổ chức phi lợi nhuận, trường học, viện nghiên cứu công, cơ quan nhà nước.
- **Không được dùng cho mục đích thương mại** (bán, tích hợp vào sản phẩm/dịch vụ trả tiền, tư vấn
  thương mại…). Muốn dùng thương mại cần giấy phép riêng từ chủ sở hữu bản quyền.
- Không phải giấy phép "open source" theo định nghĩa OSI, vì OSI cấm giấy phép giới hạn theo lĩnh vực
  sử dụng — "open source nhưng cấm thương mại" là hai yêu cầu mâu thuẫn. PolyForm Noncommercial là
  **source-available** (công khai mã nguồn, cho phép dùng phi thương mại), đúng thứ dự án cần.

**Thành phần bên thứ ba** giữ nguyên giấy phép riêng; sổ đăng ký ở `configs/licenses.yaml` và
`configs/models.lock`, tóm tắt trong [`NOTICE`](NOTICE):

| Nhóm | Ví dụ | Giấy phép | Cách dùng |
| --- | --- | --- | --- |
| Gọi như subprocess, không kèm theo | ffmpeg, MuseScore 4, FluidSynth | GPL-2.0-or-later / GPL-3.0 / LGPL-2.1-or-later | Người dùng tự cài, P2S không phân phối lại |
| Thư viện liên kết | Verovio, cairosvg, soxr | LGPL-3.0 / LGPL-3.0 / LGPL-2.1-or-later | Liên kết động; giữ notice tương ứng |
| Thư viện liên kết | numpy, music21, httpx, soundfile, pypdf… | BSD-3-Clause | Ghi công trong `NOTICE` |
| Thư viện liên kết | pydantic, PyYAML, pretty_midi, fastapi… | MIT | Ghi công trong `NOTICE` |

**Trọng số và dữ liệu không nằm trong repo.** Chúng được tải riêng theo `configs/models.lock` /
`bench/datasets/registry.yaml` và theo điều khoản của từng bên. Điểm quan trọng: Transkun và Beat This!
là MIT; M2ST **chưa công bố giấy phép** nên chỉ dùng nội bộ/phi thương mại; Aria-AMT có weights
CC BY-NC-SA 4.0; MAESTRO và ASAP là CC BY-NC-SA 4.0. Vì vậy cả dự án là phi thương mại; muốn chuyển
sang thương mại phải thay hoặc xin lại giấy phép cho từng engine/dataset trước.
