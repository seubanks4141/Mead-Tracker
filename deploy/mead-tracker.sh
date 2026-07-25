#!/bin/sh

# Install or safely update Mead Tracker on a systemd-based Linux server.
# Run as root:
#   sh mead-tracker.sh setup
#   mead-tracker-deploy update

set -eu
umask 022

APP_USER="meadtracker"
APP_GROUP="meadtracker"
APP_DIR="/opt/mead-tracker"
ENV_DIR="/etc/mead-tracker"
ENV_FILE="$ENV_DIR/mead-tracker.env"
STATE_DIR="/var/lib/mead-tracker"
INSTALL_MARKER="$ENV_DIR/.setup-complete"
SERVICE_NAME="mead-tracker.service"
BACKUP_SERVICE="mead-tracker-backup.service"
BACKUP_TIMER="mead-tracker-backup.timer"
INSTALLED_SCRIPT="/usr/local/sbin/mead-tracker-deploy"
LOCK_FILE="/run/mead-tracker-deploy.lock"

REPO_URL="${MEAD_TRACKER_REPO_URL:-https://github.com/seubanks4141/Mead-Tracker.git}"
BRANCH="${MEAD_TRACKER_BRANCH:-main}"
PYTHON_COMMAND="${MEAD_TRACKER_PYTHON:-python3}"
VENV_PYTHON="$APP_DIR/.venv/bin/python"

phase="starting"
temporary_env=""
temporary_script=""
timer_should_run=0
timer_should_enable=0
timer_stopped=0
app_stopped=0
backup_created=0

log() {
    printf '%s\n' "[mead-tracker] $*"
}

die() {
    printf '%s\n' "[mead-tracker] ERROR: $*" >&2
    exit 1
}

usage() {
    cat <<'EOF'
Usage:
  sudo sh mead-tracker.sh setup
  sudo mead-tracker-deploy update

Commands:
  setup   First installation. Clones the repository, creates a virtual
          environment and protected configuration, installs systemd units,
          and starts the application and daily backup timer.

  update  Fetches main, refuses dirty or divergent repositories, creates a
          verified database backup, applies only a fast-forward update,
          refreshes dependencies and systemd units, and checks application
          health before restoring the backup timer.

Optional setup environment variables:
  MEAD_TRACKER_SERVER_ADDRESS   LAN IPv4 address or hostname used by browsers
  MEAD_TRACKER_PORT             Listening port (default: 8765)
  MEAD_TRACKER_ALLOW_SIGNUPS    true or false (default: true)
  MEAD_TRACKER_TIME_ZONE        Django timezone (default: America/Chicago)
  MEAD_TRACKER_SKIP_PACKAGES    Set to 1 if prerequisites are already installed
  MEAD_TRACKER_PYTHON           Python 3.10+ command (default: python3)

Advanced overrides:
  MEAD_TRACKER_REPO_URL         Git repository URL
  MEAD_TRACKER_BRANCH           Deployment branch (default: main)

The setup command never overwrites an existing environment file or database.
The update command never stashes, resets, cleans, or force-checks out files.
EOF
}

cleanup() {
    cleanup_status=$?
    trap - 0 HUP INT TERM
    set +e

    if [ -n "$temporary_env" ] && [ -f "$temporary_env" ]; then
        rm -f "$temporary_env"
    fi
    if [ -n "$temporary_script" ] && [ -f "$temporary_script" ]; then
        rm -f "$temporary_script"
    fi

    if [ "$cleanup_status" -ne 0 ]; then
        printf '%s\n' \
            "[mead-tracker] FAILED during phase: $phase" >&2
        if [ "$app_stopped" -eq 1 ]; then
            systemctl stop "$SERVICE_NAME" >/dev/null 2>&1 || true
            printf '%s\n' \
                "[mead-tracker] The web service and backup timer remain stopped." \
                "[mead-tracker] Review: journalctl -u $SERVICE_NAME -n 100 --no-pager" >&2
            if [ "$backup_created" -eq 1 ]; then
                printf '%s\n' \
                    "[mead-tracker] A verified pre-update backup was kept." >&2
            else
                printf '%s\n' \
                    "[mead-tracker] Existing configuration and data were not removed." >&2
            fi
        elif [ "$timer_stopped" -eq 1 ] && [ "$timer_should_run" -eq 1 ]; then
            systemctl start "$BACKUP_TIMER" >/dev/null 2>&1 || true
        fi
    fi

    exit "$cleanup_status"
}

