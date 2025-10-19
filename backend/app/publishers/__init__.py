"""Publisher connectors for automated Money Bots distribution."""
import os
from typing import Optional, Dict, Any, List
from pathlib import Path
from importlib import import_module


class PublisherError(Exception):
    """Generic publisher error."""


class PublisherConfigError(PublisherError):
    """Raised when required configuration is missing."""


def _load_env_file(path: str) -> Dict[str, str]:
    res = {}
    p = Path(path)
    if not p.exists():
        return res
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            res[k.strip()] = v.strip().strip('"').strip("'")
    return res


# Merge environment with fallback to .env.production at repo root
_env_cache: Optional[Dict[str, str]] = None


def get_env() -> Dict[str, str]:
    global _env_cache
    if _env_cache is not None:
        return _env_cache
    env = dict(os.environ)
    env_file = Path("/root/teamops-1/.env.production")
    if env_file.exists():
        file_env = _load_env_file(str(env_file))
        for k, v in file_env.items():
            env.setdefault(k, v)
    _env_cache = env
    return env

# Dynamically discover publisher adapter modules if present.
_candidate_names = ["reddit", "twitter", "youtube", "tiktok"]
_PUBLISHERS: Dict[str, Any] = {}
for name in _candidate_names:
    try:
        mod = import_module(f"backend.app.publishers.{name}")
        slug = getattr(mod, "SLUG", name)
        _PUBLISHERS[slug] = mod
    except Exception:
        # skip modules that fail to import to avoid import-time crashes
        continue

# Build alias map for common names -> canonical slug (only for discovered publishers)
_aliases_base = {
    "reddit": ["reddit", "reddit_script"],
    "twitter": ["twitter", "x", "twitter_x"],
    "youtube": ["youtube", "youtube_shorts"],
    "tiktok": ["tiktok"],
}
_ALIASES: Dict[str, str] = {}
for slug, module in _PUBLISHERS.items():
    # primary mapping
    _ALIASES[slug] = slug
    # add known aliases if module exists
    for key, aliases in _aliases_base.items():
        if key == slug:
            for a in aliases:
                _ALIASES[a] = slug
# Ensure lowercased keys
_ALIASES = {k.lower(): v for k, v in _ALIASES.items()}


def normalize_platform(platform: str) -> str:
    key = (platform or "").strip().lower().replace("-", "_")
    if key not in _ALIASES:
        raise PublisherError(f"Unsupported publishing platform: {platform}")
    slug = _ALIASES[key]
    if slug not in _PUBLISHERS:
        raise PublisherError(f"Publisher not implemented for: {platform}")
    return slug


def _find_publisher_class(module, slug: str):
    """Heuristic to find the Publisher class in a module."""
    # 1) try explicit name e.g. RedditPublisher
    candidate = "".join(part.title() for part in slug.split("_")) + "Publisher"
    cls = getattr(module, candidate, None)
    if isinstance(cls, type):
        return cls
    # 2) fallback: find first class ending with 'Publisher'
    for attr in dir(module):
        if attr.endswith("Publisher"):
            obj = getattr(module, attr)
            if isinstance(obj, type):
                return obj
    raise PublisherConfigError(f"No Publisher class found in module for slug '{slug}'.")


def get_publisher(name: str):
    try:
        slug = normalize_platform(name)
    except PublisherError:
        # allow direct name synonyms to try as slug
        slug = (name or "").strip().lower()
    module = _PUBLISHERS.get(slug)
    if not module:
        # last resort: attempt dynamic import by name
        try:
            module = import_module(f"backend.app.publishers.{slug}")
            _PUBLISHERS[slug] = module
        except Exception:
            return None
    try:
        publisher_class = _find_publisher_class(module, slug)
        return publisher_class(get_env())
    except PublisherConfigError:
        return None


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
            try:
                meta.update(module.metadata())
            except Exception:
                pass
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
