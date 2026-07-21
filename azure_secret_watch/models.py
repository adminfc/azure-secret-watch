"""Data models for scanned applications and their credentials."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class CredentialType(str, Enum):
    SECRET = "secret"
    CERTIFICATE = "certificate"


@dataclass(frozen=True)
class Credential:
    key_id: str
    credential_type: CredentialType
    display_name: str
    start_datetime: datetime
    end_datetime: datetime
    app_object_id: str
    app_id: str
    app_display_name: str
    # "application" (an App Registration's own secret/certificate) or
    # "service_principal" (an Enterprise Application's SAML signing
    # certificate, a completely separate object with its own renewal blade).
    object_kind: str = "application"

    @property
    def days_until_expiry(self) -> int:
        now = datetime.now(timezone.utc)
        delta = self.end_datetime - now
        # Round down so "expires in a few hours" is not reported as a full day away.
        return delta.days

    @property
    def is_expired(self) -> bool:
        return self.end_datetime <= datetime.now(timezone.utc)

    @property
    def portal_url(self) -> str:
        if self.object_kind == "service_principal":
            return (
                "https://portal.azure.com/#view/Microsoft_AAD_IAM/ManagedAppMenuBlade/"
                f"~/SingleSignOn/appId/{self.app_id}"
            )
        return (
            "https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/"
            f"ApplicationMenuBlade/~/Credentials/appId/{self.app_id}"
        )


@dataclass(frozen=True)
class Alert:
    credential: Credential
    bucket: str  # "expired" or the threshold-day string, e.g. "7"
    owners: list[str]


@dataclass(frozen=True)
class ScanResult:
    credentials: list[Credential]
    alerts: list[Alert]
    owners_by_app: dict[str, list[str]]
