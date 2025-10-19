from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape, TemplateNotFound
from pathlib import Path
from sqlalchemy import create_engine, text
from datetime import datetime, timezone
import os
import hmac
import hashlib
import httpx
import asyncio
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
import json

# Minimal imports for scheduler and publishers
# (removed top-level AIScheduleDispatcher import to avoid import-time failures)
from backend.app.publishers import get_publisher
from backend.app import media as media_mod

# ---------- Config ----------
# Default to local SQLite for out-of-the-box local runs; override via DATABASE_URL if needed
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:////tmp/teamops_local.sqlite3")
BACKEND_SECRET = os.getenv("BACKEND_SECRET", "dev-secret")
AI_LOCAL = os.getenv("AI_LOCAL", "true").lower() in ("1", "true", "yes")
AI_API_KEY = os.getenv("AI_API_KEY")
_default_base = "http://127.0.0.1:11434/v1" if AI_LOCAL else "https://api.openai.com/v1"
AI_API_BASE = os.getenv("AI_API_BASE", _default_base)
_default_model = "llama3.1" if AI_LOCAL else "gpt-3.5-turbo"
AI_MODEL = os.getenv("AI_MODEL", _default_model)
AI_TIMEOUT = float(os.getenv("AI_TIMEOUT", "30"))

engine = create_engine(DATABASE_URL, future=True)

TEMPLATES_DIR = str((Path(__file__).resolve().parent / "templates").as_posix())
templates = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(["html", "xml"])
)

app = FastAPI()
_scheduler: Optional[Any] = None
_voices_cache_data: Optional[Dict[str, Any]] = None
_voices_cache_ts: float = 0.0

