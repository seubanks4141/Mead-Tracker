from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings

from run_mcp_server import load_application


CALLBACK_URL = "https://chatgpt.com/connector/oauth/runtime-startup-test"
CLIENT_ID = "mead-tracker-runtime-test"


@override_settings(
    CHATGPT_ENABLED=True,
    CHATGPT_OAUTH_CLIENT_ID=CLIENT_ID,
    CHATGPT_OAUTH_CALLBACK_URL=CALLBACK_URL,
    MCP_PUBLIC_URL="https://mead.example.test/mcp",
    OAUTH_ISSUER_URL="https://mead.example.test/o",
    MCP_HOST="127.0.0.1",
)
class MCPRuntimeStartupTests(TestCase):
    def test_startup_fails_fast_when_oauth_client_is_missing(self):
        with self.assertRaisesRegex(RuntimeError, "OAuth client is missing"):
            load_application()

    def test_startup_accepts_the_configured_public_client(self):
        call_command(
            "configure_chatgpt_oauth",
            callback_url=CALLBACK_URL,
            client_id=CLIENT_ID,
            stdout=StringIO(),
        )

        application = load_application()

        paths = {route.path for route in application.routes}
        self.assertIn("/mcp", paths)
        self.assertIn("/.well-known/oauth-protected-resource/mcp", paths)


@override_settings(
    CHATGPT_ENABLED=True,
    CHATGPT_OAUTH_CLIENT_ID=CLIENT_ID,
    CHATGPT_OAUTH_CALLBACK_URL="",
    MCP_PUBLIC_URL="https://mead.example.test/mcp",
    OAUTH_ISSUER_URL="https://mead.example.test/o",
    MCP_HOST="127.0.0.1",
)
class MCPRuntimeBootstrapTests(TestCase):
    def test_startup_allows_discovery_before_chatgpt_assigns_callback(self):
        application = load_application()

        paths = {route.path for route in application.routes}
        self.assertIn("/mcp", paths)
        self.assertIn("/.well-known/oauth-protected-resource/mcp", paths)

    def test_startup_rejects_stale_client_in_discovery_only_mode(self):
        call_command(
            "configure_chatgpt_oauth",
            callback_url=CALLBACK_URL,
            client_id=CLIENT_ID,
            stdout=StringIO(),
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "Discovery-only startup requires",
        ):
            load_application()
