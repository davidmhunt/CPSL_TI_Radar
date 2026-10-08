"""On-chip CFAR editing from the firmware descriptor (gui-35): schema, round trip over every shipped cfg, one seeded-bad cfg
per `cfar_` rule code, SAR/raw notes, generation and the HTTP endpoints. Hardware-free."""
import re

import pytest
from fastapi.testclient import TestClient

from radar_gui.app import create_app
from radar_gui.cfg import detection, generate, parse_cfg, validate
from radar_gui.cfg import firmware as fwmod
from radar_gui.cfg.detection import DetectionError
from radar_gui.sources import MockSource
from pathlib import Path

from test_radar_gui_cfg import SHIPPED, board_for

FIXTURES = sorted((Path(__file__).parent / "fixtures").rglob("*.cfg"))

CMDS = ("cfarCfg", "cfarFovCfg", "peakGrouping")


def base(fw, board):
    return fwmod.template_path(fwmod.get(fw), board).read_text()


def codes(text, board, fw):
    return {i.code: i.level for i in validate(parse_cfg(text), board, fw).issues if i.code.startswith("cfar_")}


def sub_line(text, cmd, repl, nth=0):
    """Replace the nth `cmd` line of `text` by `repl` (a callable on the token list)."""
    lines, seen = text.splitlines(), 0
    for i, ln in enumerate(lines):
        if ln.split("%", 1)[0].split()[:1] == [cmd]:
            if seen == nth:
                tok = ln.split("%", 1)[0].split()
                repl(tok)
                lines[i] = " ".join(tok)
                break
            seen += 1
    return "\n".join(lines) + "\n"


# --- descriptors ------------------------------------------------------------------------------------

def test_every_descriptor_is_valid_and_every_field_has_help_and_cite():
    for d in fwmod.load_all().values():
        assert fwmod.check_descriptor(d, d["id"]) == []
        det = d.get("detection")
        if det is None:
            assert d["detection_note"]
            continue
        for vid, v in det["variants"].items():
            assert v["level"] in detection.LEVELS
            for f in v["fields"]:
                assert f["help"] and f["cite"], (vid, f["key"])
    assert fwmod.get("demo")["detection"]["boards"] == {"IWR1443": "sdk2_14xx", "IWR1843": "sdk3_hwa",
                                                         "IWR6843": "sdk3_dsp", "IWR6843ODS": "sdk3_dsp"}


def test_check_detection_rejects_bad_blocks():
    d = fwmod.get("demo")
    bad = dict(d, detection=None)
    assert any("detection_note" in m for m in detection.check_detection(dict(bad, detection_note=""), list(d["templates"])))
    import copy
    x = copy.deepcopy(d)
    x["detection"]["variants"]["sdk3_hwa"]["rules"].append({"code": "cfar_nope"})
    assert any("cfar_nope" in m for m in detection.check_detection(x, list(d["templates"])))
    x = copy.deepcopy(d)
    del x["detection"]["variants"]["sdk3_hwa"]["fields"][0]["cite"]
    assert any("no cite" in m for m in detection.check_detection(x, list(d["templates"])))


def test_sar_and_raw_have_no_detection_and_say_why():
    for fw, board in (("iwr1843_sar_lvds", "IWR1843"), ("dca1000_raw", "IWR1443")):
        res = detection.describe(base(fw, board), board, fw)
        assert res["schema"] is None and res["values"] is None and not res["editable"] and res["note"]
        with pytest.raises(DetectionError):
            detection.apply(base(fw, board), {"range": {"mode": 0}}, fw, board)


def test_schema_shapes():
    s = detection.schema("demo", "IWR1843")
    assert s["directions"] == ["range", "doppler"] and s["fov"]["command"] == "cfarFovCfg"
    assert all(f["per_direction"] for f in s["fields"])
    s = detection.schema("demo", "IWR1443")
    assert s["directions"] == [] and s["fov"] is None and not any(f["per_direction"] for f in s["fields"])
    s = detection.schema("cascade_ddm", "AWR2243_CASCADE")
    assert s["fov"] is None and {f["key"] for f in s["fields"]} >= {"osKvalue", "isEnabled"}


