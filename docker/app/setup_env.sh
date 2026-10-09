#!/usr/bin/env bash
# Write docker/app/.env for `docker compose --profile hw` (uid/gid, the serial device's own group,
# by-id radar ports, GUI host/port). No sudo. See docs/docker.md.
#   docker/app/setup_env.sh [--non-interactive] [--print] [--force]
# BY_ID_DIR overrides /dev/serial/by-id (tests).
set -eu

NONINT=0; PRINT=0; FORCE=0
for a in "$@"; do
  case "$a" in
    --non-interactive) NONINT=1 ;;
    --print) PRINT=1 ;;
    --force) FORCE=1 ;;
    -h|--help) sed -n '2,5p' "$0"; exit 0 ;;
    *) echo "unknown option: $a" >&2; exit 2 ;;
  esac
done

HERE=$(cd "$(dirname "$0")" && pwd)
ENV_FILE="$HERE/.env"
BY_ID_DIR=${BY_ID_DIR:-/dev/serial/by-id}

if [ "$PRINT" = 0 ] && [ -e "$ENV_FILE" ] && [ "$FORCE" = 0 ]; then
  echo "$ENV_FILE exists; use --force to overwrite (or --print to preview)." >&2
  exit 1
fi

say() { echo "$@" >&2; }
# ask PROMPT DEFAULT -> answer on stdout (the default when non-interactive or on empty input)
ask() {
  if [ "$NONINT" = 1 ]; then echo "$2"; return; fi
  printf '%s [%s]: ' "$1" "$2" >&2
  ans=""; read -r ans || true
  echo "${ans:-$2}"
}

# ---- boards: XDS110 interface 0 = CLI, interface 3 = data ----------------------------------
boards=()
for f in "$BY_ID_DIR"/*XDS110*-if00; do
  [ -e "$f" ] && boards+=("$f")
done
RADAR_CLI=""; RADAR_DATA=""
if [ "${#boards[@]}" -eq 0 ]; then
  say "warning: no XDS110 board found under $BY_ID_DIR; RADAR_CLI/RADAR_DATA left at /dev/ttyACM0 and /dev/ttyACM1."
  RADAR_CLI=/dev/ttyACM0; RADAR_DATA=/dev/ttyACM1
else
  pick=0
  if [ "${#boards[@]}" -gt 1 ] && [ "$NONINT" = 0 ]; then
    say "Several boards found:"
    i=1; for b in "${boards[@]}"; do say "  $i) ${b##*/}"; i=$((i+1)); done
    n=$(ask "Which board" 1)
    case "$n" in ''|*[!0-9]*) say "not a number: $n"; exit 2 ;; esac
    if [ "$n" -lt 1 ] || [ "$n" -gt "${#boards[@]}" ]; then say "no board $n"; exit 2; fi
    pick=$((n-1))
  elif [ "${#boards[@]}" -gt 1 ]; then
    say "note: ${#boards[@]} boards found; using the first (${boards[0]##*/})."
  fi
  RADAR_CLI=${boards[$pick]}
  RADAR_DATA=${RADAR_CLI%-if00}-if03
  [ -e "$RADAR_DATA" ] || say "warning: $RADAR_DATA does not exist (data port)."
fi

# ---- serial group --------------------------------------------------------------------------
SERIAL_GID=$(stat -L -c %g "$RADAR_CLI" 2>/dev/null || echo "")
if [ -z "$SERIAL_GID" ]; then
  SERIAL_GID=$(getent group dialout | cut -d: -f3 || true); SERIAL_GID=${SERIAL_GID:-20}
  say "warning: cannot stat $RADAR_CLI; SERIAL_GID falls back to dialout ($SERIAL_GID)."
else
  data_gid=$(stat -L -c %g "$RADAR_DATA" 2>/dev/null || echo "$SERIAL_GID")
  [ "$data_gid" = "$SERIAL_GID" ] || say "warning: the data port's group ($data_gid) differs from the CLI port's ($SERIAL_GID); only $SERIAL_GID is added."
  case " $(id -G) " in
    *" $SERIAL_GID "*) ;;
    *) say "warning: you are not in group $SERIAL_GID ($(getent group "$SERIAL_GID" | cut -d: -f1)); host-side runs need: sudo usermod -aG <group> \$USER (log out and in)." ;;
  esac
fi

# ---- GUI bind ------------------------------------------------------------------------------
GUI_HOST_DEFAULT=127.0.0.1
if command -v tailscale >/dev/null 2>&1; then
  ts=$(tailscale ip -4 2>/dev/null | head -n1 || true)
  if [ -n "$ts" ] && [ "$NONINT" = 0 ]; then
    say "Tailscale address found: $ts. Binding to it exposes the GUI (no authentication) to your tailnet."
  fi
  TS_IP=$ts
else
  TS_IP=""
fi
GUI_HOST=$(ask "GUI host (127.0.0.1 = this machine only${TS_IP:+, $TS_IP = tailnet})" "$GUI_HOST_DEFAULT")
GUI_PORT=$(ask "GUI port" 8090)
if [ "$GUI_HOST" != 127.0.0.1 ] && [ "$GUI_HOST" != localhost ]; then
  say "warning: $GUI_HOST:$GUI_PORT is unauthenticated; anyone who can reach it can start the radar."
fi

content=$(cat <<EOT
# Written by docker/app/setup_env.sh. Read by compose.yaml (see .env.example).
HOST_UID=$(id -u)
HOST_GID=$(id -g)
SERIAL_GID=$SERIAL_GID
RADAR_CLI=$RADAR_CLI
RADAR_DATA=$RADAR_DATA
GUI_HOST=$GUI_HOST
GUI_PORT=$GUI_PORT
EOT
)

if [ "$PRINT" = 1 ]; then
  echo "$content"
else
  printf '%s\n' "$content" > "$ENV_FILE"
  say "wrote $ENV_FILE"
fi
say ""
say "Start (from the repo root; keep logs with 'docker compose ... logs hw'):"
say "  mkdir -p runs CPSL_TI_Radar_cpp/config/user"
say "  docker compose -f docker/app/compose.yaml --profile hw up hw"
say "Then open http://$GUI_HOST:$GUI_PORT/"
