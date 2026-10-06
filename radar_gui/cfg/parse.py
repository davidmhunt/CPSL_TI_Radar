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

    # --- chirp-loop model (gui-14) -----------------------------------------------------------
    @property
    def chirp_sequence(self) -> list[tuple[int, int]]:
        """Every chirp the cfg defines as (chirp index, TX enable mask), sorted by index; masks of
        overlapping chirpCfg ranges are OR-ed (as `chirp_tx_masks` always did)."""
        masks: dict[int, int] = {}
        for c in self.all("chirpCfg"):
            a = c.floats()
            if len(a) < 8:
                raise CfgError(f"line {c.line}: chirpCfg needs 8 fields, got {len(a)}")
            for i in range(int(a[0]), int(a[1]) + 1):
                masks[i] = masks.get(i, 0) | int(a[7])
        return sorted(masks.items())

    def chirp_profile_id(self, chirp: int) -> int | None:
        """profileId of the first chirpCfg covering `chirp` (None when no chirpCfg covers it)."""
        for c in self.all("chirpCfg"):
            a = c.floats()
            if len(a) >= 8 and int(a[0]) <= chirp <= int(a[1]):
                return int(a[2])
        return None

    @property
    def bpm_enabled(self) -> bool:
        """`bpmCfg <subFrame> <isEnabled> <chirp0> <chirp1>`: True when any bpmCfg has isEnabled != 0."""
        for c in self.all("bpmCfg"):
            a = c.floats()
            if len(a) >= 2 and int(a[1]) != 0:
                return True
        return False

    @property
    def subframes(self) -> list[dict]:
        """Advanced-frame subframes (empty for a plain frameCfg cfg). `advFrameCfg <n> ...` declares n;
        `subFrameCfg <idx> <forceProfile> <chirpStart> <numChirps> <numLoops> <burstPeriod> <chirpOffset>
        <numBurst> <numBurstLoops> <subFramePeriod>`. Dict keys: index, chirp_start, num_chirps, num_loops,
        period (subFramePeriod, raw)."""
        adv = self.first("advFrameCfg")
        if adv is None:
            return []
        out = []
        for c in self.all("subFrameCfg"):
            a = c.floats()
            if len(a) < 5:
                raise CfgError(f"line {c.line}: subFrameCfg needs at least 5 fields, got {len(a)}")
            out.append(dict(index=int(a[0]), chirp_start=int(a[2]), num_chirps=int(a[3]), num_loops=int(a[4]),
                            period=a[9] if len(a) > 9 else 0.0))
        out.sort(key=lambda d: d["index"])
        n = int(adv.floats()[0]) if adv.args else len(out)
        if len(out) != n:
            raise CfgError(f"line {adv.line}: advFrameCfg declares {n} subframes but the cfg has {len(out)} subFrameCfg")
        return out


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
