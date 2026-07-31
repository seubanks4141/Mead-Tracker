from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from mead_tracker import settings as project_settings


class ChatGPTPublicSecuritySettingsTests(SimpleTestCase):
    def validate(self, **overrides):
        configuration = {
            "CHATGPT_ENABLED": True,
            "DEBUG": False,
            "SESSION_COOKIE_SECURE": True,
            "CSRF_COOKIE_SECURE": True,
            "ALLOWED_HOSTS": ["mead.example.test"],
            "PUBLIC_BASE_URL": "https://mead.example.test",
        }
        configuration.update(overrides)
        with patch.multiple(project_settings, **configuration):
            project_settings._validate_chatgpt_public_security()

    def test_safe_public_configuration_is_accepted(self):
        self.validate()

    def test_disabled_integration_keeps_local_development_defaults(self):
        self.validate(
            CHATGPT_ENABLED=False,
            DEBUG=True,
            SESSION_COOKIE_SECURE=False,
            CSRF_COOKIE_SECURE=False,
            ALLOWED_HOSTS=["*"],
            PUBLIC_BASE_URL="http://127.0.0.1:8000",
        )

    def test_debug_mode_is_rejected_when_chatgpt_is_enabled(self):
        with self.assertRaisesRegex(
            ImproperlyConfigured,
            "MEAD_TRACKER_DEBUG must be false",
        ):
            self.validate(DEBUG=True)

    def test_insecure_session_cookies_are_rejected(self):
        with self.assertRaisesRegex(
            ImproperlyConfigured,
            "MEAD_TRACKER_SECURE_COOKIES must be true",
        ):
            self.validate(
                SESSION_COOKIE_SECURE=False,
                CSRF_COOKIE_SECURE=False,
            )

    def test_wildcard_allowed_host_is_rejected(self):
        with self.assertRaisesRegex(
            ImproperlyConfigured,
            "MEAD_TRACKER_ALLOWED_HOSTS must not contain",
        ):
            self.validate(ALLOWED_HOSTS=["*"])

    def test_public_base_url_must_be_https(self):
        with self.assertRaisesRegex(
            ImproperlyConfigured,
            "MEAD_TRACKER_PUBLIC_BASE_URL must be the public HTTPS origin",
        ):
            self.validate(PUBLIC_BASE_URL="http://mead.example.test")
