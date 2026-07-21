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
  status filters, CSV export, a rolling 24-hour scan history, and a manual
  "scan now" button
- 🧪 A "Send test" button per notification channel, so you can confirm Email /
  Teams / webhook actually works before relying on it
- ❓ An in-app **Help** page (the "?" icon in the top nav) documenting every
  environment variable as a collapsible FAQ — this README's Configuration
  section mirrors it
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

Every setting is an environment variable in `.env` — none of it is entered in
the web UI, since these values can include credentials. This section mirrors
the in-app **Help** page (the "?" icon in the top nav of the web dashboard),
which documents the same variables as a collapsible FAQ. After changing
`.env`, apply it with `docker compose up -d`; for the notification channels,
use the **Send test** button on the Monitoring page afterwards to confirm it
actually works before relying on it.

### Azure AD authentication (required)

1. Register a dedicated App Registration for this watcher in Microsoft Entra ID.
2. Grant it the **application** permission `Application.Read.All` (Microsoft
   Graph), then click **Grant admin consent**.
3. If you plan to enable `NOTIFY_OWNERS` below, also grant `User.Read.All` so
   owner emails can be resolved.

This tool only ever issues Graph `GET` requests — it cannot read secret
values (Graph never returns them after creation) and cannot modify anything.

**Option A — client secret (simplest)**

```env
AZURE_TENANT_ID=<your tenant ID>
AZURE_CLIENT_ID=<the app registration's client ID>
AZURE_CLIENT_SECRET=<a client secret you created for it>
```

This means the watcher's own access depends on a secret that will eventually
expire — set yourself a calendar reminder, or prefer Option B for long-lived
deployments.

**Option B — client certificate (recommended for long-lived deployments)**

```env
AZURE_CLIENT_CERTIFICATE_PATH=/certs/watcher.pem
AZURE_CLIENT_CERTIFICATE_PASSWORD=
```

Mount your `.pem` (private key + certificate chain) into the container — see
the `./certs` volume in `docker-compose.yml` — instead of setting
`AZURE_CLIENT_SECRET`.

### Scan behavior

```env
WARNING_THRESHOLDS_DAYS=30,14,7,1
INCLUDE_SECRETS=true
INCLUDE_CERTIFICATES=true
EXPIRED_REMINDER_INTERVAL_DAYS=7
NOTIFY_OWNERS=false
```

- `WARNING_THRESHOLDS_DAYS` — comma-separated "days before expiry" that
  trigger an alert; also editable later from the Monitoring page.
- `INCLUDE_SECRETS` / `INCLUDE_CERTIFICATES` — which credential types to scan.
- `EXPIRED_REMINDER_INTERVAL_DAYS` — how often (in days) to re-notify about
  something that's still expired and hasn't been rotated.
- `NOTIFY_OWNERS` — look up each app's owners via
  `/applications/{id}/owners` and show/include them in the dashboard and
  notifications (requires the `User.Read.All` permission above). This is
  Entra ID's real ownership data, not something this tool invents or lets
  you assign — apps with genuinely no owner assigned show up as "no owner"
  and are called out in a summary chip.

### Scheduling

```env
RUN_MODE=loop
CRON_SCHEDULE=0 8 * * *
RUN_SCAN_ON_STARTUP=true
```

- `RUN_MODE=loop` (default) — the container keeps running and scans on
  `CRON_SCHEDULE` (standard 5-field cron syntax, evaluated in UTC).
- `RUN_MODE=once` — scan a single time and exit; use this if you're driving
  the schedule yourself via host cron, systemd, or a Kubernetes CronJob (see
  `docker-compose.once.yml`).
- `RUN_SCAN_ON_STARTUP` — also scan immediately when the container starts
  (loop mode only), so the dashboard has data right away instead of waiting
  for the first scheduled run.

### Web dashboard & access

```env
WEB_UI_ENABLED=true
WEB_UI_HOST=0.0.0.0
WEB_UI_PORT=8080
WEB_UI_USERNAME=
WEB_UI_PASSWORD=
```

`WEB_UI_USERNAME` and `WEB_UI_PASSWORD` are both blank by default, which
means **anyone who can reach this port sees every credential's status and
can trigger a scan — no login required**. Set both to turn on HTTP Basic
Auth — a browser-native username/password prompt, not a page on the site —
for the whole dashboard, then `docker compose up -d` to apply it. The
dashboard never shows secret or certificate values regardless — only names,
key ids, and expiry dates — but it does reveal your App Registration
inventory, which is still worth keeping access-controlled. Set
`WEB_UI_ENABLED=false` to disable the dashboard entirely.

