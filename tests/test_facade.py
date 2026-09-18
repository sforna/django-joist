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
    plain = base.to_dbml()
    assert plain != compacted.to_dbml()
    # branching off the same base leaves it untouched
    assert base.to_dbml() == plain


@pytest.mark.django_db
def test_schema_helper_returns_snapshot():
    snap = django_joist.schema("default")
    assert snap["connection"] == "default"
    assert any(t["name"] == "testapp_book" for t in snap["tables"])


@pytest.mark.django_db
def test_post_migrate_refresh_captures_baseline_and_rebuilds(tmp_path, settings_overrides):
    settings_overrides("enabled", True)
    settings_overrides("diff.enabled", True)
    settings_overrides("diff.dir", str(tmp_path))

    from django_joist.diff.baseline import BaselineStore

    cache = schema_cache()
    pre = cache.rebuild("default")  # a snapshot exists cached = "pre-migration" schema

    # Simulate a migrate run: pre_migrate re-arms, post_migrate fires per app.
    # (Receivers called directly: sending the real signal would also drive
    # contenttypes' create_contenttypes, which needs a real app_config sender.)
    signals.rearm_after_migrate(sender=None, using="default")
    signals.rebuild_after_migrate(sender=None, using="default")
    signals.rebuild_after_migrate(sender=None, using="default")  # debounced

    store = BaselineStore()
    baseline = store.get("default")
    assert baseline is not None, "pre-migration snapshot was not captured as baseline"
    assert baseline["generated_at"] == pre["generated_at"]
    assert cache.peek("default") is not None
    assert store.last_error is None


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

    The repository here is hostile on purpose: ``peek`` raises and ``rebuild``
    reports a write failure, which are the two ways the listener could
    otherwise let an exception escape into the migrate run.
    """
    import logging

    settings_overrides("enabled", True)  # arm the listener

    class Hostile:
        last_error = "the cache store is on fire"

        def managed_aliases(self):
            return ["default"]

        def peek(self, alias):
            raise RuntimeError("cannot read the cache")

        def rebuild(self, alias):
            return {"connection": alias, "tables": []}

    monkeypatch.setattr("django_joist.cache.schema_cache", lambda: Hostile())

    with caplog.at_level(logging.WARNING, logger="joist"):
        signals.rearm_after_migrate(sender=None, using="default")
        signals.rebuild_after_migrate(sender=None, using="default")  # must not raise

    assert "could not capture diff baseline" in caplog.text
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
