"""Tune API (radar-37): an RX-gain sweep as a background job, /api/tune/{info,start,status,cancel}.

One sweep = one run folder `runs/gui/<UTC>_tune_<config>/` holding the base cfg copy (`radar.cfg`), `tune.json` (params, rows,
suggestion), `tune.csv`, `plot.json`, and one `step_g<NN>/` per gain (the cfg copy at that gain, its temporary system JSON,
the driver run folder with session.json / driver.log, and out/chirp_meta.csv). A step is a FULL reconfigure by a fresh driver run on a temporary cfg copy + system
JSON copy (a profileCfg-only change between sensorStop/sensorStart is rejected by the firmware: radar-37 Step 1, runs/radar37_gate)
-- no power cycle. The sweep never applies anything to the user's setup and never opens `config/user/` for write: that
directory is only read (the base system JSON and its cfg are copied from it).

Steps run on a PRIVATE DriverManager that shares the process-wide radar lock, so a sweep cannot start while any driver run
holds the radar, and the app's own driver refuses to start while a sweep is active (`extern_busy`). The ADC frames come off the
private run's tap pipe; the firmware's per-chirp saturation counter comes from the run's `out/chirp_meta.csv`.
"""
from __future__ import annotations

import csv
import json
import os
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import adc, session_cfg, tap, tune
from .cfg import analog
from .cfg import firmware as fwmod
from .cfg import limits as limmod
from .cfgapi import DEFAULT_USER_DIR
from .driver import REPO, DriverError, DriverManager, run_root
from .driver_api import DEFAULT_SYSTEM_DIR, list_configs
from .ports import radar_lock

STEP_FILES = ("tune.json", "tune.csv", "plot.json", "radar.cfg")


class StartReq(BaseModel):
    config: str                                   # a saved system JSON listed by GET /api/driver/configs
    gain_min: int
    gain_max: int
    gain_step: int = Field(2, ge=1)
    frames: int = Field(tune.DEFAULT_FRAMES, ge=1, le=64)
    margin_db: float = Field(tune.DEFAULT_MARGIN_DB, ge=0, le=30)
    exclude_m: float | None = Field(None, ge=0)   # DC/leakage exclusion radius; None = 5 range bins of the config
    adc_bits: int | None = Field(None, ge=8, le=16)   # override; None = derived from the cfg's adcCfg numADCBits


def _board_firmware(doc: dict) -> tuple[str | None, str | None]:
    board = doc.get("board")
    gb = fwmod.gui_board(board) if isinstance(board, str) and board else None
    return gb, doc.get("firmware") if isinstance(doc.get("firmware"), str) else None


def gain_range_of(doc: dict) -> dict | None:
    """The board's {min, max, step, ...} RX gain (radar-36) for a system JSON's board/firmware, or None."""
    gb, fw = _board_firmware(doc)
    if not gb:
        return None
    try:
        lim = limmod.firmware_limits(gb, fw) if fw else limmod.BOARD_LIMITS.get(gb)
    except Exception:
        lim = None
    return analog.gain_range(lim) if lim else None


class Sweep:
    """State of the newest sweep (the page polls it)."""

    def __init__(self, name: str, config: str, params: dict):
        self.name, self.config, self.params = name, config, params
        self.state, self.error = "running", None
        self.step, self.steps, self.gain_db, self.phase = 0, len(params["gains"]), None, "start"
        self.rows, self.suggestion = [], None
        self.cancel = threading.Event()
        self.t_start, self.t_end = time.time(), None
        self.dir: Path | None = None

    def status(self) -> dict:
        return {"state": self.state, "name": self.name, "config": self.config, "run_dir": str(self.dir) if self.dir else None,
                "step": self.step, "steps": self.steps, "gain_db": self.gain_db, "phase": self.phase,
                "rows": [dict(r) for r in self.rows], "suggestion": self.suggestion, "error": self.error,
                "params": self.params, "started": self.t_start, "ended": self.t_end}


