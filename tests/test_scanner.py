from __future__ import annotations

from azure_secret_watch.scanner import bucket_for, credential_status, scan
from tests.conftest import make_credential


def test_bucket_for_no_warning_when_far_from_expiry():
    cred = make_credential(days_from_now=90)
    assert bucket_for(cred, [30, 14, 7, 1]) is None


def test_bucket_for_picks_smallest_matching_threshold():
    cred = make_credential(days_from_now=10)
    assert bucket_for(cred, [30, 14, 7, 1]) == "14"


def test_bucket_for_exact_threshold_boundary():
    cred = make_credential(days_from_now=7)
    assert bucket_for(cred, [30, 14, 7, 1]) == "7"


def test_bucket_for_expired_credential():
    cred = make_credential(days_from_now=-5)
    assert bucket_for(cred, [30, 14, 7, 1]) == "expired"


def test_bucket_for_unsorted_thresholds_input():
    cred = make_credential(days_from_now=10)
    assert bucket_for(cred, [7, 30, 1, 14]) == "14"


def test_credential_status_ok_warning_expired():
    assert credential_status(make_credential(days_from_now=90), [30, 14, 7, 1]) == "ok"
    assert credential_status(make_credential(days_from_now=10), [30, 14, 7, 1]) == "warning"
    assert credential_status(make_credential(days_from_now=-3), [30, 14, 7, 1]) == "expired"


class _FakeGraphClient:
    def __init__(self, apps, service_principals=None):
        self._apps = apps
        self._service_principals = service_principals or []
        self.owner_lookup_calls = []

    def iter_applications(self):
        return iter(self._apps)

    def iter_service_principals(self):
        return iter(self._service_principals)

    def get_owner_emails(self, object_id, resource="applications"):
        self.owner_lookup_calls.append((object_id, resource))
        return ["owner@example.com"]


def test_scan_returns_full_inventory_and_alerts(state_db_path):
    from azure_secret_watch.state_store import StateStore

    apps = [
        {
            "id": "obj-1",
            "appId": "app-1",
            "displayName": "App 1",
            "passwordCredentials": [
                {
                    "keyId": "far-future",
                    "displayName": "safe secret",
                    "startDateTime": "2020-01-01T00:00:00Z",
                    "endDateTime": "2099-01-01T00:00:00Z",
                },
                {
                    "keyId": "soon",
                    "displayName": "expiring secret",
                    "startDateTime": "2020-01-01T00:00:00Z",
                    "endDateTime": "2020-01-05T00:00:00Z",
                },
            ],
            "keyCredentials": [],
        }
    ]
    graph_client = _FakeGraphClient(apps)
    state_store = StateStore(state_db_path)

    result = scan(
        graph_client=graph_client,
        state_store=state_store,
        warning_thresholds_days=[30, 14, 7, 1],
        include_secrets=True,
        include_certificates=True,
        expired_reminder_interval_days=7,
        notify_owners=False,
        include_enterprise_apps=False,
    )

    assert len(result.credentials) == 2
    assert len(result.alerts) == 1
    assert result.alerts[0].credential.key_id == "soon"
    assert result.alerts[0].owners == []
    assert result.owners_by_app == {}


def test_scan_notify_owners_populates_owner_list(state_db_path):
    from azure_secret_watch.state_store import StateStore

    apps = [
        {
            "id": "obj-1",
            "appId": "app-1",
            "displayName": "App 1",
            "passwordCredentials": [
                {
                    "keyId": "soon",
                    "displayName": "expiring secret",
                    "startDateTime": "2020-01-01T00:00:00Z",
                    "endDateTime": "2020-01-05T00:00:00Z",
                }
            ],
            "keyCredentials": [],
        }
    ]
    graph_client = _FakeGraphClient(apps)
    state_store = StateStore(state_db_path)

    result = scan(
        graph_client=graph_client,
        state_store=state_store,
        warning_thresholds_days=[30, 14, 7, 1],
        include_secrets=True,
        include_certificates=True,
        expired_reminder_interval_days=7,
        notify_owners=True,
        include_enterprise_apps=False,
    )

    assert result.alerts[0].owners == ["owner@example.com"]
    assert result.owners_by_app == {"obj-1": ["owner@example.com"]}


