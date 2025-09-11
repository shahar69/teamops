import os, time, base64, hmac, hashlib, json, sys, traceback
from typing import Optional, List, Tuple
from fastapi import FastAPI, HTTPException, Request, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from passlib.hash import bcrypt
import httpx
from jinja2 import Environment, FileSystemLoader, TemplateNotFound

# ---------- Config ----------
DATABASE_URL = os.environ["DATABASE_URL"]  # e.g. postgresql+psycopg2://teamops:pass@db:5432/teamops
SECRET = os.environ.get("BACKEND_SECRET", "change-me-please")

PVE_HOST = os.environ.get("PVE_HOST", "https://proxmox:8006")
PVE_TOKEN_ID = os.environ.get("PVE_TOKEN_ID", "teamops@pve!dash")
PVE_TOKEN_SECRET = os.environ.get("PVE_TOKEN_SECRET", "")

NC_BASE = os.environ.get("NEXTCLOUD_BASE","http://nextcloud")
NC_ADMIN = os.environ.get("NEXTCLOUD_ADMIN","admin")
NC_ADMIN_PASS = os.environ.get("NEXTCLOUD_ADMIN_PASS","admin")

KUMA_URL = os.environ.get("KUMA_URL", "http://kuma:3001")
KUMA_TOKEN = os.environ.get("KUMA_TOKEN", "")

# ---------- DB ----------
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
Session = sessionmaker(bind=engine)

# ---------- Jinja ----------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=True)

