# syntax=docker/dockerfile:1.12
FROM ghcr.io/d590900/smcp-worker:v0.1.0@sha256:fc894e462bcdb09e24ad883145be645a53e30dd67d2a2a335973312d17c047c2

ARG VCS_REF=unknown
ARG VERSION=development
LABEL org.opencontainers.image.source="https://github.com/D590900/space-message-compression-platform" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.licenses="Apache-2.0 AND MIT" \
      org.opencontainers.image.title="SMCP EnCodec 48 kHz CPU runtime"
ENV SMCP_ENCODEC_PYTHON=/opt/encodec-venv/bin/python \
    SMCP_MODEL_CACHE=/var/lib/smcp/models \
    TRANSFORMERS_OFFLINE=1 \
    HF_HUB_OFFLINE=1 \
    PYTHONPATH=/opt/worker/src \
    PATH=/opt/venv/bin:$PATH
USER root
COPY --from=ghcr.io/astral-sh/uv:0.11.21@sha256:ff07b86af50d4d9391d9daf4ff89ce427bc544f9aae87057e69a1cc0aa369946 /uv /uvx /bin/
COPY services/compression-worker/model-runtime/mimi-requirements.lock /tmp/encodec-requirements.lock
COPY services/compression-worker/src /opt/worker/src
RUN uv venv --python /usr/local/bin/python3.12 /opt/encodec-venv \
    && uv pip install --python /opt/encodec-venv/bin/python \
      --require-hashes --no-deps --torch-backend cpu \
      --requirement /tmp/encodec-requirements.lock \
    && /opt/encodec-venv/bin/python -c \
      "import torch, transformers; from transformers import EncodecModel; from smcp_worker.encodec_runtime import pack_tokens; assert torch.__version__ == '2.6.0+cpu'; assert transformers.__version__ == '5.5.0'; assert EncodecModel; assert pack_tokens" \
    && rm /tmp/encodec-requirements.lock \
    && rm -rf /root/.cache/uv \
    && rm -f /usr/bin/uv /usr/bin/uvx \
    && chown -R smcp:smcp /opt/encodec-venv /opt/worker/src \
    && find /opt/encodec-venv -type d -exec chmod 0555 {} + \
    && find /opt/encodec-venv -type f -exec chmod 0444 {} + \
    && chmod 0555 /opt/encodec-venv/bin/*

USER smcp
