from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from azure_secret_watch.config import (
    AzureAuthConfig,
    Config,
    EmailConfig,
    TeamsConfig,
    WebhookConfig,
    WebUIConfig,
)
from azure_secret_watch.models import Credential, CredentialType


def make_credential(
    days_from_now: float,
    key_id: str = "key-1",
    credential_type: CredentialType = CredentialType.SECRET,
    app_id: str = "app-id-1",
    app_object_id: str = "obj-1",
    app_display_name: str = "Test App",
) -> Credential:
    now = datetime.now(timezone.utc)
    return Credential(
        key_id=key_id,
        credential_type=credential_type,
        display_name="test credential",
        start_datetime=now - timedelta(days=365),
        end_datetime=now + timedelta(days=days_from_now),
        app_object_id=app_object_id,
        app_id=app_id,
        app_display_name=app_display_name,
    )


@pytest.fixture
def state_db_path(tmp_path):
    return str(tmp_path / "state.db")


def make_config(tmp_path, **overrides) -> Config:
    defaults = dict(
        azure=AzureAuthConfig(tenant_id="t", client_id="c", client_secret="s"),
        warning_thresholds_days=[30, 14, 7, 1],
        include_secrets=True,
        include_certificates=True,
        notify_owners=False,
        expired_reminder_interval_days=7,
        run_mode="loop",
        run_scan_on_startup=False,
        cron_schedule="0 8 * * *",
        state_db_path=str(tmp_path / "state.db"),
        status_file_path=str(tmp_path / "last_run.json"),
        inventory_file_path=str(tmp_path / "inventory.json"),
        scan_history_file_path=str(tmp_path / "scan_history.json"),
        scan_history_limit=20,
        settings_file_path=str(tmp_path / "settings.json"),
        dry_run=False,
        log_level="INFO",
        email=EmailConfig(),
        teams=TeamsConfig(),
        webhook=WebhookConfig(),
        web_ui=WebUIConfig(),
        graph_page_size=999,
        request_timeout_seconds=30,
    )
    defaults.update(overrides)
    return Config(**defaults)
