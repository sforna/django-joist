"""Degraded mode: the throwaway-SQLite replay behind ``fallback: true``.

The trigger is the one part that cannot run faithfully in this lane: an
unreachable server needs a real backend (see the PostgreSQL/MySQL gap in
TRUSS-LACKS.md), so the connectivity error is injected. Everything downstream
runs for real - the replay, the per-migration retry, the introspection of the
throwaway database, and the post-migrate listener refusing to cache it.

These tests are deliberately outside ``django_db``: the database under test is
the throwaway one the replay builds for itself, so what they need unblocked is
database access as such, not the test database's schema.
"""

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db import InterfaceError, OperationalError, ProgrammingError
from django.db.migrations.executor import MigrationExecutor

from django_joist.cache import schema_cache
from django_joist.introspection.builder import FALLBACK_ALIAS_PREFIX, SnapshotBuilder
from django_joist.introspection.fallback import replay_migrations_on_sqlite


@pytest.fixture()
def unreachable(monkeypatch):
    """Make one alias look unreachable, leaving the throwaway alias working.

    Only the live connection is stubbed: the replay below really runs
    ``migrate`` and really introspects the in-memory database it builds.
    """
    original = SnapshotBuilder.introspect

    def introspect(self, alias):
        if alias == "ghost":
            raise OperationalError("could not connect to server: Connection refused")
        return original(self, alias)

    monkeypatch.setattr(SnapshotBuilder, "introspect", introspect)
    return "ghost"


# -- the trigger -------------------------------------------------------------
def test_build_falls_back_when_the_connection_is_unreachable(unreachable, django_db_blocker):
    with django_db_blocker.unblock():
        snapshot = SnapshotBuilder().build(unreachable)
    assert snapshot["connection"] == "ghost"  # reported under the alias asked for
    assert snapshot["fallback"] is True
    assert snapshot["fallback_error"] is None
    assert snapshot["skipped_migrations"] == []
    assert "testapp_book" in [t["name"] for t in snapshot["tables"]]


def test_build_reraises_a_failure_that_is_not_connectivity(monkeypatch, django_db_blocker):
    def introspect(self, alias):
        raise ProgrammingError("permission denied for table pg_class")

    monkeypatch.setattr(SnapshotBuilder, "introspect", introspect)
    # A failure *after* a successful connect is a real error: degrading to a
    # replay would hide a broken catalog behind a plausible-looking diagram.
    with django_db_blocker.unblock(), pytest.raises(ProgrammingError):
        SnapshotBuilder().build("ghost")


@pytest.mark.parametrize(
    "exc",
    [
        OperationalError("unable to open database file"),
        InterfaceError("connection already closed"),
        ImproperlyConfigured("no driver for postgresql"),
    ],
)
def test_connectivity_errors_trigger_the_fallback(exc):
    assert SnapshotBuilder._is_connectivity_error(exc) is True


@pytest.mark.parametrize(
    "exc",
    [
        ProgrammingError("bad query"),
        RuntimeError("anything else"),
        ValueError("not a db error"),
    ],
)
def test_other_errors_are_not_connectivity(exc):
    assert SnapshotBuilder._is_connectivity_error(exc) is False


# -- the replay --------------------------------------------------------------
def test_fallback_snapshot_is_the_replayed_structure(django_db_blocker):
    with django_db_blocker.unblock():
        snapshot = replay_migrations_on_sqlite("ghost", SnapshotBuilder())
    tables = {t["name"]: t for t in snapshot["tables"]}

    assert snapshot["fallback"] is True
    assert snapshot["fallback_error"] is None
    assert {"testapp_book", "testapp_author", "django_migrations"} <= set(tables)

    book = tables["testapp_book"]
    assert "title" in [c["name"] for c in book["columns"]]
    (fk,) = [f for f in book["foreign_keys"] if f["columns"] == ["author_id"]]
    assert fk["references_table"] == "testapp_author"
    # The introspection layer stamps nothing: generated_at belongs to the cache.
    assert "generated_at" not in snapshot


def test_fallback_is_skipped_when_disabled(settings_overrides):
    settings_overrides("fallback.enabled", False)
    snapshot = replay_migrations_on_sqlite("ghost", SnapshotBuilder())
    assert snapshot["fallback"] is False
    assert "fallback is disabled" in snapshot["fallback_error"]
    assert snapshot["tables"] == []


def test_fallback_leaves_the_databases_setting_as_it_found_it(django_db_blocker):
    from django.conf import settings as django_settings

    alias = f"{FALLBACK_ALIAS_PREFIX}ghost"
    assert alias not in django_settings.DATABASES

    with django_db_blocker.unblock():
        replay_migrations_on_sqlite("ghost", SnapshotBuilder())
    assert alias not in django_settings.DATABASES  # the throwaway entry is gone

    # An entry that was already there is restored, not deleted.
    django_settings.DATABASES[alias] = {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": "preserved",
    }
    try:
        with django_db_blocker.unblock():
            replay_migrations_on_sqlite("ghost", SnapshotBuilder())
        assert django_settings.DATABASES[alias]["NAME"] == "preserved"
    finally:
        del django_settings.DATABASES[alias]


def test_fallback_never_caches_the_throwaway_schema(settings_overrides, django_db_blocker):
    settings_overrides("enabled", True)  # arm the post-migrate listener
    with django_db_blocker.unblock():
        replay_migrations_on_sqlite("ghost", SnapshotBuilder())

    cache = schema_cache()
    assert cache.peek("ghost") is None
    assert cache.peek(f"{FALLBACK_ALIAS_PREFIX}ghost") is None
    # The replay's own migrate emits post_migrate, so the listener did run and
    # had to skip the whole thing: without that skip it would fall through to
    # the managed aliases and cache a schema nobody asked for, mid-replay.
    assert cache.peek("default") is None


def test_fallback_retries_per_migration_when_the_run_aborts(monkeypatch, django_db_blocker):
    def exploding_migrate(*args, **kwargs):
        raise RuntimeError("one migration is not SQLite compatible")

    monkeypatch.setattr("django.core.management.call_command", exploding_migrate)

    original = MigrationExecutor.migrate
    failed_once = []

    def migrate(self, targets, *args, **kwargs):
        # Fail the first migration only: the rest must still replay, and the
        # failed one must be recorded instead of taking the snapshot down.
        if not failed_once:
            failed_once.append(targets)
            raise RuntimeError("unsupported on SQLite")
        return original(self, targets, *args, **kwargs)

    monkeypatch.setattr(MigrationExecutor, "migrate", migrate)

    with django_db_blocker.unblock():
        snapshot = replay_migrations_on_sqlite("ghost", SnapshotBuilder())
    assert snapshot["fallback"] is True
    assert snapshot["fallback_error"] == "one migration is not SQLite compatible"
    # Only the migration that actually failed is recorded: the run continued
    # from there instead of re-applying what the fresh executor already knew.
    assert snapshot["skipped_migrations"] == ["contenttypes.0001_initial"]
    assert "testapp_book" in [t["name"] for t in snapshot["tables"]]
