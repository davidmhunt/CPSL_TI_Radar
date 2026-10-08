# Firmware project contract — requirements

**Status:** draft (awaiting Editor pass, cold read, user sign-off)
**Owner:** fwstd loop (Firmware specialist) · **Sponsor:** user · **Serves:** firmware standardisation (fwstd-03..08) and the later GUI build/flash/verify directive

Every `firmware_dev/projects/<p>/` follows one contract: one manifest, one set of
`fw` verbs, one machine interface, one set of flash gates. A person at a
terminal and a future GUI drive the same verbs; the GUI never reads project
files, only `fw list --json`.

**Done when:** each project passes `fw test <p>` with no failures, and a script
with no TTY can `list`, `build`, `verify` and (via the two-phase token) `flash`
every flashable project, and `publish` to a scratch directory.

## Requirements

| ID | Requirement | Verification | Threshold |
|----|-------------|--------------|-----------|
| R1 | `projects/<p>/project.toml` replaces `project.env` (stdlib `tomllib`). `fw` reads `project.env` only during migration, with a stderr deprecation line. | `fw test` schema check per project | 0 invalid; 0 `.env`-only at fwstd-08 |
| R2 | Required keys: `[project]` name, summary, `status` (`stub\|source\|built\|bench`); `[deps]` sdk, sdk_version, toolchain, `download_items`, in-image paths; `[source]` baseline, baseline_commit; `[build]` script, variants, est_minutes. | Validator on missing/unknown key | Exit 1 naming the key |
| R3 | `[[artifact]]` (first = default image): file, board, `descriptor` (id in `CPSL_TI_Radar_cpp/config/firmware/`, or `""`), `flashable`. | `fw test`; parent pytest cross-check both ways | 0 mismatches |
| R4 | `[flash]`: method (`dslite\|uart_uniflash\|manual`), gate (`sop\|j6`), port_glob, mode_steps, after_steps, success_marker. Gate comes from the manifest, not from `*.ccxml` presence. | Test: ccxml added/removed | Same gate |
| R5 | `[verify]` holds only cli_port_glob, baud, descriptor. Probes, timeout and `once_safe` live in the descriptor `identify` block, the single source of truth; it wins on conflict. | `fw test`: no probe keys in manifest; `identify` exists for the board | 0 duplicates |
| R6 | `[test]`: host commands and `bench_doc` (default `docs/bench_check.md`). | `fw test` | Exit 0; doc exists |
| R7 | Verbs `fw list \| new \| deps \| build \| test \| flash \| verify \| publish \| help`, each with `--help`. `fw flash <p> <port> [image] [--dry-run]` unchanged. | Table test; old `--dry-run` diff | Output same in substance |
| R8 | `fw deps <p>` reports whether `download_items` are present; `fw build` runs it first. | Fake downloads dir | Exit 4 naming the item |
| R9 | `fw test <p>` needs no hardware or Docker: schema, descriptor consistency, cfg checks, `[test]` commands, `build --dry-run`. `_template` TODOs are warnings. | Run on every project and `fw new x` | Exit 0 |
| R10 | `--json`: JSON Lines on stdout, text on stderr. Zero or more `{"event":"progress",...}`, then exactly one last `{"event":"result","ok","code","reason",...}`. | Parse every verb's stdout | 100% lines parse; 1 result |
| R11 | Without a TTY `fw` never prompts or reads stdin; a missing confirmation gives exit 5 with a reason. | Each verb, `</dev/null`, 10 s timeout | No hang |
| R12 | Exit codes: 0 ok; 1 failed; 2 usage; 3 manual step / unsupported; 4 precondition refused (deps or image missing; port missing, wrong or held; dirty or stale on publish); 5 confirmation required or token invalid. | One test per code | Only these codes emitted |
| R13 | Every current flash gate stays, cascade included: image inside `firmware_dev/`; by-id `-if00` port (else extra acknowledgement; refused under `--json`); port exists and not held; checklist (SOP or J6 per manifest); TTY typed phrase `FLASH MODE CONFIRMED`; `--dry-run` flashes nothing. | Reviewer diff of old `gated_flash()`; tests for held, non-by-id, no-TTY | Every gate present; refusals exit 4/5 |
| R14 | GUI path: `fw flash <p> <port> [image] --plan --json` runs the non-interactive gates and returns checklist, sha256, resolved port and a single-use token (128-bit, bound to port and sha256, 300 s, stored in gitignored `firmware_dev/.fw/`). `fw flash --confirm <token> --json` re-checks port, hold and sha256, then flashes. | Tests: reuse, age 301 s, other port, changed image, held port | Refused (exit 5 token, 4 port/image); never flashes |
| R15 | The flash tool runs only after the typed phrase or a valid token; no flag bypasses both. | Grep + test of call sites | 0 other paths |
| R16 | `fw verify <p> [--port P]` sends only the descriptor's probes (never a chirp/sensor cfg), refuses a held or non-by-id port (4), and maps `require`/`reject` to pass/fail. `once_safe: false` (cascade): sends nothing, reports `skipped`, exit 0. | Pty fake board: pass, fail, held, once_safe false | 0/1/4/0; 0 bytes written when skipped |
| R17 | `fw build` writes `build/build_info.json`: project, commit (`-dirty` if so), variant, toolchain, time, sha256 of every artifact (cascade too). | Fake-build test | All hashed |
| R18 | `fw publish <p> [--dest D]` copies the image and `<image>.provenance.json` (project, commit, variant, toolchain, sha256, time, chirp cfg) to `<D>/<BOARD>/<descriptor>/`; default D is the parent's `shipped_firmware/`. | Scratch-dest test | Hashes equal |
| R19 | Publish refuses (4) a `-dirty` tree, or an image whose sha256 or `build_info` commit differs from HEAD. | Dirty, stale, edited-image tests | Exit 4; nothing written |
| R20 | Each project has hardware-free host tests and a user-run `docs/bench_check.md`: preconditions, steps, expected output, pass/fail rows, results log. | `fw test` file check | Sections present |
| R21 | Each README has the sections: Purpose, Status, Build, Test, Flash, Verify, Bench check, Layout, Changes vs TI, Known limits. `fw new` copies `_template`. | Heading check | All present |

## Constraints and interfaces

- `fw` stays bash; logic is stdlib Python 3.11+ on the host, no `uv sync` to build or flash.
- Descriptors gain `source: {fw_project, artifact}` (or `null`); `flash_hint` names a real project.
- The cascade takes a cfg once per power-up; `fw` never sends one.
- Implementation never publishes to the real `shipped_firmware/`; tests use a scratch dir.

## Out of scope

The GUI; real publishing of TI-derived binaries (later, after the user rules on redistribution); multi-board flashing; changing firmware behaviour; descriptor changes beyond `source`.

## Open decisions

| # | Decision | Owner | Needed by |
|---|----------|-------|-----------|
| 1 | **(proposed)** `status` levels (R2) and README sections (R21). | user | sign-off |
| 2 | `--confirm` needs no typed phrase: the token, issued after the GUI shows the checklist, is the attestation. Accept? | user | sign-off |

## Pointers

`firmware_dev/fw` (`gated_flash`); `firmware_dev/projects/README.md` §3-4; `iwr1843_sar_lvds` (reference); descriptors' `identify`; `docs/firmware.md`; fwstd-01 Evaluation.

## Amendments
