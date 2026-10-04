"""Pure utility helpers."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urlparse

from .constants import MANAGED_MARKER, MANAGED_PREFIX


def short_hash(value: str, length: int = 12) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def normalize_harbor_api_url(url: str) -> str:
    normalized = url.rstrip("/")
    return normalized if "/api/v2.0" in normalized else f"{normalized}/api/v2.0"


def normalize_registry_url(url: str) -> str:
    normalized = url.strip().rstrip("/")
    if not re.match(r"^https?://", normalized, flags=re.IGNORECASE):
        normalized = f"https://{normalized}"
    return normalized


def split_registry_prefix(prefix: str) -> tuple[str, str]:
    """Return ``(https registry URL, repository path)`` from a GitLab prefix."""
    if not prefix:
        raise ValueError("GitLab project has no container_registry_image_prefix")

    candidate = prefix if "://" in prefix else f"//{prefix}"
    parsed = urlparse(candidate)
    host = parsed.netloc
    repository = parsed.path.lstrip("/")
    if not host or not repository:
        raise ValueError(f"Invalid container_registry_image_prefix: {prefix!r}")
    return f"https://{host}", repository


def marker_description(**fields: object) -> str:
    suffix = "; ".join(f"{key}={value}" for key, value in fields.items())
    return f"{MANAGED_MARKER}; {suffix}" if suffix else MANAGED_MARKER


def is_managed(name: str | None, description: str | None) -> bool:
    return bool(
        name
        and name.startswith(MANAGED_PREFIX)
        and description
        and description.startswith(MANAGED_MARKER)
    )


def id_from_location(location: str) -> int | None:
    match = re.search(r"/(\d+)/?$", location or "")
    return int(match.group(1)) if match else None
