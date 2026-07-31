from __future__ import annotations

import base64
import hashlib
import importlib
import json
from io import StringIO
from urllib.parse import parse_qs, urlparse

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import NoReverseMatch, clear_url_caches, reverse
from oauth2_provider.models import (
    get_access_token_model,
    get_application_model,
    get_refresh_token_model,
)

from mead_tracker import urls as project_urls


CHATGPT_CALLBACK_URL = (
    "https://chatgpt.com/connector/oauth/callback-test_123"
)
CHATGPT_CLIENT_ID = "mead-tracker-chatgpt-test"


def _well_known_path(prefix: str, public_url: str) -> str:
    resource_path = urlparse(public_url).path.strip("/")
    if resource_path:
        return f"/.well-known/{prefix}/{resource_path}"
    return f"/.well-known/{prefix}"


class ChatGPTURLSettingMixin:
    chatgpt_enabled = True

    @classmethod
    def setUpClass(cls):
        cls._chatgpt_url_override = override_settings(
            CHATGPT_ENABLED=cls.chatgpt_enabled
        )
        cls._chatgpt_url_override.enable()
        importlib.reload(project_urls)
        clear_url_caches()
        try:
            super().setUpClass()
        except Exception:
            cls._chatgpt_url_override.disable()
            importlib.reload(project_urls)
            clear_url_caches()
            raise

    @classmethod
    def tearDownClass(cls):
        try:
            super().tearDownClass()
        finally:
            cls._chatgpt_url_override.disable()
            importlib.reload(project_urls)
            clear_url_caches()


class OAuthDisabledRouteTests(ChatGPTURLSettingMixin, SimpleTestCase):
    chatgpt_enabled = False

    def test_oauth_and_discovery_routes_are_absent_when_disabled(self):
        with self.assertRaises(NoReverseMatch):
            reverse("oauth2_provider:authorize")

        for path in (
            "/o/authorize/",
            "/o/token/",
            _well_known_path(
                "oauth-authorization-server",
                settings.OAUTH_ISSUER_URL,
            ),
            _well_known_path(
                "oauth-protected-resource",
                settings.MCP_PUBLIC_URL,
            ),
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)


class OAuthConfigurationTests(ChatGPTURLSettingMixin, SimpleTestCase):
    def test_oauth_provider_is_restricted_to_read_only_pkce_code_flow(self):
        provider = settings.OAUTH2_PROVIDER

        self.assertEqual(
            provider["SCOPES"],
            {
                "batches:read": (
                    "Read batches owned by your Mead Tracker account."
                )
            },
        )
        self.assertEqual(provider["DEFAULT_SCOPES"], ["batches:read"])
        self.assertTrue(provider["PKCE_REQUIRED"])
        self.assertTrue(provider["COMPLIANT_BCP_RFC9700_PKCE_METHOD"])
        self.assertTrue(provider["COMPLIANT_BCP_RFC9700_TOKEN_STORAGE"])
        self.assertTrue(provider["REFRESH_TOKEN_REUSE_PROTECTION"])
        self.assertEqual(provider["ALLOWED_REDIRECT_URI_SCHEMES"], ["https"])
        self.assertEqual(provider["OAUTH2_RESPONSE_TYPES_SUPPORTED"], ["code"])
        self.assertEqual(
            provider["OAUTH2_GRANT_TYPES_SUPPORTED"],
            ["authorization_code", "refresh_token"],
        )
        self.assertEqual(
            provider["OAUTH2_TOKEN_ENDPOINT_AUTH_METHODS_SUPPORTED"],
            ["none"],
        )
        self.assertFalse(provider["DCR_ENABLED"])
        self.assertFalse(provider["CIMD_ENABLED"])
        self.assertEqual(
            provider["OAUTH2_PROTECTED_RESOURCE_IDENTIFIER"],
            settings.MCP_PUBLIC_URL,
        )
        self.assertEqual(
            provider["OAUTH2_PROTECTED_RESOURCE_AUTHORIZATION_SERVERS"],
            [settings.OAUTH_ISSUER_URL],
        )

    def test_authorization_server_metadata_uses_canonical_public_urls(self):
        metadata_path = _well_known_path(
            "oauth-authorization-server",
            settings.OAUTH_ISSUER_URL,
        )
        response = self.client.get(metadata_path)

        self.assertEqual(response.status_code, 200)
        document = response.json()
        issuer = urlparse(settings.OAUTH_ISSUER_URL)
        public_origin = f"{issuer.scheme}://{issuer.netloc}"
        self.assertEqual(document["issuer"], settings.OAUTH_ISSUER_URL)
        self.assertEqual(
            document["authorization_endpoint"],
            f"{public_origin}{reverse('oauth2_provider:authorize')}",
        )
        self.assertEqual(
            document["token_endpoint"],
            f"{public_origin}{reverse('oauth2_provider:token')}",
        )
        self.assertEqual(
            document["revocation_endpoint"],
            f"{public_origin}{reverse('oauth2_provider:revoke-token')}",
        )
        self.assertNotIn("introspection_endpoint", document)
        self.assertNotIn("registration_endpoint", document)
        self.assertEqual(document["response_types_supported"], ["code"])
        self.assertEqual(
            document["grant_types_supported"],
            ["authorization_code", "refresh_token"],
        )
        self.assertEqual(document["scopes_supported"], ["batches:read"])
        self.assertEqual(document["code_challenge_methods_supported"], ["S256"])
        self.assertEqual(
            document["token_endpoint_auth_methods_supported"],
            ["none"],
        )
        self.assertFalse(document["client_id_metadata_document_supported"])
        self.assertTrue(
            document["authorization_response_iss_parameter_supported"]
        )
        self.assertEqual(response.headers["Access-Control-Allow-Origin"], "*")

    def test_protected_resource_metadata_binds_exact_mcp_audience(self):
        metadata_path = _well_known_path(
            "oauth-protected-resource",
            settings.MCP_PUBLIC_URL,
        )
        response = self.client.get(metadata_path)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "resource": settings.MCP_PUBLIC_URL,
                "authorization_servers": [settings.OAUTH_ISSUER_URL],
                "scopes_supported": ["batches:read"],
                "bearer_methods_supported": ["header"],
                "resource_name": "Mead Tracker batch context",
            },
        )

    def test_unused_oauth_toolkit_surfaces_are_not_mounted(self):
        for path in (
            "/o/applications/",
            "/o/applications/register/",
            "/o/register/",
            "/o/introspect/",
            "/o/device-authorization/",
            "/o/.well-known/openid-configuration",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)


