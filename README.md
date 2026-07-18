# azure-secret-watch

[English](README.md) | [中文](README.zh-CN.md)

Microsoft Entra ID (Azure AD) does **not** send any native warning before an
App Registration's client secret or certificate expires — once a credential
expires, the application simply fails to authenticate, and the first sign of
trouble is usually a production outage.

**azure-secret-watch** uses read-only Microsoft Graph permissions to scan
every App Registration in your tenant and notify you — by Email, Microsoft
Teams, or a custom webhook — before a secret or certificate expires, with
enough lead time to rotate it.

## Features

- 🔍 Scans every App Registration's client secrets and certificates for
  upcoming expiry
- 📬 Multiple notification channels: Email / Microsoft Teams / custom webhook
- ⏰ Configurable, tiered warning thresholds (e.g. 30 / 14 / 7 / 1 days before
  expiry)
- 🔁 Deduplicated alerts — each threshold is only sent once per credential, and
  already-expired credentials get a periodic reminder until rotated
- 🔒 Strictly read-only against Microsoft Graph (`Application.Read.All`); it
  never reads, logs, or transmits actual secret values — Graph itself never
  returns them after creation
- 🖥️ Built-in web dashboard: sortable/paginated credential table, search and
  status filters, CSV export, scan history, light/dark theme, and a manual
  "scan now" button
- 🐳 Ships as a single Docker Compose service; no separate always-on server or
  Logic App required

## How it works

1. Authenticates to Microsoft Graph as its own App Registration (client
   secret or certificate).
2. Calls `GET /applications` (paginated) and reads each app's
   `passwordCredentials` and `keyCredentials` metadata — key id, description,
   start/end dates. Never reads the secret value itself.
3. For each credential, computes days-until-expiry and checks it against your
   configured warning thresholds.
4. Tracks which (credential, threshold) pairs have already been notified in a
   small local SQLite file, so you get one alert per threshold crossed instead
   of a repeat every run.
5. Sends a batched notification per enabled channel listing everything that
   needs attention, with a direct link to the credential's blade in the Azure
   portal.

## Quick start (Docker Compose)

### 1. Create an App Registration for the watcher

The watcher needs its own identity in Entra ID with **read-only** Graph
permissions:

1. In the Azure Portal, go to **Microsoft Entra ID → App registrations → New
   registration**. Any name/account type is fine (single tenant is typical).
2. Under **API permissions → Add a permission → Microsoft Graph → Application
   permissions**, add:
   - `Application.Read.All` (required)
   - `User.Read.All` (only if you plan to enable `NOTIFY_OWNERS`, to resolve
     owner emails)
3. Click **Grant admin consent** for these permissions — application
   permissions don't work without it.
4. Under **Certificates & secrets**, create either:
   - **Option A — Client secret** (simplest): note the value immediately, you
     won't be able to see it again.
   - **Option B — Certificate** (recommended for long-running deployments,
     since it avoids the watcher itself depending on a secret that can
     expire): upload a certificate's public key and keep the private key
     `.pem` for the container.
5. Note the **Application (client) ID** and **Directory (tenant) ID** from the
   app's Overview page.

### 2. Configure and run

```bash
git clone <this repo>
cd azure-secret-watch
cp .env.example .env
# edit .env: fill in AZURE_TENANT_ID / AZURE_CLIENT_ID / AZURE_CLIENT_SECRET
# (or AZURE_CLIENT_CERTIFICATE_PATH), and enable at least one notification
# channel (email / Teams / webhook).

docker compose up -d
```

The container runs continuously and scans on the cron schedule set by
`CRON_SCHEDULE` (default: daily at 08:00 UTC), plus once immediately on
startup (`RUN_SCAN_ON_STARTUP=true` by default). State (dedupe database and
last run status) is persisted under `./data`.

Open **http://localhost:8080** for the web dashboard — a table of every
scanned credential with its expiry status, search/filter, and a "scan now"
button. It only ever displays credential metadata (names, key ids, expiry
dates), never secret values.

To do a one-off test run without waiting for the schedule:

```bash
docker compose run --rm azure-secret-watch python -m azure_secret_watch --once
```

Consider setting `DRY_RUN=true` for your first run — it logs everything it
would have sent without actually notifying anyone or updating dedupe state.

### Running on an external schedule instead

If you'd rather trigger scans from host cron, systemd, or a Kubernetes
CronJob, use `docker-compose.once.yml` (sets `RUN_MODE=once`, so the container
scans once and exits):

```bash
docker compose -f docker-compose.once.yml run --rm azure-secret-watch
```

## Configuration

All configuration is via environment variables — see
[`.env.example`](.env.example) for the full, documented list, including:

