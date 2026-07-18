from __future__ import annotations

import base64
import time

import azure_secret_watch.web as web
from azure_secret_watch.cache import write_json
from azure_secret_watch.config import EmailConfig, TeamsConfig, WebhookConfig, WebUIConfig
from azure_secret_watch.notifiers import EmailNotifier, TeamsNotifier, WebhookNotifier
from tests.conftest import make_config


def _basic_auth_header(username, password):
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def test_dashboard_shows_empty_state_when_no_inventory(tmp_path):
    config = make_config(tmp_path)
    client = web.create_app(config).test_client()

    resp = client.get("/")

    assert resp.status_code == 200
    assert "No scan data yet" in resp.get_data(as_text=True)


def test_dashboard_shows_summary_and_rows(tmp_path):
    config = make_config(tmp_path)
    write_json(
        config.inventory_file_path,
        {
            "generated_at": "2026-01-01T00:00:00+00:00",
            "credentials": [
                {
                    "app_display_name": "Billing Service",
                    "app_id": "app-1",
                    "app_object_id": "obj-1",
                    "credential_type": "secret",
                    "display_name": "prod secret",
                    "key_id": "k1",
                    "start_datetime": "2020-01-01T00:00:00+00:00",
                    "end_datetime": "2026-01-05T00:00:00+00:00",
                    "days_until_expiry": 3,
                    "is_expired": False,
                    "status": "warning",
                    "portal_url": "https://portal.azure.com/x",
                }
            ],
        },
    )
    client = web.create_app(config).test_client()

    resp = client.get("/")
    body = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert "Billing Service" in body
    assert "prod secret" in body


def test_dashboard_shows_needs_attention_and_hides_full_list_by_default(tmp_path):
    config = make_config(tmp_path)
    write_json(
        config.inventory_file_path,
        {
            "generated_at": "2026-01-01T00:00:00+00:00",
            "credentials": [
                {
                    "app_display_name": "Billing Service",
                    "app_id": "app-1",
                    "app_object_id": "obj-1",
                    "credential_type": "secret",
                    "display_name": "prod secret",
                    "key_id": "k1",
                    "start_datetime": "2020-01-01T00:00:00+00:00",
                    "end_datetime": "2026-01-05T00:00:00+00:00",
                    "days_until_expiry": 3,
                    "is_expired": False,
                    "status": "warning",
                    "portal_url": "https://portal.azure.com/x",
                },
                {
                    "app_display_name": "Internal Portal",
                    "app_id": "app-2",
                    "app_object_id": "obj-2",
                    "credential_type": "secret",
                    "display_name": "portal secret",
                    "key_id": "k2",
                    "start_datetime": "2020-01-01T00:00:00+00:00",
                    "end_datetime": "2027-01-01T00:00:00+00:00",
                    "days_until_expiry": 300,
                    "is_expired": False,
                    "status": "ok",
                    "portal_url": "https://portal.azure.com/y",
                },
            ],
        },
    )
    client = web.create_app(config).test_client()

    body = client.get("/").get_data(as_text=True)

    assert "Expiring soon" in body
    assert 'id="full-list-section" style="display:none;"' in body
    assert "All credentials" in body
    # The attention section shows the warning credential...
    attention_html = body[body.index("Expiring soon") : body.index('id="full-list-section"')]
    assert "Billing Service" in attention_html
    # ...but not the healthy one, which only appears inside the hidden full list.
    assert "Internal Portal" not in attention_html


