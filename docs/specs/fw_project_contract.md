# Firmware project contract — requirements

**Status:** signed off 2026-10-08 (user); amended 2026-10-08 (user)
**Owner:** fwstd loop · **Sponsor:** user · **Serves:** firmware standardisation (fwstd-03..08) and the later GUI build/flash/verify directive

Every project in `firmware_dev/projects/` (`ti_stock_demos`, `iwr1843_sar_lvds`,
`awr2243_cascade_ddm`, `_template`) follows one manifest, one set of `fw` verbs,
one machine interface and one set of flash gates. A person and a future GUI
drive the same verbs; the GUI reads only `fw` JSON (Appendix A).

**Done when:** (a) hardware-free, fwstd-03: every R passes on a fake board and
fake `docker`, `fw test` passes per project, `publish` targets a scratch dir only;
(b) user bench, fwstd-09: a no-TTY script builds, flashes (token) and verifies each
flashable project (cascade verify reports `skipped`).

## Requirements

| ID | Requirement | Verification | Threshold |
|----|-------------|--------------|-----------|
| R1 | `projects/<p>/project.toml` replaces `project.env` (stdlib `tomllib`); `project.env` is read only during migration, with a stderr deprecation line. | `fw test` schema check | 0 invalid; 0 `.env`-only at fwstd-08 |
| R2 | Tables: `[project]` name, summary, `status` (`stub\|source\|built\|bench`); `[deps]` sdk, sdk_version, toolchain, `download_items`; `[source]` baseline, baseline_commit; `[build]` script, `variants` (selected by `--variant`), est_minutes. Required tables by status: A5. | Validator: missing/unknown key, wrong type, bad enum | Exit 1 naming the key path |
| R3 | `[[artifact]]` (first = default image): file, board, `descriptor` (id in `../CPSL_TI_Radar_cpp/config/firmware/`, or `""`), `flashable`. | `fw test`; parent pytest, both directions | 0 mismatches |
| R4 | `[flash]`: method (`dslite\|uart_uniflash\|manual`), gate (`sop\|j6`), port_glob, `mode_steps`, `after_steps`, success_marker, optional `manual_images` (see Amendment 4). The gate comes from the manifest, not `*.ccxml` presence. | Ccxml added/removed; `--dry-run` per project | Same gate; exit 0; checklist, command, sha256 shown |
| R5 | `[verify]` holds only cli_port_glob, baud, descriptor. Probes, timeout, `once_safe` live only in the descriptor `identify` block, which wins on conflict. | `fw test` | 0 probe keys in manifest; `identify` exists |
| R6 | `[test]`: host `commands`, `cfgs` (tracked cfg globs, never `build/`; parent tests use them, not `rglob`), `bench_doc` (default `docs/bench_check.md`). | Stray `build/x.cfg` | Exit 0; stray cfg ignored |
| R7 | Verbs `fw list \| ports [<p>] \| new \| deps \| build \| test \| flash \| verify \| publish \| help`, each with `--help` and `--json`; `build` first runs `deps`. `fw flash <p> <port> [image]` stays accepted, plus `--dry-run`, `--plan`, `--confirm`. | Table test; SAR `--dry-run` golden | Golden has checklist, command, sha256 |
| R8 | Locks (A4) serialise `flash`/`verify` per port and `build`/`publish` per project. **Held** = a process has the tty (fuser/lsof) or the fw lock is live. | Concurrent flash; kill -9, retry | Second gets exit 4; stale lock reclaimed |
| R9 | `fw test <p>` needs no hardware or Docker: schema, descriptor consistency, cfgs, `[test]` commands, `build --dry-run`. Template TODOs warn. | Every project and `fw new x` | Exit 0 |
| R10 | `--json`: JSON Lines on stdout, text on stderr; events and `fw list` shape per Appendix A. | Validate every line against the A2/A3 schemas | 100% valid; exactly 1 `result`, last |
| R11 | Without a TTY `fw` never prompts; a missing confirmation exits 5 with a reason. | Each verb, `</dev/null`, 10 s timeout | No hang |
| R12 | Exit codes (Appendix A1): 0 ok; 1 failed; 2 usage; 3 unsupported / manual; 4 precondition refused; 5 confirmation not given or token invalid. | One test per A1 row | Only A1 codes emitted |
| R13 | TTY path. Gates, each with a test `gate_Gn`: G1-G7 in A6, cascade included; under `--json` a non-by-id port is refused, so the GUI flashes by-id ports only. | Reviewer diff vs old `gated_flash()`; seven tests | All present, passing |
| R14 | Non-TTY path. `fw flash <p> <port> [image] --plan --json` runs G1-G5 and returns the checklist and a single-use token; `--confirm <token>` re-runs G2-G4 and the sha256, then flashes. The flash tool runs only after G6 or a valid token; no flag bypasses both. Token store and rules: A4. | Tests, one per A4 rule | Exit per A1; no flash |
| R15 | On SIGINT/SIGTERM `fw` kills the child tool, emits `result` code 1 reason `cancelled`, releases locks, prints `after_steps` (board may stay in flash mode). | Signal fake flash | Child dead; locks gone |
| R16 | `fw verify <p> [--port P]` sends only the descriptor's probes (never a chirp/sensor cfg), refuses a held or non-by-id port, maps `require`/`reject` to `outcome` pass/fail. `once_safe: false` (cascade): sends nothing, `outcome` skipped. Descriptor (R3 path) absent or without `identify`: exit 3 with a reason. | Pty fake board, 6 cases | Exits per A1; 0 bytes written when skipped |
| R17 | `fw build` writes `build/build_info.json`: project, firmware_dev commit (never `unknown`), `dirty`, variant, toolchain, time, sha256 of every artifact. Dirty and stale: A7. Git unavailable: exit 4. | Fake builds, each A7 case | `fw list` reports `none\|clean\|dirty\|stale` correctly |
| R18 | `fw publish <p> [--dest D]` publishes flashable artifacts with a non-empty descriptor: image + `<image>.provenance.json` (project, commit, variant, toolchain, sha256, time, chirp cfg) to `<D>/<BOARD>/<descriptor>/`; default D is the parent's `shipped_firmware/`. | Scratch dest | Hashes equal; others skipped |
| R19 | Publish refuses (exit 4) a dirty or stale build (R17). | Dirty, stale, edited-image tests | Exit 4; nothing written |
| R20 | Each project has hardware-free host tests and a user-run `docs/bench_check.md` (headings: Preconditions, Board state, Steps, Expected output, Pass/fail, Results log). | `fw test` heading check | All six present |
| R21 | Each README has headings: Purpose, Status, Build, Test, Flash, Verify, Bench check, Layout, Changes vs TI, Known limits. Status is one line quoting `fw list`. | Heading check; `grep -E '20[0-9]{2}-[0-9]{2}-[0-9]{2}'` on README | All present; 0 dates |
| R22 | Bench record lives only in the manifest: `[[bench]]` board, date, image sha256, result (`pass\|partial\|fail`), doc link. Consistency rules: A5. | Fixtures | 0 inconsistent; reason present |

