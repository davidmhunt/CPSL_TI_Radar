#!/usr/bin/env python3
"""Check (and optionally fix) the host prerequisites for CPSL TI Radar bench runs.

Default mode is a read-only *doctor*: every prerequisite is reported as OK,
MISSING, WARN or N-A, with the exact command that fixes it.  Exit status is 0
when nothing is MISSING and 1 otherwise, so scripts and CI can gate on it.

    uv run tools/setup/host_setup.py --nic enp3s0           # doctor
    uv run tools/setup/host_setup.py --nic enp3s0 --apply --dry-run
    uv run tools/setup/host_setup.py --nic enp3s0 --apply   # asks once per check

Checks: ``sysctl`` (net.core.rmem_max, runtime and persistent), ``dca-nic``
(192.168.33.30/24 on the DCA1000 NIC, persistent in its NetworkManager
profile), ``dialout``, ``build-type`` (Release) and, opt-in with ``--udev``, stable
``/dev/radar/<id>-cli|data`` symlinks for XDS110 and CP2105 radar boards (``<id>`` is the
USB serial, or the USB port path when boards share a serial).  ``firewall`` checks that an
active ufw lets the DCA1000 (``--fpga-ip``) in on the NIC: the board replies from UDP port
1024 to host port 4096, which conntrack does not see as a reply, so a default-DROP ufw
silently eats SYSTEM_CONNECT.  ``/etc/ufw/user.rules`` is root-only, so without root the
check reports WARN (cannot verify), never a guessed MISSING.

``--apply`` never runs as root itself: it calls ``sudo`` per command, so every
privilege prompt is visible, and it re-checks each fix after running it.
``--dry-run`` prints the commands and file contents and runs nothing.  The
DCA1000 NIC is never picked for you: pass ``--nic``, or confirm the single
candidate when ``--apply`` asks.

Python stdlib only.  The checks are pure functions over a ``Host`` object;
tests substitute a fake host fed with captured command output.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import shlex
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

try:
    REPO = Path(__file__).resolve().parents[2]
except (NameError, IndexError):   # piped via `python3 -` (no __file__), e.g. run inside a container
    REPO = None
if REPO is not None and not (REPO / "tools/bench/bench_lib.py").is_file():
    REPO = None                   # __file__ was '<stdin>' resolved against the cwd
if REPO is not None:
    sys.path.insert(0, str(REPO / "tools/bench"))
    from bench_lib import parse_cmake_cache  # noqa: E402
else:
    def parse_cmake_cache(text: str) -> dict:
        """Just CMAKE_BUILD_TYPE (bench_lib is not importable without the repo path)."""
        return {k: l.split("=", 1)[1] for l in text.splitlines()
                if not l.startswith(("//", "#")) and ":" in l and "=" in l
                for k in [l.split(":", 1)[0]] if k == "CMAKE_BUILD_TYPE"}

DEFAULT_DRIVER = REPO / "CPSL_TI_Radar_cpp/build/CPSL_TI_Radar_CPP" if REPO else None
RMEM_TARGET = 134217728
RMEM_KEY = "net.core.rmem_max"
SYSCTL_DROPIN = "/etc/sysctl.d/99-radar.conf"
# systemd-sysctl / `sysctl --system` search order: a basename in an earlier
# directory shadows the same basename later; files then apply in basename order.
SYSCTL_DIRS = ("/etc/sysctl.d", "/run/sysctl.d", "/usr/local/lib/sysctl.d",
               "/usr/lib/sysctl.d", "/lib/sysctl.d")
DCA_HOST_CIDR = "192.168.33.30/24"
DCA_SUBNET_PREFIX = "192.168.33."
DCA_FPGA_IP = "192.168.33.180"
UDEV_RULES = "/etc/udev/rules.d/99-radar.rules"
UFW_CONF = "/etc/ufw/ufw.conf"          # world-readable: ENABLED=yes|no
UFW_DEFAULTS = "/etc/default/ufw"       # world-readable: DEFAULT_INPUT_POLICY
UFW_USER_RULES = "/etc/ufw/user.rules"  # root-only (0640): the rules themselves
DCA_PORT = "4096"                       # host-side port the DCA1000 answers to
# model -> (USB vendor id, product id, {interface number: role})
RADAR_MODELS = {
    "xds110": ("0451", "bef3", {"00": "cli", "03": "data"}),   # ttyACM*
    "cp2105": ("10c4", "ea70", {"00": "cli", "01": "data"}),   # ttyUSB*
}
_SAFE_SERIAL = re.compile(r"^[A-Za-z0-9._-]+$")

OK, MISSING, WARN, NA = "OK", "MISSING", "WARN", "N-A"


# ---------------------------------------------------------------- data types

@dataclass
class Step:
    """One command of a fix.  ``stdin`` is file content piped to ``sudo tee``."""

    argv: list
    stdin: str | None = None
    comment: str | None = None  # display-only, e.g. the NM profile name behind a uuid

    def display(self) -> str:
        cmd = shlex.join(self.argv)
        if self.stdin is None:
            return cmd + (f"  # {self.comment}" if self.comment else "")
        body = self.stdin if self.stdin.endswith("\n") else self.stdin + "\n"
        return f"{cmd} > /dev/null <<'EOF'\n{body}EOF"


@dataclass
class Check:
    """Result of one prerequisite check.

    ``fix_cmds`` are what ``--apply`` runs (one confirmation per check);
    ``manual`` are commands only ever printed (never executed by the tool).
    """

    name: str
    status: str
    detail: str
    fix_cmds: list = field(default_factory=list)
    manual: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    boards: list = field(default_factory=list)   # udev check only: one dict per radar board

    def to_dict(self) -> dict:
        d = asdict(self)
        if not self.boards:
            del d["boards"]
        d["fix_cmds"] = [s.display() for s in self.fix_cmds]
        return d


class Host:
    """All I/O the checks need.  Read-only except ``execute`` (used by --apply)."""

    def read(self, path: str) -> str | None:
        try:
            return Path(path).read_text()
        except (OSError, UnicodeDecodeError):
            return None

    def listdir(self, path: str) -> list:
        try:
            return sorted(os.listdir(path))
        except OSError:
            return []

    def exists(self, path: str) -> bool:
        return os.path.exists(path)

    def realpath(self, path: str) -> str:
        return os.path.realpath(path)

    def run(self, argv: list) -> tuple:
        """(returncode, stdout); 127 if the program is not installed."""
        try:
            p = subprocess.run(argv, capture_output=True, text=True, timeout=15)
        except FileNotFoundError:
            return 127, ""
        except (OSError, subprocess.TimeoutExpired) as exc:
            return 1, f"{exc.__class__.__name__}"
        return p.returncode, p.stdout

    def user(self) -> str:
        import pwd  # not getpass: it trusts $LOGNAME/$USER, and this name reaches usermod
        return pwd.getpwuid(os.getuid()).pw_name

    def euid(self) -> int:
        return os.geteuid()

    def group_of(self, path: str) -> str | None:
        import grp
        try:
            return grp.getgrgid(os.stat(path).st_gid).gr_name
        except (OSError, KeyError):
            return None

    def execute(self, step: Step) -> int:
        """Run one fix step (no shell).  Only ever reached from --apply."""
        p = subprocess.run(step.argv, input=step.stdin, text=True,
                           stdout=subprocess.DEVNULL if step.stdin is not None else None)
        return p.returncode


# ------------------------------------------------------------------- parsers

def parse_sysctl_conf(text: str) -> list:
    """[(key, value)] from a sysctl.d file; '/' keys normalised to '.'."""
    out = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s[0] in "#;" or "=" not in s:
            continue
        key, val = s.split("=", 1)
        key = key.strip().lstrip("-").replace("/", ".")
        out.append((key, val.strip()))
    return out


def parse_ip_o_addr(text: str) -> dict:
    """iface -> [cidr] from `ip -o -4 addr show`."""
    out: dict = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) > 3 and parts[2] == "inet":
            out.setdefault(parts[1].rstrip(":"), []).append(parts[3])
    return out


def split_terse(line: str) -> list:
    """Split an `nmcli -t` line on unescaped ':' (nmcli escapes ':' and '\\')."""
    fields, cur, i = [], [], 0
    while i < len(line):
        c = line[i]
        if c == "\\" and i + 1 < len(line):
            cur.append(line[i + 1])
            i += 2
            continue
        if c == ":":
            fields.append("".join(cur))
            cur = []
        else:
            cur.append(c)
        i += 1
    fields.append("".join(cur))
    return fields


def parse_nmcli_kv(text: str) -> dict:
    """`nmcli -t -f a,b ... show` output ('field:value' lines) -> dict."""
    out = {}
    for line in text.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k] = v.replace("\\:", ":").replace("\\\\", "\\")
    return out


def parse_nmcli_con_list(text: str) -> list:
    """Rows of `nmcli -t -f NAME,UUID,TYPE,DEVICE connection show`."""
    rows = []
    for line in text.splitlines():
        f = split_terse(line)
        if len(f) >= 4:
            rows.append({"name": f[0], "uuid": f[1], "type": f[2], "device": f[3]})
    return rows


def parse_udev_props(text: str) -> dict:
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)


# -------------------------------------------------------------------- checks

def _sysctl_files(host: Host, assume: str | None = None) -> list:
    """Files `sysctl --system` reads, in order; ``assume`` is treated as existing."""
    chosen: dict = {}
    if assume:
        chosen[os.path.basename(assume)] = assume
    for d in SYSCTL_DIRS:
        for name in host.listdir(d):
            if name.endswith(".conf") and name not in chosen:
                chosen[name] = f"{d}/{name}"
    files = [chosen[k] for k in sorted(chosen)]
    reals = {host.realpath(f) for f in files}
    if host.exists("/etc/sysctl.conf") and host.realpath("/etc/sysctl.conf") not in reals:
        files.append("/etc/sysctl.conf")  # procps `sysctl --system` reads it last
    return files


def _effective(host: Host, files: list, key: str, override: dict | None = None):
    """(value, source file) of the last assignment of key, or (None, None)."""
    val, src = None, None
    for f in files:
        text = (override or {}).get(f, host.read(f)) or ""
        for k, v in parse_sysctl_conf(text):
            if k == key:
                val, src = v, f
    return val, src


def _as_int(v) -> int | None:
    try:
        return int(str(v).split()[0])
    except (TypeError, ValueError, IndexError):
        return None


def _dropin_content(existing: str | None, target: int) -> str:
    kept = [ln for ln in (existing or "").splitlines()
            if not any(k == RMEM_KEY for k, _ in parse_sysctl_conf(ln))]
    if not kept:
        kept = ["# CPSL TI Radar: UDP receive buffer cap for DCA1000 streaming "
                "(tools/setup/host_setup.py)"]
    return "\n".join(kept + [f"{RMEM_KEY}={target}"]) + "\n"


def check_sysctl(host: Host, target: int = RMEM_TARGET, require_persistent: bool = True) -> Check:
    runtime = _as_int(host.read("/proc/sys/net/core/rmem_max"))
    files = _sysctl_files(host)
    pval, psrc = _effective(host, files, RMEM_KEY)
    persistent = _as_int(pval)
    rt_ok = runtime is not None and runtime >= target
    p_ok = persistent is not None and persistent >= target
    pdesc = f"{persistent} (from {psrc})" if psrc else "not set in any sysctl.d file (kernel default after reboot)"
    detail = f"{RMEM_KEY}: runtime {runtime}, persistent {pdesc}; need >= {target}"
    if not require_persistent:
        if rt_ok:
            return Check("sysctl", OK, detail)
        return Check("sysctl", MISSING, detail,
                     fix_cmds=[Step(["sudo", "sysctl", "-w", f"{RMEM_KEY}={target}"])],
                     notes=["persist it with: uv run tools/setup/host_setup.py --apply"])
    if rt_ok and p_ok:
        return Check("sysctl", OK, detail)
    if p_ok:  # persistent but not loaded (e.g. file added since boot)
        return Check("sysctl", MISSING, detail,
                     fix_cmds=[Step(["sudo", "sysctl", "-w", f"{RMEM_KEY}={target}"])])
    existing = host.read(SYSCTL_DROPIN)
    if existing is None and host.exists(SYSCTL_DROPIN):
        return Check("sysctl", MISSING, detail + f"; {SYSCTL_DROPIN} exists but is unreadable",
                     manual=[f"sudo cat {SYSCTL_DROPIN}"],
                     notes=["refusing to rewrite a file whose contents cannot be read; "
                            f"add {RMEM_KEY}={target} to it by hand"])
    content = _dropin_content(existing, target)
    files_after = _sysctl_files(host, assume=SYSCTL_DROPIN)
    after, after_src = _effective(host, files_after, RMEM_KEY, {SYSCTL_DROPIN: content})
    notes = []
    if _as_int(after) is None or _as_int(after) < target:
        notes.append(f"{after_src} sets {RMEM_KEY}={after} after {SYSCTL_DROPIN} and would "
                     "override it at boot; fix that file by hand")
    return Check("sysctl", MISSING, detail,
                 fix_cmds=[Step(["sudo", "tee", SYSCTL_DROPIN], stdin=content),
                           Step(["sudo", "sysctl", "-p", SYSCTL_DROPIN])],
                 notes=notes)


def ethernet_candidates(host: Host) -> list:
    """Physical, wired ethernet interfaces (type 1, has a device, not wireless/bridge)."""
    out = []
    for name in host.listdir("/sys/class/net"):
        base = f"/sys/class/net/{name}"
        if ((host.read(f"{base}/type") or "").strip() == "1" and host.exists(f"{base}/device")
                and not host.exists(f"{base}/wireless") and not host.exists(f"{base}/bridge")):
            out.append(name)
    return out


def _nm_profile_for(host: Host, nic: str):
    """(profile dict | None, active: bool, problem str | None, same-name rows)."""
    rc, out = host.run(["nmcli", "-t", "-f", "NAME,UUID,TYPE,DEVICE", "connection", "show"])
    if rc != 0:
        return None, False, "could not list NetworkManager profiles", []
    rows = parse_nmcli_con_list(out)

    def found(prof, is_active):
        if prof is None:
            return None, is_active, "could not read the NetworkManager profile", []
        dups = [r for r in rows if r["name"] == prof.get("connection.id")
                and r["uuid"] != prof.get("connection.uuid")]
        return prof, is_active, None, dups

    def details(uuid):
        rc, o = host.run(["nmcli", "-t", "-f",
                          "connection.id,connection.uuid,connection.interface-name,ipv4.method,ipv4.addresses",
                          "connection", "show", "uuid", uuid])
        return parse_nmcli_kv(o) if rc == 0 else None

    active = [r for r in rows if r["device"] == nic]
    if active:
        return found(details(active[0]["uuid"]), True)
    bound = []
    for r in rows:
        if r["type"] == "802-3-ethernet":
            d = details(r["uuid"])
            if d and d.get("connection.interface-name") == nic:
                bound.append(d)
    if len(bound) == 1:
        return found(bound[0], False)
    if not bound:
        return None, False, f"no NetworkManager profile is bound to {nic}", []
    names = ", ".join(repr(b.get("connection.id")) for b in bound)
    return None, False, f"several NetworkManager profiles are bound to {nic} ({names}); not guessing", []


def check_dca_nic(host: Host, nic: str | None, confirm=None, ping: bool = False) -> Check:
    """confirm(candidate) -> bool is only offered by an interactive --apply."""
    rc, out = host.run(["ip", "-o", "-4", "addr", "show"])
    addrs = parse_ip_o_addr(out) if rc == 0 else {}
    confirmed = nic is not None
    if nic is None:
        cands = ethernet_candidates(host)
        tag = lambda n: n + (" (holds 192.168.33.x)" if any(
            a.startswith(DCA_SUBNET_PREFIX) for a in addrs.get(n, [])) else "")
        if not cands:
            return Check("dca-nic", NA, "no wired ethernet NIC found (only needed for DCA1000 streaming)")
        if len(cands) > 1:
            return Check("dca-nic", MISSING,
                         "several ethernet NICs, not guessing: " + ", ".join(tag(c) for c in cands),
                         manual=[f"re-run with --nic <one of: {', '.join(cands)}>"])
        nic = cands[0]
        if confirm is not None and confirm(nic):
            confirmed = True
    c = _check_nic(host, nic, addrs)
    if ping:
        prc, _ = host.run(["ping", "-c", "1", "-W", "1", DCA_FPGA_IP])
        c.notes.append(f"DCA1000 {DCA_FPGA_IP} {'answers ping' if prc == 0 else 'does not answer ping'} "
                       "(report only)")
    if not confirmed:
        c.detail = f"candidate {nic}, NOT confirmed: {c.detail}"
        if c.status == OK:
            c.status = WARN
        if c.fix_cmds:
            c.manual = [s.display() for s in c.fix_cmds] + c.manual
            c.fix_cmds = []
        q = shlex.quote(nic)
        c.notes.append(f"the DCA NIC is never picked automatically: re-run with --nic {q}")
        c.manual.append(f"uv run tools/setup/host_setup.py --nic {q}")
    return c


def _check_nic(host: Host, nic: str, addrs: dict) -> Check:
    base = f"/sys/class/net/{nic}"
    if not host.exists(base):
        return Check("dca-nic", MISSING, f"interface {nic} not found")
    have = addrs.get(nic, [])
    runtime = DCA_HOST_CIDR in have
    carrier = (host.read(f"{base}/carrier") or "").strip() == "1"
    notes = []
    dup = [i for i, a in addrs.items() if i != nic and DCA_HOST_CIDR.split("/")[0] in
           [x.split("/")[0] for x in a]]
    if dup:
        notes.append(f"192.168.33.30 is also on {', '.join(dup)}; DCA1000 traffic may be misrouted")
    rc, out = host.run(["nmcli", "-t", "-f", "GENERAL.STATE,GENERAL.CONNECTION", "device", "show", nic])
    state = parse_nmcli_kv(out).get("GENERAL.STATE", "") if rc == 0 else ""
    managed = rc == 0 and not state.startswith("10 ")
    link = "carrier up" if carrier else "no carrier (link down)"
    if not managed:
        why = "nmcli not installed" if rc == 127 else "not managed by NetworkManager"
        if runtime:
            return Check("dca-nic", WARN,
                         f"{nic}: {DCA_HOST_CIDR} present, {link}; {why}, so persistence is not "
                         "verified (make it persistent in netplan/ifupdown)", notes=notes)
        return Check("dca-nic", MISSING, f"{nic}: {DCA_HOST_CIDR} absent, {link}; {why}",
                     manual=[shlex.join(["sudo", "ip", "addr", "add", DCA_HOST_CIDR, "dev", nic])],
                     notes=notes + ["`ip addr add` is NOT persistent: it is lost on reboot or link "
                                    "reset; configure it in netplan/ifupdown to keep it"])
    prof, active, problem, dups = _nm_profile_for(host, nic)
    if prof is None:
        manual, fix = [], []
        if problem and problem.startswith("no NetworkManager profile"):
            # A new profile for the point-to-point DCA1000 link: static address, and never
            # the default route (the host's internet is on another interface).
            fix = [Step(["sudo", "nmcli", "connection", "add", "type", "ethernet", "ifname", nic,
                         "con-name", "radar-dca", "ipv4.method", "manual",
                         "ipv4.addresses", DCA_HOST_CIDR, "ipv4.never-default", "yes"]),
                   Step(["sudo", "nmcli", "connection", "up", "radar-dca", "ifname", nic])]
            if not carrier:
                fix = fix[:1]
                notes = notes + ["link is down: the profile is created now and the address "
                                 "appears when the link comes up"]
        return Check("dca-nic", MISSING, f"{nic}: {problem}", fix_cmds=fix, manual=manual, notes=notes)
    name, uuid = prof.get("connection.id", ""), prof.get("connection.uuid", "")
    if dups:
        notes.append(f"WARN: {len(dups) + 1} NetworkManager profiles are named {name!r} ("
                     + ", ".join(f"{r['uuid']} on {r['device'] or 'no device'}" for r in dups)
                     + f"); commands address only {uuid} ({nic}'s profile) by uuid")
    paddrs = [a.strip() for a in prof.get("ipv4.addresses", "").split(",") if a.strip()]
    persistent = DCA_HOST_CIDR in paddrs
    method = prof.get("ipv4.method", "")
    detail = (f"{nic}: profile {name!r} ({'active' if active else 'inactive'}, ipv4.method {method}, "
              f"addresses {', '.join(paddrs) or 'none'}); runtime {', '.join(have) or 'no IPv4'}; {link}")
    # On this one profile, addressed by uuid: NM allows duplicate names, so `id <name>`
    # could select another NIC's profile.  A static-addressed profile only gets the address
    # added; a DHCP (`auto`) profile is switched to manual, because on the DCA1000's
    # DHCP-less point-to-point link `auto` can stall activation.  nmcli needs root here
    # (polkit refuses an ordinary session), like the other checks.
    label = repr(name)
    if method == "auto":
        args = ["ipv4.method", "manual", "ipv4.addresses", DCA_HOST_CIDR, "ipv4.never-default", "yes"]
        if not prof.get("connection.interface-name"):
            args += ["connection.interface-name", nic]
        mod = Step(["sudo", "nmcli", "connection", "modify", "uuid", uuid] + args, comment=label)
    else:
        mod = Step(["sudo", "nmcli", "connection", "modify", "uuid", uuid, "+ipv4.addresses",
                    DCA_HOST_CIDR], comment=label)
    up = Step(["sudo", "nmcli", "connection", "up", "uuid", uuid], comment=label)
    if persistent and runtime:
        return Check("dca-nic", WARN if dups else OK, detail, notes=notes)
    if method in ("disabled", "ignore"):
        # Left manual: switching these changes how the profile gets its other addresses.
        return Check("dca-nic", MISSING, detail + f"; IPv4 is {method} on this profile",
                     manual=[shlex.join(["sudo", "nmcli", "connection", "modify", "uuid", uuid,
                                         "ipv4.method", "manual", "+ipv4.addresses", DCA_HOST_CIDR])],
                     notes=notes + ["changing ipv4.method is left to you (it changes how "
                                    "this profile gets its other addresses)"])
    if persistent:
        if not carrier:
            return Check("dca-nic", WARN, detail + "; the address is persistent and is applied "
                         "when the link comes up (cable / DCA1000 power)", notes=notes)
        return Check("dca-nic", MISSING, detail, fix_cmds=[up], notes=notes)
    if not carrier:
        return Check("dca-nic", MISSING, detail, fix_cmds=[mod],
                     notes=notes + ["link is down: the profile is updated now and the "
                                    "address appears when the link comes up"])
    return Check("dca-nic", MISSING, detail, fix_cmds=[mod, up], notes=notes)


def parse_ufw_tuples(text: str) -> list:
    """Rules from ufw's user.rules ``### tuple ###`` lines.

    Each is a dict: action, proto, dport, dst, sport, src and direction ('in'/'out')
    plus iface (None when the rule is not bound to one).  Format (ufw's own):
    ``### tuple ### allow any any 0.0.0.0/0 any 192.168.33.180 in_enp86s0 comment=...``
    """
    out = []
    for line in text.splitlines():
        if not line.startswith("### tuple ### "):
            continue
        f = line[len("### tuple ### "):].split()
        if len(f) < 6:
            continue
        direction, _, iface = (f[6] if len(f) > 6 else "in").partition("_")
        out.append({"action": f[0], "proto": f[1], "dport": f[2], "dst": f[3], "sport": f[4],
                    "src": f[5], "direction": direction, "iface": iface or None})
    return out


def _src_covers(src: str, ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip) in ipaddress.ip_network(src, strict=False)
    except ValueError:
        return False


def _ufw_allows_dca(rules: list, nic: str | None, ip: str) -> bool:
    for r in rules:
        if (r["action"] == "allow" and r["direction"] == "in"
                and r["proto"] in ("any", "udp") and r["dport"] in ("any", DCA_PORT)
                and _src_covers(r["src"], ip)
                and (r["iface"] is None or nic is None or r["iface"] == nic)):
            return True
    return False


def ufw_allow_step(nic: str, ip: str) -> Step:
    return Step(["sudo", "ufw", "allow", "in", "on", nic, "from", ip, "comment", "DCA1000"])


def check_firewall(host: Host, nic: str | None = None, fpga_ip: str = DCA_FPGA_IP) -> Check:
    """ufw must allow the DCA1000's replies in; the rules file is root-only (see module doc)."""
    conf = host.read(UFW_CONF)
    if conf is None:
        if host.exists("/etc/firewalld/firewalld.conf") or host.exists("/usr/sbin/firewalld"):
            return Check("firewall", NA, "firewalld host, not ufw; its rules are not checked "
                         "(allow UDP from the DCA1000 by hand if streaming stalls)")
        if host.exists(UFW_CONF) or host.exists("/usr/sbin/ufw"):
            return Check("firewall", WARN, "ufw is installed but " + UFW_CONF + " is unreadable; "
                         "cannot tell whether it is active")
        return Check("firewall", NA, "ufw not installed (nftables/iptables rules, if any, are not checked)")
    enabled = any(ln.strip().upper() == "ENABLED=YES" for ln in conf.splitlines())
    if not enabled:
        return Check("firewall", NA, f"ufw is inactive (ENABLED=no in {UFW_CONF}); nothing blocks the DCA1000")
    policy = next((ln.split("=", 1)[1].strip().strip('"').upper() for ln in
                   (host.read(UFW_DEFAULTS) or "").splitlines()
                   if ln.strip().startswith("DEFAULT_INPUT_POLICY=")), None)
    if policy == "ACCEPT":
        return Check("firewall", OK, f"ufw active but DEFAULT_INPUT_POLICY=ACCEPT in {UFW_DEFAULTS}; "
                     "the DCA1000 is not blocked")
    where = f"on {nic}" if nic else "on any interface"
    fix_nic = nic or "<dca-nic>"
    hand = shlex.join(["sudo", "ufw", "allow", "in", "on", fix_nic, "from", fpga_ip, "comment", "DCA1000"])
    text = host.read(UFW_USER_RULES)
    if text is None:
        return Check("firewall", WARN, f"ufw active, cannot verify DCA1000 rule without root "
                     f"({UFW_USER_RULES} is root-only); looking for an allow from {fpga_ip} {where}",
                     manual=[f"sudo ufw status | grep {fpga_ip}",
                             f"if absent: {hand}  (ufw skips a rule that already exists)"])
    if _ufw_allows_dca(parse_ufw_tuples(text), nic, fpga_ip):
        return Check("firewall", OK, f"ufw active; allow rule from {fpga_ip} {where} present in {UFW_USER_RULES}")
    detail = f"ufw active with input policy {policy or 'unknown'} and no allow rule from {fpga_ip} {where}: " \
             "the DCA1000's replies (UDP 1024 -> 4096) are dropped silently"
    if nic is None:
        return Check("firewall", MISSING, detail, manual=[hand],
                     notes=["re-run with --nic <dca-nic> and --apply to add it"])
    return Check("firewall", MISSING, detail, fix_cmds=[ufw_allow_step(nic, fpga_ip)])


def check_dialout(host: Host) -> Check:
    user = host.user()
    _, sess = host.run(["id", "-nG"])
    _, db = host.run(["id", "-nG", user])
    sess_g, db_g = sess.split(), db.split()
    notes = []
    for dev in host.listdir("/dev"):
        if dev.startswith(("ttyACM", "ttyUSB")):
            g = host.group_of(f"/dev/{dev}")
            if g and g not in sess_g:
                notes.append(f"/dev/{dev} belongs to group {g!r}, which this session lacks")
    if "dialout" in sess_g:
        return Check("dialout", OK, f"{user} is in dialout", notes=notes)
    if "dialout" in db_g:
        return Check("dialout", MISSING,
                     f"{user} is in dialout in /etc/group but not in this login session",
                     notes=notes + ["log out and back in (or reboot); nothing to run"])
    return Check("dialout", MISSING, f"{user} is not in dialout",
                 fix_cmds=[Step(["sudo", "usermod", "-aG", "dialout", user])],
                 notes=notes + ["takes effect after you log out and back in"])


def _rel(p: Path) -> str:
    try:
        return str(p.resolve().relative_to(REPO))
    except (ValueError, TypeError):   # outside the repo, or REPO unknown
        return str(p)


def check_build_type(host: Host, driver: Path | None) -> Check:
    if driver is None:
        return Check("build-type", NA, "no repo path (script run from stdin) and no --driver given")
    build = driver.parent
    text = host.read(str(build / "CMakeCache.txt"))
    if text is None:
        return Check("build-type", NA, f"no CMakeCache.txt in {build} (driver not built)")
    bt = parse_cmake_cache(text).get("CMAKE_BUILD_TYPE")
    if bt == "Release":
        return Check("build-type", OK, f"CMAKE_BUILD_TYPE=Release ({_rel(build)})")
    b = _rel(build)
    return Check("build-type", MISSING,
                 f"CMAKE_BUILD_TYPE is {bt!r} in {b}/CMakeCache.txt, not 'Release'",
                 manual=[f"cmake -S CPSL_TI_Radar_cpp -B {shlex.quote(b)} -DCMAKE_BUILD_TYPE=Release "
                         f"&& cmake --build {shlex.quote(b)} -j"])


def radar_boards(host: Host):
    """([board], [problems]) for every radar board on USB, one entry per physical board.

    A board is keyed by its USB port path (from the tty's DEVPATH), not by its
    serial: two boards can report the same serial.  Each board is a dict with
    ``model``, ``serial``, ``usb_path`` and ``ifs`` ({interface number: devnode}).
    """
    boards: dict = {}
    problems = []
    for dev in host.listdir("/dev"):
        if not re.fullmatch(r"tty(ACM|USB)\d+", dev):
            continue
        rc, out = host.run(["udevadm", "info", "--query=property", f"--name=/dev/{dev}"])
        if rc != 0:
            continue
        p = parse_udev_props(out)
        model = next((m for m, (v, i, _) in RADAR_MODELS.items()
                      if (p.get("ID_VENDOR_ID"), p.get("ID_MODEL_ID")) == (v, i)), None)
        if model is None:
            continue
        m = re.search(r"/([^/:]+):\d+\.(\d+)/", p.get("DEVPATH", ""))
        if not m:
            problems.append(f"/dev/{dev}: no USB port path in its DEVPATH; skipped")
            continue
        path, ifn = m.group(1), p.get("ID_USB_INTERFACE_NUM") or m.group(2).zfill(2)
        b = boards.setdefault(path, {"model": model, "serial": p.get("ID_SERIAL_SHORT", ""),
                                     "usb_path": path, "ifs": {}})
        b["ifs"][ifn] = f"/dev/{dev}"
    return [boards[k] for k in sorted(boards)], problems


def board_id(board: dict, serial_counts: dict) -> tuple:
    """(id, 'serial'|'path'): the serial when it is the only one of its kind and safe, else the path."""
    s = board["serial"]
    if s and serial_counts[s] == 1 and _SAFE_SERIAL.match(s):
        return s, "serial"
    return board["usb_path"], "path"


def render_udev_rule(serial: str, ifn: str, role: str, model: str = "xds110") -> str:
    vendor, product, _ = RADAR_MODELS[model]
    return (f'SUBSYSTEM=="tty", ENV{{ID_VENDOR_ID}}=="{vendor}", '
            f'ENV{{ID_MODEL_ID}}=="{product}", ENV{{ID_SERIAL_SHORT}}=="{serial}", '
            f'ENV{{ID_USB_INTERFACE_NUM}}=="{ifn}", SYMLINK+="radar/{serial}-{role}"')


def render_udev_path_rule(path: str, ifn: str, role: str, model: str = "xds110") -> str:
    vendor, product, _ = RADAR_MODELS[model]
    return (f'SUBSYSTEM=="tty", ENV{{ID_VENDOR_ID}}=="{vendor}", ENV{{ID_MODEL_ID}}=="{product}", '
            f'KERNELS=="{path}:1.{int(ifn)}", SYMLINK+="radar/{path}-{role}"')


def _board_rules(b: dict) -> list:
    render = render_udev_rule if b["id_kind"] == "serial" else render_udev_path_rule
    return [render(b["id"], ifn, role, b["model"]) for ifn, role in sorted(b["roles"].items())]


def check_udev(host: Host, enabled: bool) -> Check | None:
    scanned, problems = radar_boards(host)
    if not enabled:
        if len(scanned) > 1:
            return Check("udev", NA, f"skipped (opt-in): {len(scanned)} radar boards seen "
                         f"({', '.join(b['serial'] or b['usb_path'] for b in scanned)}); run with --udev "
                         "for stable /dev/radar/<id>-cli|-data names")
        return None
    counts: dict = {}
    for b in scanned:
        if b["serial"]:
            counts[b["serial"]] = counts.get(b["serial"], 0) + 1
    good, notes = [], list(problems)
    for b in scanned:
        b["id"], b["id_kind"] = board_id(b, counts)
        b["roles"] = RADAR_MODELS[b["model"]][2]
        label = f"{b['model']} board {b['id']}"
        if b["serial"] and counts[b["serial"]] > 1:
            notes.append(f"serial {b['serial']!r} is shared by {counts[b['serial']]} boards; "
                         f"naming {label} by USB port path")
        elif b["serial"] and b["id_kind"] == "path":
            notes.append(f"serial {b['serial']!r} has unexpected characters; naming {label} by USB port path")
        if b["id_kind"] == "path" and not _SAFE_SERIAL.match(b["usb_path"]):
            notes.append(f"{label}: unexpected characters in the USB path; no rule written")
        elif set(b["ifs"]) != set(b["roles"]):
            exp = ", ".join(f"{i}={'CLI' if r == 'cli' else r}" for i, r in sorted(b["roles"].items()))
            notes.append(f"{label}: interfaces {sorted(b['ifs'])} (expected {exp}); no rule written")
        else:
            good.append(b)
            if b["id_kind"] == "serial" and set(b["serial"]) == {"0"}:
                notes.append(f"serial {b['serial']} looks like an unprogrammed default; another board "
                             "with the same serial would collide")
    if not good:
        return Check("udev", NA, "no radar board with the expected interface layout found", notes=notes)
    want = [r for b in good for r in _board_rules(b)]
    for b in good:
        b["cli_dev"] = next(b["ifs"][i] for i, r in b["roles"].items() if r == "cli")
        b["data_dev"] = next(b["ifs"][i] for i, r in b["roles"].items() if r == "data")
        b["links"] = [f"/dev/radar/{b['id']}-cli", f"/dev/radar/{b['id']}-data"]
    boards_json = lambda have: [{
        "id": b["id"], "id_kind": b["id_kind"], "model": b["model"], "serial": b["serial"],
        "usb_path": b["usb_path"], "cli_dev": b["cli_dev"], "data_dev": b["data_dev"],
        "links": b["links"], "rule_present": all(r in have for r in _board_rules(b))} for b in good]
    existing = host.read(UDEV_RULES)
    if existing is None and host.exists(UDEV_RULES):
        return Check("udev", MISSING, f"{UDEV_RULES} exists but is unreadable",
                     manual=[f"sudo cat {UDEV_RULES}"], boards=boards_json([]),
                     notes=notes + ["refusing to rewrite a file whose contents cannot be read; "
                                    "add these rules by hand:"] + want)
    have = [ln.strip() for ln in (existing or "").splitlines()]
    mapping = "; ".join(f"{b['id']}: cli {b['cli_dev']}, data {b['data_dev']}" for b in good)

    def stale(ln: str) -> bool:
        """An old line for a serial or port path that a plugged board now claims."""
        return ln.strip() not in want and any(
            (b["serial"] and f'ENV{{ID_SERIAL_SHORT}}=="{b["serial"]}"' in ln)
            or f'KERNELS=="{b["usb_path"]}:1.' in ln for b in good)

    drops = [ln for ln in have if stale(ln)]
    if all(w in have for w in want) and not drops:
        return Check("udev", OK, f"{UDEV_RULES} has rules for {mapping}", notes=notes,
                     boards=boards_json(have))
    keep = [ln for ln in (existing or "").splitlines() if ln.strip() and not stale(ln) and ln.strip() not in want]
    if not keep or not keep[0].startswith("#"):
        keep.insert(0, "# CPSL TI Radar port names (tools/setup/host_setup.py --udev)")
    content = "\n".join(keep + want) + "\n"
    return Check("udev", MISSING, f"rules missing for {mapping}",
                 fix_cmds=[Step(["sudo", "tee", UDEV_RULES], stdin=content),
                           Step(["sudo", "udevadm", "control", "--reload"]),
                           Step(["sudo", "udevadm", "trigger", "--subsystem-match=tty"])],
                 notes=notes, boards=boards_json(have))


def run_checks(host: Host, args, confirm=None, only: str | None = None) -> list:
    table = [
        ("sysctl", lambda: check_sysctl(host, args.rmem_target)),
        ("dca-nic", lambda: check_dca_nic(host, args.nic, confirm=confirm, ping=args.ping)),
        ("firewall", lambda: check_firewall(host, args.nic, args.fpga_ip)),
        ("dialout", lambda: check_dialout(host)),
        ("build-type", lambda: check_build_type(host, args.driver)),
        ("udev", lambda: check_udev(host, args.udev)),
    ]
    out = []
    for name, fn in table:
        if only is None or name == only:
            c = fn()
            if c is not None:
                out.append(c)
    return out


def preflight(driver: Path, host: Host | None = None,
              rmem_target: int = RMEM_TARGET) -> list:
    """Checks tools/bench/bench_run.py runs before launching the driver.

    rmem_max is checked at runtime only (persistence does not affect a run).
    """
    host = host or Host()
    checks = [check_sysctl(host, rmem_target, require_persistent=False)]
    checks.append(check_build_type(host, driver))
    return checks


def exit_code(checks: list) -> int:
    return 1 if any(c.status == MISSING for c in checks) else 0


# ---------------------------------------------------------------------- CLI

def format_check(c: Check) -> str:
    lines = [f"[{c.status:^7}] {c.name:<10} {c.detail}"]
    for s in c.fix_cmds:
        lines += ["           fix: " + ln if i == 0 else "                " + ln
                  for i, ln in enumerate(s.display().splitlines())]
    for m in c.manual:
        lines.append("           run by hand: " + m)
    for n in c.notes:
        lines.append("           note: " + n)
    return "\n".join(lines)


def _ask_tty(prompt: str) -> bool:
    try:
        return input(prompt).strip().lower() in ("y", "yes")
    except EOFError:
        return False


def _ip(v: str) -> str:
    try:
        return str(ipaddress.IPv4Address(v))
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an IPv4 address: {v!r}")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--nic", help="DCA1000 host NIC (e.g. enp3s0); never auto-picked")
    ap.add_argument("--fpga-ip", default=DCA_FPGA_IP, type=_ip,
                    help="DCA1000 address for the firewall check/rule (default %(default)s)")
    ap.add_argument("--driver", type=Path, default=DEFAULT_DRIVER,
                    help="driver binary for the build-type check")
    ap.add_argument("--rmem-target", type=int, default=RMEM_TARGET)
    ap.add_argument("--udev", action="store_true",
                    help="also check/generate /etc/udev/rules.d/99-radar.rules: /dev/radar/<id>-cli|-data for "
                         "every XDS110 and CP2105 radar board (<id> = USB serial, or USB port path if shared)")
    ap.add_argument("--ping", action="store_true", help=f"ping the DCA1000 at {DCA_FPGA_IP} (report only)")
    ap.add_argument("--apply", action="store_true",
                    help="run the fixes (sudo per command, one confirmation per check)")
    ap.add_argument("--dry-run", action="store_true", help="print the commands, run nothing")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    return ap


