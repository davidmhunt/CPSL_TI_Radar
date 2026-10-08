# GUI screenshots

One PNG per GUI tab (1400x900): `configure`, `radar`, `point_cloud`, `raw_adc`, `devices`, `logs`.
They were shot with no hardware: the fake driver (`tests/fakes/fake_driver.py`), the replay
`tests/fixtures/replay/iwr1843_sdk3_20frames.bin` and a fake serial server. The Devices serial number is masked.

Re-shoot (one command, free port chosen automatically; check `console_errors.txt` in `--out` is `(none)`):

    uv run python tools/gui_shots.py --scenarios tools/gui_shots_specs/docs_tabs.json --out /tmp/shots
    for t in configure point_cloud radar raw_adc devices logs; do cp /tmp/shots/$t/$t.png docs/images/gui/; done

Swap in real-board shots: keep the same filenames. Either run the same command against your live GUI
(`--url http://127.0.0.1:<port>`; the spec's actions still drive the tabs), or use a browser at 1400x900
and save each tab under its name. Keep each PNG under 400 KB and all together under 3 MB (`du -ch *.png`).
