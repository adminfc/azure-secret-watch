# Security Policy

## Scope and design

azure-secret-watch is intentionally read-only: it is granted only Microsoft
Graph `Application.Read.All` (and optionally `User.Read.All` for owner
lookups), and every request it issues is a `GET`. It never reads, logs, or
transmits the actual value of a client secret or certificate private key —
Microsoft Graph does not return secret values after creation, only metadata
(key id, display name, start/end dates).

Credentials for the watcher itself (`AZURE_CLIENT_SECRET`,
`AZURE_CLIENT_CERTIFICATE_PATH`/password, SMTP password, webhook headers) are
read from environment variables / mounted files and are never written to the
state database, the status file, or log output.

## Reporting a vulnerability

If you find a security issue, please open a private report via GitHub's
"Report a vulnerability" feature on this repository's Security tab instead of
opening a public issue. If that isn't available, open an issue asking a
maintainer to provide a private contact channel, without including
exploit details.

## Hardening recommendations for deployers

- Prefer certificate-based authentication (`AZURE_CLIENT_CERTIFICATE_PATH`)
  over a client secret for the watcher's own App Registration, so it isn't
  subject to the same expiry problem it's meant to catch.
- Grant only `Application.Read.All` (and `User.Read.All` if you enable
  `NOTIFY_OWNERS`) — no write or directory-modifying permissions are needed.
- Run the container as the provided non-root `watcher` user (the default).
- Mount `/data` as a dedicated volume; it only ever contains the dedupe
  state database and a small JSON status file, never secret values.
