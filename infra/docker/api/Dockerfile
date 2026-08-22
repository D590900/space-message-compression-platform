# syntax=docker/dockerfile:1.12
FROM rust:1.98.0-slim-bookworm@sha256:94e9efa4033213dbb70d4f665527e7ece3944ddb7ba1dd2e43f6fd6e2490af58 AS capsule-build
WORKDIR /workspace
COPY Cargo.toml Cargo.lock ./
COPY crates crates
RUN cargo build --locked --release -p smcp-capsule-cli

FROM node:24.8.0-bookworm-slim@sha256:cadbfafeb6baf87eaaffa40b3640209c4b7fd38cebde65059d15bc39cd636b85 AS build
ENV PNPM_HOME=/pnpm
ENV PATH=/pnpm:$PATH
RUN corepack enable && corepack prepare pnpm@11.6.0 --activate
WORKDIR /workspace
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml turbo.json tsconfig.base.json ./
COPY apps/api/package.json apps/api/package.json
COPY packages/schemas/package.json packages/schemas/package.json
RUN pnpm install --frozen-lockfile
COPY apps/api apps/api
COPY packages/schemas packages/schemas
RUN pnpm install --offline --frozen-lockfile --force \
    && pnpm exec tsc -b packages/schemas/tsconfig.json --force \
    && pnpm --filter @smcp/api build \
    && pnpm --filter @smcp/api deploy --prod /opt/smcp-api

FROM node:24.8.0-bookworm-slim@sha256:cadbfafeb6baf87eaaffa40b3640209c4b7fd38cebde65059d15bc39cd636b85 AS runtime
ARG VCS_REF=unknown
ARG VERSION=0.0.0-dev
LABEL org.opencontainers.image.source="https://github.com/D590900/space-message-compression-platform" \
      org.opencontainers.image.revision="$VCS_REF" \
      org.opencontainers.image.version="$VERSION" \
      org.opencontainers.image.licenses="Apache-2.0"
ENV NODE_ENV=production
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get clean \
    && find /var/lib/apt/lists -mindepth 1 -delete \
    && rm -rf /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/corepack \
    && rm -f /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/corepack \
      /usr/local/bin/pnpm /usr/local/bin/pnpx /usr/local/bin/yarn /usr/local/bin/yarnpkg \
    && groupadd --system smcp \
    && useradd --system --gid smcp --home-dir /opt/smcp-api smcp
WORKDIR /opt/smcp-api
COPY --from=build --chown=smcp:smcp /opt/smcp-api ./
COPY --from=capsule-build /workspace/target/release/smcp-capsule /usr/local/bin/smcp-capsule
USER smcp
EXPOSE 3001
CMD ["node", "dist/server.js"]
