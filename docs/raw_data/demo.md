# Stock mmWave demo (IWR1843 / IWR6843 / IWR6843ODS, SDK 3.6)

Only what differs from the [pipeline](README.md). Config key: `lvdsStreamCfg`. Decode recipe with a worked byte example: [README section 9](README.md#9-recipe-decode-a-stock-demo-frame-iwr1843-sampleswap-1-no-header).

## Stream

| Level | Content |
|---|---|
| radar cfg | `adcCfg 2 1`, `adcbufCfg -1 0 1 1 1`, `lvdsStreamCfg -1 0 1 0` |
| per chirp | `[ R x Ns x 4 B ADC payload ]`: one LVDS packet per chirp, no header |
| per frame | Nc chirps back to back: 4 x R x Ns x Nc bytes |

- Hardware session is ADC only (`dataFmt` 1) or CP_ADC_CQ (4); header optional; one packet per chirp; 2 lanes; SampleSwap 1; non-interleaved; complex 16-bit. The shipped demo configs use `lvdsStreamCfg -1 0 1 0`, except `IWR6843/demo/default.cfg` and `IWR6843ODS/demo/lr_CFAR_7dB.cfg` (`-1 0 0 0`) and `demo_tlv_default.cfg` (`-1 1 1 0`).
- Use `enableHeader` 0. With header on, our driver would compute the wrong frame size (it counts header bytes only for SAR), so header-on demo captures are unsupported. One shipped config, `demo_tlv_default.cfg`, sets `enableHeader` 1 with `dataFmt` 1: do not use it for DCA1000 raw capture (whether it is TLV-only was not checked).
- Not verified for IWR6843/ODS: the I/Q order is inferred from the IWR1843 measurement ([README Unverified](README.md#unverified)).