| Area | Key variables |
| --- | --- |
| Azure auth | `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET` or `AZURE_CLIENT_CERTIFICATE_PATH` |
| Scan behavior | `WARNING_THRESHOLDS_DAYS`, `INCLUDE_SECRETS`, `INCLUDE_CERTIFICATES`, `NOTIFY_OWNERS`, `EXPIRED_REMINDER_INTERVAL_DAYS` |
| Scheduling | `RUN_MODE` (`loop`/`once`), `CRON_SCHEDULE` |
| Email | `NOTIFY_EMAIL_ENABLED`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `EMAIL_FROM`, `EMAIL_TO` |
| Teams | `NOTIFY_TEAMS_ENABLED`, `TEAMS_WEBHOOK_URL`, `TEAMS_WEBHOOK_FORMAT` |
| Custom webhook | `NOTIFY_WEBHOOK_ENABLED`, `CUSTOM_WEBHOOK_URL`, `CUSTOM_WEBHOOK_METHOD`, `CUSTOM_WEBHOOK_HEADERS` |
| Web dashboard | `WEB_UI_ENABLED`, `WEB_UI_PORT`, `WEB_UI_USERNAME`, `WEB_UI_PASSWORD` |
| Safety | `DRY_RUN`, `LOG_LEVEL` |

### Web dashboard

Enabled by default at `http://<host>:8080` whenever `RUN_MODE=loop`. It reads
from a local JSON cache written after each scan — no extra Graph calls, and
no impact on the notification/dedupe logic.

**Set `WEB_UI_USERNAME` and `WEB_UI_PASSWORD` before exposing the port beyond
your own machine.** Left blank, the dashboard has no authentication at all —
fine for `localhost`-only access, not fine if the port is reachable from your
network or the internet. Either set both variables (enables HTTP Basic Auth)
or put the port behind your own reverse proxy / VPN / firewall rule. The
dashboard never shows secret or certificate values regardless — only names,
key ids, and expiry dates — but it does reveal your App Registration
inventory, which is still worth keeping access-controlled.

#### Owners column

Set `NOTIFY_OWNERS=true` to add an "Owners" column to the dashboard, backed
by Microsoft Graph's `/applications/{id}/owners` — Entra ID's real ownership
data, not something this tool invents or lets you assign. It requires the
`User.Read.All` Graph permission (in addition to `Application.Read.All`) with
admin consent granted; without it, owner lookups fail silently (logged, not
fatal) and every app shows no owner. Apps with genuinely no owner assigned in
Entra ID — common for service accounts created via CI/CD or Terraform — show
up as "no owner" and are called out in a summary chip, since that's usually
worth fixing at the source (Entra ID → App registrations → the app → Owners)
rather than worked around.

Set `WEB_UI_ENABLED=false` to disable it entirely.

#### Monitoring page

The **Monitoring** page in the sidebar lets you toggle each notification
channel on/off, edit the email recipient list, and adjust the warning
thresholds — all without editing `.env` or redeploying the container. A
channel can only be turned on if its underlying connection details (SMTP
host, Teams/webhook URL) are already set via the environment; the page never
displays those URLs, since they often carry an embedded token. Changes are
saved to `SETTINGS_FILE_PATH` (default `/data/settings.json`) and take effect
immediately, and are re-applied on top of your `.env` values the next time
the container starts.

### Microsoft Teams webhook setup

In the target Teams channel: **⋯ → Workflows → "Post to a channel when a
webhook request is received"** (this replaced the legacy Office 365 Connector
webhooks, which Microsoft has deprecated). Copy the generated URL into
`TEAMS_WEBHOOK_URL`. If you're still using an old Office 365 Connector
webhook, set `TEAMS_WEBHOOK_FORMAT=messagecard` instead.

### Custom webhook payload

```json
{
  "summary": {"total": 2, "expired": 1, "expiring_soon": 1},
  "alerts": [
    {
      "severity": "expired",
      "app_display_name": "Billing Service",
      "app_id": "00000000-0000-0000-0000-000000000000",
      "credential_type": "secret",
      "days_until_expiry": -3,
      "portal_url": "https://portal.azure.com/...",
      "owners": []
    }
  ]
}
```

Wire this up to Slack, PagerDuty, ntfy, or any system of your own — set
`CUSTOM_WEBHOOK_HEADERS` for bearer-token/API-key auth if the receiving side
needs it.

## Data & privacy

The only state the watcher persists (under `/data`) is:

- `state.db` — a SQLite file mapping `(credential key id, warning threshold)`
  to the timestamp it was last notified, purely to avoid duplicate alerts.
- `last_run.json` — the outcome of the most recent scan, used by the Docker
  healthcheck.
- `inventory.json` — the full credential list and expiry status shown on the
  web dashboard.
- `settings.json` — the notification/threshold overrides made from the
  Monitoring page (see above); absent until you save a change there.

Neither file, nor any log line, ever contains an actual secret value or
certificate private key.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for running tests, lint, and building
the image locally.

## License

[MIT](LICENSE)
