"""gui-15 Step 2: MIMO-scheme-aware params/generate (docs/design/mimo_modes.md s4). Hardware-free."""
from pathlib import Path

import pytest

from radar_gui.cfg import ParamsError, apply_params, generate, metrics, parse_cfg, params_from_cfg
from radar_gui.cfg import firmware as fwmod

ROOT = Path(__file__).resolve().parents[1]
RADAR = ROOT / "CPSL_TI_Radar_cpp" / "config" / "radar"
T6843 = (RADAR / "nav_configs" / "6843_RadVel_ods_10Hz.cfg").read_text()     # 3-TX plain TDM, bpm off
T1843 = (RADAR / "nav_configs" / "1843_RadVel_10Hz.cfg").read_text()
CAS = (ROOT / "tools" / "radar_viewer" / "configs" / "cascade_R15m_V5ms_20Hz.cfg").read_text()
TARGETS = dict(max_range_m=20, max_velocity_ms=5)


def chirps(text):
    return [int(c.args[7]) for c in parse_cfg(text).all("chirpCfg")]


def ch_tx(text):
    return int(parse_cfg(text).first("channelCfg").args[1])


def test_tx_mask_only_edit_is_azimuth_first():
    out = apply_params(T1843, {"tx_mask": 7})
    assert chirps(out) == [1, 4, 2] and ch_tx(out) == 7
    assert metrics(parse_cfg(out), "IWR1843").n_tx == 3
    assert chirps(apply_params(T6843, {"tx_mask": 6})) == [4, 2]


def test_channelcfg_tx_is_or_of_chirp_masks():
    out = apply_params(T6843, {"chirp_tx_masks": [1, 2]})
    assert chirps(out) == [1, 2] and ch_tx(out) == 3
    # explicit conflicting tx_mask: the OR wins, with a warning
    w = []
    out = apply_params(T6843, {"chirp_tx_masks": [1, 4], "tx_mask": 7}, warnings=w)
    assert ch_tx(out) == 5 and [c for c, _ in w] == ["tx_mask_from_chirps"]
    # rx edit survives the coupling
    out = apply_params(T6843, {"chirp_tx_masks": [1, 4, 2], "rx_mask": 3})
    assert parse_cfg(out).first("channelCfg").args[0] == "3"


def test_cascade_chirp_mask_edit_ignored_with_warning():
    w = []
    out = apply_params(CAS, {"chirp_tx_masks": [1, 2, 4]}, warnings=w)
    assert [c for c, _ in w] == ["cascade_chirp_mask_ignored"]
    assert out == apply_params(CAS, {})
    assert "bpm" not in params_from_cfg(parse_cfg(CAS), "AWR2243_CASCADE")


def test_cascade_rejects_bpm():
    with pytest.raises(ParamsError):
        apply_params(CAS, {"bpm": True}, board="AWR2243_CASCADE", firmware="cascade_ddm")


def test_default_params_output_is_plain_tdm_bpm_disabled():
    p = params_from_cfg(parse_cfg(T6843), "IWR6843")
    assert p["bpm"] is False
    out = apply_params(T6843, {"bpm": False}, board="IWR6843", firmware="demo")
    assert out == apply_params(T6843, {})
    assert not parse_cfg(out).bpm_enabled


def test_bpm_on_writes_mask5_and_enables_bpmcfg():
    out = apply_params(T6843, {"bpm": True}, board="IWR6843", firmware="demo")
    cfg = parse_cfg(out)
    assert chirps(out) == [5, 5] and ch_tx(out) == 5 and cfg.bpm_enabled
    m = metrics(cfg, "IWR6843")
    assert m.n_tx == 2 and m.bpm_enabled
    assert params_from_cfg(cfg, "IWR6843")["bpm"] is True
    back = apply_params(out, {"bpm": False, "tx_mask": 7}, board="IWR6843", firmware="demo")
    assert not parse_cfg(back).bpm_enabled and chirps(back) == [1, 4, 2]


def test_bpm_inserts_line_when_missing():
    base = "\n".join(l for l in T6843.splitlines() if not l.startswith("bpmCfg")) + "\n"
    out = apply_params(base, {"bpm": True}, board="IWR6843", firmware="demo")
    assert parse_cfg(out).bpm_enabled


@pytest.mark.parametrize("board,fw", [("IWR1443", "demo"), ("IWR1843", "iwr1843_sar_lvds"),
                                      ("IWR6843", "dca1000_raw")])
def test_bpm_rejected_where_descriptor_false(board, fw):
    assert not fwmod.mimo(board, fw)["bpm"]
    with pytest.raises(ParamsError, match="BPM"):
        apply_params(T1843, {"bpm": True}, board=board, firmware=fw)


def test_bpm_needs_board():
    with pytest.raises(ParamsError):
        apply_params(T6843, {"bpm": True})


def test_generate_default_is_plain_tdm_azimuth_first():
    r = generate("IWR6843", TARGETS)
    assert r.ok, r.report.issues
    cfg = parse_cfg(r.text)
    assert chirps(r.text) == [1, 4] and not cfg.bpm_enabled
    assert any(c.args[1] == "0" for c in cfg.all("bpmCfg"))
    r3 = generate("IWR6843", dict(TARGETS, tx_mask=7))
    assert chirps(r3.text) == [1, 4, 2]


def test_generate_vmax_uses_scheme_aware_ntx():
    # tx_mask 3 = TX1 + TX2: two slots; tx_mask 7: three. Velocity target met with n_TX, not popcount
    for mask, n in ((5, 2), (7, 3), (3, 2), (1, 1)):
        r = generate("IWR6843", dict(TARGETS, tx_mask=mask))
        assert r.ok, (mask, r.report.issues)
        assert r.metrics.n_tx == n
        assert r.metrics.max_velocity_ms == pytest.approx(5, rel=0.05)


def test_generate_bpm_on_supported_firmware():
    r = generate("IWR6843", dict(TARGETS, bpm=True))
    assert r.ok, r.report.issues
    cfg = parse_cfg(r.text)
    assert cfg.bpm_enabled and chirps(r.text) == [5, 5] and ch_tx(r.text) == 5
    assert r.metrics.n_tx == 2 and r.metrics.max_velocity_ms == pytest.approx(5, rel=0.05)


@pytest.mark.parametrize("board,fw", [("IWR1443", None), ("IWR6843", "dca1000_raw"), ("AWR2243_CASCADE", None)])
def test_generate_bpm_rejected_where_unsupported(board, fw):
    r = generate(board, dict(TARGETS, bpm=True), firmware=fw)
    assert not r.ok and r.report.issues[0].code == "bpm_unsupported"
