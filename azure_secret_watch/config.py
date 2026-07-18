"""Configuration loaded from environment variables (optionally via a .env file)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv


def _bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    val = os.getenv(name)
    if val is None or val.strip() == "":
        return default
    return int(val)


def _csv(name: str, default: str) -> list[str]:
    val = os.getenv(name, default)
    return [item.strip() for item in val.split(",") if item.strip()]


def _thresholds(name: str, default: str) -> list[int]:
    days = sorted({int(x) for x in _csv(name, default)})
    if not days:
        raise ValueError(f"{name} must contain at least one integer value")
    return days


@dataclass
class AzureAuthConfig:
    tenant_id: str
    client_id: str
    client_secret: str | None = None
    certificate_path: str | None = None
    certificate_password: str | None = None

    def __post_init__(self) -> None:
        if not self.client_secret and not self.certificate_path:
            raise ValueError(
                "Either AZURE_CLIENT_SECRET or AZURE_CLIENT_CERTIFICATE_PATH must be set"
            )


@dataclass
class EmailConfig:
    enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    use_tls: bool = True
    mail_from: str = ""
    mail_to: list[str] = field(default_factory=list)

    def validate(self) -> None:
        if not self.enabled:
            return
        missing = [
            name
            for name, val in {
                "SMTP_HOST": self.smtp_host,
                "EMAIL_FROM": self.mail_from,
            }.items()
            if not val
        ]
        if not self.mail_to:
            missing.append("EMAIL_TO")
        if missing:
            raise ValueError(f"Email notifier enabled but missing: {', '.join(missing)}")


@dataclass
class TeamsConfig:
    enabled: bool = False
    webhook_url: str = ""
    format: str = "adaptive_card"  # or "messagecard" (legacy Office 365 connector)

    def validate(self) -> None:
        if self.enabled and not self.webhook_url:
            raise ValueError("Teams notifier enabled but TEAMS_WEBHOOK_URL is not set")


@dataclass
class WebhookConfig:
    enabled: bool = False
    url: str = ""
    method: str = "POST"
    headers: dict = field(default_factory=dict)

    def validate(self) -> None:
        if self.enabled and not self.url:
            raise ValueError("Custom webhook notifier enabled but CUSTOM_WEBHOOK_URL is not set")


@dataclass
class WebUIConfig:
    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 8080
    username: str = ""
    password: str = ""

    @property
    def auth_enabled(self) -> bool:
        return bool(self.username and self.password)


@dataclass
class Config:
    azure: AzureAuthConfig
    warning_thresholds_days: list[int]
    include_secrets: bool
    include_certificates: bool
    notify_owners: bool
    expired_reminder_interval_days: int
    run_mode: str
    run_scan_on_startup: bool
    cron_schedule: str
    state_db_path: str
    status_file_path: str
    inventory_file_path: str
    scan_history_file_path: str
    scan_history_limit: int
    settings_file_path: str
    dry_run: bool
    log_level: str
    email: EmailConfig
    teams: TeamsConfig
    webhook: WebhookConfig
    web_ui: WebUIConfig
    graph_page_size: int
    request_timeout_seconds: int

    @classmethod
    def from_env(cls) -> Config:
        load_dotenv()

        azure = AzureAuthConfig(
            tenant_id=_require("AZURE_TENANT_ID"),
            client_id=_require("AZURE_CLIENT_ID"),
            client_secret=os.getenv("AZURE_CLIENT_SECRET") or None,
            certificate_path=os.getenv("AZURE_CLIENT_CERTIFICATE_PATH") or None,
            certificate_password=os.getenv("AZURE_CLIENT_CERTIFICATE_PASSWORD") or None,
        )

        email = EmailConfig(
            enabled=_bool("NOTIFY_EMAIL_ENABLED", False),
            smtp_host=os.getenv("SMTP_HOST", ""),
            smtp_port=_int("SMTP_PORT", 587),
            smtp_username=os.getenv("SMTP_USERNAME", ""),
            smtp_password=os.getenv("SMTP_PASSWORD", ""),
            use_tls=_bool("SMTP_USE_TLS", True),
            mail_from=os.getenv("EMAIL_FROM", ""),
            mail_to=_csv("EMAIL_TO", ""),
        )
        email.validate()

        teams = TeamsConfig(
            enabled=_bool("NOTIFY_TEAMS_ENABLED", False),
            webhook_url=os.getenv("TEAMS_WEBHOOK_URL", ""),
            format=os.getenv("TEAMS_WEBHOOK_FORMAT", "adaptive_card"),
        )
        teams.validate()

        raw_headers = os.getenv("CUSTOM_WEBHOOK_HEADERS", "").strip()
        webhook = WebhookConfig(
            enabled=_bool("NOTIFY_WEBHOOK_ENABLED", False),
            url=os.getenv("CUSTOM_WEBHOOK_URL", ""),
            method=os.getenv("CUSTOM_WEBHOOK_METHOD", "POST").upper(),
            headers=json.loads(raw_headers) if raw_headers else {},
        )
        webhook.validate()

        web_ui = WebUIConfig(
            enabled=_bool("WEB_UI_ENABLED", True),
            host=os.getenv("WEB_UI_HOST", "0.0.0.0"),
            port=_int("WEB_UI_PORT", 8080),
            username=os.getenv("WEB_UI_USERNAME", ""),
            password=os.getenv("WEB_UI_PASSWORD", ""),
        )

        return cls(
            azure=azure,
            warning_thresholds_days=_thresholds("WARNING_THRESHOLDS_DAYS", "30,14,7,1"),
            include_secrets=_bool("INCLUDE_SECRETS", True),
            include_certificates=_bool("INCLUDE_CERTIFICATES", True),
            notify_owners=_bool("NOTIFY_OWNERS", False),
            expired_reminder_interval_days=_int("EXPIRED_REMINDER_INTERVAL_DAYS", 7),
            run_mode=os.getenv("RUN_MODE", "loop").strip().lower(),
            run_scan_on_startup=_bool("RUN_SCAN_ON_STARTUP", True),
            cron_schedule=os.getenv("CRON_SCHEDULE", "0 8 * * *"),
            state_db_path=os.getenv("STATE_DB_PATH", "/data/state.db"),
            status_file_path=os.getenv("STATUS_FILE_PATH", "/data/last_run.json"),
            inventory_file_path=os.getenv("INVENTORY_FILE_PATH", "/data/inventory.json"),
            scan_history_file_path=os.getenv(
                "SCAN_HISTORY_FILE_PATH", "/data/scan_history.json"
            ),
            scan_history_limit=_int("SCAN_HISTORY_LIMIT", 20),
            settings_file_path=os.getenv("SETTINGS_FILE_PATH", "/data/settings.json"),
            dry_run=_bool("DRY_RUN", False),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            email=email,
            teams=teams,
            webhook=webhook,
            web_ui=web_ui,
            graph_page_size=_int("GRAPH_PAGE_SIZE", 999),
            request_timeout_seconds=_int("REQUEST_TIMEOUT_SECONDS", 30),
        )


def _require(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise ValueError(f"Required environment variable {name} is not set")
    return val
