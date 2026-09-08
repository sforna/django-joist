"""Index rules (JOIST-IDX-*): indexes that are missing, duplicated, or
redundant. Ported from the reference; per-rule Django notes below."""

from __future__ import annotations

from typing import Iterable

from ..enums import Category, Confidence, Severity
from ..finding import Finding
from .base import Rule


class ForeignKeyWithoutIndex(Rule):
    """JOIST-IDX-001: a foreign key column with no index leading with it, so
    every join and cascade on it scans the table.

    Engine aware: MySQL and MariaDB create the index implicitly with the
    foreign key, so this rarely fires there and is only info; PostgreSQL,
    SQLite, and others do not, so it is an error. ``snapshot['driver']`` is
    injected by DoctorReport (Django's ``connection.vendor``).

    Django note: Django adds an index for ForeignKey columns itself, so a
    finding here means a hand-made or ``managed = False`` table.
    """

    code = "JOIST-IDX-001"
    category = Category.INDEX
    confidence = Confidence.HIGH
    default_severity = Severity.ERROR
    title = "Foreign key column without an index"

    def check(self, snapshot: dict, connection: str) -> Iterable[Finding]:
        auto_indexed = snapshot.get("driver") in ("mysql", "mariadb")
        severity = Severity.INFO if auto_indexed else Severity.ERROR

        for table in snapshot.get("tables", []):
            for fk in table.get("foreign_keys", []):
                columns = fk.get("columns") or []
                if not columns or self._covered_by_leading_index(table, columns):
                    continue
                label = ", ".join(columns)
                yield Finding(
                    code=self.code,
                    severity=severity,
                    connection=connection,
                    table=table["name"],
                    column=label,
                    message=(
                        f"Foreign key column \"{table['name']}.{label}\" has no index, "
                        "so joins and cascades scan the table."
                    ),
                    hint=(
                        "MySQL usually indexes foreign keys automatically, so an "
                        "unindexed one is unexpected; add an index to be safe."
                        if auto_indexed
                        else "This engine does not index foreign keys automatically. "
                        "Add an index on the column so lookups and cascades stay fast."
                    ),
                )

    @staticmethod
    def _covered_by_leading_index(table: dict, columns: list[str]) -> bool:
        """Whether an index or the primary key leads with exactly these columns."""
        count = len(columns)
        if (table.get("primary_key") or [])[:count] == columns:
            return True
        for index in table.get("indexes", []):
            if (index.get("columns") or [])[:count] == columns:
                return True
        return False


class DuplicateIndex(Rule):
    """JOIST-IDX-002: two indexes over the same columns in the same order.
    Column order matters, so (a, b) and (b, a) are not duplicates."""

    code = "JOIST-IDX-002"
    category = Category.INDEX
    confidence = Confidence.HIGH
    default_severity = Severity.WARNING
    title = "Exact duplicate index"

    def check(self, snapshot: dict, connection: str) -> Iterable[Finding]:
        for table in snapshot.get("tables", []):
            seen: dict[str, str] = {}
            for index in table.get("indexes", []):
                key = ",".join(index.get("columns") or [])
                if key in seen:
                    columns = ", ".join(index.get("columns") or [])
                    yield Finding(
                        code=self.code,
                        severity=self.default_severity,
                        connection=connection,
                        table=table["name"],
                        column=index["name"],
                        message=(
                            f"Index \"{index['name']}\" duplicates \"{seen[key]}\"; "
                            f"both cover ({columns})."
                        ),
                        hint=(
                            "Two indexes over the same columns cost writes and "
                            "storage for no gain. Drop one."
                        ),
                    )
                    continue
                seen[key] = index["name"]


class RedundantPrefixIndex(Rule):
    """JOIST-IDX-003: a non-unique index whose columns are a left prefix of
    another index. Unique indexes are kept: they enforce a constraint the
    longer index does not."""

    code = "JOIST-IDX-003"
    category = Category.INDEX
    confidence = Confidence.HIGH
    default_severity = Severity.WARNING
    title = "Index is a left prefix of another index"

    def check(self, snapshot: dict, connection: str) -> Iterable[Finding]:
        for table in snapshot.get("tables", []):
            indexes = table.get("indexes", [])
            for index in indexes:
                if index.get("unique"):
                    continue
                columns = index.get("columns") or []
                covered = self._covering_index(indexes, index, columns)
                if covered is None:
                    continue
                shorter = ", ".join(columns)
                longer = ", ".join(covered.get("columns") or [])
                yield Finding(
                    code=self.code,
                    severity=self.default_severity,
                    connection=connection,
                    table=table["name"],
                    column=index["name"],
                    message=(
                        f"Index \"{index['name']}\" on ({shorter}) is a left prefix of "
                        f"\"{covered['name']}\" on ({longer}), so it is redundant."
                    ),
                    hint=(
                        "A composite index already serves queries on its leading "
                        "columns, so the shorter index can be dropped."
                    ),
                )

    @staticmethod
    def _covering_index(indexes: list[dict], index: dict, columns: list[str]) -> dict | None:
        count = len(columns)
        for other in indexes:
            if other.get("name") == index.get("name"):
                continue
            other_columns = other.get("columns") or []
            if len(other_columns) > count and other_columns[:count] == columns:
                return other
        return None


