# Raw ADC data: from chirp to array

How one radar frame becomes an array in our code, for a reader who has never used an IWR1843 or a DCA1000. Per-firmware differences are on short pages: [demo](demo.md), [dca1000_raw](dca1000_raw.md), [sar_lvds](sar_lvds.md), [cascade_ddm](cascade_ddm.md).

TI sources: IWR1843 data sheet (SWRS228B), mmWave SDK 3.6 user guide, xWR TRM (SWRU522E), DCA1000 user guide (SPRUIJ4A), app note SWRA581B. The PDFs in [`docs/references/`](../references/) are Git LFS pointers: run `git lfs pull` or use the ti.com links in its README. Where TI's public docs are silent, the text says "not documented in TI's public docs" and cites our code or a measurement. Bracketed tags like `[L3]` are claim IDs for review and are removed before release.

## 1. The pipeline in one picture

```
 chirp  -> ADC (12-bit, I+Q per RX) -> ADC buffer -> CBUFF/LVDS (2 or 4 lanes)
 (RF)      in the radar chip           (per chirp)     |  16-bit words, optional header
                                                       v
 array <- host reassembly <- UDP packets <------  DCA1000 capture card (FPGA)
 [rx][sample][chirp]   by byte count    10 B header + <=1462 B payload, over Ethernet
```

Six stages, one section each. Stages 1-3 run inside the chip, stage 4 in the DCA1000, stages 5-6 on the host. The LVDS interface on the IWR1843/6843 is a debug interface, not a production one (TI data sheet note). [L3]

## 2. Frame and chirp timing

```
 time ->
 |<------------------------ frame period ------------------------>|
 | chirp 0 | chirp 1 | ... | chirp Nc-1 |        blank (Tb)         | next frame
 \_ loop 0 _/\_ loop 1 _/ ...            (Nc = slots-per-loop x loops)
   TX0  TX1    TX0  TX1                  one chirp = idle + ramp (Tc)
        |<-- Ns ADC samples during the ramp -->|
```

- A frame is (chirpEnd - chirpStart + 1) chirp slots times `numLoops` (`frameCfg`); chirps leave the radar in time order. [A1]
- Samples per chirp is `numAdcSamples` (`profileCfg`). [A3]
- `chirpCfg` sets which TX fires on each chirp index. Our cube's chirp axis is loop-major, TX-slot-minor: chirp `c` is loop `c // cpl`, slot `c % cpl`. TI gives the per-chirp TX enable, not this array mapping; the mapping is defined in our code. [A2]
- Chirp cycle is idle time plus ramp-end time, and the frame blank is the rest of the period. The sum is not stated in TI's SDK guide; it is from our code. [A4]
- With LVDS streaming, `adcbufCfg` `chirpThreshold` must be 1, so each chirp is one ADC-buffer ping or pong and one LVDS packet. Our code does not enforce this. [A5]
- The chirp-available event triggers each CBUFF transfer after the samples are complete; frame start only arms the sequence. Packets run back to back with no per-frame marker. [A6][L14]

## 3. Sample encoding on the chip

```
 one complex sample = 2 x int16 (little-endian, two's complement) = 4 bytes
 SampleSwap = 1 (stock demo):  [ Q (low address) | I ]     Q first
 SampleSwap = 0:               [ I (low address) | Q ]     I first
 each int16:  s s s s b11 ... b0   <- 12-bit ADC value in a 16-bit container
              ^ sign-extended, LSB-aligned: HYPOTHESIS [E8][V10]
```

- The receive ADC is 12-bit and complex: I and Q per RX channel. [E1]
- Over LVDS every value rides in a 16-bit container. The SDK demo supports only 16-bit and only complex output (`adcCfg 2 1`). [E2]
- The DCA1000 data-format mode must equal `numADCBits` + 1; 3 means 16-bit. [E3]
- One complex sample is two int16, two's complement, little-endian: 4 bytes. [E4]
- Within a sample, the lower-address int16 is I when `adcbufCfg` SampleSwap is 0 and Q when it is 1. The stock demo supports only 1, so IWR1843/6843 demo data is Q first. Measured on the IWR1843; the IWR6843/ODS order is inferred, not bench-verified. [E5]
- Studio's "IQ Swap: I first" option is described by TI for the 4-lane xWR14xx file only. [E6]
- Real-only ADC output exists in TI docs but our driver rejects it. [E7]
- HYPOTHESIS: the 12 bits are sign-extended into the 16-bit word and LSB-aligned (not shifted up by 4). Evidence: a tracked IWR1843 frame has 262 144 words, min -794, max 674, and all 16 values of (word mod 16) occur. TI does not state the alignment. Discriminating experiment: a clipped capture should top out near +-2047, not +-32767. [E8][V10]

