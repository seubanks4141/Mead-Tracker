# Mead Tracker

Mead Tracker is a responsive Django application for recording batches,
ingredient additions, gravity readings, and observations. It is designed to
run unchanged on a Windows test computer or a Linux VM, using a portable SQLite
database file.

## Requirements

- Python 3.10 or newer (this Windows workspace was verified with Python 3.14)
- A modern web browser
- On Linux, a dedicated service account is recommended

## Windows quick start

Open PowerShell in the project directory:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py collectstatic --noinput
python run_server.py
```

Open <http://localhost:8000>. The server binds only to this computer by
default.

The port can be changed for one launch:

```powershell
python run_server.py --port 8765
```

Or with environment variables:

```powershell
$env:MEAD_TRACKER_HOST = "0.0.0.0"
$env:MEAD_TRACKER_PORT = "8765"
python run_server.py
```

Command-line `--host` and `--port` values override the corresponding
environment variables. A project-local `.env` is loaded automatically, but
never overrides values already supplied by PowerShell or the operating system.

To test from a phone on the same trusted network:

1. Set `MEAD_TRACKER_HOST=0.0.0.0`.
2. Add the Windows computer's LAN name or address to
   `MEAD_TRACKER_ALLOWED_HOSTS`.
3. Set `MEAD_TRACKER_PUBLIC_BASE_URL` to the stable address the phone can
   reach, including the selected port.
4. Permit that TCP port through Windows Firewall for the private network only.
5. Visit the public base URL from the phone before printing any QR labels.

Do not expose the development setup directly to the public internet.

## Runtime configuration

| Setting | Default | Purpose |
| --- | --- | --- |
| `MEAD_TRACKER_HOST` | `127.0.0.1` | Network interface on which Waitress listens |
| `MEAD_TRACKER_PORT` | `8000` | TCP port, from 1 through 65535 |
| `MEAD_TRACKER_DEBUG` | `true` locally | Enables Django debug behavior; use `false` in production |
| `MEAD_TRACKER_SECRET_KEY` | none for production | Long, private Django signing key |
| `MEAD_TRACKER_ALLOWED_HOSTS` | local hosts | Comma-separated hostnames accepted by Django |
| `MEAD_TRACKER_CSRF_TRUSTED_ORIGINS` | empty | Comma-separated HTTPS origins when behind a proxy |
| `MEAD_TRACKER_ALLOW_SIGNUPS` | follows debug mode | Show self-registration and accept new regular accounts |
| `MEAD_TRACKER_DB_PATH` | project database | Absolute path to the SQLite database |
| `MEAD_TRACKER_BACKUP_DIR` | project backups | Directory for verified SQLite snapshots |
| `MEAD_TRACKER_MEDIA_ROOT` | project media directory | Directory for uploaded observation photos |
| `MEAD_TRACKER_PUBLIC_BASE_URL` | local URL | Stable, phone-reachable origin placed in QR links |
| `MEAD_TRACKER_TIME_ZONE` | `America/Chicago` | Display timezone for recorded events |
| `MEAD_TRACKER_TRUST_PROXY_HEADERS` | `false` | Trust HTTPS/host headers from a controlled reverse proxy |
| `MEAD_TRACKER_TRUSTED_PROXY` | `127.0.0.1` | Exact proxy address accepted by Waitress |
| `MEAD_TRACKER_SECURE_COOKIES` | `false` | Set `true` when browsers always connect over HTTPS |
| `MEAD_TRACKER_CHATGPT_ENABLED` | `false` | Enable OAuth/MCP routes; the batch-page card also requires the assigned callback |
| `MEAD_TRACKER_MCP_HOST` | `127.0.0.1` | Loopback interface for the separate MCP process; do not expose it directly |
| `MEAD_TRACKER_MCP_PORT` | `8766` | Loopback port for the separate MCP process |
| `MEAD_TRACKER_MCP_PUBLIC_URL` | `<public base URL>/mcp` | Exact public HTTPS MCP resource and OAuth audience |
| `MEAD_TRACKER_OAUTH_ISSUER_URL` | `<public base URL>/o` | Exact public HTTPS OAuth issuer |
| `MEAD_TRACKER_CHATGPT_CLIENT_ID` | `mead-tracker-chatgpt` | Predefined public OAuth client ID entered in ChatGPT |
| `MEAD_TRACKER_CHATGPT_CALLBACK_URL` | empty | Exact callback URL assigned by ChatGPT, with no trailing slash |

The bind host and public URL solve different problems. `0.0.0.0` makes the
server listen on every interface, but it is not a usable browser or QR address.
The public base URL must be a real hostname or IP address reachable by the
phone.

Generate a production secret without putting it in shell history:

```powershell
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Store the result inside the existing single quotes in `.env` on Windows or the
protected systemd environment file on Linux. Never commit it.

