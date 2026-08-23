# syntax=docker/dockerfile:1.12
FROM ghcr.io/d590900/smcp-encodec-runtime@sha256:aee93174fab26f4890481db6fe9addbd1ad8c211bcdcf17cd26f1ebfc6dca653
ARG VCS_REF=unknown
ARG VERSION=development
LABEL org.opencontainers.image.source="https://github.com/D590900/space-message-compression-platform" \
      org.opencontainers.image.revision="$VCS_REF" \
      org.opencontainers.image.version="$VERSION" \
      org.opencontainers.image.licenses="Apache-2.0 AND MIT" \
      org.opencontainers.image.title="SMCP worker with EnCodec 48 kHz CPU runtime"
USER root
COPY --chown=smcp:smcp services/compression-worker/src /opt/worker/src
COPY --chown=smcp:smcp services/compression-worker/model-manifests /opt/worker/model-manifests
RUN /opt/venv/bin/python -m smcp_worker.model_manifest validate \
      /opt/worker/model-manifests/catalog.json \
    && /opt/venv/bin/python -c \
      "from pathlib import Path; from smcp_worker.model_manifest import load_catalog; catalog = load_catalog(Path('/opt/worker/model-manifests/catalog.json')); model = next(item for item in catalog.models if item.id == 'encodec'); assert model.enabled; assert model.decoder_image_digest == 'sha256:aee93174fab26f4890481db6fe9addbd1ad8c211bcdcf17cd26f1ebfc6dca653'" \
    && test ! -e /var/lib/smcp/models/encodec
USER smcp
