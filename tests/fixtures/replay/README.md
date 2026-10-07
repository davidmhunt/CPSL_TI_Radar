# Replay fixtures (bench captures, gui-09 Step 3)

Whole frames cut with `radar_gui.tlv.split_packets` from raw `dump` captures made through the GUI Live serial
source on 2026-10-07 (originals in gitignored `runs/gui/dumps/`). Partial leading/trailing bytes dropped.
Under `tests/fixtures/`, so they are on the GUI replay allowlist. Asserted by `tests/test_radar_gui_replay_bench.py`.

| File | Source capture | Dialect | Frames | Frame numbers | Points/frame | Bytes |
|------|----------------|---------|--------|---------------|--------------|-------|
| `iwr1843_sdk3_20frames.bin` | `IWR1843_2026-10-07T20-14-44.bin` | sdk3 | 20 | 2..21 | 7 each | 5760 |
| `awr2243_cascade_20frames.bin` | `AWR2243_CASCADE_2026-10-07T20-23-54.bin` | mcuplus_cascade | 20 | 2414..2433 | 49..68 | 25952 |

- IWR1843: mmWave SDK 3.6.2 out-of-box demo, shipped `IWR1843_demo.cfg`, 10 Hz.
- AWR2243 cascade: cascade_ddm demo (firmware not identified by the GUI), skip-configure capture with
  `CPSL_TI_Radar_cpp/config/user/bench_cascade_revA.cfg` (256 chirps/frame, 128 samples, 100 ms frame). No TLV 12
  (compact points) in these frames.