# --- round trip over every shipped cfg ---------------------------------------------------------------

def _tokens(text):
    return [tuple(ln.split("%", 1)[0].split()) for ln in text.splitlines() if ln.split("%", 1)[0].split()[:1] and
            ln.split("%", 1)[0].split()[0] in CMDS]


def test_round_trip_over_every_shipped_cfarcfg_cfg():
    n = readonly = 0
    for p in SHIPPED + FIXTURES:
        text = p.read_text(errors="replace")
        if not parse_cfg(text).has("cfarCfg"):
            continue
        board = board_for(p)
        fw = fwmod.default_for(board)["id"]
        cur = detection.from_cfg(parse_cfg(text), fw, board)
        if not cur["editable"]:
            readonly += 1
            assert "edit the cfg text" in cur["reason"], p
            continue
        n += 1
        out = detection.apply(text, cur["values"], fw, board)
        assert out == text, p                                  # byte-identical, so the three commands are token-identical too
        assert _tokens(out) == _tokens(text)
        assert detection.apply(text, {}, fw, board) == text
    print(f"round trip: {n} editable cfgs, {readonly} read-only (per-subframe)")
    assert n >= 50 and readonly >= 1


# --- values: parse, edit, insert ---------------------------------------------------------------------

def test_from_cfg_and_edit_1843():
    text = base("demo", "IWR1843")
    cur = detection.from_cfg(text, "demo", "IWR1843")
    assert cur["editable"] and cur["values"]["range"]["mode"] == 2 and "thresholdDb" in cur["values"]["doppler"]
    out = detection.apply(text, {"range": {"thresholdDb": 12.345}, "doppler": {"mode": 1}}, "demo", "IWR1843")
    a, b = text.splitlines(), out.splitlines()
    assert len(a) == len(b) and sum(x != y for x, y in zip(a, b)) == 2
    assert any(l.startswith("cfarCfg -1 0 ") and " 12.35 " in l + " " for l in b)       # 2 decimals kept
    assert detection.from_cfg(out, "demo", "IWR1843")["values"]["doppler"]["mode"] == 1
    # manual FOV rewrites only the FOV lines; auto restores something auto-like
    out2 = detection.apply(out, {"fov": {"mode": "manual", "range": [0.5, 7.0]}}, "demo", "IWR1843")
    fov = detection.from_cfg(out2, "demo", "IWR1843")["values"]["fov"]
    assert fov["mode"] == "manual" and fov["range"] == [0.5, 7.0]
    out3 = detection.apply(out2, {"fov": {"mode": "auto"}}, "demo", "IWR1843")
    assert detection.from_cfg(out3, "demo", "IWR1843")["values"]["fov"]["mode"] == "auto"


def test_1443_threshold_is_integer_and_peak_grouping_is_shared():
    text = base("demo", "IWR1443")
    cur = detection.from_cfg(text, "demo", "IWR1443")["values"]
    assert set(cur) == {"shared"} and cur["shared"]["thresholdRaw"] == 1280
    out = detection.apply(text, {"shared": {"thresholdRaw": 2304.0, "pgEndIdx": 100}}, "demo", "IWR1443")
    assert any(l.startswith("cfarCfg 0 2 8 4 3 0 2304") and not l.split()[7].count(".") for l in out.splitlines())
    assert any(l.startswith("peakGrouping 1 1 1 1 100") for l in out.splitlines())
    with pytest.raises(DetectionError, match="whole number"):
        detection.apply(text, {"shared": {"thresholdRaw": 12.5}}, "demo", "IWR1443")


