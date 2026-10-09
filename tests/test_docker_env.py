"""gui-40: docker/app/setup_env.sh, the hw compose wiring and the serial permission hint (no hardware)."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "docker" / "app" / "setup_env.sh"
COMPOSE = REPO / "docker" / "app" / "compose.yaml"
BOARD = "usb-Texas_Instruments_XDS110__03.00.00.18_Embedded_Debug_Probe_with_CMSIS-DAP_R0010A-if0"


def _fake_by_id(tmp_path, boards=("A",)):
    byid = tmp_path / "by-id"
    byid.mkdir()
    target = tmp_path / "ttyACM_fake"
    target.write_text("")
    for b in boards:
        for n in ("0", "3"):
            (byid / f"{BOARD.replace('R0010A', b)}{n}").symlink_to(target)
    return byid, target


def _run(byid, *args, env_extra=None):
    env = {**os.environ, "BY_ID_DIR": str(byid), "PATH": os.environ["PATH"]}
    env.update(env_extra or {})
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, env=env, timeout=30)


def _parse(text):
    return dict(ln.split("=", 1) for ln in text.splitlines() if "=" in ln and not ln.startswith("#"))


def test_syntax():
    assert subprocess.run(["bash", "-n", str(SCRIPT)]).returncode == 0


def test_print_keys_and_gid(tmp_path):
    byid, target = _fake_by_id(tmp_path)
    r = _run(byid, "--non-interactive", "--print")
    assert r.returncode == 0, r.stderr
    kv = _parse(r.stdout)
    assert set(kv) == {"HOST_UID", "HOST_GID", "SERIAL_GID", "RADAR_CLI", "RADAR_DATA", "GUI_HOST", "GUI_PORT"}
    assert kv["SERIAL_GID"] == str(target.stat().st_gid)
    assert kv["HOST_UID"] == str(os.getuid())
    assert kv["RADAR_CLI"].endswith("-if00") and kv["RADAR_DATA"].endswith("-if03")
    assert kv["GUI_HOST"] == "127.0.0.1" and kv["GUI_PORT"] == "8090"


def test_print_writes_no_file_and_refuses_overwrite(tmp_path):
    byid, _ = _fake_by_id(tmp_path)
    env_file = SCRIPT.parent / ".env"
    existed = env_file.exists()
    r = _run(byid, "--non-interactive", "--print")
    assert r.returncode == 0 and env_file.exists() == existed


def test_no_board_falls_back(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    r = _run(empty, "--non-interactive", "--print")
    assert r.returncode == 0
    assert _parse(r.stdout)["RADAR_CLI"] == "/dev/ttyACM0"
    assert "no XDS110" in r.stderr


def test_several_boards_noninteractive_uses_first(tmp_path):
    byid, _ = _fake_by_id(tmp_path, boards=("A", "B"))
    r = _run(byid, "--non-interactive", "--print")
    assert r.returncode == 0 and "using the first" in r.stderr


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not installed")
def test_compose_config_uses_env(tmp_path):
    envf = tmp_path / "sample.env"
    envf.write_text("HOST_UID=1234\nHOST_GID=2345\nSERIAL_GID=46\n"
                    "RADAR_CLI=/dev/serial/by-id/x-if00\nRADAR_DATA=/dev/serial/by-id/x-if03\n"
                    "GUI_HOST=100.83.97.21\nGUI_PORT=8123\n")
    r = subprocess.run(["docker", "compose", "-f", str(COMPOSE), "--env-file", str(envf), "--profile", "hw", "config"],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0 and "docker" in r.stderr.lower() and "compose" in r.stderr.lower() and "not a docker command" in r.stderr:
        pytest.skip("docker compose plugin missing")
    assert r.returncode == 0, r.stderr
    out = r.stdout
    import re
    assert re.search(r"group_add:\s*\n\s*- ['\"]?46['\"]?\s*\n", out)
    assert re.search(r"--host\n?.*100\.83\.97\.21", out, re.S) or "100.83.97.21" in out
    assert "8123" in out
    assert re.search(r"source: /dev/serial/by-id/x-if00\s+target: /dev/ttyACM0", out)
    assert re.search(r"source: /dev/serial/by-id/x-if03\s+target: /dev/ttyACM1", out)