def test_dashboard_view_all_query_param_shows_full_list_and_presets_filter(tmp_path):
    config = make_config(tmp_path)
    write_json(
        config.inventory_file_path,
        {
            "generated_at": "2026-01-01T00:00:00+00:00",
            "credentials": [
                {
                    "app_display_name": "Billing Service",
                    "app_id": "app-1",
                    "app_object_id": "obj-1",
                    "credential_type": "secret",
                    "display_name": "prod secret",
                    "key_id": "k1",
                    "start_datetime": "2020-01-01T00:00:00+00:00",
                    "end_datetime": "2026-01-05T00:00:00+00:00",
                    "days_until_expiry": 3,
                    "is_expired": False,
                    "status": "warning",
                    "portal_url": "https://portal.azure.com/x",
                }
            ],
        },
    )
    client = web.create_app(config).test_client()

    body = client.get("/?view=all&status=warning").get_data(as_text=True)

    assert 'id="full-list-section"' in body
    assert 'id="full-list-section" style="display:none;"' not in body
    assert '<option value="warning" selected>' in body
    assert '<a href="/?view=all" class="tab active">All credentials</a>' in body
    # The attention cards are the Applications-tab view; they must not also
    # appear on the All-credentials view, or the two tabs show duplicate content.
    assert "No expired credentials." not in body
    assert '<h1>All credentials</h1>' in body


def test_dashboard_shows_owners_in_attention_rows_when_enabled(tmp_path):
    config = make_config(tmp_path, notify_owners=True)
    write_json(
        config.inventory_file_path,
        {
            "generated_at": "2026-01-01T00:00:00+00:00",
            "notify_owners": True,
            "credentials": [
                {
                    "app_display_name": "Billing Service",
                    "app_id": "app-1",
                    "app_object_id": "obj-1",
                    "credential_type": "secret",
                    "display_name": "prod secret",
                    "key_id": "k1",
                    "start_datetime": "2020-01-01T00:00:00+00:00",
                    "end_datetime": "2026-01-05T00:00:00+00:00",
                    "days_until_expiry": 3,
                    "is_expired": False,
                    "status": "warning",
                    "portal_url": "https://portal.azure.com/x",
                    "owners": ["alice@example.com"],
                },
                {
                    "app_display_name": "Legacy Integration",
                    "app_id": "app-2",
                    "app_object_id": "obj-2",
                    "credential_type": "certificate",
                    "display_name": "old cert",
                    "key_id": "k2",
                    "start_datetime": "2020-01-01T00:00:00+00:00",
                    "end_datetime": "2026-01-01T00:00:00+00:00",
                    "days_until_expiry": -5,
                    "is_expired": True,
                    "status": "expired",
                    "portal_url": "https://portal.azure.com/y",
                    "owners": [],
                },
            ],
        },
    )
    client = web.create_app(config).test_client()

    body = client.get("/").get_data(as_text=True)

    assert "alice@example.com" in body
    assert "no owner" in body


def test_dashboard_shows_all_clear_when_nothing_needs_attention(tmp_path):
    config = make_config(tmp_path)
    write_json(
        config.inventory_file_path,
        {
            "generated_at": "2026-01-01T00:00:00+00:00",
            "credentials": [
                {
                    "app_display_name": "Internal Portal",
                    "app_id": "app-2",
                    "app_object_id": "obj-2",
                    "credential_type": "secret",
                    "display_name": "portal secret",
                    "key_id": "k2",
                    "start_datetime": "2020-01-01T00:00:00+00:00",
                    "end_datetime": "2027-01-01T00:00:00+00:00",
                    "days_until_expiry": 300,
                    "is_expired": False,
                    "status": "ok",
                    "portal_url": "https://portal.azure.com/y",
                }
            ],
        },
    )
    client = web.create_app(config).test_client()

    body = client.get("/").get_data(as_text=True)

    assert "No expired credentials." in body
    assert "Nothing expiring soon." in body


def test_api_credentials_returns_raw_inventory(tmp_path):
    config = make_config(tmp_path)
    write_json(config.inventory_file_path, {"generated_at": "now", "credentials": []})
    client = web.create_app(config).test_client()

    resp = client.get("/api/credentials")

    assert resp.status_code == 200
    assert resp.get_json() == {"generated_at": "now", "credentials": []}


def test_api_status_reports_not_scanning_by_default(tmp_path):
    config = make_config(tmp_path)
    client = web.create_app(config).test_client()

    resp = client.get("/api/status")

    assert resp.status_code == 200
    assert resp.get_json()["scanning"] is False


