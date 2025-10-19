import os
import pytest
import httpx


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_ai_voices_endpoint(tmp_path):
    # Use a temporary SQLite DB for isolation
    db_file = tmp_path / "test_ai.sqlite3"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"

    from backend.app import main
    main.init_db()

    async with httpx.AsyncClient(app=main.app, base_url="http://test") as client:
        # First call should populate cache
        r = await client.get("/ai/voices")
        assert r.status_code == 200
        data = r.json()
        assert "voices" in data
        assert isinstance(data["voices"], list)

        # Bypass cache and ensure still OK
        r2 = await client.get("/ai/voices?refresh=true")
        assert r2.status_code == 200
        data2 = r2.json()
        assert "voices" in data2
        assert isinstance(data2["voices"], list)