def init_db():
    """Create/upgrade minimal schema required by the UI for both SQLite and Postgres."""
    url = str(engine.url).lower()
    is_sqlite = url.startswith("sqlite")

    def _ensure_sqlite_columns(conn, table: str, add_sql: List[Tuple[str, str]]):
        cols = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()}
        for col_name, ddl in add_sql:
            if col_name not in cols:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))

    with engine.begin() as conn:
        if is_sqlite:
            # Profiles
            conn.execute(text(
                """
                CREATE TABLE IF NOT EXISTS ai_content_profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    tone TEXT,
                    voice TEXT,
                    target_platform TEXT,
                    guidelines TEXT,
                    settings TEXT DEFAULT '{}',
                    created_at DATETIME DEFAULT (STRFTIME('%Y-%m-%d %H:%M:%f', 'now')),
                    updated_at DATETIME
                )
                """
            ))
            _ensure_sqlite_columns(conn, "ai_content_profiles", [
                ("tone", "tone TEXT"),
                ("voice", "voice TEXT"),
                ("target_platform", "target_platform TEXT"),
                ("guidelines", "guidelines TEXT"),
                ("updated_at", "updated_at DATETIME"),
            ])

            # Jobs
            conn.execute(text(
                """
                CREATE TABLE IF NOT EXISTS ai_content_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    profile_id INTEGER,
                    title TEXT,
                    keywords TEXT,
                    content_type TEXT,
                    brief TEXT,
                    data_sources TEXT,
                    extra TEXT,
                    generated_content TEXT,
                    status TEXT DEFAULT 'completed',
                    created_at DATETIME DEFAULT (STRFTIME('%Y-%m-%d %H:%M:%f', 'now')),
                    updated_at DATETIME
                )
                """
            ))
            _ensure_sqlite_columns(conn, "ai_content_jobs", [
                ("title", "title TEXT"),
                ("keywords", "keywords TEXT"),
                ("content_type", "content_type TEXT"),
                ("brief", "brief TEXT"),
                ("data_sources", "data_sources TEXT"),
                ("extra", "extra TEXT"),
                ("generated_content", "generated_content TEXT"),
                ("updated_at", "updated_at DATETIME"),
            ])

            # Schedules
            conn.execute(text(
                """
                CREATE TABLE IF NOT EXISTS ai_content_schedules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER,
                    platform TEXT,
                    scheduled_for DATETIME NOT NULL,
                    status TEXT DEFAULT 'scheduled',
                    result TEXT,
                    attempts INTEGER DEFAULT 0,
                    last_attempted_at DATETIME,
                    delivery_meta TEXT DEFAULT '{}',
                    created_at DATETIME DEFAULT (STRFTIME('%Y-%m-%d %H:%M:%f', 'now')),
                    updated_at DATETIME
                )
                """
            ))
            _ensure_sqlite_columns(conn, "ai_content_schedules", [
                ("job_id", "job_id INTEGER"),
                ("platform", "platform TEXT"),
                ("result", "result TEXT"),
                ("attempts", "attempts INTEGER DEFAULT 0"),
                ("last_attempted_at", "last_attempted_at DATETIME"),
                ("delivery_meta", "delivery_meta TEXT DEFAULT '{}'"),
                ("updated_at", "updated_at DATETIME"),
            ])
        else:
            # Postgres schema
            conn.execute(text(
                """
                CREATE TABLE IF NOT EXISTS ai_content_profiles (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    tone TEXT,
                    voice TEXT,
                    target_platform TEXT,
                    guidelines TEXT,
                    settings JSONB DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ DEFAULT now(),
                    updated_at TIMESTAMPTZ
                )
                """
            ))
            conn.execute(text(
                """
                CREATE TABLE IF NOT EXISTS ai_content_jobs (
                    id SERIAL PRIMARY KEY,
                    profile_id INTEGER REFERENCES ai_content_profiles(id),
                    title TEXT,
                    keywords TEXT,
                    content_type TEXT,
                    brief TEXT,
                    data_sources TEXT,
                    extra TEXT,
                    generated_content TEXT,
                    status TEXT DEFAULT 'completed',
                    created_at TIMESTAMPTZ DEFAULT now(),
                    updated_at TIMESTAMPTZ
                )
                """
            ))
            conn.execute(text(
                """
                CREATE TABLE IF NOT EXISTS ai_content_schedules (
                    id SERIAL PRIMARY KEY,
                    job_id INTEGER REFERENCES ai_content_jobs(id),
                    platform TEXT,
                    scheduled_for TIMESTAMPTZ NOT NULL,
                    status TEXT DEFAULT 'scheduled',
                    result TEXT,
                    attempts INTEGER DEFAULT 0,
                    last_attempted_at TIMESTAMPTZ,
                    delivery_meta JSONB DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ DEFAULT now(),
                    updated_at TIMESTAMPTZ
                )
                """
            ))

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def parse_schedule_time(val: str) -> datetime:
    # Expect 'YYYY-MM-DDTHH:MM' or with seconds; store naive UTC for sqlite
    if not val:
        raise HTTPException(status_code=400, detail="scheduled_for required")
    s = val.strip()
    if len(s) == 16:
        s += ":00"
    try:
        return datetime.fromisoformat(s)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid datetime format; use YYYY-MM-DDTHH:MM")

def render_html(name: str, ctx: Dict[str, Any] = None) -> HTMLResponse:
    ctx = ctx or {}
    try:
        tpl = templates.get_template(name)
        return HTMLResponse(tpl.render(**ctx))
    except TemplateNotFound as e:
        return HTMLResponse(
            f"<html><body><h3>{name}</h3><pre>TemplateNotFound: {e}; loader dir: {TEMPLATES_DIR}</pre></body></html>",
            status_code=500,
        )
    except Exception as e:
        return HTMLResponse(f"<html><body><h3>{name}</h3><pre>{e}</pre></body></html>", status_code=500)

def sign_session(data: str) -> str:
    sig = hmac.new(BACKEND_SECRET.encode(), data.encode(), hashlib.sha256).hexdigest()
    return f"{data}:{sig}"

def verify_session(signed: str) -> bool:
    try:
        data, sig = signed.rsplit(":", 1)
    except Exception:
        return False
    expected = hmac.new(BACKEND_SECRET.encode(), data.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)

