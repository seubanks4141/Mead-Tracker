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
| `MEAD_TRACKER_PUBLIC_BASE_URL` | local URL | Stable, phone-reachable origin placed in QR links |
| `MEAD_TRACKER_TIME_ZONE` | `America/Chicago` | Display timezone for recorded events |
| `MEAD_TRACKER_TRUST_PROXY_HEADERS` | `false` | Trust HTTPS/host headers from a controlled reverse proxy |
| `MEAD_TRACKER_TRUSTED_PROXY` | `127.0.0.1` | Exact proxy address accepted by Waitress |
| `MEAD_TRACKER_SECURE_COOKIES` | `false` | Set `true` when browsers always connect over HTTPS |

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

Create a transactionally consistent backup while the application is running:

```powershell
python manage.py backup_mead_tracker
```

Before manually moving the live database file, stop the application and make a
copy. Copying an actively written SQLite file is not a reliable backup.

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
private Django secret, installs the systemd application and backup units, and
starts the service. For a non-interactive LAN installation:

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
  deploy/mead-tracker-backup.service \
  deploy/mead-tracker-backup.timer \
  /etc/systemd/system/

# StateDirectory creates /var/lib/mead-tracker. ExecStartPre applies database
# migrations and gathers static files before each start.
sudo systemctl daemon-reload
sudo systemctl enable --now mead-tracker
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
sudo journalctl -u mead-tracker -f
```

The included timer creates one verified SQLite snapshot per day and retains
the newest 30 snapshots. Check it with
`systemctl list-timers mead-tracker-backup.timer`.

When deploying an update, stop the service, back up the database, update the
code and dependencies, then restart the service. Its pre-start commands apply
migrations and `collectstatic` before accepting traffic.

## Data and backup notes

The SQLite database is the application's primary data. In Linux production,
keep it under `/var/lib/mead-tracker` rather than inside the code checkout.
Back up that directory to another disk or machine and periodically test a
restore. Generated labels can be recreated; the database and secret
configuration cannot.

For an on-demand verified snapshot on Linux:

```bash
sudo -u meadtracker sh -c \
  'set -a; . /etc/mead-tracker/mead-tracker.env; set +a; cd /opt/mead-tracker && exec .venv/bin/python manage.py backup_mead_tracker'
```

### Restore a Linux snapshot

Restoring replaces every batch, account, session, and setting in the database.
Keep the application stopped throughout the file swap so a stale WAL file
cannot be replayed against the restored database.

```bash
# First verify that the selected snapshot reports "ok".
/opt/mead-tracker/.venv/bin/python -c \
  'import sqlite3,sys; db=sqlite3.connect(sys.argv[1]); print(db.execute("PRAGMA integrity_check").fetchone()[0])' \
  /path/to/mead-tracker-backup.sqlite3

# Stop the timer first, then any snapshot already in progress, then the app.
sudo systemctl stop mead-tracker-backup.timer
sudo systemctl stop mead-tracker-backup.service
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
sudo systemctl start mead-tracker
sudo systemctl start mead-tracker-backup.timer
curl --fail http://127.0.0.1:8765/health/
```

Use the configured port in the health check. The restored database also
restores old login sessions; rotate `MEAD_TRACKER_SECRET_KEY` before restarting
if every device should be required to sign in again.

## Planned batch assistant

The batch page includes a disabled placeholder for the future conversational
assistant; this first release does not send brewing records to any AI service.
The planned update keeps that integration isolated from the core tracker:

- conversations and messages belong to one batch and one signed-in owner;
- the server builds an allowlisted context from batch details, active
  additions, gravity readings, status history, and journal observations;
- the OpenAI API key stays in server-side environment configuration and is
  never sent to the browser or stored in a batch;
- records are shared only after the owner submits a message, with clear
  retention, deletion, rate-limit, and cost controls;
- assistant suggestions are stored separately from production records and
  never change a batch unless the owner explicitly confirms an action.

That design lets the existing database and UI remain usable even when the
assistant is disabled, unavailable, or not configured.
