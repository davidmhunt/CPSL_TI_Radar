"""validate(cfg, board): structured errors/warnings for one cfg on one board."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from . import firmware as fwmod
from .limits import BOARD_LIMITS, Limit, dca1000_ceiling_mbps, dca1000_params, firmware_limits, host_limits
from .metrics import BOARDS, CASCADE, Metrics, frame_layout, metrics, popcount, tdm_slots
from .parse import Cfg, CfgError

# Several shipped cfgs overshoot the nominal 81/64 GHz edge by ~0.15 MHz (slope 35 x ramp 114.29) and run fine.
BAND_TOLERANCE_MHZ = 5.0
REQUIRED = ("profileCfg", "chirpCfg", "channelCfg")   # plus a frame: frameCfg OR advFrameCfg + subFrameCfg
_MIMO_DOC = "docs/design/mimo_modes.md"
_M1 = "docs/research/gui_multichirp_tdm.md"
_M2 = "docs/research/gui_board_limits_cascade_multiprofile.md"
_WEAK = ("unverified", "low")


@dataclass
class Issue:
    level: str          # "error" | "warning" | "info"
    code: str
    message: str
    source: str = ""
    confidence: str = ""   # of the limit behind it: repo | high | medium | low | unverified

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


def _frames(cfg: Cfg, cascade: bool) -> list[tuple[str, int, int, int]]:
    """(label, first chirp, last chirp, loops) of the plain frame or of each advanced-frame subframe."""
    subs = cfg.subframes
    if subs:
        return [(f"subframe {sf['index']}", sf["chirp_start"], sf["chirp_start"] + sf["num_chirps"] - 1,
                 sf["num_loops"]) for sf in subs]
    f = frame_layout(cfg, cascade)
    return [("frame", f["start"], f["end"], f["loops"])]


def mimo_issues(cfg: Cfg, board: str, m: Metrics, mm: dict | None, fw: dict | None) -> list[Issue]:
    """Per-scheme chirp-pattern, BPM, subframe and profile rules (gui-15; docs/design/mimo_modes.md section 4).
    `mm` is the firmware's `mimo` block for `board` (None: no firmware known, only structural rules run).
    A rule whose own confidence or whose firmware's mimo confidence is unverified/low never yields an error."""
    out: list[Issue] = []
    scheme = m.scheme
    fwconf = mm["confidence"] if mm else "unverified"
    fwsrc = mm["source"] if mm else ""

    def add(level, code, msg, source, conf):
        weak = conf in _WEAK or fwconf in _WEAK
        if weak and level == "error":
            level, msg = "warning", msg + f" [{'unverified' if fwconf in _WEAK else conf} rule on this firmware]"
        out.append(Issue(level, code, msg, source, conf if conf in _WEAK else (fwconf if fwconf in _WEAK else conf)))

    cascade = board == CASCADE
    try:
        frames = _frames(cfg, cascade)
        seq = dict(cfg.chirp_sequence)
    except CfgError:
        return out
    ch = cfg.first("channelCfg").floats()

    # --- advFrameCfg / subframes
    subs = cfg.subframes
    if subs and mm is not None:
        cap = mm["subframes"]
        if cap == 0:
            add("error", "subframes_unsupported",
                f"advFrameCfg ({len(subs)} subframes) is not supported by this firmware on {board}"
                + (" (DDMA chain: 'Advanced Subframe Config is not currently supported', mss_main.c:3888-3891)"
                   if scheme == "ddma" else " (frame mode only)"), f"{_M2} s2; {fwsrc}", "high" if fwconf == "high" else fwconf)
        elif cap is None:
            add("warning", "subframes_unsupported", f"advFrameCfg: subframe support on {board} is not established "
                f"for this firmware", fwsrc, "unverified")
        elif len(subs) > cap:
            add("error", "subframes_unsupported", f"advFrameCfg declares {len(subs)} subframes; this firmware accepts at most {cap}"
                " (RL_MAX_SUBFRAMES, rl_sensor.h)", f"{_M2} s2; {fwsrc}", fwconf)

    # --- profiles: the demo chain reads RF parameters from one profile per (sub)frame
    declared = {int(c.floats()[0]) for c in cfg.all("profileCfg") if c.floats()}
    used = set()
    for _, a, b, _ in frames:
        for i in range(a, b + 1):
            pid = cfg.chirp_profile_id(i)
            if pid is not None:
                used.add(pid)
    for label, a, b, _ in frames:
        pids = {cfg.chirp_profile_id(i) for i in range(a, b + 1)} - {None}
        if len(pids) > 1:
            add("error", "chirps_span_profiles",
                f"{label}: chirps {a}-{b} reference profiles {sorted(pids)}; the demo data path takes RF parameters from "
                f"one profile per (sub)frame and rejects a frame whose chirps use more than one "
                f"(mmwdemo_rfparser.c:788; {_M2} s2, docs/research/gui_board_limits_cascade_multiprofile.md)",
                f"{_M2} s2", "high")
    extra = sorted(declared - used)
    if extra and used:
        add("warning", "extra_profiles_ignored",
            f"profileCfg id(s) {extra} are not used by the frame's chirps; the demo data path reads one profile per "
            f"(sub)frame ('we support only one profile', mmwdemo_rfparser.c:788) and ignores the rest",
            f"{_M2} s2", "high")

    bpm = cfg.bpm_enabled
    if bpm and mm is not None and not mm["bpm"]:
        add("error", "bpm_unsupported",
            f"bpmCfg is enabled but this firmware does not support BPM on {board} (descriptor mimo.bpm = false)",
            f"{_M1} s2; {fwsrc}", fwconf)

    if scheme == "ddma":
        # chirp masks are overwritten by the parser; cpl should be a multiple of the Doppler band count
        chmask = int(ch[1]) | (int(ch[4]) if len(ch) > 4 else 0)
        for label, a, b, _ in frames:
            diff = sorted({seq[i] for i in range(a, b + 1) if i in seq and seq[i] != chmask})
            if diff:
                add("info", "cascade_chirp_mask_ignored",
                    f"{label}: chirpCfg TX mask(s) {diff} differ from channelCfg TX {chmask}; the DDMA parser overwrites "
                    f"them with channelCfg (mmwdemo_rfparserDDMA.c:717-733), all enabled TX fire on every chirp",
                    f"{_MIMO_DOC} s1; {_M1} s3", "high")
            cpl = b - a + 1
            if m.n_bands > 1 and cpl % m.n_bands:
                add("warning", "ddma_cpl_not_band_multiple",
                    f"{label}: {cpl} chirps per loop is not a multiple of the {m.n_bands} Doppler bands; the phase "
                    f"pattern repeats every {m.n_bands} chirps (inferred, not enforced by the firmware; every TI cfg uses 8)",
                    f"{_M2} s2", "low")
        return out

    # --- TDM single-chip patterns
    txmask = int(ch[1])
    for label, a, b, loops in frames:
        masks = [seq[i] for i in range(a, b + 1) if i in seq]
        cpl = b - a + 1
        if len(masks) != cpl:
            continue   # metrics already reports chirps with no chirpCfg
        pc = [popcount(x) for x in masks]
        if mm and mm["max_chirps_per_loop"] is not None and cpl > mm["max_chirps_per_loop"]:
            add("error", "tx_pattern_invalid",
                f"{label}: {cpl} chirps per loop exceeds the {mm['max_chirps_per_loop']} the firmware accepts "
                f"(validChirpTxEnBits[32], mmwdemo_rfparser.c:782-800)", f"{_M1} s1; {fwsrc}", fwconf)
        if any(x == 0 for x in masks):
            add("error", "tx_pattern_invalid", f"{label}: a chirp enables no TX", f"{_M1} s1 (RP:522-560)", "high")
        outside = sorted({x for x in masks if x and not x & txmask})
        if outside:
            add("error", "tx_not_in_channelcfg",
                f"{label}: chirp TX mask(s) {outside} have no TX enabled in channelCfg (TX mask {txmask}); the parser "
                f"requires (chirp mask & channelCfg TX) > 0 (mmwdemo_rfparser.c:836)", f"{_M1} s1", "high")
        if len({(x & (x - 1)) == 0 for x in masks if x}) > 1:
            add("error", "tx_pattern_invalid",
                f"{label}: mixes one-TX and multi-TX chirps (masks {masks}); the parser rejects it (mmwdemo_rfparser.c:526-560)",
                f"{_M1} s1", "high")
            continue
        multi = all(x > 1 and x & (x - 1) for x in masks)
        if bpm:
            bad = sorted({x for x in masks if x != 0b101})
            if bad:
                add("error", "tx_pattern_invalid",
                    f"{label}: bpmCfg is on but chirp mask(s) {bad} are not 5 (TX1+TX3); BPM needs both azimuth TX on "
                    f"every chirp (mmwdemo_rfparser.c:530-540)", f"{_M1} s1", "high")
            elif fwmod.elevation_tx_bit(board) == 0b100:
                # Stock 6843 demo (xwr68xx mss_main.c:1763-1796, SDK 3.6): the BPM phases are hardcoded to TX1 (+) and
                # TX3 (-), "for 68xx device"; the demo does not know the ODS layout, so BPM is flagged, not re-targeted.
                add("warning", "bpm_ods_pairing",
                    f"{label}: bpmCfg drives TX1+TX3 (mask 5) in the stock demo (mss_main.c:1767-1796), but on {board} the "
                    f"azimuth pair is TX1+TX2 (TX3 is elevation), so BPM does not give a pure 2-TX azimuth aperture here "
                    f"(inferred from the antenna layout, not bench-tested)",
                    "docs/research/iwr6843_ods_antenna_2026-10-07.md", "low")
            continue
        if multi:
            add("info", "simo_multi_tx",
                f"{label}: multi-TX mask {sorted(set(masks))} on every chirp without bpmCfg is SIMO: the TX transmit "
                f"together, n_TX = 1, {m.n_rx} virtual antennas (enable bpmCfg for 2-TX BPM)",
                f"{_M1} s1 (RP:608-616)", "high")
            continue
        # one TX per chirp (plain TDM): periodic with period n_TX, every TX of channelCfg present, azimuth first
        n_tx = tdm_slots(masks, False, fwmod.elevation_tx_bit(board))[0]
        if cpl % n_tx or any(masks[i] != masks[i % n_tx] for i in range(cpl)):
            add("warning", "tx_pattern_not_periodic",
                f"{label}: TX pattern {masks} is not periodic with the {n_tx} TX time slot(s) per loop; the range DPU "
                f"de-interleaves chirp k to TX k mod n_TX, so a non-cyclic pattern probably misdecodes (inferred, not tested)",
                f"{_M1} s1/s4", "low")
        used_tx = 0
        for x in masks:
            used_tx |= x
        absent = txmask & ~used_tx
        if absent:
            add("info", "tx_missing_from_loop",
                f"{label}: channelCfg enables TX mask {txmask} but no chirp of the loop uses TX bit(s) {absent:#x}; "
                f"those TX never transmit (harmless: shipped hardware-run cfgs do this)", f"{_M1} s1", "medium")
        if n_tx == 3 and loops % 2:
            add("warning", "tx_loops_odd",
                f"{label}: 3-TX pattern with odd numLoops {loops}; the range DPU de-interleaves with a stride of 6 chirps "
                f"(two loops), so an odd count leaves a partial stride (inferred)", f"{_M1} s1 (rangeprochwa.c:1027)", "medium")
        first = masks[:n_tx]
        ebit = fwmod.elevation_tx_bit(board)
        if ebit in first and first[-1] != ebit:
            tx = ebit.bit_length()
            order = sorted(first, key=lambda x: x == ebit)   # elevation last, azimuth in loop order
            add("warning", "tx_order_convention",
                f"{label}: TX{tx} (elevation on {board}) chirp is not last in the loop {first}; the convention is azimuth "
                f"first, elevation last ({','.join(map(str, order))}); whether another order mislabels virtual antennas "
                f"is unverified", f"{_M1} s4 (experiment 2)", "low")
    return out


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
            weak = key.confidence in ("unverified", "low")   # a violation of an unsourced limit is never an error
            if weak and lv == "error":
                lv = "warning"
            issues.append(Issue(lv, code, msg + (f" [{key.confidence} limit]" if weak else ""), key.source, key.confidence))
        else:
            issues.append(Issue(level or "error", code, msg, key))

    for name in REQUIRED:
        if not cfg.has(name):
            add("structure", "missing_" + name, f"cfg has no {name}")
    advanced = cfg.has("advFrameCfg")
    if not cfg.has("frameCfg") and not (advanced and cfg.has("subFrameCfg")):
        add("structure", "missing_frameCfg", "cfg has no frameCfg (nor advFrameCfg with subFrameCfg)")
    if any(i.level == "error" for i in issues):
        return Report(board, False, issues)

    # argument counts per dialect (board descriptor cfg_dialect); an advanced-frame cfg has no frameCfg
    fc, cc = cfg.first("frameCfg"), cfg.first("channelCfg")
    if fc is not None and len(fc.args) != lim["frame_cfg_args"].value:
        add(lim["frame_cfg_args"], "frame_cfg_layout",
            f"frameCfg has {len(fc.args)} fields; {board} expects {lim['frame_cfg_args'].value}")
    if len(cc.args) != lim["channel_cfg_args"].value:
        add(lim["channel_cfg_args"], "channel_cfg_layout",
            f"channelCfg has {len(cc.args)} fields; {board} expects {lim['channel_cfg_args'].value}")
    if issues:   # metrics would misread the fields
        return Report(board, False, issues)

    # driver board cfg_dialect: commands the firmware needs / rejects (gui-30; data-driven, only the SAR board sets them)
    _fw0 = fwmod.get(firmware) if firmware else fwmod.default_for(board)
    drv = fwmod.driver_board(_fw0, board) if _fw0 else board
    dia = fwmod.cfg_dialect(drv)
    dsrc = f"config/boards/{drv}.json cfg_dialect"
    for name in dia.get("required_commands") or []:
        if not cfg.has(name):
            issues.append(Issue("error", "missing_" + name, f"cfg has no {name}, which the {drv} firmware requires", dsrc, "repo"))
    for name in dia.get("forbidden_commands") or []:
        if cfg.has(name):
            issues.append(Issue("error", "forbidden_" + name, f"cfg has {name}, which the {drv} firmware rejects", dsrc, "repo"))

    try:
        _fw = fwmod.get(firmware) if firmware else fwmod.default_for(board)
        mm = fwmod.mimo(board, _fw) if _fw else None
        m = metrics(cfg, board, mm["scheme"] if mm else None)
    except CfgError as e:
        add("parse", "bad_cfg", str(e))
        return Report(board, False, issues)

    # --- MIMO / chirp pattern / subframes / profiles (gui-15)
    issues += mimo_issues(cfg, board, m, mm, _fw)

    # --- array sizes
    if m.n_rx > lim["n_rx"].value:
        add(lim["n_rx"], "too_many_rx", f"{m.n_rx} RX enabled, {board} has {lim['n_rx'].value}")
    if m.n_tx > lim["n_tx"].value:
        add(lim["n_tx"], "too_many_tx", f"{m.n_tx} TX used, {board} has {lim['n_tx'].value}")
    if "valid_tx_counts" in lim and m.n_tx not in lim["valid_tx_counts"].value:
        add(lim["valid_tx_counts"], "tx_count_invalid",
            f"{m.n_tx} TX is not a valid DDMA count; the firmware accepts {list(lim['valid_tx_counts'].value)} TX")

    # --- RF
    lo, hi = lim["band_ghz"].value
    top = m.start_ghz + m.sweep_mhz / 1e3
    over_mhz = max((lo - m.start_ghz) * 1e3, (top - hi) * 1e3)   # how far outside the band, MHz
    if over_mhz > BAND_TOLERANCE_MHZ:
        add(lim["band_ghz"], "band",
            f"chirp spans {m.start_ghz:g}-{top:.3f} GHz, outside the {lo:g}-{hi:g} GHz band")
    else:
        if over_mhz > 1e-6:
            add(lim["band_ghz"], "band_edge",
                f"chirp spans {m.start_ghz:g}-{top:.4f} GHz, {over_mhz:.2f} MHz past the {lo:g}-{hi:g} GHz band edge "
                f"(rounding in TI's own cfgs; accepted by the firmware)", "warning")
        if "band_subranges_ghz" in lim:
            tol = BAND_TOLERANCE_MHZ / 1e3
            if not any(a - tol <= m.start_ghz and top <= b + tol for a, b in lim["band_subranges_ghz"].value):
                add(lim["band_subranges_ghz"], "band_subrange",
                    f"chirp spans {m.start_ghz:g}-{top:.3f} GHz; a sweep must lie wholly inside one of "
                    f"{[list(r) for r in lim['band_subranges_ghz'].value]} GHz")
    if m.slope_mhz_us > lim["max_slope_mhz_us"].value:
        add(lim["max_slope_mhz_us"], "slope",
            f"slope {m.slope_mhz_us:g} MHz/us exceeds the {board} limit of {lim['max_slope_mhz_us'].value:g}")
    elif "tested_max_slope_mhz_us" in lim and m.slope_mhz_us > lim["tested_max_slope_mhz_us"].value:
        add(lim["tested_max_slope_mhz_us"], "slope_untested",
            f"slope {m.slope_mhz_us:g} MHz/us is above the {lim['tested_max_slope_mhz_us'].value:g} this repo has tested "
            f"(silicon allows {lim['max_slope_mhz_us'].value:g})")
    # sample rate: the datasheet caps are for complex 1x; real / complex 2x ADC output formats allow twice that
    fmt = cfg.first("adcCfg")
    adc_fmt = int(float(fmt.args[1])) if fmt is not None and len(fmt.args) > 1 else 1
    adc_factor = 2 if adc_fmt in (0, 2) else 1
    fs_cap = lim["max_sample_rate_ksps"].value * adc_factor
    if m.sample_rate_ksps > fs_cap:
        add(lim["max_sample_rate_ksps"], "sample_rate",
            f"sample rate {m.sample_rate_ksps:g} ksps exceeds the {board} maximum of {fs_cap:g}")
    lp = cfg.first("lowPower")
    low_power = lp is not None and len(lp.args) > 1 and int(float(lp.args[1])) == 1
    if low_power and "lowpower_max_ksps" in lim and m.sample_rate_ksps > lim["lowpower_max_ksps"].value * adc_factor:
        add(lim["lowpower_max_ksps"], "sample_rate_lowpower",
            f"sample rate {m.sample_rate_ksps:g} ksps exceeds {lim['lowpower_max_ksps'].value * adc_factor:g} ksps, the "
            f"{board} limit in low-power ADC mode (lowPower 0 1); use lowPower 0 0 or a lower rate")
    if "min_sample_rate_ksps" in lim and m.sample_rate_ksps < lim["min_sample_rate_ksps"].value:
        add(lim["min_sample_rate_ksps"], "sample_rate_low",
            f"sample rate {m.sample_rate_ksps:g} ksps is below {lim['min_sample_rate_ksps'].value:g}")
    if "tested_sample_rates_ksps" in lim and m.sample_rate_ksps not in lim["tested_sample_rates_ksps"].value:
        add(lim["tested_sample_rates_ksps"], "sample_rate_untested",
            f"sample rate {m.sample_rate_ksps:g} ksps is not one of TI's tested {list(lim['tested_sample_rates_ksps'].value)} "
            f"(silicon allows {lim['min_sample_rate_ksps'].value:g}-{lim['max_sample_rate_ksps'].value:g})")
    if "min_chirp_cycle_us" in lim and m.chirp_us < lim["min_chirp_cycle_us"].value:
        add(lim["min_chirp_cycle_us"], "chirp_cycle",
            f"chirp cycle (idle {m.idle_us:g} + ramp {m.ramp_us:g} us) = {m.chirp_us:g} us is below the "
            f"{lim['min_chirp_cycle_us'].value:g} us minimum")
    if "min_idle_us" in lim and m.idle_us < lim["min_idle_us"].value:
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
    else:
        if "min_frame_period_us" in lim and m.frame_period_ms * 1e3 < lim["min_frame_period_us"].value:
            add(lim["min_frame_period_us"], "frame_period_short",
                f"frame period {m.frame_period_ms:g} ms is below {lim['min_frame_period_us'].value / 1e3:g} ms")
        if "max_frame_period_ms" in lim and m.frame_period_ms > lim["max_frame_period_ms"].value:
            add(lim["max_frame_period_ms"], "frame_period_long",
                f"frame period {m.frame_period_ms:g} ms exceeds {lim['max_frame_period_ms'].value:g} ms")
        blank_us = (m.frame_period_ms - m.active_ms) * 1e3
        if "min_frame_blank_us" in lim and blank_us < lim["min_frame_blank_us"].value:
            add(lim["min_frame_blank_us"], "frame_blank",
                f"only {blank_us:.0f} us between the last chirp and the next frame; the radar needs about "
                f"{lim['min_frame_blank_us'].value:g} us")
        if m.duty_cycle > host_limits()["duty_warn"].value:
            add(host_limits()["duty_warn"], "duty", f"duty cycle {m.duty_cycle:.0%}: little time left to process each frame")
    if "max_samples_silicon" in lim and m.num_samples > lim["max_samples_silicon"].value:
        add(lim["max_samples_silicon"], "samples_silicon",
            f"{m.num_samples} samples exceeds the ADC buffer limit of {lim['max_samples_silicon'].value}")
    if "max_samples" in lim and m.num_samples > lim["max_samples"].value:
        add(lim["max_samples"], "samples", f"{m.num_samples} samples exceeds tested {lim['max_samples'].value}")
    if "max_chirps" in lim and m.n_chirps > lim["max_chirps"].value:
        add(lim["max_chirps"], "chirps", f"{m.n_chirps} chirps exceeds tested {lim['max_chirps'].value}")
    if "adc_buffer_bytes" in lim:
        chirp_b = m.num_samples * m.n_rx * m.bytes_per_sample
        if chirp_b > lim["adc_buffer_bytes"].value:
            add(lim["adc_buffer_bytes"], "adc_buffer",
                f"one chirp is {chirp_b} B, larger than the {lim['adc_buffer_bytes'].value} B ADC buffer")
        elif "adc_buffer_streaming_bytes" in lim and chirp_b > lim["adc_buffer_streaming_bytes"].value and \
                (m.lvds_data_fmt or not _is_demo(cfg)):
            add(lim["adc_buffer_streaming_bytes"], "adc_buffer_streaming",
                f"one chirp is {chirp_b} B; when streaming over LVDS only a {lim['adc_buffer_streaming_bytes'].value} B "
                f"ping/pong half is usable per chirp")

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
            lv = cfg.first("lvdsStreamCfg")
            header_on = lv is not None and len(lv.args) > 1 and int(float(lv.args[1])) != 0
            if "lvds_min_transfer_bytes" in lim and not header_on and \
                    m.num_samples * m.n_rx * m.bytes_per_sample < lim["lvds_min_transfer_bytes"].value:
                add(lim["lvds_min_transfer_bytes"], "lvds_min_transfer",
                    f"one chirp is {m.num_samples * m.n_rx * m.bytes_per_sample} B, below the {lim['lvds_min_transfer_bytes'].value} B "
                    f"CBUFF minimum transfer; enable the HSI header in lvdsStreamCfg or use more samples")
            if "lvds_min_samples" in lim and m.num_samples < lim["lvds_min_samples"].value:
                add(lim["lvds_min_samples"], "lvds_min_samples",
                    f"TI supports LVDS streaming of the demo for at least {lim['lvds_min_samples'].value} ADC samples per chirp, cfg has {m.num_samples}")
            need = m.bytes_per_chirp + lim["lvds_chirp_overhead_bytes"].value
            align = lim["lvds_chirp_align_bytes"].value
            need = -(-need // align) * align
            cap_b = m.chirp_us * lim["lvds_lanes"].value * lim["lvds_lane_mbps"].value / 8
            if need > cap_b:
                add(lim["lvds_lane_mbps"], "lvds_rate",
                    f"each chirp sends {need} B over LVDS (ADC data + header, rounded up) but a chirp cycle of "
                    f"{m.chirp_us:g} us carries only {cap_b:.0f} B on {lim['lvds_lanes'].value} lanes x "
                    f"{lim['lvds_lane_mbps'].value} Mbps; the firmware will not stream this cfg")
            host = host_limits()
            ceil = dca1000_ceiling_mbps(board)
            _, delay = dca1000_params(board)
            if m.avg_data_rate_mbps > host["dca1000_ethernet_mbps"].value:
                add(host["dca1000_ethernet_mbps"], "dca_rate",
                    f"average {m.avg_data_rate_mbps:.0f} Mbps exceeds the 1 Gb/s DCA1000 link")
            elif m.avg_data_rate_mbps > ceil:
                add(host["dca1000_max_mbps"], "dca_rate_high",
                    f"average {m.avg_data_rate_mbps:.0f} Mbps is above the ~{ceil:.0f} Mbps the DCA1000 sustains at the "
                    f"driver's {delay:g} us packet delay (config/boards/{board}.json dca1000; lower the delay to raise it)")
        _fw = fwmod.get(firmware) if firmware else fwmod.default_for(board)
        _fm = _fw.get("lvds_data_fmts") if _fw else None
        if _fm and m.lvds_data_fmt not in _fm["value"]:
            issues.append(Issue("warning", "lvds_fmt_unsupported",
                                f"lvdsStreamCfg dataFmt {m.lvds_data_fmt} is not one of the values firmware {_fw['id']!r} "
                                f"accepts ({', '.join(map(str, _fm['value']))}); it will not stream as configured"
                                + (" [unverified set]" if _fm["confidence"] in ("unverified", "low") else ""),
                                _fm["source"], _fm["confidence"]))

    if lim["config_once_per_boot"].value:
        add(lim["config_once_per_boot"], "once_per_boot",
            f"{board} accepts a cfg only once per power-up; power-cycle before sending this one", "info")

    return Report(board, not any(i.level == "error" for i in issues), issues, m)
