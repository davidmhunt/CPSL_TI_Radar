"""Hardware-free tests for tools/setup/host_setup.py.

Fixtures in tests/fixtures/host_setup/ are real output captured read-only on
the IWR1843 bench host (2026-10-05): `ip -o -4 addr show`, `nmcli -t ...`,
`id -nG`, PipeWire's limits.d file, and `udevadm info --query=property` for two
XDS110 boards (R2101050 on ttyACM0/1, 00000000 on ttyACM2/3).  No test runs a
real command that changes anything: the fake host records what --apply would
execute.  ROS's pytest plugins are disabled in pyproject.toml (see test_bench.py).
"""
import io
import json
import shlex
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools/setup"))
import host_setup as hs  # noqa: E402

FIX = REPO / "tests/fixtures/host_setup"
DRIVER = Path("/fake/build/CPSL_TI_Radar_CPP")
W1 = "8cca3611-6a6e-34cd-99f7-f55a946082b8"
W2 = "fd3566a5-8ff1-3bfc-835b-e8d1fd63e2d2"
CON_FIELDS = "connection.id,connection.uuid,connection.interface-name,ipv4.method,ipv4.addresses"


def fx(name):
    return (FIX / name).read_text()


class FakeHost(hs.Host):
    def __init__(self):
        self.files, self.dirs, self.cmds, self.links = {}, set(), {}, {}
        self.groups_of, self.executed, self.calls = {}, [], []
        self._user, self._euid, self.fail_on = "cpsl", 1000, None

    def read(self, path):
        return self.files.get(str(path))

    def listdir(self, path):
        pre = str(path).rstrip("/") + "/"
        return sorted({k[len(pre):].split("/")[0] for k in [*self.files, *self.dirs] if k.startswith(pre)})

    def exists(self, path):
        p = str(path)
        return p in self.files or p in self.dirs or bool(self.listdir(p))

    def realpath(self, path):
        return self.links.get(path, path)

    def run(self, argv):
        self.calls.append(tuple(argv))
        return self.cmds.get(tuple(argv), (127, ""))

    def user(self):
        return self._user

    def euid(self):
        return self._euid

    def group_of(self, path):
        return self.groups_of.get(path)

    def execute(self, step):
        self.executed.append(step)
        return 1 if self.fail_on and self.fail_on in step.argv else 0


def nmcli_con(uuid):
    return ("nmcli", "-t", "-f", CON_FIELDS, "connection", "show", "uuid", uuid)


def bench_host(boards=1):
    """The bench host as captured: NIC configured, rmem set at runtime only."""
    h = FakeHost()
    h.files.update({
        "/proc/sys/net/core/rmem_max": "134217728\n",
        "/etc/sysctl.conf": fx("etc_sysctl.conf"),
        "/etc/sysctl.d/99-sysctl.conf": fx("etc_sysctl.conf"),
        "/etc/sysctl.d/10-network-security.conf": "net.ipv4.conf.default.rp_filter=2\n",
        "/usr/lib/sysctl.d/50-pid-max.conf": "kernel.pid_max = 4194304\n",
        "/etc/security/limits.conf": "#<domain> <type> <item> <value>\n#        - rtprio - max realtime priority\n",
        "/etc/security/limits.d/25-pw-rlimits.conf": fx("limits_25-pw-rlimits.conf"),
        "/etc/security/limits.d/10-gamemode.conf": "@gamemode - nice -10\n",
        str(DRIVER): "", str(DRIVER.parent / "CMakeCache.txt"): "//x\nCMAKE_BUILD_TYPE:STRING=Release\n",
    })
    h.links["/etc/sysctl.d/99-sysctl.conf"] = "/etc/sysctl.conf"
    for nic, typ, extra in [("enp3s0", "1", ["device"]), ("wlp1s0", "1", ["device", "wireless"]),
                            ("docker0", "1", ["bridge"]), ("lo", "772", []), ("tailscale0", "65534", [])]:
        h.files[f"/sys/class/net/{nic}/type"] = typ + "\n"
        h.dirs.update(f"/sys/class/net/{nic}/{e}" for e in extra)
    h.files["/sys/class/net/enp3s0/carrier"] = "1\n"
    h.cmds.update({
        ("ip", "-o", "-4", "addr", "show"): (0, fx("ip_o4_addr.txt")),
        ("nmcli", "-t", "-f", "GENERAL.STATE,GENERAL.CONNECTION", "device", "show", "enp3s0"):
            (0, fx("nmcli_device_enp3s0.txt")),
        ("nmcli", "-t", "-f", "NAME,UUID,TYPE,DEVICE", "connection", "show"): (0, fx("nmcli_con_list.txt")),
        nmcli_con(W1): (0, fx(f"nmcli_con_{W1}.txt")),
        nmcli_con(W2): (0, fx(f"nmcli_con_{W2}.txt")),
        ("id", "-nG"): (0, fx("id_nG_session.txt")),
        ("id", "-nG", "cpsl"): (0, fx("id_nG_user.txt")),
        ("ping", "-c", "1", "-W", "1", "192.168.33.180"): (1, ""),
    })
    for n in range(2 * boards):
        h.dirs.add(f"/dev/ttyACM{n}")
        h.groups_of[f"/dev/ttyACM{n}"] = "plugdev"
        h.cmds[("udevadm", "info", "--query=property", f"--name=/dev/ttyACM{n}")] = (0, fx(f"udevadm_ttyACM{n}.txt"))
    return h