trap cleanup 0
trap 'exit 130' HUP INT TERM

require_root() {
    [ "$(id -u)" -eq 0 ] || die "Run this command with sudo or as root."
}

validate_fixed_paths() {
    for protected_path in \
        "$APP_DIR" \
        "$ENV_DIR" \
        "$ENV_FILE" \
        "$STATE_DIR" \
        "$INSTALL_MARKER" \
        "$STATE_DIR/backups" \
        "$LOCK_FILE"
    do
        [ ! -L "$protected_path" ] \
            || die "Refusing symbolic link at protected path: $protected_path"
    done
}

acquire_lock() {
    phase="acquiring deployment lock"
    command -v flock >/dev/null 2>&1 \
        || die "flock is required (normally provided by util-linux)."
    umask 077
    exec 9>"$LOCK_FILE"
    chmod 0600 "$LOCK_FILE"
    umask 022
    flock -n 9 \
        || die "Another setup or update is already running."
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

run_as_app() {
    runuser -u "$APP_USER" -g "$APP_GROUP" -- "$@"
}

run_with_env() {
    run_as_app sh -c '
        set -a
        . "$1"
        set +a
        cd "$2"
        shift 2
        exec "$@"
    ' sh "$ENV_FILE" "$APP_DIR" "$@"
}

install_packages() {
    phase="installing operating-system prerequisites"

    if [ "${MEAD_TRACKER_SKIP_PACKAGES:-0}" = "1" ]; then
        log "Skipping operating-system package installation."
        return
    fi

    if command -v apt-get >/dev/null 2>&1; then
        apt-get update
        DEBIAN_FRONTEND=noninteractive apt-get install -y \
            ca-certificates curl git python3 python3-venv util-linux
    elif command -v dnf >/dev/null 2>&1; then
        dnf install -y ca-certificates curl git python3 util-linux
    elif command -v yum >/dev/null 2>&1; then
        yum install -y ca-certificates curl git python3 util-linux
    else
        log "No supported package manager found; checking existing tools."
    fi
}

validate_prerequisites() {
    phase="checking prerequisites"
    prerequisite_mode="$1"
    require_command awk
    require_command curl
    require_command find
    require_command getent
    require_command git
    require_command grep
    require_command groupadd
    require_command install
    require_command journalctl
    require_command mktemp
    require_command runuser
    require_command stat
    require_command systemctl
    require_command tr
    require_command useradd
    require_command usermod

    if [ "$prerequisite_mode" = "setup" ]; then
        require_command "$PYTHON_COMMAND"
        version_python="$PYTHON_COMMAND"
    else
        [ -x "$VENV_PYTHON" ] \
            || die "Virtual environment not found: $VENV_PYTHON"
        version_python="$VENV_PYTHON"
    fi

    "$version_python" -c \
        'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' \
        || die "Python 3.10 or newer is required."
}

ensure_service_account() {
    phase="creating the service account"

    if ! getent group "$APP_GROUP" >/dev/null 2>&1; then
        groupadd --system "$APP_GROUP"
    fi

    if ! id "$APP_USER" >/dev/null 2>&1; then
        nologin_shell="$(command -v nologin 2>/dev/null || true)"
        [ -n "$nologin_shell" ] || nologin_shell="/usr/sbin/nologin"
        useradd \
            --system \
            --gid "$APP_GROUP" \
            --home-dir "$APP_DIR" \
            --shell "$nologin_shell" \
            "$APP_USER"
    elif ! id -Gn "$APP_USER" | tr ' ' '\n' | grep -qx "$APP_GROUP"; then
        usermod --append --groups "$APP_GROUP" "$APP_USER"
    fi
}

secure_checkout_ownership() {
    phase="securing the root-owned application checkout"
    chown -R root:root "$APP_DIR"
    chmod -R go-w "$APP_DIR"

    install -d -o "$APP_USER" -g "$APP_GROUP" -m 0750 \
        "$APP_DIR/staticfiles" \
        "$APP_DIR/media"
    chown -R "$APP_USER":"$APP_GROUP" \
        "$APP_DIR/staticfiles" \
        "$APP_DIR/media"
    chmod -R u+rwX,go-rwx \
        "$APP_DIR/staticfiles" \
        "$APP_DIR/media"
}

validate_repository() {
    [ -d "$APP_DIR/.git" ] \
        || die "$APP_DIR is not a Git repository. Run setup first."

    repository_owner="$(stat -c '%U' "$APP_DIR/.git")"
    [ "$repository_owner" = "root" ] || die \
        "The deployment checkout must be owned by root, not $repository_owner."

    repository_remote="$(git -C "$APP_DIR" config --get remote.origin.url)"
    [ "$repository_remote" = "$REPO_URL" ] || die \
        "origin is $repository_remote; expected $REPO_URL"

    repository_branch="$(git -C "$APP_DIR" symbolic-ref --quiet --short HEAD)" \
        || die "The deployment repository has a detached HEAD."
    [ "$repository_branch" = "$BRANCH" ] || die \
        "The deployment repository is on $repository_branch, not $BRANCH."

    repository_changes="$(git -C "$APP_DIR" status --porcelain)"
    [ -z "$repository_changes" ] || die \
        "The deployment repository has local changes. Commit or remove them first."

    insecure_path="$(
        find "$APP_DIR" \
            \( \
                -path "$APP_DIR/staticfiles" \
                -o -path "$APP_DIR/media" \
            \) -prune \
            -o \( ! -type l -perm /022 \) -print -quit
    )"
    [ -z "$insecure_path" ] || die \
        "Application source is group/other-writable: $insecure_path"

    for privileged_source in \
        "$APP_DIR/deploy/mead-tracker.sh" \
        "$APP_DIR/deploy/mead-tracker.service" \
        "$APP_DIR/deploy/mead-tracker-backup.service" \
        "$APP_DIR/deploy/mead-tracker-backup.timer"
    do
        [ -f "$privileged_source" ] && [ ! -L "$privileged_source" ] \
            || die "Privileged deployment source must be a regular file: $privileged_source"
        source_owner="$(stat -c '%U' "$privileged_source")"
        [ "$source_owner" = "root" ] || die \
            "Privileged deployment source is not root-owned: $privileged_source"
    done
}

