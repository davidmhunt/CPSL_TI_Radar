import asyncio
import contextlib
import os
import time

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .cfgapi import make_router
from .driver import DriverManager
from .driver_api import make_router as make_driver_router
from .source_api import make_router as make_source_router
from .sources import DriverSource, Source

WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


class Hub:
    """Runs the current source and fans frames out to every connected browser (newest wins).
    `set_source` swaps the source at runtime (gui-06)."""

    def __init__(self, source: Source):
        self.source, self.clients = source, set()
        self.task = None
        self.spec = {"kind": source.name}   # what POST /api/source would need to recreate it
        self.replay_file = getattr(source, "path", None)   # remembered so replay -> mock -> replay needs no file
        self.status = {"type": "status", "state": "starting", "msg": "Starting"}
        self.frames = self.errors = self.gaps = 0
        self.last_t = None
        self.rate = 0.0

    def cfg_msg(self):
        sp = self.spec
        name = f"{self.source.name} source" + (f" · {sp['board']}" if sp.get("board") else "")
        if self.source.name == "none":
            name = ""
        return {"type": "cfg", "name": name, **self.source.info}

    def publish(self, msg):
        for q in list(self.clients):
            if q.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    q.get_nowait()
            q.put_nowait(msg)

    def set_status(self, state, msg):
        self.status = {"type": "status", "state": state, "msg": msg}
        self.publish(self.status)

    def start(self):
        self.task = asyncio.create_task(self.run())

    async def stop_source(self):
        task, self.task = self.task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self.source.release()

    async def set_source(self, new: Source, spec: dict | None = None):
        """Swap the running source. A source that needs the radar lock claims it first (raises PortBusy; the old
        source then keeps running), unless the old source holds it itself: then the old one is stopped first."""
        if not self.source.holds_lock:
            new.claim()
            await self.stop_source()
        else:
            await self.stop_source()
            try:
                new.claim()
            except Exception as e:
                self.set_status("ended", f"Source stopped ({e})")
                raise
        self.source, self.spec = new, spec or {"kind": new.name}
        self.replay_file = getattr(new, "path", None) or self.replay_file
        self.frames = self.errors = self.gaps = 0
        self.last_t, self.rate = None, 0.0
        if hasattr(new, "on_status"):
            new.on_status = self.set_status
        self.publish(self.cfg_msg())
        self.start()

    @property
    def following_run(self) -> bool:
        """True while the Live source is a driver run that is still going (the source card is read-only then)."""
        return isinstance(self.source, DriverSource) and self.source.running

    async def follow_driver(self, mgr, info: dict):
        """A GUI-started driver run begins: Live shows it (no radar lock to claim, the run holds it)."""
        new = DriverSource(mgr, info["run"], info["config"], info["pid"], info.get("tap_fd"))
        try:
            await self.set_source(new, new.spec)
        except Exception:
            new.release()
            raise

    async def run(self):
        if not getattr(self.source, "drives_status", False):
            self.set_status("streaming", "")
        elif hasattr(self.source, "on_status"):
            self.source.on_status = self.set_status
        try:
            async for fr in self.source.frames():
                now = time.monotonic()
                if self.last_t:
                    inst = 1 / max(now - self.last_t, 1e-6)
                    self.rate = 0.8 * self.rate + 0.2 * inst if self.rate else inst
                self.last_t = now
                self.frames += 1
                fr.setdefault("gaps", self.gaps)
                fr.setdefault("errors", self.errors)
                fr["rate"] = self.rate
                self.publish(fr)
            if not getattr(self.source, "finished_status", False):
                self.set_status("ended", "Source finished")
        except asyncio.CancelledError:
            raise
        except Exception as e:  # keep the page informed rather than dying silently
            self.set_status("error", f"Source failed: {e}")


def create_app(source: Source, user_cfg_dir=None, driver_bin=None, system_cfg_dir=None, run_root=None,
               min_stop_grace: float = 5.0, serial_factory=None) -> FastAPI:
    hub = Hub(source)
    loop_ref = {}

    def emit(msg):  # called from the driver's reader threads
        loop = loop_ref.get("loop")
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(hub.publish, msg)

    def on_run(info):   # a driver run was spawned (any thread): Live follows it
        loop = loop_ref.get("loop")
        if loop is None or loop.is_closed():
            return False
        asyncio.run_coroutine_threadsafe(hub.follow_driver(driver, info), loop)
        return True

    def owner_detail():   # who holds the board, for the refusal text
        sp = hub.spec
        return f" ({sp.get('cli_port')})" if hub.source.holds_lock and sp.get("cli_port") else ""

    driver = DriverManager(bin_override=driver_bin, run_root_override=run_root, emit=emit,
                           min_stop_grace=min_stop_grace, on_run=on_run, owner_detail=owner_detail)

    @contextlib.asynccontextmanager
    async def lifespan(app):
        loop_ref["loop"] = asyncio.get_running_loop()
        hub.start()
        yield
        await asyncio.to_thread(driver.shutdown)
        await hub.stop_source()

    app = FastAPI(title="CPSL radar GUI", lifespan=lifespan)
    app.state.hub, app.state.driver = hub, driver
    app.include_router(make_router(user_cfg_dir))
    app.include_router(make_driver_router(driver, user_cfg_dir, system_cfg_dir))
    app.include_router(make_source_router(hub, user_cfg_dir, serial_factory))

    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.get("/api/state")
    def state():
        return {"source": hub.source.name, "rate_hz": hub.source.rate_hz, "status": hub.status,
                "frames_sent": hub.frames, "cfg": hub.cfg_msg()}

    @app.websocket("/stream")
    async def stream(ws: WebSocket):
        await ws.accept()
        q = asyncio.Queue(maxsize=8)
        q.put_nowait(hub.status)
        q.put_nowait(hub.cfg_msg())
        q.put_nowait({"type": "driver_state", **driver.status(log=False)})
        hub.clients.add(q)
        try:
            while True:
                await ws.send_json(await q.get())
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            hub.clients.discard(q)

    @app.get("/")
    def index():
        return FileResponse(os.path.join(WEB, "index.html"), headers={"Cache-Control": "no-store"})

    app.mount("/", StaticFiles(directory=WEB), name="web")
    return app