def make_all_ok(h):
    h.files["/etc/sysctl.d/99-radar.conf"] = "net.core.rmem_max=134217728\n"
    return h


def args(*a):
    return hs.build_parser().parse_args(["--driver", str(DRIVER), *a])


def by_name(checks):
    return {c.name: c for c in checks}


def run_main(h, *argv, ask=lambda p: False):
    out = io.StringIO()
    rc = hs.main(["--driver", str(DRIVER), *argv], host=h, ask=ask, out=out)
    return rc, out.getvalue()


def all_steps(checks):
    return [s for c in checks for s in c.fix_cmds]


# ---------------------------------------------------------------- parsers

def test_parsers_on_captured_output():
    addrs = hs.parse_ip_o_addr(fx("ip_o4_addr.txt"))
    assert addrs["enp3s0"] == ["192.168.1.57/24", "192.168.33.30/24"]
    rows = hs.parse_nmcli_con_list(fx("nmcli_con_list.txt"))
    assert {"name": "Wired connection 1", "uuid": W1, "type": "802-3-ethernet", "device": "enp3s0"} in rows
    assert hs.split_terse(r"Lab\:DCA:uuid-1:802-3-ethernet:") == ["Lab:DCA", "uuid-1", "802-3-ethernet", ""]
    prof = hs.parse_nmcli_kv(fx(f"nmcli_con_{W1}.txt"))
    assert prof["ipv4.addresses"] == "192.168.1.57/24, 192.168.33.30/24"
    p = hs.parse_udev_props(fx("udevadm_ttyACM3.txt"))
    assert (p["ID_SERIAL_SHORT"], p["ID_USB_INTERFACE_NUM"]) == ("00000000", "03")
    assert hs.parse_sysctl_conf("# c\n; c\n-net/core/rmem_max = 5\n") == [("net.core.rmem_max", "5")]


# ------------------------------------------------------- captured bench host

def test_doctor_on_captured_bench_host():
    """The real host: rmem set at runtime only; no realtime check (core-20)."""
    h = bench_host()
    rc, out = run_main(h, "--nic", "enp3s0")
    c = by_name(hs.run_checks(h, args("--nic", "enp3s0")))
    assert rc == 1
    assert {n: x.status for n, x in c.items()} == {
        "sysctl": "MISSING", "dca-nic": "OK", "dialout": "OK", "build-type": "OK"}
    assert "persistent not set" in c["sysctl"].detail and "runtime 134217728" in c["sysctl"].detail
    assert "realtime" not in out and "setcap" not in out
    assert not h.executed


