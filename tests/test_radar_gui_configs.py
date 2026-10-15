"""radar-40: Configs tab backend (promote / delete / list). Every test works on a TEMP COPY of CPSL_TI_Radar_cpp/config
(system, radar, boards, firmware, limits, README, moved_paths) with its own config/user: the real tree is only read."""
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from radar_gui import configs_api as ca
from radar_gui import sysjson

REAL = Path(__file__).resolve().parents[1] / "CPSL_TI_Radar_cpp" / "config"
GATE = "IWR1843_iwr1843_sar_lvds_SAR_2ms_fmt2"


def digest(root: Path) -> dict:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*"))
            if p.is_file() and not p.is_symlink()}


class FakeMgr:
    def __init__(self):
        self.state, self.config, self.session_json = "idle", None, None

    def status(self, log=True):
        return {"state": self.state, "config": self.config, "session_json": self.session_json}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.delenv("RADAR_GUI_SHIPPED_WRITES", raising=False)
    cfg = tmp_path / "config"
    cfg.mkdir()
    for d in ("system", "radar", "boards", "firmware", "limits", "archive"):
        shutil.copytree(REAL / d, cfg / d)
    for f in ("README.md", "moved_paths.json"):
        shutil.copy2(REAL / f, cfg / f)
    user = cfg / "user"
    user.mkdir()
    # a saved setup derived from a shipped one (never read from the real config/user/)
    src = json.loads((REAL / "system" / f"{GATE}.json").read_text())
    src["radar_cfg"] = "scratch.cfg"
    src["serial_stream"] = {"enabled": False, "port": "/dev/ttyACM1"}
    (user / "scratch.json").write_text(sysjson.dumps(src))
    shutil.copyfile(REAL / "radar" / "IWR1843" / "iwr1843_sar_lvds" / "SAR_2ms_fmt2.cfg", user / "scratch.cfg")
    (user / "scratch.cfg").write_text((user / "scratch.cfg").read_text() + "% scratch marker\n")
    mgr = FakeMgr()
    app = FastAPI()
    app.include_router(ca.make_router(mgr, user, cfg, driver_bin=tmp_path / "no_such_driver"))
    t = ca.Tree(cfg, user)
    return TestClient(app), cfg, user, mgr, t


def post(c, path, **body):
    return c.post(path, json=body)


def test_listing_shape(env):
    c, cfg, user, mgr, t = env
    j = c.get("/api/configs").json()
    by = {i["id"]: i for i in j["configs"]}
    assert len([i for i in j["configs"] if i["group"] == "shipped" and i["kind"] == "radar_cfg"]) == len(list((cfg / "radar").glob("*/*/*.cfg")))
    assert len([i for i in j["configs"] if i["group"] == "shipped" and i["kind"] == "system_json"]) == len(list((cfg / "system").glob("*.json")))
    s = by["user:scratch.json"]
    assert s["board"] == "IWR1843_SAR" and s["gui_board"] == "IWR1843" and s["firmware"] == "iwr1843_sar_lvds"
    assert s["cfg"] == "user:scratch.cfg" and s["cfg_exists"] and s["outputs"] == ["DCA1000"] and not s["in_use"]
    cf = by["shipped:radar/IWR1843/iwr1843_sar_lvds/SAR_2ms_fmt2.cfg"]
    assert cf["referenced_by"] == [f"shipped:system/{GATE}.json"] and cf["board"] == "IWR1843"
    assert by["user:scratch.cfg"]["referenced_by"] == ["user:scratch.json"]
    assert j["git"]["available"] is False and j["shipped_writes"]["enabled"]
    # a firmware template cfg is reported as such
    assert any(i.get("template_of") for i in j["configs"] if i["kind"] == "radar_cfg")