def test_cascade_edit_and_no_fov_line():
    text = base("cascade_ddm", "AWR2243_CASCADE")
    out = detection.apply(text, {"doppler": {"thresholdDb": 20, "osKvalue": 5}}, "cascade_ddm", "AWR2243_CASCADE")
    assert "cfarFovCfg" not in out
    assert detection.from_cfg(out, "cascade_ddm", "AWR2243_CASCADE")["values"]["doppler"]["osKvalue"] == 5
    with pytest.raises(DetectionError):
        detection.apply(text, {"fov": {"mode": "auto"}}, "cascade_ddm", "AWR2243_CASCADE")


def test_insert_missing_lines_before_sensorstart_and_keep_comments():
    text = base("demo", "IWR1843")
    stripped = "\n".join(l for l in text.splitlines() if not l.startswith(("cfarCfg", "cfarFovCfg"))) + "\n"
    assert "sensorStart" in stripped
    out = detection.apply(stripped, {"range": {"thresholdDb": 9}, "doppler": {"thresholdDb": 8}, "fov": {"mode": "auto"}},
                          "demo", "IWR1843")
    lines = out.splitlines()
    last = max(i for i, l in enumerate(lines) if l.startswith("sensorStart"))
    new = [i for i, l in enumerate(lines) if l.startswith(("cfarCfg", "cfarFovCfg"))]
    assert len(new) == 4 and all(i < last for i in new)
    assert codes(out, "IWR1843", "demo") == {}
    commented = text.replace("cfarCfg -1 0 ", "cfarCfg -1 0 ", 1).splitlines()
    i = next(i for i, l in enumerate(commented) if l.startswith("cfarCfg -1 0"))
    commented[i] += " % range cfar"
    out = detection.apply("\n".join(commented) + "\n", {"range": {"noiseWin": 6}}, "demo", "IWR1843")
    assert any(l.endswith("% range cfar") and " 6 " in l for l in out.splitlines())


def test_bad_values_and_readonly_subframes():
    text = base("demo", "IWR1843")
    for vals in ({"range": {"mode": 9}}, {"range": {"nope": 1}}, {"shared": {"mode": 1}}, {"range": {"cyclic": 2}},
                 {"range": {"noiseWin": "x"}}, {"fov": {"range": [1]}}, {"zzz": {}}):
        with pytest.raises(DetectionError):
            detection.apply(text, vals, "demo", "IWR1843")
    sub = text.replace("cfarCfg -1 0", "cfarCfg 0 0", 1)
    res = detection.describe(sub, "IWR1843", "demo")
    assert not res["editable"] and "subframe" in res["note"] and res["values"] is None and res["schema"]
    with pytest.raises(DetectionError, match="subframe"):
        detection.apply(sub, {}, "demo", "IWR1843")


# --- one seeded-bad cfg per rule code ----------------------------------------------------------------

def _f(name):
    return lambda t: None