async def ai_call(messages: List[Dict[str, str]], temperature: float = 0.7, timeout: float = None) -> Dict[str, Any]:
    """Call an OpenAI-compatible chat completions endpoint.

    Local mode: when AI_LOCAL=true, no API key is required and the default base is http://127.0.0.1:11434/v1 (Ollama-compatible).
    """
    timeout = timeout or AI_TIMEOUT
    url = f"{AI_API_BASE.rstrip('/')}/chat/completions"
    payload = {"model": AI_MODEL, "messages": messages, "temperature": temperature}
    headers = {"Content-Type": "application/json"}
    if AI_API_KEY:
        headers["Authorization"] = f"Bearer {AI_API_KEY}"
    elif not AI_LOCAL:
        # no API key and not in local mode — surface clear error to enable fallback
        raise HTTPException(status_code=500, detail="AI_API_KEY not configured (set AI_LOCAL=true to use a local server)")
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(url, json=payload, headers=headers)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        # map HTTPX errors to a 502 for clarity
        raise HTTPException(status_code=502, detail=f"AI provider error: {str(e)}")

def build_ai_messages(system_prompt: str, user_prompt: str) -> List[Dict[str, str]]:
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]


@app.get("/ai/config")
async def ai_config():
    """Expose current AI configuration (non-sensitive) and reachability.

    Useful for local AI workflows to confirm the server is reachable and which model/base are active.
    """
    reachable = False
    detail = None
    try:
        # Try a lightweight probe: GET /models (Ollama & most OpenAI-compatible servers expose this)
        url = f"{AI_API_BASE.rstrip('/')}/models"
        headers = {}
        if AI_API_KEY:
            headers["Authorization"] = f"Bearer {AI_API_KEY}"
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(url, headers=headers)
            reachable = r.status_code < 500
    except Exception as e:
        detail = str(e)
    return {
        "local": AI_LOCAL,
        "api_base": AI_API_BASE,
        "model": AI_MODEL,
        "reachable": reachable,
        "note": detail,
    }

@app.on_event("startup")
async def startup_event():
    init_db()
    # Auto-seed basic content and sample backgrounds if empty
    try:
        seed_profiles_and_jobs()
    except Exception as e:
        print("Seed profiles/jobs warning:", e)
    try:
        if not media_mod.list_backgrounds():
            media_mod.seed_backgrounds()
    except Exception as e:
        print("Seed backgrounds warning:", e)
    global _scheduler
    # Only start scheduler if explicitly enabled and database is not SQLite
    enable = os.getenv("SCHEDULER_ENABLED", "false").lower() in ("1", "true", "yes")
    is_sqlite = str(engine.url).lower().startswith("sqlite")
    if enable and not is_sqlite:
        try:
            # local import to avoid hard crash if scheduler file missing or broken
            from backend.app.scheduler import AIScheduleDispatcher
            _scheduler = AIScheduleDispatcher(engine=engine)
            await _scheduler.start()
            print("Backend started. Scheduler running.")
        except Exception as e:
            # keep the app up even if scheduler can't start; surface a clear warning
            print("Backend startup warning: scheduler failed to start:", e)
    else:
        print("Scheduler disabled (SCHEDULER_ENABLED not set or using SQLite)")

@app.on_event("shutdown")
async def shutdown_event():
    global _scheduler
    if _scheduler:
        try:
            await _scheduler.stop()
        except Exception as e:
            print("Scheduler shutdown warning:", e)
        _scheduler = None
    print("Backend shutdown complete.")

@app.get("/health")
async def health():
    return {"status": "ok"}

# Mount media directory for serving generated videos locally
try:
    app.mount("/media", StaticFiles(directory=str(media_mod.MEDIA_DIR)), name="media")
except Exception:
    # In case MEDIA_DIR is not accessible at import time; this is non-fatal
    pass

@app.get("/ui/ai-content", response_class=HTMLResponse)
async def ui_ai_content(request: Request):
    return render_html("ai_content.html")

@app.get("/ui/{page}", response_class=HTMLResponse)
async def ui_page(page: str):
    name = page
    if not name.endswith(".html"):
        name = f"{name}.html"
    return render_html(name)

@app.get("/", response_class=HTMLResponse)
async def root():
    return render_html("ai_content.html")

@app.get("/debug/templates")
async def debug_templates():
    try:
        import os
        listing = []
        for entry in os.listdir(TEMPLATES_DIR):
            listing.append(entry)
        exists = True
    except Exception as e:
        listing = [str(e)]
        exists = False
    return {"templates_dir": TEMPLATES_DIR, "exists": exists, "entries": listing}