def test_auth_required_when_credentials_configured(tmp_path):
    config = make_config(
        tmp_path, web_ui=WebUIConfig(username="admin", password="hunter2")
    )
    client = web.create_app(config).test_client()

    assert client.get("/").status_code == 401
    assert client.get("/", headers=_basic_auth_header("admin", "wrong")).status_code == 401
    assert client.get("/", headers=_basic_auth_header("admin", "hunter2")).status_code == 200


def test_no_auth_required_when_credentials_not_configured(tmp_path):
    config = make_config(tmp_path, web_ui=WebUIConfig(username="", password=""))
    client = web.create_app(config).test_client()

    assert client.get("/").status_code == 200


def test_dashboard_shows_owners_column_when_enabled(tmp_path):
    config = make_config(tmp_path, notify_owners=True)
    write_json(
        config.inventory_file_path,
        {
            "generated_at": "2026-01-01T00:00:00+00:00",
            "notify_owners": True,
            "credentials": [
                {
                    "app_display_name": "Billing Service",
                    "app_id": "app-1",
                    "app_object_id": "obj-1",
                    "credential_type": "secret",
                    "display_name": "prod secret",
                    "key_id": "k1",
                    "start_datetime": "2020-01-01T00:00:00+00:00",
                    "end_datetime": "2026-01-05T00:00:00+00:00",
                    "days_until_expiry": 3,
                    "is_expired": False,
                    "status": "warning",
                    "portal_url": "https://portal.azure.com/x",
                    "owners": ["alice@example.com"],
                },
                {
                    "app_display_name": "Orphan App",
                    "app_id": "app-2",
                    "app_object_id": "obj-2",
                    "credential_type": "secret",
                    "display_name": "old secret",
                    "key_id": "k2",
                    "start_datetime": "2020-01-01T00:00:00+00:00",
                    "end_datetime": "2026-01-05T00:00:00+00:00",
                    "days_until_expiry": 3,
                    "is_expired": False,
                    "status": "warning",
                    "portal_url": "https://portal.azure.com/y",
                    "owners": [],
                },
            ],
        },
    )
    client = web.create_app(config).test_client()

    body = client.get("/").get_data(as_text=True)

    assert "Owners" in body
    assert "alice@example.com" in body
    assert "No owner" in body


def test_dashboard_hides_owners_column_when_disabled(tmp_path):
    config = make_config(tmp_path, notify_owners=False)
    write_json(
        config.inventory_file_path,
        {
            "generated_at": "2026-01-01T00:00:00+00:00",
            "notify_owners": False,
            "credentials": [
                {
                    "app_display_name": "Billing Service",
                    "app_id": "app-1",
                    "app_object_id": "obj-1",
                    "credential_type": "secret",
                    "display_name": "prod secret",
                    "key_id": "k1",
                    "start_datetime": "2020-01-01T00:00:00+00:00",
                    "end_datetime": "2026-01-05T00:00:00+00:00",
                    "days_until_expiry": 3,
                    "is_expired": False,
                    "status": "warning",
                    "portal_url": "https://portal.azure.com/x",
                    "owners": [],
                }
            ],
        },
    )
    client = web.create_app(config).test_client()

    body = client.get("/").get_data(as_text=True)

    assert "Owner lookup disabled" in body
    assert "<th class=\"col-owners truncate\">Owners</th>" not in body


def test_api_history_returns_recorded_runs(tmp_path):
    config = make_config(tmp_path)
    history = [
        {
            "status": "ok",
            "detail": "scan completed",
            "alert_count": 2,
            "credential_count": 10,
            "app_count": 5,
            "ran_at": "2026-01-02T00:00:00+00:00",
        }
    ]
    write_json(config.scan_history_file_path, history)
    client = web.create_app(config).test_client()

    resp = client.get("/api/history")

    assert resp.status_code == 200
    assert resp.get_json() == history


def test_dashboard_renders_history_section(tmp_path):
    config = make_config(tmp_path)
    write_json(
        config.scan_history_file_path,
        [
            {
                "status": "error",
                "detail": "Authentication failed",
                "alert_count": 0,
                "credential_count": 0,
                "app_count": 0,
                "ran_at": "2026-01-02T00:00:00+00:00",
            }
        ],
    )
    client = web.create_app(config).test_client()

    body = client.get("/").get_data(as_text=True)

    assert "Authentication failed" in body
    assert "Scan history" in body


