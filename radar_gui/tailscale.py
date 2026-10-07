"""Opt-in tailnet access.

Default `--tailscale` (bind mode): also listen on this machine's Tailscale IPv4 address
(plain HTTP, same port; never 0.0.0.0, no Tailscale privileges or admin changes needed).
`--tailscale-serve`: proxy via `tailscale serve` (HTTPS :443, tailnet-only, never `funnel`;
needs HTTPS certificates enabled and operator rights) and remove the mapping on exit.
Every failure degrades to local-only with the reason printed.
"""
import json
import subprocess

HTTPS_PORT = 443


def _run(args, timeout=15):
    return subprocess.run(["tailscale", *args], capture_output=True, text=True, timeout=timeout)


def _err(r):
    return (r.stderr or r.stdout or "").strip().splitlines()[-1:] or ["(no output)"]


def _status(run, flag):
    """-> (status dict, None) or (None, reason)."""
    try:
        r = run(["status", "--json"])
    except FileNotFoundError:
        return None, "`tailscale` not found on PATH; install it from https://tailscale.com/download"
    except (subprocess.TimeoutExpired, OSError) as e:
        return None, f"`tailscale status` failed ({e})"
    try:
        st = json.loads(r.stdout)
    except ValueError:
        st = None
    if r.returncode != 0 or not isinstance(st, dict):
        return None, f"tailscale daemon not reachable ({_err(r)[0]}); is tailscaled running?"
    if st.get("BackendState") != "Running":
        return None, f"tailscale is {st.get('BackendState')!r}, not Running; run `tailscale up` (log in)"
    return st, None


def bind_addresses(run=_run):
    """Bind mode: -> (tailscale_ipv4, short_name_or_None, None) or (None, None, reason)."""
    st, why = _status(run, "--tailscale")
    if st is None:
        return None, None, why
    me = st.get("Self") or {}
    ips = [i for i in (me.get("TailscaleIPs") or []) if isinstance(i, str) and "." in i]
    if not ips:
        try:
            r = run(["ip", "-4"])
            ips = [l.strip() for l in (r.stdout or "").splitlines() if l.strip().count(".") == 3] if r.returncode == 0 else []
        except (subprocess.TimeoutExpired, OSError):
            ips = []
    if not ips:
        return None, None, "no Tailscale IPv4 address found for this node"
    dns = (me.get("DNSName") or "").rstrip(".")
    return ips[0], (dns.split(".")[0] or None), None


def bind_sockets(local_host, port, ts_ip):
    """Pre-bound listening sockets: local_host and the Tailscale IP, same port."""
    import socket
    socks = []
    try:
        for h in (local_host, ts_ip):
            if h in ("0.0.0.0", "", "::"):
                raise ValueError("refusing to bind a wildcard address")
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            socks.append(s)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((h, port))
            s.set_inheritable(True)
    except BaseException:
        for s in socks:
            s.close()
        raise
    return socks


class TailscaleServe:
    """start() -> tailnet URL or None (reason printed); stop() removes only our mapping."""

    def __init__(self, port, run=_run):
        self.port = port
        self._run = run
        self.active = False

    def start(self):
        st, why = _status(self._run, "--tailscale-serve")
        if st is None:
            print(f"radar_gui: --tailscale-serve: {why}. Serving locally only.", flush=True)
            return None
        me = st.get("Self") or {}
        dns = (me.get("DNSName") or "").rstrip(".")
        if not st.get("CertDomains"):
            print("radar_gui: --tailscale-serve: HTTPS certificates are not enabled for your tailnet "
                  "- enable them in the Tailscale admin console (DNS -> HTTPS Certificates) or use "
                  "plain --tailscale. Serving locally only.", flush=True)
            return None
        if not dns:
            print("radar_gui: --tailscale-serve: no DNSName for this node (enable MagicDNS). "
                  "Serving locally only.", flush=True)
            return None
        try:
            cur = self._run(["serve", "status", "--json"])
            cfg = json.loads(cur.stdout or "{}") if cur.returncode == 0 else None
        except (ValueError, subprocess.TimeoutExpired, OSError):
            cfg = None
        if cfg:  # existing serve config: never clobber it
            print("radar_gui: --tailscale-serve: a tailscale serve config already exists "
                  "(see `tailscale serve status`); not touching it. Serving locally only.", flush=True)
            return None
        try:
            r = self._run(["serve", "--bg", "--yes", f"--https={HTTPS_PORT}", str(self.port)])
        except (subprocess.TimeoutExpired, OSError) as e:
            print(f"radar_gui: --tailscale-serve: `tailscale serve` failed ({e}). Serving locally only.", flush=True)
            return None
        if r.returncode != 0:
            msg = ((r.stderr or r.stdout or "").strip() or "(no output)").replace("\n", " | ")
            hint = (" Fix: run once `sudo tailscale set --operator=$USER`."
                    if any(w in (r.stderr + r.stdout).lower() for w in ("denied", "operator", "permission"))
                    else "")
            print(f"radar_gui: --tailscale-serve: `tailscale serve` failed: {msg}.{hint} Serving locally only.", flush=True)
            return None
        self.active = True
        url = f"https://{dns}/"
        print(f"GUI on tailnet: {url}  (no authentication: tailnet members can reach it)", flush=True)
        return url

    def stop(self):
        if not self.active:
            return
        self.active = False
        manual = "run `tailscale serve --https=443 off` (or `tailscale serve reset`)"
        try:
            r = self._run(["serve", f"--https={HTTPS_PORT}", "off"])
            if r.returncode == 0:
                return
            # `off` may be unsupported; start() only sets active when the serve config
            # was empty beforehand, so the config is ours alone and reset is safe.
            r = self._run(["serve", "reset"])
            if r.returncode != 0:
                print(f"radar_gui: could not remove tailscale serve mapping ({_err(r)[0]}); {manual}.", flush=True)
        except (subprocess.TimeoutExpired, OSError) as e:
            print(f"radar_gui: could not remove tailscale serve mapping ({e}); {manual}.", flush=True)
