# syntax=docker/dockerfile:1.12
FROM rust:1.98.0-slim-bookworm@sha256:94e9efa4033213dbb70d4f665527e7ece3944ddb7ba1dd2e43f6fd6e2490af58 AS capsule-build
WORKDIR /workspace
COPY Cargo.toml Cargo.lock ./
COPY crates crates
RUN cargo build --locked --release -p smcp-capsule-cli

FROM debian:bookworm-slim@sha256:88200866dfff7ea7f5cbcb6ec7c8a701889efe6fe859fe64d6990e4b07ea4171 AS ffmpeg-build
ARG FFMPEG_VERSION=9.0.1
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      build-essential ca-certificates curl gnupg libdav1d-dev libopus-dev libsvtav1enc-dev \
      nasm pkg-config xz-utils yasm zlib1g-dev \
    && mkdir -p /usr/src/ffmpeg /opt/ffmpeg \
    && curl --fail --location --proto '=https' --tlsv1.2 \
      --output /tmp/ffmpeg.tar.xz \
      "https://ffmpeg.org/releases/ffmpeg-${FFMPEG_VERSION}.tar.xz" \
    && curl --fail --location --proto '=https' --tlsv1.2 \
      --output /tmp/ffmpeg.tar.xz.asc \
      "https://ffmpeg.org/releases/ffmpeg-${FFMPEG_VERSION}.tar.xz.asc" \
    && curl --fail --location --proto '=https' --tlsv1.2 \
      --output /tmp/ffmpeg-devel.asc https://ffmpeg.org/ffmpeg-devel.asc \
    && gpg --batch --import /tmp/ffmpeg-devel.asc \
    && gpg --batch --with-colons --fingerprint B4322F04D67658D8 \
      | grep -F 'fpr:::::::::FCF986EA15E6E293A5644F10B4322F04D67658D8:' \
    && gpg --batch --verify /tmp/ffmpeg.tar.xz.asc /tmp/ffmpeg.tar.xz \
    && tar --extract --xz --file /tmp/ffmpeg.tar.xz \
      --directory /usr/src/ffmpeg --strip-components=1 \
    && cd /usr/src/ffmpeg \
    && ./configure \
      --prefix=/opt/ffmpeg \
      --disable-debug \
      --disable-doc \
      --disable-ffplay \
      --disable-gpl \
      --disable-network \
      --enable-libdav1d \
      --enable-libopus \
      --enable-libsvtav1 \
      --enable-zlib \
    && make -j"$(nproc)" \
    && make install

FROM python:3.12.13-slim-bookworm@sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2 AS python-build
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv
COPY --from=ghcr.io/astral-sh/uv:0.11.21@sha256:ff07b86af50d4d9391d9daf4ff89ce427bc544f9aae87057e69a1cc0aa369946 /uv /uvx /bin/
WORKDIR /opt/worker
COPY services/compression-worker/pyproject.toml services/compression-worker/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY services/compression-worker/src src
COPY services/compression-worker/model-manifests model-manifests
RUN uv sync --frozen --no-dev \
    && /opt/venv/bin/python -m smcp_worker.model_manifest validate model-manifests/catalog.json

FROM python:3.12.13-slim-bookworm@sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2 AS runtime
ARG VCS_REF=unknown
ARG VERSION=0.0.0-dev
LABEL org.opencontainers.image.source="https://github.com/D590900/space-message-compression-platform" \
      org.opencontainers.image.revision="$VCS_REF" \
      org.opencontainers.image.version="$VERSION" \
      org.opencontainers.image.licenses="Apache-2.0"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends \
      ca-certificates libavif-bin libdav1d6 libjxl-tools libmagic1 libopus0 libsvtav1enc1 \
    && apt-get clean \
    && find /var/lib/apt/lists -mindepth 1 -delete \
    && groupadd --system smcp \
    && useradd --system --gid smcp --home-dir /opt/worker smcp
COPY --from=ffmpeg-build /opt/ffmpeg/bin/ffmpeg /opt/ffmpeg/bin/ffprobe /usr/local/bin/
COPY --from=capsule-build /workspace/target/release/smcp-capsule /usr/local/bin/smcp-capsule
WORKDIR /opt/worker
COPY --from=python-build --chown=smcp:smcp /opt/venv /opt/venv
COPY --from=python-build --chown=smcp:smcp /opt/worker/src src
COPY --from=python-build --chown=smcp:smcp /opt/worker/model-manifests model-manifests
USER smcp
EXPOSE 8000
CMD ["smcp-worker"]
