"""Tracked docs must not reference the dev harness, and relative links must resolve."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# harness setup files, out of scope for this check
EXEMPT_FILES = {"AGENTS.md", "CLAUDE.md"}
EXEMPT_DIRS = (".claude/", ".agents/")
# submodules that may be uninitialised in a plain checkout
SKIP_PREFIXES = ("firmware_dev/",)
LINK = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
FENCE = re.compile(r"^\s*(```|~~~)")


def tracked_md():
    out = subprocess.run(["git", "ls-files", "-z", "*.md"], cwd=ROOT, check=True,
                         capture_output=True, text=True).stdout
    for rel in filter(None, out.split("\0")):
        if rel in EXEMPT_FILES or rel.startswith(EXEMPT_DIRS) or (ROOT / rel).is_symlink():
            continue
        if (ROOT / rel).is_file():
            yield rel


def test_no_harness_references():
    bad = []
    for rel in tracked_md():
        for n, line in enumerate((ROOT / rel).read_text(errors="replace").splitlines(), 1):
            if ".friday" in line:
                bad.append(f"{rel}:{n}: {line.strip()[:100]}")
    assert not bad, "docs reference .friday/:\n" + "\n".join(bad)


def test_relative_links_resolve():
    bad = []
    for rel in tracked_md():
        base = (ROOT / rel).parent
        in_fence = False
        for n, line in enumerate((ROOT / rel).read_text(errors="replace").splitlines(), 1):
            if FENCE.match(line):
                in_fence = not in_fence
            if in_fence:
                continue
            for target in LINK.findall(line):
                if re.match(r"^([a-z][a-z0-9+.-]*:|#|/|<)", target):
                    continue
                path = target.split("#")[0].split("?")[0].replace("%20", " ")
                if not path:
                    continue
                dest = (base / path).resolve()
                try:
                    r = dest.relative_to(ROOT).as_posix()
                except ValueError:
                    continue
                if r.startswith(SKIP_PREFIXES) or dest.exists():
                    continue
                bad.append(f"{rel}:{n}: {target}")
    assert not bad, "broken relative links:\n" + "\n".join(bad)
