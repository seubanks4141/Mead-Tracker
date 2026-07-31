from __future__ import annotations

import re
from urllib.parse import urlparse

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from oauth2_provider.models import (
    get_access_token_model,
    get_application_model,
    get_grant_model,
    get_refresh_token_model,
)


CHATGPT_CALLBACK_PATH = re.compile(
    r"/connector/oauth/(?P<callback_id>[A-Za-z0-9._~-]+)"
)


def validate_chatgpt_callback_url(callback_url: str) -> str:
    """Return a normalized, exact ChatGPT OAuth callback URL."""
    callback_url = callback_url.strip()
    try:
        parsed_url = urlparse(callback_url)
        port = parsed_url.port
    except ValueError as exc:
        raise CommandError("The ChatGPT callback URL has an invalid port.") from exc

    if (
        parsed_url.scheme != "https"
        or parsed_url.hostname != "chatgpt.com"
        or port is not None
        or parsed_url.username
        or parsed_url.password
        or parsed_url.params
        or parsed_url.query
        or parsed_url.fragment
        or not CHATGPT_CALLBACK_PATH.fullmatch(parsed_url.path)
    ):
        raise CommandError(
            "The callback must exactly match "
            "https://chatgpt.com/connector/oauth/{callback_id}, using the "
            "callback ID shown by ChatGPT with no port, query, fragment, "
            "credentials, or trailing slash."
        )
    return callback_url


def validate_client_id(client_id: str) -> str:
    client_id = client_id.strip()
    if (
        not client_id
        or len(client_id) > 255
        or any(character.isspace() for character in client_id)
        or any(
            ord(character) < 33 or ord(character) == 127
            for character in client_id
        )
    ):
        raise CommandError(
            "The OAuth client ID must be 1-255 visible characters without "
            "whitespace."
        )
    return client_id


def revoke_application_authorizations(application) -> int:
    """Delete every code and token previously issued to one OAuth client."""

    deleted_count = 0
    for model in (
        get_grant_model(),
        get_refresh_token_model(),
        get_access_token_model(),
    ):
        count, _ = model.objects.filter(application=application).delete()
        deleted_count += count
    return deleted_count


class Command(BaseCommand):
    help = (
        "Create or update the predefined public OAuth client used by the "
        "ChatGPT Mead Tracker plugin."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--callback-url",
            help=(
                "Exact callback URL shown by ChatGPT. Defaults to "
                "MEAD_TRACKER_CHATGPT_CALLBACK_URL."
            ),
        )
        parser.add_argument(
            "--client-id",
            help=(
                "Public OAuth client ID entered in ChatGPT. Defaults to "
                "MEAD_TRACKER_CHATGPT_CLIENT_ID or mead-tracker-chatgpt."
            ),
        )
        parser.add_argument(
            "--revoke-existing-authorizations",
            action="store_true",
            help=(
                "Revoke every grant, access token, and refresh token already "
                "issued to this client, even when its configuration is unchanged."
            ),
        )
        parser.add_argument(
            "--discovery-only",
            action="store_true",
            help=(
                "Remove the predefined client and its authorizations so MCP can "
                "start safely before ChatGPT assigns a callback."
            ),
        )

    def handle(self, *args, **options):
        client_id = validate_client_id(
            options.get("client_id") or settings.CHATGPT_OAUTH_CLIENT_ID
        )
        application_model = get_application_model()

        if options["discovery_only"]:
            if options.get("callback_url") or settings.CHATGPT_OAUTH_CALLBACK_URL:
                raise CommandError(
                    "Clear MEAD_TRACKER_CHATGPT_CALLBACK_URL before using "
                    "--discovery-only."
                )
            with transaction.atomic():
                application = (
                    application_model.objects.select_for_update()
                    .filter(client_id=client_id)
                    .first()
                )
                if application is None:
                    deleted_count = 0
                else:
                    if (
                        application.registration_source
                        != application_model.RegistrationSource.MANUAL
                    ):
                        raise CommandError(
                            f"OAuth client {client_id!r} was not manually "
                            "registered; refusing to remove it."
                        )
                    deleted_count, _ = application.delete()
            self.stdout.write(
                self.style.SUCCESS(
                    "Discovery-only OAuth state is ready for client "
                    f"{client_id!r}; removed {deleted_count} client and "
                    "authorization records."
                )
            )
            return

        callback_url = options.get("callback_url") or settings.CHATGPT_OAUTH_CALLBACK_URL
        if not callback_url:
            raise CommandError(
                "Provide --callback-url, set "
                "MEAD_TRACKER_CHATGPT_CALLBACK_URL, or explicitly use "
                "--discovery-only."
            )
        callback_url = validate_chatgpt_callback_url(callback_url)

        with transaction.atomic():
            application = (
                application_model.objects.select_for_update()
                .filter(client_id=client_id)
                .first()
            )
            created = application is None
            if created:
                application = application_model(client_id=client_id)
            elif (
                application.registration_source
                != application_model.RegistrationSource.MANUAL
            ):
                raise CommandError(
                    f"OAuth client {client_id!r} was not manually registered; "
                    "refusing to replace it."
                )

            security_configuration = {
                "user_id": None,
                "redirect_uris": callback_url,
                "post_logout_redirect_uris": "",
                "client_type": application_model.CLIENT_PUBLIC,
                "authorization_grant_type": (
                    application_model.GRANT_AUTHORIZATION_CODE
                ),
                "client_secret": "",
                "hash_client_secret": False,
                "skip_authorization": False,
                "algorithm": application_model.NO_ALGORITHM,
                "allowed_origins": "",
                "registration_source": (
                    application_model.RegistrationSource.MANUAL
                ),
                "cimd_expires_at": None,
            }
            configuration_changed = not created and any(
                getattr(application, field_name) != expected_value
                for field_name, expected_value in security_configuration.items()
            )
            for field_name, expected_value in security_configuration.items():
                setattr(application, field_name, expected_value)
            application.name = "ChatGPT Mead Tracker"
            try:
                application.full_clean()
            except ValidationError as exc:
                raise CommandError("; ".join(exc.messages)) from exc
            application.save()
            should_revoke = (
                options["revoke_existing_authorizations"]
                or configuration_changed
            )
            revoked_count = (
                revoke_application_authorizations(application)
                if should_revoke
                else 0
            )

        action = "Created" if created else "Updated"
        revocation_message = (
            f" Revoked {revoked_count} existing authorization records."
            if should_revoke
            else ""
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} ChatGPT OAuth client {client_id!r} with callback "
                f"{callback_url}.{revocation_message}"
            )
        )
