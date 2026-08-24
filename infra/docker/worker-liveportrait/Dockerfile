# syntax=docker/dockerfile:1.12
FROM ghcr.io/d590900/smcp-liveportrait-runtime@sha256:b0805d6919914e3ed1a2190a48227aa5f56377e7d2735073a78718950d43c5c7
ARG VCS_REF=unknown
ARG VERSION=development
LABEL org.opencontainers.image.source="https://github.com/D590900/space-message-compression-platform" \
      org.opencontainers.image.revision="$VCS_REF" \
      org.opencontainers.image.version="$VERSION" \
      org.opencontainers.image.licenses="Apache-2.0 AND MIT" \
      org.opencontainers.image.title="SMCP worker with detector-free LivePortrait CPU runtime"
USER root
COPY --chown=smcp:smcp services/compression-worker/src /opt/worker/src
COPY --chown=smcp:smcp services/compression-worker/model-manifests /opt/worker/model-manifests
RUN /opt/venv/bin/python -m smcp_worker.model_manifest validate \
      /opt/worker/model-manifests/catalog.json \
    && /opt/venv/bin/python -c \
      "from pathlib import Path; from smcp_worker.model_manifest import load_catalog; catalog = load_catalog(Path('/opt/worker/model-manifests/catalog.json')); model = next(item for item in catalog.models if item.id == 'liveportrait'); assert model.enabled; assert model.decoder_image_digest == 'sha256:b0805d6919914e3ed1a2190a48227aa5f56377e7d2735073a78718950d43c5c7'" \
    && test ! -e /var/lib/smcp/models/liveportrait \
    && test ! -e /opt/liveportrait/src/utils/cropper.py \
    && ! find /opt/liveportrait -iname '*insightface*' -o -iname '*landmark*' | grep .
USER smcp