ensure_repository_for_setup() {
    phase="preparing the application repository"
    install -d -o root -g root -m 0755 "$APP_DIR"

    if [ -d "$APP_DIR/.git" ]; then
        existing_owner="$(stat -c '%U' "$APP_DIR/.git")"
        [ "$existing_owner" = "root" ] || die \
            "Existing checkout is owned by $existing_owner; use a fresh root-owned checkout."
        secure_checkout_ownership
        validate_repository
        log "Using the existing clean repository at $APP_DIR."
        return
    fi

    if find "$APP_DIR" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
        die "$APP_DIR is not empty and is not a Git repository."
    fi

    git clone \
        --branch "$BRANCH" \
        --single-branch \
        "$REPO_URL" \
        "$APP_DIR"
    secure_checkout_ownership
}

ensure_virtual_environment() {
    phase="preparing the Python virtual environment"

    if [ -e "$APP_DIR/.venv" ] && [ ! -x "$VENV_PYTHON" ]; then
        die "$APP_DIR/.venv exists but does not contain a usable Python."
    fi

    if [ ! -x "$VENV_PYTHON" ]; then
        "$PYTHON_COMMAND" -m venv "$APP_DIR/.venv"
        "$VENV_PYTHON" -m pip install \
            --disable-pip-version-check \
            --no-cache-dir \
            --upgrade pip
    fi
}

install_python_dependencies() {
    phase="installing Python dependencies"
    "$VENV_PYTHON" -m pip install \
        --disable-pip-version-check \
        --no-cache-dir \
        --requirement "$APP_DIR/requirements.txt"
}