def test_file_view(env):
    c, *_ = env
    r = c.get("/api/configs/file", params={"id": "user:scratch.cfg"}).json()
    assert "scratch marker" in r["text"] and r["kind"] == "radar_cfg"
    assert c.get("/api/configs/file", params={"id": "user:nope.cfg"}).status_code == 404


BAD_IDS = ["user:../x.json", "user:/etc/passwd", "user:%2e%2e%2fx.json", "user:a/b.json", "shipped:../system/x.json",
           "shipped:boards/IWR1843.json", "shipped:archive/x.cfg", "shipped:limits/x.json", "shipped:system/../README.md",
           "shipped:system/README.md", "shipped:system/moved_paths.json", "user:scratch.json.bak", "user:scratch.txt",
           "shipped:radar/IWR1843/iwr1843_sar_lvds/SAR_2ms_fmt2.json", "shipped:system/x.cfg", "shipped:radar/a/b.cfg",
           "other:scratch.json", "scratch.json", "user:", ":x.json", "user:..", "shipped:radar/IWR1843/../x/y.cfg"]


@pytest.mark.parametrize("id_", BAD_IDS)
def test_traversal_ids_refused_everywhere_without_change(env, id_):
    c, cfg, user, mgr, t = env
    before = digest(cfg)
    assert 400 <= c.get("/api/configs/file", params={"id": id_}).status_code < 500
    assert 400 <= post(c, "/api/configs/promote", id=id_, confirm_overwrite=True).status_code < 500
    assert 400 <= post(c, "/api/configs/delete", ids=[id_], confirm=True, confirm_shipped=True, force_referenced=True).status_code < 500
    assert digest(cfg) == before


def test_symlinks_not_addressable(env, tmp_path):
    c, cfg, user, mgr, t = env
    out = tmp_path / "outside.json"
    out.write_text("{}")
    (user / "link.json").symlink_to(out)
    (cfg / "system" / "Link_x.json").symlink_to(out)
    (cfg / "radar" / "IWR1843" / "evil").symlink_to(tmp_path)   # a folder symlink
    before = digest(cfg)
    for id_ in ("user:link.json", "shipped:system/Link_x.json", "shipped:radar/IWR1843/evil/outside.json",
                "shipped:radar/IWR1843/evil/x.cfg"):
        assert 400 <= c.get("/api/configs/file", params={"id": id_}).status_code < 500
        assert 400 <= post(c, "/api/configs/delete", ids=[id_], confirm=True, confirm_shipped=True).status_code < 500
    assert out.exists() and digest(cfg) == before
    ids = {i["id"] for i in c.get("/api/configs").json()["configs"]}
    assert "user:link.json" not in ids and "shipped:system/Link_x.json" not in ids


def _readme_rows(cfg):
    return {m.group(1): None for m in re.finditer(r"^\| \[`([^`]+\.json)`\]\(system/", (cfg / "README.md").read_text(), re.M)}


def test_promote_dry_run_writes_nothing(env):
    c, cfg, user, mgr, t = env
    before = digest(cfg)
    j = post(c, "/api/configs/promote?dry=1", id="user:scratch.json").json()
    assert j["dry"] and j["would_replace"] == []
    assert j["would_write"] == ["shipped:radar/IWR1843/iwr1843_sar_lvds/scratch.cfg",
                                "shipped:system/IWR1843_iwr1843_sar_lvds_scratch.json"]
    assert j["json"]["radar_cfg"] == "../radar/IWR1843/iwr1843_sar_lvds/scratch.cfg"
    assert digest(cfg) == before


