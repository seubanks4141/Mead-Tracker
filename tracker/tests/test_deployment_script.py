from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from django.test import SimpleTestCase


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SCRIPT = PROJECT_ROOT / "deploy" / "mead-tracker.sh"
MCP_SERVICE = PROJECT_ROOT / "deploy" / "mead-tracker-mcp.service"
LOCAL_ENV_EXAMPLE = PROJECT_ROOT / ".env.example"
DEPLOY_ENV_EXAMPLE = PROJECT_ROOT / "deploy" / "mead-tracker.env.example"


class DeploymentScriptTests(SimpleTestCase):
    def test_update_keeps_deployment_safety_guards(self):
        script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
        update = script.split("update_application() {", 1)[1]

        self.assertIn('systemctl start "$BACKUP_SERVICE"', script)
        self.assertIn("merge-base", update)
        self.assertIn("--is-ancestor", update)
        self.assertIn("--ff-only", update)
        self.assertIn("status --porcelain", script)
        self.assertIn('is-enabled --quiet "$BACKUP_TIMER"', update)
        self.assertIn('INSTALL_MARKER="$ENV_DIR/.setup-complete"', script)
        self.assertIn('systemctl enable "$BACKUP_TIMER"', update)
        self.assertIn('systemctl is-active --quiet "$SERVICE_NAME"', script)
        self.assertIn('[ "$health_body" = \'{\"status\": \"ok\"}\' ]', script)
        self.assertIn("The deployment checkout must be owned by root", script)
        self.assertIn('LOCK_FILE="/run/mead-tracker-deploy.lock"', script)
        self.assertIn('chmod 0600 "$LOCK_FILE"', script)
        self.assertEqual(
            script.count("validate_fixed_paths\n        acquire_lock"),
            2,
        )
        self.assertNotIn("git reset", script)
        self.assertNotIn("git clean", script)
        self.assertNotIn("git stash", script)

    def test_setup_preserves_existing_configuration_and_data(self):
        script = DEPLOY_SCRIPT.read_text(encoding="utf-8")

        self.assertIn('[ -f "$ENV_FILE" ]', script)
        self.assertIn('[ ! -f "$STATE_DIR/mead-tracker.sqlite3" ]', script)
        self.assertIn(
            "Resuming an incomplete setup and preserving",
            script,
        )
        self.assertNotIn("rm -rf", script)

    def test_mcp_unit_is_loopback_only_and_shares_application_state(self):
        unit = MCP_SERVICE.read_text(encoding="utf-8")

        self.assertIn("User=meadtracker", unit)
        self.assertIn("Group=meadtracker", unit)
        self.assertIn("WorkingDirectory=/opt/mead-tracker", unit)
        self.assertIn(
            "EnvironmentFile=/etc/mead-tracker/mead-tracker.env",
            unit,
        )
        self.assertIn("StateDirectory=mead-tracker", unit)
        self.assertIn("Requires=mead-tracker.service", unit)
        self.assertIn("PartOf=mead-tracker.service", unit)
        self.assertIn(
            "ExecStart=/opt/mead-tracker/.venv/bin/python "
            "/opt/mead-tracker/run_mcp_server.py",
            unit,
        )
        self.assertNotIn("--host 0.0.0.0", unit)
        self.assertNotIn("--port 8766", unit)
        self.assertIn("NoNewPrivileges=true", unit)
        self.assertIn("ProtectSystem=full", unit)

    def test_deploy_reconciles_mcp_service_only_when_configured(self):
        script = DEPLOY_SCRIPT.read_text(encoding="utf-8")

        self.assertIn('MCP_SERVICE="mead-tracker-mcp.service"', script)
        self.assertIn(
            '"$APP_DIR/deploy/mead-tracker-mcp.service"',
            script,
        )
        self.assertIn(
            'MEAD_TRACKER_CHATGPT_ENABLED:-false',
            script,
        )
        self.assertIn(
            '[ "$chatgpt_enabled" = "true" ] || return',
            script,
        )
        self.assertIn(
            "from run_mcp_server import load_application; load_application()",
            script,
        )
        self.assertIn(
            "manage.py configure_chatgpt_oauth",
            script,
        )
        self.assertIn(
            'MEAD_TRACKER_CHATGPT_CALLBACK_URL:-',
            script,
        )
        self.assertIn(
            "starting MCP in discovery-only bootstrap mode",
            script,
        )
        self.assertIn(
            "manage.py configure_chatgpt_oauth \\\n"
            "            --discovery-only",
            script,
        )
        self.assertIn('systemctl enable "$MCP_SERVICE"', script)
        self.assertIn('systemctl restart "$MCP_SERVICE"', script)
        self.assertIn('systemctl stop "$MCP_SERVICE"', script)
        self.assertIn('systemctl disable "$MCP_SERVICE"', script)
        self.assertIn(
            "/.well-known/oauth-protected-resource{resource_path}",
            script,
        )
        self.assertIn('[ "$mcp_health_status" = "200" ]', script)
        self.assertEqual(script.count("reconcile_mcp_service\n"), 2)
        self.assertEqual(
            script.count("configure_chatgpt_oauth_client\n"),
            2,
        )
        self.assertEqual(script.count("stop_mcp_if_running\n"), 2)
        self.assertIn("MEAD_TRACKER_MCP_HOST=127.0.0.1", script)
        self.assertIn("MEAD_TRACKER_MCP_PORT=8766", script)

    def test_environment_examples_document_public_https_oauth_and_mcp(self):
        for env_path in (LOCAL_ENV_EXAMPLE, DEPLOY_ENV_EXAMPLE):
            with self.subTest(env_path=env_path):
                environment = env_path.read_text(encoding="utf-8")
                self.assertIn(
                    "MEAD_TRACKER_CHATGPT_ENABLED=false",
                    environment,
                )
                self.assertIn(
                    "MEAD_TRACKER_MCP_HOST=127.0.0.1",
                    environment,
                )
                self.assertIn("MEAD_TRACKER_MCP_PORT=8766", environment)
                self.assertIn(
                    "MEAD_TRACKER_MCP_PUBLIC_URL=https://mead.example.com/mcp",
                    environment,
                )
                self.assertIn(
                    "MEAD_TRACKER_OAUTH_ISSUER_URL=https://mead.example.com/o",
                    environment,
                )
                self.assertIn(
                    "MEAD_TRACKER_CHATGPT_CLIENT_ID=mead-tracker-chatgpt",
                    environment,
                )
                self.assertIn(
                    "MEAD_TRACKER_CHATGPT_CALLBACK_URL=\n",
                    environment,
                )
                self.assertNotIn(
                    "MEAD_TRACKER_CHATGPT_CALLBACK_URL=https://",
                    environment,
                )

    def test_script_has_valid_shell_syntax_when_sh_is_available(self):
        shell = shutil.which("sh")
        if shell is None:
            self.skipTest("No POSIX shell is available on this host.")

        result = subprocess.run(
            [shell, "-n", str(DEPLOY_SCRIPT)],
            capture_output=True,
            check=False,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
