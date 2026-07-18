from __future__ import annotations

import logging
from collections.abc import Sequence

import requests

from ..config import TeamsConfig
from ..models import Alert
from .base import Notifier, run_dry, severity_label, sort_key

logger = logging.getLogger(__name__)


class TeamsNotifier(Notifier):
    name = "teams"

    def __init__(self, config: TeamsConfig, timeout: int = 30, dry_run: bool = False):
        self._config = config
        self._timeout = timeout
        self._dry_run = dry_run

    def send(self, alerts: Sequence[Alert]) -> None:
        if not alerts:
            return
        if self._dry_run:
            run_dry(self.name, alerts)
            return

        payload = (
            self._build_messagecard(alerts)
            if self._config.format == "messagecard"
            else self._build_adaptive_card(alerts)
        )
        response = requests.post(self._config.webhook_url, json=payload, timeout=self._timeout)
        response.raise_for_status()
        logger.info("Sent Teams notification for %d alert(s)", len(alerts))

    @staticmethod
    def _build_adaptive_card(alerts: Sequence[Alert]) -> dict:
        expired = [a for a in alerts if a.bucket == "expired"]
        expiring = [a for a in alerts if a.bucket != "expired"]

        title_bits = []
        if expired:
            title_bits.append(f"{len(expired)} expired")
        if expiring:
            title_bits.append(f"{len(expiring)} expiring soon")
        title = "Azure App Registration credentials — " + ", ".join(title_bits)

        def fact_for(alert: Alert) -> dict:
            c = alert.credential
            kind = "Certificate" if c.credential_type.value == "certificate" else "Secret"
            when = "expired" if c.is_expired else f"expires in {c.days_until_expiry} day(s)"
            expiry_date = c.end_datetime.date().isoformat()
            value = f"{kind} · {when} ({expiry_date}) · [Rotate]({c.portal_url})"
            if alert.owners:
                value += f" · Owner: {', '.join(alert.owners)}"
            return {"title": c.app_display_name, "value": value}

        body = [
            {
                "type": "TextBlock",
                "text": title,
                "weight": "bolder",
                "size": "medium",
                "wrap": True,
            }
        ]
        if expired:
            body.append(
                {
                    "type": "TextBlock",
                    "text": "Expired",
                    "weight": "bolder",
                    "color": "attention",
                    "spacing": "medium",
                }
            )
            expired_facts = [fact_for(a) for a in sorted(expired, key=sort_key)]
            body.append({"type": "FactSet", "facts": expired_facts})
        if expiring:
            body.append(
                {
                    "type": "TextBlock",
                    "text": "Expiring soon",
                    "weight": "bolder",
                    "color": "warning",
                    "spacing": "medium",
                }
            )
            expiring_facts = [fact_for(a) for a in sorted(expiring, key=sort_key)]
            body.append({"type": "FactSet", "facts": expiring_facts})

        card = {
            "type": "AdaptiveCard",
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.4",
            "body": body,
        }
        return {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "contentUrl": None,
                    "content": card,
                }
            ],
        }

    @staticmethod
    def _build_messagecard(alerts: Sequence[Alert]) -> dict:
        # Legacy Office 365 Connector card format. Kept for older Teams webhooks;
        # Microsoft has deprecated this connector type in favor of Workflows.
        facts = []
        for alert in sorted(alerts, key=sort_key):
            c = alert.credential
            kind = "Certificate" if c.credential_type.value == "certificate" else "Secret"
            when = "ALREADY EXPIRED" if c.is_expired else f"{c.days_until_expiry}d left"
            expiry_date = c.end_datetime.date().isoformat()
            facts.append(
                {
                    "name": f"{c.app_display_name} ({kind})",
                    "value": f"{severity_label(alert)} — {when} — {expiry_date}",
                }
            )
        return {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "summary": "Azure App Registration credential alert",
            "themeColor": "C0392B",
            "title": "Azure App Registration credentials need attention",
            "sections": [{"facts": facts, "markdown": True}],
        }
