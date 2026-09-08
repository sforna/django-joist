"""The internal export service: select, deterministically order, render.

Splitting "select the tables" from "render them" lets the caller (the command,
the HTTP route) detect an empty result and choose its own exit code before
anything is rendered. Determinism lives here, once, so every format inherits
it and no generator ever has to sort. Schema only; row data is never read.
"""

from __future__ import annotations

from typing import Any, Callable

from .generators.csv import CsvGenerator
from .generators.dbml import DbmlGenerator
from .generators.json import JsonGenerator
from .generators.llm import LlmGenerator
from .generators.markdown import MarkdownGenerator
from .generators.mermaid import MermaidGenerator

#: format token -> generator class. The keys are the public format names used
#: by the CLI flag, the URL route, and the builder terminals.
GENERATORS: dict[str, type] = {
    "dbml": DbmlGenerator,
    "json": JsonGenerator,
    "csv": CsvGenerator,
    "markdown": MarkdownGenerator,
    "mermaid": MermaidGenerator,
    "llm": LlmGenerator,
}


class SchemaExporter:
    @staticmethod
    def formats() -> list[str]:
        return list(GENERATORS)

    @staticmethod
    def supports(fmt: str) -> bool:
        return fmt in GENERATORS

    def tables_for(
        self,
        tables: list[dict[str, Any]],
        only: list[str] | None = None,
        exclude: list[str] | None = None,
        config_excluded: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Select and deterministically order the tables to export.

        Precedence: a table is kept when it is in the allowlist (or the
        allowlist is empty), is not in the blocklist, and is not
        config-excluded. Config exclusions always win, so you cannot filter
        your way to a table the dashboard hides.
        """
        only = only or []
        exclude = set(exclude or [])
        config_excluded = set(config_excluded or [])

        selected = [
            t
            for t in tables
            if (not only or t["name"] in only) and t["name"] not in exclude and t["name"] not in config_excluded
        ]
        return self._order(selected)

    def generate(self, fmt: str, tables: list[dict[str, Any]], notes: list[str] | None = None) -> str:
        """Render already-selected, already-ordered tables in one format.

        Tables may carry ``annotation`` keys (per table and per column);
        ``notes`` are global notes rendered by the formats that have a header
        block. Empty notes and un-annotated tables reproduce the un-annotated
        output exactly.
        """
        if not self.supports(fmt):
            raise ValueError(f"Unsupported export format [{fmt}].")
        generator: Callable[..., str] = GENERATORS[fmt]().generate
        return generator(tables, notes or [])

    @staticmethod
    def _order(tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Canonical ordering: tables alphabetical, foreign keys by source
        column, indexes by name. Columns and primary-key order are left
        untouched because their order carries meaning (declaration order,
        key order)."""
        out = []
        for table in sorted(tables, key=lambda t: str(t["name"])):
            table = dict(table)
            table["foreign_keys"] = sorted(
                table.get("foreign_keys") or [],
                key=lambda fk: ",".join(fk["columns"]),
            )
            table["indexes"] = sorted(table.get("indexes") or [], key=lambda idx: str(idx["name"]))
            out.append(table)
        return out
