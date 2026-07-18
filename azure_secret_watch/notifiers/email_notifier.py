from __future__ import annotations

import logging
import smtplib
from collections.abc import Sequence
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from ..config import EmailConfig
from ..models import Alert
from .base import Notifier, run_dry, severity_label, sort_key

logger = logging.getLogger(__name__)


class EmailNotifier(Notifier):
    name = "email"

    def __init__(self, config: EmailConfig, dry_run: bool = False):
        self._config = config
        self._dry_run = dry_run

    def send(self, alerts: Sequence[Alert]) -> None:
        if not alerts:
            return
        if self._dry_run:
            run_dry(self.name, alerts)
            return

        message = MIMEMultipart("alternative")
        message["Subject"] = self._subject(alerts)
        message["From"] = self._config.mail_from
        message["To"] = ", ".join(self._config.mail_to)
        message.attach(MIMEText(self._plain_text(alerts), "plain"))
        message.attach(MIMEText(self._html(alerts), "html"))

        with smtplib.SMTP(self._config.smtp_host, self._config.smtp_port, timeout=30) as server:
            if self._config.use_tls:
                server.starttls()
            if self._config.smtp_username:
                server.login(self._config.smtp_username, self._config.smtp_password)
            server.sendmail(self._config.mail_from, self._config.mail_to, message.as_string())

        logger.info("Sent email notification for %d alert(s)", len(alerts))

    @staticmethod
    def _subject(alerts: Sequence[Alert]) -> str:
        expired = sum(1 for a in alerts if a.bucket == "expired")
        expiring = len(alerts) - expired
        parts = []
        if expired:
            parts.append(f"{expired} EXPIRED")
        if expiring:
            parts.append(f"{expiring} expiring soon")
        return f"[azure-secret-watch] App Registration credentials: {', '.join(parts)}"

    @staticmethod
    def _plain_text(alerts: Sequence[Alert]) -> str:
        lines = ["The following App Registration credentials need attention:", ""]
        for alert in sorted(alerts, key=sort_key):
            c = alert.credential
            kind = "Certificate" if c.credential_type.value == "certificate" else "Secret"
            when = "ALREADY EXPIRED" if c.is_expired else f"expires in {c.days_until_expiry} day(s)"
            lines.append(
                f"- [{severity_label(alert)}] {c.app_display_name} ({c.app_id})\n"
                f"  {kind}: {c.display_name}\n"
                f"  {when} on {c.end_datetime.date().isoformat()}\n"
                f"  Rotate at: {c.portal_url}"
            )
            if alert.owners:
                lines.append(f"  Owners: {', '.join(alert.owners)}")
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _html(alerts: Sequence[Alert]) -> str:
        rows = []
        for alert in sorted(alerts, key=sort_key):
            c = alert.credential
            kind = "Certificate" if c.credential_type.value == "certificate" else "Secret"
            when = "ALREADY EXPIRED" if c.is_expired else f"{c.days_until_expiry} day(s)"
            color = "#c0392b" if alert.bucket == "expired" else "#e67e22"
            rows.append(
                "<tr>"
                f'<td style="padding:6px;border:1px solid #ddd;color:{color};font-weight:bold">'
                f"{severity_label(alert)}</td>"
                f'<td style="padding:6px;border:1px solid #ddd">{c.app_display_name}</td>'
                f'<td style="padding:6px;border:1px solid #ddd">{kind}: {c.display_name}</td>'
                f'<td style="padding:6px;border:1px solid #ddd">{when}</td>'
                f'<td style="padding:6px;border:1px solid #ddd">'
                f'{c.end_datetime.date().isoformat()}</td>'
                f'<td style="padding:6px;border:1px solid #ddd">'
                f'<a href="{c.portal_url}">Open in Azure Portal</a></td>'
                "</tr>"
            )
        return (
            "<html><body>"
            "<p>The following App Registration credentials need attention:</p>"
            '<table style="border-collapse:collapse">'
            "<tr>"
            '<th style="padding:6px;border:1px solid #ddd">Status</th>'
            '<th style="padding:6px;border:1px solid #ddd">Application</th>'
            '<th style="padding:6px;border:1px solid #ddd">Credential</th>'
            '<th style="padding:6px;border:1px solid #ddd">Expires</th>'
            '<th style="padding:6px;border:1px solid #ddd">Date</th>'
            '<th style="padding:6px;border:1px solid #ddd">Action</th>'
            "</tr>" + "".join(rows) + "</table></body></html>"
        )
