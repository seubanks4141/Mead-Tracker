"""Standard-library tests for the separate loopback MCP process."""

from __future__ import annotations

import contextlib
import io
import unittest

import run_mcp_server


class MCPRuntimeConfigurationTests(unittest.TestCase):
    def test_defaults_are_local_only(self) -> None:
        args = run_mcp_server.parse_args([], {})

        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.port, 8766)

    def test_environment_configures_host_and_port(self) -> None:
        args = run_mcp_server.parse_args(
            [],
            {
                "MEAD_TRACKER_MCP_HOST": "localhost",
                "MEAD_TRACKER_MCP_PORT": "9001",
            },
        )

        self.assertEqual(args.host, "localhost")
        self.assertEqual(args.port, 9001)

    def test_main_passes_loopback_values_to_uvicorn(self) -> None:
        calls: list[tuple[object, dict[str, object]]] = []
        fake_application = object()

        def fake_serve(application: object, **kwargs: object) -> None:
            calls.append((application, kwargs))

        with contextlib.redirect_stdout(io.StringIO()):
            exit_code = run_mcp_server.main(
                [],
                environ={
                    "MEAD_TRACKER_MCP_HOST": "127.0.0.1",
                    "MEAD_TRACKER_MCP_PORT": "8766",
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
                    {
                        "host": "127.0.0.1",
                        "port": 8766,
                        "log_level": "info",
                        "proxy_headers": False,
                    },
                )
            ],
        )

    def test_public_bind_is_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "must bind to loopback"):
            run_mcp_server.main(
                ["--host", "0.0.0.0"],
                environ={},
                application=object(),
                serve=lambda *args, **kwargs: None,
            )


if __name__ == "__main__":
    unittest.main()
