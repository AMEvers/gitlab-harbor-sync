"""Configuration loading and environment helpers."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from .models import TargetConfig


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Required environment variable {name} is not set")
    return value


def load_targets(path: str) -> list[TargetConfig]:
    """Load and validate target mappings from YAML."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))

    # The primary format is a direct list. A {targets: [...]} wrapper is also
    # accepted for deployments that prefer a named top-level YAML key.
    if isinstance(raw, dict) and "targets" in raw:
        raw = raw["targets"]

    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raise ValueError("Config must be a YAML list or a mapping containing 'targets'")

    result: list[TargetConfig] = []
    seen: set[tuple[str, str]] = set()

    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"Config item {index} must be a mapping")

        topic = str(item.get("git-project-tag", "")).strip()
        target = str(item.get("harbor-target", "")).strip().strip("/")

        if not topic:
            raise ValueError(f"Config item {index} is missing 'git-project-tag'")
        if not target:
            raise ValueError(f"Config item {index} is missing 'harbor-target'")
        if "://" in target or any(part in {".", ".."} for part in target.split("/")):
            raise ValueError(f"Config item {index} has invalid harbor-target {target!r}")

        key = (topic, target)
        if key not in seen:
            result.append(TargetConfig(topic, target))
            seen.add(key)

    return result