## 4. Over the LVDS lanes

```
 IWR1843/6843, 2 lanes, SampleSwap=1, memory units u0 u1 u2 u3 = Q0 I0 Q1 I1
   lane A:  Q0  Q1  | ...      file (A0 A1 B0 B1) = Q0 Q1 I0 I1
   lane B:  I0  I1  | ...      i.e. two Q, then two I, repeating     [L6][L7]

 IWR1443, 4 lanes (one per RX), interleaved, per ADC time step t:
   file:  c(RX0) c(RX1) c(RX2) c(RX3)  c'(RX0) c'(RX1) c'(RX2) c'(RX3)  | next t
          \_____ first component ____/ \____ second component ____/       [L11]
```

- IWR1843/6843 have 2 LVDS data lanes plus a bit clock and a frame clock (DDR). The IWR1443 has 4 data lanes. [L1][L2]
- Data reach the pins through CBUFF, which reads the ADC buffer by EDMA. Minimum packet is 64 B. [L4] A session's size must be a multiple of 8 B; for 4 B samples this means R x Ns is even (enforced by our driver only for the SAR format). [L5]
- 2-lane complex, non-interleaved: lane 1 carries the real parts and lane 2 the imaginary parts of two consecutive samples, so TI's file is `I I Q Q` repeating, one RX after another. With SampleSwap 1 ours is the mirror, `Q Q I I`. [L6]
- Not documented in TI's public docs; from our code and a golden-frame measurement: the device memory unit order `u0 u1 u2 u3` reaches the file as `u0 u2 u1 u3`. [L7]
- Order in memory: chirp, then RX (lowest first), then sample. [L9]
- The 2-lane devices use the ADC buffer in non-interleaved mode only; interleaved exists only on the xWR14xx. [L10]
- With 2 lanes, exactly 3 RX cannot be captured (TI: only 1, 2 or 4); our driver does not check this. [L13]
- 4-lane complex, interleaved (IWR1443): per time step, one word per lane for the first component (RX0..RX3), then one per lane for the second. TI shows I first. [L11]
- TI says the 4-lane file always carries four lane words with unused lanes zero. Our code assumes one lane per enabled RX. Latent, since all shipped IWR1443 configs enable 4 RX. [L12][V1]

## 5. Headers: what they carry

```
 no header (dataFmt 1, enableHeader 0):  [ ADC payload ........................ ]
 HSI header on:   [ data-card hdr 16 B ][ SDK hdr ][ pad ][ ADC payload ][ pad ]
                    8 B ID + 8 B length   CBUFF session description            [H3][H4]
 SAR (dataFmt 2): [ ADC payload (4 x R x Ns) ][ 2 x 32 B chirp metadata ]      -> sar_lvds.md: H, record fields, lane undo [F7][F8][F9]
```

- `lvdsStreamCfg <subFrameIdx> <enableHeader> <dataFmt> <enableSW>`: `enableHeader` 1 adds an HSI header to all active streams; `dataFmt` 0 off, 1 ADC, 4 CP_ADC_CQ; `enableSW` 1 adds a software session and needs `enableHeader` 1. [H1]
- Raw mode (no header) captures the payload only, "no header or extra bytes/padding", and exists only for the hardware session. [H2]
- Header IDs: first stream `0x0CDA0ADC0CDA0ADC` (SDK notation, a little-endian u64), second `0x09CC0CC909CC0CC9`. The DCA1000 guide prints the same bytes in stream order of 16-bit units. [H3][V6, resolved by inference]
- The header is a data-card header (64-bit ID, 64-bit length with 24 valid bits) followed by an SDK header describing the CBUFF session. The SDK header's field layout is not documented in TI's public docs; the 16 B split is inferred from the DCA1000 guide. [H4]
- Data types TI defines: ADC, CP (chirp parameters), CQ (chirp quality), and combinations. CQ carries three monitor results; the byte layout of CP and CQ blocks is not documented in TI's public docs. Our driver cannot read CP or CQ and rejects `dataFmt` 4 for capture. [H5][H6][H7]
- A software session adds a per-frame packet the driver cannot place, so `enableSW` must be 0 for the SAR format. [H8]

