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

    def iter_service_principals(self) -> Iterator[dict]:
        """Yield raw service principal (Enterprise Application) objects.

        This includes every service principal in the tenant, not just ones
        with credentials of interest — most (first-party Microsoft ones in
        particular) have empty passwordCredentials/keyCredentials and are
        filtered out downstream in extract_credentials.
        """
        url = f"{GRAPH_BASE_URL}/servicePrincipals"
        params = {
            "$select": "id,appId,displayName,passwordCredentials,keyCredentials",
            "$top": str(self._page_size),
        }
        yield from self._paged(url, params)

    def get_owner_emails(self, object_id: str, resource: str = "applications") -> list[str]:
        """Best-effort lookup of an application/service principal's owner emails."""
        url = f"{GRAPH_BASE_URL}/{resource}/{object_id}/owners"
        params = {"$select": "mail,userPrincipalName"}
        emails: list[str] = []
        try:
            for owner in self._paged(url, params):
                email = owner.get("mail") or owner.get("userPrincipalName")
                if email:
                    emails.append(email)
        except requests.HTTPError as exc:
            logger.warning("Could not fetch owners for %s %s: %s", resource, object_id, exc)
        return emails


def _parse_datetime(value: str) -> datetime:
    # Graph returns ISO 8601 timestamps, e.g. 2027-01-15T00:00:00Z
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _active_signing_certificate(key_credentials: list[dict]) -> list[dict]:
    """A service principal's keyCredentials lists every SAML signing
    certificate it has ever had — each one duplicated once per usage
    ("Sign" and "Verify") — but only one of them is actually in use at a
    time; the rest are historical (rolled-over or already-expired) and not
    worth alerting on.

    Graph exposes which one is active via the service principal's
    ``preferredTokenSigningKeyThumbprint``, but that's a SHA-1 thumbprint of
    the certificate bytes, and ``keyCredentials[].customKeyIdentifier`` is a
    SHA-256 identifier instead — there's no way to cross-reference the two
    without the actual certificate (which Graph never returns). Instead,
    collapse the Sign/Verify duplicates for each physical certificate
    (grouped by customKeyIdentifier) and keep only the one with the
    furthest-future endDateTime: rotating to a new certificate always means
    creating one with a later expiry than whatever was previously active, so
    in every normal rotation workflow that's also the currently-active one.
    """
    by_identifier: dict[str, dict] = {}
    for cred in key_credentials:
        identifier = cred.get("customKeyIdentifier") or cred["keyId"]
        if identifier not in by_identifier or cred.get("usage") == "Sign":
            by_identifier[identifier] = cred
    if not by_identifier:
        return []
    return [max(by_identifier.values(), key=lambda cred: cred["endDateTime"])]


def extract_credentials(
    app: dict,
    include_secrets: bool,
    include_certificates: bool,
    object_kind: str = "application",
) -> Iterable[Credential]:
    app_object_id = app["id"]
    app_id = app["appId"]
    app_display_name = app.get("displayName") or "(unnamed application)"
    all_key_credentials = app.get("keyCredentials") or []

    if include_secrets:
        # A service principal with SAML SSO configured mirrors each signing
        # certificate's metadata into passwordCredentials too (same keyId,
        # but secretText/hint are always null - there's no actual secret
        # value behind it). Skip those here so they're not double-counted
        # alongside the same certificate already handled via keyCredentials
        # below; any password credential that doesn't match a certificate is
        # a real secret and still gets reported normally.
        cert_key_ids = {cred["keyId"] for cred in all_key_credentials}
        for cred in app.get("passwordCredentials") or []:
            if object_kind == "service_principal" and cred["keyId"] in cert_key_ids:
                continue
            yield Credential(
                key_id=cred["keyId"],
                credential_type=CredentialType.SECRET,
                display_name=cred.get("displayName") or "(no description)",
                start_datetime=_parse_datetime(cred["startDateTime"]),
                end_datetime=_parse_datetime(cred["endDateTime"]),
                app_object_id=app_object_id,
                app_id=app_id,
                app_display_name=app_display_name,
                object_kind=object_kind,
            )

    if include_certificates:
        key_credentials = all_key_credentials
        if object_kind == "service_principal":
            key_credentials = _active_signing_certificate(key_credentials)
        for cred in key_credentials:
            yield Credential(
                key_id=cred["keyId"],
                credential_type=CredentialType.CERTIFICATE,
                display_name=cred.get("displayName") or "(no description)",
                start_datetime=_parse_datetime(cred["startDateTime"]),
                end_datetime=_parse_datetime(cred["endDateTime"]),
                app_object_id=app_object_id,
                app_id=app_id,
                app_display_name=app_display_name,
                object_kind=object_kind,
            )