## Constraints and interfaces

- `fw` stays bash; logic is stdlib Python 3.11+.
- Descriptors gain `source: {fw_project, artifact}` (`null` for prebuilts `dca1000_raw`, IWR1443 `demo`); `flash_hint` names a real project.
- `tools/cascade_serial_check.py` moves into `awr2243_cascade_ddm`; `verify` replaces it.
- The cascade takes a cfg once per power-up; `fw` never sends one.

## Out of scope

The GUI; real publishing of TI-derived binaries (pending a ruling); multi-board flashing; firmware changes.

## Decisions

Decided 2026-10-08 (user): `--confirm` needs no typed phrase (TTY path keeps it); `status` levels (R2) and README sections (R21) as written; descriptor `source` as in Constraints. Changed from today by the Architect: a wrong typed phrase exits 5 (was 1). No open decisions.

## Pointers

`firmware_dev/fw`; `projects/README.md` §3-4; `iwr1843_sar_lvds`; fwstd-01 Evaluation.

## Appendix A — Machine interface

**A1 Exit codes**

| Situation | Code |
|---|---|
| success; `verify` skipped (`once_safe` false) | 0 |
| build/flash tool failed; verify outcome fail, timeout or no response; bad manifest (R2); cancelled | 1 |
| bad arguments, unknown project | 2 |
| `manual` flash method; verify with no descriptor or no `identify` | 3 |
| image outside `firmware_dev/`; port missing, held, or non-by-id under `--json`; deps missing; image missing; lock held; dirty/stale on publish; token's port gone or image sha256 changed; git unavailable | 4 |
| no TTY and no token; wrong typed phrase; non-by-id port on TTY without acknowledgement; token unknown, expired or reused | 5 |

