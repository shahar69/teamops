from __future__ import annotations

from typing import Any, Dict

from . import PublisherConfigError, PublisherError, get_env

SLUG = "twitter_x"
DISPLAY_NAME = "Twitter / X (API v2)"
DESCRIPTION = "Publishes threads or tweets using the v2 API and OAuth 1.0a user context."
REQUIRED_ENV = [
    "PUBLISHER_TWITTER_API_KEY",
    "PUBLISHER_TWITTER_API_SECRET",
    "PUBLISHER_TWITTER_ACCESS_TOKEN",
    "PUBLISHER_TWITTER_ACCESS_SECRET",
    "PUBLISHER_TWITTER_BEARER_TOKEN",
]


def metadata() -> Dict[str, Any]:
    return {
        "slug": SLUG,
        "display_name": DISPLAY_NAME,
        "description": DESCRIPTION,
        "required_env": REQUIRED_ENV,
        "notes": "Provide `handle` in schedule metadata to target the posting account.",
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
            "Missing Twitter/X credentials: " + ", ".join(missing)
        )
    return creds


def health_check() -> Dict[str, Any]:
    _load_credentials()
    return {
        "success": True,
        "message": "Twitter/X credentials loaded",
    }


def publish(job: Dict[str, Any], schedule: Dict[str, Any]) -> Dict[str, Any]:
    _load_credentials()
    metadata = schedule.get("metadata") or {}
    handle = metadata.get("handle") or metadata.get("account")
    if not handle:
        raise PublisherError("Schedule metadata must include `handle` for Twitter/X publishing.")
    body = (job.get("generated_content") or "").strip()
    if not body:
        raise PublisherError("Job has no generated content for Twitter/X publishing.")
    preview = body.splitlines()[0][:240]
    return {
        "success": True,
        "platform": SLUG,
        "message": "Simulated Twitter/X publish (dry run)",
        "payload": {
            "handle": handle,
            "preview": preview,
        },
    }


class TwitterPublisher:
    REQUIRED_ENV = ["TWITTER_API_KEY", "TWITTER_API_SECRET", "TWITTER_ACCESS_TOKEN", "TWITTER_ACCESS_SECRET"]

    def __init__(self, env: Dict[str, str]):
        self.env = env

    def health_check(self) -> Dict[str, Any]:
        missing = [k for k in self.REQUIRED_ENV if not self.env.get(k)]
        ok = not missing
        return {"ok": ok, "success": ok, "message": ("Missing: " + ", ".join(missing)) if missing else "ok"}

    def prepare_payload(self, job: Dict[str, Any]) -> Dict[str, Any]:
        return {"status_text": job.get("text", ""), "media": job.get("media")}

    def publish(self, job: Dict[str, Any], schedule: Dict[str, Any] = None) -> Dict[str, Any]:
        payload = self.prepare_payload(job)
        return {"status": "dry_run", "payload": payload}
