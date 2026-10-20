# IWR1443 `iwr_raw_rosnode` image (4 lanes)

Only what differs from the [pipeline](README.md). **Not verified on a bench:** no IWR1443 raw capture exists; this page is checked against TI documents and code only.

## Stream

```
 IWR1443, 4 lanes, interleaved (one lane per RX), R = 4:
 per ADC time step t:
   file:  c(RX0) c(RX1) c(RX2) c(RX3)  c'(RX0) c'(RX1) c'(RX2) c'(RX3)  | next t
          \_____ first component ____/ \____ second component ____/
 t runs over sample, then chirp; no header, no lvdsStreamCfg
```

- 4-lane complex, interleaved: per time step, one word per lane for the first component (RX0..RX3), then one per lane for the second. TI shows I first.
- TI says the 4-lane file always carries four lane words with unused lanes zero. Our code assumes one lane per enabled RX. Latent, since all shipped IWR1443 configs enable 4 RX.
- Prebuilt image `xwr14xx_lvds_stream.bin`, a fork of an open-source ROS node whose sources are not in this repo. No UART TLV. Four lanes, `adcCfg 2 1`, `adcbufCfg 0 1 0 1`, no `lvdsStreamCfg`, and `channelCfg 15 x 0` in all shipped configs but one, which has no `adcbufCfg` (R = 4). Only `dataFmt` 0/1 are known.
- The IWR1443 has 4 data lanes (TI lists 600 Mbps max for the DCA1000). The DCA1000 is set for 4-lane capture.
- `i_first` is the board descriptor's value for the IWR1443.

## Unverified

- I/Q order: the shipped configs send `adcbufCfg 0 1 0 1`, whose second field is SampleSwap = 1. Under SDK 3.6 semantics that means Q first, which contradicts `i_first`. The IWR1443 `adcbufCfg` dialect (4 fields) is described only by a repo comment, because the SDK 2.1 guide was not available. Discriminating experiment: an IWR1443 reflector capture with an image-ratio I/Q check, as done for the IWR1843.
