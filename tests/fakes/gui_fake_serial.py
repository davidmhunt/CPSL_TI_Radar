#!/usr/bin/env python3
"""radar_gui server for gui_shots with the serial-port allowlist opened up (so a pty fake board, see fake_board_pty.py,
can stand in for /dev/serial/by-id/...). Test scaffolding only: never use it with a real radar. Same argv as `python -m radar_gui`."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from radar_gui import source_api  # noqa: E402
from radar_gui.__main__ import main  # noqa: E402

source_api.PORT_NAME = re.compile(r"^.+$")
main()
