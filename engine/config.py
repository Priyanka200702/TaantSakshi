"""
engine/config.py
Loads config.yaml from the repo root and exposes get_config().
All engine code must call get_config() instead of hard-coding constants.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

# Repo root is two levels up from this file: engine/ -> repo root
_REPO_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _REPO_ROOT / "config.yaml"

_REQUIRED_TOP_KEYS = {
    "card", "rectify", "quality", "enhance", "fft",
    "defects", "grade", "fingerprint",
}

_cache: dict[str, Any] | None = None


def get_config() -> dict[str, Any]:
    """Return the full engine config dict (cached after first load)."""
    global _cache
    if _cache is None:
        _cache = _load()
    return _cache


def reload_config() -> dict[str, Any]:
    """Force a fresh load from disk (useful in tests)."""
    global _cache
    _cache = None
    return get_config()


def _load() -> dict[str, Any]:
    if not _CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Engine config not found at {_CONFIG_PATH}. "
            "Run from the repo root or set TANTSAAKSHI_CONFIG env var."
        )
    # Allow override via environment variable (handy in CI)
    env_path = os.environ.get("TANTSAAKSHI_CONFIG")
    path = Path(env_path) if env_path else _CONFIG_PATH

    with path.open("r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)

    if not isinstance(cfg, dict):
        raise ValueError(f"config.yaml must be a YAML mapping, got {type(cfg)}")

    missing = _REQUIRED_TOP_KEYS - cfg.keys()
    if missing:
        raise KeyError(f"config.yaml is missing required sections: {sorted(missing)}")

    return cfg

