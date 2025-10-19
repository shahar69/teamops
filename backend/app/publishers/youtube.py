from __future__ import annotations

from typing import Any, Dict

from . import PublisherConfigError, PublisherError, get_env

SLUG = "youtube_shorts"
DISPLAY_NAME = "YouTube Shorts"
DESCRIPTION = "Uploads scripted Shorts via the YouTube Data API."
REQUIRED_ENV = [
    "PUBLISHER_YOUTUBE_CLIENT_ID",
    "PUBLISHER_YOUTUBE_CLIENT_SECRET",
    "PUBLISHER_YOUTUBE_REFRESH_TOKEN",
    "PUBLISHER_YOUTUBE_CHANNEL_ID",
]


def metadata() -> Dict[str, Any]:
    return {
        "slug": SLUG,
        "display_name": DISPLAY_NAME,
        "description": DESCRIPTION,
        "required_env": REQUIRED_ENV,
        "notes": "Schedule metadata may include `privacy_status` and `tags` for Shorts uploads.",
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
        raise PublisherConfigError(
            "Missing YouTube credentials: " + ", ".join(missing)
        )
    return creds


def health_check() -> Dict[str, Any]:
    creds = _load_credentials()
    return {
        "success": True,
        "message": "YouTube Shorts credentials loaded",
        "channel": creds.get("PUBLISHER_YOUTUBE_CHANNEL_ID", ""),
    }


def publish(job: Dict[str, Any], schedule: Dict[str, Any]) -> Dict[str, Any]:
    creds = _load_credentials()
    metadata = schedule.get("metadata") or {}
    title = metadata.get("title") or job.get("title") or "Untitled Short"
    description = (job.get("generated_content") or "").strip()
    if not description:
        raise PublisherError("Job has no generated script to upload to YouTube Shorts.")
    privacy = metadata.get("privacy_status", "unlisted")
    tags = metadata.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    return {
        "success": True,
        "platform": SLUG,
        "message": "Simulated YouTube Shorts publish (dry run)",
        "payload": {
            "channel": creds.get("PUBLISHER_YOUTUBE_CHANNEL_ID", ""),
            "title": title,
            "privacy_status": privacy,
            "tags": tags,
            "description_preview": description[:200],
        },
    }


class YouTubePublisher:
    REQUIRED_ENV = ["YOUTUBE_API_KEY"]

    def __init__(self, env: Dict[str, str]):
        self.env = env

    def health_check(self) -> Dict[str, Any]:
        missing = [k for k in self.REQUIRED_ENV if not self.env.get(k)]
        ok = not missing
        return {"ok": ok, "success": ok, "message": ("Missing: " + ", ".join(missing)) if missing else "ok"}

    def prepare_payload(self, job: Dict[str, Any]) -> Dict[str, Any]:
        return {"title": job.get("title", ""), "description": job.get("description", ""), "privacyStatus": job.get("privacy", "unlisted")}

    def publish(self, job: Dict[str, Any], schedule: Dict[str, Any] = None) -> Dict[str, Any]:
        payload = self.prepare_payload(job)
        return {"status": "dry_run", "payload": payload}