class ChatGPTOAuthClientCommandTests(TestCase):
    def test_command_creates_public_authorization_code_client(self):
        output = StringIO()

        call_command(
            "configure_chatgpt_oauth",
            callback_url=CHATGPT_CALLBACK_URL,
            client_id=CHATGPT_CLIENT_ID,
            stdout=output,
        )

        application_model = get_application_model()
        application = application_model.objects.get(client_id=CHATGPT_CLIENT_ID)
        self.assertEqual(application.redirect_uris, CHATGPT_CALLBACK_URL)
        self.assertEqual(
            application.client_type,
            application_model.CLIENT_PUBLIC,
        )
        self.assertEqual(
            application.authorization_grant_type,
            application_model.GRANT_AUTHORIZATION_CODE,
        )
        self.assertEqual(application.client_secret, "")
        self.assertFalse(application.hash_client_secret)
        self.assertFalse(application.skip_authorization)
        self.assertEqual(application.algorithm, application_model.NO_ALGORITHM)
        self.assertEqual(
            application.registration_source,
            application_model.RegistrationSource.MANUAL,
        )
        self.assertIn(CHATGPT_CLIENT_ID, output.getvalue())
        self.assertNotIn("secret", output.getvalue().lower())

    def test_command_is_idempotent_and_updates_only_exact_callback(self):
        first_callback = (
            "https://chatgpt.com/connector/oauth/first-callback"
        )
        second_callback = (
            "https://chatgpt.com/connector/oauth/second-callback"
        )
        call_command(
            "configure_chatgpt_oauth",
            callback_url=first_callback,
            client_id=CHATGPT_CLIENT_ID,
            stdout=StringIO(),
        )
        call_command(
            "configure_chatgpt_oauth",
            callback_url=second_callback,
            client_id=CHATGPT_CLIENT_ID,
            stdout=StringIO(),
        )

        application_model = get_application_model()
        self.assertEqual(
            application_model.objects.filter(
                client_id=CHATGPT_CLIENT_ID
            ).count(),
            1,
        )
        application = application_model.objects.get(client_id=CHATGPT_CLIENT_ID)
        self.assertEqual(application.redirect_uris, second_callback)

    def test_command_rejects_non_chatgpt_or_inexact_callbacks(self):
        invalid_callbacks = (
            "http://chatgpt.com/connector/oauth/callback-id",
            "https://chatgpt.com.evil.example/connector/oauth/callback-id",
            "https://chatgpt.com:443/connector/oauth/callback-id",
            "https://chatgpt.com/connector/oauth/callback-id/",
            "https://chatgpt.com/connector/oauth/callback-id?token=leak",
            "https://chatgpt.com/connector/oauth/callback%2Fid",
        )

        for callback_url in invalid_callbacks:
            with self.subTest(callback_url=callback_url):
                with self.assertRaises(CommandError):
                    call_command(
                        "configure_chatgpt_oauth",
                        callback_url=callback_url,
                        client_id=CHATGPT_CLIENT_ID,
                        stdout=StringIO(),
                    )

        self.assertFalse(
            get_application_model().objects.filter(
                client_id=CHATGPT_CLIENT_ID
            ).exists()
        )

    def test_command_refuses_to_replace_dynamically_registered_client(self):
        application_model = get_application_model()
        application_model.objects.create(
            client_id=CHATGPT_CLIENT_ID,
            redirect_uris=CHATGPT_CALLBACK_URL,
            client_type=application_model.CLIENT_PUBLIC,
            authorization_grant_type=(
                application_model.GRANT_AUTHORIZATION_CODE
            ),
            client_secret="",
            hash_client_secret=False,
            registration_source=application_model.RegistrationSource.DCR,
        )

        with self.assertRaisesMessage(
            CommandError,
            "was not manually registered",
        ):
            call_command(
                "configure_chatgpt_oauth",
                callback_url=CHATGPT_CALLBACK_URL,
                client_id=CHATGPT_CLIENT_ID,
                stdout=StringIO(),
            )

    @override_settings(CHATGPT_OAUTH_CALLBACK_URL="")
    def test_discovery_only_removes_predefined_manual_client(self):
        call_command(
            "configure_chatgpt_oauth",
            callback_url=CHATGPT_CALLBACK_URL,
            client_id=CHATGPT_CLIENT_ID,
            stdout=StringIO(),
        )

        call_command(
            "configure_chatgpt_oauth",
            discovery_only=True,
            client_id=CHATGPT_CLIENT_ID,
            stdout=StringIO(),
        )

        self.assertFalse(
            get_application_model().objects.filter(
                client_id=CHATGPT_CLIENT_ID
            ).exists()
        )

    def test_discovery_only_requires_the_callback_setting_to_be_empty(self):
        with override_settings(
            CHATGPT_OAUTH_CALLBACK_URL=CHATGPT_CALLBACK_URL
        ):
            with self.assertRaisesMessage(
                CommandError,
                "Clear MEAD_TRACKER_CHATGPT_CALLBACK_URL",
            ):
                call_command(
                    "configure_chatgpt_oauth",
                    discovery_only=True,
                    client_id=CHATGPT_CLIENT_ID,
                    stdout=StringIO(),
                )