def test_dashboard_shows_notifier_and_threshold_chips(tmp_path):
    from azure_secret_watch.config import TeamsConfig

    config = make_config(
        tmp_path, teams=TeamsConfig(enabled=True, webhook_url="https://example.com/hook")
    )
    client = web.create_app(config).test_client()

    body = client.get("/").get_data(as_text=True)

    assert "Teams" in body
    assert "30" in body and "14" in body


def test_settings_page_shows_current_state(tmp_path):
    from azure_secret_watch.config import EmailConfig

    config = make_config(
        tmp_path,
        email=EmailConfig(
            enabled=True,
            smtp_host="smtp.example.com",
            mail_from="watch@example.com",
            mail_to=["ops@example.com"],
        ),
    )
    client = web.create_app(config).test_client()

    body = client.get("/settings").get_data(as_text=True)

    assert "Monitoring" in body
    assert "ops@example.com" in body
    assert "30, 14, 7, 1" in body
    assert "Monitoring alerts are active" in body


def test_settings_page_disables_unconfigured_channel_toggle(tmp_path):
    config = make_config(tmp_path)
    client = web.create_app(config).test_client()

    body = client.get("/settings").get_data(as_text=True)

    assert 'name="notify_teams_enabled"' in body
    assert "Set TEAMS_WEBHOOK_URL" in body


def test_settings_post_updates_thresholds_and_recipients(tmp_path):
    from azure_secret_watch.config import EmailConfig

    config = make_config(
        tmp_path,
        email=EmailConfig(smtp_host="smtp.example.com", mail_from="watch@example.com"),
    )
    client = web.create_app(config).test_client()

    resp = client.post(
        "/settings",
        data={
            "warning_thresholds_days": "14, 3",
            "notify_email_enabled": "on",
            "email_to": "ops@example.com",
        },
    )

    assert resp.status_code == 200
    assert "Settings saved" in resp.get_data(as_text=True)
    assert config.warning_thresholds_days == [3, 14]
    assert config.email.enabled is True
    assert config.email.mail_to == ["ops@example.com"]


def test_settings_post_persists_across_new_app_instance(tmp_path):
    from azure_secret_watch.config import EmailConfig

    config = make_config(
        tmp_path,
        email=EmailConfig(smtp_host="smtp.example.com", mail_from="watch@example.com"),
    )
    client = web.create_app(config).test_client()
    client.post(
        "/settings",
        data={"warning_thresholds_days": "5", "email_to": "ops@example.com"},
    )

    from azure_secret_watch.settings import bootstrap

    fresh_config = make_config(
        tmp_path,
        email=EmailConfig(smtp_host="smtp.example.com", mail_from="watch@example.com"),
    )
    bootstrap(fresh_config)

    assert fresh_config.warning_thresholds_days == [5]
    assert fresh_config.email.mail_to == ["ops@example.com"]


def test_settings_post_rejects_invalid_threshold(tmp_path):
    config = make_config(tmp_path)
    client = web.create_app(config).test_client()

    resp = client.post("/settings", data={"warning_thresholds_days": "not-a-number"})

    assert resp.status_code == 400
    assert "not a whole number of days" in resp.get_data(as_text=True)
    assert config.warning_thresholds_days == [30, 14, 7, 1]


def test_settings_post_rejects_enabling_unconfigured_teams(tmp_path):
    config = make_config(tmp_path)
    client = web.create_app(config).test_client()

    resp = client.post(
        "/settings",
        data={"warning_thresholds_days": "30", "notify_teams_enabled": "on"},
    )

    assert resp.status_code == 400
    assert config.teams.enabled is False


