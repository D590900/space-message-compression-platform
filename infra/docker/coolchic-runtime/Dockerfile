# syntax=docker/dockerfile:1.12
FROM debian:bookworm-slim@sha256:abd67ffcfa541b485a3dff59865ab629aa048a6c613e639d36e7456b0b229241 AS source
ARG COOLCHIC_COMMIT=a6fe38a414dd098b39c41636bd6e423626402f7e
ARG COOLCHIC_ARCHIVE_SHA256=38918ef2bbf3111387fddc43e5299bef2dc5b78de2de968e9e51ad3e2ef760fb
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && curl --fail --location --proto '=https' --tlsv1.2 \
      --output /tmp/coolchic.tar.gz \
      "https://codeload.github.com/Orange-OpenSource/Cool-Chic/tar.gz/${COOLCHIC_COMMIT}" \
    && echo "${COOLCHIC_ARCHIVE_SHA256}  /tmp/coolchic.tar.gz" | sha256sum --check --strict \
    && mkdir -p /opt/coolchic \
    && tar --extract --gzip --file /tmp/coolchic.tar.gz \
      --directory /opt/coolchic --strip-components=1 \
    && test -f /opt/coolchic/cc_encode.py \
    && test -f /opt/coolchic/cc_decode.py \
    && test -f /opt/coolchic/LICENSE.txt

FROM ghcr.io/d590900/smcp-worker:v0.1.0@sha256:fc894e462bcdb09e24ad883145be645a53e30dd67d2a2a335973312d17c047c2
ARG VCS_REF=unknown
ARG VERSION=development
LABEL org.opencontainers.image.source="https://github.com/D590900/space-message-compression-platform" \
      org.opencontainers.image.revision="$VCS_REF" \
      org.opencontainers.image.version="$VERSION" \
      org.opencontainers.image.licenses="Apache-2.0 AND BSD-3-Clause" \
      org.opencontainers.image.title="SMCP Cool-Chic overfit neural image and video runtime"
ENV SMCP_COOLCHIC_ROOT=/opt/coolchic \
    SMCP_COOLCHIC_PYTHON=/opt/coolchic-venv/bin/python \
    PYTHONPATH=/opt/worker/src:/opt/coolchic \
    PATH=/opt/venv/bin:$PATH
USER root
COPY --from=ghcr.io/astral-sh/uv:0.11.21@sha256:ff07b86af50d4d9391d9daf4ff89ce427bc544f9aae87057e69a1cc0aa369946 /uv /uvx /bin/
COPY --from=source --chown=smcp:smcp /opt/coolchic /opt/coolchic
COPY services/compression-worker/model-runtime/coolchic-requirements.lock /tmp/coolchic-requirements.lock
COPY --chown=smcp:smcp services/compression-worker/src /opt/worker/src
RUN uv venv --python /usr/local/bin/python3.12 /opt/coolchic-venv \
    && uv pip install --python /opt/coolchic-venv/bin/python \
      --require-hashes --no-deps --torch-backend cpu \
      --requirement /tmp/coolchic-requirements.lock \
    && cd /opt/coolchic \
    && /opt/coolchic-venv/bin/python -c \
      "import torch; from coolchic.bitstream.decode import decode_video; from smcp_worker.coolchic_runtime import unpack_container; assert torch.__version__ == '2.11.0+cpu'; assert decode_video and unpack_container" \
    && rm /tmp/coolchic-requirements.lock \
    && rm -rf /root/.cache/uv \
    && rm -f /usr/bin/uv /usr/bin/uvx \
    && chown -R smcp:smcp /opt/coolchic /opt/coolchic-venv /opt/worker/src \
    && find /opt/coolchic /opt/coolchic-venv /opt/worker/src -type d -exec chmod 0555 {} + \
    && find /opt/coolchic /opt/coolchic-venv /opt/worker/src -type f -exec chmod 0444 {} + \
    && chmod 0555 /opt/coolchic-venv/bin/*
USER smcp
