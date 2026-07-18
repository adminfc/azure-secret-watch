from __future__ import annotations

import json

import responses

from azure_secret_watch.config import EmailConfig, TeamsConfig, WebhookConfig
from azure_secret_watch.models import Alert
from azure_secret_watch.notifiers.email_notifier import EmailNotifier
from azure_secret_watch.notifiers.teams_notifier import TeamsNotifier
from azure_secret_watch.notifiers.webhook_notifier import WebhookNotifier
from tests.conftest import make_credential


def make_alert(days_from_now=5, bucket="7", owners=None):
    return Alert(
        credential=make_credential(days_from_now=days_from_now), bucket=bucket, owners=owners or []
    )


@responses.activate
def test_webhook_notifier_sends_expected_payload():
    config = WebhookConfig(enabled=True, url="https://example.com/hook", method="POST")
    responses.add(responses.POST, "https://example.com/hook", json={}, status=200)

    notifier = WebhookNotifier(config)
    notifier.send([make_alert()])

    assert len(responses.calls) == 1
    body = json.loads(responses.calls[0].request.body)
    assert body["summary"]["total"] == 1
    assert body["alerts"][0]["app_id"] == "app-id-1"
    assert body["alerts"][0]["severity"] == "warning"


def test_webhook_notifier_dry_run_sends_nothing():
    config = WebhookConfig(enabled=True, url="https://example.com/hook")
    notifier = WebhookNotifier(config, dry_run=True)
    # Should not raise even though no HTTP mock is registered, since nothing is sent.
    notifier.send([make_alert()])


def test_webhook_notifier_no_alerts_is_noop():
    config = WebhookConfig(enabled=True, url="https://example.com/hook")
    notifier = WebhookNotifier(config)
    notifier.send([])  # no responses registered; would raise ConnectionError if it tried to POST


@responses.activate
def test_teams_notifier_adaptive_card_payload():
    config = TeamsConfig(
        enabled=True, webhook_url="https://example.com/teams", format="adaptive_card"
    )
    responses.add(responses.POST, "https://example.com/teams", json={}, status=200)

    notifier = TeamsNotifier(config)
    notifier.send([make_alert(days_from_now=-1, bucket="expired")])

    payload = json.loads(responses.calls[0].request.body)
    assert payload["type"] == "message"
    card = payload["attachments"][0]["content"]
    assert card["type"] == "AdaptiveCard"
    assert "1 expired" in card["body"][0]["text"]
    assert card["body"][1]["text"] == "Expired"
    facts = card["body"][2]["facts"]
    assert facts[0]["title"] == "Test App"
    assert "expired" in facts[0]["value"]
    assert "Rotate" in facts[0]["value"]


@responses.activate
def test_teams_notifier_adaptive_card_includes_owners_and_sections():
    config = TeamsConfig(
        enabled=True, webhook_url="https://example.com/teams", format="adaptive_card"
    )
    responses.add(responses.POST, "https://example.com/teams", json={}, status=200)

    notifier = TeamsNotifier(config)
    notifier.send(
        [
            make_alert(days_from_now=-1, bucket="expired", owners=["alice@example.com"]),
            make_alert(days_from_now=5, bucket="7"),
        ]
    )

    card = json.loads(responses.calls[0].request.body)["attachments"][0]["content"]
    section_headers = [b["text"] for b in card["body"] if b.get("type") == "TextBlock"][1:]
    assert section_headers == ["Expired", "Expiring soon"]

    expired_facts, expiring_facts = (b["facts"] for b in card["body"] if b.get("type") == "FactSet")
    assert "Owner: alice@example.com" in expired_facts[0]["value"]
    assert "Owner" not in expiring_facts[0]["value"]


@responses.activate
def test_teams_notifier_messagecard_payload():
    config = TeamsConfig(
        enabled=True, webhook_url="https://example.com/teams", format="messagecard"
    )
    responses.add(responses.POST, "https://example.com/teams", json={}, status=200)

    notifier = TeamsNotifier(config)
    notifier.send([make_alert()])

    payload = json.loads(responses.calls[0].request.body)
    assert payload["@type"] == "MessageCard"


def test_email_notifier_dry_run_does_not_touch_smtp(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("SMTP should not be contacted during a dry run")

    monkeypatch.setattr("smtplib.SMTP", _boom)

    config = EmailConfig(
        enabled=True,
        smtp_host="smtp.example.com",
        mail_from="from@example.com",
        mail_to=["to@example.com"],
    )
    notifier = EmailNotifier(config, dry_run=True)
    notifier.send([make_alert()])


def test_email_notifier_sends_via_smtp(monkeypatch):
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=30):
            sent["host"] = host
            sent["port"] = port

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self):
            sent["starttls"] = True

        def login(self, username, password):
            sent["login"] = (username, password)

        def sendmail(self, from_addr, to_addrs, message):
            sent["from_addr"] = from_addr
            sent["to_addrs"] = to_addrs
            sent["message"] = message

    monkeypatch.setattr("smtplib.SMTP", FakeSMTP)

    config = EmailConfig(
        enabled=True,
        smtp_host="smtp.example.com",
        smtp_port=587,
        mail_from="from@example.com",
        mail_to=["to@example.com"],
    )
    notifier = EmailNotifier(config)
    notifier.send([make_alert()])

    assert sent["host"] == "smtp.example.com"
    assert sent["from_addr"] == "from@example.com"
    assert sent["to_addrs"] == ["to@example.com"]
    assert "app-id-1" in sent["message"]