## Account management

When `MEAD_TRACKER_ALLOW_SIGNUPS=true`, the login page offers account
registration. Self-registered accounts are always ordinary users and cannot
grant themselves staff or superuser permissions.

Superusers have a **Users** area for creating accounts, reviewing each user's
active and total batch counts, and deactivating or reactivating access.
Deactivation is deliberately used instead of permanent deletion so production
records and audit history remain intact. It also revokes the user's current
login sessions, so reactivation requires a fresh sign-in. Use
`manage.py createsuperuser` when a new administrator account is required.

## Checks

Run the Django test suite:

```powershell
python manage.py test
```

The portable runtime validation can also be run on its own:

```powershell
python -m unittest tests.test_runtime_config
```

Create a transactionally consistent database backup while the application is
running:

```powershell
python manage.py backup_mead_tracker
```

The command snapshots SQLite only. Also copy `MEAD_TRACKER_MEDIA_ROOT` to
preserve uploaded observation photos. Before manually moving the live database
file, stop the application and make a copy. Copying an actively written SQLite
file is not a reliable backup.

## Linux VM deployment

The included deployment script installs the application at
`/opt/mead-tracker`, keeps configuration in `/etc/mead-tracker`, persists data
under `/var/lib/mead-tracker`, and runs it as an unprivileged account. It
supports apt- or dnf/yum-based systemd servers with Python 3.10 or newer.

### Automated initial setup

Copy `deploy/mead-tracker.sh` to the Linux server and run:

```bash
sudo sh mead-tracker.sh setup
```

Interactive setup asks for the server's LAN address and port, generates a
private Django secret, installs the web, opt-in MCP, and backup systemd units,
and starts the enabled services. For a non-interactive LAN installation:

```bash
sudo env \
  MEAD_TRACKER_SERVER_ADDRESS=10.0.10.25 \
  MEAD_TRACKER_PORT=8765 \
  MEAD_TRACKER_ALLOW_SIGNUPS=true \
  sh mead-tracker.sh setup
```

The script preserves any existing environment file and database. It installs
itself as `mead-tracker-deploy`, so future releases can be applied with:

```bash
sudo mead-tracker-deploy update
```

Updates require a clean, non-divergent `main` checkout. Before changing code
or dependencies, the script pauses the backup timer and creates a verified
SQLite backup. It then applies a fast-forward-only update and restores the
timer only after the updated application passes its health check.

The generated settings are suitable for direct HTTP access from a trusted
LAN. Before exposing the application to the internet, edit
`/etc/mead-tracker/mead-tracker.env` for an HTTPS reverse proxy as described
below.

### Manual setup

The equivalent manual setup is shown below. Adjust commands for the VM's
distribution and deployment process.

