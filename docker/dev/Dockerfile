# CPSL TI Radar dev container: the toolchain that ./run sends builds, tests and scripts into.
# Claude Code and your editor stay on the host; only commands run in here. See docs/docker.md
# ("Dev container"). Separate from docker/app/ (the runtime image) and from firmware_dev's image.
#
# Built by ./run on first use (or `./run --rebuild`), never by hand: ./run passes your uid/gid
# so files the container writes into the bind-mounted repo are yours.

ARG UV_VERSION=0.12.23
FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

FROM ubuntu:24.04 AS dev
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential cmake git ca-certificates python3.12 \
 && rm -rf /var/lib/apt/lists/*
COPY --from=uv /uv /uvx /usr/local/bin/

# One user whose uid/gid match the owner of the repo on the host. The base image's
# `ubuntu` user (uid 1000) is removed first so uid 1000 is free for you.
ARG HOST_UID=1000
ARG HOST_GID=1000
RUN userdel -r ubuntu 2>/dev/null; \
    (getent group "${HOST_GID}" >/dev/null || groupadd -g "${HOST_GID}" dev) \
 && useradd -m -u "${HOST_UID}" -g "${HOST_GID}" -s /bin/bash dev \
 && mkdir -p /home/dev/venv /home/dev/.cache/uv \
 && chown -R "${HOST_UID}:${HOST_GID}" /home/dev

# The project venv and the uv cache live in named volumes (compose.yaml), not in the repo's
# .venv, so a host venv and the container's never overwrite each other. `uv run` syncs the venv
# from uv.lock on every call, so a lockfile change needs no rebuild.
ENV UV_PROJECT_ENVIRONMENT=/home/dev/venv \
    UV_CACHE_DIR=/home/dev/.cache/uv \
    UV_PYTHON_PREFERENCE=only-system \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1
USER dev
CMD ["sleep", "infinity"]
