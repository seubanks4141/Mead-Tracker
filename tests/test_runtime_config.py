"""Tests for the portable server configuration.

These use the standard library so the validation can be checked independently
of Django's test runner.
"""

from __future__ import annotations

import contextlib
import io
import unittest

import run_server


class RuntimeConfigurationTests(unittest.TestCase):
    def test_defaults_are_local_only(self) -> None:
        args = run_server.parse_args([], {})

        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.port, 8000)

    def test_environment_configures_host_and_port(self) -> None:
        args = run_server.parse_args(
            [],
            {
                "MEAD_TRACKER_HOST": "0.0.0.0",
                "MEAD_TRACKER_PORT": "8765",
            },
        )

        self.assertEqual(args.host, "0.0.0.0")
        self.assertEqual(args.port, 8765)

    def test_cli_takes_precedence_over_environment(self) -> None:
        args = run_server.parse_args(
            ["--host", "localhost", "--port", "9000"],
            {
                "MEAD_TRACKER_HOST": "0.0.0.0",
                "MEAD_TRACKER_PORT": "8765",
            },
        )

        self.assertEqual(args.host, "localhost")
        self.assertEqual(args.port, 9000)

    def test_invalid_environment_port_has_clear_error(self) -> None:
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors), self.assertRaises(SystemExit):
            run_server.parse_args([], {"MEAD_TRACKER_PORT": "eight thousand"})

        self.assertIn("port must be a whole number", errors.getvalue())

    def test_port_range_is_checked(self) -> None:
        for port in ("0", "65536", "-1"):
            with self.subTest(port=port), contextlib.redirect_stderr(
                io.StringIO()
            ), self.assertRaises(SystemExit):
                run_server.parse_args(["--port", port], {})

    def test_urls_are_rejected_as_bind_hosts(self) -> None:
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors), self.assertRaises(SystemExit):
            run_server.parse_args(["--host", "http://localhost"], {})

        self.assertIn("hostname or IP address", errors.getvalue())

    def test_port_must_not_be_embedded_in_host(self) -> None:
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors), self.assertRaises(SystemExit):
            run_server.parse_args(["--host", "localhost:8765"], {})

        self.assertIn("put the port in --port", errors.getvalue())

    def test_bracketed_ipv6_host_is_normalized(self) -> None:
        args = run_server.parse_args(["--host", "[::1]"], {})

        self.assertEqual(args.host, "::1")

    def test_main_passes_resolved_values_to_waitress(self) -> None:
        calls: list[tuple[object, dict[str, object]]] = []
        fake_application = object()

        def fake_serve(application: object, **kwargs: object) -> None:
            calls.append((application, kwargs))

        with contextlib.redirect_stdout(io.StringIO()):
            exit_code = run_server.main(
                [],
                environ={
                    "MEAD_TRACKER_HOST": "127.0.0.1",
                    "MEAD_TRACKER_PORT": "8123",
                },
                application=fake_application,
                serve=fake_serve,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            calls,
            [
                (
                    fake_application,
                    {"host": "127.0.0.1", "port": 8123, "threads": 4},
                )
            ],
        )

    def test_trusted_proxy_configuration_reaches_waitress(self) -> None:
        calls: list[dict[str, object]] = []

        def fake_serve(application: object, **kwargs: object) -> None:
            calls.append(kwargs)

        with contextlib.redirect_stdout(io.StringIO()):
            exit_code = run_server.main(
                [],
                environ={
                    "MEAD_TRACKER_HOST": "127.0.0.1",
                    "MEAD_TRACKER_PORT": "8123",
                    "MEAD_TRACKER_TRUST_PROXY_HEADERS": "true",
                    "MEAD_TRACKER_TRUSTED_PROXY": "127.0.0.1",
                },
                application=object(),
                serve=fake_serve,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(calls[0]["trusted_proxy"], "127.0.0.1")
        self.assertEqual(
            calls[0]["trusted_proxy_headers"],
            {"x-forwarded-host", "x-forwarded-proto"},
        )

    def test_public_phone_url_is_shown_at_startup(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = run_server.main(
                [],
                environ={
                    "MEAD_TRACKER_HOST": "0.0.0.0",
                    "MEAD_TRACKER_PORT": "8000",
                    "MEAD_TRACKER_PUBLIC_BASE_URL": "http://192.0.2.42:8000/",
                },
                application=object(),
                serve=lambda *args, **kwargs: None,
            )

        self.assertEqual(exit_code, 0)
        self.assertIn(
            "Phone and QR address: http://192.0.2.42:8000",
            output.getvalue(),
        )

    def test_invalid_boolean_configuration_is_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "must be one of"):
            run_server.environment_flag(
                {"MEAD_TRACKER_TRUST_PROXY_HEADERS": "ture"},
                "MEAD_TRACKER_TRUST_PROXY_HEADERS",
            )

    def test_public_bind_cannot_trust_every_proxy(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(
            RuntimeError,
            "Refusing to trust proxy headers",
        ):
            run_server.main(
                [],
                environ={
                    "MEAD_TRACKER_HOST": "0.0.0.0",
                    "MEAD_TRACKER_PORT": "8123",
                    "MEAD_TRACKER_TRUST_PROXY_HEADERS": "true",
                    "MEAD_TRACKER_TRUSTED_PROXY": "*",
                },
                application=object(),
                serve=lambda *args, **kwargs: None,
            )


if __name__ == "__main__":
    unittest.main()
