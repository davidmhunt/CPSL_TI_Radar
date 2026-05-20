# Utilities

Python notebooks for analyzing output from the C++ radar streamer (`CPSL_TI_Radar_cpp/`).

## Notebooks

| Notebook | Reads | Purpose |
|---|---|---|
| `process_adc_data.ipynb` | `adc_data.bin` | Load ADC cube, convert to complex, range/Doppler/azimuth FFT analysis |
| `process_raw_lbds_data.ipynb` | `LVDS_Raw_0.bin` | Decode raw LVDS packet stream, reconstruct complex samples |
| `print_config.ipynb` | `.cfg` file | Decode radar config and print key parameters |
| `determine_serial_ports.ipynb` | — | List available serial/COM ports on the host |
| `bartlet.ipynb` | — | Angle-of-arrival estimation (Bartlett and Capon beamforming demo) |
| `test_ethernet_traffic.ipynb` | — | DCA1000 network debugging |

---

## File Formats Produced by C++

### `adc_data.bin`

Written by `DCA1000Handler::write_adc_data_cube_to_file()` when `save_to_file: true` in the JSON config.

- **Dtype**: `int16` (little-endian), interleaved real/imaginary pairs
- **Write order**: `for frame → for chirp → for rx → for sample`: write `real (int16)`, `imag (int16)`
- **Shape after loading**: `(N_frames, N_rx, samples_per_chirp, chirps_per_frame)` as `complex64`
- **Bytes per frame**: `4 × chirps_per_frame × num_rx × samples_per_chirp`

Loading recipe (NumPy):
```python
import numpy as np

data = np.fromfile("adc_data.bin", dtype=np.int16)
data = np.reshape(data, (2, -1), order='F')        # deinterleave: row 0 = real, row 1 = imag
data = data[0] + 1j * data[1]                       # complex array, ordered (frame, chirp, rx, sample)
cube = np.reshape(data, (-1, chirps_per_frame, num_rx, samples_per_chirp), order='C')
cube = np.transpose(cube, axes=(0, 2, 3, 1))        # → (frames, rx, samples, chirps)
```

---

### `LVDS_Raw_0.bin`

Written by the RX worker thread when `save_to_file: true` (raw LVDS option).

- **Content**: Concatenation of all UDP ADC payloads with the 10-byte DCA1000 header stripped
- **Dtype**: `uint8` stream (raw bytes as received from FPGA)
- **Endianness**: Little-endian (as transmitted by DCA1000)
- **Processing**: Must be decoded through the same lane-demux and byte-to-int16 conversion used by `ADCCubeConverter`

The 10-byte DCA1000 UDP header format (already stripped from this file):
```
Bytes 0–3:  sequence number (uint32, little-endian)
Bytes 4–9:  byte count (uint48, little-endian)
Bytes 10+:  ADC payload (up to 1462 bytes per packet)
```
