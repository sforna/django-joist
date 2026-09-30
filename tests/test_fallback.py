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


@pytest.fixture(autouse=True)
def opt_in_to_fallback(settings_overrides):
    settings_overrides("fallback.enabled", True)


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


def test_unreachable_connection_does_not_replay_without_opt_in(unreachable, settings_overrides, monkeypatch):
    settings_overrides("fallback.enabled", False)

    def unexpected_migration(*args, **kwargs):
        raise AssertionError("fallback must not execute migrations")

    monkeypatch.setattr("django.core.management.call_command", unexpected_migration)
    with pytest.raises(OperationalError, match="Connection refused"):
        SnapshotBuilder().build(unreachable)


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
    assert cache._cache().get(cache.key("ghost")) is None
    assert cache._cache().get(cache.key(f"{FALLBACK_ALIAS_PREFIX}ghost")) is None
    # The replay's own migrate emits post_migrate, so the listener did run and
    # had to skip the whole thing: without that skip it would fall through to
    # the managed aliases and cache a schema nobody asked for, mid-replay.
    assert cache.peek("default") is None


def test_fallback_retries_per_migration_when_the_run_aborts(monkeypatch, django_db_blocker):
    def exploding_migrate(*args, **kwargs):
        raise RuntimeError("one migration is not SQLite compatible")

    monkeypatch.setattr("django.core.management.call_command", exploding_migrate)

    original = MigrationExecutor.apply_migration
    failed = ("contenttypes", "0001_initial")

    def apply_migration(self, state, migration, fake=False, fake_initial=False):
        # Fail the *same* migration every time it is attempted, not once: only
        # the faked record lets a later fresh executor skip it. Without that
        # record every target after it replays the dependency and fails too.
        if (migration.app_label, migration.name) == failed:
            raise RuntimeError("unsupported on SQLite")
        return original(self, state, migration, fake=fake, fake_initial=fake_initial)

    monkeypatch.setattr(MigrationExecutor, "apply_migration", apply_migration)

    with django_db_blocker.unblock():
        snapshot = replay_migrations_on_sqlite("ghost", SnapshotBuilder())
    assert snapshot["fallback"] is True
    assert snapshot["fallback_error"] == "one migration is not SQLite compatible"
    # The failed migration is faked into the throwaway history, so the run
    # continues from it: reported first, and the project's own schema still
    # gets built. If the faking silently did nothing, every later target would
    # replay the dependency and fail with it, and testapp would come back empty.
    assert snapshot["skipped_migrations"][0] == "contenttypes.0001_initial"
    assert "testapp_book" in [t["name"] for t in snapshot["tables"]]


# -- the doctor on a replay --------------------------------------------------
def test_the_doctor_on_a_replay_judges_the_live_backend(django_db_blocker):
    # The replay is SQLite whatever the alias's own vendor, so on the
    # PostgreSQL and MySQL lanes this is a server's alias carrying SQLite's
    # types. As in the reference, the rules are told the live vendor; only
    # JOIST-INT-003 reads the types as SQLite's, or Django's integer primary
    # key and bigint foreign keys would be an error on every key. So the
    # verdict is the SQLite lane's structure, with the unindexed key judged as
    # the live backend would: an error, or info on MySQL, which indexes it.
    from django_joist.doctor import findings_for
    from tests.test_backends import DOCTOR_VERDICT, LANE

    unindexed = ("error", "JOIST-IDX-001", "testapp_fkaction", "author_id")
    expected = set(DOCTOR_VERDICT["sqlite"])
    if LANE == "mysql":
        expected = (expected - {unindexed}) | {("info", *unindexed[1:])}

    with django_db_blocker.unblock():
        snapshot = replay_migrations_on_sqlite("default", SnapshotBuilder())
        findings = findings_for("default", snapshot, preset="strict")
    assert snapshot["fallback"] is True
    verdict = {
        (f.severity.value, f.code, f.table, f.column)
        for f in findings
        if f.table.startswith("testapp_")
    }
    assert verdict == expected
    assert [f for f in findings if f.code == "JOIST-INT-003"] == []