def test_promote_creates_both_files_readme_row_and_tree_rules(env):
    c, cfg, user, mgr, t = env
    r = post(c, "/api/configs/promote", id="user:scratch.json", note="scratch 2 ms test setup")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["result"] == "created" and j["readme_updated"] and j["backups"] == []
    cfgf = cfg / "radar" / "IWR1843" / "iwr1843_sar_lvds" / "scratch.cfg"
    jsf = cfg / "system" / "IWR1843_iwr1843_sar_lvds_scratch.json"
    assert cfgf.read_bytes() == (user / "scratch.cfg").read_bytes()          # byte-identical
    doc = json.loads(jsf.read_text())
    src = json.loads((user / "scratch.json").read_text())
    assert doc["radar_cfg"] == "../radar/IWR1843/iwr1843_sar_lvds/scratch.cfg"
    assert "port" not in doc["serial_stream"] and src["serial_stream"]["port"] == "/dev/ttyACM1"   # dropped, source kept
    assert list(doc) == list(src) and jsf.read_text() == sysjson.dumps(doc)    # key order and format
    assert {k: v for k, v in doc.items() if k not in ("radar_cfg", "serial_stream")} == \
           {k: v for k, v in src.items() if k not in ("radar_cfg", "serial_stream")}
    # same shape as the shipped sibling: key sets equal
    sib = json.loads((cfg / "system" / f"{GATE}.json").read_text())
    assert list(doc) == list(sib) and doc["serial_stream"] == sib["serial_stream"]
    # the tree rules the real tests enforce, on the temp tree
    rows = {m.group(1): (m.group(3), m.group(4), m.group(5)) for m in re.finditer(
        r"^\| \[`([^`]+\.json)`\]\(system/([^)]+)\) \| ([^|]+?) \| ([^|]+?) \| ([^|]+?) \|", (cfg / "README.md").read_text(), re.M)}
    assert sorted(rows) == sorted(p.name for p in (cfg / "system").glob("*.json"))
    assert rows[jsf.name][:2] == ("IWR1843_SAR", "iwr1843_sar_lvds") and rows[jsf.name][2] == "DCA1000"
    assert "scratch 2 ms test setup" in (cfg / "README.md").read_text()
    assert ca.name_pattern(t).match(jsf.name)
    assert (jsf.parent / doc["radar_cfg"]).resolve() == cfgf.resolve()
    # sorted position: the row sits between its neighbours
    names = [m.group(1) for m in re.finditer(r"^\| \[`([^`]+\.json)`\]\(system/", (cfg / "README.md").read_text(), re.M)]
    assert names == sorted(names)
    # untouched bytes elsewhere in the README
    old, new = (REAL / "README.md").read_text().splitlines(), (cfg / "README.md").read_text().splitlines()
    assert [x for x in new if x not in old] and len(new) == len(old) + 1 and set(old) <= set(new)
    # user files untouched
    assert (user / "scratch.json").exists() and (user / "scratch.cfg").exists()


def test_promote_overwrite_needs_confirm_and_backs_up(env):
    c, cfg, user, mgr, t = env
    assert post(c, "/api/configs/promote", id="user:scratch.json").status_code == 200
    jsf = cfg / "system" / "IWR1843_iwr1843_sar_lvds_scratch.json"
    cfgf = cfg / "radar" / "IWR1843" / "iwr1843_sar_lvds" / "scratch.cfg"
    old_json, old_cfg = jsf.read_bytes(), cfgf.read_bytes()
    (user / "scratch.cfg").write_text((user / "scratch.cfg").read_text() + "% second\n")
    before = digest(cfg)
    r = post(c, "/api/configs/promote", id="user:scratch.json")
    assert r.status_code == 409
    d = r.json()["detail"]
    assert sorted(d["exists"]) == ["shipped:radar/IWR1843/iwr1843_sar_lvds/scratch.cfg",
                                   "shipped:system/IWR1843_iwr1843_sar_lvds_scratch.json"]
    assert digest(cfg) == before                                                # nothing changed, no backup dir
    r = post(c, "/api/configs/promote", id="user:scratch.json", confirm_overwrite=True)
    assert r.status_code == 200 and r.json()["result"] == "overwritten"
    assert cfgf.read_bytes() == (user / "scratch.cfg").read_bytes() != old_cfg
    bdir = [p for p in (user / ".promote_backups").iterdir()]
    assert len(bdir) == 1 and bdir[0].name.endswith("_scratch")
    assert (bdir[0] / "radar/IWR1843/iwr1843_sar_lvds/scratch.cfg").read_bytes() == old_cfg
    assert (bdir[0] / "system/IWR1843_iwr1843_sar_lvds_scratch.json").read_bytes() == old_json
    # README still has exactly one row for the file
    assert (cfg / "README.md").read_text().count("(system/IWR1843_iwr1843_sar_lvds_scratch.json)") == 1


