# syntax=docker/dockerfile:1.12
FROM debian:bookworm-slim@sha256:abd67ffcfa541b485a3dff59865ab629aa048a6c613e639d36e7456b0b229241 AS source
ARG SNAC_COMMIT=8f79a718f1ad71f94f79999f0071348227aff22e
ARG SNAC_ARCHIVE_SHA256=a79c6753b88013de80d485a6f814320656e76ef59574e57f935c78e5fdc08a2b
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && curl --fail --location --proto '=https' --tlsv1.2 \
      --output /tmp/snac.tar.gz \
      "https://codeload.github.com/hubertsiuzdak/snac/tar.gz/${SNAC_COMMIT}" \
    && echo "${SNAC_ARCHIVE_SHA256}  /tmp/snac.tar.gz" | sha256sum --check --strict \
    && mkdir -p /opt/snac \
    && tar --extract --gzip --file /tmp/snac.tar.gz \
      --directory /opt/snac --strip-components=1 \
    && test -f /opt/snac/snac/snac.py \
    && test -f /opt/snac/LICENSE

FROM ghcr.io/d590900/smcp-worker:v0.1.0@sha256:fc894e462bcdb09e24ad883145be645a53e30dd67d2a2a335973312d17c047c2
ARG VCS_REF=unknown
ARG VERSION=development
LABEL org.opencontainers.image.source="https://github.com/D590900/space-message-compression-platform" \
      org.opencontainers.image.revision="$VCS_REF" \
      org.opencontainers.image.version="$VERSION" \
      org.opencontainers.image.licenses="Apache-2.0 AND MIT" \
      org.opencontainers.image.title="SMCP SNAC 24 kHz CPU runtime"
ENV SMCP_SNAC_ROOT=/opt/snac \
    SMCP_SNAC_PYTHON=/opt/snac-venv/bin/python \
    SMCP_MODEL_CACHE=/var/lib/smcp/models \
    PYTHONPATH=/opt/worker/src:/opt/snac \
    PATH=/opt/venv/bin:$PATH
USER root
COPY --from=ghcr.io/astral-sh/uv:0.11.21@sha256:ff07b86af50d4d9391d9daf4ff89ce427bc544f9aae87057e69a1cc0aa369946 /uv /uvx /bin/
COPY --from=source --chown=smcp:smcp /opt/snac /opt/snac
COPY services/compression-worker/model-runtime/snac-requirements.lock /tmp/snac-requirements.lock
COPY services/compression-worker/src /opt/worker/src
RUN uv venv --python /usr/local/bin/python3.12 /opt/snac-venv \
    && uv pip install --python /opt/snac-venv/bin/python \
      --require-hashes --no-deps --torch-backend cpu \
      --requirement /tmp/snac-requirements.lock \
    && /opt/snac-venv/bin/python -c \
      "import torch; from snac import SNAC; from smcp_worker.snac_runtime import pack_tokens; assert torch.__version__ == '2.6.0+cpu'; assert SNAC; assert pack_tokens" \
    && rm /tmp/snac-requirements.lock \
    && rm -rf /root/.cache/uv \
    && rm -f /usr/bin/uv /usr/bin/uvx \
    && chown -R smcp:smcp /opt/snac-venv /opt/worker/src \
    && find /opt/snac /opt/snac-venv -type d -exec chmod 0555 {} + \
    && find /opt/snac /opt/snac-venv -type f -exec chmod 0444 {} + \
    && chmod 0555 /opt/snac-venv/bin/*
USER smcp