def test_sysctl_paths():
    h = make_all_ok(bench_host())
    assert hs.check_sysctl(h).status == "OK"
    # persistent but not loaded -> runtime-only fix
    h.files["/proc/sys/net/core/rmem_max"] = "212992\n"
    c = hs.check_sysctl(h)
    assert c.status == "MISSING" and [s.argv for s in c.fix_cmds] == [
        ["sudo", "sysctl", "-w", "net.core.rmem_max=134217728"]]
    # nothing persistent, low runtime -> drop-in written + only that file loaded
    del h.files["/etc/sysctl.d/99-radar.conf"]
    c = hs.check_sysctl(h)
    assert [s.argv for s in c.fix_cmds] == [["sudo", "tee", "/etc/sysctl.d/99-radar.conf"],
                                            ["sudo", "sysctl", "-p", "/etc/sysctl.d/99-radar.conf"]]
    assert c.fix_cmds[0].stdin.endswith("net.core.rmem_max=134217728\n")
    assert not c.notes
    # a later file with a lower value would win at boot: say so
    h.files["/etc/sysctl.d/99-zz-local.conf"] = "net/core/rmem_max = 4096\n"
    c = hs.check_sysctl(h)
    assert "99-zz-local.conf" in c.detail and any("override" in n for n in c.notes)
    # an existing drop-in keeps its other lines
    del h.files["/etc/sysctl.d/99-zz-local.conf"]
    h.files["/etc/sysctl.d/99-radar.conf"] = "# mine\nnet.core.wmem_max=1\nnet.core.rmem_max=1000\n"
    assert hs.check_sysctl(h).fix_cmds[0].stdin == "# mine\nnet.core.wmem_max=1\nnet.core.rmem_max=134217728\n"
    # --rmem-target raises the bar
    h.files["/etc/sysctl.d/99-radar.conf"] = "net.core.rmem_max=134217728\n"
    h.files["/proc/sys/net/core/rmem_max"] = "134217728\n"
    assert hs.check_sysctl(h, 268435456).status == "MISSING"


# ------------------------------------------------------------------- NIC

def nic(h, *a, confirm=None):
    ns = args(*a)
    return hs.check_dca_nic(h, ns.nic, confirm=confirm, ping=ns.ping)


def strip_dca_addr(h, profile_too=True, runtime_too=True):
    ipk = ("ip", "-o", "-4", "addr", "show")
    if runtime_too:
        h.cmds[ipk] = (0, "".join(l for l in fx("ip_o4_addr.txt").splitlines(True) if "192.168.33.30" not in l))
    if profile_too:
        h.cmds[nmcli_con(W1)] = (0, fx(f"nmcli_con_{W1}.txt").replace(", 192.168.33.30/24", ""))


def test_nic_link_down_with_persistent_profile_is_warn():
    """The cable was pulled: NM reports 'unavailable', no runtime address, profile intact."""
    h = bench_host()
    strip_dca_addr(h, profile_too=False)
    h.files["/sys/class/net/enp3s0/carrier"] = "0\n"
    h.cmds[("nmcli", "-t", "-f", "GENERAL.STATE,GENERAL.CONNECTION", "device", "show", "enp3s0")] = (
        0, "GENERAL.STATE:20 (unavailable)\nGENERAL.CONNECTION:\n")
    h.cmds[("nmcli", "-t", "-f", "NAME,UUID,TYPE,DEVICE", "connection", "show")] = (
        0, fx("nmcli_con_list.txt").replace(f"{W1}:802-3-ethernet:enp3s0", f"{W1}:802-3-ethernet:"))
    c = nic(h, "--nic", "enp3s0")
    assert c.status == "WARN" and not c.fix_cmds
    assert "'Wired connection 1' (inactive" in c.detail and "no carrier" in c.detail


def test_nic_fix_is_additive_on_named_profile_only():
    h = bench_host()
    strip_dca_addr(h)
    c = nic(h, "--nic", "enp3s0")
    assert c.status == "MISSING"
    assert [s.display() for s in c.fix_cmds] == [
        f"nmcli connection modify uuid {W1} +ipv4.addresses 192.168.33.30/24  # 'Wired connection 1'",
        f"nmcli connection up uuid {W1}  # 'Wired connection 1'"]
    for s in c.fix_cmds:
        assert "sudo" not in s.argv and "ipv4.addresses" not in s.argv and "-ipv4.addresses" not in s.argv
        assert s.argv[s.argv.index("uuid") + 1] == W1 and "id" not in s.argv
        assert W2 not in s.display() and "Wired connection 1" not in s.argv  # name is display-only


