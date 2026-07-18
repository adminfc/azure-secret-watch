from __future__ import annotations

import logging
from collections.abc import Sequence

import requests

from ..config import WebhookConfig
from ..models import Alert
from .base import Notifier, run_dry, severity_label, sort_key

logger = logging.getLogger(__name__)


class WebhookNotifier(Notifier):
    name = "webhook"

    def __init__(self, config: WebhookConfig, timeout: int = 30, dry_run: bool = False):
        self._config = config
        self._timeout = timeout
        self._dry_run = dry_run

    def send(self, alerts: Sequence[Alert]) -> None:
        if not alerts:
            return
        if self._dry_run:
            run_dry(self.name, alerts)
            return

        payload = {
            "summary": {
                "total": len(alerts),
                "expired": sum(1 for a in alerts if a.bucket == "expired"),
                "expiring_soon": sum(1 for a in alerts if a.bucket != "expired"),
            },
            "alerts": [self._alert_to_dict(a) for a in sorted(alerts, key=sort_key)],
        }
        response = requests.request(
            self._config.method,
            self._config.url,
            json=payload,
            headers=self._config.headers or None,
            timeout=self._timeout,
        )
        response.raise_for_status()
        logger.info("Sent custom webhook notification for %d alert(s)", len(alerts))

    @staticmethod
    def _alert_to_dict(alert: Alert) -> dict:
        c = alert.credential
        return {
            "severity": "expired" if alert.bucket == "expired" else "warning",
            "bucket": severity_label(alert),
            "app_display_name": c.app_display_name,
            "app_id": c.app_id,
            "app_object_id": c.app_object_id,
            "credential_type": c.credential_type.value,
            "credential_display_name": c.display_name,
            "credential_key_id": c.key_id,
            "end_datetime": c.end_datetime.isoformat(),
            "days_until_expiry": c.days_until_expiry,
            "is_expired": c.is_expired,
            "portal_url": c.portal_url,
            "owners": alert.owners,
        }