@app.get("/ai/publishers")
async def api_list_publishers():
    from backend.app.publishers import list_publishers
    return {"publishers": list_publishers()}

@app.post("/ai/publishers/{slug}/health")
async def api_publisher_health(slug: str):
    pub = get_publisher(slug)
    if not pub or not hasattr(pub, "health_check"):
        return {"result": {"success": False, "message": "Publisher not available"}}
    try:
        res = pub.health_check()
        # normalize response keys to success/message
        if isinstance(res, dict):
            if "ok" in res and "success" not in res:
                res = {**res, "success": bool(res.get("ok"))}
            if "detail" in res and "message" not in res:
                res = {**res, "message": res.get("detail")}
    except Exception as e:
        res = {"success": False, "message": str(e)}
    return {"result": res}

# ---------- Profiles ----------
@app.get("/ai/profiles")
async def api_profiles_list():
    with engine.begin() as conn:
        rows = conn.execute(text(
            """
            SELECT id, name, tone, voice, target_platform, guidelines,
                   created_at, updated_at
            FROM ai_content_profiles
            ORDER BY COALESCE(updated_at, created_at) DESC, id DESC
            """
        )).mappings().all()
    return {"profiles": [dict(r) for r in rows]}

@app.post("/ai/profiles")
async def api_profiles_create(body: Dict[str, Any]):
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, detail="name is required")
    tone = body.get("tone")
    voice = body.get("voice")
    target_platform = body.get("target_platform")
    guidelines = body.get("guidelines")
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        conn.execute(text(
            """
            INSERT INTO ai_content_profiles(name, tone, voice, target_platform, guidelines, updated_at)
            VALUES (:name, :tone, :voice, :target_platform, :guidelines, :updated_at)
            """
        ), {
            "name": name, "tone": tone, "voice": voice,
            "target_platform": target_platform, "guidelines": guidelines,
            "updated_at": now,
        })
    return {"ok": True}

@app.delete("/ai/profiles/{pid}")
async def api_profiles_delete(pid: int):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM ai_content_profiles WHERE id=:id"), {"id": pid})
    return {"ok": True}

# ---------- Content Generation ----------
def _build_prompt_from_profile(conn, profile_id: Optional[int], body: Dict[str, Any]) -> Tuple[str, str]:
    system = "You are a content generation assistant."
    # user will be constructed later
    if profile_id:
        row = conn.execute(text("SELECT * FROM ai_content_profiles WHERE id=:id"), {"id": profile_id}).mappings().first()
        if row:
            parts = [
                "Tone: {}".format(row.get('tone') or ''),
                "Voice: {}".format(row.get('voice') or ''),
                "Primary platforms: {}".format(row.get('target_platform') or ''),
                "Guidelines: {}".format(row.get('guidelines') or ''),
            ]
            system = "You write on-brand content.\n" + "\n".join(parts)
    title = body.get("title") or ""
    keywords = body.get("keywords") or ""
    extra = body.get("extra") or ""
    user = "Title: {}\nKeywords: {}\nBrief: {}\nExtra: {}".format(title, keywords, body.get('brief') or '', extra)
    return system, user