def test_nic_duplicate_profile_name_targets_only_enp3s0_uuid():
    """A second 'Wired connection 1' bound to another NIC: commands use enp3s0's uuid only."""
    h = bench_host()
    strip_dca_addr(h)
    lst = ("nmcli", "-t", "-f", "NAME,UUID,TYPE,DEVICE", "connection", "show")
    h.cmds[lst] = (0, h.cmds[lst][1].replace("Wired connection 2:", "Wired connection 1:"))
    h.cmds[nmcli_con(W2)] = (0, fx(f"nmcli_con_{W2}.txt").replace("connection.id:Wired connection 2",
                                                                   "connection.id:Wired connection 1"))
    c = nic(h, "--nic", "enp3s0")
    assert c.status == "MISSING" and len(c.fix_cmds) == 2
    for s in c.fix_cmds:
        assert s.argv[3:5] == ["uuid", W1] and W2 not in s.argv
    assert any(n.startswith("WARN: 2 NetworkManager profiles are named 'Wired connection 1'") and W2 in n
               for n in c.notes)
    # configured host with the duplicate: still flagged (WARN), nothing to run
    h = bench_host()
    h.cmds[lst] = (0, h.cmds[lst][1].replace("Wired connection 2:", "Wired connection 1:"))
    c = nic(h, "--nic", "enp3s0")
    assert c.status == "WARN" and not c.fix_cmds and any(W2 in n for n in c.notes)


def test_nic_profile_with_awkward_name_is_quoted():
    h = bench_host()
    strip_dca_addr(h)
    h.cmds[("nmcli", "-t", "-f", "NAME,UUID,TYPE,DEVICE", "connection", "show")] = (
        0, fx("nmcli_con_list.txt").replace("Wired connection 1:", r"Lab\:DCA it's:"))
    h.cmds[nmcli_con(W1)] = (0, h.cmds[nmcli_con(W1)][1].replace("connection.id:Wired connection 1",
                                                                  r"connection.id:Lab\:DCA it's"))
    c = nic(h, "--nic", "enp3s0")
    assert c.fix_cmds[0].argv[4] == W1
    assert c.fix_cmds[0].display().endswith('  # "Lab:DCA it\'s"')
    assert shlex.split(c.fix_cmds[0].display(), comments=True) == c.fix_cmds[0].argv


def test_nic_link_down_profile_missing_address_only_modifies():
    h = bench_host()
    strip_dca_addr(h)
    h.files["/sys/class/net/enp3s0/carrier"] = "0\n"
    c = nic(h, "--nic", "enp3s0")
    assert [s.argv[2] for s in c.fix_cmds] == ["modify"]


def test_nic_inactive_profile_found_by_interface_name_and_ambiguity():
    h = bench_host()
    strip_dca_addr(h, profile_too=False)
    lst = ("nmcli", "-t", "-f", "NAME,UUID,TYPE,DEVICE", "connection", "show")
    h.cmds[lst] = (0, fx("nmcli_con_list.txt").replace(f"{W1}:802-3-ethernet:enp3s0", f"{W1}:802-3-ethernet:"))
    c = nic(h, "--nic", "enp3s0")  # Wired connection 2 is bound to enx306893aba600, not picked
    assert [s.display() for s in c.fix_cmds] == [f"nmcli connection up uuid {W1}  # 'Wired connection 1'"]
    h.cmds[nmcli_con(W2)] = (0, fx(f"nmcli_con_{W2}.txt").replace("enx306893aba600", "enp3s0"))
    c = nic(h, "--nic", "enp3s0")
    assert c.status == "MISSING" and not c.fix_cmds and "several NetworkManager profiles" in c.detail


def test_nic_unmanaged_prints_ip_addr_add_only():
    h = bench_host()
    for k in [k for k in h.cmds if k[0] == "nmcli"]:
        del h.cmds[k]
    assert nic(h, "--nic", "enp3s0").status == "WARN"  # address present, persistence unknown
    strip_dca_addr(h, profile_too=False)
    c = nic(h, "--nic", "enp3s0")
    assert c.status == "MISSING" and not c.fix_cmds
    assert c.manual == ["sudo ip addr add 192.168.33.30/24 dev enp3s0"]
    assert any("NOT persistent" in n for n in c.notes)


