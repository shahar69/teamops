from __future__ import annotations

from typing import Any, Dict

from . import PublisherConfigError, PublisherError, get_env

SLUG = "tiktok"
DISPLAY_NAME = "TikTok (Upload)"
DESCRIPTION = "Publishes short-form videos / captions to TikTok (dry-run placeholder)."
REQUIRED_ENV = [
    "PUBLISHER_TIKTOK_CLIENT_ID",
    "PUBLISHER_TIKTOK_CLIENT_SECRET",
    "PUBLISHER_TIKTOK_ACCESS_TOKEN",
]


def metadata() -> Dict[str, Any]:
    return {
        "slug": SLUG,
        "display_name": DISPLAY_NAME,
        "description": DESCRIPTION,
        "required_env": REQUIRED_ENV,
        "notes": "Provide `handle` or `channel_id` in schedule metadata for targeting.",
    }


def _load_credentials() -> Dict[str, str]:
    creds: Dict[str, str] = {}
    missing = []
    env = get_env()
    for key in REQUIRED_ENV:
        value = env.get(key)
        if value:
            creds[key] = value
        else:
            missing.append(key)
    if missing:
        raise PublisherConfigError("Missing TikTok credentials: " + ", ".join(missing))
    return creds


def health_check() -> Dict[str, Any]:
    _load_credentials()
    return {"success": True, "message": "TikTok credentials loaded"}


def publish(job: Dict[str, Any], schedule: Dict[str, Any]) -> Dict[str, Any]:
    _load_credentials()
    metadata = schedule.get("metadata") or {}
    handle = metadata.get("handle") or metadata.get("channel_id")
    title = metadata.get("title") or job.get("title") or "Untitled"
    description = (job.get("generated_content") or "").strip()
    if not description:
        raise PublisherError("Job has no generated content for TikTok upload.")
    return {
        "success": True,
        "platform": SLUG,
        "message": "Simulated TikTok publish (dry run)",
        "payload": {
            "target": handle,
            "title": title,
            "description_preview": description[:200],
        },
    }


class TiktokPublisher:
    REQUIRED_ENV = REQUIRED_ENV

    def __init__(self, env: Dict[str, str]):
        self.env = env

    def health_check(self) -> Dict[str, Any]:
        missing = [k for k in REQUIRED_ENV if not self.env.get(k)]
        return {"success": not missing, "message": ("Missing: " + ", ".join(missing)) if missing else "ok"}

    def prepare_payload(self, job: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "title": job.get("title", "Untitled"),
            "description": (job.get("generated_content") or job.get("description") or "").strip(),
        }

    def publish(self, job: Dict[str, Any], schedule: Dict[str, Any] = None) -> Dict[str, Any]:
        return {"status": "dry_run", "payload": self.prepare_payload(job)}
