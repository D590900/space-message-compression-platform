# syntax=docker/dockerfile:1.12
FROM ghcr.io/d590900/smcp-cod-lite-runtime@sha256:791454206faacd38b9b4126f89a998a2d2ff9761f8cd1dcdc81e7030022035cf
ARG VCS_REF=unknown
ARG VERSION=development
LABEL org.opencontainers.image.source="https://github.com/D590900/space-message-compression-platform" \
      org.opencontainers.image.revision="$VCS_REF" \
      org.opencontainers.image.version="$VERSION" \
      org.opencontainers.image.licenses="Apache-2.0 AND MIT" \
      org.opencontainers.image.title="SMCP worker with CoD-Lite CUDA runtime"
USER root
COPY --chown=smcp:smcp services/compression-worker/model-manifests /opt/worker/model-manifests
RUN /opt/venv/bin/python -m smcp_worker.model_manifest validate \
      /opt/worker/model-manifests/catalog.json \
    && /opt/venv/bin/python -c \
      "from pathlib import Path; from smcp_worker.model_manifest import load_catalog; catalog = load_catalog(Path('/opt/worker/model-manifests/catalog.json')); model = next(item for item in catalog.models if item.id == 'cod-lite'); assert model.enabled; assert model.decoder_image_digest == 'sha256:791454206faacd38b9b4126f89a998a2d2ff9761f8cd1dcdc81e7030022035cf'" \
    && test ! -e /var/lib/smcp/models/cod-lite
USER smcp
