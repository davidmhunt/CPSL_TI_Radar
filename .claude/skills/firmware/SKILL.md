---
name: firmware
description: TI mmWave firmware in this repo: the firmware_dev submodule and its fw tool, shipped images and their provenance, toolchain pins, flashing and on-board bring-up. Use before touching firmware_dev/, shipped_firmware/, or flashing a board.
---

# Firmware

Facts live in `docs/firmware.md` (toolchain versions, which image each board needs, ports, quirks)
and `docs/tutorials/03_flash_a_radar.md`. Read them before any firmware step. If a fact you need
is missing, ask the user; once answered, add it to `docs/firmware.md` in the same commit as the change.

- **Build in the container.** Firmware builds run in the `firmware_dev` Docker image
  (`./fw build <project>` from `firmware_dev/`), never against a host TI install. Builds are long:
  hand them to the `runner` agent.
- **Sources in git, dependencies downloaded.** TI SDKs, toolchains and the Radar Toolbox come from
  `downloads/download.sh` and are never committed. Flag any TI binary or library you find in git.
- **Shipped images carry provenance.** `./fw publish <project>` copies a clean build and its
  provenance (firmware_dev commit, build config, chirp config) into `shipped_firmware/` in the same
  commit as the image. Contract: `docs/specs/fw_project_contract.md`.
- **Toolchain versions follow the projectspecs.** Cascade compiler/SDK versions are pinned by
  `firmware/cascade/src/demo/src/awr2243/*.projectspec`; change them together with the Dockerfile and
  `download.sh`, never one alone.
- **Flashing is a bench step.** `./fw flash <project> <port>` asks the user (hardware hook). SOP
  switches, the cascade J6 jumper and power cycles are the user's: write the exact steps and stop.
  Never assume a board's boot mode.
- **Submodule discipline.** `firmware_dev/` is its own repo on `release/v2.0`. Commit inside it
  first, on its current branch; the parent repo's pointer bump is a separate commit. Never switch
  branches or push inside it unless the directive says so.
- **Numbers carry their source.** Register, timing, memory-map or chirp-parameter claims cite the TI
  document page, projectspec or source line.
