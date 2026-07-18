"""Orchestrates a single scan-and-notify run."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from .cache import read_json, write_json
from .config import Config
from .graph_client import GraphClient
from .models import Credential
from .notifiers import EmailNotifier, Notifier, TeamsNotifier, WebhookNotifier
from .scanner import credential_status, mark_alerts_sent, scan
from .state_store import StateStore

logger = logging.getLogger(__name__)


def build_notifiers(config: Config) -> list[Notifier]:
    notifiers: list[Notifier] = []
    if config.email.enabled:
        notifiers.append(EmailNotifier(config.email, dry_run=config.dry_run))
    if config.teams.enabled:
        notifiers.append(
            TeamsNotifier(
                config.teams,
                timeout=config.request_timeout_seconds,
                dry_run=config.dry_run,
            )
        )
    if config.webhook.enabled:
        notifiers.append(
            WebhookNotifier(
                config.webhook,
                timeout=config.request_timeout_seconds,
                dry_run=config.dry_run,
            )
        )
    if not notifiers:
        logger.warning(
            "No notification channel is enabled (NOTIFY_EMAIL_ENABLED / "
            "NOTIFY_TEAMS_ENABLED / NOTIFY_WEBHOOK_ENABLED) — alerts will only be logged."
        )
    return notifiers


def _credential_to_dict(
    credential: Credential, warning_thresholds_days: list[int], owners: list[str]
) -> dict:
    return {
        "app_display_name": credential.app_display_name,
        "app_id": credential.app_id,
        "app_object_id": credential.app_object_id,
        "credential_type": credential.credential_type.value,
        "display_name": credential.display_name,
        "key_id": credential.key_id,
        "start_datetime": credential.start_datetime.isoformat(),
        "end_datetime": credential.end_datetime.isoformat(),
        "days_until_expiry": credential.days_until_expiry,
        "is_expired": credential.is_expired,
        "status": credential_status(credential, warning_thresholds_days),
        "portal_url": credential.portal_url,
        "owners": owners,
    }


def _write_inventory(
    config: Config, credentials: list[Credential], owners_by_app: dict[str, list[str]]
) -> None:
    if not config.inventory_file_path:
        return
    items = [
        _credential_to_dict(
            c, config.warning_thresholds_days, owners_by_app.get(c.app_object_id, [])
        )
        for c in credentials
    ]
    items.sort(key=lambda item: item["days_until_expiry"])
    write_json(
        config.inventory_file_path,
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "warning_thresholds_days": config.warning_thresholds_days,
            "notify_owners": config.notify_owners,
            "credentials": items,
        },
    )


def _ran_within_last_day(entry: dict) -> bool:
    try:
        ran_at = datetime.fromisoformat(entry["ran_at"])
    except (KeyError, ValueError):
        return False
    return datetime.now(timezone.utc) - ran_at <= timedelta(days=1)


def _record_run_result(
    config: Config,
    status: str,
    detail: str,
    alert_count: int,
    credential_count: int,
    app_count: int,
) -> None:
    ran_at = datetime.now(timezone.utc).isoformat()
    entry = {
        "status": status,
        "detail": detail,
        "alert_count": alert_count,
        "credential_count": credential_count,
        "app_count": app_count,
        "ran_at": ran_at,
    }
    if config.status_file_path:
        write_json(config.status_file_path, entry)
    if config.scan_history_file_path:
        history = read_json(config.scan_history_file_path) or []
        history.insert(0, entry)
        history = [h for h in history if _ran_within_last_day(h)]
        write_json(config.scan_history_file_path, history[: config.scan_history_limit])


def run_once(config: Config) -> int:
    """Run a single scan. Returns the number of alerts sent."""
    graph_client = GraphClient(
        config.azure, timeout=config.request_timeout_seconds, page_size=config.graph_page_size
    )
    state_store = StateStore(config.state_db_path)
    notifiers = build_notifiers(config)

    try:
        result = scan(
            graph_client=graph_client,
            state_store=state_store,
            warning_thresholds_days=config.warning_thresholds_days,
            include_secrets=config.include_secrets,
            include_certificates=config.include_certificates,
            expired_reminder_interval_days=config.expired_reminder_interval_days,
            notify_owners=config.notify_owners,
        )

        for notifier in notifiers:
            try:
                notifier.send(result.alerts)
            except Exception:
                logger.exception("Notifier %s failed to send", notifier.name)

        if not config.dry_run:
            mark_alerts_sent(state_store, result.alerts)

        _write_inventory(config, result.credentials, result.owners_by_app)
        app_count = len({c.app_id for c in result.credentials})
        _record_run_result(
            config, "ok", "scan completed", len(result.alerts), len(result.credentials), app_count
        )
        return len(result.alerts)
    except Exception as exc:
        _record_run_result(config, "error", str(exc), 0, 0, 0)
        raise
