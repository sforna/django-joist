"""post_migrate receiver: rebuild the cached snapshot after migrations.

The counterpart of Laravel Truss's ``RebuildOnMigrationsEnded`` listener, with
one Django wrinkle: there is no single "migrations ended" signal - Django
sends ``pre_migrate`` and ``post_migrate`` *once per app* around a migrate
run. So we debounce per alias: the first ``post_migrate`` of a run refreshes,
the rest of that run's firings are no-ops, and the next ``pre_migrate`` for
the alias re-arms the listener.

The same two rules hold:

* it never throws: an exception here would take down ``manage.py migrate``
  on a migration that already succeeded;
* before overwriting the cache, the currently cached snapshot is captured as
  the schema-diff baseline - this is the one place that knows a migration
  just ran, and the cache is the only remaining source of the previous
  schema once the migration has completed.
"""

from __future__ import annotations

import logging

from django.db.models.signals import post_migrate, pre_migrate
from django.dispatch import receiver

from .conf import joist_settings
from .introspection.builder import FALLBACK_ALIAS_PREFIX

logger = logging.getLogger("joist")

#: Aliases refreshed since the last pre_migrate - cleared per run (see above).
_refreshed: set[str] = set()


@receiver(pre_migrate, dispatch_uid="joist.rearm_after_migrate")
def rearm_after_migrate(sender, **kwargs):
    alias = kwargs.get("using") or "default"
    _refreshed.discard(str(alias))


@receiver(post_migrate, dispatch_uid="joist.rebuild_after_migrate")
def rebuild_after_migrate(sender, **kwargs):
    from .cache import schema_cache

    if not joist_settings.get("enabled"):
        return

    alias = str(kwargs.get("using") or "default")
    if alias.startswith(FALLBACK_ALIAS_PREFIX):
        return  # never cache the throwaway fallback schema
    if alias in _refreshed:
        return
    _refreshed.add(alias)

    cache = schema_cache()
    aliases = [alias] if alias in cache.managed_aliases() else cache.managed_aliases()
    capture_baseline = bool(joist_settings.get("diff.enabled", True))

    for name in aliases:
        try:
            _refresh(cache, name, capture_baseline)
        except Exception as exc:  # noqa: BLE001 - migrate must never fail because of Joist
            logger.warning("joist: post-migration refresh failed for [%s]: %s", name, exc)


def _refresh(cache, alias: str, capture_baseline: bool) -> None:
    if capture_baseline:
        try:
            previous = cache.peek(alias)
            if previous is not None:
                from .diff.baseline import BaselineStore

                BaselineStore().save(alias, previous)
        except Exception as exc:  # noqa: BLE001 - the baseline serves one feature; rebuild must go on
            logger.warning("joist: could not capture diff baseline for [%s]: %s", alias, exc)

    cache.rebuild(alias)

    if cache.last_error:
        logger.warning(
            "joist: rebuilt the schema snapshot for [%s] but could not cache it: %s. "
            "The dashboard will read the schema live until the cache store is usable again.",
            alias,
            cache.last_error,
        )
