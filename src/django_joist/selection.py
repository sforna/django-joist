"""Serve-time table selection shared by the API, the exporter and the doctor.

Two selection layers, split by nature exactly as the reference does:

* **permanent exclusions** (``JOIST['excluded_tables']`` plus per-alias
  overrides) are applied *server-side*: an excluded table never reaches the
  API response, the export bytes, or a doctor finding. The cached snapshot
  stays the full schema, so toggling exclusions needs no rebuild.
* transient interactive selection (filter/focus) is client-side.

This module is pure over the serialized snapshot; it knows nothing about
HTTP or formats.
"""

from __future__ import annotations

from typing import Any

from .conf import joist_settings


def excluded_tables_for(alias: str) -> list[str]:
    """The global exclusion list merged with this alias's overrides."""
    global_list = list(joist_settings.get("excluded_tables", []) or [])
    per_alias = list(
        joist_settings.get(f"connections.{alias}.excluded_tables", []) or []
    )
    seen: dict[str, None] = {}
    for name in [*global_list, *per_alias]:
        seen.setdefault(str(name), None)
    return list(seen)


def without_excluded_tables(tables: list[dict[str, Any]], alias: str) -> list[dict[str, Any]]:
    """Drop any table whose name is excluded, globally or for this alias."""
    excluded = set(excluded_tables_for(alias))
    return [t for t in tables if t.get("name") not in excluded]
