from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from django.test import SimpleTestCase


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SCRIPT = PROJECT_ROOT / "deploy" / "mead-tracker.sh"


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