## 6. DCA1000 to UDP

```
 UDP datagram, raw mode (1472 B max on the wire):
 byte  0         4                  10                                  1472
       +---------+------------------+------------------------------------+
       | seq u32 | byte count u48   | raw payload (48..1462 B)           |
       | LE      | LE               | LVDS bytes exactly as received     |
       +---------+------------------+------------------------------------+
 [D4][D5]   data-separated mode adds 8 B ID + 8 B length, payload <= 1446 B
```

- The DCA1000 takes LVDS in and sends UDP out. Raw mode captures all LVDS data as is; data-separated mode splits by header. Mode comes from SW2.4 or software. Our driver always asks for raw. [D1][H2]
- Defaults: FPGA 192.168.33.180, host 192.168.33.30, command port 4096, ADC data port 4098. [D2]
- Commands are UDP packets framed `0xA55A` ... `0xEEAA`. [D3]
- A raw packet is a 4-byte sequence number, a 6-byte byte count and 48-1462 bytes of payload. TI gives no endianness and no definition of "byte count"; little-endian and "ADC bytes sent before this packet" are from our code and bench measurement. [D4][D9]
- Our boards configure 1472 B packets, so payload is 1462 = 1472 - 10 (max UDP payload 1500 - 20 - 8 = 1472). Whether TI's size field includes the header is inferred. [D5]
- The inter-packet delay trades throughput against drops (TI default 25 us, about 325 Mbps). Our boards ship 100 us, outside TI's table. [D6]
- Loss and disorder are visible only through sequence numbers and byte counts; TI specifies no recovery. Sequence numbers start at 1 after RECORD_START. [D8][D9]
- The capture card must be armed before the radar starts, and needs at least 12 ms of bit clock before data. [D10]
- The Studio/CLI file has two forms: payload only, or sequence number + length + byte count + payload. Our `LVDS_Raw_0.bin` is payload only (packet header stripped). [D7]

## 7. Host reassembly and array axes

```
 UDP payloads          stream (byte count = offset)         frames
 [p1][p2][p3]...  -->  |<---- frame 0 ---->|<-- frame 1 -->| ...    B bytes each
 memcpy at offset;     lost bytes stay zero (missing_bytes)          [R2][R3]
 frame f = offset / B
                  |
                  v  ADCCubeConverter: undo lane order, apply I/Q order
 C++ cube  [rx][sample][chirp]  complex<int16>   (chirp innermost)    [R5]
 adc_data.bin       [chirp][rx][sample][re,im] int16
 live tap / GUI     [rx][sample][chirp][I,Q] int16   (radar_gui reshape)
 ROS ADCDataCube    dims rx_channel/sample/chirp, int16[] real_data, imag_data
 HDF5 radar_adc/data int16 (N, 2, rx, sample, chirp)   index 0 = I, 1 = Q  [R6]
```

- A plain demo frame (dataFmt 1, no header) is 4 x R x Ns x Nc bytes. The tracked golden frame is 4 x 4 x 128 x 256 = 524 288 B. [R1]
- No frame marker exists in the stream, so frames are cut by counting bytes from the start of the capture. [L14]
- Each payload is copied to stream offset = its byte count, so a lost, late or duplicate packet never shifts later bytes; a payload straddling a frame boundary is split. [R2]
- A frame is emitted when complete, or when the stream is 8 packets past its end; missing bytes are zero and the frame is counted incomplete. At most two frames are open. [R3]
- A DCA1000 restart (byte counts jump back, 4 consecutive implausible packets) triggers a resync; frame indices keep increasing. [R4]
- The converter produces the cube `[rx][sample][chirp]` of `complex<int16>` with re = I, im = Q. TI has no equivalent array. [R5]
- Each output form has its own axis order on purpose (figure above); content order agrees. TI's MATLAB example uses `[rx x (chirp*sample)]`. [R6]
- For the GUI, range FFT runs over the sample axis, Doppler over loops, and the chirp axis is reshaped to `[loops, chirps-per-loop]`. [R7]

