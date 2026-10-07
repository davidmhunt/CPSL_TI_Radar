"""Logs tab backend (gui-37 Step 2b): list, view and delete the GUI's run folders under the run root (`runs/gui/`).

Every path is confined: a session is addressed by the folder NAME only (`<UTC>_<name>[-N]`, a strict pattern: no `/`, no `..`),
the folder must be a real directory (not a symlink) whose realpath is a direct child of the run root, and only a fixed set of
file names can be read. Delete is explicit (POST with the exact names), refuses the running session (409) and never touches
anything outside the run root (`config/user/`, `runs/gui/dumps/` and every other folder are not addressable at all).
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from . import driver as driver_mod
from . import session_cfg
from .source_api import RUN_CAPTURE, run_dialect

NAME_RE = re.compile(r"^\d{8}T\d{6}Z_[A-Za-z0-9][A-Za-z0-9_.-]{0,100}$")
VIEW_FILES = (session_cfg.DRIVER_LOG, session_cfg.SESSION_JSON, session_cfg.CFG_COPY)
MAX_VIEW_BYTES = 2_000_000
MAX_DELETE = 200


class DeleteReq(BaseModel):
    names: list[str] = Field(min_length=1, max_length=MAX_DELETE)


def folder_size(d: Path) -> tuple[int, list[dict]]:
    files, total = [], 0
    for p in sorted(d.iterdir()):
        try:
            st = p.lstat()
        except OSError:
            continue
        if p.is_symlink() or not p.is_file():
            if p.is_dir() and not p.is_symlink():   # a nested folder (e.g. an output dir): count it, list it as a folder
                n = sum(f.lstat().st_size for f in p.rglob("*") if f.is_file() and not f.is_symlink())
                files.append({"name": p.name + "/", "size": n}); total += n
            continue
        files.append({"name": p.name, "size": st.st_size}); total += st.st_size
    return total, files


def make_router(mgr, run_root=None) -> APIRouter:
    r = APIRouter(prefix="/api/logs")

    def root() -> Path:
        return driver_mod.run_root(run_root).resolve()

    def session_dir(name: str) -> Path:
        """The folder of session `name`, or HTTPException: 422 for anything but a plain session folder name / an escaping path."""
        if not isinstance(name, str) or not NAME_RE.match(name) or ".." in name:
            raise HTTPException(422, f"{name!r} is not a session folder name")
        rt = root()
        p = rt / name
        if p.is_symlink() or p.resolve().parent != rt:
            raise HTTPException(422, f"{name!r} resolves outside the run folder")
        if not p.is_dir():
            raise HTTPException(404, f"no such session {name!r}")
        return p

    def running_name() -> str | None:
        st = mgr.status(log=False)
        return Path(st["run_dir"]).name if st.get("state") in ("running", "stopping") and st.get("run_dir") else None

    @r.get("")
    def listing():
        rt, run = root(), running_name()
        out = []
        for d in (sorted((p for p in rt.iterdir() if p.is_dir() and not p.is_symlink() and NAME_RE.match(p.name)), reverse=True) if rt.is_dir() else []):
            size, files = folder_size(d)
            try:
                started = datetime.strptime(d.name[:16], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).isoformat()
            except ValueError:
                started = None
            sj = {}
            try:
                sj = json.loads((d / session_cfg.SESSION_JSON).read_text())
            except (OSError, ValueError):
                pass
            board = Path(str(sj.get("board") or "")).stem or None
            out.append({"name": d.name, "label": d.name[17:], "started": started, "board": board,
                        "firmware": sj.get("firmware"), "size": size, "files": files, "running": d.name == run,
                        "has_log": (d / session_cfg.DRIVER_LOG).is_file(),
                        "replayable": (d / RUN_CAPTURE).is_file() and not (d / RUN_CAPTURE).is_symlink(),
                        "dialect": run_dialect(d) if (d / RUN_CAPTURE).is_file() else None,
                        "capture": str((d / RUN_CAPTURE).resolve()) if (d / RUN_CAPTURE).is_file() else None,
                        "saving": {k: bool((sj.get("output") or {}).get(k)) for k in session_cfg.SAVE_KEYS}})
        return {"root": str(rt), "running": run, "sessions": out, "total_size": sum(s["size"] for s in out)}

    @r.get("/{name}/file")
    def view(name: str, file: str = Query(session_cfg.DRIVER_LOG), tail: int = Query(500, ge=1, le=20000)):
        if file not in VIEW_FILES:
            raise HTTPException(422, f"file must be one of {list(VIEW_FILES)}")
        p = session_dir(name) / file
        if p.is_symlink() or not p.is_file():
            raise HTTPException(404, f"{name} has no {file}")
        size = p.stat().st_size
        with p.open("rb") as f:
            if size > MAX_VIEW_BYTES:
                f.seek(size - MAX_VIEW_BYTES)
            data = f.read(MAX_VIEW_BYTES)
        lines = data.decode("utf-8", "replace").split("\n")
        if size > MAX_VIEW_BYTES:
            lines = lines[1:]
        total = len(lines)
        return {"name": name, "file": file, "size": size, "text": "\n".join(lines[-tail:]), "lines": total,
                "truncated": size > MAX_VIEW_BYTES or total > tail}

    @r.post("/delete")
    def delete(req: DeleteReq):
        names = list(dict.fromkeys(req.names))
        dirs = [session_dir(n) for n in names]            # all names are validated before anything is removed
        run = running_name()
        if run in names:
            raise HTTPException(409, f"{run} is the running session: stop it first")
        freed = 0
        for d in dirs:
            freed += folder_size(d)[0]
            shutil.rmtree(d)                              # rmtree never follows symlinks inside
        return {"deleted": names, "freed": freed}

    return r
