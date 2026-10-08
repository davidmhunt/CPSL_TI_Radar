# syntax=docker/dockerfile:1
# CPSL TI Radar: C++ driver + web GUI. Build from the repo root:
#   docker compose -f docker/app/compose.yaml build
# Separate from firmware_dev's build image and from the harness dev container.

ARG UV_VERSION=0.12.23

# ---- build: compile the driver (Release) and run ctest; the build dir stays inside the image ----
FROM ubuntu:24.04 AS build
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential cmake ca-certificates \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY CPSL_TI_Radar_cpp CPSL_TI_Radar_cpp
COPY tests tests
RUN cmake -S CPSL_TI_Radar_cpp -B /build -DCMAKE_BUILD_TYPE=Release \
 && cmake --build /build -j"$(nproc)"

# ---- test: ctest inside the image (also forced by the runtime stage, so a default build always runs it) ----
FROM build AS test
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN ctest --test-dir /build --output-on-failure 2>&1 | tee /ctest.log

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# ---- runtime ----
FROM ubuntu:24.04 AS runtime
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3.12 \
 && rm -rf /var/lib/apt/lists/* \
 && userdel -r ubuntu 2>/dev/null; useradd -m -u 1000 -s /bin/bash radar
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON_PREFERENCE=only-system UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy \
    PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY radar_gui radar_gui
COPY tools/bench tools/bench
COPY tools/setup tools/setup
COPY tests/fakes tests/fakes
COPY tests/fixtures/replay tests/fixtures/replay
COPY CPSL_TI_Radar_cpp/config CPSL_TI_Radar_cpp/config
# the driver sits where radar_gui looks by default (CPSL_TI_Radar_cpp/build/CPSL_TI_Radar_CPP)
COPY --from=build /build/CPSL_TI_Radar_CPP CPSL_TI_Radar_cpp/build/CPSL_TI_Radar_CPP
# ties the ctest run to this stage: the runtime image cannot be built if the tests fail
COPY --from=test /ctest.log /usr/share/doc/cpsl-ctest.log
RUN mkdir -p runs/gui CPSL_TI_Radar_cpp/config/user && chown -R radar:radar runs CPSL_TI_Radar_cpp/config/user
USER radar
EXPOSE 8090
# 0.0.0.0 is the container side; compose publishes it on 127.0.0.1 only
CMD ["python", "-m", "radar_gui", "--host", "0.0.0.0", "--port", "8090"]
