"""Package-level facade and signal integration: the documented public API and
the post-migrate rebuild / baseline-capture behaviour."""

import pytest

import django_joist
from django_joist import signals
from django_joist.cache import schema_cache


@pytest.mark.django_db
def test_facade_snapshot_fluent_pipeline():
    text = (
        django_joist.snapshot()
        .only(["testapp_book", "testapp_author"])
        .focus("testapp_book", depth=1)
        .compact()
        .to_dbml()
    )
    assert "Table testapp_book" in text
    assert "Table testapp_author" in text
    assert "testapp_publisher" not in text  # only() wins over the focus neighbourhood
    assert "[default" not in text  # compact() dropped column defaults


@pytest.mark.django_db
def test_facade_builder_is_immutable_and_branchable():
    base = django_joist.snapshot().only(["testapp_book"])
    compacted = base.compact()
    # Markdown so the difference is backend-independent: compact() clears the
    # internal index name, which exists under the same name everywhere, while
    # column defaults and per-column FK indexes do not.
    plain = base.to_markdown()
    assert plain != compacted.to_markdown()
    # branching off the same base leaves it untouched
    assert base.to_markdown() == plain


@pytest.mark.django_db
def test_schema_helper_returns_snapshot():
    snap = django_joist.schema("default")
    assert snap["connection"] == "default"
    assert any(t["name"] == "testapp_book" for t in snap["tables"])


@pytest.mark.django_db
def test_post_migrate_refresh_captures_baseline_and_rebuilds(tmp_path, settings_overrides, monkeypatch):
    settings_overrides("enabled", True)
    settings_overrides("diff.enabled", True)
    settings_overrides("diff.dir", str(tmp_path))

    from django_joist.diff.baseline import BaselineStore

    cache = schema_cache()
    assert cache.peek("default") is None  # no cached baseline to rely on

    # Simulate a migrate run: pre_migrate re-arms, post_migrate fires per app.
    # (Receivers called directly: sending the real signal would also drive
    # contenttypes' create_contenttypes, which needs a real app_config sender.)
    signals.rearm_after_migrate(sender=None, using="default")
    pre = cache.peek("default")
    assert pre is not None

    original_rebuild = cache.rebuild

    def migrated(alias):
        after = original_rebuild(alias)
        after["tables"].append({"name": "new_table"})
        return after

    monkeypatch.setattr(cache, "rebuild", migrated)
    signals.rebuild_after_migrate(sender=None, using="default")
    signals.rebuild_after_migrate(sender=None, using="default")  # debounced

    store = BaselineStore()
    baseline = store.get("default")
    assert baseline is not None, "pre-migration snapshot was not captured as baseline"
    assert baseline["tables"] == pre["tables"]
    assert cache.peek("default") is not None
    assert store.last_error is None


@pytest.mark.django_db
def test_noop_migrate_and_flush_keep_the_previous_baseline(tmp_path, settings_overrides):
    from django_joist.diff.baseline import BaselineStore

    settings_overrides("enabled", True)
    settings_overrides("diff.dir", str(tmp_path))
    store = BaselineStore()
    older = {"connection": "default", "tables": []}
    assert store.save("default", older)

    signals.rearm_after_migrate(sender=None, using="default")
    signals.rearm_after_migrate(sender=None, using="default")  # another app
    signals.rebuild_after_migrate(sender=None, using="default")
    signals.rebuild_after_migrate(sender=None, using="default")  # another app
    signals.rebuild_after_migrate(sender=None, using="default")  # flush has no pre_migrate

    assert store.get("default") == older


@pytest.mark.django_db(databases=["default", "secondary"])
def test_migrate_on_unmanaged_alias_does_not_refresh_managed_alias(settings_overrides):
    settings_overrides("enabled", True)
    settings_overrides("connections", {"secondary": {}})
    cache = schema_cache()

    signals.rearm_after_migrate(sender=None, using="default")
    signals.rebuild_after_migrate(sender=None, using="default")

    assert cache.peek("secondary") is None


@pytest.mark.django_db
def test_post_migrate_skips_fallback_alias(tmp_path, settings_overrides):
    settings_overrides("enabled", True)
    settings_overrides("diff.dir", str(tmp_path))

    from django_joist.diff.baseline import BaselineStore
    from django_joist.introspection.builder import FALLBACK_ALIAS_PREFIX

    schema_cache().rebuild("default")
    ghost = FALLBACK_ALIAS_PREFIX + "default"
    signals.rebuild_after_migrate(sender=None, using=ghost)
    assert BaselineStore().get(ghost) is None
    assert not (tmp_path / "baselines").exists() or list((tmp_path / "baselines").iterdir()) == []


def test_post_migrate_survives_a_hostile_cache(monkeypatch, caplog, settings_overrides):
    """A migrate that already succeeded must not fail because of Joist.

    The repository here is hostile on purpose: the pre-migration read raises
    and the post-migration rebuild reports a write failure, either of which could
    otherwise let an exception escape into the migrate run.
    """
    import logging

    settings_overrides("enabled", True)  # arm the listener

    class Hostile:
        last_error = "the cache store is on fire"
        calls = 0

        def managed_aliases(self):
            return ["default"]

        def rebuild(self, alias):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("cannot read the schema")
            return {"connection": alias, "tables": []}

    hostile = Hostile()
    monkeypatch.setattr("django_joist.cache.schema_cache", lambda: hostile)

    with caplog.at_level(logging.WARNING, logger="joist"):
        signals.rearm_after_migrate(sender=None, using="default")
        signals.rebuild_after_migrate(sender=None, using="default")  # must not raise

    assert "could not capture schema before migration" in caplog.text
    assert "could not cache it" in caplog.text


