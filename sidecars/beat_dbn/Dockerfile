# Beat sidecar with a DBN postprocessor (D-037/D-039).
#
# madmom does not build on Python 3.11, so this image stays on 3.10. Weights are
# mounted read-only from models/beat_this; nothing is baked into the image.
FROM python:3.10-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg libsndfile1 build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY sidecars/beat_dbn/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip setuptools wheel "Cython<3" \
    && pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.4.1 torchaudio==2.4.1 \
    && pip install --no-cache-dir --no-build-isolation -r /app/requirements.txt

COPY p2s /app/p2s
COPY sidecars /app/sidecars

ENV PYTHONPATH=/app \
    P2S_BEAT_CHECKPOINT=/models/beat_this/final0.ckpt \
    MPLCONFIGDIR=/tmp/mpl
EXPOSE 8003
CMD ["python", "-m", "uvicorn", "sidecars.beat_dbn.server:app", "--host", "0.0.0.0", "--port", "8003"]
