#!/usr/bin/env python3
"""Layout-robust perf gate over saved `bench_pipeline` outputs (directive core-14).

A perf change is measured as before/after pairs in two Release builds of the
same tree: the default build and the `bench-aligned` preset build
(`-falign-functions=64 -falign-loops=64`). Each build runs
`bench_pipeline --frames 400` before/after interleaved x3; every run's stdout
is saved to a file. This script reads those files and applies the gate
(history.md, core-11 P1 ruling):

* a row is a **regression** only if its mean ns/byte is more than the
  threshold (default 5%) slower **in both builds**; a shift in one build only
  is code-layout noise: it is reported, not blocking;
* allocations/frame may never rise (any build, any row);
* every replay row of every "after" run must complete the golden frame count.

Each file's role comes from its name, which must contain `before` or `after`
and `default` or `aligned`, e.g. `p3_before_default_1.txt` or
`after-aligned-2.log`. Rows are keyed by scenario and variant id
(`clean (a)`), so a changed variant label does not break the comparison.

Usage:
    uv run tools/bench/pipeline_gate.py FILE... [--threshold PCT]

Prints one markdown table per build (runs, delta of the mean, allocs/frame)
and the verdict. Exit 0: pass; 1: regression, allocation rise or a run not
golden; 2: usage error or unreadable input.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean

# "  clean        (a) today ADCCubeConverter    793.3 [  838.8]    2.501 [   2.366]   1013.0    1.00x"
ROW_RE = re.compile(
    r"^\s+(?P<scenario>\S+)\s+\((?P<id>\w)\)\s+(?P<label>.*?)\s+"
    r"(?P<fps>[\d.]+)\s+\[\s*(?P<fps_best>[\d.]+)\]\s+"
    r"(?P<ns>[\d.]+)\s+\[\s*(?P<ns_best>[\d.]+)\]\s+"
    r"(?P<allocs>[\d.]+)\s+(?:[\d.]+x|-)\s*$"
)
# "    drop_1pct    13650 packets (...); frames completed 40 of 40 (= golden); ..."
GOLDEN_RE = re.compile(r"^\s+(?P<scenario>\S+)\s+\d+ packets .*?frames completed (?P<done>\d+) of (?P<want>\d+)")
ROLE_RE = re.compile(r"(?:^|[^a-z])(before|after)(?:[^a-z]|$)")
BUILD_RE = re.compile(r"(?:^|[^a-z])(default|aligned)(?:[^a-z]|$)")

BUILDS = ("default", "aligned")
ALLOC_EPS = 0.05  # allocs/frame is printed with one decimal


class GateError(Exception):
    """Unusable input (exit 2)."""


@dataclass
class Run:
    path: Path
    rows: dict[str, tuple[float, float]] = field(default_factory=dict)  # key -> (ns/byte median, allocs/frame)
    golden: dict[str, tuple[int, int]] = field(default_factory=dict)    # scenario -> (done, wanted)


def parse_run(path: Path) -> Run:
    run = Run(path)
    try:
        text = path.read_text()
    except OSError as e:
        raise GateError(f"cannot read {path}: {e}") from e
    for line in text.splitlines():
        m = ROW_RE.match(line)
        if m:
            key = f"{m['scenario']} ({m['id']})"
            run.rows[key] = (float(m["ns"]), float(m["allocs"]))
            continue
        g = GOLDEN_RE.match(line)
        if g:
            run.golden[g["scenario"]] = (int(g["done"]), int(g["want"]))
    if not run.rows:
        raise GateError(f"{path}: no bench_pipeline rows found")
    return run


def role_of(path: Path) -> tuple[str, str]:
    name = path.name.lower()
    roles = set(ROLE_RE.findall(name))
    builds = set(BUILD_RE.findall(name))
    if len(roles) != 1 or len(builds) != 1:
        raise GateError(f"{path.name}: the name must contain exactly one of before/after "
                        f"and one of default/aligned")
    return roles.pop(), builds.pop()


@dataclass
class RowResult:
    key: str
    build: str
    before: list[float]
    after: list[float]
    allocs_before: float | None
    allocs_after: float | None

    @property
    def delta(self) -> float | None:
        if not self.before or not self.after:
            return None
        b = mean(self.before)
        return (mean(self.after) - b) / b * 100.0 if b > 0 else None


def compare(groups: dict[tuple[str, str], list[Run]]) -> dict[str, dict[str, RowResult]]:
    """build -> row key -> RowResult, rows in first-seen order."""
    out: dict[str, dict[str, RowResult]] = {}
    for build in BUILDS:
        before, after = groups[("before", build)], groups[("after", build)]
        keys: list[str] = []
        for r in before + after:
            for k in r.rows:
                if k not in keys:
                    keys.append(k)
        res: dict[str, RowResult] = {}
        for k in keys:
            b = [r.rows[k] for r in before if k in r.rows]
            a = [r.rows[k] for r in after if k in r.rows]
            res[k] = RowResult(
                key=k, build=build,
                before=[x[0] for x in b], after=[x[0] for x in a],
                allocs_before=max(x[1] for x in b) if b else None,
                allocs_after=max(x[1] for x in a) if a else None,
            )
        out[build] = res
    return out


def fmt_runs(v: list[float]) -> str:
    return " ".join(f"{x:.3f}" for x in v) if v else "-"


def fmt_allocs(v: float | None) -> str:
    return "-" if v is None else f"{v:.1f}"


def table(rows: dict[str, RowResult]) -> list[str]:
    lines = ["| row | before ns/byte (runs) | after ns/byte (runs) | Δ mean | allocs/frame before→after |",
             "|---|---|---|---|---|"]
    for r in rows.values():
        d = r.delta
        lines.append(f"| {r.key} | {fmt_runs(r.before)} | {fmt_runs(r.after)} | "
                     f"{'-' if d is None else f'{d:+.1f}%'} | "
                     f"{fmt_allocs(r.allocs_before)}→{fmt_allocs(r.allocs_after)} |")
    return lines


def gate(groups: dict[tuple[str, str], list[Run]], threshold: float) -> tuple[list[str], bool]:
    """The report lines and whether the gate passed."""
    res = compare(groups)
    lines: list[str] = []
    for build in BUILDS:
        n_b, n_a = len(groups[("before", build)]), len(groups[("after", build)])
        lines.append(f"### {build} build ({n_b} before, {n_a} after runs)")
        lines.append("")
        lines.extend(table(res[build]))
        lines.append("")

    failures: list[str] = []
    notes: list[str] = []
    keys = list(dict.fromkeys(list(res["default"]) + list(res["aligned"])))
    for k in keys:
        per_build = {b: res[b].get(k) for b in BUILDS}
        deltas = {b: (r.delta if r else None) for b, r in per_build.items()}
        if any(r is None or not r.before or not r.after for r in per_build.values()):
            missing = [b for b, r in per_build.items() if r is None or not r.before or not r.after]
            if any(r is not None and r.before and not r.after for r in per_build.values()):
                failures.append(f"{k}: row missing from the after runs ({', '.join(missing)})")
            else:
                notes.append(f"{k}: new row (no before data in {', '.join(missing)}), not gated")
        else:
            slow = [b for b in BUILDS if deltas[b] is not None and deltas[b] > threshold]
            if len(slow) == len(BUILDS):
                failures.append(f"{k}: regression, slower by more than {threshold:g}% in both builds "
                                f"({', '.join(f'{b} {deltas[b]:+.1f}%' for b in BUILDS)})")
            elif slow:
                b = slow[0]
                other = BUILDS[1] if b == BUILDS[0] else BUILDS[0]
                notes.append(f"{k}: {b} build {deltas[b]:+.1f}% but {other} {deltas[other]:+.1f}%: "
                             f"one build only = layout noise, not blocking")
        for b, r in per_build.items():
            if r and r.allocs_before is not None and r.allocs_after is not None \
                    and r.allocs_after > r.allocs_before + ALLOC_EPS:
                failures.append(f"{k}: allocations/frame rose in the {b} build "
                                f"({r.allocs_before:.1f} -> {r.allocs_after:.1f})")

    for (role, build), runs in sorted(groups.items()):
        for run in runs:
            for scen, (done, want) in run.golden.items():
                if done != want:
                    msg = f"{run.path.name}: {scen} completed {done} of {want} frames"
                    if role == "after":
                        failures.append(msg + " (not golden)")
                    else:
                        notes.append(msg + " (before run, informational)")

    lines.append("### Verdict")
    lines.append("")
    for n in notes:
        lines.append(f"- note: {n}")
    for f in failures:
        lines.append(f"- FAIL: {f}")
    lines.append(f"- {'FAIL' if failures else 'PASS'}: threshold {threshold:g}% in both builds, "
                 f"allocs/frame never rise, every after run golden")
    return lines, not failures


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", type=Path,
                    help="saved bench_pipeline outputs; names contain before|after and default|aligned")
    ap.add_argument("--threshold", type=float, default=5.0,
                    help="slowdown (%%) that counts when seen in both builds (default 5)")
    args = ap.parse_args(argv)
    try:
        groups: dict[tuple[str, str], list[Run]] = {(r, b): [] for r in ("before", "after") for b in BUILDS}
        for p in sorted(args.files):
            groups[role_of(p)].append(parse_run(p))
        empty = [f"{r}/{b}" for (r, b), runs in groups.items() if not runs]
        if empty:
            raise GateError(f"no runs for {', '.join(empty)} (need before and after in both builds)")
    except GateError as e:
        print(f"pipeline_gate: {e}", file=sys.stderr)
        return 2
    lines, ok = gate(groups, args.threshold)
    print("\n".join(lines))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