def test_nic_autodetect_never_picks():
    h = bench_host()
    strip_dca_addr(h)
    c = nic(h)  # one candidate, unconfirmed: report it, but no runnable fix
    assert c.status == "MISSING" and not c.fix_cmds and "NOT confirmed" in c.detail
    assert any("+ipv4.addresses" in m for m in c.manual)
    assert nic(h, confirm=lambda n: False).fix_cmds == []
    assert len(nic(h, confirm=lambda n: n == "enp3s0").fix_cmds) == 2
    # the configured host without --nic: WARN, not OK
    assert nic(bench_host()).status == "WARN"
    # second wired NIC (the USB adapter of 'Wired connection 2') -> stop, list both
    h = bench_host()
    h.files["/sys/class/net/enx306893aba600/type"] = "1\n"
    h.dirs.add("/sys/class/net/enx306893aba600/device")
    asked = []
    c = nic(h, confirm=lambda n: asked.append(n) or True)
    assert c.status == "MISSING" and not c.fix_cmds and not asked
    assert "enp3s0 (holds 192.168.33.x)" in c.detail and "enx306893aba600" in c.detail
    assert not any(k[0] == "nmcli" for k in h.calls)


def test_nic_ping_is_report_only_and_missing_iface():
    h = bench_host()
    c = nic(h, "--nic", "enp3s0", "--ping")
    assert c.status == "OK" and any("does not answer ping" in n for n in c.notes)
    assert nic(h, "--nic", "eth9").detail == "interface eth9 not found"


# --------------------------------------------------- dialout / build

def test_dialout_paths():
    h = bench_host()
    assert hs.check_dialout(h).status == "OK"
    h.cmds[("id", "-nG")] = (0, "cpsl adm sudo plugdev\n")
    c = hs.check_dialout(h)
    assert c.status == "MISSING" and not c.fix_cmds and "not in this login session" in c.detail
    h.cmds[("id", "-nG", "cpsl")] = (0, "cpsl adm sudo plugdev\n")
    c = hs.check_dialout(h)
    assert [s.argv for s in c.fix_cmds] == [["sudo", "usermod", "-aG", "dialout", "cpsl"]]
    h.groups_of["/dev/ttyACM0"] = "uucp"
    assert any("'uucp'" in n for n in hs.check_dialout(h).notes)


def test_build_type_is_printed_never_run():
    h = bench_host()
    h.files[str(DRIVER.parent / "CMakeCache.txt")] = "CMAKE_BUILD_TYPE:STRING=Debug\n"
    c = hs.check_build_type(h, DRIVER)
    assert c.status == "MISSING" and not c.fix_cmds
    assert "-DCMAKE_BUILD_TYPE=Release" in c.manual[0]
    del h.files[str(DRIVER.parent / "CMakeCache.txt")]
    assert hs.check_build_type(h, DRIVER).status == "N-A"


# ------------------------------------------------------------------- udev

def test_udev_two_xds110_boards():
    h = bench_host(boards=2)
    assert hs.check_udev(h, enabled=False).status == "N-A"  # suggestion only
    assert "--udev" in hs.check_udev(h, enabled=False).detail
    assert hs.check_udev(bench_host(boards=1), enabled=False) is None
    c = hs.check_udev(h, enabled=True)
    assert c.status == "MISSING"
    rules = c.fix_cmds[0].stdin
    assert c.fix_cmds[0].argv == ["sudo", "tee", "/etc/udev/rules.d/99-radar.rules"]
    for serial in ("R2101050", "00000000"):
        assert (f'ENV{{ID_SERIAL_SHORT}}=="{serial}", ENV{{ID_USB_INTERFACE_NUM}}=="00", '
                f'SYMLINK+="radar/{serial}-cli"') in rules
        assert f'ENV{{ID_USB_INTERFACE_NUM}}=="03", SYMLINK+="radar/{serial}-data"' in rules
    assert "MODE=" not in rules and "GROUP=" not in rules and "chmod" not in rules and "0666" not in rules
    assert [s.argv for s in c.fix_cmds[1:]] == [["sudo", "udevadm", "control", "--reload"],
                                                ["sudo", "udevadm", "trigger", "--subsystem-match=tty"]]
    assert any("00000000" in n and "default" in n for n in c.notes)
    # rules already installed -> OK; a rule for an unplugged board is kept on rewrite
    h.files["/etc/udev/rules.d/99-radar.rules"] = rules
    assert hs.check_udev(h, enabled=True).status == "OK"
    old = hs.render_udev_rule("OLD123", "00", "cli")
    h.files["/etc/udev/rules.d/99-radar.rules"] = f"{old}\n"
    assert old in hs.check_udev(h, enabled=True).fix_cmds[0].stdin


