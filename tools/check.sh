#!/usr/bin/env bash
# The hardware-free check: C++ driver build, ctest, and the fast Python tests.
# Exits 0 only when all three pass. Run it as `./run tools/check.sh`; this is the default
# `Verify:` command for directives in this repo.
#
#   tools/check.sh           build + ctest + pytest -m "not slow"   (~3 min cold, less warm)
#   tools/check.sh --full    also the slow pytest tests
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [[ ! -f CPSL_TI_Radar_cpp/include/json/CMakeLists.txt ]]; then
  echo "check: the json submodule is missing; on the host run:" >&2
  echo "  git submodule update --init CPSL_TI_Radar_cpp/include/json" >&2
  exit 2
fi

pytest_sel=(-m "not slow")
[[ "${1:-}" == --full ]] && pytest_sel=()

echo "== cmake configure + build"
cmake -S CPSL_TI_Radar_cpp -B CPSL_TI_Radar_cpp/build -DCMAKE_BUILD_TYPE=Release >/dev/null
cmake --build CPSL_TI_Radar_cpp/build -j"$(nproc)"

echo "== ctest"
ctest --test-dir CPSL_TI_Radar_cpp/build --output-on-failure

echo "== pytest ${pytest_sel[*]}"
uv run pytest -q "${pytest_sel[@]}"

echo "== check passed"
