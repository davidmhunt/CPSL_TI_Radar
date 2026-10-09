"""gui-39 Step 3: the IWR1843 stock demo has no bpmCfg command (SDK 3.6 xwr18xx mmw_cli.c; the xwr68xx demo has it).
demo.json lists it under cfg_rules.IWR1843.skip_commands and sets mimo.boards.IWR1843.bpm false; the generator never emits
it for the 1843, and the validator warns when a loaded cfg carries the line (the driver skips it: `cli [skip] bpmCfg`)."""
import json
from pathlib import Path

from radar_gui.cfg import firmware as fwmod
from radar_gui.cfg import generate, parse_cfg, parse_cfg_file, validate

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "CPSL_TI_Radar_cpp" / "config" / "firmware" / "demo.json"
ICA = ROOT / "CPSL_TI_Radar_cpp" / "config" / "radar" / "IWR1843" / "demo" / "IcaRAus.cfg"
T = {"max_range_m": 10, "max_velocity_ms": 3}


def test_descriptor_data():
    d = json.loads(DEMO.read_text())
    assert d["cfg_rules"]["IWR1843"]["skip_commands"] == ["bpmCfg"]
    assert d["cfg_rules"]["IWR1843"]["required_commands"] == ["calibData"]          # the existing rule is untouched
    b = d["mimo"]["boards"]["IWR1843"]
    assert b["bpm"] is False and "mmw_cli.c" in b["source"]
    assert d["mimo"]["bpm"] is True and "IWR6843" not in d["mimo"]["boards"]        # the xwr68xx demo keeps BPM
    assert fwmod.cfg_rules("IWR1843", "demo")["skip_commands"] == ["bpmCfg"]
    assert fwmod.cfg_rules("IWR6843", "demo")["skip_commands"] == []


def test_generator_never_emits_bpmcfg_on_the_1843_demo():
    g = generate("IWR1843", T, firmware="demo")
    assert g.ok and "bpmCfg" not in g.text
    bad = generate("IWR1843", {**T, "bpm": True}, firmware="demo")
    assert not bad.ok and [i.code for i in bad.report.issues][:1] == ["bpm_unsupported"]
    assert generate("IWR6843", {**T, "bpm": True}, firmware="demo").ok               # still supported where the demo has it


def test_generator_drops_skip_listed_template_lines(monkeypatch):
    real = fwmod.cfg_rules
    monkeypatch.setattr(fwmod, "cfg_rules", lambda b, f=None: {**real(b, f), "skip_commands": [*real(b, f)["skip_commands"], "lowPower"]})
    assert "lowPower" not in generate("IWR1843", T, firmware="demo").text


def test_validator_warns_about_a_skip_listed_line():
    r = validate(parse_cfg_file(str(ICA)), "IWR1843", "demo")
    w = [i for i in r.issues if i.code == "skipped_bpmCfg"]
    assert len(w) == 1 and w[0].level == "warning" and "not sent" in w[0].message and "no such command" in w[0].message
    assert not [i for i in r.issues if i.code == "skipped_bpmCfg" and i.level == "error"]
    clean = "\n".join(l for l in ICA.read_text().splitlines() if not l.startswith("bpmCfg"))
    assert not [i for i in validate(parse_cfg(clean), "IWR1843", "demo").issues if i.code == "skipped_bpmCfg"]
    assert not [i for i in validate(parse_cfg_file(str(ICA)), "IWR6843", "demo").issues if i.code == "skipped_bpmCfg"]
