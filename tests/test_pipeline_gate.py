"""tools/bench/pipeline_gate.py: the layout-robust perf gate (directive core-14 Step 1).

The fixture is a real `bench_pipeline` stdout; the tests derive before/after
runs from it by scaling one row's ns/byte (or allocs/frame, or the frame
count) and check the verdict and exit code.
"""
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools/bench"))
import pipeline_gate as gate  # noqa: E402

SAMPLE = (REPO / "tests/fixtures/pipeline_gate/bench_pipeline_sample.txt").read_text()


def scaled(text, row=None, factor=1.0, allocs=None, frames_done=None):
    """`text` with one row's ns/byte medians multiplied by `factor` (and its
    allocs/frame set to `allocs`); `frames_done` rewrites every golden line."""
    out = []
    for line in text.splitlines():
        m = gate.ROW_RE.match(line)
        if m and row and f"{m['scenario']} ({m['id']})" == row:
            ns = float(m["ns"]) * factor
            line = line[:m.start("ns")] + f"{ns:8.3f}"[-len(m["ns"]):].rjust(len(m["ns"])) + line[m.end("ns"):]
            if allocs is not None:
                a = f"{allocs:.1f}"
                line = line[:m.start("allocs")] + a.rjust(len(m["allocs"])) + line[m.end("allocs"):]
        if frames_done is not None:
            line = re.sub(r"frames completed \d+ of (\d+) \(= golden\)",
                          lambda g: f"frames completed {frames_done} of {g[1]} (NOT golden)", line)
        out.append(line)
    return "\n".join(out) + "\n"


def write_set(tmp_path, before_def, after_def, before_al, after_al, runs=3):
    files = []
    for role, build, text in (("before", "default", before_def), ("after", "default", after_def),
                              ("before", "aligned", before_al), ("after", "aligned", after_al)):
        for i in range(1, runs + 1):
            p = tmp_path / f"step_{role}_{build}_{i}.txt"
            p.write_text(text)
            files.append(p)
    return files


def run_gate(files, *extra):
    return gate.main([str(f) for f in files] + list(extra))


def test_parser_reads_every_row_and_golden_line(tmp_path):
    p = tmp_path / "x_before_default_1.txt"
    p.write_text(SAMPLE)
    run = gate.parse_run(p)
    assert gate.role_of(p) == ("before", "default")
    # 4 kernel groups x (a, b, c) + 3 driver rows (d)
    assert len(run.rows) == 15
    assert run.rows["converter (a)"][1] == 1013.0
    assert "drv_save (d)" in run.rows and "drv_drop_1pct (d)" in run.rows
    assert set(run.golden) == {"clean", "drop_1pct", "dup_reorder", "drv_clean", "drv_drop_1pct", "drv_save"}
    assert all(d == w for d, w in run.golden.values())


def test_identical_runs_pass(tmp_path, capsys):
    files = write_set(tmp_path, SAMPLE, SAMPLE, SAMPLE, SAMPLE)
    assert run_gate(files) == 0
    out = capsys.readouterr().out
    assert "### default build (3 before, 3 after runs)" in out
    assert "| clean (a) |" in out and "+0.0%" in out
    assert "- PASS:" in out


def test_regression_in_both_builds_fails(tmp_path, capsys):
    slow = scaled(SAMPLE, "clean (b)", 1.10)
    files = write_set(tmp_path, SAMPLE, slow, SAMPLE, slow)
    assert run_gate(files) == 1
    out = capsys.readouterr().out
    assert "FAIL: clean (b): regression" in out
    assert re.search(r"default \+(9\.\d|10\.\d)%, aligned \+(9\.\d|10\.\d)%", out)


def test_shift_in_one_build_only_passes_with_a_note(tmp_path, capsys):
    slow = scaled(SAMPLE, "converter (c)", 1.75)  # the core-11 P1 layout shift
    files = write_set(tmp_path, SAMPLE, slow, SAMPLE, SAMPLE)
    assert run_gate(files) == 0
    out = capsys.readouterr().out
    assert re.search(r"note: converter \(c\): default build \+7\d\.\d% but aligned \+0\.0%", out)
    assert "layout noise, not blocking" in out
    assert "- PASS:" in out


def test_threshold_is_strictly_more_than_five_percent(tmp_path):
    at = scaled(SAMPLE, "clean (a)", 1.04)
    files = write_set(tmp_path, SAMPLE, at, SAMPLE, at)
    assert run_gate(files) == 0
    assert run_gate(files, "--threshold", "3") == 1


def test_allocations_may_never_rise(tmp_path, capsys):
    more = scaled(SAMPLE, "clean (b)", 1.0, allocs=1.0)
    files = write_set(tmp_path, SAMPLE, SAMPLE, SAMPLE, more)  # one build is enough
    assert run_gate(files) == 1
    assert "allocations/frame rose in the aligned build (0.0 -> 1.0)" in capsys.readouterr().out


def test_fewer_allocations_pass(tmp_path):
    fewer = scaled(SAMPLE, "clean (a)", 0.5, allocs=0.0)
    files = write_set(tmp_path, SAMPLE, fewer, SAMPLE, fewer)
    assert run_gate(files) == 0


def test_after_run_not_golden_fails_before_run_only_noted(tmp_path, capsys):
    short = scaled(SAMPLE, frames_done=39)
    assert run_gate(write_set(tmp_path, SAMPLE, short, SAMPLE, SAMPLE)) == 1
    assert "completed 39 of 40 frames (not golden)" in capsys.readouterr().out
    for f in tmp_path.iterdir():
        f.unlink()
    assert run_gate(write_set(tmp_path, short, SAMPLE, short, SAMPLE)) == 0
    assert "(before run, informational)" in capsys.readouterr().out


def test_new_row_is_not_gated_and_a_dropped_row_fails(tmp_path, capsys):
    without = "\n".join(l for l in SAMPLE.splitlines() if "drv_save     (d)" not in l) + "\n"
    assert run_gate(write_set(tmp_path, without, SAMPLE, without, SAMPLE)) == 0
    assert "drv_save (d): new row" in capsys.readouterr().out
    for f in tmp_path.iterdir():
        f.unlink()
    assert run_gate(write_set(tmp_path, SAMPLE, without, SAMPLE, without)) == 1
    assert "drv_save (d): row missing from the after runs" in capsys.readouterr().out


def test_bad_names_and_missing_groups_exit_2(tmp_path):
    p = tmp_path / "run1.txt"
    p.write_text(SAMPLE)
    assert run_gate([p]) == 2
    files = write_set(tmp_path, SAMPLE, SAMPLE, SAMPLE, SAMPLE)
    only_default = [f for f in files if "default" in f.name]
    assert run_gate(only_default) == 2
    empty = tmp_path / "x_before_default_9.txt"
    empty.write_text("nothing here\n")
    assert run_gate(files + [empty]) == 2


def test_cli_runs_under_uv_style_invocation(tmp_path):
    files = write_set(tmp_path, SAMPLE, SAMPLE, SAMPLE, SAMPLE, runs=1)
    r = subprocess.run([sys.executable, str(REPO / "tools/bench/pipeline_gate.py"), *map(str, files)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "### aligned build (1 before, 1 after runs)" in r.stdout
