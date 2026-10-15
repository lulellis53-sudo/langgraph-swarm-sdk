# syntax=docker/dockerfile:1
FROM rust:1-slim-bookworm AS build
WORKDIR /src
COPY Cargo.toml Cargo.lock ./
# Warm the dependency layer with a stub main, then build the real source.
RUN mkdir src && echo 'fn main() {}' > src/main.rs \
    && cargo build --release --locked && rm -rf src target/release/websearch-rs*
COPY src ./src
RUN cargo build --release --locked

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 websearch
COPY --from=build /src/target/release/websearch-rs /usr/local/bin/websearch-rs
USER websearch
ENTRYPOINT ["websearch-rs"]