def test_api_scan_triggers_run_once_and_rejects_concurrent_scan(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    calls = []

    def fake_run_once(cfg):
        calls.append(cfg)
        time.sleep(0.05)

    monkeypatch.setattr(web, "run_once", fake_run_once)
    client = web.create_app(config).test_client()

    resp = client.post("/api/scan")
    assert resp.status_code == 202
    assert resp.get_json()["started"] is True

    resp_busy = client.post("/api/scan")
    assert resp_busy.status_code == 409

    for _ in range(50):
        if calls:
            break
        time.sleep(0.02)
    assert calls == [config]


def test_test_notification_rejects_unknown_channel(tmp_path):
    config = make_config(tmp_path)
    client = web.create_app(config).test_client()

    resp = client.post("/api/test-notification/carrier-pigeon")

    assert resp.status_code == 404
    assert resp.get_json()["ok"] is False


def test_test_notification_rejects_unconfigured_channel(tmp_path):
    config = make_config(tmp_path, email=EmailConfig())
    client = web.create_app(config).test_client()

    resp = client.post("/api/test-notification/email")

    assert resp.status_code == 400
    assert resp.get_json()["ok"] is False


def test_test_notification_email_success(tmp_path, monkeypatch):
    config = make_config(
        tmp_path,
        email=EmailConfig(
            enabled=False,
            smtp_host="smtp.example.com",
            mail_from="watch@example.com",
            mail_to=["ops@example.com"],
        ),
    )
    sent = []
    monkeypatch.setattr(EmailNotifier, "send", lambda self, alerts: sent.append(alerts))
    client = web.create_app(config).test_client()

    resp = client.post("/api/test-notification/email")

    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}
    assert len(sent) == 1 and len(sent[0]) == 1


def test_test_notification_teams_failure_redacts_webhook_url(tmp_path, monkeypatch):
    webhook_url = "https://example.com/webhook/super-secret-token"
    config = make_config(tmp_path, teams=TeamsConfig(enabled=False, webhook_url=webhook_url))

    def boom(self, alerts):
        raise RuntimeError(f"connection failed for {webhook_url}")

    monkeypatch.setattr(TeamsNotifier, "send", boom)
    client = web.create_app(config).test_client()

    resp = client.post("/api/test-notification/teams")

    assert resp.status_code == 502
    body = resp.get_json()
    assert body["ok"] is False
    assert webhook_url not in body["error"]
    assert "[redacted]" in body["error"]


def test_test_notification_webhook_success(tmp_path, monkeypatch):
    config = make_config(tmp_path, webhook=WebhookConfig(enabled=False, url="https://example.com/hook"))
    sent = []
    monkeypatch.setattr(WebhookNotifier, "send", lambda self, alerts: sent.append(alerts))
    client = web.create_app(config).test_client()

    resp = client.post("/api/test-notification/webhook")

    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}
    assert len(sent) == 1


def test_help_page_documents_each_channel(tmp_path):
    config = make_config(tmp_path)
    client = web.create_app(config).test_client()

    resp = client.get("/help")
    body = resp.get_data(as_text=True)

    assert resp.status_code == 200
    assert "How do I authenticate with Azure AD?" in body
    assert "How do I control what counts as expiring?" in body
    assert "How often does it scan?" in body
    assert "How do I require a login for the dashboard?" in body
    assert "What do the storage / advanced settings do?" in body
    assert "How do I set up email alerts?" in body
    assert "How do I send alerts to Microsoft Teams?" in body
    assert "How do I send alerts somewhere else" in body
    assert "AZURE_TENANT_ID" in body
    assert "WEB_UI_USERNAME" in body
    assert "NOTIFY_TEAMS_ENABLED" in body
    assert "CUSTOM_WEBHOOK_URL" in body


def test_help_page_questions_are_collapsed_by_default(tmp_path):
    config = make_config(tmp_path)
    client = web.create_app(config).test_client()

    resp = client.get("/help")
    body = resp.get_data(as_text=True)

    assert body.count('<details class="card-surface help-section">') == 8
    assert "<details class=\"card-surface help-section\" open>" not in body


def test_help_link_present_in_nav(tmp_path):
    config = make_config(tmp_path)
    client = web.create_app(config).test_client()

    resp = client.get("/")

    assert 'href="/help"' in resp.get_data(as_text=True)