def test_overwrite_lists_other_jsons_that_reference_the_cfg(env):
    c, cfg, user, mgr, t = env
    # a user setup named like an existing shipped cfg: SAR_2ms_fmt2 is referenced by the shipped fmt2 JSON
    shutil.copyfile(user / "scratch.json", user / "SAR_2ms_fmt2.json")
    shutil.copyfile(user / "scratch.cfg", user / "SAR_2ms_fmt2.cfg")
    d = json.loads((user / "SAR_2ms_fmt2.json").read_text())
    d["radar_cfg"] = "SAR_2ms_fmt2.cfg"
    (user / "SAR_2ms_fmt2.json").write_text(sysjson.dumps(d))
    other = cfg / "system" / f"{GATE}_front.json"                     # a second shipped JSON on the same cfg, not replaced
    shutil.copyfile(cfg / "system" / f"{GATE}.json", other)
    j = post(c, "/api/configs/promote?dry=1", id="user:SAR_2ms_fmt2.json").json()
    assert sorted(j["would_replace"]) == [f"shipped:radar/IWR1843/iwr1843_sar_lvds/SAR_2ms_fmt2.cfg",
                                          f"shipped:system/{GATE}.json"]
    assert j["referenced_by"] == [f"shipped:system/{GATE}_front.json"]
    r = post(c, "/api/configs/promote", id="user:SAR_2ms_fmt2.json")
    assert r.status_code == 409 and r.json()["detail"]["referenced_by"] == [f"shipped:system/{GATE}_front.json"]


def test_promote_refusals(env, tmp_path):
    c, cfg, user, mgr, t = env
    # legacy: no firmware
    d = json.loads((user / "scratch.json").read_text())
    legacy = {k: v for k, v in d.items() if k != "firmware"}
    snap = lambda: {k: v for k, v in digest(cfg).items() if not k.startswith("user/")}   # noqa: E731
    before = snap()
    (user / "legacy.json").write_text(sysjson.dumps(legacy))
    shutil.copyfile(user / "scratch.cfg", user / "legacy.cfg")
    r = post(c, "/api/configs/promote", id="user:legacy.json")
    assert r.status_code == 422 and "firmware" in r.text
    # name that would break the shipped pattern
    assert post(c, "/api/configs/promote", id="user:scratch.json", name="a-b").status_code == 422
    assert post(c, "/api/configs/promote", id="user:scratch.json", name="a.b").status_code == 422
    assert post(c, "/api/configs/promote", id="user:scratch.json", name="../x").status_code == 422
    # source must be a user JSON
    assert post(c, "/api/configs/promote", id="shipped:system/" + GATE + ".json").status_code == 422
    assert post(c, "/api/configs/promote", id="user:scratch.cfg").status_code == 422
    # missing cfg / cfg outside the user dir
    d2 = dict(d, radar_cfg="gone.cfg")
    (user / "nocfg.json").write_text(sysjson.dumps(d2))
    assert post(c, "/api/configs/promote", id="user:nocfg.json").status_code == 422
    d3 = dict(d, radar_cfg="/etc/hostname")
    (user / "abs.json").write_text(sysjson.dumps(d3))
    assert post(c, "/api/configs/promote", id="user:abs.json").status_code == 422
    # schema
    (user / "v1.json").write_text(json.dumps(dict(d, schema_version=1)))
    assert post(c, "/api/configs/promote", id="user:v1.json").status_code == 422
    assert snap() == before and not (user / ".promote_backups").exists()


