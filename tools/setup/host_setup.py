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
``/dev/radar/<serial>-cli|data`` symlinks for XDS110 boards.

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
import json
import os
import re
import shlex
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools/bench"))
from bench_lib import parse_cmake_cache  # noqa: E402

DEFAULT_DRIVER = REPO / "CPSL_TI_Radar_cpp/build/CPSL_TI_Radar_CPP"
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
XDS110_VENDOR, XDS110_MODEL = "0451", "bef3"
XDS110_IFACES = {"00": "cli", "03": "data"}
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

    def to_dict(self) -> dict:
        d = asdict(self)
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
        manual = []
        if problem and problem.startswith("no NetworkManager profile"):
            manual = [shlex.join(["nmcli", "connection", "add", "type", "ethernet", "ifname", nic,
                                  "con-name", "radar-dca", "ipv4.method", "manual",
                                  "ipv4.addresses", DCA_HOST_CIDR])]
        return Check("dca-nic", MISSING, f"{nic}: {problem}", manual=manual, notes=notes)
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
    # Additive only (+ipv4.addresses), on this one profile, addressed by uuid: NM allows
    # duplicate names, so `id <name>` could select another NIC's profile.
    label = repr(name)
    mod = Step(["nmcli", "connection", "modify", "uuid", uuid, "+ipv4.addresses", DCA_HOST_CIDR],
               comment=label)
    up = Step(["nmcli", "connection", "up", "uuid", uuid], comment=label)
    polkit = ("nmcli runs without sudo; if NetworkManager's polkit policy refuses, "
              "run the same command with sudo")
    if persistent and runtime:
        return Check("dca-nic", WARN if dups else OK, detail, notes=notes)
    if method in ("disabled", "ignore"):
        return Check("dca-nic", MISSING, detail + f"; IPv4 is {method} on this profile",
                     manual=[shlex.join(["nmcli", "connection", "modify", "uuid", uuid,
                                         "ipv4.method", "manual", "+ipv4.addresses", DCA_HOST_CIDR])],
                     notes=notes + ["changing ipv4.method is left to you (it changes how "
                                    "this profile gets its other addresses)"])
    if persistent:
        if not carrier:
            return Check("dca-nic", WARN, detail + "; the address is persistent and is applied "
                         "when the link comes up (cable / DCA1000 power)", notes=notes)
        return Check("dca-nic", MISSING, detail, fix_cmds=[up], notes=notes + [polkit])
    if not carrier:
        return Check("dca-nic", MISSING, detail, fix_cmds=[mod],
                     notes=notes + [polkit, "link is down: the profile is updated now and the "
                                    "address appears when the link comes up"])
    return Check("dca-nic", MISSING, detail, fix_cmds=[mod, up], notes=notes + [polkit])


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
    except ValueError:
        return str(p)


def check_build_type(host: Host, driver: Path) -> Check:
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


def xds110_boards(host: Host):
    """({serial: {ifnum: devnode}}, [problems]) for XDS110 ttyACM ports."""
    boards: dict = {}
    problems = []
    for dev in host.listdir("/dev"):
        if not re.fullmatch(r"ttyACM\d+", dev):
            continue
        rc, out = host.run(["udevadm", "info", "--query=property", f"--name=/dev/{dev}"])
        if rc != 0:
            continue
        p = parse_udev_props(out)
        if (p.get("ID_VENDOR_ID"), p.get("ID_MODEL_ID")) != (XDS110_VENDOR, XDS110_MODEL):
            continue
        serial, ifn = p.get("ID_SERIAL_SHORT", ""), p.get("ID_USB_INTERFACE_NUM", "")
        b = boards.setdefault(serial, {})
        if ifn in b:
            problems.append(f"serial {serial!r}: interface {ifn} seen twice ({b[ifn]}, /dev/{dev}); "
                            "two boards share this serial")
            b["dup"] = True
        b[ifn] = f"/dev/{dev}"
    return boards, problems


