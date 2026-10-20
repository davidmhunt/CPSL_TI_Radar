# `iwr1843_sar_lvds` (custom CBUFF firmware)

Only what differs from the [pipeline](README.md). Not a TI-published format: TI's prebuilt CBUFF library leaves `ADC_USER` out, so this firmware rebuilds it. The byte-level specification is [`lvds_data_format.md`](../../firmware_dev/projects/iwr1843_sar_lvds/docs/lvds_data_format.md) in the firmware repo; it is not copied here.

## Stream

`dataFmt` 2, one LVDS packet per chirp (B bytes), no header, `enableSW` 0:

| Order | Part | Size | Note |
|---|---|---|---|
| 1 | ADC payload | 4 x R x Ns | |
| 2 | metadata slot 0 | 32 B | record for chirp k sits in slot (k mod 2) |
| 3 | metadata slot 1 | 32 B | record for chirp k sits in slot (k mod 2) |

B = H + 4 x R x Ns + 64 (H = 0, 56 or 64 bytes of header/padding).

- `dataFmt` 2: ADC plus two 32-byte per-chirp metadata record slots (CBUFF `ADC_USER`).
- Requires complex output, ChanInterleave 1 (non-interleaved), R x Ns even, and `enableSW` 0.
- The board descriptor shares the stock IWR1843 LVDS path: 2 lanes, Q first (I/Q order measured on the stock demo only).
- **Header size H.** Read the cfg used for the run (the `lvdsStreamCfg <sub> <enableHeader> <dataFmt> <enableSW>` line): enableHeader 0 gives H = 0; 1 gives H = 64 if R x Ns is a multiple of 4, else 56. R = bits set in `channelCfg` rxMask, Ns = `profileCfg` numAdcSamples. Then B = H + 4 x R x Ns + 64 is the packet size (the one headerless capture checked had B = 15 984 with R = 1, Ns = 3980). The file need not be a multiple of B: it can end in a partial packet, so decode floor(len / B) packets and ignore the rest.
- **Lane undo (the record is read after this).** The DCA1000 sends each 8-byte group as 16-bit units `u0 u2 u1 u3`; swap the middle two units, i.e. bytes b0..b7 become b0 b1 b4 b5 b2 b3 b6 b7, in every 8-byte group. The record starts at M, a multiple of 8, so the groups of the stream and of the record coincide; undo the whole stream or just the record's four groups.
- The 32-byte record sits at offset M + 32 x (k mod 2) of packet k, M = H + 4 x R x Ns. Fields, little-endian, offsets **after the lane undo**:

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

  In packet k, slot k mod 2 holds record k: use it only if magic, version = 1 and `globalChirpIdx` = k hold. The other slot usually holds the next chirp's record (k+1) and is ignored; the saturation result lags 1-2 chirps.
- CQ2 reports ADC saturation. `dataFmt` 4 packets (for R = 1, Ns = 3300: 13 616 B with both monitors; the firmware's `lvds_data_format.md` has the general rule) need a CQ block and carry no metadata record.
- Bench-measured: the HSI ID read correctly in 30 090 of 30 090 packets; a 600 s soak ran.

## Unverified

- Packet padding: the firmware doc says the firmware pads header + data to 16 B (not TI's "256 B"), with no other padding, and bench-measured B = 13 264 / 13 328; the B formula above follows it. The firmware descriptor `iwr1843_sar_lvds.json` instead states `roundup256(Ns*Nrx*4+52)`. The two repo files disagree and the descriptor's formula is an open discrepancy; TI says only "multiple of 8".

## `chirp_meta.csv` (converter output)

One row per chirp, written by the driver's converter, not part of the wire format. The columns `version` ... `tsTicks` repeat the record fields above (empty if the record is invalid). The rest are derived: `chirp` = k, `frame` = k // Nc, `chirpInFrame` = k mod Nc (Nc = the cfg's chirps per frame, as the driver computes it; the record's own field is the column `rec_chirpInFrame`, and `numChirpsPerFrame` is the record's), `record_valid` (record k passed the check above), `adc_complete` (every byte of the chirp's ADC block arrived), `t_s` (seconds since the run's first valid record, (tsTicks - first) x 10 ns, interpolated when the record is invalid), `t_interpolated` (1 if `t_s` was interpolated), `late` (record flag bit 2), `sat_slices_this_chirp` (saturation result aligned to this chirp via `satRefLag`, empty if unknown). Only whole frames are written, so a trailing partial frame has no rows.