def test_udev_unexpected_layout_and_shared_serial():
    h = bench_host(boards=2)
    del h.cmds[("udevadm", "info", "--query=property", "--name=/dev/ttyACM3")]
    c = hs.check_udev(h, enabled=True)
    assert "00000000" not in c.fix_cmds[0].stdin.replace("# ", "")
    assert any("00000000" in n and "expected 00=CLI" in n for n in c.notes)
    h = bench_host(boards=2)  # second board reporting the first board's serial
    for n in (2, 3):
        k = ("udevadm", "info", "--query=property", f"--name=/dev/ttyACM{n}")
        h.cmds[k] = (0, h.cmds[k][1].replace("00000000", "R2101050"))
    c = hs.check_udev(h, enabled=True)
    assert c.status == "N-A" and any("two boards share" in n for n in c.notes)


# ----------------------------------------------------- modes and exit codes

FORCED_MISSING_DRY_RUN = """\
# sysctl
sudo tee /etc/sysctl.d/99-radar.conf > /dev/null <<'EOF'
# CPSL TI Radar: UDP receive buffer cap for DCA1000 streaming (tools/setup/host_setup.py)
net.core.rmem_max=134217728
EOF
sudo sysctl -p /etc/sysctl.d/99-radar.conf

# dca-nic
nmcli connection modify uuid 8cca3611-6a6e-34cd-99f7-f55a946082b8 +ipv4.addresses 192.168.33.30/24  # 'Wired connection 1'
nmcli connection up uuid 8cca3611-6a6e-34cd-99f7-f55a946082b8  # 'Wired connection 1'

# dialout
sudo usermod -aG dialout cpsl

# udev
sudo tee /etc/udev/rules.d/99-radar.rules > /dev/null <<'EOF'
# CPSL TI Radar XDS110 port names (tools/setup/host_setup.py --udev)
SUBSYSTEM=="tty", ENV{ID_VENDOR_ID}=="0451", ENV{ID_MODEL_ID}=="bef3", ENV{ID_SERIAL_SHORT}=="00000000", ENV{ID_USB_INTERFACE_NUM}=="00", SYMLINK+="radar/00000000-cli"
SUBSYSTEM=="tty", ENV{ID_VENDOR_ID}=="0451", ENV{ID_MODEL_ID}=="bef3", ENV{ID_SERIAL_SHORT}=="00000000", ENV{ID_USB_INTERFACE_NUM}=="03", SYMLINK+="radar/00000000-data"
SUBSYSTEM=="tty", ENV{ID_VENDOR_ID}=="0451", ENV{ID_MODEL_ID}=="bef3", ENV{ID_SERIAL_SHORT}=="R2101050", ENV{ID_USB_INTERFACE_NUM}=="00", SYMLINK+="radar/R2101050-cli"
SUBSYSTEM=="tty", ENV{ID_VENDOR_ID}=="0451", ENV{ID_MODEL_ID}=="bef3", ENV{ID_SERIAL_SHORT}=="R2101050", ENV{ID_USB_INTERFACE_NUM}=="03", SYMLINK+="radar/R2101050-data"
EOF
sudo udevadm control --reload
sudo udevadm trigger --subsystem-match=tty
"""


def forced_missing_host():
    """Every check MISSING: fresh-machine state on top of the captured bench fixtures."""
    h = bench_host(boards=2)
    h.files["/proc/sys/net/core/rmem_max"] = "212992\n"
    strip_dca_addr(h)
    h.cmds[("id", "-nG")] = h.cmds[("id", "-nG", "cpsl")] = (0, "cpsl adm sudo plugdev\n")
    h.files[str(DRIVER.parent / "CMakeCache.txt")] = "CMAKE_BUILD_TYPE:STRING=\n"
    return h