class OAuthAuthorizationCodeTests(ChatGPTURLSettingMixin, TestCase):
    password = "Oak-Barrel-Honey-42!"

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="oauth-batch-owner",
            password=cls.password,
        )

    def setUp(self):
        call_command(
            "configure_chatgpt_oauth",
            callback_url=CHATGPT_CALLBACK_URL,
            client_id=CHATGPT_CLIENT_ID,
            stdout=StringIO(),
        )
        self.client.force_login(self.user)

    def _authorize(self, code_verifier: str) -> str:
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode("ascii")).digest()
        ).rstrip(b"=").decode("ascii")
        authorization_data = {
            "client_id": CHATGPT_CLIENT_ID,
            "redirect_uri": CHATGPT_CALLBACK_URL,
            "response_type": "code",
            "scope": "batches:read",
            "state": "oauth-test-state",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "resource": settings.MCP_PUBLIC_URL,
        }
        authorize_url = reverse("oauth2_provider:authorize")
        consent_response = self.client.get(
            authorize_url,
            authorization_data,
        )
        self.assertEqual(consent_response.status_code, 200)

        authorization_data["allow"] = "on"
        response = self.client.post(authorize_url, authorization_data)
        self.assertEqual(response.status_code, 302)
        callback = urlparse(response.headers["Location"])
        self.assertEqual(
            f"{callback.scheme}://{callback.netloc}{callback.path}",
            CHATGPT_CALLBACK_URL,
        )
        query = parse_qs(callback.query)
        self.assertEqual(query["state"], ["oauth-test-state"])
        self.assertEqual(query["iss"], [settings.OAUTH_ISSUER_URL])
        return query["code"][0]

    def test_public_client_exchange_and_refresh_stay_resource_bound(self):
        code_verifier = "correct-verifier-" + ("a" * 48)
        authorization_code = self._authorize(code_verifier)

        response = self.client.post(
            reverse("oauth2_provider:token"),
            {
                "grant_type": "authorization_code",
                "client_id": CHATGPT_CLIENT_ID,
                "redirect_uri": CHATGPT_CALLBACK_URL,
                "code": authorization_code,
                "code_verifier": code_verifier,
                "resource": settings.MCP_PUBLIC_URL,
            },
        )

        self.assertEqual(response.status_code, 200, response.content)
        token_response = json.loads(response.content)
        self.assertEqual(token_response["token_type"], "Bearer")
        self.assertEqual(token_response["scope"], "batches:read")
        self.assertIn("access_token", token_response)
        self.assertIn("refresh_token", token_response)

        access_token = get_access_token_model().objects.get(user=self.user)
        self.assertEqual(access_token.scope, "batches:read")
        self.assertEqual(access_token.resource, [settings.MCP_PUBLIC_URL])
        self.assertEqual(access_token.token, "")
        self.assertTrue(access_token.token_checksum)

        refresh_response = self.client.post(
            reverse("oauth2_provider:token"),
            {
                "grant_type": "refresh_token",
                "client_id": CHATGPT_CLIENT_ID,
                "refresh_token": token_response["refresh_token"],
            },
        )

        self.assertEqual(
            refresh_response.status_code,
            200,
            refresh_response.content,
        )
        refreshed_response = refresh_response.json()
        self.assertIn("access_token", refreshed_response)
        self.assertIn("refresh_token", refreshed_response)
        refreshed_access_token = (
            get_access_token_model()
            .objects.filter(user=self.user)
            .latest("created")
        )
        self.assertEqual(
            refreshed_access_token.resource,
            [settings.MCP_PUBLIC_URL],
        )
        self.assertEqual(refreshed_access_token.scope, "batches:read")
        self.assertEqual(refreshed_access_token.token, "")
        self.assertTrue(refreshed_access_token.token_checksum)

        access_count = get_access_token_model().objects.filter(
            user=self.user
        ).count()
        refresh_count = get_refresh_token_model().objects.filter(
            user=self.user,
            revoked__isnull=True,
        ).count()
        call_command(
            "configure_chatgpt_oauth",
            callback_url=CHATGPT_CALLBACK_URL,
            client_id=CHATGPT_CLIENT_ID,
            stdout=StringIO(),
        )
        self.assertEqual(
            get_access_token_model().objects.filter(user=self.user).count(),
            access_count,
        )
        self.assertEqual(
            get_refresh_token_model()
            .objects.filter(user=self.user, revoked__isnull=True)
            .count(),
            refresh_count,
        )

        call_command(
            "configure_chatgpt_oauth",
            callback_url=CHATGPT_CALLBACK_URL,
            client_id=CHATGPT_CLIENT_ID,
            revoke_existing_authorizations=True,
            stdout=StringIO(),
        )
        self.assertFalse(
            get_access_token_model().objects.filter(user=self.user).exists()
        )
        self.assertFalse(
            get_refresh_token_model().objects.filter(user=self.user).exists()
        )

        replacement_verifier = "replacement-verifier-" + ("r" * 48)
        replacement_code = self._authorize(replacement_verifier)
        replacement_response = self.client.post(
            reverse("oauth2_provider:token"),
            {
                "grant_type": "authorization_code",
                "client_id": CHATGPT_CLIENT_ID,
                "redirect_uri": CHATGPT_CALLBACK_URL,
                "code": replacement_code,
                "code_verifier": replacement_verifier,
                "resource": settings.MCP_PUBLIC_URL,
            },
        )
        self.assertEqual(
            replacement_response.status_code,
            200,
            replacement_response.content,
        )

        call_command(
            "configure_chatgpt_oauth",
            callback_url=(
                "https://chatgpt.com/connector/oauth/rotated-callback"
            ),
            client_id=CHATGPT_CLIENT_ID,
            stdout=StringIO(),
        )
        self.assertFalse(
            get_access_token_model().objects.filter(user=self.user).exists()
        )
        self.assertFalse(
            get_refresh_token_model().objects.filter(user=self.user).exists()
        )

    def test_wrong_pkce_verifier_is_rejected_without_issuing_token(self):
        authorization_code = self._authorize(
            "correct-verifier-" + ("b" * 48)
        )

        response = self.client.post(
            reverse("oauth2_provider:token"),
            {
                "grant_type": "authorization_code",
                "client_id": CHATGPT_CLIENT_ID,
                "redirect_uri": CHATGPT_CALLBACK_URL,
                "code": authorization_code,
                "code_verifier": "wrong-verifier-" + ("c" * 48),
                "resource": settings.MCP_PUBLIC_URL,
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "invalid_grant")
        self.assertFalse(
            get_access_token_model().objects.filter(user=self.user).exists()
        )

    def test_authorization_rejects_any_callback_not_predefined_exactly(self):
        code_verifier = "callback-test-verifier-" + ("d" * 48)
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode("ascii")).digest()
        ).rstrip(b"=").decode("ascii")

        response = self.client.get(
            reverse("oauth2_provider:authorize"),
            {
                "client_id": CHATGPT_CLIENT_ID,
                "redirect_uri": f"{CHATGPT_CALLBACK_URL}/extra",
                "response_type": "code",
                "scope": "batches:read",
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
                "resource": settings.MCP_PUBLIC_URL,
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertNotIn("Location", response.headers)