**A2 Events** (one JSON object per stdout line; a GUI treats EOF without a `result` as failure)
- `{"event":"progress","verb","stage","message","percent"?}`
- `{"event":"result","verb","ok","code","reason","data":{}}`; `data` by verb: build `build_info`; `flash --plan` `checklist` (ordered, from `mode_steps`), `sha256`, `port`, `token`, `expires_at`, `after_steps`; verify `outcome` (pass\|fail\|skipped) and per-probe `{cmd, ok, matched}`; publish `paths`; ports `ports:[{path, held}]`.

**A3 `fw list --json`**: one `result` whose `data.projects` is a list of `{name, status, reason?, artifacts:[{file, board, descriptor, flashable}], bench:[...], deps_available (bool), build: none|clean|dirty|stale}`.

**A4 Tokens and locks**: `--plan` writes `firmware_dev/.fw/tokens/<token>.json` (mode 600, gitignored): project, resolved port, image path, sha256, expiry (now + 300 s); token is 128-bit random. A new `--plan` for the same port deletes older tokens. Locks: `.fw/locks/<port>` (flash, verify), `.fw/locks/project-<p>` (build, publish); a lock whose PID is dead is reclaimed. `--confirm` reads the record, re-hashes the file at that path, then deletes the record (also on failure); expired records are swept on every `fw` start.

**A5 Tables by status and bench rules**: `stub` needs `[project]`, `[test]`; `source`, `built`, `bench` also need `[deps]`, `[source]`, `[build]`, `[[artifact]]`; `[flash]` if any artifact is `flashable`; `[verify]` if a flashable artifact has a descriptor; `[[bench]]` for `bench`. `status="bench"` needs a `pass` record whose sha256 equals the current build's default artifact, else `fw list` reports `built` with a reason; `built` needs a build record, else `source`.

**A6 Gates**: G1 image inside `firmware_dev/`; G2 port exists; G3 port not held; G4 by-id `-if00` port, else extra acknowledgement; G5 checklist for the manifest gate (SOP or J6); G6 typed phrase `FLASH MODE CONFIRMED` (TTY); G7 `--dry-run` flashes nothing.

**A7 Dirty and stale**: *dirty* = `git status --porcelain -- projects/<p> fw tools` in `firmware_dev` is non-empty (`build/` is gitignored); the commit is firmware_dev HEAD. *Stale* = an artifact sha256 differs from the record, only legacy `build_info.txt` exists, or `git diff --quiet <commit> HEAD -- projects/<p> fw tools` fails. (see Amendment 3)

## Amendments

1. 2026-10-08 (user): the descriptor back-reference lives per board entry as `identify.<board>.source = {fw_project, artifact}` (a descriptor such as `demo` covers several boards with different images).
2. 2026-10-08 (user): `publish` provenance `chirp_cfg` lists every `[test].cfgs` file of the project with its sha256.
3. 2026-10-08 (user): commits that change only `[[bench]]` entries and/or `project.status` in `project.toml` do not make a build dirty or stale (A7). Any other change under the project still does.
4. 2026-10-08 (user, ratified): R4 gains an optional `[flash].manual_images` list naming images that must be flashed by hand; `--plan`/`--dry-run` on such an image return the manual steps in `result.data.checklist` with exit 3 and issue no token.
5. 2026-10-08 (user, ratified): any exit 3 (manual) from a project's flash step carries that step's output in `result.data.checklist`. This applies on every flash path: `--confirm`, TTY, and `--dry-run` for images not listed in `[flash].manual_images`.
