"""Thin, read-only wrapper around the Microsoft Graph applications API.

Only ``GET`` requests are ever issued. The tool never reads or transmits the
actual secret values (Graph itself never returns them after creation - only
metadata such as key id, display name, and expiry timestamps).
"""
from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator
from datetime import datetime, timezone

import requests
from azure.identity import CertificateCredential, ClientSecretCredential

from .config import AzureAuthConfig
from .models import Credential, CredentialType

logger = logging.getLogger(__name__)

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPE = "https://graph.microsoft.com/.default"


def build_credential(auth: AzureAuthConfig):
    if auth.certificate_path:
        return CertificateCredential(
            tenant_id=auth.tenant_id,
            client_id=auth.client_id,
            certificate_path=auth.certificate_path,
            password=auth.certificate_password,
        )
    return ClientSecretCredential(
        tenant_id=auth.tenant_id,
        client_id=auth.client_id,
        client_secret=auth.client_secret,
    )


class GraphClient:
    def __init__(self, auth: AzureAuthConfig, timeout: int = 30, page_size: int = 999):
        self._credential = build_credential(auth)
        self._timeout = timeout
        self._page_size = page_size
        self._session = requests.Session()

    def _access_token(self) -> str:
        token = self._credential.get_token(GRAPH_SCOPE)
        return token.token

    def _get(self, url: str, params: dict | None = None) -> dict:
        headers = {"Authorization": f"Bearer {self._access_token()}"}
        response = self._session.get(url, headers=headers, params=params, timeout=self._timeout)
        response.raise_for_status()
        return response.json()

    def _paged(self, url: str, params: dict | None = None) -> Iterator[dict]:
        next_url, next_params = url, params
        while next_url:
            page = self._get(next_url, next_params)
            yield from page.get("value", [])
            next_url = page.get("@odata.nextLink")
            next_params = None  # nextLink already includes query params

    def iter_applications(self) -> Iterator[dict]:
        """Yield raw application objects with credential fields selected."""
        url = f"{GRAPH_BASE_URL}/applications"
        params = {
            "$select": "id,appId,displayName,passwordCredentials,keyCredentials",
            "$top": str(self._page_size),
        }
        yield from self._paged(url, params)

    def get_owner_emails(self, app_object_id: str) -> list[str]:
        """Best-effort lookup of an application's owner email addresses."""
        url = f"{GRAPH_BASE_URL}/applications/{app_object_id}/owners"
        params = {"$select": "mail,userPrincipalName"}
        emails: list[str] = []
        try:
            for owner in self._paged(url, params):
                email = owner.get("mail") or owner.get("userPrincipalName")
                if email:
                    emails.append(email)
        except requests.HTTPError as exc:
            logger.warning("Could not fetch owners for application %s: %s", app_object_id, exc)
        return emails


def _parse_datetime(value: str) -> datetime:
    # Graph returns ISO 8601 timestamps, e.g. 2027-01-15T00:00:00Z
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def extract_credentials(
    app: dict, include_secrets: bool, include_certificates: bool
) -> Iterable[Credential]:
    app_object_id = app["id"]
    app_id = app["appId"]
    app_display_name = app.get("displayName") or "(unnamed application)"

    if include_secrets:
        for cred in app.get("passwordCredentials") or []:
            yield Credential(
                key_id=cred["keyId"],
                credential_type=CredentialType.SECRET,
                display_name=cred.get("displayName") or "(no description)",
                start_datetime=_parse_datetime(cred["startDateTime"]),
                end_datetime=_parse_datetime(cred["endDateTime"]),
                app_object_id=app_object_id,
                app_id=app_id,
                app_display_name=app_display_name,
            )

    if include_certificates:
        for cred in app.get("keyCredentials") or []:
            yield Credential(
                key_id=cred["keyId"],
                credential_type=CredentialType.CERTIFICATE,
                display_name=cred.get("displayName") or "(no description)",
                start_datetime=_parse_datetime(cred["startDateTime"]),
                end_datetime=_parse_datetime(cred["endDateTime"]),
                app_object_id=app_object_id,
                app_id=app_id,
                app_display_name=app_display_name,
            )
