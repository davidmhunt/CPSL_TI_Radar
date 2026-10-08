"""Pure-Python TI mmWave cfg tools: parse, metrics, per-board validation, generation (gui-02)."""
from . import detection, firmware
from .generate import GenResult, generate
from .limits import BOARD_LIMITS, limits_dict
from .metrics import BOARDS, Metrics, metrics
from .params import ParamsError, apply_params, params_from_cfg
from .parse import Cfg, CfgError, Command, parse_cfg, parse_cfg_file
from .validate import Issue, Report, validate

__all__ = ["BOARD_LIMITS", "BOARDS", "Cfg", "CfgError", "Command", "GenResult", "Issue", "Metrics", "Report", "ParamsError", "apply_params", "params_from_cfg",
           "detection", "firmware", "generate", "limits_dict", "metrics", "parse_cfg", "parse_cfg_file", "validate"]