def _fallback_generate(body: Dict[str, Any]) -> str:
    title = body.get('title') or 'Untitled'
    ctype = (body.get('content_type') or 'custom').lower()
    keywords = body.get('keywords') or '-'
    brief = (body.get('brief') or '').strip()
    extra = (body.get('extra') or '').strip()
    if ctype == 'social-post':
        kw = [k.strip() for k in str(keywords).split(',') if k.strip()]
        tag = (kw[0] if kw else 'content').lower()
        content = [
            f"# {title}",
            f"Keywords: {keywords}",
            "",
            "Post 1:",
            f"- Hook: {title} — you won't believe this {tag} twist.",
            f"- Body: Quick hit: what happened, why it matters, and the hidden detail everyone misses.",
            f"- CTA: Follow for more {tag} drops like this.",
            "",
            "Post 2:",
            f"- Hook: The moment that changed everything in {title}.",
            f"- Body: Set the scene, deliver the surprise, then land the takeaway.",
            f"- CTA: Share with a friend who needs this.",
            "",
            "Post 3:",
            f"- Hook: If you missed {title}, here's the 15s recap.",
            f"- Body: Three beats: setup · twist · payoff. Simple and tight.",
            f"- CTA: Save this so you don't forget.",
        ]
    elif ctype == 'reddit-story':
        kw = [k.strip() for k in str(keywords).split(',') if k.strip()]
        tag = (kw[0] if kw else 'story').lower()
        content = [
            f"# {title}",
            f"Keywords: {keywords}",
            "",
            "Intro:",
            f"Last night I was deep in {tag} mode when something felt off. Not the usual kind of off, either.",
            "",
            "The twist:",
            f"Halfway in, a tiny detail changed the entire vibe. I paused, rewound, and realized what I missed.",
            "",
            "Build-up:",
            "I started connecting dots — the noise, the timing, the way the room felt colder than it should.",
            "",
            "Climax:",
            f"Suddenly, it clicked. The whole {title} moment wasn’t random — it was building to this.",
            "",
            "Aftermath:",
            "I saved the clip, turned the lights back on, and laughed at how hard I got baited.",
            "",
            "CTA:",
            "Tell me the exact second you realized something was wrong — I bet it’s not where you think.",
        ]
    elif ctype == 'video-script':
        content = [
            f"# {title}",
            f"Keywords: {keywords}",
            "",
            "0-2s: Cold open — smash cut to the most surprising moment.",
            f"2-7s: Hook — '{title}' in one line, with a visual tease.",
            "7-20s: Setup — where we were, what we expected, and what changed.",
            "20-45s: The twist — tight cuts, punchy lines, build tension.",
            "45-55s: Payoff — the reveal and why it matters.",
            "55-60s: CTA — follow for part 2 or comment your take.",
        ]
    else:
        content = [
            f"# {title}",
            f"Type: {ctype}",
            f"Keywords: {keywords}",
            "",
            "Draft outline:",
            "- Hook",
            "- Body",
            "- CTA",
        ]
    if brief:
        content.append("")
        content.append("Brief:")
        content.append(brief)
    if extra:
        content.append("")
        content.append("Operator notes:")
        content.append(extra)
    return "\n".join(content)

@app.post("/ai/content")
async def api_content(body: Dict[str, Any]):
    profile_id = body.get("profile_id")
    content_type = body.get("content_type") or "custom"
    title = body.get("title") or "Untitled"
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        # Build prompt
        system, user = _build_prompt_from_profile(conn, int(profile_id) if profile_id else None, body)
    try:
        messages = build_ai_messages(system, user)
        ai_resp = await ai_call(messages)
        generated = ai_resp.get("choices", [{}])[0].get("message", {}).get("content") if isinstance(ai_resp, dict) else None
        if not generated:
            generated = _fallback_generate(body)
        note = "AI generated"
    except HTTPException:
        generated = _fallback_generate(body)
        note = "AI disabled — used fallback template"
    with engine.begin() as conn:
        conn.execute(text(
            """
            INSERT INTO ai_content_jobs(profile_id, title, keywords, content_type, brief, data_sources, extra, generated_content, status, created_at, updated_at)
            VALUES (:profile_id, :title, :keywords, :content_type, :brief, :data_sources, :extra, :generated_content, 'completed', :created_at, :updated_at)
            """
        ), {
            "profile_id": int(profile_id) if profile_id else None,
            "title": title,
            "keywords": body.get("keywords"),
            "content_type": content_type,
            "brief": body.get("brief"),
            "data_sources": body.get("data_sources"),
            "extra": body.get("extra"),
            "generated_content": generated,
            "created_at": now,
            "updated_at": now,
        })
        row = conn.execute(text("SELECT last_insert_rowid() as id" if str(engine.url).lower().startswith("sqlite") else "SELECT currval(pg_get_serial_sequence('ai_content_jobs','id')) as id")).mappings().first()
        job_id = int(row["id"]) if row else None
    return {"job": {
        "id": job_id,
        "title": title,
        "content_type": content_type,
        "generated_content": generated,
        "status": "completed",
    }, "note": note}

