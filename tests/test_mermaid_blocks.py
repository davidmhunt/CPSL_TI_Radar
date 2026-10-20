"""Lint Mermaid fences in tracked Markdown, and keep ASCII diagrams out.

Stdlib only; standalone (no dependency on any other repo). If `npx` is on PATH the blocks are also rendered with
@mermaid-js/mermaid-cli from a scratch directory outside the repo.
"""
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEYWORDS = ("flowchart", "graph", "sequenceDiagram", "classDiagram",
            "stateDiagram", "gantt", "erDiagram", "timeline", "pie")
BOX = re.compile("[─-╿]")
SKIP_PREFIXES = (".friday/",)
FENCE = re.compile(r"^```([^\n]*)\n(.*?)^```[ \t]*$", re.S | re.M)


def tracked_md():
    out = subprocess.run(["git", "ls-files", "*.md"], cwd=ROOT, check=True,
                         capture_output=True, text=True).stdout.split("\n")
    for p in out:
        if not p or p.startswith(SKIP_PREFIXES) or "archive" in p.lower().split("/"):
            continue
        if (ROOT / p).is_file():
            yield p


def fences():
    for p in tracked_md():
        text = (ROOT / p).read_text(encoding="utf-8")
        for m in FENCE.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            yield p, line, m.group(1).strip().lower(), m.group(2)


def lint_mermaid(body):
    errs = []
    lines = [l for l in body.splitlines() if l.strip() and not l.strip().startswith("%%")]
    if not lines or not lines[0].strip().startswith(KEYWORDS):
        errs.append("does not start with a known diagram keyword")
    if body.count('"') % 2:
        errs.append("unbalanced double quotes")
    s = re.sub(r'\|"[^"\n]*"\|', "", body)       # edge labels
    s = re.sub(r'"[^"\n]*"', '""', s)            # quoted labels
    for a, b in ("[]", "()", "{}"):
        if s.count(a) != s.count(b):
            errs.append("unbalanced %s%s" % (a, b))
    for ch in "<>|":
        # arrows legitimately contain '>' and edge labels '|'
        t = re.sub(r"[-=.]+>|<[-=.]+|\|[^|\n]*\|", "", s) if ch != "|" else s
        t = re.sub(r"\|[^|\n]*\|", "", t)
        if ch in t:
            errs.append("unquoted %r in a label" % ch)
    return errs


class MermaidBlocks(unittest.TestCase):
    def test_mermaid_lint(self):
        bad = []
        for p, line, lang, body in fences():
            if lang == "mermaid":
                for e in lint_mermaid(body):
                    bad.append("%s:%d: %s" % (p, line, e))
        self.assertEqual(bad, [])

    def test_no_ascii_diagrams(self):
        bad = []
        for p, line, lang, body in fences():
            if lang in ("", "text", "ascii", "txt") and (BOX.search(body) or "-->" in body):
                bad.append("%s:%d: ASCII diagram in a %r fence; use Mermaid or a table"
                           % (p, line, lang or "language-less"))
        self.assertEqual(bad, [])

    @unittest.skipUnless(shutil.which("npx"), "npx not available")
    def test_mermaid_cli_render(self):
        blocks = [(p, l, b) for p, l, lang, b in fences() if lang == "mermaid"]
        if not blocks:
            self.skipTest("no mermaid blocks")
        with tempfile.TemporaryDirectory() as d:
            bad = []
            for i, (p, l, b) in enumerate(blocks):
                src, out = Path(d, "b%d.mmd" % i), Path(d, "b%d.svg" % i)
                src.write_text(b, encoding="utf-8")
                r = subprocess.run(["npx", "-y", "@mermaid-js/mermaid-cli", "-i", str(src),
                                    "-o", str(out)], cwd=d, capture_output=True, text=True)
                if r.returncode or not out.exists():
                    bad.append("%s:%d: %s" % (p, l, (r.stderr or r.stdout)[-300:]))
            self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
