"""Settings for the Mead Tracker.

Every deployment-specific value is read from the environment so the same
source tree can run on Windows for testing and on a Linux VM in production.
"""

from __future__ import annotations

import os
from ipaddress import ip_address
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


def env_int(
    name: str,
    default: int,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    raw_value = os.getenv(name)
    try:
        value = default if raw_value is None else int(raw_value.strip())
    except (AttributeError, ValueError) as exc:
        raise ImproperlyConfigured(f"{name} must be an integer.") from exc
    if minimum is not None and value < minimum:
        raise ImproperlyConfigured(f"{name} must be at least {minimum}.")
    if maximum is not None and value > maximum:
        raise ImproperlyConfigured(f"{name} must be no greater than {maximum}.")
    return value


def _host_is_allowed(hostname: str, allowed_hosts: list[str]) -> bool:
    for allowed in allowed_hosts:
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
    "oauth2_provider",
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

    if not _host_is_allowed(public_hostname, ALLOWED_HOSTS):
        raise ImproperlyConfigured(
            "The hostname in MEAD_TRACKER_PUBLIC_BASE_URL must also appear in "
            "MEAD_TRACKER_ALLOWED_HOSTS."
        )


CHATGPT_ENABLED = env_bool("MEAD_TRACKER_CHATGPT_ENABLED", False)
MCP_HOST = os.getenv("MEAD_TRACKER_MCP_HOST", "127.0.0.1").strip()
unbracketed_mcp_host = MCP_HOST.strip("[]")
if (
    not MCP_HOST
    or not unbracketed_mcp_host
    or (MCP_HOST.startswith("[") != MCP_HOST.endswith("]"))
    or any(character.isspace() for character in MCP_HOST)
    or any(character in MCP_HOST for character in ("/", "\\", "?", "#", "@"))
):
    raise ImproperlyConfigured(
        "MEAD_TRACKER_MCP_HOST must be a hostname or IP address without a scheme, "
        "path, credentials, query, or fragment."
    )
if ":" in unbracketed_mcp_host:
    try:
        ip_address(unbracketed_mcp_host)
    except ValueError as exc:
        raise ImproperlyConfigured(
            "MEAD_TRACKER_MCP_HOST must not include a port; use "
            "MEAD_TRACKER_MCP_PORT separately."
        ) from exc
MCP_PORT = env_int(
    "MEAD_TRACKER_MCP_PORT",
    8766,
    minimum=1,
    maximum=65535,
)

configured_mcp_public_url = os.getenv(
    "MEAD_TRACKER_MCP_PUBLIC_URL",
    "",
).strip()
configured_oauth_issuer_url = os.getenv(
    "MEAD_TRACKER_OAUTH_ISSUER_URL",
    "",
).strip()

if PUBLIC_BASE_URL:
    default_mcp_public_url = f"{PUBLIC_BASE_URL}/mcp"
    default_oauth_issuer_url = f"{PUBLIC_BASE_URL}/o"
else:
    local_mcp_host = MCP_HOST.strip("[]")
    if local_mcp_host in {"0.0.0.0", "::"}:
        local_mcp_host = "127.0.0.1"
    if ":" in local_mcp_host:
        local_mcp_host = f"[{local_mcp_host}]"
    default_mcp_public_url = f"http://{local_mcp_host}:{MCP_PORT}/mcp"
    development_web_port = env_int(
        "MEAD_TRACKER_PORT",
        8000,
        minimum=1,
        maximum=65535,
    )
    default_oauth_issuer_url = f"http://127.0.0.1:{development_web_port}/o"

MCP_PUBLIC_URL = (configured_mcp_public_url or default_mcp_public_url).rstrip("/")
OAUTH_ISSUER_URL = (
    configured_oauth_issuer_url or default_oauth_issuer_url
).rstrip("/")


def _validate_chatgpt_service_url(name: str, value: str) -> None:
    try:
        parsed_url = urlparse(value)
        parsed_hostname = parsed_url.hostname
        parsed_url.port
    except ValueError as exc:
        raise ImproperlyConfigured(
            f"{name} contains an invalid hostname or port."
        ) from exc
    if (
        parsed_url.scheme not in {"http", "https"}
        or not parsed_url.netloc
        or not parsed_hostname
        or parsed_url.username
        or parsed_url.password
        or parsed_url.params
        or parsed_url.query
        or parsed_url.fragment
        or parsed_hostname in {"0.0.0.0", "::"}
    ):
        raise ImproperlyConfigured(
            f"{name} must be an http(s) URL without credentials, a query, a "
            "fragment, or a wildcard bind address."
        )
    if CHATGPT_ENABLED and parsed_url.scheme != "https":
        raise ImproperlyConfigured(
            f"{name} must use https when MEAD_TRACKER_CHATGPT_ENABLED is true."
        )


_validate_chatgpt_service_url("MEAD_TRACKER_MCP_PUBLIC_URL", MCP_PUBLIC_URL)
_validate_chatgpt_service_url("MEAD_TRACKER_OAUTH_ISSUER_URL", OAUTH_ISSUER_URL)
if CHATGPT_ENABLED and not PUBLIC_BASE_URL and (
    not configured_mcp_public_url or not configured_oauth_issuer_url
):
    raise ImproperlyConfigured(
        "Enable ChatGPT only after configuring MEAD_TRACKER_PUBLIC_BASE_URL, or "
        "set both MEAD_TRACKER_MCP_PUBLIC_URL and "
        "MEAD_TRACKER_OAUTH_ISSUER_URL explicitly."
    )

CHATGPT_OAUTH_CLIENT_ID = os.getenv(
    "MEAD_TRACKER_CHATGPT_CLIENT_ID",
    "mead-tracker-chatgpt",
).strip()
CHATGPT_OAUTH_CALLBACK_URL = os.getenv(
    "MEAD_TRACKER_CHATGPT_CALLBACK_URL",
    "",
).strip()
if (
    not CHATGPT_OAUTH_CLIENT_ID
    or len(CHATGPT_OAUTH_CLIENT_ID) > 255
    or any(character.isspace() for character in CHATGPT_OAUTH_CLIENT_ID)
    or any(
        ord(character) < 33 or ord(character) == 127
        for character in CHATGPT_OAUTH_CLIENT_ID
    )
):
    raise ImproperlyConfigured(
        "MEAD_TRACKER_CHATGPT_CLIENT_ID must be 1-255 visible characters "
        "without whitespace."
    )

OAUTH2_PROVIDER = {
    "SCOPES": {
        "batches:read": "Read batches owned by your Mead Tracker account.",
    },
    "DEFAULT_SCOPES": ["batches:read"],
    "AUTHORIZATION_CODE_EXPIRE_SECONDS": 60,
    "ACCESS_TOKEN_EXPIRE_SECONDS": 3600,
    "ROTATE_REFRESH_TOKEN": True,
    "REFRESH_TOKEN_REUSE_PROTECTION": True,
    "REQUEST_APPROVAL_PROMPT": "force",
    "PKCE_REQUIRED": True,
    "ALLOWED_REDIRECT_URI_SCHEMES": ["https"],
    "ALLOWED_SCHEMES": ["https"],
    "ALLOW_URI_WILDCARDS": False,
    "ALLOW_LOCALHOST_LOOPBACK": False,
    "OIDC_ENABLED": False,
    # OAuth Toolkit uses this value for RFC 8414 even with OIDC disabled.
    "OIDC_ISS_ENDPOINT": OAUTH_ISSUER_URL,
    "DCR_ENABLED": False,
    "CIMD_ENABLED": False,
    "COMPLIANT_BCP_RFC9700_IMPLICIT_GRANT": True,
    "COMPLIANT_BCP_RFC9700_PASSWORD_GRANT": True,
    "COMPLIANT_BCP_RFC9700_PKCE_METHOD": True,
    "COMPLIANT_BCP_RFC9700_ACCESS_TOKEN_TRANSPORT": True,
    "COMPLIANT_BCP_RFC9700_AUTHZ_RESPONSE_ISS": True,
    "COMPLIANT_BCP_RFC9700_TOKEN_STORAGE": True,
    "COMPLIANT_BCP_RFC9700_REFRESH_TOKEN": True,
    "COMPLIANT_BCP_RFC9700_REDIRECT_URI_SCHEME": True,
    "COMPLIANT_BCP_RFC9700_REDIRECT_URI_MATCHING": True,
    "COMPLIANT_BCP_RFC9700_PKCE_REQUIRED": True,
    "OAUTH2_RESPONSE_TYPES_SUPPORTED": ["code"],
    "OAUTH2_TOKEN_ENDPOINT_AUTH_METHODS_SUPPORTED": ["none"],
    "OAUTH2_GRANT_TYPES_SUPPORTED": [
        "authorization_code",
        "refresh_token",
    ],
    "OAUTH2_PROTECTED_RESOURCE_IDENTIFIER": MCP_PUBLIC_URL,
    "OAUTH2_PROTECTED_RESOURCE_AUTHORIZATION_SERVERS": [
        OAUTH_ISSUER_URL,
    ],
    "OAUTH2_PROTECTED_RESOURCE_BEARER_METHODS_SUPPORTED": ["header"],
    "OAUTH2_PROTECTED_RESOURCE_NAME": "Mead Tracker batch context",
}

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

TRUST_PROXY_HEADERS = env_bool("MEAD_TRACKER_TRUST_PROXY_HEADERS", False)
if TRUST_PROXY_HEADERS:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    USE_X_FORWARDED_HOST = True


def _validate_chatgpt_public_security() -> None:
    if not CHATGPT_ENABLED:
        return

    problems = []
    if DEBUG:
        problems.append("MEAD_TRACKER_DEBUG must be false")
    if not SESSION_COOKIE_SECURE or not CSRF_COOKIE_SECURE:
        problems.append("MEAD_TRACKER_SECURE_COOKIES must be true")
    if any(host.strip() == "*" for host in ALLOWED_HOSTS):
        problems.append("MEAD_TRACKER_ALLOWED_HOSTS must not contain *")
    if not PUBLIC_BASE_URL or urlparse(PUBLIC_BASE_URL).scheme != "https":
        problems.append(
            "MEAD_TRACKER_PUBLIC_BASE_URL must be the public HTTPS origin"
        )
    if problems:
        raise ImproperlyConfigured(
            "MEAD_TRACKER_CHATGPT_ENABLED requires production-safe web "
            "settings: " + "; ".join(problems) + "."
        )


_validate_chatgpt_public_security()

if not DEBUG:
    SECURE_REFERRER_POLICY = "same-origin"