## 8. Which firmware, which page

| Firmware | Lanes | Header | Page |
|---|---|---|---|
| Stock mmw demo (IWR1843/6843/ODS) | 2 | optional | [demo](demo.md) |
| `iwr_raw_rosnode` image (IWR1443) | 4 | none | [dca1000_raw](dca1000_raw.md) |
| `iwr1843_sar_lvds` | 2 | none, metadata after payload | [sar_lvds](sar_lvds.md) |
| AWR2243 cascade DDM | - | - | [cascade_ddm](cascade_ddm.md) |

[F1][F2][F3][F5]

## Known gaps

- V1: 4-lane layout with fewer than 4 RX; TI and our code disagree. Open.
- V3, V4: header-enabled demo configs and DCA1000 "multi" logging mode versus our always-raw; open, benign.
- V8, V10: see [sar_lvds](sar_lvds.md) and section 3.
- Not documented in TI's public docs: SDK header fields, CP/CQ layouts, the `u0 u2 u1 u3` reorder, CONFIG_FPGA_GEN and CONFIG_PACKET_DATA bytes, what "byte count" counts.
- The mmWave Studio guide, DCA1000 CLI guide and ICD were not available when this was written.

## Appendix: byte-level reference

Golden frame (IWR1843, stock demo, SDK 3.6.2): R = 4, Ns = 128, Nc = 256.

| Quantity | Value | Claim |
|---|---|---|
| Bytes per sample | 4 | [E4] |
| Frame bytes B | 4 x R x Ns x Nc = 524 288 | [R1] |
| Words per RX per chirp | Ns x 2 = 256 int16 | [E4][L9] |
| Stream order | chirp, RX, sample | [L9] |
| Payload per packet | 1462 B | [D4][D5] |
| Packets per frame | 524 288 / 1462 = 358.6, so frames straddle packets | [R2] |
| Packet header | seq u32 LE @0, byte count u48 LE @4 | [D4] |

Two-lane word groups (SampleSwap 1), file words `[A0 A1 B0 B1]` repeating:

| Word | Content | Claim |
|---|---|---|
| A0, A1 | Q of samples 2g, 2g+1 | [L6][L7] |
| B0, B1 | I of samples 2g, 2g+1 | [L6][L7] |

Four-lane word groups (IWR1443), per time step t = chirp x Ns + sample, R = 4:

| Words | Content | Claim |
|---|---|---|
| 0..3 | first component, RX0..RX3 (I when `i_first`) | [L11][E6] |
| 4..7 | second component, RX0..RX3 | [L11] |

Fixed identifiers:

| Item | Bytes on the wire | Claim |
|---|---|---|
| HSI ID, HW stream | `DC 0A DA 0C DC 0A DA 0C` | [H3][V6] |
| Command header / footer | `0xA55A` / `0xEEAA` | [D3] |
| Command codes | RESET 0x01, CONFIG_FPGA_GEN 0x03, RECORD_START 0x05, RECORD_STOP 0x06, SYSTEM_CONNECT 0x09, CONFIG_PACKET_DATA 0x0B, READ_FPGA_VERSION 0x0E | [D3] |
| Default ports | command 4096, data 4098 | [D2] |

Axis order per consumer:

| Consumer | Axes | Claim |
|---|---|---|
| `LVDS_Raw_0.bin` | concatenated payloads, wire order | [R6] |
| `adc_data.bin` | `[chirp][rx][sample][re, im]` int16 | [R6] |
| C++ cube | `[rx][sample][chirp]` complex<int16> | [R5] |
| Tap / `radar_gui` | `[rx][sample][chirp][I, Q]` int16, `iq_order: "IQ"` | [R6] |
| ROS `ADCDataCube` | `rx_channel`/`sample`/`chirp`, separate real and imag arrays, chirp fastest | [R6] |
| HDF5 `radar_adc/data` | `(N, 2, rx, sample, chirp)` | [R6] |
