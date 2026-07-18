"""Read-only web dashboard, plus a manual "scan now" trigger.

Deliberately minimal: server-rendered HTML (no JS build step), a couple of
JSON endpoints for scripting, and optional HTTP Basic Auth. It only ever
displays credential *metadata* (names, key ids, expiry dates) — never secret
values, consistent with the rest of the tool.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from functools import wraps

from croniter import croniter
from flask import Flask, Response, jsonify, render_template, request
from waitress import serve

from .app import run_once
from .cache import read_json
from .config import Config
from .models import Alert, Credential, CredentialType
from .notifiers import EmailNotifier, TeamsNotifier, WebhookNotifier
from .settings import apply_overrides, overrides_from_form, save_overrides

logger = logging.getLogger(__name__)

_scan_lock = threading.Lock()


def _redact(text: str, *secrets: str) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    return text


def _test_alert() -> Alert:
    now = datetime.now(timezone.utc)
    credential = Credential(
        key_id="test-notification",
        credential_type=CredentialType.SECRET,
        display_name="Test credential",
        start_datetime=now - timedelta(days=365),
        end_datetime=now + timedelta(days=1),
        app_object_id="00000000-0000-0000-0000-000000000000",
        app_id="00000000-0000-0000-0000-000000000000",
        app_display_name="azure-secret-watch (test notification)",
    )
    return Alert(credential=credential, bucket="1", owners=["test-owner@example.com"])


def _next_scan_time(config: Config) -> str | None:
    if config.run_mode != "loop":
        return None
    if not croniter.is_valid(config.cron_schedule):
        return None
    now = datetime.now(timezone.utc)
    return croniter(config.cron_schedule, now).get_next(datetime).isoformat()


def create_app(config: Config) -> Flask:
    app = Flask(__name__)

    def _requires_auth(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not config.web_ui.auth_enabled:
                return view(*args, **kwargs)
            auth = request.authorization
            valid = (
                auth
                and auth.username == config.web_ui.username
                and auth.password == config.web_ui.password
            )
            if not valid:
                return Response(
                    "Authentication required",
                    401,
                    {"WWW-Authenticate": 'Basic realm="azure-secret-watch"'},
                )
            return view(*args, **kwargs)

        return wrapped

    def _load_inventory() -> dict:
        return read_json(config.inventory_file_path) or {"credentials": [], "generated_at": None}

    def _load_history() -> list:
        return read_json(config.scan_history_file_path) or []

    @app.get("/")
    @_requires_auth
    def dashboard():
        inventory = _load_inventory()
        credentials = inventory.get("credentials", [])
        owners_enabled = inventory.get("notify_owners", config.notify_owners)
        unowned_apps = len(
            {c["app_id"] for c in credentials if owners_enabled and not c.get("owners")}
        )
        summary = {
            "total_apps": len({c["app_id"] for c in credentials}),
            "total_credentials": len(credentials),
            "expired": sum(1 for c in credentials if c["status"] == "expired"),
            "warning": sum(1 for c in credentials if c["status"] == "warning"),
            "ok": sum(1 for c in credentials if c["status"] == "ok"),
            "secrets": sum(1 for c in credentials if c["credential_type"] == "secret"),
            "certificates": sum(1 for c in credentials if c["credential_type"] == "certificate"),
            "unowned_apps": unowned_apps,
        }
        return render_template(
            "dashboard.html",
            credentials=credentials,
            summary=summary,
            generated_at=inventory.get("generated_at"),
            status=read_json(config.status_file_path) or {},
            history=_load_history(),
            run_mode=config.run_mode,
            cron_schedule=config.cron_schedule,
            next_scan_at=_next_scan_time(config),
            scanning=_scan_lock.locked(),
            thresholds=config.warning_thresholds_days,
            notifiers={
                "email": config.email.enabled,
                "teams": config.teams.enabled,
                "webhook": config.webhook.enabled,
            },
            owners_enabled=owners_enabled,
            auth_enabled=config.web_ui.auth_enabled,
            active_page="applications",
            view_all=request.args.get("view") == "all",
            status_filter=request.args.get("status", ""),
        )

    def _render_settings(error: str | None = None, success: str | None = None):
        return render_template(
            "settings.html",
            active_page="monitoring",
            thresholds=config.warning_thresholds_days,
            email=config.email,
            teams=config.teams,
            webhook=config.webhook,
            email_configured=bool(config.email.smtp_host and config.email.mail_from),
            teams_configured=bool(config.teams.webhook_url),
            webhook_configured=bool(config.webhook.url),
            cron_schedule=config.cron_schedule,
            run_mode=config.run_mode,
            error=error,
            success=success,
        )

    @app.get("/settings")
    @_requires_auth
    def settings_page():
        return _render_settings()

    @app.get("/help")
    @_requires_auth
    def help_page():
        return render_template("help.html", active_page="help")

    @app.post("/settings")
    @_requires_auth
    def settings_save():
        try:
            overrides = overrides_from_form(request.form)
            apply_overrides(config, overrides)
        except ValueError as exc:
            return _render_settings(error=str(exc)), 400
        save_overrides(config.settings_file_path, overrides)
        return _render_settings(success="Settings saved.")

    @app.get("/api/status")
    @_requires_auth
    def api_status():
        return jsonify(
            {
                "last_run": read_json(config.status_file_path) or {},
                "scanning": _scan_lock.locked(),
                "next_scan_at": _next_scan_time(config),
            }
        )

    @app.get("/api/credentials")
    @_requires_auth
    def api_credentials():
        return jsonify(_load_inventory())

    @app.get("/api/history")
    @_requires_auth
    def api_history():
        return jsonify(_load_history())

    @app.post("/api/scan")
    @_requires_auth
    def api_scan():
        if _scan_lock.locked():
            return jsonify({"started": False, "detail": "a scan is already running"}), 409

        def _run():
            with _scan_lock:
                try:
                    run_once(config)
                except Exception:
                    logger.exception("Manually triggered scan failed")

        threading.Thread(target=_run, daemon=True, name="manual-scan").start()
        return jsonify({"started": True}), 202

    @app.post("/api/test-notification/<channel>")
    @_requires_auth
    def api_test_notification(channel):
        if channel == "email":
            configured = bool(
                config.email.smtp_host and config.email.mail_from and config.email.mail_to
            )
            notifier = EmailNotifier(config.email, dry_run=False)
            secrets = (config.email.smtp_password,)
        elif channel == "teams":
            configured = bool(config.teams.webhook_url)
            notifier = TeamsNotifier(
                config.teams, timeout=config.request_timeout_seconds, dry_run=False
            )
            secrets = (config.teams.webhook_url,)
        elif channel == "webhook":
            configured = bool(config.webhook.url)
            notifier = WebhookNotifier(
                config.webhook, timeout=config.request_timeout_seconds, dry_run=False
            )
            secrets = (config.webhook.url,)
        else:
            return jsonify({"ok": False, "error": "Unknown channel."}), 404

        if not configured:
            return (
                jsonify({"ok": False, "error": "This channel is not configured yet."}),
                400,
            )

        try:
            notifier.send([_test_alert()])
        except Exception as exc:  # noqa: BLE001 - report any failure back to the caller
            message = _redact(str(exc), *secrets)
            logger.warning("Test notification for %s channel failed: %s", channel, message)
            return jsonify({"ok": False, "error": message}), 502

        return jsonify({"ok": True})

    return app


def start_server(config: Config) -> None:
    app = create_app(config)
    if not config.web_ui.auth_enabled:
        logger.warning(
            "Web dashboard is running WITHOUT authentication (set WEB_UI_USERNAME and "
            "WEB_UI_PASSWORD to enable it). Do not expose port %d to an untrusted network.",
            config.web_ui.port,
        )
    logger.info("Starting web dashboard on http://%s:%d", config.web_ui.host, config.web_ui.port)
    serve(app, host=config.web_ui.host, port=config.web_ui.port)
