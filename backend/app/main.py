import os, time, base64, hmac, hashlib, json, sys, traceback
from typing import Optional, List
from fastapi import FastAPI, Depends, HTTPException, status, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from passlib.hash import bcrypt
import httpx
from jinja2 import Environment, FileSystemLoader, TemplateNotFound

# --- Config from env ---
DATABASE_URL = os.environ["DATABASE_URL"]
SECRET = os.environ.get("BACKEND_SECRET", "change-me")

PVE_HOST = os.environ.get("PVE_HOST", "")
PVE_TOKEN_ID = os.environ.get("PVE_TOKEN_ID", "")
PVE_TOKEN_SECRET = os.environ.get("PVE_TOKEN_SECRET", "")

SMTP_HOST = os.environ.get("SMTP_HOST","")
SMTP_PORT = int(os.environ.get("SMTP_PORT","587"))
SMTP_USER = os.environ.get("SMTP_USER","")
SMTP_PASS = os.environ.get("SMTP_PASS","")
SMTP_FROM = os.environ.get("SMTP_FROM","")

TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")

NC_BASE = os.environ.get("NEXTCLOUD_BASE","http://nextcloud")
NC_ADMIN = os.environ.get("NEXTCLOUD_ADMIN","admin")
NC_ADMIN_PASS = os.environ.get("NEXTCLOUD_ADMIN_PASS","admin")

# --- DB ---
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
Session = sessionmaker(bind=engine)

# --- Jinja templates (absolute path, safe) ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=True)

