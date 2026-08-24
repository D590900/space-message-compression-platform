# syntax=docker/dockerfile:1.12
FROM ghcr.io/d590900/smcp-hinerv-runtime@sha256:f85cac0ea6fa2fa150ac1da882b18d64b91189a6ff4775750d7e5c61059f5bfa
ARG VCS_REF=unknown
ARG VERSION=development
LABEL org.opencontainers.image.source="https://github.com/D590900/space-message-compression-platform" \
      org.opencontainers.image.revision="$VCS_REF" \
      org.opencontainers.image.version="$VERSION" \
      org.opencontainers.image.licenses="Apache-2.0 AND MIT" \
      org.opencontainers.image.title="SMCP worker with HiNeRV per-video neural runtime"
USER root
COPY --chown=smcp:smcp services/compression-worker/src /opt/worker/src
COPY --chown=smcp:smcp services/compression-worker/model-manifests /opt/worker/model-manifests
RUN /opt/venv/bin/python -m smcp_worker.model_manifest validate \
      /opt/worker/model-manifests/catalog.json \
    && /opt/venv/bin/python -c \
      "from pathlib import Path; from smcp_worker.model_manifest import load_catalog; model = next(item for item in load_catalog(Path('/opt/worker/model-manifests/catalog.json')).models if item.id == 'hinerv-video'); assert model.enabled; assert model.decoder_image_digest == 'sha256:f85cac0ea6fa2fa150ac1da882b18d64b91189a6ff4775750d7e5c61059f5bfa'" \
    && test ! -e /var/lib/smcp/models \
    && test ! -e /usr/bin/g++ \
    && test ! -e /usr/bin/ninja
USER smcp
