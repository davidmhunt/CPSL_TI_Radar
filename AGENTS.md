# AGENTS.md

Guidance for coding agents in this repository. This file is loaded into every
session, so it stays lean — detail lives in on-demand docs. **Load only what
your task needs, per this index:**

> [!NOTE]
> This repo has two kinds of content. `docs/`, source, tests and this file
> are project content, tracked in the project's own repo — they must keep
> making sense after the harness is removed. `.friday/` is the harness
> itself: `.friday/` is the portable git submodule (shared across every
> project that uses it), and `.friday/active/` inside it is this project's
> generated, local-only harness working state (gitignored within the
> submodule — see below). Don't confuse harness working state with
> project content: a directive spec or a status dashboard is disposable
> scaffolding, not something the project's history depends on.

> [!NOTE]
> `.friday/active/` lives inside the `.friday` git submodule and is
> gitignored *there* (it's generated, per-project state, not part of the
> friday repo's own history). A git-ignore-respecting search — `git grep`,
> or `rg` without a flag — will not find anything under
> `.friday/active/harness/`. Read those files directly by path, or pass
> `rg --no-ignore` if you need to search across them.

| Before you… | Read |
|-------------|------|
| Run any script or test | `.friday/active/harness/rules/environment.md` (env, launch pattern) |
| Launch/check/trust a long-running job or monitor | `.friday/active/harness/rules/monitoring.md` |
| Read large files, run builds/tests, or review diffs | `.friday/active/harness/rules/context_hygiene.md` (keep context small) |
| Mutate any canonical data artifact (re-generate, re-render, ground truth) | `.friday/active/harness/rules/data_artifacts.md` — snapshot FIRST |
| Change driver internals (DCA1000 RX, serial TLV, configs, ADC cube layout) | `docs/ARCHITECTURE.md` |
| Build, flash, or bring up firmware; touch `firmware_dev/` or a board | `docs/firmware.md` (Firmware role's facts) |
| Configure a host for DCA1000 streaming or serial ports | `CPSL_TI_Radar_cpp/Readme.md` (system prerequisites) |
| Plan v2.0 work on the cascade | `planning/CASCADE_PLAN.md`, `planning/CASCADE_HARDWARE_SETUP.md` |
| Open, comment on, or close a tracker issue (rule 13) | AGENTS.md "Tracker credentials" below |
| Drive the harness (as the user) | `.friday/active/harness/USER_GUIDE.md` |
| Act as an assigned agent role | `.friday/active/harness/harness.md` (core rules) + `.friday/active/harness/roles/<your-role>.md` only |

## Project facts

| | |
|---|---|
| Project | CPSL TI Radar — host-side drivers, configs, firmware and tools for TI mmWave radars; on `release/v2.0` for a full v2.0 rework |
| Working root | `/home/cpsl/Documents/radar_dev/CPSL_TI_Radar` |
| Results doc (rule 2) | `docs/RESULTS.md` — measured streaming rates, drop counts, on-board check results |
| Environment | uv (`uv run ...`); see `.friday/active/harness/rules/environment.md` |
| Accelerators | none. The scarce hardware is the radars: EVMs, their serial ports and the DCA1000 are single-user — claim them in `status.md` |
| Work record (rule 12) | git + `git@github.com:davidmhunt/CPSL_TI_Radar.git`; a "record" = a commit, referenced by hash |
| Who records work | Each producing role commits its own work, scoped to the paths it touched, on a non-`main` branch where `git commit` is auto-allowed (rule 12); the Reviewer verifies the record at close-out, and only the user approves a merge to `main` |
| Queue mirror (rule 13, opt-in) | github-issues — one issue per directive; the Controller opens it when the user approves the directive, the Reviewer closes it ("none" = not tracked externally) |
| Project specialists | `firmware` — TI firmware in `firmware_dev/`, shipped images, flashing and on-board bring-up; facts in `docs/firmware.md`; role file `.friday-project/roles/firmware.md` |
| Antigravity models | every role, `-heavy` included, runs on `flash`; for `[heavy]` work start the session with `agy --effort high` (no per-agent effort field) |
| Docker dev container | `false` — when enabled, the image installs `uv` plus the `claude,antigravity` CLI(s); see `.friday/reference/docker.md` to set up or reconfigure |

## Project Overview

CPSL TI Radar is the Collaborative Perception and Sensing Lab's host-side
stack for TI mmWave radars: IWR1443/1843/6843 single-chip sensors and the
AWR2243 2-chip cascade (AM273x). The C++ driver (`CPSL_TI_Radar_cpp/`)
configures a radar over its CLI serial port, then streams either raw ADC
data through a DCA1000 capture card (UDP, high-rate, real-time threads) or
the on-chip demo's TLV point cloud over a serial data port. Prebuilt
firmware ships with the repo; the opt-in `firmware_dev/` submodule
reproduces it from source in a Docker build environment, with TI SDKs and
toolchains downloaded rather than tracked.

Work is on `release/v2.0`, a full rework toward a v2.0 release: clear out
unused code, make the driver more efficient and customizable, add firmware
generation (build → publish shipped images with provenance), add a
single-process web GUI (Python backend + no-build-step `web/` frontend,
growing out of `tools/radar_viewer/`), and add Docker support for firmware
builds and driver runs (native builds stay the default). The defining
constraint is real hardware: boards, serial ports and the DCA1000 are
single-user, flashing and power-cycling need a human at the bench, and the
cascade demo accepts a cfg only once per power-up. ROS 2 Jazzy is sourced
on the dev host, so its `PYTHONPATH` is visible inside `uv` environments.

## Tracker credentials

A gitignored, mode-600 `.env` at the repo root holds the credential `gh issue` needs; `gh` itself is not logged in. Run from the repo root:
`(set -a; . ./.env; set +a; gh issue list --limit 3)`.
Never print or read the token: no `cat`/`grep` of `.env`, no `env`/`set` dumps, no `gh auth token`.
If `gh` returns 401, tell the user — do not hunt for other credentials.
`.env` must stay gitignored (`git check-ignore -v .env`).

## Session Continuity

Multiple agents/sessions work here, sometimes concurrently — treat state as
shared, not private to one session.

- **`.friday/active/harness/status.md`** is the living dashboard: the open
  loops (named workstreams, each owned by one Controller session), the OPEN
  directives (owner, state, what's left — the answer to "what is directive
  X doing right now"), claims on single-user resources (a hardware board, a
  file a GUI tool holds open), what's running, recent milestones, open
  issues. Read it at session start; update it on real progress, directive
  pickup/handoff, job start/finish, or blockers — it must reflect current
  reality. Edit only rows belonging to your own loop. Keep entries terse;
  link to your results doc or the relevant script/output instead of
  duplicating detail. `.friday/active/harness/status_history.md` holds a
  directive's record once the Reviewer closes it — check it for the outcome
  of past directives. `.friday/active/harness/plans/directives/<ID>.md` is
  the directive itself — goal, steps, `Verify:`, and a running Log — and
  moves to `plans/directives/closed/` at close-out. Like everything under
  `.friday/active/`, it is local state; the commits and tracker issue are
  the durable record.
- **`docs/RESULTS.md`** is the comprehensive
  results reference (see harness rule 2 — single source of truth for
  numbers). Update on significant milestones (new version, finalized
  result, systemic bug fix, real ablation) — not every incremental step.
  Prefer the pattern: result table + honest interpretation, including
  negative results with real caveats.

## Repository Layout

| Dir | Contents |
|-----|----------|
| `CPSL_TI_Radar_cpp/` | C++ driver (primary): `CLIController`, `SerialStreamer`, DCA1000 streaming, the `Radar` API; configs in `config/radar/` and `config/system/`; `include/json` submodule. Build: `cmake -S CPSL_TI_Radar_cpp -B CPSL_TI_Radar_cpp/build && cmake --build CPSL_TI_Radar_cpp/build -j` |
| `firmware_dev/` | Opt-in submodule (`CPSL_TI_Radar_Firmware_Dev`, `release/v2.0`): firmware sources, Docker build env, download/build/flash scripts — Firmware role's namespace, see `docs/firmware.md` |
| `Firmware/` | v1 prebuilt images (`IWR_Demos/`, `DCA1000_Streaming/` + `iwr_raw_rosnode` submodule); to be reorganized into the v2.0 shipped-firmware directory |
| `DCA_Programming/` | DCA1000 FPGA network reprogramming: docs and source |
| `tools/radar_viewer/` | Cascade live point-cloud viewer (stdlib HTTP + pyserial) — seed of the v2.0 GUI |
| `utilities/` | Notebooks for post-processing driver output (ADC cube, raw LVDS, `.cfg`), serial-port and DCA1000 network debugging, and a TI SDK LVDS parser example |
| `tests/` | pytest suite (`uv run pytest`); C++ unit tests are in `CPSL_TI_Radar_cpp/tests/` and run via `ctest` (see "Running tests" below) |
| `planning/` | Cascade plan and hardware bring-up notes |
| `docs/` | `ARCHITECTURE.md`, `RESULTS.md`, `firmware.md` |
| `readme_images/` | IWR boot-mode (SOP) diagrams linked from `CPSL_TI_Radar_cpp/Readme.md` |
| `.friday/active/harness/` | Multi-agent harness: core rules, role definitions, per-rule detail docs, the live dashboard (`status.md` + `status_history.md`, unless `.friday/active/harness/status_history.md` points elsewhere), goals and directives (`plans/`), and the Reviewer/Runner working folders (`review/`, `running/`). |
| `.friday-project/` | Project-owned harness extensions, tracked in this repo: `roles/<role>.md` for each project specialist (linked into `.friday/active/harness/roles/` by `init_harness.py`). Omit if the project has none. |
| `docs/research/` | The Researcher's memos — tracked project content, not part of the `.friday/` submodule's generated output. |

Conventions: all paths relative to the repo root
(`/home/cpsl/Documents/radar_dev/CPSL_TI_Radar`), no hardcoded absolute paths in
code. uv manages dependencies — every run goes
through `uv run`.

## Multi-Agent Workflow

The harness runs as a small team with a lead. The user works with the
**Controller** (start it with `claude --agent controller`, or "you are the
controller"), which is the user's single point of contact:

1. The user gives the Controller a goal; the Controller asks whatever it
   needs to.
2. The **Planner** turns the goal into one or more directives.
3. **The user approves each directive before any work starts.**
4. The Controller dispatches the specialists — **Coder**, **Runner**,
   **Researcher**, **Author**, **Editor**, plus any project specialists
   listed under Project facts — and iterates inside the approved scope.
5. The **Reviewer** closes each directive against its `Verify:` line.

The **Architect** is optional. It writes a short (≤ 2-page) requirements
spec in `docs/specs/` when work needs a signed scope. Several loops can run
at once, in one Controller session or one per terminal. Roles other than
the Controller and a directly-opened Architect run as subagents, with spawn
titles `role(model): task` (e.g. `coder(<mid-tier model>): <task>`);
utility spawns keep plain titles.

**CRITICAL:** `.friday/active/harness/harness.md` holds the loop and the shared rules every
role must follow; `.friday/active/harness/roles/<role>.md` holds your role's namespace,
tier, constraints, and handoff protocol. Read the core plus your own role
file — not the other roles' files. Rule detail docs under `.friday/active/harness/rules/`
are read only when a rule's trigger matches your next action.

## Running tests

- C++ (hardware-free unit tests, in-tree harness, no extra dependencies):
  `cmake -S CPSL_TI_Radar_cpp -B CPSL_TI_Radar_cpp/build && cmake --build CPSL_TI_Radar_cpp/build -j && ctest --test-dir CPSL_TI_Radar_cpp/build --output-on-failure`.
  Add a test as `CPSL_TI_Radar_cpp/tests/test_<name>.cpp` plus an `add_driver_test` line in `tests/CMakeLists.txt`; details in `CPSL_TI_Radar_cpp/Readme.md`. Tests pin current behaviour; a bug found is recorded with `KNOWN_BUG(...)`, not fixed in the test pass.
- C++ replay benchmark (not part of the plain `ctest` run): build with `-DCMAKE_BUILD_TYPE=Release`, then `ctest --test-dir <build> -C bench -L bench --verbose` (`bench_pipeline`; see `CPSL_TI_Radar_cpp/Readme.md`).
- Python: `uv run pytest` (`pyproject.toml` disables ROS's `launch_testing`/`launch_ros` plugins, so it passes with ROS sourced or not).

## Command Execution & Approval Policy

Under the Antigravity adapter, command execution is programmatically guarded
by `.agents/hooks.json` via `.agents/hooks/command_guard.py` before
`run_command` executes (Claude Code sessions are not covered by this hook;
they use Claude Code's own permission settings):

- **Auto-allowed (`allow`)**: `uv sync`,
  `uv run`, `cmake -S CPSL_TI_Radar_cpp -B CPSL_TI_Radar_cpp/build && cmake --build CPSL_TI_Radar_cpp/build -j && ctest --test-dir CPSL_TI_Radar_cpp/build --output-on-failure && uv run pytest`,
  read-only git queries
  (`git status`, `git diff`, `git log`, `git show`, `git branch`),
  `git commit` **when the checked-out branch is not `main`/`master`** (see
  `.friday/active/harness/rules/version_control.md` §Branching),
  and non-destructive inspections (`ls`, `cat`, `grep`, `rg`, `find`, `pwd`).
- **Requires user approval (`force_ask`)**: `git commit` **on `main`/`master`** (or when the
  branch cannot be determined — the guard fails closed), and every other state-modifying
  git command on any branch (`git push`, `git merge`, `git checkout`, `git switch`,
  `git reset`), background jobs (`systemd-run`,
  `setsid`), dependency modifications (`uv add` and its
  remove counterpart), file deletions (`rm`, `unlink`), and unclassified commands.
- **Strictly forbidden (`deny`)**: Privilege escalation (`sudo`, `su`), force pushes
  (`git push --force`, and the `git push origin +main` refspec spelling), adding a new
  git remote, unscoped destructive wipes (`rm -rf` aimed at `/`, `~`, `.`, `..`, or a bare
  `*`), and fetching remote scripts into a shell (`curl | sh`, `curl … && sh …`,
  `eval "$(curl …)"`).

**Inside the Docker dev container this policy is reduced to its deny list.**
`docker/docker-compose.harness.yml` sets `ANTIGRAVITY_CONTAINER=1`, which switches the guard into
container mode: deny still applies, but force-ask and the allow list are skipped and
anything unrecognized runs without confirmation. Do not read a successful command in
the container as evidence that it would have been permitted on the host.