def main(argv=None, host: Host | None = None, ask=_ask_tty, out=None) -> int:
    host = host or Host()
    out = out or sys.stdout
    ap = build_parser()
    args = ap.parse_args(argv)
    executing = args.apply and not args.dry_run
    if args.json and executing:
        ap.error("--json reports only; combine it with --apply only together with --dry-run")
    if host.euid() == 0:
        print("host_setup: do not run this tool as root or with sudo; it calls sudo itself "
              "for each command that needs it", file=sys.stderr)
        return 2
    chosen = {}

    def confirm(nic):
        if ask(f"Only ethernet NIC found: {nic}. Use it as the DCA1000 NIC? [y/N] "):
            chosen["nic"] = nic
            return True
        return False

    checks = run_checks(host, args, confirm=confirm if executing and not args.nic else None)
    pending = [c for c in checks if c.status == MISSING and c.fix_cmds] if args.apply else []

    if args.json:
        json.dump({"checks": [c.to_dict() for c in checks], "exit": exit_code(checks),
                   "would_run": [s.display() for c in pending for s in c.fix_cmds]}, out, indent=2)
        out.write("\n")
        return exit_code(checks)
    for c in checks:
        print(format_check(c), file=out)
    if not args.apply:
        return exit_code(checks)
    if args.dry_run:
        print("\n--apply --dry-run: " + ("nothing to run." if not pending else
                                         "would run (nothing executed):"), file=out)
        for c in pending:
            print(f"\n# {c.name}", file=out)
            for s in c.fix_cmds:
                print(s.display(), file=out)
        return exit_code(checks)

    final = {c.name: c for c in checks}
    re_args = argparse.Namespace(**{**vars(args), "nic": args.nic or chosen.get("nic")})
    for c in pending:
        print(f"\n# {c.name}: {c.detail}", file=out)
        for s in c.fix_cmds:
            print(s.display(), file=out)
        if not ask(f"Apply the {c.name} fix above? [y/N] "):
            print(f"skipped {c.name}", file=out)
            continue
        for s in c.fix_cmds:
            rc = host.execute(s)
            if rc != 0:
                print(f"command failed (exit {rc}): {shlex.join(s.argv)}; stopping {c.name}", file=out)
                break
        again = run_checks(host, re_args, only=c.name)
        if again:
            final[c.name] = again[0]
            print("re-check: " + format_check(again[0]), file=out)
    return exit_code(list(final.values()))


if __name__ == "__main__":
    sys.exit(main())
