"""Runtime-editable overlay on top of the env-loaded Config.

Most configuration (Azure credentials, SMTP host, Teams/webhook URLs) is
infrastructure and stays in the environment. A small subset — whether a
channel is on, who gets emailed, and the warning thresholds — is safe to
expose in the web UI and is persisted here as a JSON file under ``/data``,
so it survives container restarts without needing a redeploy.

Config objects are shared (by reference) between the scheduler thread and
the web server thread, so overrides are applied by mutating the existing
Config/notifier-config instances in place rather than building new ones.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from .cache import read_json, write_json
from .config import Config

logger = logging.getLogger(__name__)

EDITABLE_FIELDS = (
    "warning_thresholds_days",
    "notify_email_enabled",
    "email_to",
    "notify_teams_enabled",
    "notify_webhook_enabled",
)


@dataclass
class SettingsOverrides:
    warning_thresholds_days: list[int] | None = None
    notify_email_enabled: bool | None = None
    email_to: list[str] | None = None
    notify_teams_enabled: bool | None = None
    notify_webhook_enabled: bool | None = None

    @classmethod
    def from_dict(cls, data: dict) -> SettingsOverrides:
        return cls(**{k: data.get(k) for k in EDITABLE_FIELDS})

    def to_dict(self) -> dict:
        return {k: v for k in EDITABLE_FIELDS if (v := getattr(self, k)) is not None}


def load_overrides(path: str) -> SettingsOverrides:
    return SettingsOverrides.from_dict(read_json(path) or {})


def save_overrides(path: str, overrides: SettingsOverrides) -> None:
    write_json(path, overrides.to_dict())


def _normalize_thresholds(values: list[int]) -> list[int]:
    if not values:
        raise ValueError("At least one threshold is required")
    if any(v < 0 for v in values):
        raise ValueError("Thresholds must be zero or a positive number of days")
    return sorted(set(values))


def _parse_thresholds(raw: str) -> list[int]:
    values = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            values.append(int(part))
        except ValueError:
            raise ValueError(f"'{part}' is not a whole number of days") from None
    return _normalize_thresholds(values)


def _parse_recipients(raw: str) -> list[str]:
    recipients = [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]
    for addr in recipients:
        if "@" not in addr or " " in addr:
            raise ValueError(f"'{addr}' does not look like a valid email address")
    return recipients


def overrides_from_form(form: dict) -> SettingsOverrides:
    """Parse the Settings page form into overrides. Raises ValueError on bad input."""
    return SettingsOverrides(
        warning_thresholds_days=_parse_thresholds(form.get("warning_thresholds_days", "")),
        notify_email_enabled="notify_email_enabled" in form,
        email_to=_parse_recipients(form.get("email_to", "")),
        notify_teams_enabled="notify_teams_enabled" in form,
        notify_webhook_enabled="notify_webhook_enabled" in form,
    )


def apply_overrides(config: Config, overrides: SettingsOverrides) -> None:
    """Mutate `config` in place to reflect `overrides`, validating as it goes.

    On failure, `config` is left exactly as it was — nothing partially applied.
    """
    snapshot = (
        config.warning_thresholds_days,
        config.email.enabled,
        config.email.mail_to,
        config.teams.enabled,
        config.webhook.enabled,
    )
    try:
        if overrides.warning_thresholds_days is not None:
            config.warning_thresholds_days = _normalize_thresholds(
                overrides.warning_thresholds_days
            )
        if overrides.notify_email_enabled is not None:
            config.email.enabled = overrides.notify_email_enabled
        if overrides.email_to is not None:
            config.email.mail_to = overrides.email_to
        if overrides.notify_teams_enabled is not None:
            config.teams.enabled = overrides.notify_teams_enabled
        if overrides.notify_webhook_enabled is not None:
            config.webhook.enabled = overrides.notify_webhook_enabled

        config.email.validate()
        config.teams.validate()
        config.webhook.validate()
    except ValueError:
        (
            config.warning_thresholds_days,
            config.email.enabled,
            config.email.mail_to,
            config.teams.enabled,
            config.webhook.enabled,
        ) = snapshot
        raise


def bootstrap(config: Config) -> None:
    """Apply any persisted overrides on top of the freshly loaded env Config.

    Called once at startup. Invalid persisted state (e.g. a channel was
    enabled from the UI but its env-configured URL was since removed) is
    logged and skipped rather than crashing startup.
    """
    overrides = load_overrides(config.settings_file_path)
    try:
        apply_overrides(config, overrides)
    except ValueError as exc:
        logger.warning(
            "Ignoring persisted settings override at %s: %s", config.settings_file_path, exc
        )
