"""gui-39 Step 1: bench-session-1 follow-ups in the Radar / Configure tabs: list refresh on every show, "Open in Radar" wording,
firmware-identify probes are not failures, and user .cfg files without a system JSON are listed (greyed) in the Radar tab."""
import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from radar_gui.app import create_app
from radar_gui.driver import DriverManager, first_fail
from radar_gui.sources import MockSource

WEB = Path(__file__).resolve().parent.parent / "radar_gui" / "web"
FAKE = str(Path(__file__).parent / "fakes" / "fake_driver.py")


def js(name):
    return (WEB / "js" / name).read_text()


def fn_body(src, head):
    i = src.index(head)
    return src[i:src.index("\n}\n", i)]


# ---- A1 wording ----
def test_open_in_radar_wording():
    assert "Open in Radar" in js("cfg.js") and "Open in Run" not in js("cfg.js")
    assert "Open in Run" not in js("main.js")
    for f in WEB.rglob("*.js"):
        assert not re.search(r"\bRun tab\b", f.read_text()), f


# ---- A2 refresh ----
def test_show_functions_reload_their_lists():
    run = fn_body(js("run.js"), "export function showRun()")
    assert re.search(r"if \(R\.ready\) \{[^}]*loadData\(\)", run)          # on every show, not only the first
    cfg = js("cfg.js")
    assert re.search(r"export function showConfigure\(\) \{[^\n]*else loadList\(\)", cfg)
    html = (WEB / "index.html").read_text()
    assert 'id="rRefresh"' in html and 'id="cRefresh"' in html
    assert "$('rRefresh').onclick" in js("run.js") and "$('cRefresh').onclick" in cfg


def test_reloads_keep_the_selection():
    # Radar: fixSpec only resets a selection that vanished; Configure: loadList restores the picker's value
    assert "!D.configs.some(c => c.path === spec.config)" in js("session.js")
    assert "const keep = $('cLoad').value" in js("cfg.js") and "$('cLoad').value = keep" in js("cfg.js")


# ---- A4 probe ----
PROBE_LINES = [
    "cli [id] version -> DONE (4 ms)",
    'cli [id] sarStats -> ERROR (3 ms) "sarStats not recognized as a CLI command"',
    "cli [1/3] sensorStop -> DONE (2 ms)",
]


def test_probe_error_is_not_first_fail():
    m = DriverManager(emit=lambda e: None)
    for ln in PROBE_LINES:
        m._line(ln)
    probe = next(e for e in m.cli if e["cmd"] == "sarStats")
    assert probe["verdict"] == "ERROR" and probe["probe"] is True and probe["tag"] == "id"
    assert not any(e["probe"] for e in m.cli if e["cmd"] == "sensorStop")
    assert m.status()["cli_first_fail"] is None and first_fail(m.cli) is None
    m._line('cli [2/3] foo -> ERROR (1 ms) "Error -1"')   # a real cfg failure after the probe still is one
    assert first_fail(m.cli) == next(e["seq"] for e in m.cli if e["cmd"] == "foo")


def test_cli_panel_renders_probe_not_error():
    src = js("cli_panel.js")
    assert "const isProbe" in src and "firmware probe" in src
    assert re.search(r"const bad = e => !isProbe\(e\)", src)   # a probe row is never "bad" / first failure
    assert "setFirmware" in js("run.js")                        # the outcome comes from the driver's firmware verdict


# ---- Q1 orphan cfgs ----
def test_orphan_user_cfgs_are_listed(tmp_path):
    user, system = tmp_path / "user", tmp_path / "system"
    user.mkdir(); system.mkdir()
    doc = {"schema_version": 2, "board": "IWR1843", "firmware": "demo", "radar_cfg": "with_json.cfg", "cli": {"port": "/dev/ttyACM0"}}
    (user / "with_json.cfg").write_text("% a\n"); (user / "with_json.json").write_text(json.dumps(doc))
    (user / "lonely.cfg").write_text("% b\n")
    # a JSON whose name differs from the cfg it references still claims that cfg
    (user / "renamed.json").write_text(json.dumps({**doc, "radar_cfg": "other.cfg"})); (user / "other.cfg").write_text("% c\n")
    with TestClient(create_app(MockSource(rate_hz=5), user_cfg_dir=user, system_cfg_dir=system, driver_bin=FAKE, run_root=tmp_path / "runs")) as c:
        j = c.get("/api/driver/configs").json()
    assert [o["name"] for o in j["orphans"]] == ["lonely.cfg"]
    assert j["orphans"][0]["id"] == "user:lonely.cfg"
    assert {x["name"] for x in j["configs"]} == {"with_json", "renamed"}


def test_orphan_ui_wiring():
    run, main = js("run.js"), js("main.js")
    assert "cfg only, no system JSON" in run and "Open in Configure" in run
    assert "open-in-configure" in run and "open-in-configure" in main and "openInConfigure" in js("cfg.js")


def test_save_button_does_not_pass_click_event_as_overwrite():
    """Regression (#97): `onclick = save` sent the MouseEvent as `overwrite` -> 422 'valid boolean'."""
    src = js("cfg.js")
    assert re.search(r"\$\('sSave'\)\.onclick\s*=\s*\(\)\s*=>\s*save\(false\)", src)
    assert not re.search(r"\.onclick\s*=\s*save\s*;", src)


# ---- gui-41 A/B ----
def test_gui41_save_message_clears_on_reload_and_selection_change():
    run = js("run.js")
    assert "function clearSaveMsg()" in run
    body = fn_body(run, "export function showRun()")
    assert "clearSaveMsg(); refresh(); loadData()" in body                # re-show
    assert "$('rRefresh').onclick = () => { clearSaveMsg();" in body      # Refresh
    assert "on('rCfg', e => { clearSaveMsg();" in body and "on('rBoard', e => { clearSaveMsg();" in body
    # a save / add-firmware still writes its own fresh message after the reload
    assert "Saved ${res.j.path}" in run and "Added firmware" in run


def test_gui41_reconfigure_confirm_guard_and_skip_bypass():
    s = js("session.js")
    g = fn_body(s, "export async function startSession(")
    assert "onceBoard() && cfgSentHere(specBoard()) && !body.skip_configure" in g
    assert "accepts a cfg once per power-up. Power-cycle it first, or it will not start. Continue?" in g
    assert g.index("confirm(") < g.index("api('/api/driver/start'")      # asked before anything is sent
    assert "if (skip && onceBoard() && skipSupported()) body.skip_configure = true" in s   # skip on -> no prompt
