"""Settings for the Mead Tracker.

Every deployment-specific value is read from the environment so the same
source tree can run on Windows for testing and on a Linux VM in production.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from django.core.exceptions import ImproperlyConfigured


BASE_DIR = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv(BASE_DIR / ".env", override=False)


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ImproperlyConfigured(
        f"{name} must be one of: true, false, 1, 0, yes, no, on, off."
    )


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


DEVELOPMENT_SECRET_KEY = "development-only-change-me-before-production"
SECRET_KEY = os.getenv("MEAD_TRACKER_SECRET_KEY", DEVELOPMENT_SECRET_KEY)
DEBUG = env_bool("MEAD_TRACKER_DEBUG", True)
if not DEBUG and (
    SECRET_KEY == DEVELOPMENT_SECRET_KEY
    or SECRET_KEY.lower().startswith("replace-with")
    or len(SECRET_KEY) < 50
    or len(set(SECRET_KEY)) < 5
):
    raise ImproperlyConfigured(
        "MEAD_TRACKER_SECRET_KEY must be a private, randomly generated value "
        "of at least 50 characters when MEAD_TRACKER_DEBUG is false."
    )

ALLOWED_HOSTS = env_list(
    "MEAD_TRACKER_ALLOWED_HOSTS",
    "localhost,127.0.0.1,[::1]" if not DEBUG else "*",
)
CSRF_TRUSTED_ORIGINS = env_list("MEAD_TRACKER_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "tracker.apps.TrackerConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "mead_tracker.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "tracker.context_processors.app_settings",
            ],
        },
    },
]

WSGI_APPLICATION = "mead_tracker.wsgi.application"
ASGI_APPLICATION = "mead_tracker.asgi.application"

database_path = Path(
    os.getenv("MEAD_TRACKER_DB_PATH", str(BASE_DIR / "data" / "mead_tracker.sqlite3"))
).expanduser()
if not database_path.is_absolute():
    database_path = (BASE_DIR / database_path).resolve()
database_path.parent.mkdir(parents=True, exist_ok=True)

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": database_path,
        "OPTIONS": {"timeout": 20},
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.getenv("MEAD_TRACKER_TIME_ZONE", "America/Chicago")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "media/"
media_root = Path(
    os.getenv("MEAD_TRACKER_MEDIA_ROOT", str(BASE_DIR / "media"))
).expanduser()
if not media_root.is_absolute():
    media_root = (BASE_DIR / media_root).resolve()
MEDIA_ROOT = media_root
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "tracker:dashboard"
LOGOUT_REDIRECT_URL = "login"
ALLOW_SIGNUPS = env_bool("MEAD_TRACKER_ALLOW_SIGNUPS", DEBUG)

PUBLIC_BASE_URL = os.getenv("MEAD_TRACKER_PUBLIC_BASE_URL", "").strip().rstrip("/")
if PUBLIC_BASE_URL:
    parsed_public_url = urlparse(PUBLIC_BASE_URL)
    try:
        parsed_hostname = parsed_public_url.hostname
        parsed_public_url.port
    except ValueError as exc:
        raise ImproperlyConfigured(
            "MEAD_TRACKER_PUBLIC_BASE_URL contains an invalid hostname or port."
        ) from exc
    if (
        parsed_public_url.scheme not in {"http", "https"}
        or not parsed_public_url.netloc
        or not parsed_hostname
        or parsed_public_url.username
        or parsed_public_url.password
        or parsed_public_url.path
        or parsed_public_url.params
        or parsed_public_url.query
        or parsed_public_url.fragment
        or parsed_hostname in {"0.0.0.0", "::"}
    ):
        raise ImproperlyConfigured(
            "MEAD_TRACKER_PUBLIC_BASE_URL must be an http(s) origin such as "
            "https://mead.example.com or http://192.168.1.20:8765. Do not use "
            "credentials, paths, queries, fragments, or wildcard bind addresses."
        )

    public_hostname = parsed_hostname

    def _host_is_allowed(hostname: str) -> bool:
        for allowed in ALLOWED_HOSTS:
            normalized = allowed.strip("[]").lower()
            if normalized == "*":
                return True
            if normalized.startswith(".") and (
                hostname.lower() == normalized[1:]
                or hostname.lower().endswith(normalized)
            ):
                return True
            if hostname.lower() == normalized:
                return True
        return False

    if not _host_is_allowed(public_hostname):
        raise ImproperlyConfigured(
            "The hostname in MEAD_TRACKER_PUBLIC_BASE_URL must also appear in "
            "MEAD_TRACKER_ALLOWED_HOSTS."
        )
BACKUP_DIR = Path(
    os.getenv("MEAD_TRACKER_BACKUP_DIR", str(BASE_DIR / "backups"))
).expanduser()
if not BACKUP_DIR.is_absolute():
    BACKUP_DIR = (BASE_DIR / BACKUP_DIR).resolve()

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_NAME = "mead_tracker_sessionid"
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_NAME = "mead_tracker_csrftoken"
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = env_bool("MEAD_TRACKER_SECURE_COOKIES", False)
CSRF_COOKIE_SECURE = env_bool("MEAD_TRACKER_SECURE_COOKIES", False)
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

if env_bool("MEAD_TRACKER_TRUST_PROXY_HEADERS", False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    USE_X_FORWARDED_HOST = True

if not DEBUG:
    SECURE_REFERRER_POLICY = "same-origin"
