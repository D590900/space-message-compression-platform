# syntax=docker/dockerfile:1.12
FROM debian:bookworm-slim@sha256:abd67ffcfa541b485a3dff59865ab629aa048a6c613e639d36e7456b0b229241 AS source
ARG LIVEPORTRAIT_COMMIT=9b294b3d0536135442ea73cb01e6cb3ca7029dd3
ARG LIVEPORTRAIT_ARCHIVE_SHA256=14db8304a3eb98461ec5c19f95a1b46b996ea7daa9cbbcf113b9139d60e0f3be
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && curl --fail --location --proto '=https' --tlsv1.2 \
      --output /tmp/liveportrait.tar.gz \
      "https://codeload.github.com/KlingAIResearch/LivePortrait/tar.gz/${LIVEPORTRAIT_COMMIT}" \
    && echo "${LIVEPORTRAIT_ARCHIVE_SHA256}  /tmp/liveportrait.tar.gz" | sha256sum --check --strict \
    && mkdir -p /tmp/upstream /opt/liveportrait/src/modules /opt/liveportrait/src/utils \
    && tar --extract --gzip --file /tmp/liveportrait.tar.gz \
      --directory /tmp/upstream --strip-components=1 \
    && install -m 0444 /tmp/upstream/LICENSE /opt/liveportrait/LICENSE \
    && install -m 0444 /dev/null /opt/liveportrait/src/__init__.py \
    && install -m 0444 /tmp/upstream/src/modules/__init__.py /opt/liveportrait/src/modules/__init__.py \
    && install -m 0444 /tmp/upstream/src/modules/appearance_feature_extractor.py /opt/liveportrait/src/modules/appearance_feature_extractor.py \
    && install -m 0444 /tmp/upstream/src/modules/convnextv2.py /opt/liveportrait/src/modules/convnextv2.py \
    && install -m 0444 /tmp/upstream/src/modules/dense_motion.py /opt/liveportrait/src/modules/dense_motion.py \
    && install -m 0444 /tmp/upstream/src/modules/motion_extractor.py /opt/liveportrait/src/modules/motion_extractor.py \
    && install -m 0444 /tmp/upstream/src/modules/spade_generator.py /opt/liveportrait/src/modules/spade_generator.py \
    && install -m 0444 /tmp/upstream/src/modules/util.py /opt/liveportrait/src/modules/util.py \
    && install -m 0444 /tmp/upstream/src/modules/warping_network.py /opt/liveportrait/src/modules/warping_network.py \
    && install -m 0444 /tmp/upstream/src/utils/__init__.py /opt/liveportrait/src/utils/__init__.py \
    && install -m 0444 /tmp/upstream/src/utils/camera.py /opt/liveportrait/src/utils/camera.py \
    && test "$(find /opt/liveportrait/src -type f | wc -l)" = 11 \
    && ! find /opt/liveportrait -iname '*insightface*' -o -iname '*crop*' -o -iname '*landmark*' | grep .

FROM ghcr.io/d590900/smcp-encodec-runtime@sha256:aee93174fab26f4890481db6fe9addbd1ad8c211bcdcf17cd26f1ebfc6dca653
ARG VCS_REF=unknown
ARG VERSION=development
LABEL org.opencontainers.image.source="https://github.com/D590900/space-message-compression-platform" \
      org.opencontainers.image.revision="$VCS_REF" \
      org.opencontainers.image.version="$VERSION" \
      org.opencontainers.image.licenses="Apache-2.0 AND MIT" \
      org.opencontainers.image.title="SMCP detector-free LivePortrait CPU runtime"
ENV SMCP_LIVEPORTRAIT_ROOT=/opt/liveportrait \
    SMCP_LIVEPORTRAIT_PYTHON=/opt/encodec-venv/bin/python \
    SMCP_MODEL_CACHE=/var/lib/smcp/models \
    PYTHONPATH=/opt/worker/src:/opt/liveportrait \
    PATH=/opt/venv/bin:$PATH
USER root
COPY --from=source --chown=smcp:smcp /opt/liveportrait /opt/liveportrait
COPY --chown=smcp:smcp services/compression-worker/src /opt/worker/src
RUN /opt/encodec-venv/bin/python -c \
      "import torch, yaml; from src.modules.appearance_feature_extractor import AppearanceFeatureExtractor; from src.modules.motion_extractor import MotionExtractor; from src.modules.spade_generator import SPADEDecoder; from src.modules.warping_network import WarpingNetwork; from smcp_worker.liveportrait_runtime import pack_container, unpack_container; assert torch.__version__ == '2.6.0+cpu'; assert yaml; assert AppearanceFeatureExtractor and MotionExtractor and SPADEDecoder and WarpingNetwork and pack_container and unpack_container" \
    && test ! -e /var/lib/smcp/models/liveportrait \
    && test ! -e /opt/liveportrait/src/utils/cropper.py \
    && ! find /opt/liveportrait -iname '*insightface*' -o -iname '*landmark*' | grep . \
    && chown -R smcp:smcp /opt/liveportrait /opt/worker/src \
    && find /opt/liveportrait /opt/worker/src -type d -exec chmod 0555 {} + \
    && find /opt/liveportrait /opt/worker/src -type f -exec chmod 0444 {} +
USER smcp