@app.get("/ai/jobs")
async def api_jobs_list():
    with engine.begin() as conn:
        sql = (
            "SELECT j.*, p.name AS profile_name, p.target_platform AS profile_platform "
            "FROM ai_content_jobs j LEFT JOIN ai_content_profiles p ON p.id=j.profile_id "
            "ORDER BY COALESCE(j.updated_at, j.created_at) DESC, j.id DESC LIMIT 50"
        )
        rows = conn.execute(text(sql)).mappings().all()
    # add simple ISO times
    out = []
    for r in rows:
        d = dict(r)
        if d.get("created_at"):
            d["created_at"] = str(d["created_at"])
        if d.get("updated_at"):
            d["updated_at"] = str(d["updated_at"])
        out.append(d)
    return {"jobs": out}

# ---------- Scheduling ----------
def _schedule_row_to_dto(row: Dict[str, Any]) -> Dict[str, Any]:
    d = dict(row)
    if d.get("scheduled_for"):
        # normalize to ISO string for UI
        try:
            d["scheduled_for_iso"] = d["scheduled_for"].isoformat() if hasattr(d["scheduled_for"], "isoformat") else str(d["scheduled_for"])
        except Exception:
            d["scheduled_for_iso"] = str(d["scheduled_for"])
    return d

@app.get("/ai/schedule")
async def api_schedule_list():
    with engine.begin() as conn:
        rows = conn.execute(text(
            """
            SELECT s.*, j.title AS job_title, p.name AS job_profile_name, j.content_type AS job_content_type
            FROM ai_content_schedules s
            LEFT JOIN ai_content_jobs j ON j.id = s.job_id
            LEFT JOIN ai_content_profiles p ON p.id = j.profile_id
            ORDER BY COALESCE(s.updated_at, s.created_at) DESC, s.id DESC
            """
        )).mappings().all()
    return {"schedules": [_schedule_row_to_dto(r) for r in rows]}

@app.post("/ai/schedule")
async def api_schedule_create(body: Dict[str, Any]):
    job_id = body.get("job_id")
    platform = (body.get("platform") or "").strip()
    when = parse_schedule_time(body.get("scheduled_for"))
    if not job_id or not platform:
        raise HTTPException(400, detail="job_id and platform are required")
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        conn.execute(text(
            """
            INSERT INTO ai_content_schedules(job_id, platform, scheduled_for, status, created_at, updated_at)
            VALUES (:job_id, :platform, :when, 'scheduled', :created_at, :updated_at)
            """
        ), {"job_id": int(job_id), "platform": platform, "when": when, "created_at": now, "updated_at": now})
    return {"ok": True}

@app.put("/ai/schedule/{sid}")
async def api_schedule_update(sid: int, body: Dict[str, Any]):
    platform = (body.get("platform") or "").strip()
    when = parse_schedule_time(body.get("scheduled_for"))
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE ai_content_schedules SET platform=:platform, scheduled_for=:when, updated_at=:now WHERE id=:id"
        ), {"platform": platform, "when": when, "now": now, "id": sid})
    return {"ok": True}

@app.post("/ai/schedule/{sid}/cancel")
async def api_schedule_cancel(sid: int):
    now = datetime.utcnow()
    with engine.begin() as conn:
        conn.execute(text("UPDATE ai_content_schedules SET status='canceled', updated_at=:now WHERE id=:id"), {"now": now, "id": sid})
    return {"ok": True}

@app.post("/ai/schedule/{sid}/retry")
async def api_schedule_retry(sid: int):
    now = datetime.utcnow()
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE ai_content_schedules SET status='scheduled', result=NULL, updated_at=:now WHERE id=:id"
        ), {"now": now, "id": sid})
    return {"ok": True}

