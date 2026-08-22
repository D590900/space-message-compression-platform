# syntax=docker/dockerfile:1.12
FROM rust:1.98.0-slim-bookworm@sha256:94e9efa4033213dbb70d4f665527e7ece3944ddb7ba1dd2e43f6fd6e2490af58 AS build
WORKDIR /workspace
COPY Cargo.toml Cargo.lock ./
COPY crates crates
RUN cargo build --locked --release -p smcp-capsule-cli

FROM debian:bookworm-slim@sha256:abd67ffcfa541b485a3dff59865ab629aa048a6c613e639d36e7456b0b229241 AS runtime
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get clean \
    && find /var/lib/apt/lists -mindepth 1 -delete \
    && groupadd --system smcp \
    && useradd --system --gid smcp --home-dir /opt/smcp smcp
COPY --from=build /workspace/target/release/smcp-capsule /usr/local/bin/smcp-capsule
USER smcp
ENTRYPOINT ["smcp-capsule"]