### Storage & advanced

Mostly fine to leave at the defaults already set in `docker-compose.yml`.

- `STATE_DB_PATH`, `STATUS_FILE_PATH`, `INVENTORY_FILE_PATH`,
  `SCAN_HISTORY_FILE_PATH`, `SETTINGS_FILE_PATH` — where each piece of
  persisted data lives inside the container, all under `/data`; already
  mapped to the `./data` volume. None of these files, nor any log line, ever
  contain an actual secret value or certificate private key.
- `SCAN_HISTORY_LIMIT` — a safety cap on how many scan-history rows can pile
  up within the rolling 24-hour window the dashboard's history panel keeps
  (entries older than 24 hours are dropped automatically).
- `DRY_RUN` — log what would be sent without actually sending anything or
  updating dedupe state; useful for a first trial run.
- `LOG_LEVEL` — standard Python logging level (`INFO`, `DEBUG`, `WARNING`, …).
- `GRAPH_PAGE_SIZE` / `REQUEST_TIMEOUT_SECONDS` — pagination size and HTTP
  timeout for calls to Microsoft Graph; the defaults work for virtually
  every tenant.

### Email (SMTP)

```env
NOTIFY_EMAIL_ENABLED=true
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_USE_TLS=true
EMAIL_FROM=azure-secret-watch@example.com
EMAIL_TO=ops@example.com, secops@example.com
```

`EMAIL_TO` is a fixed distribution list (e.g. your ops/security team) —
every alert email goes to all of these addresses. It is **not**
per-application owner routing: if `NOTIFY_OWNERS` is enabled, each app's
owners are shown inside the email body for reference (so you know who to
follow up with), but they are never added as separate recipients.

### Microsoft Teams

1. In the Teams left-hand app rail, search for and open the **Workflows**
   app (this is not the same as a "Power Automate" tab added to a channel —
   you don't need to be inside a channel first).
2. Search for the template **"Send webhook alerts to a chat"**, or build a
   blank flow with the same trigger and a "Post card in a chat or channel"
   action (see the note below on why you might prefer this).
3. In the wizard, pick the chat or channel you want alerts posted to, then
   finish it.
4. Copy the generated HTTP POST URL — this is your webhook URL.

```env
NOTIFY_TEAMS_ENABLED=true
TEAMS_WEBHOOK_URL=<the URL you copied>
TEAMS_WEBHOOK_FORMAT=adaptive_card
```

`TEAMS_WEBHOOK_FORMAT` defaults to `adaptive_card`, which matches the
Workflows-based webhook above. Use `messagecard` only if you're on an older,
legacy Office 365 Connector webhook.

A webhook URL is bound to the one chat or channel you picked when creating
it. To also post to a different destination, create another flow with that
one selected and you'll get another URL — this tool currently sends to one
Teams destination at a time.

If you'd rather not have Teams show "used a Workflow template… Get template"
under every message, build the flow from a blank canvas (same trigger +
"Post card in a chat or channel" action) instead of starting from the
template gallery — that attribution line is added by Teams based on how the
flow was created, not by anything this tool sends.

### Custom webhook

```env
NOTIFY_WEBHOOK_ENABLED=true
CUSTOM_WEBHOOK_URL=https://your-endpoint.example.com/hook
CUSTOM_WEBHOOK_METHOD=POST
CUSTOM_WEBHOOK_HEADERS={"Authorization": "Bearer <token>"}
```

`CUSTOM_WEBHOOK_HEADERS` is optional — a JSON object of extra headers, most
commonly used for a bearer token or API key the target endpoint expects.

Payload shape:

```json
{
  "summary": {"total": 2, "expired": 1, "expiring_soon": 1},
  "alerts": [
    {
      "severity": "expired",
      "app_display_name": "Billing Service",
      "credential_type": "secret",
      "credential_display_name": "prod secret",
      "days_until_expiry": -3,
      "owners": ["alice@example.com"],
      "portal_url": "https://portal.azure.com/..."
    }
  ]
}
```

This is a generic, tool-agnostic shape — not Slack's or PagerDuty's native
message format. If your target expects its own format, put a small relay in
between (a Power Automate flow, a Zapier "Catch Hook", or your own tiny
endpoint) that reshapes this JSON before forwarding it on.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for running tests, lint, and building
the image locally.

## License

[MIT](LICENSE)
