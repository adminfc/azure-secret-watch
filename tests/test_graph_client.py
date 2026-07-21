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