# Minimal endpoint to dry-run publisher payload
@app.post("/publish/{publisher_name}/dry_run")
async def publish_dry_run(publisher_name: str, job: Dict[str, Any]):
    publisher = get_publisher(publisher_name)
    if not publisher:
        raise HTTPException(status_code=404, detail="publisher not found")
    health = publisher.health_check()
    ok = bool(health.get("success") if isinstance(health, dict) else False)
    if not ok:
        raise HTTPException(status_code=400, detail="publisher not healthy")
    payload = job
    if hasattr(publisher, "prepare_payload"):
        try:
            payload = publisher.prepare_payload(job)
        except Exception:
            payload = job
    return {"publisher": publisher_name, "dry_run_payload": payload}


# ---------- Video generation ----------
def _ensure_text(value: Optional[str], fallback: str = "") -> str:
    return (value or fallback).strip()


@app.post("/ai/video")
async def api_generate_video(body: Dict[str, Any]):
    """Generate a vertical short video from a job or raw text using fully local tools.

    Accepts:
      - job_id: int (fetches title and generated_content from ai_content_jobs)
      - title: str
      - script: str
    Returns a JSON with video filename and a local URL under /media.
    """
    job_id = body.get("job_id")
    title = _ensure_text(body.get("title"))
    script = _ensure_text(body.get("script"))
    if job_id and (not title or not script):
        with engine.begin() as conn:
            row = conn.execute(text("SELECT title, generated_content FROM ai_content_jobs WHERE id=:id"), {"id": int(job_id)}).mappings().first()
            if not row:
                raise HTTPException(status_code=404, detail="job not found")
            title = _ensure_text(title, row.get("title") or "Untitled")
            script = _ensure_text(script, row.get("generated_content") or "")
    if not title or not script:
        raise HTTPException(status_code=400, detail="title and script are required (or provide job_id)")

    # Optional parameters
    background = (body.get("background") or body.get("background_name") or "").strip() or None
    subtitles = bool(body.get("subtitles", True))
    draw_title = bool(body.get("draw_title", True))
    tts_rate = body.get("tts_rate")
    tts_voice = body.get("tts_voice")
    # Advanced options
    min_duration_secs = body.get("min_duration") or body.get("min_duration_secs")
    try:
        min_duration_secs = int(min_duration_secs) if min_duration_secs is not None else None
    except Exception:
        min_duration_secs = None
    music = bool(body.get("music", False))
    ducking = bool(body.get("ducking", True))
    music_volume = body.get("music_volume", 0.15)
    try:
        music_volume = float(music_volume)
    except Exception:
        music_volume = 0.15

    # Generate locally using media module
    try:
        meta = media_mod.generate_short(
            title=title,
            script=script,
            background_name=background,
            subtitles=subtitles,
            draw_title=draw_title,
            tts_rate=tts_rate,
            tts_voice=tts_voice,
            min_duration_secs=min_duration_secs,
            music=music,
            music_volume=music_volume,
            ducking=ducking,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"video generation failed: {e}")
    filename = meta.get("filename")
    url = f"/media/{filename}"
    return {"video": {"filename": filename, "url": url}, "meta": meta}


@app.get("/media/raw/{filename}")
async def media_raw(filename: str):
    """Serve raw media file by filename from MEDIA_DIR."""
    path = media_mod.MEDIA_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(path)


@app.get("/ai/video/backgrounds")
async def list_backgrounds():
    try:
        items = media_mod.list_backgrounds()
        return {"backgrounds": items}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/ai/video/backgrounds/seed")
async def seed_backgrounds():
    try:
        return media_mod.seed_backgrounds()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/ai/voices")
