from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

from .utils import atomic_write_json

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "challenge_config.json"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    path = Path(path)
    with path.open("r", encoding="utf-8") as fh:
        config = json.load(fh)
    config.setdefault("overlay", {})
    config["overlay"].setdefault("emote_size_px", 58)
    config["overlay"].setdefault("emote_speed_percent", 100)
    validate_config(config)
    return config


def save_config(config: dict[str, Any], path: str | Path = DEFAULT_CONFIG_PATH) -> None:
    validate_config(config)
    atomic_write_json(path, config)


def validate_config(config: dict[str, Any]) -> None:
    c = config.get("challenge", {})
    if float(c.get("target_km", 0)) <= 0:
        raise ValueError("challenge.target_km must be > 0")
    if int(c.get("milestone_interval_km", 0)) <= 0:
        raise ValueError("challenge.milestone_interval_km must be > 0")
    if int(c.get("major_milestone_interval_km", 0)) <= 0:
        raise ValueError("challenge.major_milestone_interval_km must be > 0")
    b = config.get("boss", {})
    interval = int(b.get("interval_km", 20))
    major = int(b.get("major_interval_km", 100))
    if interval <= 0 or major <= 0 or major % interval != 0:
        raise ValueError("boss.major_interval_km must be a positive multiple of boss.interval_km")
    overlay = config.get("overlay", {})
    for name, default, low, high in [("emote_size_px", 58, 24, 160), ("emote_speed_percent", 100, 50, 200)]:
        value = float(overlay.get(name, default))
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"overlay.{name} muss zwischen {low} und {high} liegen")
    for key in ("small_duration_seconds", "major_duration_seconds"):
        value = float(b.get(key, 0))
        if not math.isfinite(value) or not 1 <= value <= 3600:
            raise ValueError(f"boss.{key} muss zwischen 1 und 3600 Sekunden liegen")
    h = config.get("heat", {})
    levels = [float(h.get("level1_kmh", 30)), float(h.get("level2_kmh", 35)), float(h.get("level3_kmh", 40))]
    if not (levels[0] < levels[1] < levels[2]):
        raise ValueError("heat thresholds must be strictly increasing")
    twitch = config.get("twitch", {})
    reward_title = str(twitch.get("medipack_reward_title", "Medipak"))
    reward_prompt = str(twitch.get("medipack_reward_prompt", ""))
    if not reward_title.strip() or len(reward_title) > 45:
        raise ValueError("twitch.medipack_reward_title must contain 1-45 characters")
    if int(twitch.get("medipack_reward_cost", 500)) < 1:
        raise ValueError("twitch.medipack_reward_cost must be >= 1")
    if len(reward_prompt) > 200:
        raise ValueError("twitch.medipack_reward_prompt must contain at most 200 characters")
    features = config.get("features", {})
    if features.get("betting") or features.get("milestone_dedications"):
        raise ValueError("future feature flags betting/milestone_dedications must stay disabled")


def update_config(config: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    candidate = _deep_merge(config, patch)
    validate_config(candidate)
    return candidate
