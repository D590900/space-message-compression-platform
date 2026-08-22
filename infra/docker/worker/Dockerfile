# syntax=docker/dockerfile:1.12
FROM python:3.12.13-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libmagic1 libavif-bin libjxl-tools \
    && apt-get clean \
    && find /var/lib/apt/lists -mindepth 1 -delete \
    && groupadd --system smcp \
    && useradd --system --gid smcp --home-dir /opt/worker smcp
COPY --from=ghcr.io/astral-sh/uv:0.11.21 /uv /uvx /bin/
WORKDIR /opt/worker
COPY services/compression-worker/pyproject.toml services/compression-worker/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY services/compression-worker/src src
COPY services/compression-worker/model-manifests model-manifests
RUN uv sync --frozen --no-dev \
    && chown -R smcp:smcp /opt/worker /opt/venv
USER smcp
ENV PATH=/opt/venv/bin:$PATH
CMD ["smcp-worker"]
