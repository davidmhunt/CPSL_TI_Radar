import asyncio
import contextlib
import os
import time

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .cfgapi import make_router
from .sources import Source

WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


class Hub:
    """Runs the source once and fans frames out to every connected browser (newest wins)."""

    def __init__(self, source: Source):
        self.source, self.clients = source, set()
        self.status = {"type": "status", "state": "starting", "msg": "Starting"}
        self.frames = self.errors = self.gaps = 0
        self.last_t = None
        self.rate = 0.0

    def cfg_msg(self):
        return {"type": "cfg", "name": f"{self.source.name} source", **self.source.info}

    def publish(self, msg):
        for q in list(self.clients):
            if q.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    q.get_nowait()
            q.put_nowait(msg)

    def set_status(self, state, msg):
        self.status = {"type": "status", "state": state, "msg": msg}
        self.publish(self.status)

    async def run(self):
        self.set_status("streaming", "")
        try:
            async for fr in self.source.frames():
                now = time.monotonic()
                if self.last_t:
                    inst = 1 / max(now - self.last_t, 1e-6)
                    self.rate = 0.8 * self.rate + 0.2 * inst if self.rate else inst
                self.last_t = now
                self.frames += 1
                fr.update(rate=self.rate, gaps=self.gaps, errors=self.errors)
                self.publish(fr)
            self.set_status("ended", "Source finished")
        except asyncio.CancelledError:
            raise
        except Exception as e:  # keep the page informed rather than dying silently
            self.set_status("error", f"Source failed: {e}")


def create_app(source: Source, user_cfg_dir=None) -> FastAPI:
    hub = Hub(source)

    @contextlib.asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(hub.run())
        yield
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    app = FastAPI(title="CPSL radar GUI", lifespan=lifespan)
    app.state.hub = hub
    app.include_router(make_router(user_cfg_dir))

    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.get("/api/state")
    def state():
        return {"source": source.name, "rate_hz": source.rate_hz, "status": hub.status,
                "frames_sent": hub.frames, "cfg": hub.cfg_msg()}

    @app.websocket("/stream")
    async def stream(ws: WebSocket):
        await ws.accept()
        q = asyncio.Queue(maxsize=8)
        q.put_nowait(hub.status)
        q.put_nowait(hub.cfg_msg())
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
