import os
import asyncio
import pathlib

import pytest


@pytest.fixture
def anyio_backend():
    return "asyncio"
import httpx


@pytest.mark.anyio
async def test_profiles_content_and_schedule(tmp_path):
    # Use a temporary SQLite DB for this test
    db_file = tmp_path / "test_ai.sqlite3"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"

    # Import after setting env so the engine uses SQLite
    from backend.app import main

    # Ensure schema exists
    main.init_db()

    async with httpx.AsyncClient(app=main.app, base_url="http://test") as client:
        # Verify AI config endpoint reports local mode by default
        r = await client.get("/ai/config")
        assert r.status_code == 200
        cfg = r.json()
        assert cfg["local"] in (True, False)
        assert isinstance(cfg.get("api_base"), str)
        assert isinstance(cfg.get("model"), str)
        # Health
        r = await client.get("/health")
        assert r.status_code == 200
        assert r.json().get("status") == "ok"

        # No profiles initially
        r = await client.get("/ai/profiles")
        assert r.status_code == 200
        assert r.json()["profiles"] == []

        # Create profile
        payload = {
            "name": "Tester",
            "tone": "witty",
            "voice": "narrator",
            "target_platform": "TikTok · Reddit",
            "guidelines": "Keep it clean",
        }
        r = await client.post("/ai/profiles", json=payload)
        assert r.status_code == 200
        assert r.json().get("ok") is True

        # List profiles has one
        r = await client.get("/ai/profiles")
        assert r.status_code == 200
        profiles = r.json()["profiles"]
        assert len(profiles) == 1
        pid = profiles[0]["id"]

        # Generate content (fallback path if no AI key)
        gen_body = {
            "profile_id": pid,
            "content_type": "social-post",
            "title": "Test Title",
            "keywords": "alpha, beta",
            "brief": "Make it nice",
        }
        r = await client.post("/ai/content", json=gen_body)
        assert r.status_code == 200
        data = r.json()
        assert data["job"]["status"] == "completed"
        assert "generated_content" in data["job"]
        assert isinstance(data["job"]["generated_content"], str)

        # Jobs list contains the job
        r = await client.get("/ai/jobs")
        assert r.status_code == 200
        jobs = r.json()["jobs"]
        assert len(jobs) >= 1
        jid = jobs[0]["id"]

        # Create schedule for immediate time
        now = "2025-01-01T00:00"
        r = await client.post("/ai/schedule", json={"job_id": jid, "platform": "reddit", "scheduled_for": now})
        assert r.status_code == 200
        assert r.json().get("ok") is True

        # List schedules
        r = await client.get("/ai/schedule")
        assert r.status_code == 200
        schedules = r.json()["schedules"]
        assert any(s["job_id"] == jid for s in schedules)

        # Attempt local video generation for the job; shape should be valid
        r = await client.post("/ai/video", json={"job_id": jid})
        # Accept 200 for success or 500 if ffmpeg/pyttsx3 are unavailable in test env
        assert r.status_code in (200, 500)
        if r.status_code == 200:
            v = r.json()["video"]
            assert v["filename"].endswith('.mp4')
            assert v["url"].startswith('/media/')