def render_udev_rule(serial: str, ifn: str, role: str) -> str:
    return (f'SUBSYSTEM=="tty", ENV{{ID_VENDOR_ID}}=="{XDS110_VENDOR}", '
            f'ENV{{ID_MODEL_ID}}=="{XDS110_MODEL}", ENV{{ID_SERIAL_SHORT}}=="{serial}", '
            f'ENV{{ID_USB_INTERFACE_NUM}}=="{ifn}", SYMLINK+="radar/{serial}-{role}"')


def check_udev(host: Host, enabled: bool) -> Check | None:
    boards, problems = xds110_boards(host)
    if not enabled:
        if len(boards) > 1:
            return Check("udev", NA, f"skipped (opt-in): {len(boards)} XDS110 boards seen "
                         f"({', '.join(sorted(boards))}); run with --udev for stable "
                         "/dev/radar/<serial>-cli|-data names")
        return None
    good, notes = {}, list(problems)
    for serial, ifs in sorted(boards.items()):
        if ifs.get("dup"):
            continue
        if not _SAFE_SERIAL.match(serial):
            notes.append(f"serial {serial!r} has unexpected characters; no rule written")
        elif set(ifs) != set(XDS110_IFACES):
            notes.append(f"serial {serial}: interfaces {sorted(ifs)} (expected 00=CLI, 03=data); "
                         "no rule written")
        else:
            good[serial] = ifs
            if set(serial) == {"0"}:
                notes.append(f"serial {serial} looks like an unprogrammed default; another board "
                             "with the same serial would collide")
    if not good:
        return Check("udev", NA, "no XDS110 board with the 00/03 interface layout found", notes=notes)
    want = [render_udev_rule(s, ifn, role) for s in sorted(good)
            for ifn, role in sorted(XDS110_IFACES.items())]
    existing = host.read(UDEV_RULES)
    if existing is None and host.exists(UDEV_RULES):
        return Check("udev", MISSING, f"{UDEV_RULES} exists but is unreadable",
                     manual=[f"sudo cat {UDEV_RULES}"],
                     notes=notes + ["refusing to rewrite a file whose contents cannot be read; "
                                    "add these rules by hand:"] + [render_udev_rule(s, i, r)
                                    for s in sorted(good) for i, r in sorted(XDS110_IFACES.items())])
    have = [ln.strip() for ln in (existing or "").splitlines()]
    mapping = "; ".join(f"{s}: cli {good[s]['00']}, data {good[s]['03']}" for s in sorted(good))
    if all(w in have for w in want):
        return Check("udev", OK, f"{UDEV_RULES} has rules for {mapping}", notes=notes)
    keep = [ln for ln in (existing or "").splitlines()
            if ln.strip() and not any(f'=="{s}"' in ln for s in good)]
    if not keep or not keep[0].startswith("#"):
        keep.insert(0, "# CPSL TI Radar XDS110 port names (tools/setup/host_setup.py --udev)")
    content = "\n".join(keep + want) + "\n"
    return Check("udev", MISSING, f"rules missing for {mapping}",
                 fix_cmds=[Step(["sudo", "tee", UDEV_RULES], stdin=content),
                           Step(["sudo", "udevadm", "control", "--reload"]),
                           Step(["sudo", "udevadm", "trigger", "--subsystem-match=tty"])],
                 notes=notes)


def run_checks(host: Host, args, confirm=None, only: str | None = None) -> list:
    table = [
        ("sysctl", lambda: check_sysctl(host, args.rmem_target)),
        ("dca-nic", lambda: check_dca_nic(host, args.nic, confirm=confirm, ping=args.ping)),
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


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--nic", help="DCA1000 host NIC (e.g. enp3s0); never auto-picked")
    ap.add_argument("--driver", type=Path, default=DEFAULT_DRIVER,
                    help="driver binary for the build-type check")
    ap.add_argument("--rmem-target", type=int, default=RMEM_TARGET)
    ap.add_argument("--udev", action="store_true",
                    help="also check/generate /etc/udev/rules.d/99-radar.rules for XDS110 boards")
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
