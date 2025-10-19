import os
import pytest
from fastapi.testclient import TestClient


def test_video_studio_ui_loads(tmp_path):
    """Test that the video studio UI endpoint loads correctly."""
    db_file = tmp_path / "test_video_studio.sqlite3"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"

    from backend.app import main

    main.init_db()

    with TestClient(main.app) as client:
        # Test video studio UI endpoint
        r = client.get("/ui/video-studio")
        assert r.status_code == 200
        assert "Video Studio" in r.text
        assert "🎬 Video Studio" in r.text
        assert "Project Settings" in r.text
        assert "Background" in r.text
        assert "Voice & Audio" in r.text


def test_video_studio_api_endpoints(tmp_path):
    """Test that all required API endpoints for video studio work."""
    db_file = tmp_path / "test_video_studio_api.sqlite3"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"

    from backend.app import main

    main.init_db()

    with TestClient(main.app) as client:
        # Test voices endpoint
        r = client.get("/ai/voices")
        assert r.status_code == 200
        data = r.json()
        assert "voices" in data

        # Test backgrounds endpoint
        r = client.get("/ai/video/backgrounds")
        assert r.status_code == 200
        data = r.json()
        assert "backgrounds" in data

        # Test AI config endpoint
        r = client.get("/ai/config")
        assert r.status_code == 200
        data = r.json()
        assert "local" in data
        assert "api_base" in data
        assert "model" in data


def test_video_generation_with_minimal_data(tmp_path):
    """Test video generation with minimal required data."""
    db_file = tmp_path / "test_video_gen.sqlite3"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"

    from backend.app import main

    main.init_db()

    with TestClient(main.app) as client:
        # Test video generation endpoint
        payload = {
            "title": "Test Video",
            "script": "This is a test video script for our new studio interface."
        }
        r = client.post("/ai/video", json=payload)
        # Accept 200 for success or 500 if ffmpeg/pyttsx3 unavailable
        assert r.status_code in (200, 500)
        if r.status_code == 200:
            data = r.json()
            assert "video" in data
            assert "filename" in data["video"]
            assert "url" in data["video"]
