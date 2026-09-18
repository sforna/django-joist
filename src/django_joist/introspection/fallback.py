"""Degraded mode: replay the project's migrations on a throwaway in-memory
SQLite database and introspect *that*.

Used only when the configured database is unreachable. This is a degraded
view: SQLite storage classes replace native types and driver-specific
migrations may not replay cleanly, so the result is flagged (``fallback:
true``) and the UI says so. The replay is graceful per migration: one that
fails on SQLite is recorded as skipped (and faked in the throwaway history so
its dependants are still attempted), never fatal.

The replay must not take the host project down with it: the ``post_migrate``
signal fires during the replay, and the package's rebuild listener skips the
fallback alias so we never introspect-and-cache the throwaway schema under
the real alias.
"""

from __future__ import annotations

import io
import logging
from typing import Any

from django.conf import settings
from django.db import connections

from .builder import FALLBACK_ALIAS_PREFIX

logger = logging.getLogger("joist")


def replay_migrations_on_sqlite(requested_alias: str, builder) -> dict[str, Any]:
    from ..conf import joist_settings

    if not joist_settings.get("fallback.enabled", True):
        return {
            "connection": requested_alias,
            "fallback": False,
            "fallback_error": "connection unreachable and the SQLite fallback is disabled",
            "skipped_migrations": [],
            "tables": [],
        }

    fallback_alias = f"{FALLBACK_ALIAS_PREFIX}{requested_alias}"
    databases = settings.DATABASES
    previous = databases.get(fallback_alias)
    databases[fallback_alias] = {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
        # Explicit defaults: the live DATABASES dict was normalized at first
        # connection, but this late entry never got Django's setdefaults.
        "ATOMIC_REQUESTS": False,
        "AUTOCOMMIT": True,
        "CONN_MAX_AGE": 0,
        "CONN_HEALTH_CHECKS": False,
        "OPTIONS": {},
        "TIME_ZONE": None,
        "TEST": {},
    }
    # Drop any cached connection object for the alias (per-thread).
    try:
        del connections[fallback_alias]
    except Exception:  # noqa: BLE001, S110 - not created yet
        pass

    error: str | None = None
    skipped: list[str] = []
    try:
        connection = connections[fallback_alias]
        connection.ensure_connection()

        from django.core.management import call_command

        try:
            call_command(
                "migrate",
                database=fallback_alias,
                run_syncdb=True,
                verbosity=0,
                no_color=True,
                skip_checks=True,
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )
        except Exception as exc:  # noqa: BLE001 - degrade per migration instead of failing
            logger.debug("joist: fallback replay aborted: %s; retrying per migration", exc)
            error = str(exc)
            skipped = _replay_per_migration(connection, fallback_alias)

        tables = builder.introspect(fallback_alias)
        return {
            "connection": requested_alias,
            "fallback": True,
            "fallback_error": error,
            "skipped_migrations": skipped,
            "tables": builder.serializer.tables(tables),
        }
    except Exception as exc:  # noqa: BLE001 - last resort, never crash the caller
        logger.debug("joist: fallback replay failed entirely: %s", exc)
        return {
            "connection": requested_alias,
            "fallback": True,
            "fallback_error": str(exc),
            "skipped_migrations": skipped,
            "tables": [],
        }
    finally:
        try:
            connections[fallback_alias].close()
            del connections[fallback_alias]
        except Exception:  # noqa: BLE001, S110 - cleanup only
            pass
        if previous is not None:
            databases[fallback_alias] = previous
        else:
            databases.pop(fallback_alias, None)


def _replay_per_migration(connection, alias: str) -> list[str]:
    """Apply the plan one migration at a time, skipping and recording failures.

    A failed migration is faked into the throwaway history so its dependants
    still run: the snapshot is built from whatever replayed successfully.
    """
    from django.db.migrations.executor import MigrationExecutor

    executor = MigrationExecutor(connection)
    plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    skipped: list[str] = []
    for migration, _backwards in plan:
        target = [(migration.app_label, migration.name)]
        try:
            # One executor per target on purpose: its loader snapshots the
            # applied migrations, so a reused one plans the next target from
            # stale state and re-applies what already ran - which is every
            # migration after the first failure, each misfiled as "skipped".
            MigrationExecutor(connection).migrate(target)
        except Exception as exc:  # noqa: BLE001 - graceful per migration
            logger.debug("joist: fallback replay skipped %s.%s: %s", migration.app_label, migration.name, exc)
            skipped.append(f"{migration.app_label}.{migration.name}")
            try:
                executor.recorder.add_record(target)
            except Exception:  # noqa: BLE001, S110
                pass
    return skipped
