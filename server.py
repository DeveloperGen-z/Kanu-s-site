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

        # Upload endpoint is public but requires a registration id created immediately before it.
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
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
