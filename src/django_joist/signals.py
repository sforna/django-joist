"""Refresh a managed schema after migrate and record real structural changes.

Django sends pre_migrate and post_migrate once per app, and post_migrate also
runs for flush and migrations with no operations. A pending snapshot per alias
lets us read the live structure once before migrations, refresh once after,
and leave the last diff alone when the structure did not change.
"""

from __future__ import annotations

import logging

from django.db.models.signals import post_migrate, pre_migrate
from django.dispatch import receiver

from .conf import joist_settings
from .introspection.builder import FALLBACK_ALIAS_PREFIX

logger = logging.getLogger("joist")

# A None value means the pre-migration schema could not be captured (or diff
# is off). Presence still marks a migrate run and debounces per-app signals.
_pending: dict[str, dict | None] = {}


@receiver(pre_migrate, dispatch_uid="joist.rearm_after_migrate")
def rearm_after_migrate(sender, **kwargs):
    from .cache import schema_cache

    if not joist_settings.get("enabled"):
        return

    alias = str(kwargs.get("using") or "default")
    if alias.startswith(FALLBACK_ALIAS_PREFIX) or alias in _pending:
        return

    cache = schema_cache()
    if alias not in cache.managed_aliases():
        return

    _pending[alias] = None
    if joist_settings.get("diff.enabled", True):
        try:
            # Read the actual pre-migration schema. A cached snapshot may have
            # expired or may be stale after a manual database change.
            before = cache.rebuild(alias)
            if not before.get("fallback_error"):
                _pending[alias] = before
        except Exception as exc:  # noqa: BLE001 - Joist must not stop migrate
            logger.warning("joist: could not capture schema before migration for [%s]: %s", alias, exc)


@receiver(post_migrate, dispatch_uid="joist.rebuild_after_migrate")
def rebuild_after_migrate(sender, **kwargs):
    from .cache import schema_cache

    if not joist_settings.get("enabled"):
        return

    alias = str(kwargs.get("using") or "default")
    if alias not in _pending:
        return  # flush, unmanaged alias, or a later per-app signal
    before = _pending.pop(alias)

    cache = schema_cache()
    try:
        after = cache.rebuild(alias)
        if before is not None and not after.get("fallback_error"):
            from .diff.baseline import BaselineStore
            from .diff.differ import SchemaDiffer

            if SchemaDiffer().diff(before, after)["has_changes"]:
                baselines = BaselineStore()
                if not baselines.save(alias, before):
                    logger.warning(
                        "joist: could not capture diff baseline for [%s]: %s",
                        alias,
                        baselines.last_error,
                    )
    except Exception as exc:  # noqa: BLE001 - Joist must not stop migrate
        logger.warning("joist: post-migration refresh failed for [%s]: %s", alias, exc)
        return

    if cache.last_error:
        logger.warning(
            "joist: rebuilt the schema snapshot for [%s] but could not cache it: %s. "
            "The dashboard will read the schema live until the cache store is usable again.",
            alias,
            cache.last_error,
        )