def test_promote_name_override(env):
    c, cfg, user, mgr, t = env
    r = post(c, "/api/configs/promote", id="user:scratch.json", name="ScratchTwo")
    assert r.status_code == 200
    assert (cfg / "system" / "IWR1843_iwr1843_sar_lvds_ScratchTwo.json").is_file()
    assert (cfg / "radar" / "IWR1843" / "iwr1843_sar_lvds" / "ScratchTwo.cfg").is_file()


def test_live_session_guard(env):
    c, cfg, user, mgr, t = env
    mgr.state, mgr.config = "running", str(user / "scratch.json")
    before = digest(cfg)
    j = c.get("/api/configs").json()
    assert {i["id"] for i in j["configs"] if i["in_use"]} == {"user:scratch.json", "user:scratch.cfg"}   # json + the cfg it names
    assert post(c, "/api/configs/promote", id="user:scratch.json").status_code == 409
    assert post(c, "/api/configs/delete", ids=["user:scratch.json"], confirm=True).status_code == 409
    assert post(c, "/api/configs/delete", ids=["user:scratch.cfg"], confirm=True, force_referenced=True).status_code == 409
    assert digest(cfg) == before
    # a running session on a shipped target blocks the overwrite
    mgr.state = "idle"
    assert post(c, "/api/configs/promote", id="user:scratch.json").status_code == 200
    mgr.state, mgr.config = "running", str(cfg / "system" / "IWR1843_iwr1843_sar_lvds_scratch.json")
    r = post(c, "/api/configs/promote", id="user:scratch.json", confirm_overwrite=True)
    assert r.status_code == 409 and "in use" in r.text
    assert post(c, "/api/configs/delete", ids=["shipped:system/IWR1843_iwr1843_sar_lvds_scratch.json"],
                confirm=True, confirm_shipped=True).status_code == 409
    mgr.state = "exited"
    assert post(c, "/api/configs/delete", ids=["shipped:system/IWR1843_iwr1843_sar_lvds_scratch.json"],
                confirm=True, confirm_shipped=True).status_code == 200


def test_delete_user_goes_to_trash(env):
    c, cfg, user, mgr, t = env
    assert post(c, "/api/configs/delete", ids=["user:scratch.json"]).status_code == 422   # no confirm
    assert (user / "scratch.json").exists()
    r = post(c, "/api/configs/delete", ids=["user:scratch.json"], confirm=True)
    assert r.status_code == 200, r.text
    res = r.json()["results"][0]
    assert res["action"] == "trashed" and not (user / "scratch.json").exists()
    trashed = Path(res["to"])
    assert trashed.is_file() and trashed.parent.parent == user / ".trash"
    assert json.loads(trashed.read_text())["firmware"] == "iwr1843_sar_lvds"


def test_delete_with_cfg_only_when_unreferenced(env):
    c, cfg, user, mgr, t = env
    shutil.copyfile(user / "scratch.json", user / "second.json")           # also references scratch.cfg
    r = post(c, "/api/configs/delete", ids=["user:scratch.json"], confirm=True, with_cfg=True)
    assert r.status_code == 200 and (user / "scratch.cfg").exists()         # second.json still uses it
    r = post(c, "/api/configs/delete", ids=["user:second.json"], confirm=True, with_cfg=True)
    assert r.status_code == 200 and not (user / "scratch.cfg").exists()
    assert {x["id"] for x in r.json()["results"]} == {"user:second.json", "user:scratch.cfg"}


def test_delete_cfg_still_referenced_needs_force(env):
    c, cfg, user, mgr, t = env
    r = post(c, "/api/configs/delete", ids=["user:scratch.cfg"], confirm=True)
    assert r.status_code == 409 and r.json()["detail"]["referenced_by"] == {"user:scratch.cfg": ["user:scratch.json"]}
    assert (user / "scratch.cfg").exists()
    assert post(c, "/api/configs/delete", ids=["user:scratch.cfg"], confirm=True, force_referenced=True).status_code == 200


