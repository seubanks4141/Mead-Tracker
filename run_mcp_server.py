"""Run Mead Tracker's authenticated Streamable HTTP MCP service."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping, Sequence
from urllib.parse import urlparse

from run_server import load_environment, valid_host, valid_port


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8766
DEFAULT_SETTINGS_MODULE = "mead_tracker.settings"


def build_parser(environ: Mapping[str, str] | None = None) -> argparse.ArgumentParser:
    environment = os.environ if environ is None else environ
    parser = argparse.ArgumentParser(
        description="Run the authenticated Mead Tracker MCP service.",
    )
    parser.add_argument(
        "--host",
        type=valid_host,
        default=environment.get("MEAD_TRACKER_MCP_HOST", DEFAULT_HOST),
        help=(
            "interface to bind to (environment: MEAD_TRACKER_MCP_HOST; "
            f"default: {DEFAULT_HOST})"
        ),
    )
    parser.add_argument(
        "--port",
        type=valid_port,
        default=environment.get("MEAD_TRACKER_MCP_PORT", str(DEFAULT_PORT)),
        help=(
            "TCP port to listen on (environment: MEAD_TRACKER_MCP_PORT; "
            f"default: {DEFAULT_PORT})"
        ),
    )
    return parser


def parse_args(
    argv: Sequence[str] | None = None,
    environ: Mapping[str, str] | None = None,
) -> argparse.Namespace:
    parser = build_parser(environ)
    args = parser.parse_args(argv)
    try:
        args.host = valid_host(args.host)
        args.port = valid_port(args.port)
    except argparse.ArgumentTypeError as error:
        parser.error(str(error))
    return args


def load_application():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", DEFAULT_SETTINGS_MODULE)
    try:
        import django
    except ImportError as error:
        raise RuntimeError(
            "Django is not installed. Run: python -m pip install -r requirements.txt"
        ) from error

    django.setup()
    from django.conf import settings

    if not getattr(settings, "CHATGPT_ENABLED", False):
        raise RuntimeError(
            "Set MEAD_TRACKER_CHATGPT_ENABLED=true after configuring the public "
            "OAuth and MCP URLs."
        )

    try:
        from django.core.management.base import CommandError
        from django.db import DatabaseError
        from oauth2_provider.models import get_application_model
        from tracker.management.commands.configure_chatgpt_oauth import (
            validate_chatgpt_callback_url,
        )

        application_model = get_application_model()
        application = application_model.objects.filter(
            client_id=settings.CHATGPT_OAUTH_CLIENT_ID,
        ).first()
    except DatabaseError as error:
        raise RuntimeError(
            "OAuth tables are unavailable. Run `python manage.py migrate`, then "
            "`python manage.py configure_chatgpt_oauth`."
        ) from error

    expected_callback = settings.CHATGPT_OAUTH_CALLBACK_URL
    if application is None:
        if expected_callback:
            raise RuntimeError(
                "The predefined ChatGPT OAuth client is missing. Run "
                "`python manage.py configure_chatgpt_oauth` before starting MCP."
            )
        # ChatGPT assigns its exact redirect URI while an administrator creates
        # the connection. Until that value exists, it is safe to publish the
        # authenticated MCP/discovery surface because no OAuth client exists.
    else:
        if not expected_callback:
            raise RuntimeError(
                "Discovery-only startup requires the predefined OAuth client "
                "to be absent. Run `python manage.py configure_chatgpt_oauth "
                "--discovery-only` before starting MCP."
            )
        try:
            validate_chatgpt_callback_url(application.redirect_uris)
        except CommandError as error:
            raise RuntimeError(
                "The configured OAuth client does not contain one exact ChatGPT "
                "callback. Run `python manage.py configure_chatgpt_oauth` again."
            ) from error
        if expected_callback and application.redirect_uris != expected_callback:
            raise RuntimeError(
                "The OAuth client's callback differs from "
                "MEAD_TRACKER_CHATGPT_CALLBACK_URL. Re-run "
                "`python manage.py configure_chatgpt_oauth`."
            )
        if (
            application.client_type != application_model.CLIENT_PUBLIC
            or application.authorization_grant_type
            != application_model.GRANT_AUTHORIZATION_CODE
            or application.client_secret
            or application.hash_client_secret
            or application.skip_authorization
            or application.user_id is not None
            or application.registration_source
            != application_model.RegistrationSource.MANUAL
        ):
            raise RuntimeError(
                "The ChatGPT OAuth client is not the expected predefined public "
                "authorization-code client. Re-run "
                "`python manage.py configure_chatgpt_oauth`."
            )

    from mead_tracker.mcp_server import create_mcp_application

    return create_mcp_application()


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    application=None,
    serve=None,
) -> int:
    load_environment()
    effective_environment = os.environ if environ is None else environ
    args = parse_args(argv, effective_environment)
    asgi_application = load_application() if application is None else application

    if serve is None:
        try:
            import uvicorn
        except ImportError as error:
            raise RuntimeError(
                "Uvicorn is not installed. Run: python -m pip install -r "
                "requirements.txt"
            ) from error
        serve = uvicorn.run

    if args.host not in {"127.0.0.1", "::1", "localhost"}:
        raise RuntimeError(
            "The MCP service must bind to loopback and be exposed through the "
            "same trusted HTTPS reverse proxy as Mead Tracker."
        )

    configured_public_url = effective_environment.get(
        "MEAD_TRACKER_MCP_PUBLIC_URL",
        "",
    ).strip()
    public_path = urlparse(configured_public_url).path or "/mcp"
    display_host = f"[{args.host}]" if ":" in args.host else args.host
    print(
        f"Mead Tracker MCP listening on "
        f"http://{display_host}:{args.port}{public_path}",
        flush=True,
    )
    try:
        serve(
            asgi_application,
            host=args.host,
            port=args.port,
            log_level="info",
            proxy_headers=False,
        )
    except OSError as error:
        print(
            f"Unable to listen on {args.host}:{args.port}: {error}",
            file=sys.stderr,
        )
        return 1
    except KeyboardInterrupt:
        print("\nMead Tracker MCP stopped.", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as error:
        print(f"Startup error: {error}", file=sys.stderr)
        raise SystemExit(1) from error
