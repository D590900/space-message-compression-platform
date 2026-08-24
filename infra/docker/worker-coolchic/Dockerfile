# syntax=docker/dockerfile:1.12
FROM ghcr.io/d590900/smcp-coolchic-runtime@sha256:606962ae27366101361ccf555aa6664bd1a128719085a815eb398edd22e714dc
ARG VCS_REF=unknown
ARG VERSION=development
LABEL org.opencontainers.image.source="https://github.com/D590900/space-message-compression-platform" \
      org.opencontainers.image.revision="$VCS_REF" \
      org.opencontainers.image.version="$VERSION" \
      org.opencontainers.image.licenses="Apache-2.0 AND BSD-3-Clause" \
      org.opencontainers.image.title="SMCP worker with Cool-Chic overfit image and video runtime"
USER root
COPY --chown=smcp:smcp services/compression-worker/src /opt/worker/src
COPY --chown=smcp:smcp services/compression-worker/model-manifests /opt/worker/model-manifests
RUN /opt/venv/bin/python -m smcp_worker.model_manifest validate \
      /opt/worker/model-manifests/catalog.json \
    && /opt/venv/bin/python -c \
      "from pathlib import Path; from smcp_worker.model_manifest import load_catalog; catalog = load_catalog(Path('/opt/worker/model-manifests/catalog.json')); models = [next(item for item in catalog.models if item.id == model_id) for model_id in ('coolchic-image', 'coolchic-video')]; assert all(model.enabled and model.decoder_image_digest == 'sha256:606962ae27366101361ccf555aa6664bd1a128719085a815eb398edd22e714dc' for model in models)" \
    && test ! -e /var/lib/smcp/models \
    && ! find /opt/coolchic -type f \( -name '*.pth' -o -name '*.pt' -o -name '*.ckpt' \) | grep .
USER smcp
