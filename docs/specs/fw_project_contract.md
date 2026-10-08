# Firmware project contract — requirements

**Status:** draft (decisions settled 2026-10-08; awaiting sign-off)
**Owner:** fwstd loop · **Sponsor:** user · **Serves:** firmware standardisation (fwstd-03..08) and the later GUI build/flash/verify directive

Every `firmware_dev/projects/<p>/` follows one contract: one manifest, one set of
`fw` verbs, one machine interface, one set of flash gates. A person and a
future GUI drive the same verbs; the GUI reads only `fw list --json`.

**Done when:** each project passes `fw test <p>`, and a script with no TTY can
`list`, `build`, `verify`, `flash` (two-phase token) every flashable project and
`publish` to a scratch directory (never the real `shipped_firmware/`).

## Requirements

| ID | Requirement | Verification | Threshold |
|----|-------------|--------------|-----------|
| R1 | `projects/<p>/project.toml` replaces `project.env` (stdlib `tomllib`). `fw` reads `project.env` only during migration, with a stderr deprecation line. | `fw test` schema check | 0 invalid; 0 `.env`-only at fwstd-08 |
| R2 | Keys: `[project]` name, summary, `status` (`stub\|source\|built\|bench`); `[deps]` sdk, sdk_version, toolchain, `download_items`; `[source]` baseline, baseline_commit; `[build]` script, variants, est_minutes. | Validator, missing/unknown key | Exit 1 naming the key |
| R3 | `[[artifact]]` (first = default image): file, board, `descriptor` (id in `CPSL_TI_Radar_cpp/config/firmware/`, or `""`), `flashable`. | `fw test`; parent pytest, both ways | 0 mismatches |
| R4 | `[flash]`: method (`dslite\|uart_uniflash\|manual`), gate (`sop\|j6`), port_glob, mode_steps, after_steps, success_marker. Gate comes from the manifest, not `*.ccxml` presence; `--dry-run` works for every method. | Test: ccxml added/removed; `--dry-run` per project | Same gate; exit 0 |
| R5 | `[verify]` holds only cli_port_glob, baud, descriptor. Probes, timeout, `once_safe` live only in the descriptor `identify` block, which wins on conflict. | `fw test`: no probe keys; `identify` exists | 0 duplicates |
| R6 | `[test]`: host commands, `cfgs` (tracked cfg globs, never `build/`; parent tests use them, not `rglob`), `bench_doc` (default `docs/bench_check.md`). | `fw test`; stray `build/x.cfg` | Exit 0; ignored |
| R7 | Verbs `fw list \| new \| deps \| build \| test \| flash \| verify \| publish \| help`, each with `--help`; `build` first runs `deps` (exit 4 naming a missing download item). `fw flash <p> <port> [image] [--dry-run]` unchanged. | Table test; `--dry-run` diff | Output same in substance |
| R9 | `fw test <p>` needs no hardware or Docker: schema, descriptor consistency, cfgs, `[test]` commands, `build --dry-run`. Template TODOs warn. | Every project and `fw new x` | Exit 0 |
| R10 | `--json`: JSON Lines on stdout, text on stderr. `progress` events, then one last `result` event (ok, code, reason). | Parse every verb's stdout | 100% lines parse; 1 result |
| R11 | Without a TTY `fw` never prompts; a missing confirmation gives exit 5 with a reason. | Each verb, `</dev/null`, 10 s timeout | No hang |
| R12 | Exit codes: 0 ok; 1 failed; 2 usage; 3 manual step / unsupported; 4 precondition refused; 5 confirmation required or token invalid. | Test per code | Only these codes emitted |
| R13 | Every current flash gate stays, cascade included: image inside `firmware_dev/`; by-id `-if00` port (else extra acknowledgement; refused under `--json`); port exists and not held; checklist (SOP or J6 per manifest); TTY typed phrase `FLASH MODE CONFIRMED`; `--dry-run` flashes nothing. | Reviewer diff of old `gated_flash()`; held/non-by-id/no-TTY tests | Every gate present; refusals exit 4/5 |
| R14 | GUI path: `fw flash <p> <port> [image] --plan --json` runs the non-interactive gates and returns checklist, sha256, resolved port and a single-use token (128-bit, bound to port and sha256, 300 s, stored in gitignored `firmware_dev/.fw/`). `fw flash --confirm <token> --json` re-checks port, hold and sha256, then flashes. The flash tool runs only after the typed phrase or a valid token; no flag bypasses both. | Tests: reuse, age 301 s, other port, changed image, held port | Exit 5 (token) or 4 (port/image); no flash |
| R16 | `fw verify <p> [--port P]` sends only the descriptor's probes (never a chirp/sensor cfg), refuses a held or non-by-id port (4), and maps `require`/`reject` to pass/fail. `once_safe: false` (cascade): sends nothing, reports `skipped`, exit 0. | Pty fake board cases | 0/1/4/0; 0 bytes written when skipped |
| R17 | `fw build` writes `build/build_info.json`: project, firmware_dev commit (never `unknown`; `-dirty` if `git status --porcelain` non-empty), variant, toolchain, time, sha256 of every artifact. A build is **clean** if its commit has no `-dirty`; **stale** if its commit differs from HEAD, an artifact sha256 differs from the record, or only the old `build_info.txt` exists. | Fake builds: clean, dirty, edited, legacy | All hashed; states classified |
| R18 | `fw publish <p> [--dest D]` copies the image and `<image>.provenance.json` (project, commit, variant, toolchain, sha256, time, chirp cfg) to `<D>/<BOARD>/<descriptor>/`; default D is the parent's `shipped_firmware/`. | Scratch dest | Hashes equal |
| R19 | Publish refuses (4) a `-dirty` tree, or an image whose sha256 or `build_info` commit differs from HEAD. | Dirty, stale (as R17), edited-image tests | Exit 4; nothing written |
| R20 | Each project has hardware-free host tests and a user-run `docs/bench_check.md`: preconditions, steps, expected output, pass/fail rows. | `fw test` file check | Sections present |
| R21 | Each README has the sections: Purpose, Status, Build, Test, Flash, Verify, Bench check, Layout, Changes vs TI, Known limits. Status is one line quoting `fw list`. | Heading check; no dated bench claim outside the manifest | All present |
| R22 | Bench record lives only in the manifest: `[[bench]]` with board, date, image sha256, result (`pass\|partial\|fail`), doc link. `status = "bench"` requires a `pass` for the default image's board; `built` otherwise. `fw list --json` exposes both. | `fw test`: status vs records | 0 inconsistent |

## Constraints and interfaces

- `fw` stays bash; logic is stdlib Python 3.11+.
- Descriptors gain `source: {fw_project, artifact}` (or `null` for prebuilts `dca1000_raw`, IWR1443 `demo`); `flash_hint` names a real project.
- `tools/cascade_serial_check.py` moves into `awr2243_cascade_ddm`; `verify` replaces it.
- The cascade takes a cfg once per power-up; `fw` never sends one.

## Out of scope

The GUI; real publishing of TI-derived binaries (pending a redistribution ruling); multi-board flashing; firmware behaviour changes.

## Decisions

Decided 2026-10-08 (user): `--confirm` needs no typed phrase (TTY path keeps it); `status` levels (R2) and README sections (R21) as written; descriptor `source` as in Constraints. No open decisions.

## Pointers

`firmware_dev/fw` (`gated_flash`); `projects/README.md` §3-4; `iwr1843_sar_lvds` (reference); fwstd-01 Evaluation.

## Amendments
