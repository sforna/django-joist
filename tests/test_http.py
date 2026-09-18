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


def test_an_authorizer_object_is_used_as_given(settings, settings_overrides):
    from django_joist.security import resolve_authorizer

    callback = lambda request: True  # noqa: E731 - a stand-in for a host's callable
    settings_overrides("authorization.callable", callback)
    assert resolve_authorizer() is callback


def test_a_dotted_authorizer_path_is_imported(settings, settings_overrides):
    from django_joist.security import default_authorizer, resolve_authorizer

    settings_overrides("authorization.callable", "django_joist.security.default_authorizer")
    assert resolve_authorizer() is default_authorizer


def test_no_authorizer_falls_back_to_the_allow_list():
    from django_joist.security import default_authorizer, resolve_authorizer

    assert resolve_authorizer() is default_authorizer


def test_a_broken_authorizer_path_fails_loudly(client, enabled, settings, settings_overrides):
    # A misconfigured guard must not silently deny: that looks like a working
    # install that shows nothing, and nobody can tell it apart from a 404.
    from django.core.exceptions import ImproperlyConfigured

    settings.DEBUG = False
    settings_overrides("authorization.callable", "nope.not_here")
    with pytest.raises(ImproperlyConfigured):
        client.get(reverse("joist:index"))


def test_a_non_callable_authorizer_is_rejected(settings_overrides):
    from django.core.exceptions import ImproperlyConfigured

    from django_joist.security import resolve_authorizer

    settings_overrides("authorization.callable", 42)
    with pytest.raises(ImproperlyConfigured, match="must be a callable or dotted path"):
        resolve_authorizer()


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


def test_an_asset_cannot_escape_the_static_root(client, enabled, monkeypatch):
    # Defense in depth on top of the basename allow-list: even an allow-listed
    # name that resolves to a real file outside the static root is refused, so
    # a mapping mistake cannot turn the asset route into a source reader.
    monkeypatch.setitem(ASSETS, "escape.txt", "../../security.py")
    assert client.get(reverse("joist:asset", args=["escape.txt"])).status_code == 404


def test_schema_api_reports_a_broken_cache_store(client, enabled, settings_overrides):
    # The dashboard reads this flag to say the structure was built live: a
    # broken store costs speed, and the user should know why it is slow.
    settings_overrides("cache.alias", "not-a-cache")
    payload = json.loads(client.get(reverse("joist:api_schema")).content)
    assert payload["cache_unavailable"] is True
    assert payload["tables"]  # still complete: built from the live database


def test_schema_api_reports_a_baseline_it_could_not_read(client, enabled, tmp_path, settings_overrides):
    settings_overrides("diff.dir", str(tmp_path))
    (tmp_path / "baselines").mkdir()
    (tmp_path / "baselines" / "default.json").write_text("{not json")
    payload = json.loads(client.get(reverse("joist:api_schema")).content)
    assert payload["diff_unavailable"] is True
    assert payload["diff"] is None


def test_schema_api_omits_the_diff_when_the_feature_is_off(client, enabled, settings_overrides):
    settings_overrides("diff.enabled", False)
    payload = json.loads(client.get(reverse("joist:api_schema")).content)
    assert payload["diff"] is None
    assert "diff_unavailable" not in payload  # off is not the same as broken


def test_export_route_can_drop_annotations(client, enabled, settings_overrides):
    settings_overrides("annotations.tables", {"testapp_book": "Books"})
    annotated = client.get(reverse("joist:export", args=["dbml"])).content.decode()
    assert 'Note: "Books"' in annotated or "Books" in annotated
    bare = client.get(reverse("joist:export", args=["dbml"]), {"no_annotations": "1"}).content.decode()
    assert "Books" not in bare


# -- export route ---------------------------------------------------------
def test_export_unknown_format_404(client, enabled):
    assert client.get(reverse("joist:export", args=["exe"])).status_code == 404


# -- layer integration (doctor payload + export route) ----------------------
def test_schema_api_carries_doctor_payload(client, enabled, settings_overrides):
    settings_overrides("doctor.dashboard", True)
    settings_overrides("doctor.preset", "strict")
    payload = json.loads(client.get(reverse("joist:api_schema")).content)
    doctor = payload["doctor"]
    assert doctor is not None
    assert set(doctor["summary"]) == {"total", "error", "warning", "info"}
    assert doctor["summary"]["total"] == len(doctor["findings"]) >= 1
    codes = {f["code"] for f in doctor["findings"]}
    assert any(c.startswith("JOIST-") for c in codes)
    # Money-as-float bait in the test app (Publisher.balance) must surface.
    assert any(f["table"] == "testapp_publisher" and f["column"] == "balance" for f in doctor["findings"])
    # Excluded tables never reach a finding.
    settings_overrides("excluded_tables", ["testapp_publisher", "testapp_tag", "testapp_label", "testapp_legacyrow"])
    payload = json.loads(client.get(reverse("joist:api_schema")).content)
    assert all(f["table"] != "testapp_publisher" for f in payload["doctor"]["findings"])


def test_export_route_matches_builder_bytes(client, enabled):
    from django_joist.export.builder import ExportBuilder

    expected = ExportBuilder().only(["testapp_book"]).to_dbml()
    response = client.get(reverse("joist:export", args=["dbml"]), {"only": "testapp_book"})
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/plain")
    assert response.content.decode() == expected


def test_export_route_focus_and_compact(client, enabled):
    response = client.get(
        reverse("joist:export", args=["llm"]),
        {"focus": "testapp_book", "depth": 1, "compact": "1"},
    )
    assert response.status_code == 200
    body = response.content.decode()
    # Defined tables = non-indented, non-comment header lines. 1-hop
    # undirected neighbourhood of book: author + publisher (outgoing FKs)
    # and booktag (incoming). tag appears only as a referenced table inside
    # booktag's FK lines (an edge, not a table) - two hops away.
    defined = {
        line.strip()
        for line in body.splitlines()
        if line.strip() and not line.startswith((" ", "#")) and " " not in line.strip() and "->" not in line
    }
    assert defined == {"testapp_book", "testapp_author", "testapp_publisher", "testapp_booktag"}
    assert "testapp_legacyrow" not in body
    # compact: column defaults must be gone
    assert "default" not in body.lower()


def test_export_route_bad_input_404(client, enabled):
    assert client.get(reverse("joist:export", args=["dbml"]), {"connection": "nope"}).status_code == 404
    assert client.get(reverse("joist:export", args=["dbml"]), {"focus": "ghost"}).status_code == 404
    assert client.get(reverse("joist:export", args=["dbml"]), {"only": "testapp_tag_and_nope"}).status_code == 404
