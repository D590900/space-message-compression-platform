# syntax=docker/dockerfile:1.12
FROM debian:bookworm-slim@sha256:abd67ffcfa541b485a3dff59865ab629aa048a6c613e639d36e7456b0b229241 AS source
ARG HINERV_COMMIT=fdb92ec22492246f800621dfd454f6a5c62ab75b
ARG HINERV_ARCHIVE_SHA256=a2933084048fcabd4f250d749b24439a6905a24eef00f0c8321d855140f1eea4
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl patch \
    && curl --fail --location --proto '=https' --tlsv1.2 \
      --output /tmp/hinerv.tar.gz \
      "https://codeload.github.com/hmkx/HiNeRV/tar.gz/${HINERV_COMMIT}" \
    && echo "${HINERV_ARCHIVE_SHA256}  /tmp/hinerv.tar.gz" | sha256sum --check --strict \
    && mkdir -p /opt/hinerv \
    && tar --extract --gzip --file /tmp/hinerv.tar.gz \
      --directory /opt/hinerv --strip-components=1 \
    && test -f /opt/hinerv/hinerv_main.py \
    && test -f /opt/hinerv/LICENSE
COPY infra/docker/hinerv-runtime/hinerv-security.patch /tmp/hinerv-security.patch
RUN patch --fuzz=0 --directory=/opt/hinerv --strip=1 < /tmp/hinerv-security.patch

FROM ghcr.io/d590900/smcp-worker:v0.1.0@sha256:fc894e462bcdb09e24ad883145be645a53e30dd67d2a2a335973312d17c047c2 AS builder
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential ninja-build patch \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.11.21@sha256:ff07b86af50d4d9391d9daf4ff89ce427bc544f9aae87057e69a1cc0aa369946 /uv /uvx /bin/
COPY services/compression-worker/model-runtime/hinerv-requirements.lock /tmp/hinerv-requirements.lock
RUN uv venv --python /usr/local/bin/python3.12 /opt/hinerv-venv \
    && uv pip install --python /opt/hinerv-venv/bin/python \
      --require-hashes --no-deps --torch-backend cpu \
      --requirement /tmp/hinerv-requirements.lock \
    && TORCH_EXTENSIONS_DIR=/tmp/torch-extensions /opt/hinerv-venv/bin/python -c \
      "import shutil; import torchac.torchac as impl; shutil.copy2(impl.torchac_backend.__file__, '/opt/hinerv-venv/lib/python3.12/site-packages/torchac/torchac_backend.so')" \
    && torchac_py=/opt/hinerv-venv/lib/python3.12/site-packages/torchac/torchac.py \
    && test "$(grep -Fxc 'from torch.utils.cpp_extension import load' "$torchac_py")" -eq 1 \
    && test "$(grep -Fxc '# Load on-the-fly with ninja.' "$torchac_py")" -eq 1 \
    && test "$(grep -Fxc '  verbose=True)' "$torchac_py")" -eq 1 \
    && sed -i 's/^from torch\.utils\.cpp_extension import load$/from . import torchac_backend/' "$torchac_py" \
    && sed -i '/^# Load on-the-fly with ninja\.$/,/^  verbose=True)$/d' "$torchac_py" \
    && ! grep -F 'cpp_extension' "$torchac_py" \
    && /opt/hinerv-venv/bin/python -c \
      "import torch; import torchac.torchac as impl; assert torch.__version__ == '2.6.0+cpu'; assert impl.torchac_backend"

FROM ghcr.io/d590900/smcp-worker:v0.1.0@sha256:fc894e462bcdb09e24ad883145be645a53e30dd67d2a2a335973312d17c047c2
ARG VCS_REF=unknown
ARG VERSION=development
LABEL org.opencontainers.image.source="https://github.com/D590900/space-message-compression-platform" \
      org.opencontainers.image.revision="$VCS_REF" \
      org.opencontainers.image.version="$VERSION" \
      org.opencontainers.image.licenses="Apache-2.0 AND MIT" \
      org.opencontainers.image.title="SMCP HiNeRV per-video neural runtime"
ENV SMCP_HINERV_ROOT=/opt/hinerv \
    SMCP_HINERV_PYTHON=/opt/hinerv-venv/bin/python \
    PYTHONPATH=/opt/worker/src:/opt/hinerv \
    PATH=/opt/venv/bin:$PATH \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1
USER root
COPY --from=source --chown=smcp:smcp /opt/hinerv /opt/hinerv
COPY --from=builder --chown=smcp:smcp /opt/hinerv-venv /opt/hinerv-venv
COPY --chown=smcp:smcp services/compression-worker/src /opt/worker/src
RUN chown -R smcp:smcp /opt/hinerv /opt/hinerv-venv /opt/worker/src \
    && find /opt/hinerv /opt/hinerv-venv /opt/worker/src -type d -exec chmod 0555 {} + \
    && find /opt/hinerv /opt/hinerv-venv /opt/worker/src -type f -exec chmod 0444 {} + \
    && chmod 0555 /opt/hinerv-venv/bin/* \
    && /opt/hinerv-venv/bin/python -c \
      "import torchac.torchac as impl; from compression.codec_utils import _safe_extract_archive; assert impl.torchac_backend and _safe_extract_archive"
USER smcp
