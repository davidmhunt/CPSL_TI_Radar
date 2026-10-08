# Archive

Legacy radar cfgs kept for the record. Nothing in the live tree references them: no system JSON or firmware
template points here (`tests/test_config_tree.py` checks that), and the GUI lists only `radar/`.

| File | Was at (under `config/`) | Notes |
|---|---|---|
| `radar/IWR1443/dca1000_raw/standard.cfg` | `radar/DCA1000/custom_configs/archived_configs/standard.cfg` | already archived in v1 |
| `radar/IWR1443/dca1000_raw/vel_detection.cfg` | `radar/DCA1000/custom_configs/archived_configs/vel_detection.cfg` | already archived in v1 |

The layout mirrors `radar/<BOARD>/<firmware>/`. To bring a file back, `git mv` it into `radar/` and point a system JSON at it.
