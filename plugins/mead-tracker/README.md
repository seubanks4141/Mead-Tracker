# Mead Tracker plugin

This package supplies the ChatGPT batch-advisor workflow in the universal
plugin folder format. The current OAuth callback allowlist is intentionally
ChatGPT-specific. The workflow is read-only and requires live,
owner-authorized data from the Mead Tracker MCP server before it gives
batch-specific advice.

The package is not connected merely because this directory exists. Its live
MCP and ChatGPT IDs are deliberately omitted until a real deployment has
completed OAuth setup. Conversations and model usage remain in the signed-in
user's ChatGPT account and follow that account's limits. Custom read-only MCP
availability depends on the current plan, workspace policy, and rollout;
OpenAI's current connection documentation explicitly covers read/fetch access
for Pro. Mead Tracker does not promise a particular "Max" allowance and does
not need an OpenAI API key. Invoking a batch tool sends its allowlisted
snapshot to ChatGPT so the model can answer.

Until the real URL, connection ID, and dependency wiring are added, installing
this checked-in directory provides the advisory skill only; it cannot call
Mead Tracker tools.

Relevant OpenAI documentation:

- [Connect and test your plugin](https://developers.openai.com/plugins/deploy/connect-chatgpt)
- [Authenticate plugin users](https://developers.openai.com/plugins/build/auth)
- [Developer mode and MCP availability](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt-beta)

## Prerequisites

Complete the production activation runbook in the repository `README.md`
before modifying this package. In particular:

- Django and the MCP process must use the same environment and database.
- `MEAD_TRACKER_CHATGPT_ENABLED=true` must be loaded by both services. The
  batch-page ChatGPT card remains hidden until the real callback is also set
  and Django has restarted.
- The public MCP resource must use HTTPS and route `/mcp` to the loopback MCP
  listener.
- `/o/*`, `/.well-known/oauth-authorization-server/o`, and
  `/.well-known/oauth-protected-resource/mcp` must remain routed to Django.
- OAuth migrations must be applied.
- Django must be in production-safe mode: debug off, Secure session and CSRF
  cookies, an HTTPS public base URL, and no `*` entry in `ALLOWED_HOSTS`.

A private tunnel for the MCP listener alone does not expose the browser OAuth
and root discovery routes used by this implementation. A public HTTPS
web/OAuth origin is still required unless ingress is provided for both sides.

The production environment must include matching real values before
activation:

```dotenv
MEAD_TRACKER_PUBLIC_BASE_URL=https://your-real-host.example
MEAD_TRACKER_SECURE_COOKIES=true
MEAD_TRACKER_TRUST_PROXY_HEADERS=true
MEAD_TRACKER_TRUSTED_PROXY=127.0.0.1
MEAD_TRACKER_CHATGPT_ENABLED=true
MEAD_TRACKER_MCP_HOST=127.0.0.1
MEAD_TRACKER_MCP_PORT=8766
MEAD_TRACKER_MCP_PUBLIC_URL=https://your-real-host.example/mcp
MEAD_TRACKER_OAUTH_ISSUER_URL=https://your-real-host.example/o
MEAD_TRACKER_CHATGPT_CLIENT_ID=mead-tracker-chatgpt
MEAD_TRACKER_CHATGPT_CALLBACK_URL=
```

Apply the OAuth migrations to that same configured database:

```bash
sudo -u meadtracker sh -c \
  'set -a; . /etc/mead-tracker/mead-tracker.env; set +a; cd /opt/mead-tracker && exec .venv/bin/python manage.py migrate --noinput'
```

For an existing production installation, stop both application services and
take a verified database snapshot before changing dependencies or running
migrations.

## Bootstrap the ChatGPT connection

1. Start the Django and MCP services with the public HTTPS resource and issuer
   configured. With the callback still empty, deployment runs
   `configure_chatgpt_oauth --discovery-only`, removing any stale client and
   authorizations before MCP exposes discovery metadata. No batch data is
   accessible.
2. In ChatGPT web, enable **Developer mode**. OpenAI's plugin-testing pages
   currently place it under **Settings → Security and login**; the newer
   account/workspace help also documents **Settings → Apps → Advanced
   Settings** and **Workspace settings → Apps → Create**. Use the location
   visible for the account. Availability and controls differ by plan,
   workspace policy, role, and rollout.
3. In the ChatGPT Plugins area, select the plus button and begin adding a
   custom read-only MCP connection using the exact URL
   `https://your-real-host.example/mcp`.
4. Choose OAuth and enter the predefined public client ID from
   `MEAD_TRACKER_CHATGPT_CLIENT_ID`, normally `mead-tracker-chatgpt`.
5. Copy the exact callback shown by ChatGPT. It must match
   `https://chatgpt.com/connector/oauth/{callback_id}` with no trailing slash.
6. Store that value in `MEAD_TRACKER_CHATGPT_CALLBACK_URL`, then configure the
   database client:

   ```bash
   sudo -u meadtracker sh -c \
     'set -a; . /etc/mead-tracker/mead-tracker.env; set +a; cd /opt/mead-tracker && exec .venv/bin/python manage.py configure_chatgpt_oauth'
   sudo systemctl restart mead-tracker mead-tracker-mcp
   ```

7. Return to ChatGPT, scan or refresh the app, and finish creating it. Confirm
   that only the read-only `list_batches` and `get_batch_context` tools are
   discovered.
8. Authenticate with a Mead Tracker account, approve `batches:read`, and verify
   that one account cannot retrieve another account's batch ID.

Do not proceed to package wiring until the connection works and ChatGPT has
assigned its real technical app ID. Copy that ID from the created connection's
ChatGPT browser URL; it begins with `plugin_asdk_app`.

## Add deployment-specific connection wiring

This source package deliberately does not yet contain `.mcp.json` or
`.app.json`. Add them only after the stable endpoint and assigned IDs above
exist.

1. Add `.mcp.json` with the real streamable HTTP URL:

```json
{
  "mcpServers": {
    "mead-tracker": {
      "type": "http",
      "url": "https://your-real-host.example/mcp"
    }
  }
}
```

2. Add the MCP reference to `.codex-plugin/plugin.json`:

```json
{
  "mcpServers": "./.mcp.json"
}
```

Merge that property into the existing manifest; do not replace its existing
metadata.

3. Copy the technical app ID from the created connection's ChatGPT browser URL.
   It begins with `plugin_asdk_app`; use the complete exact value.
4. Add `.app.json`:

```json
{
  "apps": {
    "mead-tracker": {
      "id": "plugin_asdk_app_REAL_ASSIGNED_ID"
    }
  }
}
```

5. Add the app reference to the existing `.codex-plugin/plugin.json`:

```json
{
  "apps": "./.app.json"
}
```

The package intentionally cannot add `.app.json` or the manifest's `apps`
reference before ChatGPT creates the connection and assigns this real ID.

6. Add the real MCP dependency URL to
   `skills/mead-batch-advisor/agents/openai.yaml`. Preserve the existing
   `interface` block and add:

```yaml
dependencies:
  tools:
    - type: "mcp"
      value: "mead-tracker"
      description: "Read the signed-in user's current Mead Tracker batch data."
      transport: "streamable_http"
      url: "https://your-real-host.example/mcp"
```

Do this only after the deployed dependency exists; never add a guessed
connection name or URL.

The manifest, app reference, skill dependency, OAuth audience, and MCP URL must
all identify the same deployed service. These values are deployment-specific;
do not copy an app ID from another ChatGPT workspace.

7. For repo-local installation, add or merge
   `.agents/plugins/marketplace.json` at the repository root:

```json
{
  "name": "mead-tracker-development",
  "interface": {
    "displayName": "Mead Tracker Development"
  },
  "plugins": [
    {
      "name": "mead-tracker",
      "source": {
        "source": "local",
        "path": "./plugins/mead-tracker"
      },
      "policy": {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL"
      },
      "category": "Productivity"
    }
  ]
}
```

After the live MCP and app wiring above is complete, register this repo-local
marketplace from the repository root, then install the plugin:

```bash
codex plugin marketplace add .
codex plugin add mead-tracker@mead-tracker-development
```

The marketplace registration is required for a repo-local marketplace. After
registering it, the second command can instead be performed by installing
Mead Tracker from the **Mead Tracker Development** source in the Plugins
Directory. Restart the ChatGPT desktop app and test in a new conversation.
Do not create or register the marketplace while this package is still
skill-only, because it would advertise a workflow it cannot complete.

## Connection checks

Before calling the package connected, verify:

```bash
curl -i \
  https://your-real-host.example/.well-known/oauth-authorization-server/o
curl -i \
  https://your-real-host.example/.well-known/oauth-protected-resource/mcp
curl -i https://your-real-host.example/mcp
sudo systemctl status mead-tracker mead-tracker-mcp
sudo journalctl \
  -u mead-tracker \
  -u mead-tracker-mcp \
  -n 200 \
  --no-pager
```

Both discovery URLs should return HTTP 200 JSON. An unauthenticated `/mcp`
request should reach the MCP service and return an authentication response,
not a proxy 404 or 502.

In ChatGPT, test all of the following in a new conversation:

- list the connected account's batches;
- retrieve one selected batch;
- add a new Mead Tracker entry, ask ChatGPT to refresh the batch, and confirm
  the new entry appears;
- try an invalid or foreign batch UUID and confirm no ownership information is
  disclosed; and
- ask for a write and confirm no write tool exists.

If OAuth reports a redirect mismatch, copy the callback again, update
`MEAD_TRACKER_CHATGPT_CALLBACK_URL`, rerun `configure_chatgpt_oauth`, and
restart both web and MCP services.

## Package validation

From the plugin-creator skill directory, run:

```text
python scripts/validate_plugin.py <path-to-repository>/plugins/mead-tracker
```

After changing an already-installed local plugin, use the plugin-creator
cachebuster/reinstall workflow and test it in a new conversation. Public
directory publication is a separate release step; private Developer Mode
testing does not by itself make this package publicly available.
