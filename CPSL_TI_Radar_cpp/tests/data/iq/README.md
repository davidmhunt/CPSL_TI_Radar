# I/Q golden frame (core-17)

`iwr1843_R0.9m_frame99.bin` is one raw LVDS frame used by `tests/test_iq_golden.cpp`, which pins the
IWR1843 `lvds.iq_order` (`q_first`) against real data.

| | |
|---|---|
| Source run tag | `core17_iq_raw_R0.9m` (`tools/bench/runs/`, gitignored), captured 2026-10-12 |
| Board / firmware | IWR1843, stock demo (SDK 3.6.2), DCA1000, `save_raw_lvds` |
| Geometry | corner/metal reflector at about 0.9 m (user estimate, not measured) |
| Source file | `LVDS_Raw_0.bin`, 52702832 B, sha256 `f96ae88f906f1ed67909e5eca875636a68c82e36dfec6bed8e88f52353b2921c` (100 full frames + 274032 B partial tail, frame-aligned at byte 0) |
| Extracted | frame index 99, byte offset 51904512 (99 x 524288), length 524288 B |
| Frame sha256 | `079e118b9587b92e8f91d57908c74e6b03212f9bb6bd7502056971d8b20a435e` |

Regenerate: `dd if=LVDS_Raw_0.bin of=iwr1843_R0.9m_frame99.bin bs=524288 skip=99 count=1`.

## Radar parameters the test hard-codes (from `config/user/bench_1843_dca.cfg`, gitignored)

    channelCfg 15 5 0
    profileCfg 0 77 87.04 7 73 0 0 26.981 1 128 2000 0 0 30
    chirpCfg 0 0 0 0 0 0 0 1
    chirpCfg 1 1 0 0 0 0 0 4
    frameCfg 0 1 128 0 100 1 0
    lvdsStreamCfg -1 0 1 0

4 RX, 128 samples, 2 chirps x 128 loops = 256 chirps, 4 B/sample: 4 x 4 x 128 x 256 = 524288 B/frame.
Slope 26.981 MHz/us at 2000 ksps gives 0.0868 m/bin; 0.9 m is bin 10.4 (mirror at 128 - peak).
The test reads no cfg, so none is committed.

## What the test asserts

Chirp-averaged range DFT magnitude on rx0 (positive half, DC excluded): the peak is in bins 9..12
(10.4 +/- 2), and the mirror bin (128 - peak) is at least 15 dB below it. Measured on this frame
(ctest): peak bin 9, 82.7 dB, mirror 31.2 dB below (Python on frames 0 / 50: peak 11 / 9, mirror 28.8 / 26.8 dB below).
The reflector is not at exactly 10.4 (peak 9 or 11 across frames, user-estimated range, strong room
clutter at bins 21-27), so the +/-2 tolerance is the directive's, not loosened. Frame 99 was chosen for the
largest margin over the next peak. A second case flips `iq_order`: the peak leaves the window.