def promoted(c):
    assert post(c, "/api/configs/promote", id="user:scratch.json").status_code == 200
    return ["shipped:system/IWR1843_iwr1843_sar_lvds_scratch.json"], "shipped:radar/IWR1843/iwr1843_sar_lvds/scratch.cfg"


def test_delete_shipped_needs_both_confirms_and_restores_tree(env):
    c, cfg, user, mgr, t = env
    orig = digest(cfg)
    js, cfgid = promoted(c)
    assert digest(cfg) != orig
    assert post(c, "/api/configs/delete", ids=js, confirm=True).status_code == 422          # no confirm_shipped
    assert post(c, "/api/configs/delete", ids=js, confirm_shipped=True).status_code == 422  # no confirm
    assert (cfg / "system" / "IWR1843_iwr1843_sar_lvds_scratch.json").exists()
    r = post(c, "/api/configs/delete", ids=js, confirm=True, confirm_shipped=True, with_cfg=True)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["readme_updated"] and {x["id"] for x in j["results"]} == {js[0], cfgid}
    assert all(x["action"] == "removed" and "git status unavailable" in x["restore"] for x in j["results"])   # temp tree: no repo
    after = digest(cfg)
    gone = {k for k in after if k.startswith(".")}
    assert not gone
    # the shipped tree and README are exactly as before; only config/user differs (backups none, scratch files kept)
    assert {k: v for k, v in after.items() if not k.startswith("user/")} == {k: v for k, v in orig.items() if not k.startswith("user/")}


def test_delete_shipped_cfg_referenced_refused_without_force(env):
    c, cfg, user, mgr, t = env
    cid = "shipped:radar/IWR1843/iwr1843_sar_lvds/SAR_2ms.cfg"
    # SAR_2ms_fmt1.cfg is not a template; SAR_2ms.cfg? pick one referenced and not a template
    items = {i["id"]: i for i in c.get("/api/configs").json()["configs"]}
    cid = next(k for k, v in items.items() if v["kind"] == "radar_cfg" and v["group"] == "shipped" and v["referenced_by"]
               and not v.get("template_of"))
    before = digest(cfg)
    r = post(c, "/api/configs/delete", ids=[cid], confirm=True, confirm_shipped=True)
    assert r.status_code == 409 and r.json()["detail"]["referenced_by"][cid] == items[cid]["referenced_by"]
    assert digest(cfg) == before
    dry = post(c, "/api/configs/delete?dry=1", ids=[cid]).json()
    assert dry["needs_force_referenced"] and dry["needs_confirm_shipped"] and digest(cfg) == before


def test_delete_firmware_template_hard_refused(env):
    c, cfg, user, mgr, t = env
    items = c.get("/api/configs").json()["configs"]
    tpl = next(i["id"] for i in items if i.get("template_of"))
    before = digest(cfg)
    r = post(c, "/api/configs/delete", ids=[tpl], confirm=True, confirm_shipped=True, force_referenced=True)
    assert r.status_code == 409 and "template" in r.text
    assert digest(cfg) == before


def test_delete_moved_paths_target_needs_force_and_notes_it(env):
    c, cfg, user, mgr, t = env
    moved = sorted(ca.moved_targets(t) - set(ca.template_cfgs(t)))
    sysid = next(i for i in moved if i.startswith("shipped:system/"))
    r = post(c, "/api/configs/delete", ids=[sysid], confirm=True, confirm_shipped=True)
    assert r.status_code == 409 and "moved_paths.json" in r.text
    r = post(c, "/api/configs/delete", ids=[sysid], confirm=True, confirm_shipped=True, force_referenced=True)
    assert r.status_code == 200 and any("moved_paths" in n for n in r.json()["notes"])


