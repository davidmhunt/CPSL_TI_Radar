"""validate(cfg, board): structured errors/warnings for one cfg on one board."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from . import firmware as fwmod
from .limits import (BOARD_LIMITS, firmware_limits, DCA1000_ETHERNET_HEADROOM_MBPS, DCA1000_ETHERNET_MBPS, DUTY_WARN,
                     SAR_FIRMWARE_FMT2, Limit)
from .metrics import BOARDS, Metrics, metrics
from .parse import Cfg, CfgError

# Several shipped cfgs overshoot the nominal 81/64 GHz edge by ~0.15 MHz (slope 35 x ramp 114.29) and run fine.
BAND_TOLERANCE_MHZ = 5.0
REQUIRED = ("profileCfg", "chirpCfg", "frameCfg", "channelCfg")


@dataclass
class Issue:
    level: str          # "error" | "warning" | "info"
    code: str
    message: str
    source: str = ""
    confidence: str = ""   # of the limit behind it: repo | recalled | unverified

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Report:
    board: str
    ok: bool                         # no error-level issue
    issues: list[Issue] = field(default_factory=list)
    metrics: Metrics | None = None

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "warning"]

    def to_dict(self) -> dict:
        return {"board": self.board, "ok": self.ok, "issues": [i.to_dict() for i in self.issues],
                "metrics": self.metrics.to_dict() if self.metrics else None}


def _is_demo(cfg: Cfg) -> bool:
    """On-chip demo cfgs carry guiMonitor / CFAR; raw-ADC (DCA1000) cfgs do not."""
    return cfg.has("guiMonitor") or cfg.has("cfarCfg")


def validate(cfg: Cfg, board: str, firmware: str | None = None) -> Report:
    """Check `cfg` against `board`'s limits; `firmware` (id) selects that firmware's limits, default: the board's."""
    if board not in BOARDS:
        return Report(board, False, [Issue("error", "unknown_board",
                                           f"unknown board {board!r}; expected one of {list(BOARDS)}")])
    lim = firmware_limits(board, firmware) if firmware else BOARD_LIMITS[board]
    if lim is None:
        return Report(board, False, [Issue("error", "firmware_board_mismatch",
                                           f"firmware {firmware!r} has no limits for {board}")])
    issues: list[Issue] = []

    def add(key: Limit | str, code: str, msg: str, level: str | None = None):
        if isinstance(key, Limit):
            lv = level or key.level
            if key.confidence == "unverified" and lv == "error":
                lv = "warning"
            issues.append(Issue(lv, code, msg + (" [unverified limit]" if key.confidence == "unverified" else ""),
                                key.source, key.confidence))
        else:
            issues.append(Issue(level or "error", code, msg, key))

    for name in REQUIRED:
        if not cfg.has(name):
            add("structure", "missing_" + name, f"cfg has no {name}")
    if any(i.level == "error" for i in issues):
        return Report(board, False, issues)

    # argument counts per dialect (board descriptor cfg_dialect)
    fc, cc = cfg.first("frameCfg"), cfg.first("channelCfg")
    if len(fc.args) != lim["frame_cfg_args"].value:
        add(lim["frame_cfg_args"], "frame_cfg_layout",
            f"frameCfg has {len(fc.args)} fields; {board} expects {lim['frame_cfg_args'].value}")
    if len(cc.args) != lim["channel_cfg_args"].value:
        add(lim["channel_cfg_args"], "channel_cfg_layout",
            f"channelCfg has {len(cc.args)} fields; {board} expects {lim['channel_cfg_args'].value}")
    if issues:   # metrics would misread the fields
        return Report(board, False, issues)

    try:
        _fw = fwmod.get(firmware) if firmware else fwmod.default_for(board)
        m = metrics(cfg, board, fwmod.mimo(board, _fw)["scheme"] if _fw else None)
    except CfgError as e:
        add("parse", "bad_cfg", str(e))
        return Report(board, False, issues)

    # --- array sizes
    if m.n_rx > lim["n_rx"].value:
        add(lim["n_rx"], "too_many_rx", f"{m.n_rx} RX enabled, {board} has {lim['n_rx'].value}")
    if m.n_tx > lim["n_tx"].value:
        add(lim["n_tx"], "too_many_tx", f"{m.n_tx} TX used, {board} has {lim['n_tx'].value}")

    # --- RF
    lo, hi = lim["band_ghz"].value
    top = m.start_ghz + m.sweep_mhz / 1e3
    over_mhz = max((lo - m.start_ghz) * 1e3, (top - hi) * 1e3)   # how far outside the band, MHz
    if over_mhz > BAND_TOLERANCE_MHZ:
        add(lim["band_ghz"], "band",
            f"chirp spans {m.start_ghz:g}-{top:.3f} GHz, outside the {lo:g}-{hi:g} GHz band")
    elif over_mhz > 1e-6:
        add(lim["band_ghz"], "band_edge",
            f"chirp spans {m.start_ghz:g}-{top:.4f} GHz, {over_mhz:.2f} MHz past the {lo:g}-{hi:g} GHz band edge "
            f"(rounding in TI's own cfgs; accepted by the firmware)", "warning")
    if m.slope_mhz_us > lim["max_slope_mhz_us"].value:
        add(lim["max_slope_mhz_us"], "slope",
            f"slope {m.slope_mhz_us:g} MHz/us exceeds {lim['max_slope_mhz_us'].value:g}")
    if m.sample_rate_ksps > lim["max_sample_rate_ksps"].value:
        add(lim["max_sample_rate_ksps"], "sample_rate",
            f"sample rate {m.sample_rate_ksps:g} ksps exceeds {lim['max_sample_rate_ksps'].value:g}")
    if "min_sample_rate_ksps" in lim and m.sample_rate_ksps < lim["min_sample_rate_ksps"].value:
        add(lim["min_sample_rate_ksps"], "sample_rate_low",
            f"sample rate {m.sample_rate_ksps:g} ksps is below {lim['min_sample_rate_ksps'].value:g}")
    if "tested_sample_rates_ksps" in lim and m.sample_rate_ksps not in lim["tested_sample_rates_ksps"].value:
        add(lim["tested_sample_rates_ksps"], "sample_rate_untested",
            f"sample rate {m.sample_rate_ksps:g} ksps is not one of TI's tested {lim['tested_sample_rates_ksps'].value}")
    if m.idle_us < lim["min_idle_us"].value:
        add(lim["min_idle_us"], "idle", f"idle time {m.idle_us:g} us is below {lim['min_idle_us'].value:g}")
    if m.adc_start_us + m.sampling_us > m.ramp_us:
        add("physics: ADC window must end inside the ramp", "sampling_outside_ramp",
            f"ADC start {m.adc_start_us:g} + sampling {m.sampling_us:.2f} us = "
            f"{m.adc_start_us + m.sampling_us:.2f} us exceeds ramp end {m.ramp_us:g} us")

    # --- frame
    if m.n_loops > lim["max_loops"].value:
        add(lim["max_loops"], "loops", f"numLoops {m.n_loops} exceeds {lim['max_loops'].value}")
    if m.frame_period_ms <= 0:
        add("physics", "frame_period", "frame period must be positive")
    elif m.active_ms > m.frame_period_ms:
        add("physics: chirps cannot take longer than the frame", "frame_too_short",
            f"chirps take {m.active_ms:.2f} ms but the frame period is {m.frame_period_ms:g} ms")
    elif m.duty_cycle > DUTY_WARN.value:
        add(DUTY_WARN, "duty", f"duty cycle {m.duty_cycle:.0%}: little time left to process each frame")
    if "max_samples" in lim and m.num_samples > lim["max_samples"].value:
        add(lim["max_samples"], "samples", f"{m.num_samples} samples exceeds tested {lim['max_samples'].value}")
    if "max_chirps" in lim and m.n_chirps > lim["max_chirps"].value:
        add(lim["max_chirps"], "chirps", f"{m.n_chirps} chirps exceeds tested {lim['max_chirps'].value}")
    if "adc_buffer_half_bytes" in lim:
        chirp_b = m.num_samples * m.n_rx * m.bytes_per_sample
        if chirp_b > lim["adc_buffer_half_bytes"].value:
            add(lim["adc_buffer_half_bytes"], "adc_buffer",
                f"one chirp is {chirp_b} B, larger than the {lim['adc_buffer_half_bytes'].value} B ADC buffer half")

    # --- on-chip demo memory (not applicable to raw-ADC cfgs)
    if "l3_radar_cube_bytes" in lim and _is_demo(cfg):
        pow2 = lambda x: 1 << max(0, (int(x) - 1).bit_length())
        cube = pow2(m.num_samples) * pow2(m.n_loops) * m.n_virtual * 4
        if cube > lim["l3_radar_cube_bytes"].value:
            add(lim["l3_radar_cube_bytes"], "radar_cube",
                f"radar cube ~{cube} B (range x doppler x virtual x 4) exceeds L3 {lim['l3_radar_cube_bytes'].value} B")

    # --- LVDS / DCA1000
    if m.lvds_data_fmt is not None and m.lvds_data_fmt != 0:
        _fw = fwmod.get(firmware) if firmware else fwmod.default_for(board)
        if _fw is not None and board in _fw["outputs"] and not _fw["outputs"][board]["lvds"]:
            issues.append(Issue("error", "lvds_not_in_firmware",
                                f"lvdsStreamCfg is enabled but firmware {_fw['id']!r} has no LVDS output on {board}",
                                f"config/firmware/{_fw['id']}.json", "repo"))
        if not lim["lvds_supported"].value:
            add(lim["lvds_supported"], "lvds_unsupported", f"lvdsStreamCfg is enabled but {board} has no LVDS output",
                "warning")
        else:
            cap = lim["lvds_lanes"].value * lim["lvds_lane_mbps"].value
            if m.chirp_avg_rate_mbps > cap:
                add(lim["lvds_lane_mbps"], "lvds_rate",
                    f"per-chirp average {m.chirp_avg_rate_mbps:.0f} Mbps (ADC buffer drained between chirps) exceeds {lim['lvds_lanes'].value} lanes x "
                    f"{lim['lvds_lane_mbps'].value} Mbps")
            if m.avg_data_rate_mbps > DCA1000_ETHERNET_MBPS.value:
                add(DCA1000_ETHERNET_MBPS, "dca_rate",
                    f"average {m.avg_data_rate_mbps:.0f} Mbps exceeds the 1 Gb/s DCA1000 link")
            elif m.avg_data_rate_mbps > DCA1000_ETHERNET_HEADROOM_MBPS.value:
                add(DCA1000_ETHERNET_HEADROOM_MBPS, "dca_rate_high",
                    f"average {m.avg_data_rate_mbps:.0f} Mbps leaves little headroom on the 1 Gb/s link")
        if m.lvds_data_fmt == 2:
            add(SAR_FIRMWARE_FMT2, "lvds_fmt2", "dataFmt 2 needs the iwr1843_sar_lvds firmware",
                "info" if board == "IWR1843" else "warning")

    if lim["config_once_per_boot"].value:
        add(lim["config_once_per_boot"], "once_per_boot",
            f"{board} accepts a cfg only once per power-up; power-cycle before sending this one", "info")

    return Report(board, not any(i.level == "error" for i in issues), issues, m)
