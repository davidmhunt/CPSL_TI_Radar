"""Opt-in `--tailscale` support: proxy the local GUI onto the tailnet via `tailscale serve`.

The server stays on 127.0.0.1; only a tailnet-only HTTPS mapping on :443 is added
(never `funnel`) and removed again on exit. Every failure degrades to local-only.
"""
import json
import subprocess

HTTPS_PORT = 443


def _run(args, timeout=15):
    return subprocess.run(["tailscale", *args], capture_output=True, text=True, timeout=timeout)


def _err(r):
    return (r.stderr or r.stdout or "").strip().splitlines()[-1:] or ["(no output)"]


class TailscaleServe:
    """start() -> tailnet URL or None (reason printed); stop() removes only our mapping."""

    def __init__(self, port, run=_run):
        self.port = port
        self._run = run
        self.active = False

    def start(self):
        try:
            r = self._run(["status", "--json"])
        except FileNotFoundError:
            print("radar_gui: --tailscale: `tailscale` not found on PATH; install it from "
                  "https://tailscale.com/download. Serving locally only.", flush=True)
            return None
        except (subprocess.TimeoutExpired, OSError) as e:
            print(f"radar_gui: --tailscale: `tailscale status` failed ({e}). Serving locally only.", flush=True)
            return None
        try:
            st = json.loads(r.stdout)
        except ValueError:
            st = None
        if r.returncode != 0 or not isinstance(st, dict):
            print(f"radar_gui: --tailscale: tailscale daemon not reachable ({_err(r)[0]}). "
                  "Is tailscaled running? Serving locally only.", flush=True)
            return None
        if st.get("BackendState") != "Running":
            print(f"radar_gui: --tailscale: tailscale is {st.get('BackendState')!r}, not Running; "
                  "run `tailscale up` (log in). Serving locally only.", flush=True)
            return None
        dns = ((st.get("Self") or {}).get("DNSName") or "").rstrip(".")
        if not dns:
            print("radar_gui: --tailscale: no DNSName for this node (enable MagicDNS/HTTPS in the "
                  "tailnet admin console). Serving locally only.", flush=True)
            return None
        try:
            cur = self._run(["serve", "status", "--json"])
            cfg = json.loads(cur.stdout or "{}") if cur.returncode == 0 else None
        except (ValueError, subprocess.TimeoutExpired, OSError):
            cfg = None
        if cfg:  # existing serve config: never clobber it
            print("radar_gui: --tailscale: a tailscale serve config already exists "
                  "(see `tailscale serve status`); not touching it. Serving locally only.", flush=True)
            return None
        try:
            r = self._run(["serve", "--bg", "--yes", f"--https={HTTPS_PORT}", str(self.port)])
        except (subprocess.TimeoutExpired, OSError) as e:
            print(f"radar_gui: --tailscale: `tailscale serve` failed ({e}). Serving locally only.", flush=True)
            return None
        if r.returncode != 0:
            msg = _err(r)[0]
            hint = (" Fix: run once `sudo tailscale set --operator=$USER`."
                    if any(w in (r.stderr + r.stdout).lower() for w in ("denied", "operator", "permission"))
                    else "")
            print(f"radar_gui: --tailscale: `tailscale serve` failed: {msg}.{hint} Serving locally only.", flush=True)
            return None
        self.active = True
        url = f"https://{dns}/"
        print(f"GUI on tailnet: {url}  (no authentication: tailnet members can reach it)", flush=True)
        return url

    def stop(self):
        if not self.active:
            return
        self.active = False
        try:
            r = self._run(["serve", f"--https={HTTPS_PORT}", "off"])
            if r.returncode != 0:
                print(f"radar_gui: could not remove tailscale serve mapping ({_err(r)[0]}); "
                      "run `tailscale serve --https=443 off`.", flush=True)
        except (subprocess.TimeoutExpired, OSError) as e:
            print(f"radar_gui: could not remove tailscale serve mapping ({e}); "
                  "run `tailscale serve --https=443 off`.", flush=True)
