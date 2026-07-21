from __future__ import annotations

import responses

from azure_secret_watch import graph_client as graph_client_module
from azure_secret_watch.config import AzureAuthConfig
from azure_secret_watch.graph_client import GraphClient, extract_credentials
from azure_secret_watch.models import CredentialType


class FakeToken:
    token = "fake-token"


class FakeCredential:
    def get_token(self, *scopes):
        return FakeToken()


def test_extract_credentials_secrets_and_certificates():
    app = {
        "id": "obj-1",
        "appId": "app-1",
        "displayName": "My App",
        "passwordCredentials": [
            {
                "keyId": "secret-1",
                "displayName": "prod secret",
                "startDateTime": "2024-01-01T00:00:00Z",
                "endDateTime": "2026-01-01T00:00:00Z",
            }
        ],
        "keyCredentials": [
            {
                "keyId": "cert-1",
                "displayName": "prod cert",
                "startDateTime": "2024-01-01T00:00:00Z",
                "endDateTime": "2027-01-01T00:00:00Z",
            }
        ],
    }

    creds = list(extract_credentials(app, include_secrets=True, include_certificates=True))
    assert len(creds) == 2
    assert {c.credential_type for c in creds} == {CredentialType.SECRET, CredentialType.CERTIFICATE}
    assert all(c.app_display_name == "My App" for c in creds)


def test_extract_credentials_respects_include_flags():
    app = {
        "id": "obj-1",
        "appId": "app-1",
        "displayName": "My App",
        "passwordCredentials": [
            {
                "keyId": "secret-1",
                "displayName": "prod secret",
                "startDateTime": "2024-01-01T00:00:00Z",
                "endDateTime": "2026-01-01T00:00:00Z",
            }
        ],
        "keyCredentials": [],
    }
    creds = list(extract_credentials(app, include_secrets=False, include_certificates=True))
    assert creds == []


@responses.activate
def test_iter_applications_follows_pagination(monkeypatch):
    monkeypatch.setattr(graph_client_module, "build_credential", lambda auth: FakeCredential())

    responses.add(
        responses.GET,
        "https://graph.microsoft.com/v1.0/applications",
        json={
            "value": [{"id": "1", "appId": "a1", "displayName": "App1"}],
            "@odata.nextLink": "https://graph.microsoft.com/v1.0/applications?%24skiptoken=abc",
        },
        status=200,
    )
    responses.add(
        responses.GET,
        "https://graph.microsoft.com/v1.0/applications",
        json={"value": [{"id": "2", "appId": "a2", "displayName": "App2"}]},
        status=200,
    )

    auth = AzureAuthConfig(tenant_id="t", client_id="c", client_secret="s")
    client = GraphClient(auth)
    apps = list(client.iter_applications())

    assert [a["id"] for a in apps] == ["1", "2"]
    assert len(responses.calls) == 2


@responses.activate
def test_get_owner_emails_handles_error_gracefully(monkeypatch):
    monkeypatch.setattr(graph_client_module, "build_credential", lambda auth: FakeCredential())
    responses.add(
        responses.GET,
        "https://graph.microsoft.com/v1.0/applications/obj-1/owners",
        json={"error": "forbidden"},
        status=403,
    )

    auth = AzureAuthConfig(tenant_id="t", client_id="c", client_secret="s")
    client = GraphClient(auth)
    emails = client.get_owner_emails("obj-1")

    assert emails == []


@responses.activate
def test_iter_service_principals_follows_pagination(monkeypatch):
    monkeypatch.setattr(graph_client_module, "build_credential", lambda auth: FakeCredential())

    responses.add(
        responses.GET,
        "https://graph.microsoft.com/v1.0/servicePrincipals",
        json={
            "value": [{"id": "sp-1", "appId": "a1", "displayName": "SP1"}],
            "@odata.nextLink": "https://graph.microsoft.com/v1.0/servicePrincipals?%24skiptoken=abc",
        },
        status=200,
    )
    responses.add(
        responses.GET,
        "https://graph.microsoft.com/v1.0/servicePrincipals",
        json={"value": [{"id": "sp-2", "appId": "a2", "displayName": "SP2"}]},
        status=200,
    )

    auth = AzureAuthConfig(tenant_id="t", client_id="c", client_secret="s")
    client = GraphClient(auth)
    sps = list(client.iter_service_principals())

    assert [sp["id"] for sp in sps] == ["sp-1", "sp-2"]
    assert len(responses.calls) == 2


@responses.activate
def test_get_owner_emails_uses_service_principals_resource(monkeypatch):
    monkeypatch.setattr(graph_client_module, "build_credential", lambda auth: FakeCredential())
    responses.add(
        responses.GET,
        "https://graph.microsoft.com/v1.0/servicePrincipals/sp-1/owners",
        json={"value": [{"mail": "owner@example.com"}]},
        status=200,
    )

    auth = AzureAuthConfig(tenant_id="t", client_id="c", client_secret="s")
    client = GraphClient(auth)
    emails = client.get_owner_emails("sp-1", resource="servicePrincipals")

    assert emails == ["owner@example.com"]


