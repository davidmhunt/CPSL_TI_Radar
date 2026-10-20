# `iwr1843_sar_lvds` (custom CBUFF firmware)

Only what differs from the [pipeline](README.md). Not a TI-published format: TI's prebuilt CBUFF library leaves `ADC_USER` out, so this firmware rebuilds it. The byte-level specification is [`lvds_data_format.md`](../../firmware_dev/projects/iwr1843_sar_lvds/docs/lvds_data_format.md) in the firmware repo; it is not copied here. [F3]

## Stream

```
 dataFmt 2, one LVDS packet per chirp (B bytes), no header, enableSW 0:
 [ ADC payload: 4 x R x Ns ][ metadata slot 0: 32 B ][ metadata slot 1: 32 B ]
                              ^ record for chirp k in slot (k mod 2)
 B = H + 4 x R x Ns + 64   (H = 0, 56 or 64 bytes of header/padding)
```

- `lvdsStreamCfg ... dataFmt`: 0 off, 1 ADC, 2 ADC plus two 32-byte per-chirp metadata record slots (CBUFF `ADC_USER`), 4 CP_ADC_CQ. [F3]
- Requires complex output, ChanInterleave 1 (non-interleaved), R x Ns even, and `enableSW` 0. [F3][L5][H8]
- The board descriptor shares the stock IWR1843 LVDS path: 2 lanes, Q first (I/Q order measured on the stock demo only). Lane order is undone on the metadata record before parsing. [F6][L7]
- The 32-byte record sits at offset M + 32 x (k mod 2) of packet k. Fields: magic "SARM", version 1, flags, frameIdx, chirpInFrame, numChirpsPerFrame, globalChirpIdx, runIdx, satSlices, satRefLag, tsTicks (10 ns ticks). The record in a packet usually describes the next chirp (k+1); the saturation result lags 1-2 chirps. [F4]
- CQ2 reports ADC saturation. `dataFmt` 4 packets (13 616 B with both monitors) need a CQ block and carry no metadata record. [H6]
- Bench-measured: the HSI ID read correctly in 30 090 of 30 090 packets; a 600 s soak ran. [L7][F4]
- Frames are cut by counting bytes (B per chirp). [L14][R2]

## Known gaps

- V8: the firmware doc says the firmware pads header + data to 16 B (not TI's "256 B"), with no other padding, and bench-measured B = 13 264 / 13 328. This page follows that. The firmware descriptor `iwr1843_sar_lvds.json` instead states `roundup256(Ns*Nrx*4+52)`. The two repo files disagree; the descriptor's formula is an open discrepancy. TI says only "multiple of 8". [V8][L5]
- Not documented in TI's public docs: any `dataFmt` 2 layout; from our firmware doc and code. [F3]