def test_apply_dry_run_forced_missing_prints_exact_commands():
    h = forced_missing_host()
    rc, out = run_main(h, "--nic", "enp3s0", "--udev", "--apply", "--dry-run",
                       ask=lambda p: pytest.fail("dry-run must not prompt"))
    assert rc == 1 and not h.executed
    assert out.split("would run (nothing executed):\n\n", 1)[1] == FORCED_MISSING_DRY_RUN
    assert "run by hand: cmake -S CPSL_TI_Radar_cpp -B /fake/build -DCMAKE_BUILD_TYPE=Release" in out
    for s in all_steps(hs.run_checks(h, args("--nic", "enp3s0", "--udev"))):
        assert s.argv[0] in ("sudo", "nmcli") and "sudo" not in s.argv[1:]
        assert not (s.argv[0] == "nmcli" and "ipv4.addresses" in s.argv)


def test_idempotent_second_dry_run_prints_nothing():
    h = make_all_ok(bench_host())
    rc, out = run_main(h, "--nic", "enp3s0", "--apply", "--dry-run")
    assert rc == 0 and out.rstrip().endswith("--apply --dry-run: nothing to run.")
    rc, out = run_main(h, "--nic", "enp3s0")
    assert rc == 0 and "fix:" not in out


def test_apply_confirms_per_check_and_rechecks():
    h = bench_host()
    prompts = []

    def ask(p):
        prompts.append(p)
        return "sysctl" in p  # yes to sysctl

    rc, out = run_main(h, "--nic", "enp3s0", "--apply", ask=ask)
    assert [p.split()[2] for p in prompts] == ["sysctl"]
    assert [s.argv[:2] for s in h.executed] == [["sudo", "tee"], ["sudo", "sysctl"]]
    assert "re-check: [MISSING] sysctl" in out  # fake host unchanged
    assert rc == 1
    # failure stops the group
    h = bench_host()
    h.fail_on = "tee"
    run_main(h, "--nic", "enp3s0", "--apply", ask=lambda p: True)
    assert [s.argv[1] for s in h.executed] == ["tee"]


def test_apply_confirm_single_candidate_nic():
    h = bench_host()
    strip_dca_addr(h)
    make_all_ok(h)
    asked = []
    run_main(h, "--apply", ask=lambda p: asked.append(p) or True)
    assert "enp3s0" in asked[0]
    assert [s.argv[2] for s in h.executed] == ["modify", "up"]
    assert sum(1 for k in h.calls if k[:2] == ("nmcli", "-t") and k[-1] == "enp3s0") == 2  # re-checked


def test_exit_codes_json_and_root():
    assert run_main(make_all_ok(bench_host()), "--nic", "enp3s0")[0] == 0
    assert run_main(bench_host(), "--nic", "enp3s0")[0] == 1
    rc, out = run_main(bench_host(), "--nic", "enp3s0", "--json", "--apply", "--dry-run")
    data = json.loads(out)
    assert rc == data["exit"] == 1
    assert "setcap" not in data["would_run"]
    h = bench_host()
    h._euid = 0
    assert run_main(h, "--nic", "enp3s0")[0] == 2
    with pytest.raises(SystemExit):
        run_main(bench_host(), "--json", "--apply")


def test_preflight_runtime_only():
    h = bench_host()
    checks = hs.preflight(DRIVER, host=h)
    assert [(c.name, c.status) for c in checks] == [("sysctl", "OK"), ("build-type", "OK")]


def test_unreadable_owned_files_are_never_rewritten():
    h = bench_host(boards=2)
    h.files["/proc/sys/net/core/rmem_max"] = "212992\n"
    h.dirs.update({"/etc/sysctl.d/99-radar.conf", "/etc/udev/rules.d/99-radar.rules"})  # exist, read -> None
    c = hs.check_sysctl(h)
    assert c.status == "MISSING" and not c.fix_cmds and "unreadable" in c.detail
    u = hs.check_udev(h, enabled=True)
    assert u.status == "MISSING" and not u.fix_cmds and "unreadable" in u.detail
    assert any('SYMLINK+="radar/R2101050-cli"' in n for n in u.notes)


def test_rerun_line_quotes_nic_and_user_comes_from_passwd():
    h = bench_host()
    h.dirs.discard("/sys/class/net/enp3s0/device")
    h.files["/sys/class/net/en$(x)/type"] = "1\n"
    h.dirs.add("/sys/class/net/en$(x)/device")
    c = nic(h)
    assert "uv run tools/setup/host_setup.py --nic 'en$(x)'" in c.manual
    import os
    import pwd
    assert hs.Host().user() == pwd.getpwuid(os.getuid()).pw_name
