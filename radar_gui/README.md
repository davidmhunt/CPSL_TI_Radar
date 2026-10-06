# radar_gui

Single-process radar GUI prototype (gui-01): FastAPI + uvicorn backend, plain-JS ES-module frontend (no bundler,
no build step). The look, layout and point-cloud views are ported from `tools/radar_viewer/`, which is left
untouched as a reference; `tlv.py` loads its `parse_frame`.

    uv run python -m radar_gui --source mock              # http://127.0.0.1:8000/
    uv run python -m radar_gui --source replay --file tests/fixtures/sample_frames.bin
    # options: --rate HZ  --host H  --port P

## Layout

| Path | What |
|------|------|
| `__main__.py` | CLI, starts uvicorn |
| `app.py` | `create_app(source)`: `/api/health`, `/api/state`, WebSocket `/stream`, serves `web/`; `Hub` fans frames to clients |
| `sources.py` | `Source` interface, `MockSource` (moving synthetic targets), `ReplaySource` (TLV byte dump, looped) |
| `tlv.py` | frame parsing (reuses the viewer's `parse_frame`), `split_packets`, `build_packet` (fixtures) |
| `web/index.html`, `web/style.css` | page and styles |
| `web/js/` | `main.js` (stream, controls), `state.js`, `colors.js`, `views.js` (top/3D/front/sparkline canvases) |

Wire format on `/stream` (JSON text messages): `status`, `cfg` (page hints: `max_range_m`, `fov`) and
`frame` (`frame`, `n`, `pts` = `[x, y, z, v, snr, noise]`, `rate`, `gaps`, `errors`).
New sources subclass `Source` and yield frame dicts from `async frames()`.

Tests: `uv run pytest tests/test_radar_gui_skeleton.py`.
