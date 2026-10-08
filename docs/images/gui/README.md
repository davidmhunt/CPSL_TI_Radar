# GUI screenshots

One PNG per GUI tab (1400x900): `configure`, `radar`, `point_cloud`, `raw_adc`, `devices`, `logs`.
The PNGs are tracked with git LFS (`.gitattributes`): a clone needs `git lfs install` (then `git lfs pull`), or the shots show as pointer files.
They were shot with no hardware: the fake driver (`tests/fakes/fake_driver.py`), the replay
`tests/fixtures/replay/iwr1843_sdk3_20frames.bin` and a fake serial server. Host-specific text (serial number, NIC, LAN address, temp paths) is masked by the `mask` js action in the spec.

Re-shoot (one command, free port chosen automatically; check `console_errors.txt` in `--out` is `(none)`):

    uv run python tools/gui_shots.py --scenarios tools/gui_shots_specs/docs_tabs.json --out /tmp/shots
    for t in configure point_cloud radar raw_adc devices logs; do cp /tmp/shots/$t/$t.png docs/images/gui/; done

Swap in real-board shots: keep the same filenames. Either run the same command against your live GUI
(`--url http://127.0.0.1:<port>`; the spec's actions still drive the tabs), or use a browser at 1400x900
and save each tab under its name. Keep each PNG under 400 KB and all together under 3 MB (`du -ch *.png`).
