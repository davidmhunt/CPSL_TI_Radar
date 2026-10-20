# IWR1443 `iwr_raw_rosnode` image (4 lanes)

Only what differs from the [pipeline](README.md). **Not verified on a bench:** no IWR1443 raw capture exists; this page is checked against TI documents and code only. [F2]

## Stream

```
 IWR1443, 4 lanes, interleaved (one lane per RX), R = 4:
 time step t:  c(RX0) c(RX1) c(RX2) c(RX3) | c'(RX0) c'(RX1) c'(RX2) c'(RX3)
               first component              second component                  [L11]
 t runs over sample, then chirp; no header, no lvdsStreamCfg
```

- Prebuilt image `xwr14xx_lvds_stream.bin`, a fork of an open-source ROS node whose sources are not in this repo. No UART TLV. Four lanes, `adcCfg 2 1`, `adcbufCfg 0 1 0 1`, no `lvdsStreamCfg`, and `channelCfg 15 x 0` in all 12 shipped configs (R = 4). Only `dataFmt` 0/1 are known. [F2]
- The IWR1443 has 4 data lanes (TI lists 600 Mbps max for the DCA1000). The DCA1000 is set for 4-lane capture. [L2]
- The 4-lane file holds, per ADC time step, one word per lane for the first component, then one per lane for the second. TI shows I first for Studio captures. [L11]
- This is the only device where interleaved ADC-buffer mode exists. [L10]
- `i_first` is the board descriptor's value for the IWR1443. [E6]
- Samples are int16 little-endian, 4 B per complex sample. [E4]

## Known gaps

- V2: the shipped configs send `adcbufCfg 0 1 0 1`, whose second field is SampleSwap = 1. Under SDK 3.6 semantics that means Q first, which contradicts `i_first`. Neither is verified; the IWR1443 `adcbufCfg` dialect (4 fields) is described only by a repo comment, because the SDK 2.1 guide was not available. Open. Discriminating experiment: an IWR1443 reflector capture with an image-ratio I/Q check, as done for the IWR1843. [E5][E6]
- V1: TI says the 4-lane file always has four lane words with unused lanes zero; our code assumes one per enabled RX. Latent, because every shipped config has R = 4. Open. [L12]
