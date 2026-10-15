"""Suite-wide safety nets (gui-09 D13: the full suite hung intermittently under machine load)."""
import anyio
import pytest
from starlette.testclient import WebSocketTestSession

WS_RECEIVE_TIMEOUT_S = 30


@pytest.fixture(autouse=True)
def _bounded_ws_receive(monkeypatch):
    """Starlette's WebSocketTestSession.receive() blocks forever when the server sends nothing more. Several tests
    loop on ws.receive_json() under a wall-clock deadline that is only checked BETWEEN messages, so a quiet stream
    (a fake driver that exited early, a Hub queue that dropped the awaited message) hung the whole run.
    HYPOTHESIS (not reproduced in 18 loaded runs): that is the intermittent hang. Bounded here, a stuck receive
    fails that one test with TimeoutError instead."""
    def receive(self):
        async def bounded():
            with anyio.fail_after(WS_RECEIVE_TIMEOUT_S):
                return await self._send_rx.receive()
        return self.portal.call(bounded)
    monkeypatch.setattr(WebSocketTestSession, "receive", receive)


@pytest.fixture(autouse=True)
def _no_host_radar_links(tmp_path, monkeypatch):
    """radar-41: port defaults prefer /dev/radar links; the suite must not see the host's."""
    from radar_gui import session_cfg
    monkeypatch.setattr(session_cfg, "RADAR_DIR", str(tmp_path / "no-dev-radar"))
