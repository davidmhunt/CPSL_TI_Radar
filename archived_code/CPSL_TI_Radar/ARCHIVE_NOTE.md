# Archived: Python DCA1000 Streaming Implementation

This directory contains the legacy Python radar streaming package. It has been superseded by `CPSL_TI_Radar_cpp/` (the C++ implementation), which provides more reliable high-rate DCA1000 streaming.

## What's here

- `CPSL_TI_Radar_py/` — the Python package source (renamed from `CPSL_TI_Radar/` for clarity; note: imports inside this package still reference the old name and will be broken)
- `pyproject.toml` / `poetry.lock` — Poetry project metadata and locked dependencies
- `README.md` — original hardware setup and installation instructions (still valid reference; image paths updated to point to `../../readme_images/`)
- `json_radar_settings/` — JSON config profiles for different board setups
- `tests/` — pytest suite for serial/ethernet connectivity (requires `CPSL_TI_Radar_py` to be importable)
- `utilities_and_notebooks/` — original Python notebooks (`bartlet.ipynb` and `test_ethernet_traffic.ipynb` promoted to top-level `utilities/`; `print_config.ipynb` duplicate left here)
- `run_radar.py` — original entry point

## Why archived

The C++ implementation (`CPSL_TI_Radar_cpp/`) replaces the DCA1000 streaming path with a dedicated RX thread, lock-free ring buffer, and tuned socket buffers that eliminate packet drops at high ADC rates. The Python package's TLV processing pipeline and hardware setup documentation remain as reference material.