app = FastAPI(title="TeamOps Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# --- DB bootstrap ---
def init_db():
    with engine.begin() as conn:
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS users(
            id SERIAL PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('leader','coowner')),
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS notes(
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS announcements(
            id SERIAL PRIMARY KEY,
            author_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS audit(
            id SERIAL PRIMARY KEY,
            actor_email TEXT NOT NULL,
            action TEXT NOT NULL,
            meta JSONB,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """))

init_db()

# --- session token (HMAC)
def sign_session(email: str) -> str:
    t = str(int(time.time()))
    msg = f"{email}|{t}"
    sig = hmac.new(SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{msg}|{sig}".encode()).decode()

def verify_session(token: str) -> Optional[str]:
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        email, ts, sig = raw.split("|")
        expect = hmac.new(SECRET.encode(), f"{email}|{ts}".encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expect, sig):
            return None
        if time.time() - int(ts) > 60*60*24*7:  # 7 days
            return None
        return email
    except Exception:
        return None

# --- template render (no hard crashes)
def render(name: str, **ctx):
    try:
        tpl = env.get_template(name)
        return HTMLResponse(tpl.render(**ctx))
    except TemplateNotFound:
        msg = f"[TEMPLATE ERROR] Not found: {name}"
        print(msg, file=sys.stderr)
        return PlainTextResponse(msg, status_code=500)
    except Exception as e:
        print(f"[RENDER ERROR] {name}: {e}", file=sys.stderr)
        traceback.print_exc()
        return PlainTextResponse("Internal Server Error", status_code=500)

# --- auth helpers
def current_user(req: Request) -> Optional[str]:
    tok = req.cookies.get("session", "")
    return verify_session(tok) if tok else None

def require_user(req: Request) -> str:
    email = current_user(req)
    if not email:
        raise HTTPException(status_code=401, detail="login required")
    return email

# --- admin bootstrap endpoint used by setup.sh once
@app.post("/admin/init")
def admin_init(payload: dict):
    admin_email = payload["admin_email"]; admin_pass = payload["admin_pass"]
    oded_email = payload["oded_email"]; oded_pass = payload["oded_pass"]
    orel_email = payload["orel_email"]; orel_pass = payload["orel_pass"]
    with engine.begin() as conn:
        for email, pwd, role in [
            (admin_email, admin_pass, "leader"),
            (oded_email, oded_pass, "coowner"),
            (orel_email, orel_pass, "coowner"),
        ]:
            hash_ = bcrypt.hash(pwd)
            conn.execute(text("""
              INSERT INTO users(email,password_hash,role)
              VALUES (:e,:p,:r)
              ON CONFLICT (email) DO NOTHING
            """), {"e": email, "p": hash_, "r": role})
    return {"ok": True}

# --- UI: login (GET + POST)
@app.get("/ui/login", response_class=HTMLResponse)
def login_form():
    return render("login.html")

@app.post("/ui/login")
def do_login(email: str = Form(...), password: str = Form(...)):
    with engine.begin() as conn:
        row = conn.execute(text("SELECT id,password_hash,role FROM users WHERE email=:e"), {"e": email}).fetchone()
    if not row or not bcrypt.verify(password, row.password_hash):
        return render("login.html", error="Invalid credentials")
    token = sign_session(email)
    resp = RedirectResponse("/ui/announcements", status_code=302)
    resp.set_cookie("session", token, httponly=True, samesite="lax")
    return resp

# --- UI: announcements (safe)
@app.get("/ui/announcements", response_class=HTMLResponse)
def ui_ann(req: Request):
    email = require_user(req)
    with engine.begin() as conn:
        anns = conn.execute(text("""
            SELECT COALESCE(u.email,'system') AS author, a.content, a.created_at
            FROM announcements a
            LEFT JOIN users u ON a.author_id=u.id
            ORDER BY a.id DESC
            LIMIT 50
        """)).fetchall()
    # Map to (content, author, dt)
    anns_fmt = [(row.content, row.author, row.created_at) for row in anns]
    return render("announcements.html", email=email, anns=anns_fmt)

@app.post("/api/announcements")
def post_ann(req: Request, payload: dict):
    email = require_user(req)
    content = (payload.get("content") or "").strip()
    if not content:
        raise HTTPException(400,"empty")
    with engine.begin() as conn:
        uid = conn.execute(text("SELECT id FROM users WHERE email=:e"),{"e":email}).fetchone().id
        conn.execute(text("INSERT INTO announcements(author_id,content) VALUES (:uid,:c)"),{"uid":uid,"c":content})
        conn.execute(text("INSERT INTO audit(actor_email,action,meta) VALUES (:e,'announce',:m)"),
                     {"e":email,"m":json.dumps({"content":content[:160]})})
    return {"ok": True}

# --- UI: user page (no query needed)
@app.get("/ui/user", response_class=HTMLResponse)
def ui_user(req: Request):
    viewer = require_user(req)
    with engine.begin() as conn:
        u = conn.execute(text("SELECT id,email,role FROM users WHERE email=:e"),{"e":viewer}).fetchone()
        notes = conn.execute(text("SELECT content,created_at FROM notes WHERE user_id=:id ORDER BY id DESC LIMIT 50"),{"id":u.id}).fetchall()
    return render("user.html", viewer=viewer, u=u, notes=notes)

@app.post("/api/notes")
def add_note(req: Request, payload: dict):
    email = require_user(req)
    content = (payload.get("content") or "").trim()
    if not content:
        raise HTTPException(400,"empty")
    with engine.begin() as conn:
        uid = conn.execute(text("SELECT id FROM users WHERE email=:e"),{"e":email}).fetchone().id
        conn.execute(text("INSERT INTO notes(user_id,content) VALUES (:uid,:c)"),{"uid":uid,"c":content})
        conn.execute(text("INSERT INTO audit(actor_email,action,meta) VALUES (:e,'note',:m)"),
                     {"e":email,"m":json.dumps({"content":content[:120]})})
    return {"ok": True}

# --- Proxmox helpers + UI
async def pve_get(path: str):
    headers = {"Authorization": f"PVEAPIToken={PVE_TOKEN_ID}={PVE_TOKEN_SECRET}"}
    async with httpx.AsyncClient(verify=False, timeout=10) as c:
        r = await c.get(f"{PVE_HOST}/api2/json{path}", headers=headers)
        r.raise_for_status()
        return r.json()["data"]

async def pve_post(path: str, data=None):
    headers = {"Authorization": f"PVEAPIToken={PVE_TOKEN_ID}={PVE_TOKEN_SECRET}"}
    async with httpx.AsyncClient(verify=False, timeout=10) as c:
        r = await c.post(f"{PVE_HOST}/api2/json{path}", headers=headers, data=data or {})
        r.raise_for_status()
        return r.json().get("data")

@app.get("/ui/proxmox-summary", response_class=HTMLResponse)
async def ui_pve_summary(req: Request):
    _ = require_user(req)
    try:
        nodes = await pve_get("/nodes")
    except Exception as e:
        nodes = []
        print("[PVE] summary error:", e, file=sys.stderr)
    guests = []
    try:
        for n in nodes:
            gs = await pve_get(f"/nodes/{n['node']}/qemu")
            cs = await pve_get(f"/nodes/{n['node']}/lxc")
            for g in gs + cs:
                g["node"] = n["node"]
                guests.append(g)
    except Exception as e:
        print("[PVE] guests error:", e, file=sys.stderr)
    return render("pve_summary.html", nodes=nodes, guests=guests, host=PVE_HOST)

@app.get("/ui/proxmox-vms", response_class=HTMLResponse)
async def ui_pve_vms(req: Request):
    _ = require_user(req)
    vms = []
    nodes = []
    try:
        nodes = await pve_get("/nodes")
        for n in nodes:
            qmus = await pve_get(f"/nodes/{n['node']}/qemu")
            for v in qmus:
                vms.append({"type":"qemu","node":n["node"], **v})
            lxcs = await pve_get(f"/nodes/{n['node']}/lxc")
            for v in lxcs:
                vms.append({"type":"lxc","node":n["node"], **v})
    except Exception as e:
        print("[PVE] vms error:", e, file=sys.stderr)
    return render("pve_vms.html", vms=vms, host=PVE_HOST)

@app.post("/api/pve/{kind}/{node}/{vmid}/{action}")
async def pve_action(req: Request, kind: str, node: str, vmid: int, action: str):
    email = require_user(req)
    allowed = {"start","stop","shutdown","reset","reboot","resume","suspend","snapshot"}
    if action not in allowed:
        raise HTTPException(400,"bad action")
    path_base = f"/nodes/{node}/{ 'qemu' if kind=='qemu' else 'lxc' }/{vmid}"
    if action=="snapshot":
        snapname = f"dash_{int(time.time())}"
        await pve_post(f"{path_base}/snapshot", {"snapname": snapname})
    else:
        await pve_post(f"{path_base}/status/{action}")
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO audit(actor_email,action,meta) VALUES (:e,:a,:m)"),
                     {"e":email, "a":f"pve:{action}", "m":json.dumps({"kind":kind,"node":node,"vmid":vmid})})
    return {"ok": True}

# --- Nextcloud simple provisioning (optional)
@app.get("/ui/admin", response_class=HTMLResponse)
def ui_admin(req: Request):
    email = require_user(req)
    return render("admin.html", email=email)

@app.post("/api/nextcloud/users")
def create_nc_user(req: Request, payload: dict):
    email = require_user(req)
    username = payload["username"]; password = payload["password"]; displayname = payload.get("displayname", username)
    url = f"{NC_BASE}/ocs/v2.php/cloud/users"
    headers = {"OCS-APIRequest":"true"}
    auth=(NC_ADMIN, NC_ADMIN_PASS)
    r = httpx.post(url, headers=headers, auth=auth, data={"userid":username, "password":password, "displayName":displayname})
    if r.status_code not in (200,201):
        raise HTTPException(400, f"NC error {r.status_code}: {r.text}")
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO audit(actor_email,action,meta) VALUES (:e,'nextcloud:create_user',:m)"),
                     {"e":email,"m":json.dumps({"username":username})})
    return {"ok": True}

@app.get("/health")
def health(): return {"ok": True}