SEEDED = {
    "cfar_args": ("demo", "IWR1843", lambda t: sub_line(t, "cfarCfg", lambda k: k.pop(), 0), "error"),
    "cfar_enum": ("demo", "IWR1843", lambda t: sub_line(t, "cfarCfg", lambda k: k.__setitem__(3, "7"), 0), "error"),
    "cfar_threshold_max": ("demo", "IWR1843", lambda t: sub_line(t, "cfarCfg", lambda k: k.__setitem__(8, "100.5"), 0), "error"),
    "cfar_guard_vs_bins": ("demo", "IWR1843", lambda t: sub_line(t, "cfarCfg", lambda k: k.__setitem__(4, "200"), 0), "warning"),
    "cfar_divshift_formula": ("demo", "IWR1843", lambda t: sub_line(t, "cfarCfg", lambda k: k.__setitem__(6, "6"), 0), "warning"),
    "cfar_fov_order": ("demo", "IWR1843", lambda t: sub_line(t, "cfarFovCfg", lambda k: k.__setitem__(3, "9"), 0), "error"),
    "cfar_fov_noop": ("demo", "IWR1843", lambda t: sub_line(t, "cfarFovCfg", lambda k: k.__setitem__(4, "900"), 0), "info"),
    "cfar_missing_direction": ("demo", "IWR1843", lambda t: "\n".join(
        l for l in t.splitlines() if not l.startswith("cfarCfg -1 1")) + "\n", "error"),
    "cfar_win2_invalid": ("demo", "IWR1843", lambda t: sub_line(t, "cfarCfg", lambda k: k.__setitem__(4, "2"), 0), "error"),
    "cfar_doppler_enabled": ("cascade_ddm", "AWR2243_CASCADE",
                             lambda t: sub_line(t, "cfarCfg", lambda k: k.__setitem__(12, "0"), 0), "error"),
    "cfar_doppler_os_mode": ("cascade_ddm", "AWR2243_CASCADE",
                             lambda t: sub_line(t, "cfarCfg", lambda k: k.__setitem__(3, "2"), 0), "error"),
    "cfar_doppler_os_guard0": ("cascade_ddm", "AWR2243_CASCADE",
                               lambda t: sub_line(t, "cfarCfg", lambda k: k.__setitem__(5, "2"), 0), "error"),
}


def _first_dir(t, board_cmd, d):
    return t


@pytest.mark.parametrize("code", sorted(SEEDED))
def test_seeded_bad_cfg_gives_the_rule(code):
    fw, board, mut, level = SEEDED[code]
    text = base(fw, board)
    if level != "info":
        assert code not in codes(text, board, fw)
    if code in ("cfar_doppler_enabled", "cfar_doppler_os_mode", "cfar_doppler_os_guard0"):
        # cascade template lists Doppler (dir 1) first
        pass
    got = codes(mut(text), board, fw)
    assert got.get(code) == level, (code, got)


def test_every_rule_code_is_seeded_and_the_templates_are_clean():
    used = {r["code"] for d in fwmod.load_all().values() for v in ((d.get("detection") or {}).get("variants") or {}).values()
            for r in v["rules"]}
    assert used == set(SEEDED) | {"cfar_fov_noop"} and used <= set(detection._RULES)
    for fw, board in (("demo", "IWR1443"), ("demo", "IWR1843"), ("demo", "IWR6843"), ("demo", "IWR6843ODS"),
                      ("cascade_ddm", "AWR2243_CASCADE")):
        assert codes(base(fw, board), board, fw) in ({}, {"cfar_fov_noop": "info"}), (fw, board)


def test_1443_rules_and_dsp_has_no_win2_rule():
    t = base("demo", "IWR1443")
    assert codes(sub_line(t, "cfarCfg", lambda k: k.__setitem__(2, "9"), 0), "IWR1443", "demo") == {"cfar_enum": "error"}
    assert codes(sub_line(t, "cfarCfg", lambda k: k.__setitem__(5, "5"), 0), "IWR1443", "demo") == {"cfar_divshift_formula": "warning"}
    t = base("demo", "IWR6843")
    mut = sub_line(t, "cfarCfg", lambda k: k.__setitem__(4, "2"), 0)
    assert "cfar_win2_invalid" not in codes(mut, "IWR6843", "demo")


# --- generation -------------------------------------------------------------------------------------

@pytest.mark.parametrize("board,fw", [("IWR1843", "demo"), ("IWR6843", "demo"), ("IWR1443", "demo"),
                                      ("AWR2243_CASCADE", "cascade_ddm")])
