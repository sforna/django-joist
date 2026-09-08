"""Compares two serialized schema snapshots and returns a plain diff dict.

A pure port of the reference ``SchemaDiffer``: no database, no framework, no
I/O. Tables, columns, indexes and foreign keys are matched by name, so a
rename reads as a remove plus an add (a documented limitation). Both inputs
are already structure-only, so the diff cannot expose row data by
construction.
"""

from __future__ import annotations

from typing import Any


class SchemaDiffer:
    def diff(self, baseline: dict, current: dict) -> dict[str, Any]:
        baseline_tables = self._by_name(baseline.get("tables", []))
        current_tables = self._by_name(current.get("tables", []))

        tables_added = [{"name": name} for name in current_tables if name not in baseline_tables]
        tables_removed = [{"name": name} for name in baseline_tables if name not in current_tables]

        tables_changed = []
        for name, current_table in current_tables.items():
            if name not in baseline_tables:
                continue
            table_diff = self._diff_table(baseline_tables[name], current_table)
            if table_diff is not None:
                tables_changed.append(table_diff)

        has_changes = bool(tables_added or tables_removed or tables_changed)

        return {
            "tables_added": tables_added,
            "tables_removed": tables_removed,
            "tables_changed": tables_changed,
            "has_changes": has_changes,
            "baseline_generated_at": baseline.get("generated_at"),
            "current_generated_at": current.get("generated_at"),
        }

    # -- internals ---------------------------------------------------------
    def _diff_table(self, baseline: dict, current: dict) -> dict | None:
        cols_added, cols_removed, cols_changed = self._diff_keyed(
            baseline.get("columns", []), current.get("columns", []), ["type", "nullable", "default"]
        )
        idx_added, idx_removed, idx_changed = self._diff_keyed(
            baseline.get("indexes", []), current.get("indexes", []), ["columns", "unique"]
        )
        fk_added, fk_removed, fk_changed = self._diff_keyed(
            baseline.get("foreign_keys", []),
            current.get("foreign_keys", []),
            ["columns", "references_table", "references_columns", "on_update", "on_delete"],
        )

        changes: dict[str, Any] = {}
        if baseline.get("primary_key", []) != current.get("primary_key", []):
            changes["primary_key"] = {
                "before": baseline.get("primary_key", []),
                "after": current.get("primary_key", []),
            }

        if not any([cols_added, cols_removed, cols_changed, idx_added, idx_removed, idx_changed, fk_added, fk_removed, fk_changed, changes]):
            return None

        return {
            "name": current["name"],
            "columns_added": cols_added,
            "columns_removed": cols_removed,
            "columns_changed": cols_changed,
            "indexes_added": idx_added,
            "indexes_removed": idx_removed,
            "indexes_changed": idx_changed,
            "foreign_keys_added": fk_added,
            "foreign_keys_removed": fk_removed,
            "foreign_keys_changed": fk_changed,
            "changes": changes,
        }

    def _diff_keyed(
        self, baseline: list[dict], current: list[dict], fields: list[str]
    ) -> tuple[list[dict], list[dict], list[dict]]:
        """Diff two name-keyed lists of dicts. Items match by ``name``;
        ``changed`` entries cover only the compared fields that differ. Added
        items carry their full definition; removed items carry just a name."""
        base_by_name = self._by_name(baseline)
        cur_by_name = self._by_name(current)

        added = []
        changed = []
        for name, item in cur_by_name.items():
            if name not in base_by_name:
                added.append(item)
                continue
            field_changes = self._field_changes(base_by_name[name], item, fields)
            if field_changes:
                changed.append({"name": name, "changes": field_changes})

        removed = [{"name": name} for name in base_by_name if name not in cur_by_name]
        return added, removed, changed

    @staticmethod
    def _field_changes(before: dict, after: dict, fields: list[str]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for field in fields:
            b = before.get(field)
            a = after.get(field)
            if b != a:
                out[field] = {"before": b, "after": a}
        return out

    @staticmethod
    def _by_name(items: list[dict]) -> dict[str, dict]:
        return {item["name"]: item for item in items}
