"""Per-vendor *native* schema detail providers.

Django's portable ``get_table_description`` reports column types inconsistently
across backends (an OID on postgres, a bare type word on mysql) and carries no
comments or referential actions. The snapshot promises the *native full type
exactly as the database reports it* plus comments and FK actions, so each
mainstream vendor gets batched, structure-only catalog queries here. Anything a
vendor does not supply simply stays ``None`` and the builder falls back to its
best-effort composition — unknown vendors degrade, they never crash.

Every query here reads catalog/information_schema data only. Row contents are
never touched: this is the package's core promise.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("joist")


# -- public helpers (each returns sparse dicts; missing key == not supplied) --
def native_column_types(connection, table_names: list[str], descriptions: dict) -> dict[tuple[str, str], str]:
    """(table, column) -> native full type, e.g. 'varchar(255)', 'bigint unsigned'."""
    try:
        if connection.vendor == "postgresql":
            return _pg_column_types(connection, table_names)
        if connection.vendor in ("mysql", "mariadb"):
            return _mysql_column_types(connection, table_names)
        if connection.vendor == "sqlite":
            return _sqlite_column_types(connection, table_names)
    except Exception as exc:  # noqa: BLE001 - enrichment only, never fatal
        logger.debug("joist: native column types unavailable for %s: %s", connection.alias, exc)
    return {}


def native_column_comments(connection, table_names: list[str]) -> dict[tuple[str, str], str]:
    try:
        if connection.vendor == "postgresql":
            return _pg_column_comments(connection, table_names)
        if connection.vendor in ("mysql", "mariadb"):
            return _mysql_column_comments(connection, table_names)
    except Exception as exc:  # noqa: BLE001
        logger.debug("joist: native column comments unavailable: %s", exc)
    return {}


def native_table_comments(connection, table_names: list[str]) -> dict[str, str]:
    try:
        if connection.vendor == "postgresql":
            return _pg_table_comments(connection, table_names)
        if connection.vendor in ("mysql", "mariadb"):
            return _mysql_table_comments(connection, table_names)
    except Exception as exc:  # noqa: BLE001
        logger.debug("joist: native table comments unavailable: %s", exc)
    return {}


def native_fk_actions(connection, table_names: list[str]) -> dict[tuple[str, str], dict[str, str]]:
    """(table, constraint-name) -> {'on_update': ..., 'on_delete': ...}.

    SQLite names nothing and is keyed by FK id, so its actions are matched by
    (table, column) instead; the builder looks both up.
    """
    try:
        if connection.vendor == "postgresql":
            return _pg_fk_actions(connection, table_names)
        if connection.vendor in ("mysql", "mariadb"):
            return _mysql_fk_actions(connection, table_names)
        if connection.vendor == "sqlite":
            return _sqlite_fk_actions(connection, table_names)
    except Exception as exc:  # noqa: BLE001
        logger.debug("joist: native fk actions unavailable: %s", exc)
    return {}


# -- SQLite: PRAGMA is exact and cheap; declared type is the native type -----
def _in(conn, names: list[str]) -> str:
    return ", ".join(["%s"] * len(names))


def _sqlite_column_types(connection, table_names) -> dict[tuple[str, str], str]:
    out: dict[tuple[str, str], str] = {}
    with connection.cursor() as cur:
        for table in table_names:
            cur.execute(f"PRAGMA table_info({connection.ops.quote_name(table)})")
            for row in cur.fetchall():
                # cid, name, type, notnull, dflt_value, pk
                out[(table, row[1])] = str(row[2] or "").strip()
    return out


def _sqlite_fk_actions(connection, table_names) -> dict[tuple[str, str], dict[str, str]]:
    """Keyed by (table, column): SQLite foreign keys are unnamed."""
    out: dict[tuple[str, str], dict[str, str]] = {}
    with connection.cursor() as cur:
        for table in table_names:
            cur.execute(f"PRAGMA foreign_key_list({connection.ops.quote_name(table)})")
            for row in cur.fetchall():
                # id, seq, table, from, to, on_update, on_delete, match
                actions = {"on_update": row[5], "on_delete": row[6]}
                out[(table, row[3])] = actions
                out.setdefault((table, f"fk_{row[0]}"), actions)
    return out


# -- PostgreSQL: pg_catalog + format_type ------------------------------------
def _pg_columns_query(connection, table_names):
    """Rows for all requested tables in one round-trip, scoped to the
    connection's visible search path (same namespace the table list came from)."""
    rows = []
    with connection.cursor() as cur:
        cur.execute(
            f"""
            SELECT c.relname, a.attname,
                   pg_catalog.format_type(a.atttypid, a.atttypmod),
                   col_description(a.attrelid, a.attnum)
            FROM pg_catalog.pg_attribute a
            JOIN pg_catalog.pg_class c ON c.oid = a.attrelid
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relname IN ({_in(connection, table_names)})
              AND a.attnum > 0 AND NOT a.attisdropped
              AND pg_catalog.pg_table_is_visible(c.oid)
            """,
            table_names,
        )
        rows = cur.fetchall()
    return rows


