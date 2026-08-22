# syntax=docker/dockerfile:1.12
FROM rust:1.98.0-slim-bookworm AS capsule-build
WORKDIR /workspace
COPY Cargo.toml Cargo.lock ./
COPY crates crates
RUN cargo build --locked --release -p smcp-capsule-cli

FROM node:24.8.0-bookworm-slim AS build
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

FROM node:24.8.0-bookworm-slim AS runtime
ENV NODE_ENV=production
RUN groupadd --system smcp \
    && useradd --system --gid smcp --home-dir /opt/smcp-api smcp
WORKDIR /opt/smcp-api
COPY --from=build --chown=smcp:smcp /opt/smcp-api ./
COPY --from=capsule-build /workspace/target/release/smcp-capsule /usr/local/bin/smcp-capsule
USER smcp
EXPOSE 3001
CMD ["node", "dist/server.js"]
