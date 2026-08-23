# syntax=docker/dockerfile:1.12
FROM debian:bookworm-slim@sha256:abd67ffcfa541b485a3dff59865ab629aa048a6c613e639d36e7456b0b229241 AS source
ARG GENCODEC_COMMIT=c49eb0d643cc75e6c732cbc311a508627b54cf06
ARG GENCODEC_ARCHIVE_SHA256=97889bfdc43c6285f8aa75a80ec153f3ae01f5d441d858b646632bff939c1855
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && curl --fail --location --proto '=https' --tlsv1.2 \
      --output /tmp/gencodec.tar.gz \
      "https://codeload.github.com/microsoft/GenCodec/tar.gz/${GENCODEC_COMMIT}" \
    && echo "${GENCODEC_ARCHIVE_SHA256}  /tmp/gencodec.tar.gz" | sha256sum --check --strict \
    && mkdir -p /opt/cod-lite \
    && tar --extract --gzip --file /tmp/gencodec.tar.gz \
      --directory /opt/cod-lite --strip-components=1 \
    && test -f /opt/cod-lite/CoD_Lite/finetuned_one_step_codec/inference.py \
    && test -f /opt/cod-lite/LICENSE

FROM ghcr.io/d590900/smcp-worker:v0.1.0@sha256:fc894e462bcdb09e24ad883145be645a53e30dd67d2a2a335973312d17c047c2
ARG VCS_REF=unknown
ARG VERSION=development
LABEL org.opencontainers.image.source="https://github.com/D590900/space-message-compression-platform" \
      org.opencontainers.image.revision="$VCS_REF" \
      org.opencontainers.image.version="$VERSION" \
      org.opencontainers.image.licenses="Apache-2.0 AND MIT" \
      org.opencontainers.image.title="SMCP CoD-Lite CUDA runtime"
ENV SMCP_COD_LITE_ROOT=/opt/cod-lite/CoD_Lite \
    SMCP_COD_LITE_PYTHON=/opt/cod-lite-venv/bin/python \
    SMCP_MODEL_CACHE=/var/lib/smcp/models \
    PATH=/opt/venv/bin:$PATH
USER root
COPY --from=ghcr.io/astral-sh/uv:0.11.21@sha256:ff07b86af50d4d9391d9daf4ff89ce427bc544f9aae87057e69a1cc0aa369946 /uv /uvx /bin/
COPY --from=source --chown=smcp:smcp /opt/cod-lite /opt/cod-lite
COPY services/compression-worker/model-runtime/cod-lite-requirements.lock /tmp/cod-lite-requirements.lock
COPY services/compression-worker/src /opt/worker/src
RUN uv venv --python /usr/local/bin/python3.12 /opt/cod-lite-venv \
    && uv pip install --python /opt/cod-lite-venv/bin/python \
      --require-hashes --no-deps --torch-backend cu124 \
      --requirement /tmp/cod-lite-requirements.lock \
    && cd /opt/cod-lite/CoD_Lite \
    && /opt/cod-lite-venv/bin/python -c \
      "import torch, torchvision; import finetuned_one_step_codec.inference; assert torch.version.cuda == '12.4'" \
    && rm /tmp/cod-lite-requirements.lock \
    && rm -rf /root/.cache/uv \
    && chown -R smcp:smcp /opt/cod-lite-venv /opt/worker/src \
    && find /opt/cod-lite /opt/cod-lite-venv -type d -exec chmod 0555 {} + \
    && find /opt/cod-lite /opt/cod-lite-venv -type f -exec chmod 0444 {} + \
    && chmod 0555 /opt/cod-lite-venv/bin/*
USER smcp