```bash
sudo groupadd --system meadtracker
sudo useradd --system --gid meadtracker --home /opt/mead-tracker --shell /usr/sbin/nologin meadtracker
sudo git clone https://github.com/seubanks4141/Mead-Tracker.git /opt/mead-tracker

# Keep code and the virtual environment root-owned. Only runtime directories
# are writable by the web-service account.
cd /opt/mead-tracker
sudo python3 -m venv .venv
sudo .venv/bin/python -m pip install --upgrade pip
sudo .venv/bin/python -m pip install -r requirements.txt
sudo install -d -o meadtracker -g meadtracker -m 0750 staticfiles media

sudo install -d -o root -g meadtracker -m 0750 /etc/mead-tracker
sudo install -o root -g meadtracker -m 0640 \
  deploy/mead-tracker.env.example \
  /etc/mead-tracker/mead-tracker.env
sudoedit /etc/mead-tracker/mead-tracker.env

sudo install -o root -g root -m 0644 \
  deploy/mead-tracker.service \
  /etc/systemd/system/mead-tracker.service
sudo install -o root -g root -m 0644 \
  deploy/mead-tracker-mcp.service \
  /etc/systemd/system/mead-tracker-mcp.service
sudo install -o root -g root -m 0644 \
  deploy/mead-tracker-backup.service \
  deploy/mead-tracker-backup.timer \
  /etc/systemd/system/

# StateDirectory creates /var/lib/mead-tracker. ExecStartPre applies database
# migrations and gathers static files before each start.
sudo systemctl daemon-reload
sudo systemctl enable --now mead-tracker
# Enable this unit only after completing the ChatGPT activation runbook below.
# sudo systemctl enable --now mead-tracker-mcp
sudo systemctl enable --now mead-tracker-backup.timer
sudo systemctl status mead-tracker
```

On the first deployment, create the owner account:

```bash
sudo -u meadtracker sh -c \
  'set -a; . /etc/mead-tracker/mead-tracker.env; set +a; cd /opt/mead-tracker && exec .venv/bin/python manage.py createsuperuser'
```

For direct LAN-only use, set the host to `0.0.0.0`, choose an unused port, and
restrict that port with the VM firewall. If that LAN connection uses plain
HTTP, set `MEAD_TRACKER_SECURE_COOKIES=false`. For internet access, keep the
service on `127.0.0.1` and put an HTTPS reverse proxy such as Caddy or nginx in
front of it. The proxy's hostname must match `MEAD_TRACKER_ALLOWED_HOSTS` and
`MEAD_TRACKER_PUBLIC_BASE_URL`. Set `MEAD_TRACKER_TRUST_PROXY_HEADERS=true`
only when that proxy overwrites client-supplied forwarded headers. For an
internet-reachable installation, also rate-limit `/accounts/login/` at the
reverse proxy. If self-registration is enabled, rate-limit `/accounts/signup/`
as well.

To inspect service logs:

```bash
sudo journalctl -u mead-tracker -u mead-tracker-mcp -f
```

The included timer creates one verified SQLite snapshot per day and retains
the newest 30 snapshots. Check it with
`systemctl list-timers mead-tracker-backup.timer`.

When deploying an update manually, stop `mead-tracker-mcp` before
`mead-tracker`, back up the database, update the code and dependencies, then
start the web service followed by MCP. The web service's pre-start commands
apply migrations and `collectstatic` before either service accepts production
traffic. The automated deployment script performs this ordering and keeps MCP
stopped and disabled when `MEAD_TRACKER_CHATGPT_ENABLED=false`.

## Data and backup notes

The SQLite database and uploaded-photo media directory are the application's
primary data. In Linux production, keep both under `/var/lib/mead-tracker`
rather than inside the code checkout. The included backup command and timer
snapshot SQLite only, so back up the full state directory to another disk or
machine to preserve photos, and periodically test a restore. Generated labels
can be recreated; the database, uploaded photos, and secret configuration
cannot.

For an on-demand verified snapshot on Linux:

```bash
sudo -u meadtracker sh -c \
  'set -a; . /etc/mead-tracker/mead-tracker.env; set +a; cd /opt/mead-tracker && exec .venv/bin/python manage.py backup_mead_tracker'
```

### Restore a Linux snapshot

