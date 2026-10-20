"""Configs tab backend: browse every saved (`config/user/`) and shipped (`config/system/*.json`,
`config/radar/<BOARD>/<fw>/*.cfg`) configuration, promote a user setup to a shipped one, delete a user or shipped file.

It never runs a git write. It shows `git status` for the two shipped trees and says what to commit.

Confinement (the same idea as logs_api): a file is addressed by id only, `user:<file>`, `shipped:system/<file>.json` or
`shipped:radar/<BOARD>/<fw>/<file>.cfg`; every part is a strict name (no `/`, `..`, `%`, absolute path), the file must be a
plain file (no symlink) of the right suffix inside exactly those folders. `config/archive`, `boards`, `firmware`, `limits`,
`moved_paths.json` and `README.md` (except its index rows, edited by promote/delete) are not addressable.

The shipped trees are written ONLY by promote and delete, behind explicit confirm fields, and only when `shipped_writes`
says they are writable (a container that bind-mounts just config/user cannot write them: they would land in the image).
Overwritten shipped files are kept under `config/user/.promote_backups/<UTC>_<name>/`; deleted user files are moved to
`config/user/.trash/<UTC>/` (both gitignored with config/user/). Shipped deletes are real unlinks: git is the undo.
"""
from __future__ import annotations

import json
import os
import pwd
import grp
import re
import shlex
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from . import cfgapi, sysjson
from .cfg import firmware as fwmod

REPO = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_DIR = REPO / "CPSL_TI_Radar_cpp" / "config"
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,80}$")
BACKUPS, TRASH = ".promote_backups", ".trash"
MAX_VIEW_BYTES = 1_000_000
MAX_DELETE = 100
ROW_RE = re.compile(r"^\| \[`([^`]+\.json)`\]\(system/([^)]+)\) \| ")
GIT_TIMEOUT = 8


# --- pure helpers (callable on a temp tree) --------------------------------------------------------------------

class Tree:
    """The directories one router instance works on."""

    def __init__(self, config_dir: Path, user_dir: Path):
        self.config = Path(config_dir)
        self.user = Path(user_dir)
        self.system = self.config / "system"
        self.radar = self.config / "radar"
        self.readme = self.config / "README.md"

    @property
    def repo_prefix(self) -> str:   # the config dir relative to the repo root, for the `git restore` hints
        try:
            return self.config.resolve().relative_to(REPO).as_posix()
        except ValueError:
            return self.config.name


def _plain(p: Path) -> bool:
    return p.is_file() and not p.is_symlink()


# --- ownership: warn, never fix -----------------------------------------------------------------------

MAX_OWNER_SCAN = 2000


def _owner_uid(st) -> int:
    """The uid a stat result belongs to (one seam so tests can fake a foreign owner)."""
    return st.st_uid


def _name_of(uid: int, gid: int | None = None) -> str:
    try:
        u = pwd.getpwuid(uid).pw_name
    except KeyError:
        u = str(uid)
    if gid is None:
        return u
    try:
        g = grp.getgrgid(gid).gr_name
    except KeyError:
        g = str(gid)
    return f"{u}:{g}"


def repo_owner(t: Tree) -> tuple[int, int]:
    """(uid, gid) of the repository root holding the config dir (the nearest ancestor with a .git), else of the config dir."""
    base = t.config.resolve()
    root = next((d for d in (base, *base.parents) if (d / ".git").exists()), base)
    st = root.stat()
    return st.st_uid, st.st_gid


