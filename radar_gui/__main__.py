import argparse
import signal

import uvicorn

from .app import create_app
from .sources import make_source
from .tailscale import TailscaleServe, bind_addresses, bind_sockets


def parse_args(argv=None):
    ap = argparse.ArgumentParser(prog="radar_gui", description="CPSL radar GUI server")
    ap.add_argument("--source", choices=["none", "mock", "replay"], default="none",
                    help="none (default): the Live tab waits for Serial/Replay/a driver run; mock is for tests and shots")
    ap.add_argument("--file", help="TLV byte dump for --source replay")
    ap.add_argument("--rate", type=float, default=10.0, help="frame rate in Hz (mock/replay)")
    ap.add_argument("--driver-bin", help="C++ driver binary for the Run tab (default CPSL_TI_Radar_cpp/build/CPSL_TI_Radar_CPP, "
                                         "or $RADAR_GUI_DRIVER)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--tailscale", nargs="?", const="bind", choices=["bind", "serve"],
                    help="reach the GUI over your tailnet: also listen on this machine's Tailscale IP "
                         "(plain HTTP, no privileges needed); `--tailscale=serve` = --tailscale-serve. "
                         "The GUI has no authentication")
    ap.add_argument("--tailscale-serve", dest="tailscale", action="store_const", const="serve",
                    help="share via `tailscale serve` (HTTPS; needs tailnet HTTPS certificates and "
                         "operator rights; removed on exit)")
    return ap.parse_args(argv)


def main(argv=None):
    a = parse_args(argv)
    app = create_app(make_source(a.source, rate_hz=a.rate, path=a.file), driver_bin=a.driver_bin)
    print(f"radar_gui: source={a.source}  open http://{a.host}:{a.port}/", flush=True)
    ts, socks = None, None
    if a.tailscale:
        # SIGTERM -> same clean shutdown path as Ctrl-C (finally below runs)
        signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    if a.tailscale == "serve":
        ts = TailscaleServe(a.port)
        ts.start()
    elif a.tailscale == "bind":
        ip, short, why = bind_addresses()
        if ip is None:
            print(f"radar_gui: --tailscale: {why}. Serving locally only.", flush=True)
        else:
            try:
                socks = bind_sockets(a.host, a.port, ip)
            except (OSError, ValueError) as e:
                print(f"radar_gui: --tailscale: cannot listen on {ip}:{a.port} ({e}). "
                      "Serving locally only.", flush=True)
            else:
                print(f"GUI on tailnet: http://{ip}:{a.port}/", flush=True)
                if short:
                    print(f"GUI on tailnet: http://{short}:{a.port}/", flush=True)
                print("radar_gui: no authentication: any tailnet peer your ACLs allow can reach this.",
                      flush=True)
    try:
        if socks:
            cfg = uvicorn.Config(app, host=a.host, port=a.port, log_level="warning")
            uvicorn.Server(cfg).run(sockets=socks)
        else:
            uvicorn.run(app, host=a.host, port=a.port, log_level="warning")
    finally:
        for s in socks or []:
            s.close()
        if ts:
            ts.stop()


if __name__ == "__main__":
    main()
