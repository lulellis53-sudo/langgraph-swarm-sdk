FROM mcr.microsoft.com/devcontainers/python:3.14-bookworm

ARG UV_VERSION=0.6.14
USER root
RUN curl -LsSf "https://astral.sh/uv/${UV_VERSION}/install.sh" | sh \
    && mv /root/.local/bin/uv /usr/local/bin/uv \
    && mv /root/.local/bin/uvx /usr/local/bin/uvx \
    && apt-get update \
    && apt-get install -y --no-install-recommends git-lfs ripgrep fd-find \
    && rm -rf /var/lib/apt/lists/*

USER vscode
