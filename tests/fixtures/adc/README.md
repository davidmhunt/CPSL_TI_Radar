# ADC fixtures (gui-07)

- `bench_1843_dca.cfg` / `.json`: copy of `CPSL_TI_Radar_cpp/config/user/bench_1843_dca` (serial stream off in the json). Used by the
  synthetic-cube tests and the fake driver. Shape 4 rx x 128 samples x 256 chirps (2 TX slots x 128 loops), 100 ms frames.
- `iwr1843_bench_dca_2frames.bin`: 2 whole frames (frames 264 and 265 of 529) cut from a real IWR1843 + DCA1000 capture,
  `runs/gui/20261007T214919Z_bench_1843_dca/adc_data.bin` (277,348,352 B = 529 x 524,288 B), recorded with the Rebuild 1 driver
  and `bench_1843_dca.cfg` (unchanged copy above). Scene unknown (no tape-measured reflector), so tests assert shapes and
  health, not a target position.
  - File order (docs/ARCHITECTURE.md "Output files"): chirp, rx, sample, int16 I then Q, little endian; 524,288 B per frame.
  - `iq_order`: the file is written after the driver's `ADCCubeConverter` applied the board's `lvds.iq_order` (IWR1843: `q_first`),
    so I and Q here are already in the tap's `"IQ"` meaning; no swap.
