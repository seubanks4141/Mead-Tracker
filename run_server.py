"""Start Mead Tracker with a cross-platform production WSGI server.

The command-line options take precedence over environment variables:

    python run_server.py --host 0.0.0.0 --port 8765

The default bind address is deliberately local-only. Binding to all network
interfaces must be an explicit choice.
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Callable


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_SETTINGS_MODULE = "mead_tracker.settings"


def valid_host(value: str) -> str:
    """Return a valid bind host or raise an argparse-friendly error."""
    host = value.strip()
    if not host:
        raise argparse.ArgumentTypeError("host cannot be empty")
    if "://" in host:
        raise argparse.ArgumentTypeError(
            "host must be a hostname or IP address, not a URL"
        )
    if any(character.isspace() for character in host):
        raise argparse.ArgumentTypeError("host cannot contain whitespace")
    if "/" in host or "\\" in host:
        raise argparse.ArgumentTypeError("host cannot contain a path")
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if ":" in host:
        try:
            ipaddress.IPv6Address(host)
        except ipaddress.AddressValueError as error:
            raise argparse.ArgumentTypeError(
                "put the port in --port, not in the host value"
            ) from error
    if any(character in host for character in ",*?"):
        raise argparse.ArgumentTypeError("host cannot contain wildcards or a list")
    return host


def valid_port(value: str | int) -> int:
    """Return a TCP port in the valid user-selectable range."""
    try:
        port = int(value)
    except (TypeError, ValueError) as error:
        raise argparse.ArgumentTypeError(
            f"port must be a whole number, got {value!r}"
        ) from error
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def environment_flag(
    environ: Mapping[str, str],
    name: str,
    default: bool = False,
) -> bool:
    value = environ.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(
        f"{name} must be one of: true, false, 1, 0, yes, no, on, off."
    )


def build_parser(environ: Mapping[str, str] | None = None) -> argparse.ArgumentParser:
    """Build the CLI parser using environment variables as defaults."""
    environment = os.environ if environ is None else environ
    parser = argparse.ArgumentParser(
        description="Run Mead Tracker using the Waitress WSGI server.",
    )
    parser.add_argument(
        "--host",
        type=valid_host,
        default=environment.get("MEAD_TRACKER_HOST", DEFAULT_HOST),
        help=(
            "interface to bind to (environment: MEAD_TRACKER_HOST; "
            f"default: {DEFAULT_HOST})"
        ),
    )
    parser.add_argument(
        "--port",
        type=valid_port,
        default=environment.get("MEAD_TRACKER_PORT", str(DEFAULT_PORT)),
        help=(
            "TCP port to listen on (environment: MEAD_TRACKER_PORT; "
            f"default: {DEFAULT_PORT})"
        ),
    )
    return parser


def parse_args(
    argv: Sequence[str] | None = None,
    environ: Mapping[str, str] | None = None,
) -> argparse.Namespace:
    """Parse and validate runtime configuration."""
    parser = build_parser(environ)
    args = parser.parse_args(argv)

    # argparse applies ``type`` to string defaults, but validating here too
    # keeps this function correct for any custom Mapping implementation.
    try:
        args.host = valid_host(args.host)
        args.port = valid_port(args.port)
    except argparse.ArgumentTypeError as error:
        parser.error(str(error))
    return args


def load_environment() -> None:
    """Load a project-local .env file while preserving real environment values."""
    env_path = Path(__file__).resolve().with_name(".env")
    if not env_path.is_file():
        return

    try:
        from dotenv import load_dotenv
    except ImportError as error:
        raise RuntimeError(
            "python-dotenv is not installed. Run: python -m pip install -r "
            "requirements.txt"
        ) from error

    load_dotenv(dotenv_path=env_path, override=False)


def load_application() -> Any:
    """Load Django's WSGI application after runtime configuration is available."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", DEFAULT_SETTINGS_MODULE)
    try:
        from django.core.wsgi import get_wsgi_application
    except ImportError as error:
        raise RuntimeError(
            "Django is not installed. Run: python -m pip install -r "
            "requirements.txt"
        ) from error
    return get_wsgi_application()


def _waitress_serve() -> Callable[..., Any]:
    try:
        from waitress import serve
    except ImportError as error:
        raise RuntimeError(
            "Waitress is not installed. Run: python -m pip install -r "
            "requirements.txt"
        ) from error
    return serve


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    application: Any | None = None,
    serve: Callable[..., Any] | None = None,
) -> int:
    """Run the application; injectable arguments keep configuration testable."""
    load_environment()
    effective_environment = os.environ if environ is None else environ
    args = parse_args(argv, effective_environment)
    wsgi_application = load_application() if application is None else application
    waitress_serve = _waitress_serve() if serve is None else serve

    display_host = "localhost" if args.host in {"127.0.0.1", "::1"} else args.host
    print(f"Mead Tracker listening on http://{display_host}:{args.port}", flush=True)
    public_url = effective_environment.get(
        "MEAD_TRACKER_PUBLIC_BASE_URL",
        "",
    ).strip().rstrip("/")
    if public_url:
        print(f"Phone and QR address: {public_url}", flush=True)
    if args.host in {"0.0.0.0", "::"}:
        print(
            "Network access enabled. Configure allowed hosts, authentication, "
            "and a firewall before exposing this service.",
            flush=True,
        )

    server_options = {
        "host": args.host,
        "port": args.port,
        "threads": 4,
    }
    if environment_flag(
        effective_environment,
        "MEAD_TRACKER_TRUST_PROXY_HEADERS",
        False,
    ):
        default_proxy = "::1" if args.host == "::1" else "127.0.0.1"
        trusted_proxy = effective_environment.get(
            "MEAD_TRACKER_TRUSTED_PROXY",
            default_proxy,
        ).strip()
        if not trusted_proxy:
            raise RuntimeError(
                "MEAD_TRACKER_TRUSTED_PROXY cannot be empty when proxy headers are trusted."
            )
        if trusted_proxy == "*" and args.host not in {"127.0.0.1", "::1"}:
            raise RuntimeError(
                "Refusing to trust proxy headers from every client on a network bind."
            )
        server_options.update(
            {
                "trusted_proxy": trusted_proxy,
                "trusted_proxy_count": 1,
                "trusted_proxy_headers": {
                    "x-forwarded-host",
                    "x-forwarded-proto",
                },
            }
        )

    try:
        waitress_serve(wsgi_application, **server_options)
    except OSError as error:
        print(
            f"Unable to listen on {args.host}:{args.port}: {error}",
            file=sys.stderr,
        )
        return 1
    except KeyboardInterrupt:
        print("\nMead Tracker stopped.", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as error:
        print(f"Startup error: {error}", file=sys.stderr)
        raise SystemExit(1) from error