def owner_warning(t: Tree, paths) -> dict | None:
    """None when every existing path is owned by the repo owner; else {repo_owner, entries:[{path, owner}], count, command}.
    The command is a suggestion (`sudo chown user:group <paths>`): nothing here ever runs it. Symlinks are judged by their own
    owner (lstat). Existing backup/trash trees are scanned too."""
    try:
        ruid, rgid = repo_owner(t)
    except OSError:
        return None
    extra: list[Path] = []
    for d in (t.user / BACKUPS, t.user / TRASH):
        if d.is_dir() and not d.is_symlink():
            for n, f in enumerate(d.rglob("*")):
                if n >= MAX_OWNER_SCAN:
                    break
                extra.append(f)
    bad, seen = [], set()
    for p in [*paths, *extra]:
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        try:
            st = os.lstat(p)
        except OSError:
            continue
        if _owner_uid(st) != ruid:
            bad.append({"path": key, "owner": _name_of(_owner_uid(st), st.st_gid)})
    if not bad:
        return None
    owner = _name_of(ruid, rgid)
    shown = [b["path"] for b in bad[:20]]
    return {"repo_owner": owner, "count": len(bad), "entries": bad[:50],
            "command": f"sudo chown {owner} " + " ".join(shlex.quote(x) for x in shown) + (" ..." if len(bad) > 20 else "")}


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def resolve_id(t: Tree, id_: str) -> tuple[str, str, Path]:
    """(group, kind, path) of an addressable id, or HTTPException (422 not addressable / 404 not there)."""
    bad = HTTPException(422, f"{id_!r} is not an addressable configuration id")
    if not isinstance(id_, str) or len(id_) > 300 or ".." in id_ or "\\" in id_ or "%" in id_ or "\x00" in id_:
        raise bad
    group, _, rest = id_.partition(":")
    parts = rest.split("/")
    if not rest or not all(NAME_RE.match(x) for x in parts):
        raise bad
    if group == "user" and len(parts) == 1:
        root, p = t.user, t.user / parts[0]
    elif group == "shipped" and parts[0] == "system" and len(parts) == 2:
        root, p = t.system, t.system / parts[1]
    elif group == "shipped" and parts[0] == "radar" and len(parts) == 4:
        root, p = t.radar, t.radar.joinpath(*parts[1:])
    else:
        raise bad
    if p.suffix not in (".json", ".cfg"):
        raise bad
    if group == "shipped" and parts[0] == "system" and p.suffix != ".json":
        raise bad
    if group == "shipped" and parts[0] == "radar" and p.suffix != ".cfg":
        raise bad
    # a symlink anywhere on the path out of the tree, or a file that resolves elsewhere
    rt = root.resolve()
    cur = root
    for part in p.relative_to(root).parts[:-1]:
        cur = cur / part
        if cur.is_symlink():
            raise bad
    if p.is_symlink():
        raise bad
    try:
        p.resolve().relative_to(rt)
    except ValueError:
        raise bad from None
    if not _plain(p):
        raise HTTPException(404, f"no such configuration {id_!r}")
    return group, ("system_json" if p.suffix == ".json" else "radar_cfg"), p


def _id_of(t: Tree, p: Path) -> str | None:
    """The id of a path inside one of the addressable folders (or None)."""
    try:
        rp = p.resolve()
    except OSError:
        return None
    for root, fmt in ((t.user, "user:{}"), (t.system, "shipped:system/{}"), (t.radar, "shipped:radar/{}")):
        try:
            rel = rp.relative_to(root.resolve())
        except ValueError:
            continue
        if (fmt.startswith("user") or fmt.endswith("system/{}")) and len(rel.parts) != 1:
            continue
        if fmt.endswith("radar/{}") and len(rel.parts) != 3:
            continue
        return fmt.format(rel.as_posix())
    return None


def _load(p: Path) -> dict | None:
    try:
        d = json.loads(p.read_text())
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def _cfg_path_of(doc: dict, json_path: Path) -> Path | None:
    rc = doc.get("radar_cfg")
    if not isinstance(rc, str) or not rc:
        return None
    return (json_path.parent / rc).resolve()


def outputs_of(doc: dict) -> list[str]:
    """What a JSON enables, in the README index's words and order."""
    out = []
    if (doc.get("serial_stream") or {}).get("enabled"):
        out.append("serial TLV")
    if (doc.get("dca1000") or {}).get("enabled"):
        out.append("DCA1000")
    o = doc.get("output") or {}
    for k, label in (("save_adc_frames", "saves ADC frames"), ("save_raw_lvds", "saves raw LVDS"),
                     ("save_serial_bytes", "saves serial bytes")):
        if o.get(k):
            out.append(label)
    return out


def scan(t: Tree) -> list[dict]:
    """Every listed file, with JSON facts, cfg links and (for cfgs) the JSONs that reference them."""
    items: list[dict] = []
    files: list[tuple[str, Path]] = []
    if t.user.is_dir():
        files += [("user", p) for p in sorted(t.user.iterdir()) if p.suffix in (".json", ".cfg") and NAME_RE.match(p.name)]
    if t.system.is_dir():
        files += [("shipped", p) for p in sorted(t.system.glob("*.json")) if NAME_RE.match(p.name)]
    if t.radar.is_dir():
        files += [("shipped", p) for p in sorted(t.radar.glob("*/*/*.cfg")) if NAME_RE.match(p.name)]
    refs: dict[Path, list[str]] = {}
    for group, p in files:
        if not _plain(p):
            continue
        id_ = _id_of(t, p)
        if id_ is None:
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        it = {"id": id_, "kind": "system_json" if p.suffix == ".json" else "radar_cfg", "group": group, "name": p.name,
              "rel": id_.split(":", 1)[1], "size": st.st_size, "mtime": st.st_mtime, "path": str(p)}
        if p.suffix == ".json":
            doc = _load(p)
            it["valid"] = doc is not None
            board = doc.get("board") if doc else None
            fw = doc.get("firmware") if doc else None
            it.update({"board": board if isinstance(board, str) else None, "firmware": fw if isinstance(fw, str) else None,
                       "gui_board": fwmod.gui_board(board) if isinstance(board, str) else None,
                       "outputs": outputs_of(doc) if doc else [], "cfg": None, "cfg_exists": False})
            cp = _cfg_path_of(doc, p) if doc else None
            if cp is not None:
                it["cfg"] = _id_of(t, cp)
                it["cfg_exists"] = _plain(cp)
                it["cfg_ref"] = (doc or {}).get("radar_cfg")
                refs.setdefault(cp, []).append(id_)
        else:
            it["board"] = p.parent.parent.name if group == "shipped" else None
            it["gui_board"] = it["board"]
            it["firmware"] = p.parent.name if group == "shipped" else None
        items.append(it)
    for it in items:
        if it["kind"] == "radar_cfg":
            it["referenced_by"] = sorted(refs.get(Path(it["path"]).resolve(), []))
    return items