async def list_voices(refresh: bool = False):
    """List available local TTS voices.

    Caches the result for ~60s to avoid repeated shell or library calls. Pass refresh=true to bypass cache.
    """
    import shutil, subprocess, time
    global _voices_cache_data, _voices_cache_ts

    now = time.time()
    if not refresh and _voices_cache_data and (now - _voices_cache_ts) < 60.0:
        return _voices_cache_data

    result: Dict[str, Any] = {"voices": []}
    # Try pyttsx3 first
    try:
        import pyttsx3
        try:
            engine = pyttsx3.init()
            out = []
            for v in engine.getProperty("voices") or []:
                out.append({
                    "id": getattr(v, 'id', None),
                    "name": getattr(v, 'name', None),
                    "languages": [str(x) for x in (getattr(v, 'languages', []) or [])],
                    "gender": getattr(v, 'gender', None),
                    "age": getattr(v, 'age', None),
                })
            if out:
                result = {"voices": out}
        except Exception:
            pass
    except Exception:
        # pyttsx3 import failed; continue to CLI fallback
        pass

    # Fallback: attempt to list voices from espeak-ng or espeak
    if not result.get("voices"):
        speak = shutil.which('espeak-ng') or shutil.which('espeak')
        if speak:
            try:
                # espeak-ng --voices prints table; parse names in column 4 (Variant) or 3 (Language) if missing
                out = subprocess.check_output([speak, '--voices'], stderr=subprocess.STDOUT).decode('utf-8', errors='ignore')
                lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
                results = []
                # Skip header lines
                for ln in lines:
                    if ln.lower().startswith('pty') or ln.lower().startswith('enabled') or ln.lower().startswith('idx'):
                        continue
                    parts = [p for p in ln.split(' ') if p]
                    # Typical columns: Pty Language Age/Gender VoiceName File ...
                    if len(parts) >= 4:
                        lang = parts[1]
                        name = parts[3]
                        results.append({"id": name, "name": name, "languages": [lang]})
                result = {"voices": results}
            except Exception:
                pass

    # Last resort: no voices available; return empty list rather than 500 to keep UI usable
    if not result.get("voices"):
        result = {"voices": [], "note": "No local TTS voice list available (install espeak-ng, then click Refresh voices)."}

    # Update cache
    _voices_cache_data = result
    _voices_cache_ts = now
    return result


@app.post("/ai/voices/preview")
async def voice_preview(body: Dict[str, Any]):
    text = (body.get('text') or '').strip() or 'This is a sample voice.'
    rate = body.get('rate')
    try:
        rate = int(rate) if rate is not None else None
    except Exception:
        rate = None
    voice = (body.get('voice') or '').strip() or None
    try:
        meta = media_mod.tts_preview(text=text, rate=rate, voice=voice)
        return {"preview": {"filename": meta.get('filename'), "url": f"/media/{meta.get('filename')}"}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _db_scalar(conn, sql: str) -> int:
    row = conn.execute(text(sql)).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def seed_profiles_and_jobs():
    now = datetime.utcnow()
    with engine.begin() as conn:
        profiles_count = _db_scalar(conn, "SELECT COUNT(*) FROM ai_content_profiles")
        if profiles_count == 0:
            samples = [
                {"name": "Viral Gamer", "tone": "energetic", "voice": "casual", "target_platform": "TikTok · YouTube Shorts", "guidelines": "Hook in 2s, clear beats, strong CTA"},
                {"name": "Finance Bites", "tone": "authoritative", "voice": "mentor", "target_platform": "Instagram Reels", "guidelines": "No jargon, always add a disclaimer"},
            ]
            for s in samples:
                conn.execute(text(
                    """
                    INSERT INTO ai_content_profiles(name, tone, voice, target_platform, guidelines, updated_at)
                    VALUES (:name, :tone, :voice, :target_platform, :guidelines, :updated_at)
                    """
                ), {**s, "updated_at": now})
        jobs_count = _db_scalar(conn, "SELECT COUNT(*) FROM ai_content_jobs")
        if jobs_count == 0:
            # Create one job per sample profile
            rows = conn.execute(text("SELECT id, name FROM ai_content_profiles ORDER BY id ASC LIMIT 2")).mappings().all()
            for r in rows:
                title = f"{r['name']} — First drop"
                outline = "# Script\n0-2s: Cold open\n2-7s: Hook\n7-20s: Setup\n20-45s: Twist\n45-55s: Payoff\n55-60s: CTA"
                conn.execute(text(
                    """
                    INSERT INTO ai_content_jobs(profile_id, title, content_type, generated_content, status, created_at, updated_at)
                    VALUES (:pid, :title, 'video-script', :content, 'completed', :now, :now)
                    """
                ), {"pid": r['id'], "title": title, "content": outline, "now": now})


@app.post("/ai/seed")
async def api_seed_all():
    try:
        seed_profiles_and_jobs()
        bg = media_mod.seed_backgrounds()
        return {"ok": True, "backgrounds": bg.get("generated", [])}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