class TuneManager:
    def __init__(self, main_driver: DriverManager | None = None, user_dir=None, system_dir=None, driver_bin=None, run_root_dir=None):
        self.main, self.bin_override, self.root_override = main_driver, driver_bin, run_root_dir
        self.user_dir = Path(user_dir or os.environ.get("RADAR_GUI_USER_CFG_DIR") or DEFAULT_USER_DIR)
        self.system_dir = Path(system_dir) if system_dir else DEFAULT_SYSTEM_DIR
        self.sweep: Sweep | None = None
        self._mu = threading.Lock()
        self._thread: threading.Thread | None = None
        self._dm: DriverManager | None = None

    # ---- helpers ------------------------------------------------------------------------------------------
    def resolve(self, config: str) -> Path:
        """Only configs that GET /api/driver/configs lists may be swept (the API is reachable over a tailnet)."""
        p = (REPO / config).resolve()
        listed = {(REPO / c["path"]).resolve() for c in list_configs(self.user_dir, self.system_dir)}
        if p not in listed:
            raise HTTPException(422, f"{config!r} is not a system config in config/user or config/system")
        return p

    @property
    def active(self) -> bool:
        return self.sweep is not None and self.sweep.state == "running"

    def busy_reason(self) -> str | None:
        """For the app's DriverManager.start (`extern_busy`): why a driver run may not start right now."""
        return "a gain sweep (Tune) is running; cancel it or wait for it to finish" if self.active else None

    def _driver_busy(self) -> str | None:
        if self.active:
            return "a gain sweep is already running"
        if self.main is not None and self.main.state in ("running", "stopping"):
            return "a driver run is active: stop it before sweeping the gain (a sweep reconfigures the radar at every step)"
        if radar_lock.owner is not None:
            return f"radar in use by {radar_lock.owner}"
        return None

    def info(self, config: str) -> dict:
        p = self.resolve(config)
        try:
            doc = json.loads(p.read_text())
            cfg_text = (p.parent / str(doc["radar_cfg"])).read_text(errors="replace")
        except (OSError, ValueError, KeyError) as e:
            raise HTTPException(422, f"cannot read {p.name} or its cfg: {e}")
        try:
            word = tune.read_rx_gain(cfg_text)
        except tune.TuneError as e:
            raise HTTPException(422, str(e))
        geom_err, ex = "", None
        try:
            ex = tune.exclusion_m(adc.Geometry.from_system_json(p))
        except Exception as e:
            geom_err = f"cannot build the ADC geometry from this config: {e}"
        adc_bits, adc_src = tune.adc_bits_from_cfg(cfg_text)
        gb, fw = _board_firmware(doc)
        dca = bool((doc.get("dca1000") or {}).get("enabled"))
        return {"config": config, "name": p.stem, "board": gb, "firmware": fw, "gain_range": gain_range_of(doc),
                "current_rx_gain_word": word, "current_gain_db": word & tune.GAIN_MASK,
                "dca1000": dca, "exclude_m": ex, "error": geom_err or (None if dca else "this config has the DCA1000 stream off: the sweep needs raw ADC"),
                "defaults": {"frames": tune.DEFAULT_FRAMES, "margin_db": tune.DEFAULT_MARGIN_DB,
                             "tol_db": tune.DEFAULT_TOL_DB, "min_snr_db": tune.DEFAULT_MIN_SNR_DB,
                             "adc_bits": adc_bits, "adc_bits_source": adc_src, "settle_frames": tune.SETTLE_FRAMES}}

    # ---- start / cancel ---------------------------------------------------------------------------------------
    def start(self, req: StartReq) -> dict:
        p = self.resolve(req.config)
        try:
            doc = json.loads(p.read_text())
            base_cfg = (p.parent / str(doc["radar_cfg"])).read_text(errors="replace")
        except (OSError, ValueError, KeyError) as e:
            raise HTTPException(422, f"cannot read {p.name} or its cfg: {e}")
        if not (doc.get("dca1000") or {}).get("enabled"):
            raise HTTPException(422, "this config has the DCA1000 stream off: the sweep needs raw ADC")
        rng = gain_range_of(doc)
        try:
            gains = tune.gain_grid(req.gain_min, req.gain_max, req.gain_step, rng)
            tune.read_rx_gain(base_cfg)
            geom = adc.Geometry.from_system_json(p)
        except (tune.TuneError, adc.AdcError, ValueError, KeyError) as e:
            raise HTTPException(422, str(e))
        except Exception as e:
            raise HTTPException(422, f"cannot build the ADC geometry from this config: {e}")
        ex = float(req.exclude_m) if req.exclude_m is not None else tune.exclusion_m(geom)
        with self._mu:
            why = self._driver_busy()
            if why:
                raise HTTPException(409, why)
            abits, asrc = (req.adc_bits, "override") if req.adc_bits else tune.adc_bits_from_cfg(base_cfg)
            params = {"gains": gains, "frames": req.frames, "margin_db": req.margin_db, "tol_db": tune.DEFAULT_TOL_DB,
                      "min_snr_db": tune.DEFAULT_MIN_SNR_DB, "exclude_m": ex, "adc_bits": abits,
                      "adc_bits_source": asrc, "gain_range": rng, "settle_frames": tune.SETTLE_FRAMES}
            sw = Sweep(f"tune_{session_cfg.safe_name(p.stem)}", req.config, params)
            self.sweep = sw
            self._thread = threading.Thread(target=self._run, args=(sw, p, doc, base_cfg, geom), daemon=True, name="tune-sweep")
            self._thread.start()
        return sw.status()

    def cancel(self) -> dict:
        sw = self.sweep
        if sw is None or sw.state != "running":
            raise HTTPException(409, "no sweep is running")
        sw.cancel.set()
        dm = self._dm
        if dm is not None:
            try:
                dm.stop()
            except DriverError:
                pass
        return sw.status()

    def shutdown(self):
        sw = self.sweep
        if sw is not None and sw.state == "running":
            sw.cancel.set()
            dm = self._dm
            if dm is not None:
                dm.shutdown()
            if self._thread is not None:
                self._thread.join(timeout=10)

    # ---- the job ---------------------------------------------------------------------------------------------
    def _make_dir(self, name: str) -> Path:
        root = run_root(self.root_override)
        root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        for i in range(1, 100):
            d = root / (f"{stamp}_{name}" if i == 1 else f"{stamp}_{name}-{i}")
            try:
                d.mkdir()
                return d
            except FileExistsError:
                continue
        raise RuntimeError(f"cannot create a sweep folder under {root}")

    def _step_json(self, doc: dict, src: Path, cfg_path: Path, out_dir: Path) -> dict:
        """The temporary system JSON of one step: the base's, pointing at the step's cfg copy, output into the sweep folder,
        reconfigure forced (never skip_configure), save flags only what the sweep needs."""
        d = json.loads(json.dumps(doc))
        d["radar_cfg"] = str(cfg_path)
        b = d.get("board")
        if isinstance(b, str) and b and ("/" in b or b.endswith(".json")):
            d["board"] = str((src.parent / b).resolve())
        d["output"] = {"save_adc_frames": True, "save_raw_lvds": False, "dir": str(out_dir)}
        rt = dict(d.get("runtime") or {})
        rt.pop("skip_configure", None)
        d["runtime"] = rt
        return d

    def _run(self, sw: Sweep, src: Path, doc: dict, base_cfg: str, geom: adc.Geometry):
        try:
            sw.dir = self._make_dir(sw.name)
            (sw.dir / session_cfg.CFG_COPY).write_text(base_cfg)
            (sw.dir / "base_system.json").write_text(json.dumps(doc, indent=2) + "\n")
            self._save(sw, "running")
            dm = DriverManager(bin_override=self.bin_override, run_root_override=sw.dir, on_run=self._take_tap)
            self._dm = dm
            p = sw.params
            result = tune.run_sweep(
                base_cfg, p["gains"], p["frames"], lambda g, text, n: self._capture(sw, dm, doc, src, geom, g, text, n), geom,
                rng=p["gain_range"], margin_db=p["margin_db"], tol_db=p["tol_db"], min_snr_db=p["min_snr_db"],
                exclude_m=p["exclude_m"], adc_bits=p["adc_bits"], cancelled=sw.cancel.is_set,
                progress=lambda m: self._progress(sw, m))
            sw.rows, sw.suggestion = result["rows"], result["suggestion"]
            sw.state = "cancelled" if result["cancelled"] or sw.cancel.is_set() else "done"
        except Exception as e:     # a failed step names itself; rows so far stay in the table and the folder
            sw.state, sw.error = "failed", f"{type(e).__name__}: {e}" if not isinstance(e, (tune.TuneError, DriverError)) else str(e)
            if sw.cancel.is_set():
                sw.state, sw.error = "cancelled", None
        finally:
            sw.phase, sw.t_end = "end", time.time()
            self._dm = None
            try:
                self._save(sw, sw.state)
            except OSError:
                pass

    def _progress(self, sw: Sweep, m: dict):
        sw.step, sw.steps, sw.gain_db, sw.phase = m["step"], m["steps"], m["gain_db"], m["phase"]
        if m.get("row"):
            sw.rows.append(m["row"])

    def _save(self, sw: Sweep, state: str):
        if sw.dir is None:
            return
        doc = {"schema": 1, "directive": "radar-37", "state": state, "error": sw.error, "config": sw.config,
               "params": sw.params, "rows": sw.rows, "suggestion": sw.suggestion, "started": sw.t_start, "ended": sw.t_end,
               "note": "suggestion only; nothing was applied to any setup"}
        (sw.dir / "tune.json").write_text(json.dumps(doc, indent=2) + "\n")
        if sw.rows:
            (sw.dir / "tune.csv").write_text(tune.rows_csv(sw.rows))
            (sw.dir / "plot.json").write_text(json.dumps({
                "gain_db": [r["gain_db"] for r in sw.rows], "peak_db": [r["peak_db"] for r in sw.rows],
                "noise_db": [r["noise_db"] for r in sw.rows], "headroom_db": [r["headroom_db"] for r in sw.rows],
                "saturated": [bool(r.get("sat_chirps") or r.get("clipped")) for r in sw.rows]}) + "\n")

    # ---- one gain step: a fresh driver run -------------------------------------------------------------------
    def _take_tap(self, info: dict) -> bool:
        """DriverManager.on_run of the private manager: take over the run's tap fd for the capture thread."""
        fd = info.get("tap_fd")
        if fd is None:
            return False
        cap = self._cap
        cap["fd"] = fd
        t = threading.Thread(target=self._read_tap, args=(cap,), daemon=True, name="tune-tap")
        cap["thread"] = t
        t.start()
        return True

    _cap: dict = {}

    def _read_tap(self, cap: dict):
        fd, geom, want = cap["fd"], cap["geom"], cap["want"]
        try:
            while not cap["stop"].is_set():
                kind, payload = tap.read_message(fd, cap["stop"].is_set)
                if kind != tap.ADC:
                    continue
                head, data = tap.decode_adc(payload)
                try:
                    a, partial = adc.decode(head, data, geom)
                except adc.AdcError as e:
                    cap["bad"] = str(e)
                    continue
                cap["seen"] += 1
                if partial or cap["seen"] <= tune.SETTLE_FRAMES:
                    continue
                cap["frames"].append(a)
                if len(cap["frames"]) >= want:
                    break
        except (tap.TapClosed, OSError, ValueError):
            pass
        finally:
            try:
                os.close(fd)
            except OSError:
                pass
            cap["done"].set()

    def _capture(self, sw: Sweep, dm: DriverManager, doc: dict, src: Path, geom: adc.Geometry, gain: int, text: str,
                 n_frames: int) -> tune.Capture:
        step = sw.dir / f"step_g{gain:02d}"
        out = step / "out"
        out.mkdir(parents=True)
        cfg_path = step / "step.cfg"
        cfg_path.write_text(text)
        sj = step / f"gain_{gain:02d}.json"
        sj.write_text(json.dumps(self._step_json(doc, src, cfg_path, out), indent=2) + "\n")
        rate = geom.frame_rate_hz or 4.0
        dm.root_override = step      # this step's driver run folder (session.json, radar.cfg copy, driver.log) nests in it
        cap = {"geom": geom, "want": n_frames, "frames": [], "seen": 0, "bad": None, "stop": threading.Event(), "done": threading.Event()}
        self._cap = cap
        try:
            st = dm.start(config=str(sj), adc_every=1, duration=20 + 3 * (n_frames + tune.SETTLE_FRAMES + 2) / max(rate, 0.1))
        except DriverError as e:
            raise tune.TuneError(f"gain {gain} dB: driver start failed: {e}")
        if not dm.tap == "on" or not cap.get("thread"):
            self._finish_run(dm)
            raise tune.TuneError(f"gain {gain} dB: this driver build has no live ADC tap (rebuild the driver)")
        deadline = time.monotonic() + 20 + 3 * (n_frames + tune.SETTLE_FRAMES + 2) / max(rate, 0.1)
        while not cap["done"].wait(0.2):
            if sw.cancel.is_set() or time.monotonic() > deadline:
                break
        timed_out = not cap["done"].is_set() and not sw.cancel.is_set()
        cap["stop"].set()
        self._finish_run(dm)
        cap["done"].wait(2)
        if sw.cancel.is_set():
            raise tune.TuneError("cancelled")
        frames = cap["frames"]
        if len(frames) < n_frames:
            s = dm.status()
            tail = " | ".join(l for l in (s.get("log") or [])[-4:] if l.strip())
            why = s.get("error") or (cap["bad"] and f"bad ADC message: {cap['bad']}") or ("timed out waiting for ADC frames" if timed_out else "the driver stopped early")
            ff = s.get("cli_first_fail")
            if ff is not None and s.get("cli"):
                e = s["cli"][ff]
                why = f"the board rejected `{e.get('cmd')}`: {e.get('reply') or e.get('verdict')}"
            raise tune.TuneError(f"gain {gain} dB: got {len(frames)} of {n_frames} ADC frames - {why}" + (f" [{tail}]" if tail else ""))
        sat, chirps = self._sat(out, tune.SETTLE_FRAMES, tune.SETTLE_FRAMES + n_frames)
        try:
            (out / "adc_data.bin").unlink()      # the frames are measured from the tap; the multi-MB file is not kept
        except OSError:
            pass
        return tune.Capture(frames[:n_frames], sat, chirps, {"run_dir": dm.status(log=False).get("run_dir")})

    def _finish_run(self, dm: DriverManager):
        """Stop the step's driver run (if still going) and wait for it to leave running/stopping."""
        try:
            if dm.state == "running":
                dm.stop()
        except DriverError:
            pass
        end = time.monotonic() + 30
        while dm.state in ("running", "stopping") and time.monotonic() < end:
            time.sleep(0.05)

    @staticmethod
    def _sat(out: Path, lo: int, hi: int) -> tuple[int | None, int]:
        """(saturated chirps, chirps examined) over driver frames lo..hi-1 from out/chirp_meta.csv; (None, 0) = the firmware
        writes no per-chirp saturation (the file is only produced for the adc_sar_meta stream)."""
        p = out / "chirp_meta.csv"
        if not p.is_file():
            return None, 0
        sat = n = 0
        with p.open(newline="") as f:
            for row in csv.DictReader(f):
                try:
                    fr = int(row["frame"])
                    v = row.get("sat_slices_this_chirp", "")
                except (KeyError, ValueError, TypeError):
                    continue
                if not lo <= fr < hi or v in ("", None):
                    continue
                n += 1
                try:
                    sat += int(float(v)) > 0
                except ValueError:
                    continue
        return (sat, n) if n else (None, 0)


def make_router(mgr: TuneManager) -> APIRouter:
    r = APIRouter(prefix="/api/tune")

    @r.get("/info")
    def info(config: str):
        return mgr.info(config)

    @r.post("/start")
    def start(req: StartReq):
        return mgr.start(req)

    @r.get("/status")
    def status():
        sw = mgr.sweep
        return sw.status() if sw else {"state": "idle", "rows": [], "suggestion": None, "error": None}

    @r.post("/cancel")
    def cancel():
        return mgr.cancel()

    return r
