import argparse
import signal

import uvicorn

from .app import create_app
from .sources import make_source
from .tailscale import TailscaleServe


def parse_args(argv=None):
    ap = argparse.ArgumentParser(prog="radar_gui", description="CPSL radar GUI server")
    ap.add_argument("--source", choices=["mock", "replay"], default="mock")
    ap.add_argument("--file", help="TLV byte dump for --source replay")
    ap.add_argument("--rate", type=float, default=10.0, help="frame rate in Hz (mock/replay)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--tailscale", action="store_true",
                    help="also share on your tailnet via `tailscale serve` (HTTPS, tailnet-only, "
                         "removed on exit); the GUI has no authentication")
    return ap.parse_args(argv)


def main(argv=None):
    a = parse_args(argv)
    app = create_app(make_source(a.source, rate_hz=a.rate, path=a.file))
    print(f"radar_gui: source={a.source}  open http://{a.host}:{a.port}/", flush=True)
    ts = TailscaleServe(a.port) if a.tailscale else None
    if ts:
        # SIGTERM -> same clean shutdown path as Ctrl-C (finally below runs)
        signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
        ts.start()
    try:
        uvicorn.run(app, host=a.host, port=a.port, log_level="warning")
    finally:
        if ts:
            ts.stop()


if __name__ == "__main__":
    main()
