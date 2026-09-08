"""A Mermaid ``erDiagram`` definition for the given tables.

The server-side counterpart of the dashboard's client-side generator
(``static/joist/js/mermaid-definition.js``, native-label path). Native types
only: the browser's "django" short-label mode is an interactive UI toggle
with no CLI flag, so it is not ported here. Per-column PK/FK badges are
derived from ``primary_key`` and ``foreign_keys[].columns``.

Mermaid has no clean place for annotations or global notes, so both are
omitted here by design; the other formats carry them.
"""

from __future__ import annotations

import re
from typing import Any

_ENUM_SET = re.compile(r"^\s*(enum|set)\b[\s\S]*$", re.IGNORECASE)
_NON_WORD = re.compile(r"[^A-Za-z0-9]+")
_EDGES = re.compile(r"^_+|_+$")


class MermaidGenerator:
    def generate(self, tables: list[dict[str, Any]], notes: list[str] | None = None) -> str:
        present = {t["name"] for t in tables}
        entities = [self._entity_block(t) for t in tables]

        # An edge is emitted only when BOTH endpoints are in the subset, so a
        # filtered/focused export never conjures a phantom entity.
        relationships: list[str] = []
        for table in tables:
            for fk in table.get("foreign_keys") or []:
                if fk["references_table"] not in present:
                    continue
                if fk["references_table"] == table["name"]:
                    # Self-reference: shown as a "self-ref" column note (see
                    # _entity_block), not a self-loop edge.
                    continue
                label = fk.get("name") or "_".join(fk["columns"])
                relationships.append(
                    f"  {fk['references_table']} ||--o{{ {table['name']} : \"{label}\""
                )

        return "\n".join(["erDiagram", *entities, *relationships])

    # -- internals ---------------------------------------------------------
    def _entity_block(self, table: dict[str, Any]) -> str:
        primary_key = table.get("primary_key") or []
        foreign_keys = table.get("foreign_keys") or []
        fk_columns = [c for fk in foreign_keys for c in fk["columns"]]
        self_ref_columns = [
            c for fk in foreign_keys if fk["references_table"] == table["name"] for c in fk["columns"]
        ]

        lines = []
        for column in table.get("columns") or []:
            type_ = self._mermaid_type(column["type"])
            badge = self._key_badge(column["name"], primary_key, fk_columns)
            note = ' "self-ref"' if column["name"] in self_ref_columns else ""
            lines.append(
                (f"    {type_} {column['name']}" + (f" {badge}" if badge else "") + note).rstrip()
            )
        return "\n".join([f"  {table['name']} {{", *lines, "  }"])

    @staticmethod
    def _mermaid_type(native_type: str | None) -> str:
        """Collapse a native type into a single Mermaid-safe token: Mermaid
        splits attributes on whitespace, so ``bigint unsigned`` and
        ``varchar(255)`` must become one word. enum/set value lists collapse
        to the keyword so a long list does not blow out the column width."""
        label = _ENUM_SET.sub(r"\1", str(native_type or ""))
        label = _EDGES.sub("", _NON_WORD.sub("_", label.strip()))
        return label or "unknown"

    @staticmethod
    def _key_badge(name: str, primary_key: list[str], fk_columns: list[str]) -> str:
        return ", ".join(
            badge
            for badge in (
                "PK" if name in primary_key else None,
                "FK" if name in fk_columns else None,
            )
            if badge
        )
