from __future__ import annotations

from typing import Any, Dict

from . import PublisherConfigError, PublisherError, get_env

SLUG = "reddit"
DISPLAY_NAME = "Reddit (OAuth script app)"
DESCRIPTION = "Publishes text posts using a personal script-type OAuth application."
REQUIRED_ENV = [
    "PUBLISHER_REDDIT_CLIENT_ID",
    "PUBLISHER_REDDIT_CLIENT_SECRET",
    "PUBLISHER_REDDIT_USERNAME",
    "PUBLISHER_REDDIT_PASSWORD",
    "PUBLISHER_REDDIT_USER_AGENT",
]


def metadata() -> Dict[str, Any]:
    return {
        "slug": SLUG,
        "display_name": DISPLAY_NAME,
        "description": DESCRIPTION,
        "required_env": REQUIRED_ENV,
        "notes": "Set target subreddit via schedule metadata `subreddit`.",
    }


def _load_credentials() -> Dict[str, str]:
    creds: Dict[str, str] = {}
    missing = []
    for key in REQUIRED_ENV:
        value = get_env(key)
        if value:
            creds[key] = value
        else:
            missing.append(key)
    if missing:
        raise PublisherConfigError(
            "Missing Reddit credentials: " + ", ".join(missing)
        )
    return creds


def health_check() -> Dict[str, Any]:
    creds = _load_credentials()
    return {
        "success": True,
        "message": "Reddit credentials loaded",
        "identity": creds.get("PUBLISHER_REDDIT_USERNAME", ""),
    }


def publish(job: Dict[str, Any], schedule: Dict[str, Any]) -> Dict[str, Any]:
    creds = _load_credentials()
    metadata = schedule.get("metadata") or {}
    subreddit = metadata.get("subreddit") or metadata.get("target")
    if not subreddit:
        raise PublisherError("Schedule metadata is missing `subreddit` for Reddit publish.")
    title = metadata.get("title") or job.get("title") or "Untitled"
    body = (job.get("generated_content") or "").strip()
    if not body:
        raise PublisherError("Job has no generated content to post to Reddit.")
    preview = " ".join(body.split())[:180]
    return {
        "success": True,
        "platform": SLUG,
        "message": "Simulated Reddit publish (dry run)",
        "payload": {
            "subreddit": subreddit,
            "title": title,
            "preview": preview,
            "username": creds.get("PUBLISHER_REDDIT_USERNAME", ""),
        },
    }
