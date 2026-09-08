"""Persists the pre-migration schema snapshot (the diff baseline) as a
structure-only JSON file on disk.

The baseline lives on disk, not in the cache, because it is the one piece of
state Joist cannot rebuild from the live database: once the migration has run,
the previous schema exists nowhere else. It stores the same structure-only
snapshot the cache holds, so it never records row data. The file is derived and
safe to delete; a missing baseline simply yields an empty diff until the next
migration re-seeds it.

Every operation degrades instead of throwing. The baseline is the only part of
Joist that touches the filesystem and it serves one secondary feature; letting
a storage error escape could break things that do not depend on it - the
schema endpoint, or ``manage.py migrate`` via the post-migration listener. A
missing baseline is an empty diff, and that is what every failure degrades to.
``last_error`` lets a caller that can act on it say something useful.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Callable

from django.conf import settings

from ..conf import joist_settings

logger = logging.getLogger("joist")


class BaselineStore:
    def __init__(self) -> None:
        self.last_error: str | None = None

    # -- public API --------------------------------------------------------
    def save(self, alias: str, snapshot: dict[str, Any]) -> bool:
        def op() -> bool:
            path = self.path(alias)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            return True

        return self._attempt(op, False)

    def get(self, alias: str) -> dict | None:
        """The stored baseline, or None when nothing is stored or the file
        could not be read (a failure and an absence both arrive as None;
        ``last_error`` distinguishes them)."""

        def op() -> dict | None:
            path = self.path(alias)
            if not path.is_file():
                return None
            raw = path.read_text(encoding="utf-8")
            if not raw.strip():
                return None
            return json.loads(raw)

        return self._attempt(op, None)

    def has(self, alias: str) -> bool:
        return self._attempt(lambda: self.path(alias).is_file(), False)

    def forget(self, alias: str) -> bool:
        def op() -> bool:
            try:
                self.path(alias).unlink()
            except FileNotFoundError:
                pass
            return True

        return self._attempt(op, False)

    # -- internals ---------------------------------------------------------
    @property
    def root(self) -> Path:
        configured = joist_settings.get("diff.dir")
        if configured:
            return Path(configured)
        base = getattr(settings, "BASE_DIR", None)
        return Path(base) / "var" / "joist" if base else Path(".joist-var")

    def path(self, alias: str) -> Path:
        return self.root / "baselines" / f"{self._slug(alias)}.json"

    @staticmethod
    def _slug(alias: str) -> str:
        """Reduce an alias name to a filesystem-safe filename, so a name with
        slashes or colons can never traverse out of the baselines dir."""
        slug = re.sub(r"[^a-z0-9]+", "-", alias.lower()).strip("-")
        return slug or "default"

    def _attempt(self, operation: Callable[[], Any], fallback: Any) -> Any:
        """Run a disk operation, degrading to ``fallback`` instead of throwing.

        Broad on purpose: OSError (unwritable/read-only dir), UnicodeDecodeError
        and json errors (a corrupt baseline), and ImproperlyConfigured (a bogus
        ``diff.dir``) all mean the same thing here, and none should reach the
        caller.
        """
        try:
            result = operation()
            self.last_error = None
            return result
        except Exception as exc:  # noqa: BLE001
            self.last_error = str(exc)[:180]
            logger.debug("joist: diff baseline operation failed: %s", self.last_error)
            return fallback
