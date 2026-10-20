# Stock mmWave demo (IWR1843 / IWR6843 / IWR6843ODS, SDK 3.6)

Only what differs from the [pipeline](README.md). Config key: `lvdsStreamCfg`.

## Stream

```
 radar cfg:  adcCfg 2 1   adcbufCfg -1 0 1 1 1   lvdsStreamCfg -1 0 1 0
 per chirp:  [ R x Ns x 4 B ADC payload ]   one LVDS packet per chirp, no header
 per frame:  Nc chirps back to back -> 4 x R x Ns x Nc bytes
```

- Hardware session is ADC only (`dataFmt` 1) or CP_ADC_CQ (4); header optional; one packet per chirp; 2 lanes; SampleSwap 1; non-interleaved; complex 16-bit. The 24 shipped demo configs use `lvdsStreamCfg -1 0 1 0`. [F1]
- With `enableHeader` 1, the stream gains an HSI header ahead of each session (ID `0x0CDA0ADC0CDA0ADC` for the hardware stream); our driver counts header bytes only for the SAR format, so header-on demo captures are not supported. [H3][H4]

## Known gaps

- V3: one shipped demo config (`demo_tlv_default.cfg`) enables the header with `dataFmt` 1; it would give a wrong frame size over DCA1000. It may be TLV-only; not checked. Open.
- V4: TI says use "multi" logging mode when the header is on; our driver always sends raw. Open, benign. [H2]
- Not documented in TI's public docs: the SDK header field layout and the CP/CQ block layouts. [H4][H6]