prompt_for_setup_config() {
    setup_address="${MEAD_TRACKER_SERVER_ADDRESS:-}"
    setup_port="${MEAD_TRACKER_PORT:-8765}"
    setup_signups="${MEAD_TRACKER_ALLOW_SIGNUPS:-true}"
    setup_timezone="${MEAD_TRACKER_TIME_ZONE:-America/Chicago}"

    if [ -z "$setup_address" ]; then
        detected_address="$(
            hostname -I 2>/dev/null | awk '{ print $1; exit }'
        )"
        if [ -t 0 ]; then
            printf 'Linux server LAN IP or hostname [%s]: ' "$detected_address"
            IFS= read -r setup_address
            [ -n "$setup_address" ] || setup_address="$detected_address"
        else
            die "Set MEAD_TRACKER_SERVER_ADDRESS for non-interactive setup."
        fi
    fi

    if [ -t 0 ] && [ "${MEAD_TRACKER_PORT+x}" != "x" ]; then
        printf 'Mead Tracker unprivileged port [8765]: '
        IFS= read -r entered_port
        [ -z "$entered_port" ] || setup_port="$entered_port"
    fi

    case "$setup_address" in
        ""|*[!A-Za-z0-9.-]*)
            die "Server address must be an IPv4 address or DNS hostname."
            ;;
    esac
    case "$setup_port" in
        ""|*[!0-9]*)
            die "Port must be a number from 1024 through 65535."
            ;;
    esac
    [ "$setup_port" -ge 1024 ] && [ "$setup_port" -le 65535 ] \
        || die "Port must be a number from 1024 through 65535."
    case "$setup_signups" in
        true|false) ;;
        *) die "MEAD_TRACKER_ALLOW_SIGNUPS must be true or false." ;;
    esac
    case "$setup_timezone" in
        ""|*[!A-Za-z0-9_+./-]*)
            die "MEAD_TRACKER_TIME_ZONE contains unsupported characters."
            ;;
    esac
}

ensure_environment_file() {
    phase="preparing protected application configuration"
    install -d -o root -g "$APP_GROUP" -m 0750 "$ENV_DIR"

    if [ -f "$ENV_FILE" ]; then
        chown root:"$APP_GROUP" "$ENV_FILE"
        chmod 0640 "$ENV_FILE"
        log "Preserving existing configuration: $ENV_FILE"
        return
    fi

    prompt_for_setup_config
    setup_secret="$(
        run_as_app "$VENV_PYTHON" -c \
            'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'
    )"
    case "$setup_secret" in
        *"'"*) die "Generated secret contained an unsupported quote." ;;
    esac

    temporary_env="$(mktemp "${TMPDIR:-/tmp}/mead-tracker-env.XXXXXX")"
    chmod 0600 "$temporary_env"
    cat >"$temporary_env" <<EOF
# Generated by deploy/mead-tracker.sh. Edit as root.
MEAD_TRACKER_HOST=0.0.0.0
MEAD_TRACKER_PORT=$setup_port

MEAD_TRACKER_DEBUG=false
MEAD_TRACKER_SECRET_KEY='$setup_secret'
MEAD_TRACKER_ALLOWED_HOSTS=$setup_address,localhost,127.0.0.1
MEAD_TRACKER_CSRF_TRUSTED_ORIGINS=
MEAD_TRACKER_ALLOW_SIGNUPS=$setup_signups
MEAD_TRACKER_TIME_ZONE=$setup_timezone
MEAD_TRACKER_SECURE_COOKIES=false
MEAD_TRACKER_TRUST_PROXY_HEADERS=false
MEAD_TRACKER_TRUSTED_PROXY=127.0.0.1

MEAD_TRACKER_DB_PATH=$STATE_DIR/mead-tracker.sqlite3
MEAD_TRACKER_BACKUP_DIR=$STATE_DIR/backups
MEAD_TRACKER_PUBLIC_BASE_URL=http://$setup_address:$setup_port
EOF
    install \
        -o root \
        -g "$APP_GROUP" \
        -m 0640 \
        "$temporary_env" \
        "$ENV_FILE"
    rm -f "$temporary_env"
    temporary_env=""
    log "Created LAN configuration at $ENV_FILE."
}

ensure_state_directories() {
    phase="preparing persistent data directories"
    install -d -o "$APP_USER" -g "$APP_GROUP" -m 0750 "$STATE_DIR"
    install -d -o "$APP_USER" -g "$APP_GROUP" -m 0700 "$STATE_DIR/backups"
    install -d -o "$APP_USER" -g "$APP_GROUP" -m 0750 \
        "$APP_DIR/staticfiles" \
        "$APP_DIR/media"
}

install_systemd_units() {
    phase="installing systemd units"
    validate_repository
    install -o root -g root -m 0644 \
        "$APP_DIR/deploy/mead-tracker.service" \
        "/etc/systemd/system/$SERVICE_NAME"
    install -o root -g root -m 0644 \
        "$APP_DIR/deploy/mead-tracker-backup.service" \
        "/etc/systemd/system/$BACKUP_SERVICE"
    install -o root -g root -m 0644 \
        "$APP_DIR/deploy/mead-tracker-backup.timer" \
        "/etc/systemd/system/$BACKUP_TIMER"
    systemctl daemon-reload
}

