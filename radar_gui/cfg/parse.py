"""Parse a TI mmWave `.cfg` into a list of commands (pure Python, JSON-serialisable)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path


class CfgError(ValueError):
    """The cfg is missing something the maths needs, or a field is not a number."""


@dataclass
class Command:
    name: str
    args: list[str]
    line: int  # 1-based line number in the source text

    def floats(self) -> list[float]:
        try:
            return [float(a) for a in self.args]
        except ValueError as e:
            raise CfgError(f"line {self.line}: {self.name}: {e}") from None


@dataclass
class Cfg:
    commands: list[Command] = field(default_factory=list)
    source: str = ""  # file name when parsed from a path, else ""

    def all(self, name: str) -> list[Command]:
        return [c for c in self.commands if c.name == name]

    def first(self, name: str) -> Command | None:
        for c in self.commands:
            if c.name == name:
                return c
        return None

    def has(self, name: str) -> bool:
        return self.first(name) is not None

    def to_dict(self) -> dict:
        return asdict(self)


def parse_cfg(text: str, source: str = "") -> Cfg:
    """Parse cfg text. Blank lines and `%` / `#` comments (also trailing ones) are dropped."""
    cmds = []
    for i, raw in enumerate(text.splitlines(), 1):
        line = raw.split("%", 1)[0].strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        cmds.append(Command(parts[0], parts[1:], i))
    return Cfg(cmds, source)


def parse_cfg_file(path: str | Path) -> Cfg:
    p = Path(path)
    return parse_cfg(p.read_text(errors="replace"), p.name)