Restoring replaces every batch, account, session, OAuth client, grant, access
token, and refresh token in the database. Keep the application stopped
throughout the file swap so a stale WAL file cannot be replayed against the
restored database.

```bash
# First verify that the selected snapshot reports "ok".
/opt/mead-tracker/.venv/bin/python -c \
  'import sqlite3,sys; db=sqlite3.connect(sys.argv[1]); print(db.execute("PRAGMA integrity_check").fetchone()[0])' \
  /path/to/mead-tracker-backup.sqlite3

# Stop the timer first, then any snapshot already in progress, then both app
# processes. Stopping MCP first prevents reads during the database file swap.
sudo systemctl stop mead-tracker-backup.timer
sudo systemctl stop mead-tracker-backup.service
sudo systemctl stop mead-tracker-mcp 2>/dev/null || true
sudo systemctl stop mead-tracker
restore_stamp="$(date +%Y%m%d-%H%M%S)"

# Preserve the current database and any sidecars as a rollback set.
sudo mv /var/lib/mead-tracker/mead-tracker.sqlite3 \
  "/var/lib/mead-tracker/mead-tracker.sqlite3.before-$restore_stamp"
if [ -e /var/lib/mead-tracker/mead-tracker.sqlite3-wal ]; then
  sudo mv /var/lib/mead-tracker/mead-tracker.sqlite3-wal \
    "/var/lib/mead-tracker/mead-tracker.sqlite3-wal.before-$restore_stamp"
fi
if [ -e /var/lib/mead-tracker/mead-tracker.sqlite3-shm ]; then
  sudo mv /var/lib/mead-tracker/mead-tracker.sqlite3-shm \
    "/var/lib/mead-tracker/mead-tracker.sqlite3-shm.before-$restore_stamp"
fi

sudo install -o meadtracker -g meadtracker -m 0600 \
  /path/to/mead-tracker-backup.sqlite3 \
  /var/lib/mead-tracker/mead-tracker.sqlite3

# Bring an older snapshot up to the installed schema while services remain
# stopped.
sudo -u meadtracker sh -c \
  'set -a; . /etc/mead-tracker/mead-tracker.env; set +a; cd /opt/mead-tracker && exec .venv/bin/python manage.py migrate --noinput'

# Before starting either service, invalidate restored ChatGPT authorization.
# A configured callback keeps the client but revokes its old grants/tokens;
# an empty callback removes the client for safe discovery-only bootstrap.
sudo -u meadtracker sh -c '
  set -a
  . /etc/mead-tracker/mead-tracker.env
  set +a
  cd /opt/mead-tracker
  if [ -n "${MEAD_TRACKER_CHATGPT_CALLBACK_URL:-}" ]; then
    exec .venv/bin/python manage.py configure_chatgpt_oauth \
      --revoke-existing-authorizations
  fi
  exec .venv/bin/python manage.py configure_chatgpt_oauth --discovery-only
'

# If every browser should also sign in again, replace
# MEAD_TRACKER_SECRET_KEY in the protected environment file now, before the
# first service restart.
sudo systemctl start mead-tracker
if sudo sh -c \
  'set -a; . /etc/mead-tracker/mead-tracker.env; set +a; [ "${MEAD_TRACKER_CHATGPT_ENABLED:-false}" = true ]'
then
  sudo systemctl start mead-tracker-mcp
fi
sudo systemctl start mead-tracker-backup.timer
curl --fail http://127.0.0.1:8765/health/
```

Use the configured port in the health check. The restored database also
restores old login sessions; the optional key rotation above invalidates them.

## ChatGPT batch advisor

Each batch page can show an **Ask about this batch** card. It offers separate
**Copy batch prompt** and **Open ChatGPT** controls. The prompt contains only
the batch's stable ID; the user copies it, opens ChatGPT, pastes it, selects
Mead Tracker, and sends it.
Browsers do not allow Mead Tracker to paste or submit into another site's
window automatically. The card is completely hidden until
`MEAD_TRACKER_CHATGPT_ENABLED=true`, the real
`MEAD_TRACKER_CHATGPT_CALLBACK_URL` is present, and the Django web process has
restarted.

