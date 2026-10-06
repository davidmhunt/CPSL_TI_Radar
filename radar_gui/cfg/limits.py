"""Per-board constraints. Every entry names its source and how far it is trusted.

`confidence`:
  "repo"       taken from this repo (board descriptor, cfggen.py, docs/firmware.md, docs/RESULTS.md,
               or the shipped cfgs themselves)
  "recalled"   a well-known TI datasheet/SDK figure written down from memory; NOT re-checked
               against the TI document in this session
  "unverified" best-effort estimate; a violation is only ever a warning

The driver stays the authority; gui-04 moves these into the C++ board descriptors.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

CAS = "AWR2243_CASCADE"


@dataclass(frozen=True)
class Limit:
    value: object
    level: str          # severity when violated: "error" | "warning"
    source: str
    confidence: str     # "repo" | "recalled" | "unverified"


def L(value, level, source, confidence):
    return Limit(value, level, source, confidence)


_SD = "TI IWR/AWR datasheet (recalled, not re-checked)"
_SPEC = "CPSL_TI_Radar_cpp/config/boards/{}.json"


def _single(name, n_tx, n_rx, band, max_slope, max_fs, adc_buf, l3_kb, lanes, sdk):
    return {
        "kind": "single",
        "n_tx": L(n_tx, "error", _SD, "recalled"),
        "n_rx": L(n_rx, "error", _SD, "recalled"),
        "band_ghz": L(band, "error", _SD + ": RF band", "recalled"),
        "max_slope_mhz_us": L(max_slope, "warning", _SD + ": max slope (value uncertain; shipped cfgs reach 100)", "unverified"),
        "max_sample_rate_ksps": L(max_fs, "warning", _SD + ": ADC rate / IF bandwidth (shipped cfgs reach 12499)", "unverified"),
        "min_idle_us": L(2.0, "warning", "TI mmWave DFP interface doc: minimum idle time (value uncertain; shipped cfgs use >= 5)", "unverified"),
        "max_loops": L(255, "warning", "TI mmWave interface control doc: frameCfg numLoops 1..255 (recalled)", "unverified"),
        "adc_buffer_half_bytes": L(adc_buf, "warning", "ADC buffer ping/pong half: one chirp's samples x RX x bytes must fit (recalled)", "unverified"),
        "l3_radar_cube_bytes": L(l3_kb * 1024, "warning", "L3 RAM size; the demo's radar cube must fit alongside other buffers (recalled)", "unverified"),
        "lvds_supported": L(True, "error", _SPEC.format(name) + " lvds.supported", "repo"),
        "lvds_lanes": L(lanes, "error", _SPEC.format(name) + " lvds.lanes", "repo"),
        "lvds_lane_mbps": L(600, "warning", "DCA1000 EVM user guide: LVDS DDR up to 600 Mbps/lane (recalled)", "unverified"),
        "sdk": L(sdk, "warning", _SPEC.format(name) + " sdk", "repo"),
        "frame_cfg_args": L(7, "error", _SPEC.format(name) + " cfg_dialect.frame_period_field = 5", "repo"),
        "channel_cfg_args": L(3, "error", "shipped single-chip cfgs: channelCfg rx tx cascading", "repo"),
        "config_once_per_boot": L(False, "warning", _SPEC.format(name) + " lifecycle", "repo"),
    }


BOARD_LIMITS = {
    "IWR1443": _single("IWR1443", 3, 4, (76.0, 81.0), 100.0, 12500, 16384, 256, 4, "mmwave_sdk_2"),
    "IWR1843": _single("IWR1843", 3, 4, (76.0, 81.0), 266.0, 12500, 16384, 768, 2, "mmwave_sdk_3"),
    "IWR6843": _single("IWR6843", 3, 4, (60.0, 64.0), 266.0, 12500, 16384, 1024, 2, "mmwave_sdk_3"),
    CAS: {
        "kind": "cascade",
        "n_tx": L(6, "error", "tools/radar_viewer/cfggen.py docstring: 6 TX x 8 RX (2-chip cascade, DDMA)", "repo"),
        "n_rx": L(8, "error", "tools/radar_viewer/cfggen.py docstring: 6 TX x 8 RX", "repo"),
        "band_ghz": L((76.0, 81.0), "error", "tools/radar_viewer/cfggen.py BAND_TOP_GHZ=81; AWR2243 76-81 GHz (datasheet, recalled)", "recalled"),
        "max_slope_mhz_us": L(100.0, "error", "tools/radar_viewer/cfggen.py MAX_SLOPE", "repo"),
        "max_sample_rate_ksps": L(10000, "warning", "cfggen.py FS_MAX_KSPS; TI's short/long cfgs use 5000/10000", "repo"),
        "min_sample_rate_ksps": L(2000, "warning", "cfggen.py FS_MIN_KSPS", "repo"),
        "tested_sample_rates_ksps": L((5000, 10000), "warning", "cfggen.py FS_TESTED_KSPS", "repo"),
        "min_idle_us": L(4.0, "error", "cfggen.py MIN_IDLE_US", "repo"),
        "max_loops": L(255, "warning", "TI mmWave interface control doc numLoops (recalled)", "unverified"),
        "max_samples": L(192, "warning", "cfggen.py: TI only tested 192 samples x 256 chirps ('Chirp design is limited to 192 adc samples, 256 chirps')", "repo"),
        "max_chirps": L(256, "warning", "cfggen.py: TI only tested 192 samples x 256 chirps", "repo"),
        "lvds_supported": L(False, "error", _SPEC.format("AWR2243_CASCADE") + " lvds.supported", "repo"),
        "sdk": L("mmwave_mcuplus", "warning", _SPEC.format("AWR2243_CASCADE") + " sdk", "repo"),
        "frame_cfg_args": L(9, "error", _SPEC.format("AWR2243_CASCADE") + " cfg_dialect.frame_period_field = 6", "repo"),
        "channel_cfg_args": L(5, "error", "cascade_shortrange.cfg: channelCfg rx tx cascading rx2 tx2", "repo"),
        "config_once_per_boot": L(True, "warning", _SPEC.format("AWR2243_CASCADE") + " lifecycle; docs/firmware.md", "repo"),
    },
}

# Host side, board independent.
DCA1000_ETHERNET_MBPS = L(1000, "error", "docs/RESULTS.md: NIC 1000 Mb/s link to the DCA1000", "repo")
DCA1000_ETHERNET_HEADROOM_MBPS = L(800, "warning", "80 % of the 1 Gb/s link; overhead/headroom is a guess", "unverified")
DUTY_WARN = L(0.9, "warning", "heuristic: little time left for chirp-end processing/output", "unverified")
SAR_FIRMWARE_FMT2 = "docs/firmware.md: lvdsStreamCfg dataFmt 2 exists only in the iwr1843_sar_lvds firmware"


def limits_dict() -> dict:
    """BOARD_LIMITS as plain JSON-able dicts (for the HTTP layer)."""
    return {b: {k: (asdict(v) if isinstance(v, Limit) else v) for k, v in d.items()}
            for b, d in BOARD_LIMITS.items()}
