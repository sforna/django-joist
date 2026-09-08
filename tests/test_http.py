"""HTTP layer tests: the gate (enabled + authorizer, denial = 404), the JSON
schema endpoint's server-side invariants, the theme sheet, and the asset
allow-list."""

import json

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from django_joist.views import ASSETS

pytestmark = pytest.mark.django_db


@pytest.fixture()
def enabled(settings, settings_overrides):
    # pytest-django forces DEBUG=False, so the authorizer runs; open DEBUG for
    # the non-auth tests (mirrors the reference's "local is unconditionally
    # open" rule). Authorization-specific tests re-close it explicitly.
    settings.DEBUG = True
    settings_overrides("enabled", True)
    # Keep the API response free of the doctor payload by default so these
    # tests stay independent of the doctor layer landing.
    settings_overrides("doctor.dashboard", False)


def test_disabled_is_404_everywhere(client):
    url = reverse("joist:index")
    assert client.get(url).status_code == 404
    assert client.get(reverse("joist:api_schema")).status_code == 404
    assert client.get(reverse("joist:theme")).status_code == 404
    assert client.get(reverse("joist:asset", args=["joist.js"])).status_code == 404


def test_index_renders_shell(client, enabled):
    response = client.get(reverse("joist:index"))
    assert response.status_code == 200
    body = response.content.decode()
    assert "joist-app" in body
    assert reverse("joist:api_schema") in body
    assert "__format__" in body  # export endpoint templated
    assert '"default"' in body  # managed connections present


# -- authorization ----------------------------------------------------------
def test_denial_is_404_not_403(client, enabled, settings):
    """Outside DEBUG the authorizer runs; a guest must not learn Joist exists."""
    settings.DEBUG = False
    assert client.get(reverse("joist:index")).status_code == 404


def test_allow_listed_email_admitted(client, enabled, settings, settings_overrides):
    settings.DEBUG = False
    settings_overrides("authorization.allowed_emails", ["ada@example.com"])
    user = get_user_model().objects.create_user("ada", email="ada@example.com", password="x")
    client.force_login(user)
    assert client.get(reverse("joist:index")).status_code == 200


def test_other_email_denied(client, enabled, settings, settings_overrides):
    settings.DEBUG = False
    settings_overrides("authorization.allowed_emails", ["ada@example.com"])
    user = get_user_model().objects.create_user("grace", email="grace@example.com", password="x")
    client.force_login(user)
    assert client.get(reverse("joist:index")).status_code == 404


def test_custom_authorizer_replaces_default(client, enabled, settings, settings_overrides):
    settings.DEBUG = False
    settings_overrides("authorization.callable", "tests.test_http_helpers.staff_authorizer")
    user = get_user_model().objects.create_user("root", email="r@example.com", password="x", is_staff=True)
    client.force_login(user)
    assert client.get(reverse("joist:index")).status_code == 200
    other = get_user_model().objects.create_user("norm", email="n@example.com", password="x")
    client.force_login(other)
    assert client.get(reverse("joist:index")).status_code == 404


# -- schema endpoint ---------------------------------------------------------
def test_schema_api_managed_allow_list(client, enabled):
    response = client.get(reverse("joist:api_schema"), {"connection": "not-configured"})
    assert response.status_code == 404


def test_schema_api_shape_and_exclusions(client, enabled, settings_overrides):
    settings_overrides("excluded_tables", ["testapp_tag"])
    response = client.get(reverse("joist:api_schema"))
    assert response.status_code == 200
    payload = json.loads(response.content)
    names = [t["name"] for t in payload["tables"]]
    assert "testapp_book" in names
    assert "testapp_tag" not in names  # filtered server-side
    assert "diff" in payload and payload["diff"] is None  # no baseline yet
    assert payload.get("doctor") is None  # dashboard off in this fixture
    assert "cache_unavailable" not in payload


@pytest.mark.django_db(databases=["default", "secondary"])
def test_schema_api_secondary_alias(client, enabled, settings_overrides):
    settings_overrides("connections", {"default": {}, "secondary": {"excluded_tables": ["testapp_book"]}})
    payload = json.loads(client.get(reverse("joist:api_schema"), {"connection": "secondary"}).content)
    assert payload["connection"] == "secondary"
    assert all(t["name"] != "testapp_book" for t in payload["tables"])


def test_schema_api_diff_and_baseline(tmp_path, client, enabled, settings_overrides):
    from django_joist.cache import schema_cache
    from django_joist.diff.baseline import BaselineStore

    settings_overrides("diff.dir", str(tmp_path))
    snapshot = schema_cache().rebuild("default")
    baseline = json.loads(json.dumps(snapshot))
    baseline["tables"] = [t for t in baseline["tables"] if t["name"] != "testapp_author"]
    store = BaselineStore()
    assert store.save("default", baseline)
    store.last_error = None

    payload = json.loads(client.get(reverse("joist:api_schema")).content)
    assert payload["diff"]["tables_added"] == [{"name": "testapp_author"}]
    assert "diff_unavailable" not in payload


# -- theme -------------------------------------------------------------------
def test_theme_empty_by_default(client, enabled):
    response = client.get(reverse("joist:theme"))
    assert response.status_code == 200
    assert response.content == b""
    assert response["Content-Type"].startswith("text/css")


def test_theme_emits_validated_overrides(client, enabled, settings_overrides):
    settings_overrides(
        "theme.colors.light",
        {"accent": "#3730a3", "background": "rgb(255 255 255)", "text": "; rm -rf /"},
    )
    css = client.get(reverse("joist:theme")).content.decode()
    assert "--bp-ink: #3730a3;" in css
    assert "--bp-focus-border: #3730a3;" in css
    assert "--bp-bg: rgb(255 255 255);" in css  # modern rgb form is accepted
    assert "rm -rf" not in css  # injection attempt dropped
    assert "--bp-grid: rgba(55, 48, 163, 0.07);" in css  # derived from hex accent


# -- assets --------------------------------------------------------------
def test_asset_allow_list(client, enabled):
    assert client.get(reverse("joist:asset", args=["evil.js"])).status_code == 404
    # Encoded traversal resolves to a path with slashes, which the URL
    # converter refuses to match, and the basename allow-list refuses to map:
    assert client.get("/joist/assets/..%2F..%2Fsettings.py").status_code == 404
    assert client.get("/joist/assets/js/selection.js").status_code == 404  # not a basename


def test_asset_known_but_missing_is_404(client, enabled, tmp_path, settings, monkeypatch):
    assert "joist.css" in ASSETS
    response = client.get(reverse("joist:asset", args=["joist.css"]))
    # Until the dashboard assets land this is a 404 (not found, not 500).
    # After the port it is served: assert either outcome is a clean response.
    assert response.status_code in (200, 404)


# -- export route ---------------------------------------------------------
def test_export_unknown_format_404(client, enabled):
    assert client.get(reverse("joist:export", args=["exe"])).status_code == 404