# ---------- App ----------
app = FastAPI(title="TeamOps Backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# ---------- DB bootstrap ----------
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
        CREATE TABLE IF NOT EXISTS vm_permissions(
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            node TEXT NOT NULL,
            vmid INTEGER NOT NULL,
            can_power BOOLEAN DEFAULT true,
            can_snapshot BOOLEAN DEFAULT false,
            PRIMARY KEY(user_id, node, vmid)
        );
        CREATE TABLE IF NOT EXISTS ci_profiles(
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            ciuser TEXT,
            cipassword TEXT,
            sshkeys TEXT,
            ipconfig0 TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS customers(
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            contact TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS vm_customers(
            node TEXT NOT NULL,
            vmid INTEGER NOT NULL,
            customer_id INTEGER REFERENCES customers(id) ON DELETE CASCADE,
            PRIMARY KEY(node, vmid)
        );
        """))
init_db()

# ---------- Sessions ----------
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

def current_email(req: Request) -> Optional[str]:
    tok = req.cookies.get("session", "")
    return verify_session(tok) if tok else None

def require_user(req: Request) -> Tuple[int,str,str]:
    email = current_email(req)
    if not email:
        raise HTTPException(status_code=401, detail="login required")
    with engine.begin() as conn:
        row = conn.execute(text("SELECT id,email,role FROM users WHERE email=:e"), {"e": email}).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="unknown user")
    return row.id, row.email, row.role

def audit(email: str, action: str, meta: dict):
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO audit(actor_email,action,meta) VALUES (:e,:a,:m)"),
                     {"e":email, "a":action, "m":json.dumps(meta)})

# ---------- Bootstrap users ----------
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
            conn.execute(text("""
              INSERT INTO users(email,password_hash,role)
              VALUES (:e,:p,:r)
              ON CONFLICT (email) DO NOTHING
            """), {"e": email, "p": bcrypt.hash(pwd), "r": role})
    return {"ok": True}

# ---------- Auth ----------
@app.get("/ui/login", response_class=HTMLResponse)
def login_form():
    return render("login.html")

@app.post("/ui/login")
def do_login(email: str = Form(...), password: str = Form(...)):
    with engine.begin() as conn:
        row = conn.execute(text("SELECT password_hash FROM users WHERE email=:e"), {"e": email}).fetchone()
    if not row or not bcrypt.verify(password, row.password_hash):
        return render("login.html", error="Invalid credentials")
    token = sign_session(email)
    resp = RedirectResponse("/ui/announcements", status_code=302)
    resp.set_cookie("session", token, httponly=True, samesite="lax")
    return resp

@app.get("/ui/logout")
def logout():
    resp = RedirectResponse("/ui/login", status_code=302)
    resp.delete_cookie("session")
    return resp

# ---------- Team (Announcements) ----------
@app.get("/ui/announcements", response_class=HTMLResponse)
def ui_ann(req: Request):
    uid, email, role = require_user(req)
    with engine.begin() as conn:
        anns = conn.execute(text("""
            SELECT a.content,
                   COALESCE(u.email,'system') AS author,
                   TO_CHAR(a.created_at, 'YYYY-MM-DD HH24:MI') as dt
            FROM announcements a
            LEFT JOIN users u ON a.author_id=u.id
            ORDER BY a.id DESC LIMIT 100
        """)).fetchall()
    anns_fmt = [(r.content, r.author, r.dt) for r in anns]
    return render("announcements.html", email=email, anns=anns_fmt, role=role)

@app.post("/api/announcements")
def post_ann(req: Request, payload: dict):
    uid, email, role = require_user(req)
    content = (payload.get("content") or "").strip()
    if not content:
        raise HTTPException(400,"empty")
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO announcements(author_id,content) VALUES (:uid,:c)"),{"uid":uid,"c":content})
    audit(email, "announce", {"content": content[:160]})
    return {"ok": True}

# ---------- My Space ----------
@app.get("/ui/user", response_class=HTMLResponse)
def ui_user(req: Request):
    uid, email, role = require_user(req)
    with engine.begin() as conn:
        u = conn.execute(text("SELECT id,email,role FROM users WHERE id=:id"),{"id":uid}).fetchone()
        notes = conn.execute(text("""
            SELECT content, TO_CHAR(created_at,'YYYY-MM-DD HH24:MI')
            FROM notes WHERE user_id=:id ORDER BY id DESC LIMIT 50
        """),{"id":uid}).fetchall()
    return render("user.html", viewer=email, u=u, notes=notes)

@app.post("/api/notes")
def add_note(req: Request, payload: dict):
    uid, email, role = require_user(req)
    content = (payload.get("content") or "").strip()
    if not content:
        raise HTTPException(400,"empty")
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO notes(user_id,content) VALUES (:uid,:c)"),{"uid":uid,"c":content})
    audit(email, "note", {"content": content[:120]})
    return {"ok": True}

# ---------- Proxmox helpers ----------
def pve_headers():
    return {"Authorization": f"PVEAPIToken={PVE_TOKEN_ID}={PVE_TOKEN_SECRET}"}

async def pve_get(path: str):
    async with httpx.AsyncClient(verify=False, timeout=18) as c:
        r = await c.get(f"{PVE_HOST}/api2/json{path}", headers=pve_headers())
        r.raise_for_status()
        return r.json()["data"]

async def pve_post(path: str, data=None):
    async with httpx.AsyncClient(verify=False, timeout=30) as c:
        r = await c.post(f"{PVE_HOST}/api2/json{path}", headers=pve_headers(), data=data or {})
        r.raise_for_status()
        return r.json().get("data")

async def pve_put(path: str, data=None):
    async with httpx.AsyncClient(verify=False, timeout=30) as c:
        r = await c.put(f"{PVE_HOST}/api2/json{path}", headers=pve_headers(), data=data or {})
        r.raise_for_status()
        return r.json().get("data")

async def pve_delete(path: str):
    async with httpx.AsyncClient(verify=False, timeout=30) as c:
        r = await c.delete(f"{PVE_HOST}/api2/json{path}", headers=pve_headers())
        r.raise_for_status()
        return r.json().get("data")

def filter_vms_for_user(vms: List[dict], uid: int, role: str):
    with engine.begin() as conn:
        perm_count = conn.execute(text("SELECT COUNT(1) FROM vm_permissions")).scalar()
        if role == "leader" or perm_count == 0:
            return vms, { (v['node'], int(v['vmid'])): {"can_power": True, "can_snapshot": (role=='leader')} for v in vms }
        rows = conn.execute(text("""
            SELECT node, vmid, can_power, can_snapshot
            FROM vm_permissions WHERE user_id=:uid
        """), {"uid": uid}).fetchall()
    allowed = { (r.node, int(r.vmid)): {"can_power": r.can_power, "can_snapshot": r.can_snapshot} for r in rows }
    vms_f = []
    for v in vms:
        key = (v["node"], int(v["vmid"]))
        if key in allowed:
            vms_f.append(v)
    return vms_f, allowed

# ---------- Services list ----------
@app.get("/ui/services", response_class=HTMLResponse)
async def ui_services(req: Request):
    uid, email, role = require_user(req)
    vms = []
    try:
        nodes = await pve_get("/nodes")
        for n in nodes:
            for v in await pve_get(f"/nodes/{n['node']}/qemu"):
                vms.append({"type":"qemu","node":n["node"], **v})
            for v in await pve_get(f"/nodes/{n['node']}/lxc"):
                vms.append({"type":"lxc","node":n["node"], **v})
    except Exception as e:
        print("[PVE] list error:", e, file=sys.stderr)
    vms, perms = filter_vms_for_user(vms, uid, role)
    cust_map = {}
    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT vm.node, vm.vmid, c.name
            FROM vm_customers vm JOIN customers c ON vm.customer_id=c.id
        """)).fetchall()
    for r in rows:
        cust_map[(r.node, int(r.vmid))] = r.name
    return render("services.html", vms=vms, perms=perms, host=PVE_HOST, role=role, email=email, cust_map=cust_map)

@app.get("/ui/proxmox-summary", response_class=HTMLResponse)
async def ui_pve_summary(req: Request):
    uid, email, role = require_user(req)
    nodes = []; guests = []
    try:
        nodes = await pve_get("/nodes")
        for n in nodes:
            gs = await pve_get(f"/nodes/{n['node']}/qemu")
            cs = await pve_get(f"/nodes/{n['node']}/lxc")
            for g in gs + cs:
                g["node"] = n["node"]
                guests.append(g)
    except Exception as e:
        print("[PVE] summary error:", e, file=sys.stderr)
    return render("pve_summary.html", nodes=nodes, guests=guests, host=PVE_HOST)

@app.get("/ui/proxmox-vms", response_class=HTMLResponse)
async def legacy_vms(req: Request): return await ui_services(req)

# ---------- Live selectors ----------
@app.get("/api/pve/nodes")
async def api_nodes(req: Request):
    _ = require_user(req); return await pve_get("/nodes")

@app.get("/api/pve/{node}/bridges")
async def api_bridges(req: Request, node: str):
    _ = require_user(req)
    nets = await pve_get(f"/nodes/{node}/network")
    return [n for n in nets if n.get("type")=="bridge" and n.get("active")==1]

@app.get("/api/pve/{node}/storages")
async def api_storages(req: Request, node: str):
    _ = require_user(req); return await pve_get(f"/nodes/{node}/storage")

@app.get("/api/pve/{node}/storage/{store}/content")
async def api_storage_content(req: Request, node: str, store: str, content: str = Query("iso")):
    _ = require_user(req)
    items = await pve_get(f"/nodes/{node}/storage/{store}/content")
    return [i for i in items if i.get("content")==content]

@app.get("/api/pve/nextid")
async def api_nextid(req: Request):
    _ = require_user(req); return {"vmid": await pve_get("/cluster/nextid")}

# ---------- QEMU: Create / View / Edit / Clone / Snapshots ----------
@app.get("/ui/vm/{node}/{vmid}", response_class=HTMLResponse)
async def ui_vm_detail(req: Request, node: str, vmid: int):
    _uid, email, role = require_user(req)
    try:
        cfg = await pve_get(f"/nodes/{node}/qemu/{vmid}/config")
        status = await pve_get(f"/nodes/{node}/qemu/{vmid}/status/current")
        snaps = await pve_get(f"/nodes/{node}/qemu/{vmid}/snapshot")
    except Exception as e:
        return HTMLResponse(f"<pre>VM not found or no permission\n{e}</pre>", status_code=404)
    return render("vm_detail.html", node=node, vmid=vmid, cfg=cfg, status=status, snaps=snaps, host=PVE_HOST, role=role)

@app.get("/ui/vm/{node}/{vmid}/edit", response_class=HTMLResponse)
async def ui_vm_edit(req: Request, node: str, vmid: int):
    _uid, email, role = require_user(req)
    cfg = await pve_get(f"/nodes/{node}/qemu/{vmid}/config")
    return render("vm_edit.html", node=node, vmid=vmid, cfg=cfg)

@app.post("/api/pve/qemu/{node}/{vmid}/config")
async def api_vm_config(req: Request, node: str, vmid: int, payload: dict):
    uid, email, role = require_user(req)
    name = payload.get("name")
    memory = int(payload.get("memory") or 0)
    cores = int(payload.get("cores") or 0)
    data = {}
    if name: data["name"] = name
    if memory: data["memory"] = memory
    if cores: data["cores"] = cores
    if payload.get("description") is not None:
        data["description"] = payload["description"]
    if not data: raise HTTPException(400, "no changes")
    await pve_post(f"/nodes/{node}/qemu/{vmid}/config", data)
    audit(email, "pve:config", {"node":node,"vmid":vmid,"changes":data})
    return {"ok": True}

@app.post("/api/pve/qemu/create")
async def api_vm_create(req: Request, payload: dict):
    uid, email, role = require_user(req)
    if role != "leader": raise HTTPException(403, "leader only")
    node = payload["node"]; name = payload["name"]
    vmid = int(payload.get("vmid") or (await pve_get("/cluster/nextid")))
    memory = int(payload.get("memory") or 2048); cores = int(payload.get("cores") or 2)
    storage = payload.get("storage","local-lvm"); disk_gb = int(payload.get("disk_gb") or 20)
    bridge = payload.get("bridge","vmbr0"); iso = payload.get("iso","")
    cloudinit = bool(payload.get("cloudinit", False))
    ciuser = payload.get("ciuser","ubuntu"); cipass = payload.get("cipassword","")
    sshkeys = payload.get("sshkeys",""); ipconfig0 = payload.get("ipconfig0","")
    net0 = f"virtio,bridge={bridge}"
    scsi0 = f"{storage}:{disk_gb}"
    post_data = {"vmid": vmid, "name": name, "memory": memory, "cores": cores,
                 "net0": net0, "scsi0": scsi0, "ostype":"l26","scsihw":"virtio-scsi-pci","agent":1}
    if iso:
        post_data["ide2"] = iso + ",media=cdrom"; post_data["boot"] = "order=ide2;scsi0;net0"
    if cloudinit:
        post_data["ide2"] = "local:cloudinit"
        if ciuser: post_data["ciuser"] = ciuser
        if cipass: post_data["cipassword"] = cipass
        if sshkeys: post_data["sshkeys"] = sshkeys
        if ipconfig0: post_data["ipconfig0"] = ipconfig0
        post_data["boot"] = "order=scsi0;ide2;net0"
    await pve_post(f"/nodes/{node}/qemu", post_data)
    audit(email, "pve:create", {"node":node,"vmid":vmid,"name":name})
    return {"ok": True, "vmid": vmid}

@app.post("/api/pve/qemu/{node}/{vmid}/clone")
async def api_vm_clone(req: Request, node: str, vmid: int, payload: dict):
    uid, email, role = require_user(req)
    if role != "leader": raise HTTPException(403, "leader only")
    newid = int(payload.get("newid") or (await pve_get("/cluster/nextid")))
    name = payload.get("name") or f"clone-{vmid}-{newid}"
    target = payload.get("target", node)
    storage = payload.get("storage", "local-lvm")
    full = int(bool(payload.get("full", True)))
    data = {"newid": newid, "name": name, "target": target, "storage": storage, "full": full}
    await pve_post(f"/nodes/{node}/qemu/{vmid}/clone", data)
    audit(email, "pve:clone", {"node":node,"vmid":vmid,"newid":newid,"name":name})
    return {"ok": True, "vmid": newid}

@app.get("/api/pve/qemu/{node}/{vmid}/snapshots")
async def api_vm_snaps(req: Request, node: str, vmid: int):
    _ = require_user(req); return await pve_get(f"/nodes/{node}/qemu/{vmid}/snapshot")

@app.post("/api/pve/qemu/{node}/{vmid}/snapshot")
async def api_vm_snapshot(req: Request, node: str, vmid: int, payload: dict):
    uid, email, role = require_user(req)
    name = payload.get("name") or f"dash_{int(time.time())}"
    await pve_post(f"/nodes/{node}/qemu/{vmid}/snapshot", {"snapname": name})
    audit(email, "pve:snapshot", {"node":node,"vmid":vmid,"name":name})
    return {"ok": True}

@app.post("/api/pve/qemu/{node}/{vmid}/snapshot/{name}/rollback")
async def api_vm_snap_rollback(req: Request, node: str, vmid: int, name: str):
    uid, email, role = require_user(req)
    await pve_post(f"/nodes/{node}/qemu/{vmid}/snapshot/{name}/rollback")
    audit(email, "pve:rollback", {"node":node,"vmid":vmid,"name":name})
    return {"ok": True}

@app.delete("/api/pve/qemu/{node}/{vmid}/snapshot/{name}")
async def api_vm_snap_delete(req: Request, node: str, vmid: int, name: str):
    uid, email, role = require_user(req)
    await pve_delete(f"/nodes/{node}/qemu/{vmid}/snapshot/{name}")
    audit(email, "pve:snap_delete", {"node":node,"vmid":vmid,"name":name})
    return {"ok": True}

# ---------- LXC Create ----------
@app.post("/api/pve/lxc/create")
async def api_lxc_create(req: Request, payload: dict):
    uid, email, role = require_user(req)
    if role != "leader": raise HTTPException(403, "leader only")
    node = payload["node"]; hostname = payload["hostname"]
    vmid = int(payload.get("vmid") or (await pve_get("/cluster/nextid")))
    password = payload.get("password",""); storage = payload.get("storage","local-lvm")
    rootfs = f"{storage}:{int(payload.get('disk_gb',8))}"
    template = payload.get("template")
    bridge = payload.get("bridge","vmbr0"); ip = payload.get("ip","dhcp")
    data = {"vmid": vmid, "hostname": hostname, "password": password, "rootfs": rootfs,
            "ostemplate": template, "net0": f"name=eth0,bridge={bridge},ip={ip}", "memory": int(payload.get("memory",1024))}
    await pve_post(f"/nodes/{node}/lxc", data)
    audit(email, "pve:lxc_create", {"node":node,"vmid":vmid,"hostname":hostname})
    return {"ok": True, "vmid": vmid}

# ---------- Power ----------
@app.post("/api/pve/{kind}/{node}/{vmid}/{action}")
async def pve_action(req: Request, kind: str, node: str, vmid: int, action: str):
    uid, email, role = require_user(req)
    allowed_actions = {"start","stop","shutdown","reset","reboot","resume","suspend","snapshot"}
    if action not in allowed_actions: raise HTTPException(400,"bad action")
    can_power = True; can_snap = (role == "leader")
    with engine.begin() as conn:
        perm_count = conn.execute(text("SELECT COUNT(1) FROM vm_permissions")).scalar()
        if role != "leader" and perm_count > 0:
            row = conn.execute(text("""
                SELECT can_power, can_snapshot FROM vm_permissions
                WHERE user_id=:uid AND node=:node AND vmid=:vmid
            """), {"uid": uid, "node": node, "vmid": vmid}).fetchone()
            if not row: raise HTTPException(403, "no permission")
            can_power, can_snap = row.can_power, row.can_snapshot
    path_base = f"/nodes/{node}/{ 'qemu' if kind=='qemu' else 'lxc' }/{vmid}"
    if action=="snapshot":
        if not can_snap: raise HTTPException(403, "no snapshot permission")
        snapname = f"dash_{int(time.time())}"
        await pve_post(f"{path_base}/snapshot", {"snapname": snapname})
    else:
        if not can_power: raise HTTPException(403, "no power permission")
        await pve_post(f"{path_base}/status/{action}")
    audit(email, f"pve:{action}", {"kind":kind,"node":node,"vmid":vmid})
    return {"ok": True}

# ---------- Cloud-init Profiles ----------
@app.get("/ui/profiles", response_class=HTMLResponse)
def ui_profiles(req: Request):
    uid, email, role = require_user(req)
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id,name,ciuser,cipassword,sshkeys,ipconfig0 FROM ci_profiles ORDER BY id DESC")).fetchall()
    return render("profiles.html", rows=rows, role=role)

@app.post("/api/profiles")
def create_profile(req: Request, payload: dict):
    uid, email, role = require_user(req)
    if role != "leader": raise HTTPException(403,"leader only")
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO ci_profiles(name,ciuser,cipassword,sshkeys,ipconfig0)
            VALUES (:n,:u,:p,:k,:i)
        """), {"n":payload["name"], "u":payload.get("ciuser","ubuntu"),
               "p":payload.get("cipassword",""), "k":payload.get("sshkeys",""),
               "i":payload.get("ipconfig0","")})
    audit(email, "ci_profile:create", {"name":payload["name"]})
    return {"ok": True}

@app.delete("/api/profiles/{pid}")
def delete_profile(req: Request, pid: int):
    uid, email, role = require_user(req)
    if role != "leader": raise HTTPException(403,"leader only")
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM ci_profiles WHERE id=:id"), {"id": pid})
    audit(email, "ci_profile:delete", {"id":pid})
    return {"ok": True}

# ---------- Customers & VM mapping ----------
@app.get("/ui/customers", response_class=HTMLResponse)
def ui_customers(req: Request):
    uid, email, role = require_user(req)
    with engine.begin() as conn:
        cs = conn.execute(text("SELECT id,name,contact,notes FROM customers ORDER BY name")).fetchall()
        maps = conn.execute(text("""
            SELECT vm.node, vm.vmid, c.name
            FROM vm_customers vm JOIN customers c ON vm.customer_id=c.id
        """)).fetchall()
    return render("customers.html", customers=cs, maps=maps)

@app.post("/api/customers")
def create_customer(req: Request, payload: dict):
    uid, email, role = require_user(req)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO customers(name,contact,notes) VALUES (:n,:c,:o)"),
                     {"n":payload["name"], "c":payload.get("contact",""), "o":payload.get("notes","")})
    audit(email, "customer:create", {"name":payload["name"]})
    return {"ok": True}

@app.post("/api/customers/map")
def map_vm(req: Request, payload: dict):
    uid, email, role = require_user(req)
    node = payload["node"]; vmid = int(payload["vmid"])
    cust = payload["customer"]
    with engine.begin() as conn:
        c = conn.execute(text("SELECT id FROM customers WHERE name=:n"), {"n": cust}).fetchone()
        if not c: raise HTTPException(404, "customer not found")
        conn.execute(text("""
            INSERT INTO vm_customers(node,vmid,customer_id)
            VALUES (:node,:vmid,:cid)
            ON CONFLICT(node,vmid) DO UPDATE SET customer_id=excluded.customer_id
        """), {"node":node, "vmid":vmid, "cid":c.id})
    audit(email, "customer:map_vm", {"node":node,"vmid":vmid,"customer":cust})
    return {"ok": True}

# ---------- Uptime Kuma add monitor ----------
@app.post("/api/kuma/monitor")
def kuma_monitor(req: Request, payload: dict):
    uid, email, role = require_user(req)
    if not KUMA_TOKEN: raise HTTPException(400,"KUMA_TOKEN not set")
    url = payload["url"]; name = payload.get("name", url)
    headers = {"Authorization": f"Bearer {KUMA_TOKEN}", "Content-Type":"application/json"}
    r = httpx.post(f"{KUMA_URL}/api/monitor", headers=headers, json={"type":"http","name":name,"url":url,"interval":60})
    if r.status_code not in (200,201): raise HTTPException(400, f"kuma err {r.status_code}: {r.text}")
    audit(email, "kuma:add_monitor", {"url":url,"name":name})
    return {"ok": True}

# ---------- Admin / Audit ----------
@app.get("/ui/admin", response_class=HTMLResponse)
def ui_admin(req: Request):
    uid, email, role = require_user(req)
    return render("admin.html", email=email, role=role)

@app.get("/ui/audit", response_class=HTMLResponse)
def ui_audit(req: Request):
    uid, email, role = require_user(req)
    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT actor_email, action, meta, TO_CHAR(created_at,'YYYY-MM-DD HH24:MI') AS dt
            FROM audit ORDER BY id DESC LIMIT 200
        """)).fetchall()
    return render("audit.html", rows=rows, role=role)

@app.get("/health")
def health(): return {"ok": True}
