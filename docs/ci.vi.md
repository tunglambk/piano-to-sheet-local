# CI (tích hợp liên tục)

> [English](ci.md) · **Tiếng Việt**

Repo có một check bắt buộc là `ci`, và thêm một workflow GPU tuỳ chọn.

| Workflow | Chạy ở đâu | Làm gì |
| --- | --- | --- |
| `ci` (`.github/workflows/ci.yml`) | GitHub-hosted `ubuntu-24.04`, Python 3.11, mỗi push và pull request | ruff (lint + format), pyright, sổ license, kiểm tra lockfile model, kiểm tra song ngữ tài liệu, và bộ test CPU |
| `gpu` (`.github/workflows/gpu.yml`) | Chỉ chạy tay (`workflow_dispatch`), trên runner self-hosted label `gpu` | `scripts/ci.sh --gpu`: các check như trên, cộng contract test GPU (Transkun, Beat This!) và test sidecar M2ST |

## Chạy đúng các check đó ở máy

```bash
pip install -e ".[dev]"
bash scripts/ci.sh            # check CPU (ẩn CUDA, không mạng, không sidecar)
bash scripts/ci.sh --gpu      # thêm suite GPU + sidecar, trên máy có chúng
```

`scripts/ci.sh` là entry point duy nhất: GitHub Actions chạy đúng các lệnh đó theo từng step, nên local xanh nghĩa là pull request xanh.

## Vì sao tách hai lớp

Runner của GitHub không có GPU CUDA, không có weights và không có sidecar, mà weights thì không bao giờ được commit. Cài cả stack GPU (torch, Transkun, Beat This!, M2ST) mỗi lần chạy sẽ tốn hàng GB và vài phút mà không thêm tín hiệu: lớp CPU đã chạy qua contract engine, cache, ingest, lượng tử hoá, căn chỉnh và render.

Vì vậy job CPU chỉ cài những gì các test đó dùng — `pydantic`, `PyYAML`, `httpx`, `numpy`, `soundfile`, `verovio`, `pretty_midi`, pytest, ruff, pyright — cộng `ffmpeg`. Việc này đồng thời là test hồi quy cho lazy import: nếu một module lõi import `torch` ở module level, CI sẽ fail.

## Job CPU làm gì

1. `ruff check` và `ruff format --check` trên `p2s`, `tests`, `scripts`, `bench`.
2. `pyright --pythonpath "$(command -v python)" p2s`. Các import tuỳ chọn bị thiếu (torch, fastapi, cairosvg) chỉ là warning, vì những dependency đó cố ý không có trong image CI.
3. `scripts/check_licenses.py` — mọi mục có license và bằng chứng; mục copyleft phải có ghi chú.
4. `scripts/check_lock.py` — các engine trong `configs/models.lock` không có trường `TBD`/`PENDING` và hash đúng định dạng.
5. `scripts/check_docs.py` — mọi link tương đối phân giải được, và mỗi tài liệu trong `docs/i18n.txt` có đủ cặp Anh/Việt cùng dòng chuyển ngôn ngữ.
6. `pytest -m "not gpu and not sidecar"`, sau khi tạo một fixture sine 6 giây an toàn về license dưới `data/fixtures/smoke/` (fixture không được commit).

## Dùng runner GPU `self-hosted`

Đăng ký runner với các label `self-hosted` và `gpu`, rồi bảo đảm nó có:

- repo này ở một đường dẫn có `data/` và `models/` đã nạp đầy đủ (weights không bao giờ được commit),
- các environment Python chứa stack GPU, và sidecar M2ST truy cập được tại `127.0.0.1:8002`,
- một GPU CUDA; `CUDA_DEVICE_INDEX` chọn GPU đó.

Sau đó chạy workflow `gpu` từ tab Actions. Để đổi label runner mà không sửa file, đặt biến repository `GPU_RUNNER_LABELS` thành một JSON array, ví dụ `["self-hosted","gpu","a100"]`.
