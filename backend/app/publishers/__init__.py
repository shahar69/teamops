"""Publisher connectors for automated Money Bots distribution."""
import os
from pathlib import Path
from typing import Any, Dict, List


class PublisherError(Exception):
    """Generic publisher error."""


class PublisherConfigError(PublisherError):
    """Raised when required configuration is missing."""


_ENV_CACHE: Dict[str, str] | None = None
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env.production"


def _load_env_file() -> Dict[str, str]:
    global _ENV_CACHE
    if _ENV_CACHE is not None:
        return _ENV_CACHE
    data: Dict[str, str] = {}
    if _ENV_PATH.exists():
        for raw_line in _ENV_PATH.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            data[key.strip()] = value.strip()
    _ENV_CACHE = data
    return data


def get_env(name: str) -> str | None:
    """Return publisher credential, checking environment variables first."""
    value = os.environ.get(name)
    if value:
        return value
    return _load_env_file().get(name)


from . import reddit, twitter, youtube  # noqa: E402


_PUBLISHERS = {
    reddit.SLUG: reddit,
    twitter.SLUG: twitter,
    youtube.SLUG: youtube,
}

_ALIASES = {
    reddit.SLUG: reddit.SLUG,
    "reddit": reddit.SLUG,
    "reddit_script": reddit.SLUG,
    twitter.SLUG: twitter.SLUG,
    "twitter": twitter.SLUG,
    "x": twitter.SLUG,
    "twitter_x": twitter.SLUG,
    youtube.SLUG: youtube.SLUG,
    "youtube": youtube.SLUG,
    "youtube_shorts": youtube.SLUG,
}


def normalize_platform(platform: str) -> str:
    key = (platform or "").strip().lower().replace("-", "_")
    if key not in _ALIASES:
        raise PublisherError(f"Unsupported publishing platform: {platform}")
    slug = _ALIASES[key]
    if slug not in _PUBLISHERS:
        raise PublisherError(f"Publisher not implemented for: {platform}")
    return slug


def get_publisher(platform: str):
    slug = normalize_platform(platform)
    return _PUBLISHERS[slug]


def list_publishers() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for slug, module in _PUBLISHERS.items():
        meta: Dict[str, Any] = {
            "slug": slug,
            "display_name": getattr(module, "DISPLAY_NAME", slug.replace("_", " ").title()),
            "description": getattr(module, "DESCRIPTION", ""),
            "required_env": getattr(module, "REQUIRED_ENV", []),
        }
        if hasattr(module, "metadata") and callable(module.metadata):
            meta.update(module.metadata())
        items.append(meta)
    return items


__all__ = [
    "PublisherError",
    "PublisherConfigError",
    "get_env",
    "get_publisher",
    "list_publishers",
    "normalize_platform",
]
