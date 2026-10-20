"""profileCfg analog front-end facts: the HPF corner tables, the rxGain word and the usable IF band.

All values come from the per-board `limits` of the firmware descriptors (config/firmware/<id>.json, each with
level/source/confidence; memo docs/developer/radar_notes.md#hpf-rxgain-and-adc); nothing here is a table. This module
only interprets them. Keys (per chip board):

  hpf1_corner_khz, hpf2_corner_khz   list of kHz, index = the profileCfg hpf code
  rx_gain_min_db, rx_gain_max_db, rx_gain_step_db
                                     the valid RX gain, applied to rxGain bits 5:0 ONLY
  rx_gain_rf_target_db               list indexed by rxGain bits 7:6 (the RF gain target code); "reserved" = not a valid code
  if_band_max_mhz                    the chip's maximum IF bandwidth
  if_band_frac_complex1x | _complex2x | _real
                                     usable IF bandwidth as a fraction of the ADC sample rate fs, per adcCfg output format
  complex1x_upper_half_is_positive_if  bool (informational): complex-1x FFT bins above fs/2 are real positive IF

The rxGain word is `bits 5:0 = gain dB (even)`, `bits 7:6 = RF gain target code`, bits 15:8 reserved. A range check looks at
`word & 0x3F` only and the full word is preserved on write-back (shipped IWR6843 cfgs use 158 = 0x9E).
Entries whose confidence is "unverified"/"low" are never used to draw or enforce anything beyond a warning (`trusted`).
"""
from __future__ import annotations

C_MS = 299_792_458.0
TRUSTED = ("repo", "high", "medium")
GAIN_MASK = 0x3F
HPF_KEYS = ("hpf1_corner_khz", "hpf2_corner_khz")
GAIN_KEYS = ("rx_gain_min_db", "rx_gain_max_db", "rx_gain_step_db")
IF_FRAC_KEYS = {0: "if_band_frac_real", 1: "if_band_frac_complex1x", 2: "if_band_frac_complex2x"}   # adcCfg adcOutputFmt
ANALOG_KEYS = (*HPF_KEYS, *GAIN_KEYS, "rx_gain_rf_target_db", "if_band_max_mhz", *IF_FRAC_KEYS.values(),
                "complex1x_upper_half_is_positive_if")
ADC_MODE_NAMES = {0: "real", 1: "complex 1x", 2: "complex 2x"}


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def check_entries(entries: dict) -> list[str]:
    """Shape problems of the analog front-end keys in one board's raw limits dict ([] = fine; other keys are not looked at)."""
    bad: list[str] = []
    for k in HPF_KEYS:
        if k in entries:
            v = entries[k]["value"]
            if not (isinstance(v, list) and v and all(_num(x) and x > 0 for x in v) and v == sorted(v)):
                bad.append(f"{k}: must be an ascending non-empty list of kHz values")
    for k in GAIN_KEYS:
        if k in entries and not (_num(entries[k]["value"]) and entries[k]["value"] > 0):
            bad.append(f"{k}: must be a positive number")
    if all(k in entries for k in GAIN_KEYS[:2]) and entries["rx_gain_min_db"]["value"] > entries["rx_gain_max_db"]["value"]:
        bad.append("rx_gain_min_db > rx_gain_max_db")
    if "rx_gain_rf_target_db" in entries:
        v = entries["rx_gain_rf_target_db"]["value"]
        if not (isinstance(v, list) and len(v) == 4 and all(x == "reserved" or (_num(x) and x > 0) for x in v)):
            bad.append('rx_gain_rf_target_db: must be 4 entries (indexed by rxGain bits 7:6), each dB or "reserved"')
    if "if_band_max_mhz" in entries and not (_num(entries["if_band_max_mhz"]["value"]) and entries["if_band_max_mhz"]["value"] > 0):
        bad.append("if_band_max_mhz: must be a positive number")
    for k in IF_FRAC_KEYS.values():
        if k in entries and not (_num(entries[k]["value"]) and 0 < entries[k]["value"] <= 1):
            bad.append(f"{k}: must be a fraction of fs in (0, 1]")
    return bad


def trusted(lim: dict, key: str) -> bool:
    """True when `lim` (name -> Limit) has `key` with a confidence the GUI may draw/enforce on."""
    e = lim.get(key) if lim else None
    return e is not None and e.confidence in TRUSTED


def split_gain_word(word: int) -> tuple[int, int, int]:
    """rxGain word -> (gain dB = bits 5:0, RF gain target code = bits 7:6, reserved bits 15:8)."""
    w = int(word)
    return w & GAIN_MASK, (w >> 6) & 0x3, w >> 8


