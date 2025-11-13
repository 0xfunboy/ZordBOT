"""Config loader with optional overrides for secrets/local settings."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


def _read_yaml(path: Path) -> Dict[str, Any]:
    with path.open() as handle:
        return yaml.safe_load(handle) or {}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(base_path: str = "config.yaml", local_path: Optional[str] = None) -> Dict[str, Any]:
    base_file = Path(base_path)
    if not base_file.exists():
        raise FileNotFoundError(f"Config file not found: {base_file}")
    config = _read_yaml(base_file)

    if local_path:
        local_file = Path(local_path)
        if local_file.exists():
            local_cfg = _read_yaml(local_file)
            config = _deep_merge(config, local_cfg)
    return config


__all__ = ["load_config"]