def test_batch_with_one_bad_id_changes_nothing(env):
    c, cfg, user, mgr, t = env
    before = digest(cfg)
    r = post(c, "/api/configs/delete", ids=["user:scratch.json", "user:../x.json"], confirm=True)
    assert 400 <= r.status_code < 500 and digest(cfg) == before


def test_shipped_writes_disabled_message_not_500(env, monkeypatch):
    c, cfg, user, mgr, t = env
    monkeypatch.setenv("RADAR_GUI_SHIPPED_WRITES", "0")
    before = digest(cfg)
    assert c.get("/api/configs").json()["shipped_writes"]["enabled"] is False
    r = post(c, "/api/configs/promote", id="user:scratch.json")
    assert r.status_code == 409 and "cannot be written" in r.text
    r = post(c, "/api/configs/delete", ids=[f"shipped:system/{GATE}.json"], confirm=True, confirm_shipped=True)
    assert r.status_code == 409
    # dry runs still work; user deletes are not affected
    assert post(c, "/api/configs/promote?dry=1", id="user:scratch.json").json()["shipped_writes"]["enabled"] is False
    assert digest(cfg) == before
    assert post(c, "/api/configs/delete", ids=["user:scratch.json"], confirm=True).status_code == 200


def test_write_state_detects_container_with_unmounted_shipped_tree(env, monkeypatch, tmp_path):
    c, cfg, user, mgr, t = env
    assert ca.shipped_write_state(t, container=True)["enabled"]                  # same filesystem: whole repo mounted
    real_stat = Path.stat

    def fake_stat(self, *a, **k):
        st = real_stat(self, *a, **k)
        if self == t.system:
            import types
            d = {k: getattr(st, k) for k in dir(st) if k.startswith("st_")}
            d["st_dev"] = st.st_dev + 1
            return types.SimpleNamespace(**d)
        return st
    monkeypatch.setattr(Path, "stat", fake_stat)
    s = ca.shipped_write_state(t, container=True)
    assert not s["enabled"] and "bind-mounts only config/user" in s["reason"]
    assert ca.shipped_write_state(t, container=False)["enabled"]                 # a host: different device is fine
    monkeypatch.undo()
    os.chmod(t.system, 0o555)
    try:
        if os.access(t.system, os.W_OK):
            pytest.skip("running as a user that ignores directory modes")
        assert not ca.shipped_write_state(t, container=False)["enabled"]
    finally:
        os.chmod(t.system, 0o755)


def test_git_status_with_and_without_a_repo(env, tmp_path):
    c, cfg, user, mgr, t = env
    assert ca.git_status(t)["available"] is False
    ident = ["-c", "user.name=T", "-c", "user.email=t@example.com"]
    g = lambda *a: subprocess.run(["git", *ident, "-C", str(cfg), *a], check=True, capture_output=True)   # noqa: E731
    g("init", "-q")
    g("add", "system", "radar", "README.md")
    g("commit", "-q", "-m", "t")
    s = c.get("/api/configs").json()["git"]
    assert s["available"] and s["dirty"] == [] and s["branch"]
    assert post(c, "/api/configs/promote", id="user:scratch.json").status_code == 200
    s = c.get("/api/configs").json()["git"]
    assert len(s["dirty"]) == 3 and all(x.startswith(("??", " M")) for x in s["dirty"])   # 2 new files + README
    # user/ is not part of the shipped status
    assert not any("user" in x for x in s["dirty"])
    j = post(c, "/api/configs/delete", ids=[f"shipped:system/{GATE}.json"], confirm=True, confirm_shipped=True,
             force_referenced=True)
    assert j.status_code == 200 and j.json()["git"]["available"]
    # git is only ever read: the index was not touched by the GUI (status is unstaged)
    staged = subprocess.run(["git", "-C", str(cfg), "diff", "--cached", "--name-only"], capture_output=True, text=True).stdout
    assert staged == ""


