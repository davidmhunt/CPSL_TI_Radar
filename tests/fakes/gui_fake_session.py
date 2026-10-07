#!/usr/bin/env python3
"""radar_gui server for gui_shots (gui-37) with the quick-setup port allowlist and the port-busy check lifted, so a quick setup
can name the scratch "port" file and start the fake driver (tests/fakes/fake_driver.py). Test scaffolding only: never use it with a
real radar. Same argv as `python -m radar_gui`."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from radar_gui import driver, ports, session_cfg  # noqa: E402
from radar_gui.__main__ import main  # noqa: E402

session_cfg.PORT_NAME = re.compile(r"^.+$")
ports.check_ports = driver.check_ports = lambda p: None
main()
