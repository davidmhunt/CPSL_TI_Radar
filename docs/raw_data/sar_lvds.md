# `iwr1843_sar_lvds` (custom CBUFF firmware)

Only what differs from the [pipeline](README.md). Not a TI-published format: TI's prebuilt CBUFF library leaves `ADC_USER` out, so this firmware rebuilds it. The byte-level specification is [`lvds_data_format.md`](../../firmware_dev/projects/iwr1843_sar_lvds/docs/lvds_data_format.md) in the firmware repo; it is not copied here. [F3]

## Stream

```
 dataFmt 2, one LVDS packet per chirp (B bytes), no header, enableSW 0:
 [ ADC payload: 4 x R x Ns ][ metadata slot 0: 32 B ][ metadata slot 1: 32 B ]
                              ^ record for chirp k in slot (k mod 2)
 B = H + 4 x R x Ns + 64   (H = 0, 56 or 64 bytes of header/padding)
```

- `dataFmt` 2: ADC plus two 32-byte per-chirp metadata record slots (CBUFF `ADC_USER`). [F3]
- Requires complex output, ChanInterleave 1 (non-interleaved), R x Ns even, and `enableSW` 0. [F3][L5][H8]
- The board descriptor shares the stock IWR1843 LVDS path: 2 lanes, Q first (I/Q order measured on the stock demo only). [F6][L7]
- **Header size H.** Read the cfg used for the run (the `lvdsStreamCfg <sub> <enableHeader> <dataFmt> <enableSW>` line): enableHeader 0 gives H = 0; 1 gives H = 64 if R x Ns is a multiple of 4, else 56. R = bits set in `channelCfg` rxMask, Ns = `profileCfg` numAdcSamples. Cross-check: B must divide the file length. [F8]
- **Lane undo (the record is read after this).** The DCA1000 sends each 8-byte group as 16-bit units `u0 u2 u1 u3`; swap the middle two units, i.e. bytes b0..b7 become b0 b1 b4 b5 b2 b3 b6 b7, in every 8-byte group. The record starts at M, a multiple of 8, so the groups of the stream and of the record coincide; undo the whole stream or just the record's four groups. [F9][L7]
- The 32-byte record sits at offset M + 32 x (k mod 2) of packet k, M = H + 4 x R x Ns. Fields, little-endian, offsets **after the lane undo**: [F7][F4]

  | Off | Type | Field |
  |---|---|---|
  | 0 | u32 | `magic` = 0x4D524153, bytes "SARM" |
  | 4 | u16 | `version` = 1 |
  | 6 | u16 | `flags`: bit 0 SAT_VALID, 1 SAT_MON, 2 LATE, 3 SKIP, 4 RESYNC |
  | 8 | u32 | `frameIdx` |
  | 12 | u16 | `chirpInFrame` |
  | 14 | u16 | `numChirpsPerFrame` |
  | 16 | u32 | `globalChirpIdx` (= k for a valid record) |
  | 20 | u16 | `runIdx` |
  | 22 | u8 | `satSlices` |
  | 23 | u8 | `satRefLag` (the saturation result is for chirp `globalChirpIdx - satRefLag`) |
  | 24 | u64 | `tsTicks`, 10 ns ticks |

  The record in a packet usually describes the next chirp (k+1); the saturation result lags 1-2 chirps. A record is packet k's only if magic, version = 1 and `globalChirpIdx` = k hold. [F4]
- CQ2 reports ADC saturation. `dataFmt` 4 packets (13 616 B with both monitors) need a CQ block and carry no metadata record. [H6]
- Bench-measured: the HSI ID read correctly in 30 090 of 30 090 packets; a 600 s soak ran. [L7][F4]

## Known gaps

- V8: the firmware doc says the firmware pads header + data to 16 B (not TI's "256 B"), with no other padding, and bench-measured B = 13 264 / 13 328. This page follows that. The firmware descriptor `iwr1843_sar_lvds.json` instead states `roundup256(Ns*Nrx*4+52)`. The two repo files disagree; the descriptor's formula is an open discrepancy. TI says only "multiple of 8". [V8][L5]
