# syntax=docker/dockerfile:1.12
FROM ghcr.io/d590900/smcp-hinerv-runtime@sha256:f85cac0ea6fa2fa150ac1da882b18d64b91189a6ff4775750d7e5c61059f5bfa AS hinerv

FROM ghcr.io/d590900/smcp-coolchic-runtime@sha256:606962ae27366101361ccf555aa6664bd1a128719085a815eb398edd22e714dc
ARG VCS_REF=unknown
ARG VERSION=development
LABEL org.opencontainers.image.source="https://github.com/D590900/space-message-compression-platform" \
      org.opencontainers.image.revision="$VCS_REF" \
      org.opencontainers.image.version="$VERSION" \
      org.opencontainers.image.licenses="Apache-2.0 AND BSD-3-Clause AND MIT" \
      org.opencontainers.image.title="SMCP worker with Cool-Chic and HiNeRV per-asset neural runtimes"
ENV SMCP_HINERV_ROOT=/opt/hinerv \
    SMCP_HINERV_PYTHON=/opt/hinerv-venv/bin/python \
    PYTHONPATH=/opt/worker/src:/opt/coolchic:/opt/hinerv \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1
USER root
COPY --from=hinerv --chown=smcp:smcp /opt/hinerv /opt/hinerv
COPY --from=hinerv --chown=smcp:smcp /opt/hinerv-venv /opt/hinerv-venv
COPY --chown=smcp:smcp services/compression-worker/src /opt/worker/src
COPY --chown=smcp:smcp services/compression-worker/model-manifests /opt/worker/model-manifests
RUN /opt/venv/bin/python -m smcp_worker.model_manifest validate \
      /opt/worker/model-manifests/catalog.json \
    && /opt/venv/bin/python -c \
      "from pathlib import Path; from smcp_worker.model_manifest import load_catalog; catalog = load_catalog(Path('/opt/worker/model-manifests/catalog.json')); expected = {'coolchic-image': 'sha256:606962ae27366101361ccf555aa6664bd1a128719085a815eb398edd22e714dc', 'coolchic-video': 'sha256:606962ae27366101361ccf555aa6664bd1a128719085a815eb398edd22e714dc', 'hinerv-video': 'sha256:f85cac0ea6fa2fa150ac1da882b18d64b91189a6ff4775750d7e5c61059f5bfa'}; assert all((model := next(item for item in catalog.models if item.id == model_id)).enabled and model.decoder_image_digest == digest for model_id, digest in expected.items())" \
    && test ! -e /var/lib/smcp/models \
    && test ! -e /usr/bin/g++ \
    && test ! -e /usr/bin/ninja \
    && ! find /opt/coolchic -type f \( -name '*.pth' -o -name '*.pt' -o -name '*.ckpt' \) | grep .
USER smcp
