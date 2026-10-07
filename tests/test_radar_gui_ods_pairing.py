"""gui-29 Step 1: IWR6843ODS antenna pairing (azimuth TX1+TX2, elevation TX3) vs IWR6843 ISK (azimuth TX1+TX3,
elevation TX2) in metrics / validate / generate (docs/research/iwr6843_ods_antenna_2026-10-07.md). Hardware-free."""
import math

import pytest

from radar_gui.cfg import metrics, parse_cfg, validate
from radar_gui.cfg.metrics import az_tx_mask, tdm_slots
from test_radar_gui_validate_mimo import BPM, tdm


def met(masks, board):
    return metrics(parse_cfg(tdm(masks, tx=7)), board)


def test_az_tx_mask_follows_elevation_bit():
    assert az_tx_mask(0b010) == 0b101 and az_tx_mask(0b100) == 0b011


def test_tdm_slots_pairing():
    assert tdm_slots([1, 2, 4], False, 0b100) == (3, 2, [])      # ODS: TX1+TX2 azimuth, TX3 elevation
    assert tdm_slots([1, 4, 2], False, 0b010) == (3, 2, [])      # ISK: TX1+TX3 azimuth, TX2 elevation
    assert tdm_slots([1, 2], False, 0b100)[:2] == (2, 2)         # ODS TX1+TX2 only: both azimuth, no elevation slot
    assert tdm_slots([1, 2], False, 0b010)[:2] == (2, 1)         # ISK TX1+TX2: TX1 azimuth + TX2 elevation


@pytest.mark.parametrize("masks,board,n_az_tx", [([1, 2, 4], "IWR6843ODS", 2), ([1, 4, 2], "IWR6843", 2),
                                                 ([1, 2], "IWR6843ODS", 2), ([1, 2], "IWR6843", 1)])
def test_az_resolution_uses_board_pairing(masks, board, n_az_tx):
    m = met(masks, board)
    assert m.azimuth_res_deg == pytest.approx(math.degrees(2.0 / (n_az_tx * m.n_rx)))
    assert m.n_virtual == len(masks) * m.n_rx


def test_ods_metrics_note_names_ods_pairing():
    assert any("IWR6843ODS pairing" in n for n in met([1, 2, 4], "IWR6843ODS").notes)
    assert not any("IWR6843ODS pairing" in n for n in met([1, 4, 2], "IWR6843").notes)


def test_bpm_mask_accept_reject_and_ods_flag():
    isk = validate(parse_cfg(BPM), "IWR6843", "demo")
    ods = validate(parse_cfg(BPM), "IWR6843ODS", "demo")
    codes = lambda r: {(i.level, i.code) for i in r.issues}
    assert not any(c == "bpm_ods_pairing" for _, c in codes(isk))
    assert ("warning", "bpm_ods_pairing") in codes(ods) and ods.ok          # flagged, not an error
    assert tdm([3, 3], tx=7, base=BPM) != BPM
    for board in ("IWR6843", "IWR6843ODS"):                                 # mask 3 (TX1+TX2) is rejected on both: the demo drives TX1/TX3
        r = validate(parse_cfg(tdm([3, 3], tx=7, base=BPM)), board, "demo")
        assert ("error", "tx_pattern_invalid") in codes(r)


def test_ods_order_convention_1_2_4_clean_and_generate_order():
    r = validate(parse_cfg(tdm([1, 2, 4], tx=7)), "IWR6843ODS", "demo")
    assert not [i for i in r.issues if i.code == "tx_order_convention"]


def test_generate_default_az_pair_and_order():
    from radar_gui.cfg import generate
    kw = dict(max_range_m=5, max_velocity_ms=3)
    ods, isk = generate("IWR6843ODS", **kw), generate("IWR6843", **kw)
    assert ods.ok and isk.ok
    assert ods.targets["tx_mask"] == 3 and isk.targets["tx_mask"] == 5
    o = generate("IWR6843ODS", tx_mask=7, **kw).text
    i = generate("IWR6843", tx_mask=7, **kw).text
    masks = lambda t: [int(l.split()[-1]) for l in t.splitlines() if l.startswith("chirpCfg")]
    assert masks(o) == [1, 2, 4] and masks(i) == [1, 4, 2]
