#!/usr/bin/env python3
"""Fake TI CLI board on a pseudo-terminal, for gui_shots (no hardware).

    fake_board_pty.py <symlink> [--reject CMD_PREFIX] [--silent CMD_PREFIX]

Creates a pty, symlinks its slave at <symlink>, and answers every CLI line like the IWR demo: echo, `Done`, prompt.
A line starting with --reject gets "Error: ... | Error -1" instead; one starting with --silent gets no reply (timeout).
Runs until killed."""
import os
import pty
import sys
import time

args = sys.argv[1:]
link = args[0]
reject = args[args.index("--reject") + 1] if "--reject" in args else None
silent = args[args.index("--silent") + 1] if "--silent" in args else None
master, slave = pty.openpty()
if os.path.islink(link) or os.path.exists(link):
    os.remove(link)
os.symlink(os.ttyname(slave), link)
os.close(slave)          # hold only the master: the GUI's port-holder scan must not see this process on the slave
buf = b""
while True:
    try:
        data = os.read(master, 256)
    except OSError:          # the reader closed its end; wait for the next open
        time.sleep(0.05)
        continue
    buf += data
    while b"\n" in buf:
        line, buf = buf.split(b"\n", 1)
        cmd = line.decode(errors="replace").strip()
        if not cmd:
            continue
        if silent and cmd.startswith(silent):
            out = f"{cmd}\r\n"
        elif reject and cmd.startswith(reject):
            out = (f"{cmd}\r\nError: Full configuration must be provided before sensor can be started the first time\r\n"
                   "Error -1\r\nmmwDemo:/>")
        else:
            out = f"{cmd}\r\nDone\r\nmmwDemo:/>"
        os.write(master, out.encode())
