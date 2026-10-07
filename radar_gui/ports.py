"""One-radar-at-a-time guard: a process-wide lock plus a "who holds this serial port" scan (stdlib, /proc)."""
from __future__ import annotations

import os
import threading


class RadarLock:
    """One session at a time (driver run now, gui-06 serial source next). Non-blocking."""

    def __init__(self):
        self._lock, self._owner = threading.Lock(), None

    def acquire(self, owner: str) -> bool:
        if self._lock.acquire(blocking=False):
            self._owner = owner
            return True
        return False

    def release(self, owner: str | None = None) -> None:
        if self._owner is not None and (owner is None or owner == self._owner):
            self._owner = None
            self._lock.release()

    @property
    def owner(self):
        return self._owner


radar_lock = RadarLock()  # the process-wide instance


def resolve(port: str) -> str:
    """Follow /dev/serial/by-id (and any other) symlinks to the real device node."""
    return os.path.realpath(port)


def holders(port: str, proc: str = "/proc") -> list[tuple[int, str]]:
    """(pid, comm) of every other process with `port` open, found by scanning <proc>/*/fd."""
    target, me, out = resolve(port), os.getpid(), []
    try:
        pids = [p for p in os.listdir(proc) if p.isdigit()]
    except OSError:
        return out
    for pid in pids:
        if int(pid) == me:
            continue
        fddir = os.path.join(proc, pid, "fd")
        try:
            fds = os.listdir(fddir)
        except OSError:  # gone, or not ours to read
            continue
        for fd in fds:
            try:
                if os.path.realpath(os.path.join(fddir, fd)) == target:
                    try:
                        with open(os.path.join(proc, pid, "comm")) as f:
                            comm = f.read().strip()
                    except OSError:
                        comm = "?"
                    out.append((int(pid), comm))
                    break
            except OSError:
                continue
    return out


def check_ports(ports: list[str]) -> str | None:
    """None if every port exists and is free, else the refusal message."""
    for p in ports:
        if not os.path.exists(p):
            return f"port {p} not found (is the radar plugged in?)"
    for p in ports:
        h = holders(p)
        if h:
            return f"ports busy: {p} held by {h[0][0]} {h[0][1]}"
    return None