def gain_range(lim: dict) -> dict | None:
    """{min, max, step, confidence, level, source} of the RX gain (dB) or None when the board has no (complete) entry."""
    if not lim or not all(k in lim for k in GAIN_KEYS):
        return None
    lo, hi, st = (lim[k] for k in GAIN_KEYS)
    return {"min": lo.value, "max": hi.value, "step": st.value, "confidence": lo.confidence, "level": lo.level, "source": lo.source}


def gain_issues(word: int, lim: dict) -> list[tuple[str, str, str]]:
    """[(code, message, limit key)] for one profileCfg rxGain word: range/step of bits 5:0 and a reserved RF target code.
    Only bits 5:0 are range-checked; the RF target bits are looked up in the table, never rejected by magnitude."""
    out: list[tuple[str, str, str]] = []
    g, rf, _ = split_gain_word(word)
    r = gain_range(lim)
    if r:
        if not r["min"] <= g <= r["max"]:
            out.append(("rx_gain", f"rxGain {int(word)}: gain bits 5:0 = {g} dB, outside the valid {r['min']:g}-{r['max']:g} dB", "rx_gain_min_db"))
        elif (g - r["min"]) % r["step"]:
            out.append(("rx_gain", f"rxGain {int(word)}: gain bits 5:0 = {g} dB is not on the {r['step']:g} dB step (even values only)", "rx_gain_step_db"))
    t = lim.get("rx_gain_rf_target_db") if lim else None
    if t is not None and t.confidence in TRUSTED and t.value[rf] == "reserved":
        out.append(("rx_gain_target", f"rxGain {int(word)}: RF gain target code {rf} (bits 7:6) is reserved on this chip", "rx_gain_rf_target_db"))
    return out


def hpf_issue(code: int, which: int, lim: dict) -> tuple[str, str, str] | None:
    key = HPF_KEYS[which - 1]
    e = lim.get(key) if lim else None
    if e is None or 0 <= int(code) < len(e.value):
        return None
    return ("hpf_code", f"HPF{which} code {int(code)} is not in this chip's table (0-{len(e.value) - 1})", key)


def hpf_khz(lim: dict, which: int, code: int) -> float | None:
    """Corner (kHz) of HPF`which` (1|2) code `code`, only from a trusted table; else None."""
    key = HPF_KEYS[which - 1]
    if not trusted(lim, key):
        return None
    t = lim[key].value
    return float(t[int(code)]) if 0 <= int(code) < len(t) else None


def corner_range_m(khz: float, slope_mhz_us: float) -> float:
    """R = f_c * c / (2 * slope): the range whose beat frequency is the corner."""
    return khz * 1e3 * C_MS / (2 * slope_mhz_us * 1e12)


def if_band_hz(lim: dict, adc_fmt: int, fs_hz: float) -> float | None:
    """Usable IF bandwidth (Hz) = min(chip max IF, frac(adc mode) * fs); None when the data is missing or not trusted."""
    kf = IF_FRAC_KEYS.get(int(adc_fmt))
    if not kf or not trusted(lim, kf) or not trusted(lim, "if_band_max_mhz"):
        return None
    return min(lim["if_band_max_mhz"].value * 1e6, lim[kf].value * fs_hz)


def band_edges(lim: dict | None, hpf1_code: int | None, adc_fmt: int, fs_ksps: float, slope_mhz_us: float) -> dict:
    """What the Raw ADC views shade, as plain JSON (frame header `bands`): `hpf_m` (range below which = below the HPF1 corner)
    and `if_m` (range beyond which = outside the IF band), each None when unknown/unverified (then nothing is shaded), plus the
    inputs and the limits' provenance so the label can say where the edge comes from."""
    lim = lim or {}
    out: dict = {"adc_mode": ADC_MODE_NAMES.get(int(adc_fmt), str(adc_fmt)), "fs_ksps": fs_ksps, "slope_mhz_us": slope_mhz_us,
                 "hpf_khz": None, "hpf_m": None, "if_mhz": None, "if_m": None, "hpf_source": None, "if_source": None}
    if slope_mhz_us <= 0 or fs_ksps <= 0:
        return out
    k = hpf_khz(lim, 1, hpf1_code) if hpf1_code is not None else None
    if k is not None:
        out.update(hpf_khz=k, hpf_m=corner_range_m(k, slope_mhz_us), hpf_source=lim["hpf1_corner_khz"].source)
    f = if_band_hz(lim, adc_fmt, fs_ksps * 1e3)
    if f is not None:
        out.update(if_mhz=f / 1e6, if_m=f * C_MS / (2 * slope_mhz_us * 1e12), if_source=lim[IF_FRAC_KEYS[int(adc_fmt)]].source)
    return out