def _pg_column_types(connection, table_names) -> dict[tuple[str, str], str]:
    return {(t, c): ty for t, c, ty, _ in _pg_columns_query(connection, table_names) if ty}


def _pg_column_comments(connection, table_names) -> dict[tuple[str, str], str]:
    return {(t, c): cm for t, c, _, cm in _pg_columns_query(connection, table_names) if cm}


def _pg_table_comments(connection, table_names) -> dict[str, str]:
    out: dict[str, str] = {}
    with connection.cursor() as cur:
        cur.execute(
            f"""
            SELECT c.relname, obj_description(c.oid)
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relname IN ({_in(connection, table_names)})
              AND pg_catalog.pg_table_is_visible(c.oid)
            """,
            table_names,
        )
        out = {t: cm for t, cm in cur.fetchall() if cm}
    return out


_PG_ACTION = {"a": "no action", "r": "restrict", "c": "cascade", "n": "set null", "d": "set default"}


def _pg_fk_actions(connection, table_names) -> dict[tuple[str, str], dict[str, str]]:
    out: dict[tuple[str, str], dict[str, str]] = {}
    with connection.cursor() as cur:
        cur.execute(
            f"""
            SELECT con.conname, cls.relname, con.confupdtype, con.confdeltype,
                   a.attname
            FROM pg_catalog.pg_constraint con
            JOIN pg_catalog.pg_class cls ON cls.oid = con.conrelid
            JOIN pg_catalog.pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = con.conkey[1]
            WHERE con.contype = 'f' AND cls.relname IN ({_in(connection, table_names)})
            """,
            table_names,
        )
        for name, table, upd, dele, col in cur.fetchall():
            actions = {
                "on_update": _PG_ACTION.get(upd, upd),
                "on_delete": _PG_ACTION.get(dele, dele),
            }
            out[(table, name)] = actions
            out.setdefault((table, col), actions)
    return out


# -- MySQL / MariaDB: information_schema -------------------------------------
def _mysql_schema(connection) -> str:
    with connection.cursor() as cur:
        cur.execute("SELECT DATABASE()")
        return cur.fetchone()[0]


def _mysql_columns_rows(connection, table_names):
    schema = _mysql_schema(connection)
    with connection.cursor() as cur:
        cur.execute(
            f"""
            SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, COLUMN_COMMENT
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME IN ({_in(connection, table_names)})
            """,
            [schema, *table_names],
        )
        return cur.fetchall()


def _mysql_column_types(connection, table_names) -> dict[tuple[str, str], str]:
    return {(t, c): ty for t, c, ty, _ in _mysql_columns_rows(connection, table_names) if ty}


def _mysql_column_comments(connection, table_names) -> dict[tuple[str, str], str]:
    return {(t, c): cm for t, c, _, cm in _mysql_columns_rows(connection, table_names) if cm}


def _mysql_table_comments(connection, table_names) -> dict[str, str]:
    schema = _mysql_schema(connection)
    out: dict[str, str] = {}
    with connection.cursor() as cur:
        cur.execute(
            f"""
            SELECT TABLE_NAME, TABLE_COMMENT
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME IN ({_in(connection, table_names)})
            """,
            [schema, *table_names],
        )
        out = {t: cm for t, cm in cur.fetchall() if cm}
    return out


def _mysql_fk_actions(connection, table_names) -> dict[tuple[str, str], dict[str, str]]:
    schema = _mysql_schema(connection)
    out: dict[tuple[str, str], dict[str, str]] = {}
    with connection.cursor() as cur:
        cur.execute(
            f"""
            SELECT CONSTRAINT_NAME, TABLE_NAME, UPDATE_RULE, DELETE_RULE
            FROM information_schema.REFERENTIAL_CONSTRAINTS
            WHERE CONSTRAINT_SCHEMA = %s AND TABLE_NAME IN ({_in(connection, table_names)})
            """,
            [schema, *table_names],
        )
        out = {
            (table, name): {
                "on_update": UPDATE.lower(),
                "on_delete": DELETE.lower(),
            }
            for name, table, UPDATE, DELETE in cur.fetchall()
        }
    return out