def test_post_migrate_never_lets_a_rebuild_failure_escape(monkeypatch, caplog, settings_overrides):
    """The outer safety net: whatever the refresh raises, migrate keeps going."""
    import logging

    settings_overrides("enabled", True)

    class Exploding:
        last_error = None

        def managed_aliases(self):
            return ["default"]

        def peek(self, alias):
            return None

        def rebuild(self, alias):
            raise RuntimeError("the database went away")

    monkeypatch.setattr("django_joist.cache.schema_cache", lambda: Exploding())

    with caplog.at_level(logging.WARNING, logger="joist"):
        signals.rearm_after_migrate(sender=None, using="default")
        signals.rebuild_after_migrate(sender=None, using="default")  # must not raise

    assert "post-migration refresh failed for [default]" in caplog.text


# -- payload(): the dashboard payload in process ------------------------------
@pytest.fixture()
def http_enabled(settings, settings_overrides):
    settings.DEBUG = True  # DEBUG opens the gate, so the HTTP side can be compared
    settings_overrides("enabled", True)


@pytest.mark.django_db
def test_payload_equals_what_the_endpoint_serves(client, http_enabled, settings_overrides, tmp_path):
    import json

    from django.urls import reverse

    from django_joist.diff.baseline import BaselineStore

    # Every part of the envelope populated: exclusions, a real diff and the
    # doctor, so equality covers the whole assembly rather than an empty shape.
    settings_overrides("excluded_tables", ["testapp_tag"])
    settings_overrides("diff.dir", str(tmp_path))
    settings_overrides("doctor.dashboard", True)
    baseline = json.loads(json.dumps(schema_cache().rebuild("default")))
    baseline["tables"] = [t for t in baseline["tables"] if t["name"] != "testapp_author"]
    assert BaselineStore().save("default", baseline)

    served = json.loads(client.get(reverse("joist:api_schema")).content)
    in_process = json.loads(json.dumps(django_joist.payload()))
    assert in_process == served
    assert in_process["diff"]["tables_added"] == [{"name": "testapp_author"}]
    assert in_process["doctor"]["findings"]
    assert all(t["name"] != "testapp_tag" for t in in_process["tables"])


@pytest.mark.django_db
def test_payload_is_not_the_raw_schema(settings_overrides):
    settings_overrides("excluded_tables", ["testapp_tag"])
    settings_overrides("diff.enabled", False)
    settings_overrides("doctor.dashboard", False)

    raw = django_joist.schema()
    shaped = django_joist.payload()
    assert any(t["name"] == "testapp_tag" for t in raw["tables"])
    assert all(t["name"] != "testapp_tag" for t in shaped["tables"])
    assert "diff" not in raw and shaped["diff"] is None
    assert "doctor" not in raw and shaped["doctor"] is None


@pytest.mark.django_db
def test_payload_runs_without_the_dashboard_enabled(settings_overrides):
    # No authorization and no enabled gate: that belongs to whatever page
    # exposes the result, as with snapshot() and schema().
    settings_overrides("enabled", False)
    assert django_joist.payload()["connection"] == "default"


@pytest.mark.django_db
def test_payload_refuses_an_unmanaged_alias():
    with pytest.raises(ValueError, match="not managed"):
        django_joist.payload("not-configured")


@pytest.mark.django_db
def test_payload_does_not_mutate_a_snapshot_the_cache_hands_out(monkeypatch, settings_overrides):
    settings_overrides("excluded_tables", ["testapp_tag"])
    settings_overrides("doctor.dashboard", False)
    cache = schema_cache()
    shared = cache.rebuild("default")
    monkeypatch.setattr(cache, "get", lambda alias=None: shared)

    django_joist.payload()
    assert "diff" not in shared and "doctor" not in shared
    assert any(t["name"] == "testapp_tag" for t in shared["tables"])


@pytest.mark.django_db
def test_json_script_writes_the_block_the_dashboard_reads(settings_overrides):
    # The embedding contract is Django's own filter, not markup a host has to
    # hand-write: pin that it still produces the element schema-source.js
    # selects (script#joist-payload[type="application/json"]) and escapes a
    # value that would otherwise end the block early.
    import re

    from django.template import Context, Template

    settings_overrides("doctor.dashboard", False)
    data = django_joist.payload()
    data["tables"].append({"name": "t", "columns": [{"name": "c", "default": "</script><b>&"}]})
    html = Template('{{ data|json_script:"joist-payload" }}').render(Context({"data": data}))

    opening = re.match(r"<script ([^>]*)>", html)
    assert opening is not None
    assert set(opening.group(1).split()) == {'id="joist-payload"', 'type="application/json"'}
    assert html.count("</script>") == 1 and html.endswith("</script>")
    assert "\\u003C/script\\u003E\\u003Cb\\u003E\\u0026" in html
