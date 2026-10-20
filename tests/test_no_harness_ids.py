"""No tracked source/config file cites a harness task ID (a lab-area name plus a two-digit number).

Code comments give the technical reason, or a commit hash / doc section. Markdown,
the harness, firmware_dev and vendored code are out of scope. stdlib only.
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATTERN = re.compile(
    r"\b(radar|core|gui|sensors|release|firmware|docs|rover|nav|create3|ugv)-[0-9]{2}\b")
SKIP_PREFIXES = (".friday/", "firmware_dev/", "CPSL_TI_Radar_cpp/include/json")

# path -> reason it is allowed to match.
ALLOWLIST = {
    "radar_gui/tune_api.py": (
        'emitted API payload field "directive"; kept per user ruling 2026-10-20'),
}


def _tracked():
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True,
                         capture_output=True).stdout.decode()
    for rel in filter(None, out.split("\0")):
        if rel.endswith(".md") or rel.startswith(SKIP_PREFIXES):
            continue
        yield rel


def test_no_harness_task_ids():
    hits = []
    for rel in _tracked():
        if rel in ALLOWLIST:
            continue
        try:
            text = (ROOT / rel).read_bytes().decode("utf-8")
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue  # binary, deleted or a submodule path
        for n, line in enumerate(text.splitlines(), 1):
            if PATTERN.search(line):
                hits.append(f"{rel}:{n}: {line.strip()[:100]}")
    assert not hits, "harness task IDs in tracked source:\n" + "\n".join(hits)