install_management_script() {
    phase="installing the deployment command"
    validate_repository
    temporary_script="$(
        mktemp /usr/local/sbin/.mead-tracker-deploy.XXXXXX
    )"
    install -o root -g root -m 0755 \
        "$APP_DIR/deploy/mead-tracker.sh" \
        "$temporary_script"
    mv -f "$temporary_script" "$INSTALLED_SCRIPT"
    temporary_script=""
}

configured_port() {
    run_as_app sh -c '
        set -a
        . "$1"
        set +a
        printf "%s" "${MEAD_TRACKER_PORT:-8000}"
    ' sh "$ENV_FILE"
}

configured_database_path() {
    run_as_app sh -c '
        set -a
        . "$1"
        set +a
        printf "%s" "${MEAD_TRACKER_DB_PATH:-data/mead_tracker.sqlite3}"
    ' sh "$ENV_FILE"
}

configured_public_url() {
    run_as_app sh -c '
        set -a
        . "$1"
        set +a
        printf "%s" "${MEAD_TRACKER_PUBLIC_BASE_URL:-}"
    ' sh "$ENV_FILE"
}

check_health() {
    phase="checking application health"
    health_port="$(configured_port)"
    case "$health_port" in
        ""|*[!0-9]*) die "Configured application port is invalid." ;;
    esac

    health_attempt=0
    while [ "$health_attempt" -lt 20 ]; do
        if systemctl is-active --quiet "$SERVICE_NAME"; then
            health_body="$(
                curl \
                    --fail \
                    --silent \
                    --max-time 2 \
                    "http://127.0.0.1:$health_port/health/" \
                    2>/dev/null || true
            )"
            if [ "$health_body" = '{"status": "ok"}' ]; then
                sleep 1
                if systemctl is-active --quiet "$SERVICE_NAME"; then
                    log "Health check passed on port $health_port."
                    return
                fi
            fi
        fi
        health_attempt=$((health_attempt + 1))
        sleep 1
    done

    systemctl status "$SERVICE_NAME" --no-pager || true
    journalctl -u "$SERVICE_NAME" -n 100 --no-pager || true
    die "The application did not pass its health check."
}

create_verified_backup() {
    phase="creating verified database backup"
    systemctl reset-failed "$BACKUP_SERVICE" >/dev/null 2>&1 || true
    systemctl start "$BACKUP_SERVICE"
    backup_created=1
    backup_output="$STATE_DIR/backups (verified by $BACKUP_SERVICE)"
    log "Verified backup completed."
}

