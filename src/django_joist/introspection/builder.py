"""Builds a schema snapshot for a database alias.

The primary path introspects the live connection using Django's own
introspection API (``connection.introspection``) — no static parsing of
migration files. Types are the native full types the database reports, via
per-vendor providers where available (postgres ``format_type``, MySQL
``COLUMN_TYPE``, SQLite declared type); nothing is inferred.

This layer knows only about the database. It has no knowledge of HTTP,
templates, caching, or Mermaid, and adds no envelope fields (``generated_at``)
of its own — those belong to the caching layer.

Structure only, always: introspection reads the ``CREATE TABLE`` definitions
(tables, columns, keys, indexes, foreign keys, comments). No row is ever
selected.
"""

from __future__ import annotations

import logging
from typing import Any

from django.db import connections

from .data import Column, ForeignKey, Index, Table
from .native import native_column_types, native_column_comments, native_fk_actions, native_table_comments
from .serializer import SchemaSerializer

logger = logging.getLogger("joist")

#: Sentinel alias for the throwaway in-memory SQLite replay connection.
FALLBACK_ALIAS_PREFIX = "joist_fallback_"


class SnapshotError(Exception):
    """Raised when a snapshot cannot be built at all."""


class SnapshotBuilder:
    def __init__(self, serializer: SchemaSerializer | None = None) -> None:
        self.serializer = serializer or SchemaSerializer()

    # -- public API --------------------------------------------------------
    def build(self, alias: str | None = None) -> dict[str, Any]:
        """Full serialized snapshot for an alias (``default`` when None).

        Primary path: introspect the live connection. When the connection is
        unreachable and the fallback is enabled, replay the project's
        migrations on a throwaway in-memory SQLite database and introspect
        *that* instead — a degraded mode (native types become SQLite storage
        classes) surfaced to the UI via the ``fallback`` flag. A failure
        *after* a successful connect is a real error and is allowed to
        surface; only connectivity failures trigger the fallback.
        """
        from django.db import DEFAULT_DB_ALIAS

        alias = alias or DEFAULT_DB_ALIAS

        try:
            tables = self.introspect(alias)
            return {
                "connection": alias,
                "fallback": False,
                "fallback_error": None,
                "skipped_migrations": [],
                "tables": self.serializer.tables(tables),
            }
        except Exception as exc:  # noqa: BLE001 - connectivity check, see docstring
            if not self._is_connectivity_error(exc):
                raise
            from .fallback import replay_migrations_on_sqlite

            return replay_migrations_on_sqlite(alias, self)

    @staticmethod
    def _is_connectivity_error(exc: Exception) -> bool:
        from django.core.exceptions import ImproperlyConfigured
        from django.db import InterfaceError, OperationalError

        # Missing driver, refused connection, unopenable file: all mean "no
        # live schema to read" and route to the SQLite replay. A failure
        # *after* a successful connect (permissions on a catalog, a broken
        # query) is a real error and is allowed to surface.
        return isinstance(exc, (OperationalError, InterfaceError, ImproperlyConfigured))

    # -- introspection -----------------------------------------------------
    def introspect(self, alias: str) -> list[Table]:
        """Introspect a live connection into typed value objects, sorted by table name for determinism."""
        connection = connections[alias]
        ins = connection.introspection
        with connection.cursor() as cur:
            # TableInfo.type: 't' table, 'v' view, 'p' partition. Base
            # tables only - the diagram models stored structure, and views
            # carry no keys to draw.
            names = sorted(t.name for t in ins.get_table_list(cur) if t.type == "t")
            descriptions = {name: ins.get_table_description(cur, name) for name in names}
            constraints = {name: ins.get_constraints(cur, name) for name in names}

        types = native_column_types(connection, names, descriptions)
        col_comments = native_column_comments(connection, names)
        tbl_comments = native_table_comments(connection, names)
        fk_actions = native_fk_actions(connection, names)

        return [
            self._table(name, descriptions[name], constraints[name], types, col_comments, tbl_comments, fk_actions)
            for name in names
        ]

    def _table(
        self,
        name: str,
        description,
        constraints: dict,
        types: dict,
        col_comments: dict,
        tbl_comments: dict,
        fk_actions: dict,
    ) -> Table:
        columns = [
            Column(
                name=f.name,
                type=self._column_type(f, types.get((name, f.name))),
                nullable=bool(f.null_ok) if f.null_ok is not None else True,
                default=None if f.default is None else str(f.default),
                comment=col_comments.get((name, f.name)) or None,
            )
            for f in description
        ]

        primary_key: list[str] = []
        indexes: list[Index] = []
        foreign_keys: list[ForeignKey] = []

        for key, info in constraints.items():
            cols = tuple(c for c in (info.get("columns") or []) if c)
            if info.get("primary_key"):
                primary_key = list(cols)
                continue
            if info.get("check") and not info.get("unique") and not info.get("index"):
                continue
            if info.get("foreign_key"):
                refs = info["foreign_key"]
                ref_table, ref_cols = self._normalize_fk_ref(refs)
                actions = fk_actions.get((name, key)) or {}
                if not actions and cols:
                    actions = fk_actions.get((name, cols[0])) or {}
                foreign_keys.append(
                    ForeignKey(
                        name=key,
                        columns=cols,
                        references_table=ref_table or "",
                        references_columns=ref_cols,
                        on_update=self._normalize_action(actions.get("on_update")),
                        on_delete=self._normalize_action(actions.get("on_delete")),
                    )
                )
                continue
            is_index = bool(info.get("index"))
            is_unique = bool(info.get("unique"))
            if (is_index or is_unique) and cols:
                indexes.append(Index(name=key, columns=cols, unique=is_unique))

        return Table(
            name=name,
            columns=columns,
            primary_key=tuple(primary_key),
            indexes=indexes,
            foreign_keys=foreign_keys,
            comment=tbl_comments.get(name) or None,
        )

    @staticmethod
    def _column_type(field_info, native: str | None) -> str:
        if native:
            return native
        # Generic path: compose from DB-API description fields. Deliberately
        # best-effort for exotic vendors; the three mainstream backends all
        # supply a native string.
        base = str(field_info.type_code)
        if isinstance(field_info.internal_size, int) and field_info.internal_size and base.lower() in (
            "varchar",
            "char",
            "nvarchar",
            "nchar",
            "varbinary",
            "binary",
        ):
            base = f"{base}({field_info.internal_size})"
        elif isinstance(field_info.precision, int) and isinstance(field_info.scale, int) and field_info.precision:
            base = f"{base}({field_info.precision},{field_info.scale})"
        return base

    @staticmethod
    def _normalize_fk_ref(refs) -> tuple[str | None, tuple[str, ...]]:
        """Django's get_constraints reports the referenced side per backend as
        either a (table, column) pair or a (table, [columns]) pair. Normalize."""
        if isinstance(refs, dict):  # future-shaped named dict
            return refs.get("related_table") or refs.get("table"), tuple(
                refs.get("related_columns") or refs.get("columns") or ([refs["related_column"]] if "related_column" in refs else [])
            )
        if isinstance(refs, (list, tuple)) and len(refs) == 2:
            table, cols = refs
            if isinstance(cols, (list, tuple)):
                return table, tuple(cols)
            return table, (cols,) if cols else ()
        return None, ()

    @staticmethod
    def _normalize_action(action) -> str | None:
        """Referential actions arrive as SQL words ('CASCADE'), as None, or —
        on some Django versions — as the models.deletion callable. Map the
        callable back to its SQL name via the introspection's own table."""
        if action is None:
            return None
        if isinstance(action, str):
            word = " ".join(action.split()).lower()
            return word or None
        fn = getattr(action, "__name__", "")
        mapping = {
            "CASCADE": "cascade",
            "PROTECT": None,  # Django-level only; the DB clause is RESTRICT or absent
            "RESTRICT": "restrict",
            "SET_NULL": "set null",
            "SET_DEFAULT": "set default",
            "DO_NOTHING": None,
        }
        return mapping.get(fn)
