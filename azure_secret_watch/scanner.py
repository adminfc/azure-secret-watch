"""Core scan logic: turn raw Graph applications into alerts and a full inventory."""
from __future__ import annotations

import logging
from collections.abc import Iterable

from .graph_client import GraphClient, extract_credentials
from .models import Alert, Credential, ScanResult
from .state_store import StateStore

logger = logging.getLogger(__name__)


def bucket_for(credential: Credential, warning_thresholds_days: list[int]) -> str | None:
    """Return the alert bucket a credential currently falls in, or None if it
    is not yet due for any warning."""
    days = credential.days_until_expiry
    if credential.is_expired:
        return "expired"
    for threshold in sorted(warning_thresholds_days):
        if days <= threshold:
            return str(threshold)
    return None


def credential_status(credential: Credential, warning_thresholds_days: list[int]) -> str:
    """Three-tier status used by the web dashboard: expired / warning / ok."""
    bucket = bucket_for(credential, warning_thresholds_days)
    if bucket is None:
        return "ok"
    return "expired" if bucket == "expired" else "warning"


def scan(
    graph_client: GraphClient,
    state_store: StateStore,
    warning_thresholds_days: list[int],
    include_secrets: bool,
    include_certificates: bool,
    expired_reminder_interval_days: int,
    notify_owners: bool,
) -> ScanResult:
    all_credentials: list[Credential] = []
    alerts: list[Alert] = []
    owners_by_app: dict[str, list[str]] = {}
    seen_key_ids: set[str] = set()
    app_count = 0

    def owners_for(app_object_id: str) -> list[str]:
        if app_object_id not in owners_by_app:
            owners_by_app[app_object_id] = graph_client.get_owner_emails(app_object_id)
        return owners_by_app[app_object_id]

    for app in graph_client.iter_applications():
        app_count += 1
        for credential in extract_credentials(app, include_secrets, include_certificates):
            all_credentials.append(credential)
            seen_key_ids.add(credential.key_id)
            if notify_owners:
                owners_for(credential.app_object_id)

            bucket = bucket_for(credential, warning_thresholds_days)
            if bucket is None:
                continue
            if not state_store.should_notify(
                credential.key_id, bucket, expired_reminder_interval_days
            ):
                continue

            owners = owners_for(credential.app_object_id) if notify_owners else []
            alerts.append(Alert(credential=credential, bucket=bucket, owners=owners))

    removed = state_store.prune(seen_key_ids)
    logger.info(
        "Scanned %d application(s), %d credential(s); %d alert(s) to send; "
        "pruned %d stale state row(s)",
        app_count,
        len(all_credentials),
        len(alerts),
        removed,
    )
    return ScanResult(credentials=all_credentials, alerts=alerts, owners_by_app=owners_by_app)


def mark_alerts_sent(state_store: StateStore, alerts: Iterable[Alert]) -> None:
    for alert in alerts:
        state_store.mark_notified(alert.credential.key_id, alert.bucket)