The conversation and model usage occur in the signed-in user's ChatGPT account
and follow that account's limits. Custom read-only MCP availability depends on
the current plan, workspace policy, and rollout; OpenAI's current connection
documentation explicitly covers read/fetch access for Pro. Mead Tracker does
not promise a particular "Max" allowance, call an OpenAI model API, require an
OpenAI API key, or store a second copy of the conversation.
When a tool is used, the allowlisted batch snapshot is transmitted to ChatGPT
to answer the question.

The connection exposes only the read-only `list_batches` and
`get_batch_context` tools. It authenticates the user's Mead Tracker account and
filters every query by that account's ownership. Server and skill instructions
tell ChatGPT to fetch a fresh snapshot before each substantive batch answer,
so newly added entries are available on the next tool call. This is
request-time refresh, not a live push; ChatGPT ultimately controls tool
selection, so a user can explicitly ask it to “refresh this batch” whenever
needed. Credentials, QR tokens, audit logs, deleted records, recorder
identities, observation photo files and paths, and other users' batches are
excluded. Every returned string remains untrusted data, not tool instructions.

OpenAI's current setup references are:

- [Connect and test your plugin](https://developers.openai.com/plugins/deploy/connect-chatgpt)
- [Authenticate plugin users](https://developers.openai.com/plugins/build/auth)
- [Developer mode and MCP availability](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt-beta)

### Production activation runbook

This integration uses two local processes behind one public HTTPS origin:

- Django/Waitress on its configured loopback web port, normally `8765`, serves
  Mead Tracker, OAuth under `/o/`, and discovery metadata.
- The separate MCP process on `127.0.0.1:8766` serves only the public `/mcp`
  resource through the reverse proxy.

A tunnel that publishes the MCP process alone is not sufficient for this
architecture. OAuth opens browser routes on the Mead Tracker web origin and
also depends on discovery metadata there. Use a public HTTPS web/OAuth origin,
or provide ingress for both the MCP route and all browser OAuth/discovery
routes. A Secure MCP Tunnel can still be useful only when those web/OAuth
routes are independently reachable.

#### 1. Install dependencies and migrate

OAuth adds database tables, so migrate the same database used by both
processes before configuring the client. On an existing production
installation, first follow the manual-update procedure above: stop MCP and the
web service and take a verified snapshot before changing dependencies or
running migrations.

```bash
cd /opt/mead-tracker
sudo .venv/bin/python -m pip install -r requirements.txt
sudo -u meadtracker sh -c \
  'set -a; . /etc/mead-tracker/mead-tracker.env; set +a; cd /opt/mead-tracker && exec .venv/bin/python manage.py migrate --noinput'
```

#### 2. Configure one canonical HTTPS origin

Edit `/etc/mead-tracker/mead-tracker.env`. Substitute the real hostname; do
not enable the feature with placeholder URLs:

```dotenv
MEAD_TRACKER_HOST=127.0.0.1
MEAD_TRACKER_PORT=8765
MEAD_TRACKER_PUBLIC_BASE_URL=https://mead.example.com
MEAD_TRACKER_ALLOWED_HOSTS=mead.example.com
MEAD_TRACKER_CSRF_TRUSTED_ORIGINS=https://mead.example.com
MEAD_TRACKER_SECURE_COOKIES=true
MEAD_TRACKER_TRUST_PROXY_HEADERS=true
MEAD_TRACKER_TRUSTED_PROXY=127.0.0.1

MEAD_TRACKER_CHATGPT_ENABLED=true
MEAD_TRACKER_MCP_HOST=127.0.0.1
MEAD_TRACKER_MCP_PORT=8766
MEAD_TRACKER_MCP_PUBLIC_URL=https://mead.example.com/mcp
MEAD_TRACKER_OAUTH_ISSUER_URL=https://mead.example.com/o
MEAD_TRACKER_CHATGPT_CLIENT_ID=mead-tracker-chatgpt
# Fill this in after ChatGPT displays the exact callback:
MEAD_TRACKER_CHATGPT_CALLBACK_URL=
```

Only trust proxy headers when the named loopback proxy overwrites
client-supplied `Forwarded`, `X-Forwarded-Host`, and `X-Forwarded-Proto`
values. Do not publish ports `8765` or `8766` directly. Enabling ChatGPT now
fails closed unless debug mode is off, cookies are Secure, the public base URL
uses HTTPS, and `ALLOWED_HOSTS` does not contain `*`.

#### 3. Route HTTPS paths to the correct process

Terminate TLS at the reverse proxy and preserve the original public host. Route
the paths as follows:

| Public path | Upstream |
| --- | --- |
| `/mcp` and `/mcp/*` | MCP at `http://127.0.0.1:8766` |
| `/o/*` | Django at `http://127.0.0.1:8765` |
| `/.well-known/oauth-authorization-server/o` | Django at `http://127.0.0.1:8765` |
| `/.well-known/oauth-protected-resource/mcp` | Django at `http://127.0.0.1:8765` |
| Every other path | Django at `http://127.0.0.1:8765` |

Both `/.well-known` URLs are rooted at the public origin. Do not place them
under `/o/`, and do not send their public requests to the MCP upstream.

#### 4. Install and start both systemd units

The automated deployment script installs both units and manages MCP according
to the enable flag. For a manual installation:

```bash
cd /opt/mead-tracker
sudo install -o root -g root -m 0644 \
  deploy/mead-tracker.service \
  /etc/systemd/system/mead-tracker.service
sudo install -o root -g root -m 0644 \
  deploy/mead-tracker-mcp.service \
  /etc/systemd/system/mead-tracker-mcp.service
sudo systemctl daemon-reload
sudo -u meadtracker sh -c \
  'set -a; . /etc/mead-tracker/mead-tracker.env; set +a; cd /opt/mead-tracker && exec .venv/bin/python manage.py configure_chatgpt_oauth --discovery-only'
sudo systemctl enable --now mead-tracker
sudo systemctl enable --now mead-tracker-mcp
sudo systemctl status mead-tracker mead-tracker-mcp
```

The first activation is staged because ChatGPT has not assigned its callback
yet. With the callback empty, MCP starts in discovery-only bootstrap mode:
the deployment command explicitly removes any stale predefined client and its
authorizations, ChatGPT can inspect the protected endpoint, and no batch tool
can return data. The batch-page card also stays hidden. After the callback is
stored and the OAuth client is configured below, future
`sudo mead-tracker-deploy update` runs migrations, validates the OAuth
configuration, and reconciles both services automatically.

#### 5. Create the private ChatGPT connection

1. In ChatGPT web, enable **Developer mode**. OpenAI's plugin-testing pages
   currently place the toggle under **Settings → Security and login**; the
   newer account/workspace help also documents **Settings → Apps → Advanced
   Settings** and **Workspace settings → Apps → Create**. Use the location
   visible for the account. Availability and controls differ by plan,
   workspace policy, role, and rollout.
2. Open the ChatGPT Plugins area, select the plus button, and begin creating a
   custom read-only MCP connection.
3. Enter the exact MCP URL, such as `https://mead.example.com/mcp`, choose OAuth
   authentication, and use the predefined public client ID
   `mead-tracker-chatgpt`, or the exact value configured in
   `MEAD_TRACKER_CHATGPT_CLIENT_ID`.
4. Copy the exact callback shown by ChatGPT. It must have the form
   `https://chatgpt.com/connector/oauth/{callback_id}` with no query, fragment,
   port, or trailing slash.
5. Store it as `MEAD_TRACKER_CHATGPT_CALLBACK_URL` in the protected environment
   file, then create or update the predefined OAuth client:

   ```bash
   sudo -u meadtracker sh -c \
     'set -a; . /etc/mead-tracker/mead-tracker.env; set +a; cd /opt/mead-tracker && exec .venv/bin/python manage.py configure_chatgpt_oauth'
   sudo systemctl restart mead-tracker mead-tracker-mcp
   ```

6. Return to ChatGPT, scan or refresh the MCP app, and finish creating it.
   Confirm it discovers only `list_batches` and `get_batch_context`, then
   authenticate. Sign in to the correct Mead Tracker account and approve the
   `batches:read` scope.
7. Start a new chat, add the Mead Tracker connection from the tools menu, and
   ask it to list batches or paste the starter prompt from a batch page.

After the connection is created, retain its ChatGPT browser URL. The technical
app ID in that URL begins with `plugin_asdk_app` and is required for package
wiring; the display name is not a substitute.

Dynamic client registration is intentionally disabled. The client ID and
ChatGPT callback must exactly match the predefined database record created by
`configure_chatgpt_oauth`. Changing a tracked security field on that same
client record, including its callback, automatically revokes the client's old
grants, access tokens, and refresh tokens. Changing to a different client ID
does not delete the old database row, but MCP immediately rejects tokens not
issued to the newly configured ID.

#### 6. Finalize the source plugin only after IDs exist

The package under `plugins/mead-tracker/` intentionally cannot add
`.app.json` or the manifest's `apps` reference before ChatGPT creates the
connection and assigns the real `plugin_asdk_app...` ID in its browser URL. After
that ID and the HTTPS URL both work:

1. add the real `.mcp.json`;
2. add the real `.app.json`;
3. reference both files from `.codex-plugin/plugin.json`; and
4. add the real MCP dependency to
   `skills/mead-batch-advisor/agents/openai.yaml`; then
5. add the completed package to a repo or personal plugin marketplace for
   installation and end-to-end testing.

Do not commit guessed IDs or describe the source package as connected before
those references all identify the same deployed MCP service. See
`plugins/mead-tracker/README.md` for the exact package wiring.
Until those deployment-specific files are added, the checked-in directory is
a valid skill-only package and cannot read Mead Tracker data by itself.

### Troubleshooting the connection

Check public routing first:

```bash
curl --fail https://mead.example.com/health/
curl -i https://mead.example.com/.well-known/oauth-authorization-server/o
curl -i https://mead.example.com/.well-known/oauth-protected-resource/mcp
curl -i https://mead.example.com/mcp
```

The two discovery requests should return JSON with HTTP 200. An unauthenticated
`/mcp` request should reach the MCP service and normally return an
authentication error, not a proxy 404 or 502.

Then check the loopback listener and service logs on the VM:

```bash
curl -i http://127.0.0.1:8766/.well-known/oauth-protected-resource/mcp
curl -i http://127.0.0.1:8766/mcp
sudo systemctl status mead-tracker mead-tracker-mcp
sudo journalctl \
  -u mead-tracker \
  -u mead-tracker-mcp \
  -n 200 \
  --no-pager
sudo -u meadtracker sh -c \
  'set -a; . /etc/mead-tracker/mead-tracker.env; set +a; cd /opt/mead-tracker && exec .venv/bin/python manage.py check'
```

- A missing batch-page card means the enable flag or assigned callback is
  absent, or the web process has not reloaded the updated environment.
- A public discovery 404 usually means the feature is disabled or the reverse
  proxy routed a root `/.well-known` path incorrectly.
- A public MCP 502 means the MCP unit is stopped, listening on a different
  loopback port, or blocked by proxy routing.
- An OAuth redirect mismatch means the ChatGPT callback differs by at least one
  character. Copy it again, update the environment file, rerun
  `configure_chatgpt_oauth`, and restart both web and MCP services.
- If tool discovery succeeds but sign-in does not, verify the predefined client
  ID, the HTTPS issuer and resource URLs, and the web-service logs during the
  authorization request.
