from __future__ import annotations

from tests.conftest import make_credential


def test_portal_url_for_application_points_at_app_registration_blade():
    cred = make_credential(days_from_now=10, app_id="app-1", object_kind="application")
    assert "Microsoft_AAD_RegisteredApps" in cred.portal_url
    assert "app-1" in cred.portal_url


def test_portal_url_for_service_principal_points_at_enterprise_app_sso_blade():
    cred = make_credential(
        days_from_now=10,
        app_id="app-1",
        app_object_id="sp-obj-1",
        object_kind="service_principal",
    )
    url = cred.portal_url
    assert "Microsoft_AAD_IAM/ManagedAppMenuBlade/~/SignOn" in url
    assert "objectId/sp-obj-1" in url
    assert "appId/app-1" in url
    assert "preferredSingleSignOnMode/saml" in url
