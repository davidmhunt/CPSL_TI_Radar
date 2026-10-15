"""radar-40 Step 3: the Configs tab is declared, wired and has the markup its script looks up (static, no browser)."""
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "radar_gui" / "web"
HTML = (WEB / "index.html").read_text()
JS = (WEB / "js" / "configs.js").read_text()
MAIN = (WEB / "js" / "main.js").read_text()


def test_tab_button_panel_and_main_wiring():
    assert 'data-tab="configs"' in HTML and 'id="configsMain"' in HTML and 'aria-controls="configsMain"' in HTML
    assert "import { showConfigs } from './configs.js'" in MAIN
    assert re.search(r"PANEL = \{[^}]*configs: 'configsMain'", MAIN) and "configs: '#configs'" in MAIN
    assert "name === 'configs') showConfigs()" in MAIN


def test_every_dollar_lookup_is_in_index_html():
    ids = set(re.findall(r"\$\('([A-Za-z0-9_]+)'\)", JS))
    assert ids and all(f'id="{i}"' in HTML for i in ids), sorted(i for i in ids if f'id="{i}"' not in HTML)


def test_no_innerhtml_and_no_native_confirm_of_server_text():
    assert "innerHTML" not in JS and "outerHTML" not in JS and "insertAdjacentHTML" not in JS
    assert "confirm(" not in re.sub(r"confirm_overwrite|confirm_shipped|confirm: true|confirmText|onConfirm", "", JS)


def test_requests_use_the_dry_run_before_the_confirm_and_the_two_confirm_fields():
    assert "/api/configs/promote?dry=1" in JS and "/api/configs/delete?dry=1" in JS
    assert "confirm_shipped: shipped.length > 0" in JS and "confirm: true" in JS and "confirm_overwrite" in JS
    assert "commit and push" in JS and "referenced by" in JS