def test_outputs_and_index_row_helpers():
    assert ca.outputs_of({"serial_stream": {"enabled": True}, "dca1000": {"enabled": True},
                          "output": {"save_adc_frames": True, "save_raw_lvds": True}}) == \
        ["serial TLV", "DCA1000", "saves ADC frames", "saves raw LVDS"]
    text = "# t\n| System JSON |\n|---|\n| [`B.json`](system/B.json) | b | f | o | `c` | p |\n| [`D.json`](system/D.json) | b | f | o | `c` | q |\n\nrest\n"
    new, ok = ca.readme_set_row(text, "C.json", lambda old: ca.index_row("C.json", "b", "f", [], "x", "new"))
    assert ok and new.splitlines()[4].startswith("| [`C.json`]") and new.splitlines()[5].startswith("| [`D.json`]")
    new2, _ = ca.readme_set_row(new, "C.json", lambda old: ca.index_row("C.json", "b", "f", ["DCA1000"], "x", old))
    assert "| DCA1000 | `x` | new |" in new2 and new2.count("C.json") == 2
    gone, hit = ca.readme_drop_row(new2, "C.json")
    assert hit and gone == text


def test_promoted_files_honour_umask_and_keep_readme_mode(env):
    c, cfg, user, mgr, t = env
    old = os.umask(0o022)
    try:
        os.chmod(cfg / "README.md", 0o640)
        assert post(c, "/api/configs/promote", id="user:scratch.json").status_code == 200
        js = cfg / "system" / "IWR1843_iwr1843_sar_lvds_scratch.json"
        cf = cfg / "radar" / "IWR1843" / "iwr1843_sar_lvds" / "scratch.cfg"
        assert js.stat().st_mode & 0o777 == 0o644 and cf.stat().st_mode & 0o777 == 0o644
        assert (cfg / "README.md").stat().st_mode & 0o777 == 0o640
        os.chmod(js, 0o664)                                              # an overwrite keeps the existing file's mode
        assert post(c, "/api/configs/promote", id="user:scratch.json", confirm_overwrite=True).status_code == 200
        assert js.stat().st_mode & 0o777 == 0o664
        b = next((user / ".promote_backups").iterdir())
        assert (b / "system" / js.name).stat().st_mode & 0o777 == 0o664
    finally:
        os.umask(old)


def test_restore_hint_only_for_tracked_files(env):
    c, cfg, user, mgr, t = env
    ident = ["-c", "user.name=T", "-c", "user.email=t@example.com"]
    g = lambda *a: subprocess.run(["git", *ident, "-C", str(cfg), *a], check=True, capture_output=True)   # noqa: E731
    g("init", "-q"); g("add", "system", "radar", "README.md"); g("commit", "-q", "-m", "t")
    assert post(c, "/api/configs/promote", id="user:scratch.json").status_code == 200       # untracked now
    new = "shipped:system/IWR1843_iwr1843_sar_lvds_scratch.json"
    old = f"shipped:system/{GATE}.json"
    d = post(c, "/api/configs/delete?dry=1", ids=[new, old]).json()["would_remove"]
    by = {x["id"]: x for x in d}
    assert by[new]["tracked"] is False and "git cannot restore" in by[new]["restore"]
    assert by[old]["tracked"] is True and by[old]["restore"].startswith("git restore -- ")
    r = post(c, "/api/configs/delete", ids=[new, old], confirm=True, confirm_shipped=True, force_referenced=True).json()
    res = {x["id"]: x for x in r["results"]}
    assert res[old]["action"] == "removed" and res[old]["restore"].startswith("git restore -- ")
    assert res[new]["action"] == "trashed" and Path(res[new]["to"]).is_file() and "git restore" not in res[new]["restore"]
    assert not (cfg / "system" / "IWR1843_iwr1843_sar_lvds_scratch.json").exists()