def test_scan_notify_owners_covers_full_inventory_and_caches_per_app(state_db_path):
    from azure_secret_watch.state_store import StateStore

    apps = [
        {
            "id": "obj-1",
            "appId": "app-1",
            "displayName": "App 1",
            "passwordCredentials": [
                {
                    "keyId": "far-future",
                    "displayName": "safe secret",
                    "startDateTime": "2020-01-01T00:00:00Z",
                    "endDateTime": "2099-01-01T00:00:00Z",
                },
                {
                    "keyId": "also-far-future",
                    "displayName": "another safe secret",
                    "startDateTime": "2020-01-01T00:00:00Z",
                    "endDateTime": "2099-01-01T00:00:00Z",
                },
            ],
            "keyCredentials": [],
        }
    ]
    graph_client = _FakeGraphClient(apps)
    state_store = StateStore(state_db_path)

    result = scan(
        graph_client=graph_client,
        state_store=state_store,
        warning_thresholds_days=[30, 14, 7, 1],
        include_secrets=True,
        include_certificates=True,
        expired_reminder_interval_days=7,
        notify_owners=True,
        include_enterprise_apps=False,
    )

    # Neither credential triggered an alert, but owners are still collected
    # for the whole inventory, and only fetched once per app (cached).
    assert result.alerts == []
    assert result.owners_by_app == {"obj-1": ["owner@example.com"]}
    assert graph_client.owner_lookup_calls == [("obj-1", "applications")]


def test_scan_includes_enterprise_app_saml_certificates(state_db_path):
    from azure_secret_watch.state_store import StateStore

    service_principals = [
        {
            "id": "sp-obj-1",
            "appId": "sp-app-1",
            "displayName": "Newegg NAS",
            "passwordCredentials": [],
            "keyCredentials": [
                {
                    "keyId": "saml-cert-1",
                    "displayName": "SAML signing certificate",
                    "startDateTime": "2020-01-01T00:00:00Z",
                    "endDateTime": "2020-01-05T00:00:00Z",
                }
            ],
        }
    ]
    graph_client = _FakeGraphClient([], service_principals=service_principals)
    state_store = StateStore(state_db_path)

    result = scan(
        graph_client=graph_client,
        state_store=state_store,
        warning_thresholds_days=[30, 14, 7, 1],
        include_secrets=True,
        include_certificates=True,
        expired_reminder_interval_days=7,
        notify_owners=False,
        include_enterprise_apps=True,
    )

    assert len(result.credentials) == 1
    cred = result.credentials[0]
    assert cred.object_kind == "service_principal"
    assert cred.app_display_name == "Newegg NAS"
    assert len(result.alerts) == 1
    assert result.alerts[0].credential.key_id == "saml-cert-1"


def test_scan_skips_service_principals_when_disabled(state_db_path):
    from azure_secret_watch.state_store import StateStore

    service_principals = [
        {
            "id": "sp-obj-1",
            "appId": "sp-app-1",
            "displayName": "Newegg NAS",
            "passwordCredentials": [],
            "keyCredentials": [
                {
                    "keyId": "saml-cert-1",
                    "displayName": "SAML signing certificate",
                    "startDateTime": "2020-01-01T00:00:00Z",
                    "endDateTime": "2020-01-05T00:00:00Z",
                }
            ],
        }
    ]
    graph_client = _FakeGraphClient([], service_principals=service_principals)
    state_store = StateStore(state_db_path)

    result = scan(
        graph_client=graph_client,
        state_store=state_store,
        warning_thresholds_days=[30, 14, 7, 1],
        include_secrets=True,
        include_certificates=True,
        expired_reminder_interval_days=7,
        notify_owners=False,
        include_enterprise_apps=False,
    )

    assert result.credentials == []
    assert result.alerts == []


def test_scan_notify_owners_uses_service_principals_resource_for_enterprise_apps(state_db_path):
    from azure_secret_watch.state_store import StateStore

    service_principals = [
        {
            "id": "sp-obj-1",
            "appId": "sp-app-1",
            "displayName": "Newegg NAS",
            "passwordCredentials": [],
            "keyCredentials": [
                {
                    "keyId": "saml-cert-1",
                    "displayName": "SAML signing certificate",
                    "startDateTime": "2020-01-01T00:00:00Z",
                    "endDateTime": "2020-01-05T00:00:00Z",
                }
            ],
        }
    ]
    graph_client = _FakeGraphClient([], service_principals=service_principals)
    state_store = StateStore(state_db_path)

    scan(
        graph_client=graph_client,
        state_store=state_store,
        warning_thresholds_days=[30, 14, 7, 1],
        include_secrets=True,
        include_certificates=True,
        expired_reminder_interval_days=7,
        notify_owners=True,
        include_enterprise_apps=True,
    )

    assert graph_client.owner_lookup_calls == [("sp-obj-1", "servicePrincipals")]