def test_extract_credentials_tags_service_principal_object_kind():
    sp = {
        "id": "sp-1",
        "appId": "app-1",
        "displayName": "Newegg NAS",
        "keyCredentials": [
            {
                "keyId": "saml-cert-1",
                "displayName": "SAML signing certificate",
                "startDateTime": "2024-01-01T00:00:00Z",
                "endDateTime": "2027-01-01T00:00:00Z",
            }
        ],
    }
    creds = list(
        extract_credentials(
            sp, include_secrets=True, include_certificates=True, object_kind="service_principal"
        )
    )
    assert len(creds) == 1
    assert creds[0].object_kind == "service_principal"


def _saml_cert_pair(identifier, sign_key_id, verify_key_id, start, end):
    # A real service principal's keyCredentials list each physical
    # certificate twice — once per usage — with everything else identical.
    common = {
        "customKeyIdentifier": identifier,
        "displayName": "CN=Microsoft Azure Federated SSO Certificate",
        "startDateTime": start,
        "endDateTime": end,
        "type": "AsymmetricX509Cert",
    }
    return [
        {**common, "keyId": verify_key_id, "usage": "Verify"},
        {**common, "keyId": sign_key_id, "usage": "Sign"},
    ]


def test_extract_credentials_only_yields_the_active_saml_certificate():
    # Shaped after a real tenant's service principal with 3 rotated
    # certificates: one active (furthest expiry), one inactive, one expired.
    sp = {
        "id": "sp-1",
        "appId": "app-1",
        "displayName": "Contoso SSO App",
        "keyCredentials": [
            *_saml_cert_pair(
                "active-cert", "sign-1", "verify-1", "2026-02-24T00:00:00Z", "2029-02-24T00:00:00Z"
            ),
            *_saml_cert_pair(
                "inactive-cert",
                "sign-2",
                "verify-2",
                "2023-07-25T00:00:00Z",
                "2026-07-25T00:00:00Z",
            ),
            *_saml_cert_pair(
                "expired-cert", "sign-3", "verify-3", "2022-10-22T00:00:00Z", "2025-10-22T00:00:00Z"
            ),
        ],
    }

    creds = list(
        extract_credentials(
            sp, include_secrets=False, include_certificates=True, object_kind="service_principal"
        )
    )

    assert len(creds) == 1
    assert creds[0].key_id == "sign-1"
    assert creds[0].end_datetime.isoformat() == "2029-02-24T00:00:00+00:00"


def test_extract_credentials_skips_password_credentials_mirroring_saml_certs():
    # Real tenant behavior: a service principal with SAML SSO configured
    # also mirrors each signing certificate's metadata into
    # passwordCredentials (same keyId, but no real secret value) — without
    # filtering, that means every certificate gets double-counted, and the
    # inactive/expired ones (which keyCredentials-side filtering already
    # excludes) reappear via this second path.
    sp = {
        "id": "sp-1",
        "appId": "app-1",
        "displayName": "Contoso SSO App",
        "keyCredentials": [
            *_saml_cert_pair(
                "active-cert", "sign-1", "verify-1", "2026-02-24T00:00:00Z", "2029-02-24T00:00:00Z"
            ),
            *_saml_cert_pair(
                "inactive-cert",
                "sign-2",
                "verify-2",
                "2023-07-25T00:00:00Z",
                "2026-07-25T00:00:00Z",
            ),
        ],
        "passwordCredentials": [
            {
                "keyId": "sign-1",
                "displayName": "CN=mirrored",
                "startDateTime": "2026-02-24T00:00:00Z",
                "endDateTime": "2029-02-24T00:00:00Z",
                "hint": None,
                "secretText": None,
            },
            {
                "keyId": "sign-2",
                "displayName": "CN=mirrored",
                "startDateTime": "2023-07-25T00:00:00Z",
                "endDateTime": "2026-07-25T00:00:00Z",
                "hint": None,
                "secretText": None,
            },
            {
                "keyId": "real-secret",
                "displayName": "an actual client secret",
                "startDateTime": "2024-01-01T00:00:00Z",
                "endDateTime": "2026-01-01T00:00:00Z",
                "hint": "abc",
                "secretText": None,
            },
        ],
    }

    creds = list(
        extract_credentials(
            sp, include_secrets=True, include_certificates=True, object_kind="service_principal"
        )
    )

    key_ids = sorted(c.key_id for c in creds)
    assert key_ids == ["real-secret", "sign-1"]


def test_extract_credentials_does_not_collapse_application_key_credentials():
    # The Sign/Verify collapsing is specific to service principals; a plain
    # App Registration certificate should never be filtered this way.
    app = {
        "id": "obj-1",
        "appId": "app-1",
        "displayName": "My App",
        "keyCredentials": [
            {
                "keyId": "cert-1",
                "displayName": "cert one",
                "startDateTime": "2024-01-01T00:00:00Z",
                "endDateTime": "2026-01-01T00:00:00Z",
            },
            {
                "keyId": "cert-2",
                "displayName": "cert two",
                "startDateTime": "2024-01-01T00:00:00Z",
                "endDateTime": "2027-01-01T00:00:00Z",
            },
        ],
    }

    creds = list(extract_credentials(app, include_secrets=False, include_certificates=True))

    assert len(creds) == 2