setup_application() {
    [ ! -f "$STATE_DIR/mead-tracker.sqlite3" ] \
        || die "Existing database detected; use update instead of setup."

    install_packages
    validate_prerequisites setup
    ensure_service_account

    if [ -f "$ENV_FILE" ]; then
        chown root:"$APP_GROUP" "$ENV_FILE"
        chmod 0640 "$ENV_FILE"
        partial_database="$(configured_database_path)"
        case "$partial_database" in
            /*) ;;
            "~") partial_database="$APP_DIR" ;;
            "~/"*) partial_database="$APP_DIR/${partial_database#\~/}" ;;
            *) partial_database="$APP_DIR/$partial_database" ;;
        esac
        [ ! -f "$partial_database" ] \
            || die "Existing database detected; use update instead of setup."
        if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
            die "Mead Tracker is already running; use update instead of setup."
        fi
        log "Resuming an incomplete setup and preserving $ENV_FILE."
    fi

    ensure_repository_for_setup
    ensure_virtual_environment
    install_python_dependencies
    ensure_environment_file
    ensure_state_directories
    install_systemd_units

    phase="validating application configuration"
    run_with_env "$VENV_PYTHON" manage.py check

    phase="starting application"
    systemctl enable "$SERVICE_NAME"
    app_stopped=1
    systemctl restart "$SERVICE_NAME"
    check_health
    app_stopped=0

    phase="enabling daily backups"
    systemctl enable --now "$BACKUP_TIMER"
    install -o root -g root -m 0600 /dev/null "$INSTALL_MARKER"
    install_management_script

    setup_public_url="$(configured_public_url)"
    log "Initial setup complete."
    log "Open $setup_public_url"
    log "Create an administrator when needed:"
    printf '%s\n' \
        "  sudo -u $APP_USER sh -c 'set -a; . $ENV_FILE; set +a; cd $APP_DIR && exec .venv/bin/python manage.py createsuperuser'"
    log "Future updates: sudo $INSTALLED_SCRIPT update"
}

update_application() {
    phase="checking the existing installation"
    validate_prerequisites update
    id "$APP_USER" >/dev/null 2>&1 \
        || die "Service account not found: $APP_USER"
    getent group "$APP_GROUP" >/dev/null 2>&1 \
        || die "Service group not found: $APP_GROUP"
    [ -f "$ENV_FILE" ] || die "Configuration not found: $ENV_FILE"
    validate_repository

    phase="fetching $BRANCH"
    old_sha="$(git -C "$APP_DIR" rev-parse HEAD)"
    git -C "$APP_DIR" fetch \
        --prune \
        origin \
        "refs/heads/$BRANCH:refs/remotes/origin/$BRANCH"
    remote_sha="$(
        git -C "$APP_DIR" rev-parse "refs/remotes/origin/$BRANCH"
    )"

    has_new_commit=0
    if [ "$old_sha" != "$remote_sha" ]; then
        git -C "$APP_DIR" merge-base \
            --is-ancestor \
            "$old_sha" \
            "$remote_sha" \
            || die "Local and remote history diverged; refusing to update."
        has_new_commit=1
    else
        log "Code is current at $old_sha; reconciling the installation."
    fi

    if systemctl is-enabled --quiet "$BACKUP_TIMER" 2>/dev/null; then
        timer_should_run=1
        timer_should_enable=1
    elif systemctl is-active --quiet "$BACKUP_TIMER" 2>/dev/null; then
        timer_should_run=1
    elif [ ! -f "$INSTALL_MARKER" ]; then
        # Recover a first setup that created/migrated the database but failed
        # before enabling its daily backup timer.
        timer_should_run=1
        timer_should_enable=1
    fi

    phase="pausing scheduled backups"
    timer_stopped=1
    systemctl stop "$BACKUP_TIMER"

    if [ "$has_new_commit" -eq 1 ]; then
        # Use the current, known-working release to back up before code moves.
        create_verified_backup

        phase="stopping the web service"
        app_stopped=1
        systemctl stop "$SERVICE_NAME"
        validate_repository
        stopped_sha="$(git -C "$APP_DIR" rev-parse HEAD)"
        [ "$stopped_sha" = "$old_sha" ] \
            || die "The checkout changed during the update preflight."

        phase="applying fast-forward update"
        git -C "$APP_DIR" merge \
            --ff-only \
            "refs/remotes/origin/$BRANCH"
        new_sha="$(git -C "$APP_DIR" rev-parse HEAD)"
        [ "$new_sha" = "$remote_sha" ] \
            || die "Updated commit does not match the fetched remote commit."
        validate_repository

        install_python_dependencies
        install_systemd_units
    else
        # A previous attempt may have fast-forwarded before dependencies or
        # units were ready. Reconcile those pieces before taking a fresh
        # pre-migration backup and starting the service again.
        phase="stopping the web service for reconciliation"
        app_stopped=1
        systemctl stop "$SERVICE_NAME"
        validate_repository
        install_python_dependencies
        install_systemd_units
        create_verified_backup
        new_sha="$old_sha"
    fi

    phase="validating updated application"
    run_with_env "$VENV_PYTHON" manage.py check

    phase="starting updated application"
    systemctl start "$SERVICE_NAME"
    check_health
    app_stopped=0

    if [ "$timer_should_enable" -eq 1 ]; then
        phase="enabling scheduled backups"
        systemctl enable "$BACKUP_TIMER"
    fi
    if [ "$timer_should_run" -eq 1 ]; then
        phase="restoring scheduled backups"
        systemctl start "$BACKUP_TIMER"
    fi
    timer_stopped=0
    install -o root -g root -m 0600 /dev/null "$INSTALL_MARKER"
    install_management_script

    if [ "$old_sha" = "$new_sha" ]; then
        log "Installation reconciled successfully at $new_sha."
    else
        log "Updated successfully: $old_sha -> $new_sha"
    fi
    log "Verified backup: $backup_output"
}

case "${1:-}" in
    setup)
        require_root
        validate_fixed_paths
        acquire_lock
        setup_application
        ;;
    update)
        require_root
        validate_fixed_paths
        acquire_lock
        update_application
        ;;
    -h|--help|help)
        usage
        ;;
    *)
        usage >&2
        exit 2
        ;;
esac
