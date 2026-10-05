#!/usr/bin/env bash
# Thin project-owned wrapper around the friday harness's sync command. See
# .friday/setup/harness_sync.sh for what `push`/`pull` actually do.
set -euo pipefail

SYNC_SCRIPT="$(dirname "$0")/.friday/setup/harness_sync.sh"

if [ ! -e "$SYNC_SCRIPT" ]; then
  cat >&2 <<'EOF'
This project uses the friday multi-agent harness, which lives in the
.friday git submodule — and that submodule is not currently checked out.

Fix it with:

  git submodule update --init --recursive

Then re-run this script.
EOF
  exit 1
fi

exec "$SYNC_SCRIPT" "$@"