def live_paths(mgr) -> set[Path]:
    """Files a starting/running/stopping driver session uses: its config JSON, its session.json, and the cfgs they name."""
    if mgr is None:
        return set()
    try:
        st = mgr.status(log=False)
    except Exception:   # noqa: BLE001 - a status error must not break the listing
        return set()
    if st.get("state") in (None, "idle", "exited", "failed"):
        return set()
    out: set[Path] = set()
    for c in (st.get("config"), getattr(mgr, "session_json", None), st.get("session_json")):
        if not c:
            continue
        p = Path(c)
        try:
            out.add(p.resolve())
        except OSError:
            continue
        doc = _load(p) if p.suffix == ".json" else None
        cp = _cfg_path_of(doc, p) if doc else None
        if cp is not None:
            out.add(cp)
    return out


def in_container() -> bool:
    return Path("/.dockerenv").exists() or Path("/run/.containerenv").exists()


def shipped_write_state(t: Tree, container: bool | None = None) -> dict:
    """{enabled, reason}: can the pane write the shipped trees? Disabled when they are not writable, or when this is a
    container whose config/system sits on another filesystem than the bind-mounted config/user (the `hw` compose profile
    mounts only config/user: a shipped write would land in the image layer and vanish). RADAR_GUI_SHIPPED_WRITES=0/1 forces."""
    env = os.environ.get("RADAR_GUI_SHIPPED_WRITES")
    if env == "0":
        return {"enabled": False, "reason": "disabled by RADAR_GUI_SHIPPED_WRITES=0"}
    if env != "1":
        for d in (t.system, t.radar):
            if not d.is_dir() or not os.access(d, os.W_OK):
                return {"enabled": False, "reason": f"{d} is missing or not writable by this process"}
        cont = in_container() if container is None else container
        try:
            same = t.system.stat().st_dev == t.user.stat().st_dev if t.user.is_dir() else True
        except OSError:
            same = True
        if cont and not same:
            return {"enabled": False,
                    "reason": "this GUI runs in a container that bind-mounts only config/user: the shipped config trees "
                              "are in the image, not the repository. Run the GUI on the host or in a container with the "
                              "whole repository mounted to promote or delete shipped configs."}
    return {"enabled": True, "reason": ""}


def git_status(t: Tree) -> dict:
    """Read-only `git status --porcelain` of config/system, config/radar and the README index. Never raises; `available:false` when there is
    no git binary / repository / the call fails."""
    def run(*args):
        return subprocess.run(["git", "--no-optional-locks", "-c", "safe.directory=*", "-C", str(t.config), *args],
                              capture_output=True, text=True, timeout=GIT_TIMEOUT)
    try:
        top = run("rev-parse", "--show-toplevel")
        if top.returncode != 0:
            return {"available": False, "dirty": [], "branch": None, "note": "not a git checkout"}
        names = [d.name for d in (t.system, t.radar) if d.is_dir()] + (["README.md"] if t.readme.is_file() else [])
        st = run("status", "--porcelain", "--", *names)
        if st.returncode != 0:
            return {"available": False, "dirty": [], "branch": None, "note": (st.stderr or "git status failed").strip()[:200]}
        br = run("rev-parse", "--abbrev-ref", "HEAD")
        branch = br.stdout.strip() if br.returncode == 0 else None
        return {"available": True, "dirty": [ln for ln in st.stdout.splitlines() if ln.strip()], "branch": branch,
                "toplevel": top.stdout.strip()}
    except (OSError, subprocess.SubprocessError) as e:
        return {"available": False, "dirty": [], "branch": None, "note": str(e)[:200]}


