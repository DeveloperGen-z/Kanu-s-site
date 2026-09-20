# BERLIN X PANEL — GitHub + Render + Admin Edition

This repository is intentionally split for future maintenance. The existing BERLIN X PANEL dashboard is preserved as ordered assets, while the new admin/app-registration system is isolated from it.

## Pages
- `/` — existing BERLIN X PANEL
- `/submit.html` — user app registration + APK upload
- `/admin` — protected admin console
- `/health` — health endpoint

## Structure
```text
index.html
submit.html
admin.html
server.py
css/
js/
assets/
docs/
tools/
verify_deploy.py
render.yaml
.env.example
```

## Run locally
Python 3.11+:

```bash
python server.py
```

Set credentials first:

PowerShell:
```powershell
$env:ADMIN_USER="admin"
$env:ADMIN_PASSWORD="use-a-long-random-password"
python server.py
```

Linux/macOS:
```bash
export ADMIN_USER=admin
export ADMIN_PASSWORD='use-a-long-random-password'
python server.py
```

Open:
- `http://127.0.0.1:10000/`
- `http://127.0.0.1:10000/submit.html`
- `http://127.0.0.1:10000/admin`

## GitHub
Extract the ZIP and upload **all contents of this folder** to the repository root. Do not upload `.env`, `data/`, or generated APKs.

## Render
Create a Python Web Service from this GitHub repository.

Start command:
```text
python server.py
```

Set these environment variables in Render:
```text
ADMIN_USER=your-admin-name
ADMIN_PASSWORD=your-strong-password
MAX_APK_MB=150
DATA_DIR=/var/data
```

For durable APK/SQLite storage, attach a persistent disk mounted at `/var/data`. Without persistent storage, Render's normal filesystem is not a durable database/file store.

## Admin data boundary
The system stores only fields and APK files that a user explicitly submits. A Firebase project URL/config does not grant permission to read that project's private database, Auth users, tokens, service-account keys, or other private data.

## Verification
```bash
python verify_deploy.py
```

## UI/UX system
`assets/design-tokens.json`, `assets/design-tokens.css`, and `docs/design-system.md` document the three-layer token approach and UX checks derived from the uploaded UI/UX Pro Max skill. They are kept separate so the existing dashboard can be refactored incrementally without breaking its runtime.

## Production note
For a larger multi-instance deployment, use Postgres for metadata and object storage for APKs instead of local SQLite/filesystem.
