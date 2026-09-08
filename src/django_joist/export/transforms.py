"""Focus and compact snapshot transforms, ported from the reference.

Both run between table selection and rendering, so no generator learns about
filtering or compactness: they just receive a leaner snapshot. Pure over the
serialized table dicts, structure only, never row data.
"""

from __future__ import annotations

import copy
from typing import Any


class FocusTransform:
    """Reduce a snapshot to one table and its foreign-key neighbourhood out
    to ``depth`` hops.

    The neighbourhood is undirected: a table's own foreign keys (child to
    parent) and any table that references it (parent to child) are both
    followed, so the result is the connected diagram around the root, not
    just its outbound edges. A self-referencing foreign key adds no edge (the
    table is already the root of its own neighbourhood).

    This is the server-side twin of the dashboard's client-side focus
    (``static/joist/js/selection.js``): same algorithm, two homes, kept in
    lockstep by shared tests. Output order is the input order, so the result
    is deterministic regardless of traversal order.
    """

    def apply(
        self,
        tables: list[dict[str, Any]],
        root: str,
        depth: int = 1,
    ) -> list[dict[str, Any]]:
        present = [t["name"] for t in tables]
        if root not in present:
            raise ValueError(f"Cannot focus on [{root}]: no such table in the export set.")

        neighbours = self._adjacency(tables)

        visited = {root}
        frontier = [root]
        for _hop in range(max(depth, 0)):
            nxt: list[str] = []
            for name in frontier:
                for adjacent in neighbours.get(name, {}):
                    if adjacent not in visited:
                        visited.add(adjacent)
                        nxt.append(adjacent)
            if not nxt:
                break
            frontier = nxt

        return [t for t in tables if t["name"] in visited]

    @staticmethod
    def _adjacency(tables: list[dict[str, Any]]) -> dict[str, dict[str, bool]]:
        neighbours: dict[str, dict[str, bool]] = {t["name"]: {} for t in tables}
        for table in tables:
            for fk in table.get("foreign_keys") or []:
                other = fk["references_table"]
                # Self-references are already inside the root's set; skip.
                if other != table["name"] and other in neighbours:
                    neighbours[table["name"]][other] = True
                    neighbours[other][table["name"]] = True
        return neighbours


class CompactTransform:
    """Drop the detail that costs tokens without adding structural meaning.

    Dropped: column defaults and non-unique index definitions. A unique index
    is kept but reduced to its bare marker (the name - an internal DBA detail
    - is cleared), so the uniqueness constraint survives while the index
    definition does not. Kept: every table, column, native type, nullability,
    primary key, unique constraint, foreign key, and any annotations.

    It loses no table, column, or foreign key, only detail, so full and
    compact describe the same schema at different verbosity.
    """

    def apply(self, tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for table in tables:
            table = copy.copy(table)
            table["columns"] = [
                {k: v for k, v in column.items() if k != "default"}
                for column in (table.get("columns") or [])
            ]
            table["indexes"] = [
                {**index, "name": ""}
                for index in (table.get("indexes") or [])
                if index.get("unique")
            ]
            out.append(table)
        return out
