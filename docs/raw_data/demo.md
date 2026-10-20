# Stock mmWave demo (IWR1843 / IWR6843 / IWR6843ODS, SDK 3.6)

Only what differs from the [pipeline](README.md). Config key: `lvdsStreamCfg`.

## Stream

```
 radar cfg:  adcCfg 2 1   adcbufCfg -1 0 1 1 1   lvdsStreamCfg -1 0 1 0
 per chirp:  [ R x Ns x 4 B ADC payload ]   one LVDS packet per chirp, no header
 per frame:  Nc chirps back to back -> 4 x R x Ns x Nc bytes
```

- Hardware session is ADC only (`dataFmt` 1) or CP_ADC_CQ (4); header optional; one packet per chirp; 2 lanes; SampleSwap 1; non-interleaved; complex 16-bit. The 24 shipped demo configs use `lvdsStreamCfg -1 0 1 0`. [F1]
- `lvdsStreamCfg <subFrameIdx> <enableHeader> <dataFmt> <enableSW>`. [H1]
- Sample order is Q first (SampleSwap 1 is the only value the stock demo supports); measured on the IWR1843 golden frame, inferred for IWR6843/ODS. [E5]
- 2 lanes, file words `Q Q I I` repeating. [L6][L7]
- Frame size with no header: 4 x R x Ns x Nc; the tracked IWR1843 frame is 4 x 4 x 128 x 256 = 524 288 B. [R1]
- With `enableHeader` 1, the stream gains an HSI header ahead of each session (ID `0x0CDA0ADC0CDA0ADC` for the hardware stream); our driver counts header bytes only for the SAR format, so header-on demo captures are not supported. [H3][H4]
- `dataFmt` 4 (CP_ADC_CQ) puts CP and CQ blocks on LVDS; the driver cannot assemble them and rejects it for capture. [H5][H7]
- `enableSW` 1 needs `enableHeader` 1 and adds a software session; unsupported. [H1][H8]

## Known gaps

- V3: one shipped demo config (`demo_tlv_default.cfg`) enables the header with `dataFmt` 1; it would give a wrong frame size over DCA1000. It may be TLV-only; not checked. Open.
- V4: TI says use "multi" logging mode when the header is on; our driver always sends raw. Open, benign. [H2]
- Not documented in TI's public docs: the SDK header field layout and the CP/CQ block layouts. [H4][H6]
