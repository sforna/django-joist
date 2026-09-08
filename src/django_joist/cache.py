"""Reads and writes the schema snapshot via Django's cache framework.

The snapshot is derived, disposable data, keyed per alias — no database table
is used to store it. This is the layer that stamps ``generated_at``: the
introspection layer stays deterministic and timestamp-free.

Every cache operation degrades instead of throwing, for the same reason the
baseline store does it for the filesystem: the store is somebody else's
infrastructure, and an unusable one must not break things that do not depend
on it. The snapshot is always rebuildable from the live database, so a broken
store costs speed, never correctness. ``last_error`` lets a caller that can
act on it say something useful.
"""

from __future__ import annotations

import logging
from typing import Any

from django.core.cache import caches
from django.db import DEFAULT_DB_ALIAS
from django.utils import timezone

from .conf import joist_settings
from .introspection import SnapshotBuilder

logger = logging.getLogger("joist")


class SchemaCacheRepository:
    def __init__(self, builder: SnapshotBuilder | None = None) -> None:
        self.builder = builder or SnapshotBuilder()
        self.last_error: str | None = None

    # -- addressing --------------------------------------------------------
    def key(self, alias: str) -> str:
        prefix = joist_settings.get("cache.key_prefix", "joist")
        return f"{prefix}:schema:{alias}"

    def _cache(self):
        return caches[joist_settings.get("cache.alias") or "default"]

    def resolve(self, alias: str | None) -> str:
        return alias or DEFAULT_DB_ALIAS

    def managed_aliases(self) -> list[str]:
        """The aliases Joist manages: those configured under
        ``JOIST['connections']``, or the default alias when none are."""
        configured = list((joist_settings.get("connections") or {}).keys())
        return configured or [self.resolve(None)]

    # -- reads/writes ------------------------------------------------------
    def get(self, alias: str | None = None) -> dict[str, Any]:
        """The cached snapshot, building and caching it on a miss. Always
        returns a usable snapshot: when the cache store cannot be read the
        schema is built live and simply not cached, which is slower but
        complete."""
        alias = self.resolve(alias)

        cached = self._attempt(lambda: self._cache().get(self.key(alias)), "read")
        if isinstance(cached, dict):
            return cached

        # A failed read and an empty cache are the same thing to us (build
        # it), but they are not the same thing to the caller, so the reason
        # survives the write attempt that follows.
        read_error = self.last_error

        snapshot = self._build(alias)
        self._store(alias, snapshot)
        # The read error wins when both failed: it is the diagnostic one
        # ("no such table: django_cache"), while the write error is the same
        # fact restated around a payload containing the entire snapshot.
        if read_error is not None:
            self.last_error = read_error
        return snapshot

    def rebuild(self, alias: str | None = None) -> dict[str, Any]:
        """Force a rebuild and overwrite the cache. The snapshot is returned
        even when it could not be stored, so callers that only need the
        structure carry on; ``last_error`` reports the failed write to the
        ones that care (``joist_rebuild`` fails on it)."""
        alias = self.resolve(alias)
        snapshot = self._build(alias)
        self._store(alias, snapshot)
        return snapshot

    def peek(self, alias: str | None = None) -> dict | None:
        """The currently cached snapshot without building on a miss, or None.
        Used to capture the pre-migration snapshot as a diff baseline: unlike
        get(), it never reaches the live database, so it cannot accidentally
        record the post-migration state."""
        alias = self.resolve(alias)
        value = self._attempt(lambda: self._cache().get(self.key(alias)), "read")
        return value if isinstance(value, dict) else None

    def has(self, alias: str | None = None) -> bool:
        return self.peek(alias) is not None

    def forget(self, alias: str | None = None) -> bool:
        alias = self.resolve(alias)
        return self._attempt(lambda: self._cache().delete(self.key(alias)) or True, "write")

    # -- internals ---------------------------------------------------------
    def _store(self, alias: str, snapshot: dict) -> bool:
        ttl = int(joist_settings.get("cache.ttl", 3600))
        # Plain seconds (not timedelta): portable across every Django cache
        # backend and version. ttl <= 0 means "cache forever" (timeout None).
        timeout = None if ttl <= 0 else ttl
        return self._attempt(lambda: self._cache().set(self.key(alias), snapshot, timeout) or True, "write")

    def _build(self, alias: str) -> dict[str, Any]:
        snapshot = self.builder.build(alias)
        snapshot["generated_at"] = timezone.now().isoformat()
        return snapshot

    def _attempt(self, operation, kind: str):
        """Run a cache operation, degrading to None/False instead of throwing.

        ``Exception`` rather than a narrower type on purpose: an unusable
        database-backed cache raises OperationalError/ProgrammingError,
        Memcached/Redis raise their own connection errors, and an
        unconfigured alias raises InvalidCacheBackendError. They all mean the
        same thing here.
        """
        try:
            result = operation()
            self.last_error = None
            return result
        except Exception as exc:  # noqa: BLE001
            # Trimmed because some stores echo the payload back in the error
            # message: the raw text can be tens of kilobytes, and it goes to
            # a terminal and to the log.
            self.last_error = str(exc)[:180]
            logger.debug("joist: could not reach the cache store (%s): %s", kind, self.last_error)
            return None if kind == "read" else False


_default_repository: SchemaCacheRepository | None = None


def schema_cache() -> SchemaCacheRepository:
    """One repository per process, so whoever reads the snapshot and whoever
    reports on it share the same ``last_error``. Resettable for tests."""
    global _default_repository
    if _default_repository is None:
        _default_repository = SchemaCacheRepository()
    return _default_repository


def reset_schema_cache() -> None:
    global _default_repository
    _default_repository = None