def tracked(t: Tree, p: Path) -> bool | None:
    """True/False: git tracks `p` (ls-files, read-only); None when git cannot tell (no repo / no binary)."""
    try:
        r = subprocess.run(["git", "--no-optional-locks", "-c", "safe.directory=*", "-C", str(t.config), "ls-files",
                            "--error-unmatch", "--", str(p.resolve())], capture_output=True, text=True, timeout=GIT_TIMEOUT)
        if r.returncode == 0:
            return True
        top = subprocess.run(["git", "-C", str(t.config), "-c", "safe.directory=*", "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=GIT_TIMEOUT)
        return False if top.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def default_mode() -> int:
    """0o666 minus the process umask: what a plain open() would give a new file."""
    m = os.umask(0)
    os.umask(m)
    return 0o666 & ~m


def write_like(path: Path, text: str, mode: int | None = None) -> None:
    """Atomic text write whose result has `mode` (default: the existing file's mode, else the umask default) instead of
    mkstemp's 0600."""
    if mode is None:
        try:
            mode = path.stat().st_mode & 0o777
        except OSError:
            mode = default_mode()
    sysjson.atomic_write_text(path, text)
    os.chmod(path, mode)


def name_pattern(t: Tree) -> re.Pattern:
    """The system-JSON file-name pattern `tests/test_config_tree.py` enforces: <GUIBOARD>_<fw>_<purpose>[_front|back|down|r1].json."""
    boards = {fwmod.gui_board(p.stem) for p in (t.config / "boards").glob("*.json")} or set(fwmod.load_all()) or {"X"}
    fws = [p.stem for p in (t.config / "firmware").glob("*.json")] or list(fwmod.load_all()) or ["x"]
    bs = "|".join(sorted(boards, key=len, reverse=True))
    fs = "|".join(sorted(fws, key=len, reverse=True))
    return re.compile(rf"^({bs})_({fs})_[A-Za-z0-9]+(?:_[A-Za-z0-9]+)*?(?:_(?:front|back|down|r1))?\.json$")


def moved_targets(t: Tree) -> set[str]:
    """Shipped ids named as a destination in moved_paths.json (the tree test requires them to exist)."""
    d = _load(t.config / "moved_paths.json") or {}
    out = set()
    for n in (d.get("system") or {}).values():
        out.add(f"shipped:system/{n}")
    for n in (d.get("radar") or {}).values():
        out.add(f"shipped:radar/{n}")
    return out


def template_cfgs(t: Tree) -> dict[str, list[str]]:
    """shipped cfg id -> firmware descriptors that use it as a template."""
    out: dict[str, list[str]] = {}
    for p in sorted((t.config / "firmware").glob("*.json")):
        d = _load(p) or {}
        for tpl in (d.get("templates") or {}).values():
            if isinstance(tpl, str) and tpl.startswith("radar/"):
                out.setdefault(f"shipped:{tpl}", []).append(p.stem)
    return out


# --- README index ----------------------------------------------------------------------------------------------

def index_row(name: str, board: str, fw: str, outputs: list[str], cfg_rel: str, purpose: str) -> str:
    return f"| [`{name}`](system/{name}) | {board} | {fw} | {', '.join(outputs) or 'none'} | `{cfg_rel}` | {purpose} |"


def readme_set_row(text: str, name: str, row_for: callable) -> tuple[str, bool]:
    """Insert (sorted by file name among the index rows) or replace the index row of `name`. `row_for(old_purpose|None)` builds it.
    Only index-row lines are looked at; every other byte is kept."""
    lines = text.splitlines(keepends=True)
    idx = [(i, ROW_RE.match(ln)) for i, ln in enumerate(lines)]
    idx = [(i, m) for i, m in idx if m]
    if not idx:
        return text, False
    nl = "\n"
    for i, m in idx:
        if m.group(1) == name:
            old = lines[i].rstrip("\r\n")
            parts = old[len(m.group(0)):].rstrip().removesuffix("|").rstrip().split(" | ", 4)
            purpose = parts[4] if len(parts) == 5 else None
            ending = lines[i][len(old):] or nl
            lines[i] = row_for(purpose) + ending
            return "".join(lines), True
    pos = None
    for i, m in idx:
        if m.group(1) > name:
            pos = i
            break
    if pos is None:
        pos = idx[-1][0] + 1
        if not lines[idx[-1][0]].endswith("\n"):
            lines[idx[-1][0]] += nl
    lines.insert(pos, row_for(None) + nl)
    return "".join(lines), True


def readme_drop_row(text: str, name: str) -> tuple[str, bool]:
    lines = text.splitlines(keepends=True)
    keep = [ln for ln in lines if not ((m := ROW_RE.match(ln)) and m.group(1) == name)]
    return "".join(keep), len(keep) != len(lines)


# --- requests --------------------------------------------------------------------------------------------------

class PromoteReq(BaseModel):
    id: str
    name: str | None = None
    note: str | None = Field(None, max_length=300)
    confirm_overwrite: bool = False
    folder: str | None = None   # a user .cfg only: the existing config/radar/<chip>/<firmware> folder to file it in


class DeleteReq(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=MAX_DELETE)
    confirm: bool = False
    confirm_shipped: bool = False
    with_cfg: bool = False
    force_referenced: bool = False


def radar_folders(t: Tree) -> list[str]:
    """Existing config/radar/<chip>/<firmware> folders (plain directories), as 'chip/firmware': where a .cfg can be filed."""
    out = []
    if t.radar.is_dir():
        for p in sorted(t.radar.glob("*/*")):
            if p.is_dir() and not p.is_symlink() and not p.parent.is_symlink() and NAME_RE.match(p.name) and NAME_RE.match(p.parent.name):
                out.append(f"{p.parent.name}/{p.name}")
    return out


def make_router(mgr=None, user_dir=None, config_dir=None, driver_bin=None) -> APIRouter:
    t = Tree(Path(config_dir or os.environ.get("RADAR_GUI_CONFIG_DIR") or DEFAULT_CONFIG_DIR),
             Path(user_dir or os.environ.get("RADAR_GUI_USER_CFG_DIR") or cfgapi.DEFAULT_USER_DIR))
    r = APIRouter(prefix="/api/configs")

    def hint_path(p: Path) -> str:
        try:
            return (Path(t.repo_prefix) / p.resolve().relative_to(t.config.resolve())).as_posix()
        except ValueError:
            return p.name

    # -- listing ------------------------------------------------------------------------------------------------

    @r.get("")
    def listing():
        live = live_paths(mgr)
        items = scan(t)
        tpl = template_cfgs(t)
        for it in items:
            it["in_use"] = Path(it["path"]).resolve() in live
            if it["kind"] == "radar_cfg":
                it["template_of"] = tpl.get(it["id"], [])
        ow = owner_warning(t, [Path(it["path"]) for it in items] + [d for d in (t.user, t.user / BACKUPS, t.user / TRASH) if d.exists()])
        if ow:
            bad = {e["path"]: e["owner"] for e in ow["entries"]}
            for it in items:
                if it["path"] in bad:
                    it["foreign_owner"] = bad[it["path"]]
        return {"configs": items, "user_dir": str(t.user), "config_dir": str(t.config),
                "shipped_writes": shipped_write_state(t), "git": git_status(t), "owner_warning": ow,
                "radar_folders": radar_folders(t)}

    @r.get("/file")
    def file(id: str = Query(...)):
        group, kind, p = resolve_id(t, id)
        size = p.stat().st_size
        with p.open("rb") as f:
            data = f.read(MAX_VIEW_BYTES)
        return {"id": id, "name": p.name, "kind": kind, "group": group, "size": size,
                "text": data.decode("utf-8", "replace"), "truncated": size > MAX_VIEW_BYTES}

    # -- promote ------------------------------------------------------------------------------------------------

    def plan_promote_cfg(req: PromoteReq, src: Path) -> dict:
        """A standalone chirp .cfg: filed in an EXISTING config/radar/<chip>/<firmware>/ folder the caller names (it is not
        guessed: a .cfg carries no board/firmware). No JSON and no README row are written."""
        folders = radar_folders(t)
        if not req.folder or req.folder not in folders:
            raise HTTPException(422, {"message": "choose the config/radar folder (chip/firmware) to file this .cfg in",
                                      "folders": folders})
        name = (req.name or src.stem)
        if not NAME_RE.match(name) or name.endswith("."):
            raise HTTPException(422, "name: letters, digits, '_', '-', '.', must start with a letter or digit")
        if name.endswith(".cfg"):
            name = name[:-4]
        gui, fw_id = req.folder.split("/")
        dst = t.radar / gui / fw_id / f"{name}.cfg"
        if dst.is_symlink() or (dst.exists() and not dst.is_file()):
            raise HTTPException(409, f"{dst.name} exists and is not a plain file")
        tgt = f"shipped:radar/{gui}/{fw_id}/{name}.cfg"
        if tgt in template_cfgs(t):
            raise HTTPException(409, f"{dst.name} is the template of firmware {', '.join(template_cfgs(t)[tgt])}: the Configure tab needs it, pick another name")
        refs = sorted({i["id"] for i in scan(t) if i["kind"] == "system_json" and i.get("cfg") == tgt})
        return {"kind": "cfg", "src": src, "cfg_src": src, "gui": gui, "fw": fw_id, "name": name, "sys_name": None, "doc": None,
                "cfg_dst": dst, "json_dst": None, "exists": [tgt] if dst.is_file() else [], "referenced_by": refs, "board": None}

    def plan_promote(req: PromoteReq) -> dict:
        group, kind, src = resolve_id(t, req.id)
        if group == "user" and kind == "radar_cfg":
            return plan_promote_cfg(req, src)
        if group != "user" or kind != "system_json":
            raise HTTPException(422, "promote takes a saved setup (a JSON in config/user/) or a saved chirp config (a .cfg in config/user/)")
        doc = _load(src)
        if doc is None:
            raise HTTPException(422, f"{src.name} is not a JSON object")
        if doc.get("schema_version") != 2:
            raise HTTPException(422, f"{src.name}: schema_version must be 2")
        fw_id = doc.get("firmware")
        if not isinstance(fw_id, str) or not fw_id:
            raise HTTPException(422, f'{src.name} names no firmware: use "Add firmware" on the Radar tab first (a shipped '
                                     "config is filed by board and firmware)")
        fw = fwmod.get(fw_id)
        if fw is None:
            raise HTTPException(422, f"{src.name}: unknown firmware {fw_id!r}")
        board = doc.get("board")
        if not isinstance(board, str) or not board:
            raise HTTPException(422, f"{src.name} names no board")
        gui = fwmod.gui_board(board)
        if gui not in fw["templates"]:
            raise HTTPException(422, f"{src.name}: board {board!r} has no folder for firmware {fw_id!r} "
                                     f"(descriptor boards: {list(fw['templates'])})")
        name = req.name if req.name else src.stem
        if not NAME_RE.match(name) or name.endswith("."):
            raise HTTPException(422, "name: letters, digits, '_', '-', '.', must start with a letter or digit")
        cp = _cfg_path_of(doc, src)
        if cp is None or cp.parent != t.user.resolve() or cp.suffix != ".cfg":
            raise HTTPException(422, f"{src.name}: radar_cfg must name a .cfg in config/user/ (it is {doc.get('radar_cfg')!r})")
        if not _plain(cp):
            raise HTTPException(422, f"{src.name}: radar_cfg {cp.name} does not exist in config/user/")
        sys_name = f"{gui}_{fw_id}_{name}.json"
        if not name_pattern(t).match(sys_name):
            raise HTTPException(422, f"{sys_name!r} would break the shipped naming rule "
                                     f"<BOARD>_<firmware>_<purpose>[_front|back|down|r1].json: use letters and digits, "
                                     f"separated by '_', in the name")
        cfg_dst = t.radar / gui / fw_id / f"{name}.cfg"
        json_dst = t.system / sys_name
        for d in (json_dst, cfg_dst):
            if d.is_symlink() or (d.exists() and not d.is_file()):
                raise HTTPException(409, f"{d.name} exists and is not a plain file")
        new = {}
        for k, v in doc.items():
            new[k] = v
        new["radar_cfg"] = f"../radar/{gui}/{fw_id}/{name}.cfg"
        if isinstance(new.get("board"), str) and ("/" in new["board"] or new["board"].endswith(".json")):
            new["board"] = Path(new["board"]).stem
        ss = new.get("serial_stream")
        if isinstance(ss, dict) and not ss.get("enabled"):
            ss.pop("port", None)
        exists = [i for i, d in ((f"shipped:system/{sys_name}", json_dst), (f"shipped:radar/{gui}/{fw_id}/{name}.cfg", cfg_dst))
                  if d.is_file()]
        tgt_cfg_id = f"shipped:radar/{gui}/{fw_id}/{name}.cfg"
        refs = sorted({i["id"] for i in scan(t) if i["kind"] == "system_json" and i.get("cfg") == tgt_cfg_id
                       and i["id"] != f"shipped:system/{sys_name}"})
        return {"src": src, "cfg_src": cp, "gui": gui, "fw": fw_id, "name": name, "sys_name": sys_name, "doc": new,
                "cfg_dst": cfg_dst, "json_dst": json_dst, "exists": exists, "referenced_by": refs, "board": new["board"]}

    def check_live(p: dict):
        live = live_paths(mgr)
        busy = [x.name for x in (p["src"], p["cfg_src"], p["json_dst"], p["cfg_dst"]) if x is not None and x.resolve() in live]
        if busy:
            raise HTTPException(409, f"in use by a running driver session ({', '.join(busy)}): stop it first")

    def promote_preview(p: dict) -> dict:
        if p.get("kind") == "cfg":
            return {"kind": "cfg", "would_write": [f"shipped:radar/{p['gui']}/{p['fw']}/{p['name']}.cfg"], "would_replace": p["exists"],
                    "referenced_by": p["referenced_by"], "json": None, "readme_row": None, "folders": radar_folders(t),
                    "owner_warning": owner_warning(t, [p["src"], p["cfg_dst"], p["cfg_dst"].parent, t.user, t.user / BACKUPS])}
        return {"would_write": [f"shipped:radar/{p['gui']}/{p['fw']}/{p['name']}.cfg", f"shipped:system/{p['sys_name']}"],
                "would_replace": p["exists"], "referenced_by": p["referenced_by"], "json": p["doc"],
                "owner_warning": owner_warning(t, [p["src"], p["cfg_src"], p["json_dst"], p["cfg_dst"], p["json_dst"].parent,
                                                   p["cfg_dst"].parent, t.readme, t.user, t.user / BACKUPS]),
                "readme_row": index_row(p["sys_name"], p["board"], p["fw"], outputs_of(p["doc"]),
                                        f"{p['gui']}/{p['fw']}/{p['name']}.cfg", "<note>")}

    @r.post("/promote")
    def promote(req: PromoteReq, dry: int = Query(0)):
        ws = shipped_write_state(t)
        p = plan_promote(req)
        if dry:
            return {"dry": True, "shipped_writes": ws, **promote_preview(p)}
        if not ws["enabled"]:
            raise HTTPException(409, f"shipped configs cannot be written from this GUI: {ws['reason']}")
        check_live(p)
        if p["exists"] and not req.confirm_overwrite:
            raise HTTPException(409, {"message": "a shipped config of that name exists: confirm to replace it",
                                      "exists": p["exists"], "would_replace": p["exists"], "referenced_by": p["referenced_by"]})
        stamp = utc_stamp()
        backups: list[str] = []
        if p["exists"]:
            bdir = t.user / BACKUPS / f"{stamp}_{p['name']}"
            for dst in (p["cfg_dst"], p["json_dst"]):
                if dst is not None and dst.is_file():
                    rel = dst.relative_to(t.config)
                    b = bdir / rel
                    b.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(dst, b)
                    backups.append(str(b))
        p["cfg_dst"].parent.mkdir(parents=True, exist_ok=True)
        tmp = p["cfg_dst"].with_name(f".{p['cfg_dst'].name}.{os.getpid()}.tmp")
        try:
            shutil.copyfile(p["cfg_src"], tmp)
            if tmp.read_bytes() != p["cfg_src"].read_bytes():
                raise HTTPException(500, "copy of the cfg does not match the source; nothing was replaced")
            os.replace(tmp, p["cfg_dst"])
        finally:
            tmp.unlink(missing_ok=True)
        if p.get("kind") == "cfg":
            f = {"id": f"shipped:radar/{p['gui']}/{p['fw']}/{p['name']}.cfg", "path": str(p["cfg_dst"]),
                 "action": "overwritten" if p["exists"] else "created"}
            return {"ok": True, "result": f["action"], "files": [f], "backups": backups, "readme_updated": False, "driver": None,
                    "git": git_status(t), "notes": [], "commit_hint": "git add " + hint_path(p["cfg_dst"])}
        write_like(p["json_dst"], sysjson.dumps(p["doc"]), p["json_dst"].stat().st_mode & 0o777 if p["json_dst"].is_file() else default_mode())
        notes = []
        purpose = (req.note or "").strip() or f"promoted from config/user ({datetime.now().strftime('%Y-%m-%d')})"
        purpose = re.sub(r"[\r\n]+", " ", purpose.replace("|", "/"))
        readme_updated = False
        if t.readme.is_file():
            text = t.readme.read_text()
            row = lambda old: index_row(p["sys_name"], p["board"], p["fw"], outputs_of(p["doc"]),   # noqa: E731
                                        f"{p['gui']}/{p['fw']}/{p['name']}.cfg", purpose if (req.note or old is None) else old)
            new_text, readme_updated = readme_set_row(text, p["sys_name"], row)
            if readme_updated and new_text != text:
                write_like(t.readme, new_text)
            elif not readme_updated:
                notes.append("config/README.md has no System JSON index: add the row by hand")
        else:
            notes.append("config/README.md not found: no index row written")
        verdict = cfgapi.driver_verdict(driver_bin, p["src"])
        if verdict and verdict.get("available") and not verdict.get("ok"):
            notes.append("the driver's --validate reported errors for the source JSON")
        files = [{"id": f"shipped:radar/{p['gui']}/{p['fw']}/{p['name']}.cfg", "path": str(p["cfg_dst"]),
                  "action": "overwritten" if p["cfg_dst"].name in [Path(e).name for e in p["exists"]] else "created"},
                 {"id": f"shipped:system/{p['sys_name']}", "path": str(p["json_dst"]),
                  "action": "overwritten" if f"shipped:system/{p['sys_name']}" in p["exists"] else "created"}]
        return {"ok": True, "result": "overwritten" if p["exists"] else "created", "files": files, "backups": backups,
                "readme_updated": readme_updated, "driver": verdict, "git": git_status(t), "notes": notes,
                "commit_hint": "git add " + " ".join(hint_path(Path(f["path"])) for f in files) + " " + hint_path(t.readme)}

    def restore_hint(p: Path, tr="?") -> str:
        tr = tracked(t, p) if tr == "?" else tr
        if tr is True:
            return f"git restore -- {hint_path(p)}"
        if tr is False:
            return (f"not tracked in git, so git cannot restore it: it is moved to {t.user / TRASH}/<UTC>/ "
                    f"(move it back by hand)")
        return "git status unavailable here: restore it from version control or a copy"

    # -- delete -------------------------------------------------------------------------------------------------

    def plan_delete(req: DeleteReq) -> dict:
        ids = list(dict.fromkeys(req.ids))
        targets: dict[str, tuple[str, str, Path]] = {i: resolve_id(t, i) for i in ids}   # all validated before any change
        items = {i["id"]: i for i in scan(t)}
        if req.with_cfg:
            for id_, (group, kind, p) in list(targets.items()):
                if kind != "system_json":
                    continue
                cid = (items.get(id_) or {}).get("cfg")
                if not cid or cid in targets or not (items.get(cid) or {}):
                    continue
                if (items[cid]["group"] != group):
                    continue
                others = [x for x in items[cid].get("referenced_by", []) if x not in targets]
                if not others:
                    targets[cid] = resolve_id(t, cid)
        live = live_paths(mgr)
        tpl, moved = template_cfgs(t), moved_targets(t)
        refused, referenced = [], {}
        for id_, (group, kind, p) in targets.items():
            if p.resolve() in live:
                refused.append({"id": id_, "why": "in use by a running driver session: stop it first"})
            if id_ in tpl:
                refused.append({"id": id_, "why": f"template of firmware {', '.join(tpl[id_])}: the Configure tab needs it"})
            if kind == "radar_cfg":
                others = [x for x in items.get(id_, {}).get("referenced_by", []) if x not in targets]
                if others:
                    referenced[id_] = others
            if id_ in moved:
                referenced.setdefault(id_, []).append("config/moved_paths.json")
        shipped = [i for i, (g, _, _) in targets.items() if g == "shipped"]
        return {"targets": targets, "refused": refused, "referenced": referenced, "shipped": shipped, "items": items}

    @r.post("/delete")
    def delete(req: DeleteReq, dry: int = Query(0)):
        pl = plan_delete(req)
        targets = pl["targets"]
        ws = shipped_write_state(t)
        preview = {"would_remove": [{"id": i, "group": g, "kind": k,
                                     "action": "trash" if g == "user" or tracked(t, p) is not True else "unlink",
                                     "referenced_by": pl["referenced"].get(i, []),
                                     "tracked": tracked(t, p) if g == "shipped" else None,
                                     "restore": (restore_hint(p) if g == "shipped" else
                                                 f"mv {t.user / TRASH}/<UTC>/{p.name} {p}")}
                                    for i, (g, k, p) in targets.items()],
                   "refused": pl["refused"], "shipped_writes": ws,
                   "owner_warning": owner_warning(t, [*(p for _, _, p in targets.values()), *(p.parent for _, _, p in targets.values()),
                                                      t.user / TRASH, t.readme]),
                   "needs_confirm_shipped": bool(pl["shipped"]),
                   "needs_force_referenced": bool(pl["referenced"])}
        if dry:
            return {"dry": True, **preview}
        if pl["refused"]:
            raise HTTPException(409, {"message": "some files cannot be deleted", "refused": pl["refused"]})
        if not req.confirm:
            raise HTTPException(422, "confirm is required")
        if pl["shipped"]:
            if not ws["enabled"]:
                raise HTTPException(409, f"shipped configs cannot be written from this GUI: {ws['reason']}")
            if not req.confirm_shipped:
                raise HTTPException(422, {"message": "confirm_shipped is required to delete a shipped config",
                                          "shipped": pl["shipped"]})
        if pl["referenced"] and not req.force_referenced:
            raise HTTPException(409, {"message": "other files reference these: force_referenced to delete anyway",
                                      "referenced_by": pl["referenced"]})
        results, stamp = [], utc_stamp()
        readme_dirty = False
        text = t.readme.read_text() if t.readme.is_file() else None
        for id_, (group, kind, p) in targets.items():
            res = {"id": id_, "group": group}
            try:
                if group == "user":
                    d = t.user / TRASH / stamp
                    d.mkdir(parents=True, exist_ok=True)
                    dst, n = d / p.name, 1
                    while dst.exists():
                        dst, n = d / f"{p.name}.{n}", n + 1
                    shutil.move(str(p), str(dst))
                    res.update(ok=True, action="trashed", to=str(dst))
                else:
                    tr = tracked(t, p)
                    if tr is not True:   # never committed, or git cannot tell: git may not bring it back, so keep a copy in the trash
                        d = t.user / TRASH / stamp
                        d.mkdir(parents=True, exist_ok=True)
                        dst, n = d / p.name, 1
                        while dst.exists():
                            dst, n = d / f"{p.name}.{n}", n + 1
                        shutil.move(str(p), str(dst))
                        res.update(ok=True, action="trashed", to=str(dst), tracked=tr,
                                   restore=(f"untracked in git: moved to {dst}; move it back by hand" if tr is False else
                                            f"git status unavailable here: moved to {dst}; move it back by hand"))
                    else:
                        p.unlink()
                        res.update(ok=True, action="removed", tracked=tr, restore=restore_hint(p, tr))
                    if kind == "system_json" and text is not None:
                        text, hit = readme_drop_row(text, p.name)
                        readme_dirty = readme_dirty or hit
            except OSError as e:
                res.update(ok=False, error=str(e))
            results.append(res)
        readme_updated = False
        if readme_dirty and text is not None:
            write_like(t.readme, text)
            readme_updated = True
        notes = []
        if any(i in pl["referenced"] and any("moved_paths" in x for x in pl["referenced"][i]) for i in targets):
            notes.append("config/moved_paths.json still lists a deleted file: tests/test_config_tree.py (test_d) fails until "
                         "that entry is removed")
        if any(r_["ok"] and r_["group"] == "shipped" for r_ in results):
            notes.append("console radar setups may reference a deleted shipped JSON by name")
        return {"ok": all(r_["ok"] for r_ in results), "results": results, "readme_updated": readme_updated,
                "git": git_status(t), "notes": notes}

    return r