def test_generate_with_detection_values_passes_the_rules(board, fw):
    vals = {"shared": {"thresholdRaw": 1500}} if board == "IWR1443" else \
        {"range": {"thresholdDb": 14.25}, "doppler": {"thresholdDb": 11.5}}
    g = generate(board, {"max_range_m": 10 if board != "AWR2243_CASCADE" else 20, "max_velocity_ms": 3, "frame_rate_hz": 10,
                         "detection": vals}, firmware=fw)
    assert g.text, [i.message for i in g.report.issues]
    assert not [i for i in g.report.issues if i.code.startswith("cfar_") and i.level == "error"]
    cur = detection.from_cfg(g.text, fw, board)["values"]
    if board == "IWR1443":
        assert cur["shared"]["thresholdRaw"] == 1500 and re.search(r"^cfarCfg 0 2 8 4 3 0 1500$", g.text, re.M)
    else:
        assert cur["range"]["thresholdDb"] == 14.25 and cur["doppler"]["thresholdDb"] == 11.5
    bad = generate(board, {"max_range_m": 10, "max_velocity_ms": 3, "detection": {"range": {"mode": 99}}}, firmware=fw)
    assert not bad.ok and any(i.code == "bad_detection" for i in bad.report.issues)


def test_threshold_alias_keys_still_work():
    g = generate("IWR1843", {"max_range_m": 10, "max_velocity_ms": 3, "cfar_range_db": 21, "cfar_doppler_db": 22})
    cur = detection.from_cfg(g.text, "demo", "IWR1843")["values"]
    assert cur["range"]["thresholdDb"] == 21 and cur["doppler"]["thresholdDb"] == 22


def test_apply_params_detection_key():
    from radar_gui.cfg import apply_params
    text = base("demo", "IWR1843")
    out = apply_params(text, {"detection": {"range": {"thresholdDb": 18}}}, board="IWR1843", firmware="demo")
    assert detection.from_cfg(out, "demo", "IWR1843")["values"]["range"]["thresholdDb"] == 18


# --- HTTP ------------------------------------------------------------------------------------------

@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("RADAR_GUI_USER_CFG_DIR", str(tmp_path / "user"))
    return TestClient(create_app(MockSource()))


def test_endpoints_carry_detection(client):
    text = base("demo", "IWR1843")
    a = client.post("/api/cfg/analyze", json={"board": "IWR1843", "cfg_text": text}).json()
    d = a["detection"]
    assert d["editable"] and d["schema"]["variant"] == "sdk3_hwa" and d["values"]["range"]["noiseWin"] and d["context"]["range_bins"]
    r = client.post("/api/cfg/detection", json={"board": "IWR1843", "base_cfg_text": text,
                                                  "values": {"range": {"thresholdDb": 30}}}).json()
    assert r["source"] == "detection" and r["detection"]["values"]["range"]["thresholdDb"] == 30 and r["params"]
    assert r["report"]["issues"] == r["issues"]
    bad = client.post("/api/cfg/detection", json={"board": "IWR1843", "base_cfg_text": text,
                                                    "values": {"range": {"mode": 9}}}).json()
    assert not bad["ok"] and bad["issues"][0]["code"] == "detection" and bad["detection"]["editable"]
    p = client.post("/api/cfg/params", json={"board": "IWR1843", "base_cfg_text": text,
                                              "params": {"detection": {"doppler": {"mode": 1}}}}).json()
    assert p["detection"]["values"]["doppler"]["mode"] == 1
    g = client.post("/api/cfg/generate", json={"board": "IWR1843", "targets": {"max_range_m": 10, "max_velocity_ms": 3}}).json()
    assert g["detection"]["schema"]
    sar = client.post("/api/cfg/analyze", json={"board": "IWR1843", "firmware": "iwr1843_sar_lvds",
                                                  "cfg_text": base("iwr1843_sar_lvds", "IWR1843")}).json()["detection"]
    assert sar["schema"] is None and "no on-chip detection" in sar["note"]
    nope = client.post("/api/cfg/detection", json={"board": "IWR1843", "firmware": "iwr1843_sar_lvds",
                                                     "base_cfg_text": base("iwr1843_sar_lvds", "IWR1843"), "values": {}}).json()
    assert not nope["ok"]
