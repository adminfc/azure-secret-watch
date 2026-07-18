"""Shared notifier interface and formatting helpers."""
from __future__ import annotations

import abc
import logging
from collections.abc import Sequence

from ..models import Alert

logger = logging.getLogger(__name__)


class Notifier(abc.ABC):
    name: str = "notifier"

    @abc.abstractmethod
    def send(self, alerts: Sequence[Alert]) -> None:
        """Send a notification for the given alerts. Raise on failure."""


def severity_label(alert: Alert) -> str:
    if alert.bucket == "expired":
        return "EXPIRED"
    return f"expires in <= {alert.bucket} day(s)"


def sort_key(alert: Alert):
    # Expired first, then soonest-expiring first.
    return (0 if alert.bucket == "expired" else 1, alert.credential.days_until_expiry)


def summary_line(alert: Alert) -> str:
    c = alert.credential
    kind = "Certificate" if c.credential_type.value == "certificate" else "Secret"
    days = c.days_until_expiry
    when = "ALREADY EXPIRED" if c.is_expired else f"expires in {days} day(s)"
    return (
        f"[{severity_label(alert)}] {c.app_display_name} — {kind} \"{c.display_name}\" "
        f"({when}, {c.end_datetime.date().isoformat()}) — appId: {c.app_id}"
    )


def run_dry(notifier_name: str, alerts: Sequence[Alert]) -> None:
    logger.info(
        "[dry-run] %s notifier would send %d alert(s):\n%s",
        notifier_name,
        len(alerts),
        "\n".join(summary_line(a) for a in sorted(alerts, key=sort_key)),
    )
