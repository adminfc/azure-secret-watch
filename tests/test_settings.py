from __future__ import annotations

import pytest

from azure_secret_watch import settings
from azure_secret_watch.cache import read_json
from azure_secret_watch.config import EmailConfig, TeamsConfig
from tests.conftest import make_config


def test_parse_thresholds_dedupes_and_sorts():
    assert settings._parse_thresholds("30, 7, 7, 1") == [1, 7, 30]


def test_parse_thresholds_rejects_non_integer():
    with pytest.raises(ValueError):
        settings._parse_thresholds("30, soon")


def test_parse_thresholds_requires_at_least_one_value():
    with pytest.raises(ValueError):
        settings._parse_thresholds("  ")


def test_parse_recipients_accepts_comma_or_semicolon():
    assert settings._parse_recipients("a@example.com; b@example.com,c@example.com") == [
        "a@example.com",
        "b@example.com",
        "c@example.com",
    ]


def test_parse_recipients_rejects_invalid_address():
    with pytest.raises(ValueError):
        settings._parse_recipients("not-an-email")


def test_apply_overrides_updates_config_in_place(tmp_path):
    config = make_config(
        tmp_path,
        email=EmailConfig(smtp_host="smtp.example.com", mail_from="watch@example.com"),
    )
    overrides = settings.SettingsOverrides(
        warning_thresholds_days=[10, 3],
        notify_email_enabled=True,
        email_to=["ops@example.com"],
    )

    settings.apply_overrides(config, overrides)

    assert config.warning_thresholds_days == [3, 10]
    assert config.email.enabled is True
    assert config.email.mail_to == ["ops@example.com"]


def test_apply_overrides_rolls_back_on_validation_failure(tmp_path):
    # Email has no SMTP host configured, so enabling it should fail validate().
    config = make_config(tmp_path, email=EmailConfig())
    original_thresholds = config.warning_thresholds_days

    with pytest.raises(ValueError):
        settings.apply_overrides(
            config,
            settings.SettingsOverrides(
                warning_thresholds_days=[5],
                notify_email_enabled=True,
                email_to=["ops@example.com"],
            ),
        )

    assert config.warning_thresholds_days == original_thresholds
    assert config.email.enabled is False


def test_apply_overrides_rejects_enabling_teams_without_webhook_url(tmp_path):
    config = make_config(tmp_path, teams=TeamsConfig())

    with pytest.raises(ValueError):
        settings.apply_overrides(config, settings.SettingsOverrides(notify_teams_enabled=True))

    assert config.teams.enabled is False


def test_save_and_load_overrides_round_trip(tmp_path):
    path = str(tmp_path / "settings.json")
    overrides = settings.SettingsOverrides(
        warning_thresholds_days=[7, 1], notify_email_enabled=True
    )

    settings.save_overrides(path, overrides)
    loaded = settings.load_overrides(path)

    assert loaded == overrides
    assert read_json(path) == {"warning_thresholds_days": [7, 1], "notify_email_enabled": True}


def test_load_overrides_returns_empty_when_no_file(tmp_path):
    loaded = settings.load_overrides(str(tmp_path / "missing.json"))
    assert loaded == settings.SettingsOverrides()


def test_bootstrap_applies_persisted_overrides(tmp_path):
    config = make_config(
        tmp_path,
        email=EmailConfig(smtp_host="smtp.example.com", mail_from="watch@example.com"),
    )
    settings.save_overrides(
        config.settings_file_path,
        settings.SettingsOverrides(notify_email_enabled=True, email_to=["ops@example.com"]),
    )

    settings.bootstrap(config)

    assert config.email.enabled is True
    assert config.email.mail_to == ["ops@example.com"]


def test_bootstrap_ignores_invalid_persisted_overrides(tmp_path, caplog):
    config = make_config(tmp_path, teams=TeamsConfig())
    settings.save_overrides(
        config.settings_file_path, settings.SettingsOverrides(notify_teams_enabled=True)
    )

    settings.bootstrap(config)

    assert config.teams.enabled is False


def test_overrides_from_form_parses_checkboxes_and_lists():
    form = {
        "warning_thresholds_days": "30,14,7,1",
        "notify_email_enabled": "on",
        "email_to": "a@example.com, b@example.com",
    }

    overrides = settings.overrides_from_form(form)

    assert overrides.warning_thresholds_days == [1, 7, 14, 30]
    assert overrides.notify_email_enabled is True
    assert overrides.notify_teams_enabled is False
    assert overrides.notify_webhook_enabled is False
    assert overrides.email_to == ["a@example.com", "b@example.com"]
