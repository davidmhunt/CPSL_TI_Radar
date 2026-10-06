import argparse

import uvicorn

from .app import create_app
from .sources import make_source


def main():
    ap = argparse.ArgumentParser(prog="radar_gui", description="CPSL radar GUI server")
    ap.add_argument("--source", choices=["mock", "replay"], default="mock")
    ap.add_argument("--file", help="TLV byte dump for --source replay")
    ap.add_argument("--rate", type=float, default=10.0, help="frame rate in Hz (mock/replay)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args()
    app = create_app(make_source(a.source, rate_hz=a.rate, path=a.file))
    print(f"radar_gui: source={a.source}  open http://{a.host}:{a.port}/", flush=True)
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")


main()
