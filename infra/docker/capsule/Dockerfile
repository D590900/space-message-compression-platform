# syntax=docker/dockerfile:1.12
FROM rust:1.98.0-slim-bookworm AS build
WORKDIR /workspace
COPY Cargo.toml Cargo.lock ./
COPY crates crates
RUN cargo build --locked --release -p smcp-capsule-cli

FROM debian:bookworm-slim AS runtime
RUN groupadd --system smcp \
    && useradd --system --gid smcp --home-dir /opt/smcp smcp
COPY --from=build /workspace/target/release/smcp-capsule /usr/local/bin/smcp-capsule
USER smcp
ENTRYPOINT ["smcp-capsule"]

