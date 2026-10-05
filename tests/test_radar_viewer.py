"""Smoke test: the cascade viewer imports and finds its default cfg templates."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools", "radar_viewer"))

import cfggen  # noqa: E402
import server  # noqa: E402


def test_default_cfg_templates_exist():
    assert os.path.isfile(cfggen.TEMPLATE), cfggen.TEMPLATE
    assert os.path.isfile(server.DEFAULT_CFG), server.DEFAULT_CFG
