"""
Configuration management: loads base_config.json and deep-merges strategy-specific diffs.
"""
import copy
import json
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).parent.parent
BASE_CONFIG_PATH = ROOT / "configs" / "base_config.json"
STRATEGY_CONFIGS_DIR = ROOT / "configs" / "strategies"


def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base. Override keys win."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(strategy_name: str) -> dict:
    """
    Load base config and merge with the strategy-specific diff (if any).
    Returns the fully merged config dict.
    """
    with open(BASE_CONFIG_PATH, encoding="utf-8") as f:
        base = json.load(f)

    diff_path = STRATEGY_CONFIGS_DIR / f"{strategy_name}.json"
    if diff_path.exists():
        with open(diff_path, encoding="utf-8") as f:
            diff = json.load(f)
        return deep_merge(base, diff)

    return base


def write_temp_config(config: dict) -> Path:
    """Write merged config to a temp file and return its path."""
    tmp_path = Path(tempfile.gettempdir()) / f"freqtrade_run_{uuid.uuid4().hex}.json"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    return tmp_path


def get_tp_config(config: dict) -> dict:
    """Extract tp_config with defaults."""
    defaults = {
        "enabled": False,
        "levels": [
            {"ratio": 0.33, "target": 0.01},
            {"ratio": 0.33, "target": 0.02},
            {"ratio": 0.34, "target": 0.03},
        ],
    }
    tp = config.get("tp_config", {})
    return deep_merge(defaults, tp)
