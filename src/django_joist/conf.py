"""Joist configuration.

The single source of truth for Joist's behaviour is the ``JOIST`` dict in the
host project's settings, merged over the defaults below. Mirrors
``config/truss.php`` from the reference implementation, adapted to Django:

* there is no ``route_prefix`` here: the host mounts the app's URLs wherever
  it wants with ``include("django_joist.urls")``;
* there is no ``middleware`` key: Django resolves ``request.user`` through the
  project's own middleware stack, so nothing extra is needed (but see
  ``authorization`` — the view decorator is applied by the package itself);
* "connections" are Django database *aliases* (``DATABASES`` keys).
"""

from __future__ import annotations

import copy
from typing import Any

from django.conf import settings
from django.test.signals import setting_changed

#: Defaults. Every key is overridable by the ``JOIST`` dict in settings.
DEFAULTS: dict[str, Any] = {
    # ---- Global on/off switch. Defaults to "DEBUG only", the Django analog
    # of "local environment only". When false the routes answer 404.
    "enabled": None,  # None -> settings.DEBUG at read time
    # ---- Database aliases Joist may visualize, with per-alias overrides.
    # When empty, the project's default alias (``DATABASES["default"]``) is
    # used. Example:
    #   "connections": {"analytics": {"excluded_tables": ["ingest_log"]}}
    "connections": {},
    # ---- Tables hidden from diagram and API, applied server-side (they never
    # reach the browser). Django's own bookkeeping tables are noise by default.
    "excluded_tables": [
        "django_migrations",
        "django_content_type",
        "django_session",
        "django_site",
        "auth_permission",
        "auth_group_permissions",
        "auth_user_groups",
        "auth_user_user_permissions",
    ],
    # ---- Snapshot cache. Derived, disposable data; never a database table.
    "cache": {
        "ttl": 3600,  # seconds; 0 or less means "forever"
        "alias": None,  # named cache from CACHES; None -> "default"
        "key_prefix": "joist",
    },
    # ---- HTTP ---------------------------------------------------------------
    # Base URL used only by joist_open to build a browsable link (the routes
    # themselves are mounted by the host URLconf). Defaults to runserver.
    "base_url": None,
    # ---- Authorization. Access is guarded by two independent layers, like
    # the reference: (1) ``enabled`` — the deploy switch; (2) the authorizer
    # — the access control: "who may view". The authorizer is consulted only
    # when DEBUG is false (DEBUG is the Django analog of "local", which is
    # unconditionally open). A denial always returns 404, never 403, so the
    # dashboard never confirms it exists to someone who may not see it.
    "authorization": {
        # Dotted path to a callable(request) -> bool. None uses the default
        # authorizer, which admits users whose email is in allowed_emails and
        # fails closed on an empty list.
        "callable": None,
        # Zero-code path: comma-list of emails admitted by the default
        # authorizer outside DEBUG.
        "allowed_emails": [],
    },
    # ---- Diagram presentation.
    "diagram": {
        # Default column-type label mode: "native" (full DB type) or "django"
        # (best-effort Django field name, e.g. CharField -> "char field").
        # User-toggleable in the UI; this is only the default.
        "type_labels": "native",
        # Where the browser loads Mermaid from. None self-hosts the vendored
        # copy from the gated asset route (no CDN, CSP-friendly).
        "mermaid_url": None,
        # Readable floor for the automatic fit-to-screen; the Fit button
        # ignores it. 1.0 = 100%.
        "min_zoom": 0.7,
    },
    # ---- Theme: semantic colour/font knobs, emitted as a same-origin
    # stylesheet served by the gated /theme.css route.
    "theme": {
        "fonts": {"mono": None, "sans": None},
        "colors": {"light": {}, "dark": {}},
    },
    # ---- Focus mode (a table and its FK neighbours).
    "focus": {"default_depth": 1},
    # ---- UI warning threshold for big schemas.
    "large_schema": {"warn_above": 60},
    # ---- Schema diff: "what changed since the last migration". The only
    # thing Joist writes to disk: a structure-only JSON baseline per alias.
    "diff": {
        "enabled": True,
        # Directory holding baselines/{alias}.json. None -> BASE_DIR/var/joist
        # (deliberately not MEDIA/STATIC roots: derived tooling state).
        "dir": None,
    },
    # ---- Schema doctor: deterministic, structure-only review rules.
    "doctor": {
        # recommended (high-confidence rules), strict (all), none.
        "preset": "recommended",
        # Per-rule overrides keyed by code: False disables, True enables,
        # {"severity": "error"} changes severity.
        "rules": {},
        # Per-rule fnmatch patterns (table or table.column) to silence.
        "ignore": {},
        # Severity at or above which joist_doctor exits non-zero.
        "fail_on": "error",
        # Extra tables to skip, on top of excluded_tables.
        "exclude": [],
        # Show findings in the dashboard "Health" panel.
        "dashboard": True,
        # Badge tables with findings on the diagram even with the panel closed.
        "flag_tables": True,
        # Column names the soft-delete rules treat as a delete marker
        # (Django has no native soft delete; projects commonly use these).
        "soft_delete_columns": ["deleted_at", "deleted", "removed_at"],
    },
    # ---- Business meaning a type cannot carry, rendered into exports.
    "annotations": {
        # Ordered precedence: "config" reads the maps below; "database" reads
        # native column/table comments (Postgres and MySQL; SQLite has none).
        "source": ["config", "database"],
        "notes": [],
        "tables": {},
        "columns": {},
    },
    # ---- Export.
    "export": {"default_format": "dbml"},
}

missing_marker = object()


class JoistSettings:
    """Lazily-merged view over ``settings.JOIST`` with dict deep-merge.

    Read attributes or use item access with dotted paths::

        joist_settings["cache.ttl"]
        joist_settings.get("diff.enabled")
    """

    def __init__(self) -> None:
        self._wrapped: dict[str, Any] | None = None

    # -- loading ---------------------------------------------------------
    def _load(self) -> dict[str, Any]:
        user = getattr(settings, "JOIST", None) or {}
        merged = _deep_merge(copy.deepcopy(DEFAULTS), copy.deepcopy(user))
        if merged["enabled"] is None:
            merged["enabled"] = bool(getattr(settings, "DEBUG", False))
        return merged

    @property
    def wrapped(self) -> dict[str, Any]:
        if self._wrapped is None:
            self._wrapped = self._load()
        return self._wrapped

    def reload(self) -> None:
        self._wrapped = None

    # -- access ----------------------------------------------------------
    def get(self, path: str, default: Any = None) -> Any:
        node: Any = self.wrapped
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def __getitem__(self, path: str) -> Any:
        missing = object()
        value = self.get(path, missing)
        if value is missing:
            raise KeyError(path)
        return value

    def __contains__(self, path: str) -> bool:
        return self.get(path, missing_marker) is not missing_marker  # noqa: F821

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        return self.wrapped[name]


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge ``override`` into ``base`` (dicts merge, other values
    replace). Nested config blocks stay overridable key-by-key, so a host
    that sets only ``JOIST = {"cache": {"ttl": 0}}`` keeps every other cache
    default."""
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


joist_settings = JoistSettings()


def _reload_setting(*, setting: str, **kwargs: Any) -> None:
    if setting == "JOIST":
        joist_settings.reload()


setting_changed.connect(_reload_setting)