class IndexDuplicatingPrimaryKey(Rule):
    """JOIST-IDX-004: an index whose columns are exactly the primary key, in
    the same order. The primary key is already a unique index."""

    code = "JOIST-IDX-004"
    category = Category.INDEX
    confidence = Confidence.HIGH
    default_severity = Severity.WARNING
    title = "Index duplicates the primary key"

    def check(self, snapshot: dict, connection: str) -> Iterable[Finding]:
        for table in snapshot.get("tables", []):
            primary_key = table.get("primary_key") or []
            if not primary_key:
                continue
            for index in table.get("indexes", []):
                if (index.get("columns") or []) != primary_key:
                    continue
                columns = ", ".join(primary_key)
                yield Finding(
                    code=self.code,
                    severity=self.default_severity,
                    connection=connection,
                    table=table["name"],
                    column=index["name"],
                    message=(
                        f"Index \"{index['name']}\" duplicates the primary key "
                        f"({columns}), which is already a unique index."
                    ),
                    hint=(
                        "The primary key is indexed already, so a second index over "
                        "the same columns is redundant. Drop it."
                    ),
                )


class UnindexedSoftDelete(Rule):
    """JOIST-IDX-005: a soft-delete column that no index covers. Soft-deleted
    rows add "where <marker> is null" to every query, so leaving it unindexed
    scans the table. Any index that *includes* the column satisfies the rule.

    Django adaptation: Django has no native soft delete, so the marker column
    names come from ``JOIST['doctor']['soft_delete_columns']`` (default
    deleted_at / deleted / removed_at), and the column must be nullable and
    date/time-typed to count.
    """

    code = "JOIST-IDX-005"
    category = Category.INDEX
    confidence = Confidence.HEURISTIC
    default_severity = Severity.WARNING
    title = "Soft-delete column without an index"

    def check(self, snapshot: dict, connection: str) -> Iterable[Finding]:
        from django_joist.conf import joist_settings

        # Sole deviation from the "rules never read config" contract, made
        # because Django has no fixed soft-delete column name: the marker
        # list is project knowledge, not structure. It is read here rather
        # than injected into the snapshot so a rule run standalone (tests,
        # scripts) behaves like it does inside a report.
        markers = list(joist_settings.get("doctor.soft_delete_columns", []) or [])

        for table in snapshot.get("tables", []):
            for column in table.get("columns", []):
                name = column.get("name", "")
                if name not in markers:
                    continue
                ctype = str(column.get("type", "")).lower()
                if not any(word in ctype for word in ("date", "time", "timestamp")):
                    continue
                if not column.get("nullable"):
                    continue
                if any(name in (idx.get("columns") or []) for idx in table.get("indexes", [])):
                    continue
                yield Finding(
                    code=self.code,
                    severity=self.default_severity,
                    connection=connection,
                    table=table["name"],
                    column=name,
                    message=(
                        f"Soft-delete column \"{table['name']}.{name}\" is not indexed, "
                        "so every query filters an unindexed column."
                    ),
                    hint=(
                        f'Soft-deleted rows are filtered with "where {name} is null" on '
                        "every query. Indexing the column, often as part of a composite "
                        "index, keeps those scans cheap. Ignore this on small tables."
                    ),
                )


class MissingUniqueConstraint(Rule):
    """JOIST-IDX-006: a column whose name reads like a unique identifier
    (email, slug, uuid, token) but with no unique constraint. Heuristic:
    duplicates may be intended, so it stays off the recommended default."""

    code = "JOIST-IDX-006"
    category = Category.INDEX
    confidence = Confidence.HEURISTIC
    default_severity = Severity.WARNING
    title = "Identifier column without a unique constraint"

    IDENTIFIERS = ["email", "slug", "uuid", "token"]

    def check(self, snapshot: dict, connection: str) -> Iterable[Finding]:
        for table in snapshot.get("tables", []):
            unique_columns = {
                c
                for index in table.get("indexes", [])
                if index.get("unique")
                for c in index.get("columns") or []
            }
            primary_key = table.get("primary_key") or []

            for column in table.get("columns", []):
                name = column.get("name", "")
                if name.lower() not in self.IDENTIFIERS:
                    continue
                if name in unique_columns or primary_key == [name]:
                    continue
                yield Finding(
                    code=self.code,
                    severity=self.default_severity,
                    connection=connection,
                    table=table["name"],
                    column=name,
                    message=(
                        f"Column \"{table['name']}.{name}\" looks like a unique "
                        "identifier but has no unique constraint."
                    ),
                    hint=(
                        "Columns like email, slug, uuid, and token are usually unique. "
                        "A unique index prevents duplicates and speeds lookups. Add "
                        "one, or ignore this if duplicates are intended."
                    ),
                )
