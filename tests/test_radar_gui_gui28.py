"""gui-28: raw-ADC firmware has no lvdsStreamCfg group (the GUI explains why); JS guards are present."""
from pathlib import Path

from radar_gui.cfg import params_from_cfg, parse_cfg
from radar_gui.cfg import firmware as fwmod

WEB = Path(__file__).resolve().parents[1] / "radar_gui" / "web"


def test_raw_template_has_no_lvds_stream_so_group_hidden_with_note():
    for board in ("IWR1443",):   # gui-30: dca1000_raw is IWR1443-only
        import json; rel = json.loads((fwmod.FIRMWARE_DIR / "dca1000_raw.json").read_text())["templates"][board]
        text = (fwmod.CONFIG_DIR / rel).read_text()
        assert "lvdsStreamCfg" not in text and "testFmkCfg" in text
        assert not params_from_cfg(parse_cfg(text), board).get("lvds_stream")
    assert 'id="lvdsNote"' in (WEB / "index.html").read_text()
    assert "lvdsNote" in (WEB / "js" / "cfg.js").read_text()


def test_live_canvas_skips_zero_size_and_reseed_on_board_change():
    v = (WEB / "js" / "views.js").read_text()
    assert "if (r.width < 2 || r.height < 2) return null;" in v and v.count("if (!f) return;") == 4
    c = (WEB / "js" / "cfg.js").read_text()
    assert c.count("reseedDirect()") >= 3 and "C.tblStale" in c
