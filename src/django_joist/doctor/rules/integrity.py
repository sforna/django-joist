"""Integrity rules (JOIST-INT-*): keys and references that do not add up.

Ported from the reference implementation's Integrity rules with Django
adaptations noted per rule. Code numbers keep the reference's gaps
(INT-004..006 reserved upstream): a code is permanent once released, and
staying aligned with the reference leaves the door open for shared tooling.
"""

from __future__ import annotations

from typing import Iterable

from ..enums import Category, Confidence, Severity
from ..finding import Finding
from .base import Rule, column_type as _column_type, pluralize, table_columns


class MissingPrimaryKey(Rule):
    """JOIST-INT-001: a table with no primary key. Django's models always get
    one, so this fires on ``managed = False`` or legacy tables - exactly where
    nobody checked."""

    code = "JOIST-INT-001"
    category = Category.INTEGRITY
    confidence = Confidence.HIGH
    default_severity = Severity.ERROR
    title = "Table without a primary key"

    def check(self, snapshot: dict, connection: str) -> Iterable[Finding]:
        for table in snapshot.get("tables", []):
            if table.get("primary_key") or []:
                continue
            yield Finding(
                code=self.code,
                severity=self.default_severity,
                connection=connection,
                table=table["name"],
                column=None,
                message=f"Table \"{table['name']}\" has no primary key.",
                hint=(
                    "A primary key uniquely identifies each row. Without one, updates "
                    "and deletes are unreliable, replication and many tools struggle, "
                    "and Django cannot address such a table as a model."
                ),
            )


class LikelyMissingForeignKey(Rule):
    """JOIST-INT-002: a ``*_id`` column whose name matches an existing table
    (plural or singular) but which has no foreign key constraint. Heuristic:
    a strong hint of a missing constraint, but a column can legitimately
    reference a table in another database, so it stays off the recommended
    preset and is ignorable.

    Django adaptation: a sibling ``content_type_id``/``object_id`` pair is a
    GenericForeignKey - a morph target cannot carry a database FK at all -
    and both the ``{base}_type`` sibling case and the ``content_type_id``
    column are skipped.
    """

    code = "JOIST-INT-002"
    category = Category.INTEGRITY
    confidence = Confidence.HEURISTIC
    default_severity = Severity.WARNING
    title = "Foreign-key-shaped column without a constraint"

    def check(self, snapshot: dict, connection: str) -> Iterable[Finding]:
        tables = snapshot.get("tables", [])
        table_names = [t["name"] for t in tables]

        for table in tables:
            constrained = {c for fk in table.get("foreign_keys", []) for c in fk.get("columns", [])}
            column_names = table_columns(table)

            for name in column_names:
                if not name.endswith("_id") or name in constrained:
                    continue

                base = name[:-3]

                # A morph target cannot carry a foreign key at all: the value
                # points at whichever table the sibling type column names.
                if base + "_type" in column_names:
                    continue
                # Django's generic relation marker pairs (content_type_id is
                # itself usually an FK to django_content_type; object_id is
                # the half that can never be constrained).
                if name == "object_id" and "content_type_id" in column_names:
                    continue

                target = self._matching_table(base, table_names)
                if target is None:
                    continue

                yield Finding(
                    code=self.code,
                    severity=self.default_severity,
                    connection=connection,
                    table=table["name"],
                    column=name,
                    message=(
                        f"Column \"{table['name']}.{name}\" looks like a foreign key "
                        f"to \"{target}\" but has no constraint."
                    ),
                    hint=(
                        "A foreign key enforces referential integrity and, on MySQL, "
                        "indexes the column. If this reference is intentionally "
                        "unconstrained (for example across databases), add it to the "
                        "doctor ignore list."
                    ),
                )

    @staticmethod
    def _matching_table(base: str, table_names: list[str]) -> str | None:
        if not base:
            return None
        for candidate in (pluralize(base), base):
            if candidate in table_names:
                return candidate
        return None


class ForeignKeyTypeMismatch(Rule):
    """JOIST-INT-003: a foreign key whose column type does not match the type
    of the key it references. Compared per column, so composite keys are
    covered. Skipped when the referenced table is not in the snapshot."""

    code = "JOIST-INT-003"
    category = Category.INTEGRITY
    confidence = Confidence.HIGH
    default_severity = Severity.ERROR
    title = "Foreign key type does not match the referenced key"

    def check(self, snapshot: dict, connection: str) -> Iterable[Finding]:
        by_name = {t["name"]: t for t in snapshot.get("tables", [])}

        for table in by_name.values():
            for fk in table.get("foreign_keys", []):
                referenced = by_name.get(fk.get("references_table") or "")
                if referenced is None:
                    continue

                for index, column in enumerate(fk.get("columns", [])):
                    referenced_column = (fk.get("references_columns") or [None] * 99)[index] \
                        if index < len(fk.get("references_columns") or []) else None
                    if referenced_column is None:
                        continue

                    local_type = _column_type(table, column)
                    referenced_type = _column_type(referenced, referenced_column)
                    if local_type is None or referenced_type is None or local_type == referenced_type:
                        continue

                    yield Finding(
                        code=self.code,
                        severity=self.default_severity,
                        connection=connection,
                        table=table["name"],
                        column=column,
                        message=(
                            f"Foreign key \"{table['name']}.{column}\" is {local_type} "
                            f"but references \"{fk['references_table']}.{referenced_column}\" "
                            f"which is {referenced_type}."
                        ),
                        hint=(
                            "A foreign key column should have the same type as the key "
                            "it references, or the constraint can fail to create and "
                            "joins are slower. Signed versus unsigned counts as a mismatch."
                        ),
                    )


class PivotWithoutUniqueKey(Rule):
    """JOIST-INT-007: a two-foreign-key pivot table with no unique constraint
    on the key pair, so the same relationship can be stored twice.

    Two single-column foreign keys is necessary but NOT sufficient: a join
    table carries its key pair and almost nothing else (see the reference's
    docs/adr/0003-pivot-detection.md; the thresholds are fitted to real
    schemas). A unique index over PART of the pair also satisfies the rule,
    because it already makes the whole pair unique.
    """

    code = "JOIST-INT-007"
    category = Category.INTEGRITY
    confidence = Confidence.HIGH
    default_severity = Severity.WARNING
    title = "Pivot table without a unique key on its foreign-key pair"

    #: Columns that never count against a table looking like a join table:
    #: the conventional surrogate key and Django's timestamp-name conventions.
    NON_PAYLOAD = ["id", "created_at", "updated_at", "deleted_at", "created", "updated"]

    def check(self, snapshot: dict, connection: str) -> Iterable[Finding]:
        for table in snapshot.get("tables", []):
            pair = self._pivot_pair(table)
            if pair is None or self._has_unique_on_pair(table, pair):
                continue
            yield Finding(
                code=self.code,
                severity=self.default_severity,
                connection=connection,
                table=table["name"],
                column=None,
                message=(
                    f"Pivot table \"{table['name']}\" has no unique key on "
                    f"({pair[0]}, {pair[1]}), so duplicate pairs are possible."
                ),
                hint=(
                    "A many-to-many pivot should put a unique constraint, or a "
                    "composite primary key, on its two foreign keys, otherwise the "
                    "same relationship can be stored twice."
                ),
            )

    def _pivot_pair(self, table: dict) -> list[str] | None:
        foreign_keys = table.get("foreign_keys", [])
        if len(foreign_keys) != 2:
            return None
        columns = []
        for fk in foreign_keys:
            if len(fk.get("columns", [])) != 1:
                return None
            columns.append(fk["columns"][0])
        if not self._looks_like_join_table(table, columns):
            return None
        return columns

    def _looks_like_join_table(self, table: dict, pair: list[str]) -> bool:
        names = table_columns(table)
        payload = len(set(names) - set(pair) - set(self.NON_PAYLOAD))
        primary_key = table.get("primary_key") or []

        if not primary_key or _same_set(primary_key, pair):
            return payload <= 1
        if primary_key == ["id"]:
            return payload == 0
        return False

    def _has_unique_on_pair(self, table: dict, pair: list[str]) -> bool:
        if _same_set(table.get("primary_key") or [], pair):
            return True
        for index in table.get("indexes", []):
            if not index.get("unique"):
                continue
            columns = index.get("columns") or []
            if _same_set(columns, pair):
                return True
            # A unique index over part of the pair already makes the whole
            # pair unique. Nullable columns are excluded: most engines allow
            # repeated NULLs in a unique index.
            if columns and set(columns) <= set(pair) and self._all_non_nullable(table, columns):
                return True
        return False

    @staticmethod
    def _all_non_nullable(table: dict, columns: list[str]) -> bool:
        return all(
            not c.get("nullable") for c in table.get("columns", []) if c["name"] in columns
        )


class PolymorphicWithoutIndex(Rule):
    """JOIST-INT-009: Django's generic relation pair (``content_type_id`` +
    ``object_id``) with no composite index leading with those two columns.
    Without it, every reverse generic-FK lookup scans the table.

    Django adaptation: where Laravel detects any ``{name}_type``/``{name}_id``
    pair, Django's generic relations have exactly one shape
    (``content_type_id`` + ``object_id``), so the rule matches it. Stays
    heuristic: the column-name pair can occur without a GenericForeignKey
    behind it, and a small table does not need the index.
    """

    code = "JOIST-INT-009"
    category = Category.INTEGRITY
    confidence = Confidence.HEURISTIC
    default_severity = Severity.WARNING
    title = "Polymorphic columns without a composite index"

    def check(self, snapshot: dict, connection: str) -> Iterable[Finding]:
        for table in snapshot.get("tables", []):
            names = table_columns(table)
            if "content_type_id" not in names or "object_id" not in names:
                continue
            if self._has_leading_index(table):
                continue
            yield Finding(
                code=self.code,
                severity=self.default_severity,
                connection=connection,
                table=table["name"],
                column="content_type_id",
                message=(
                    "Polymorphic columns \"content_type_id\" and \"object_id\" have "
                    "no composite index, so generic-relation lookups scan the table."
                ),
                hint=(
                    'A GenericForeignKey needs models.Index(fields=["content_type", '
                    '"object_id"]) (or the contenttypes auto-created one) so the '
                    "reverse lookup does not full-scan."
                ),
            )

    @staticmethod
    def _has_leading_index(table: dict) -> bool:
        for index in table.get("indexes", []):
            if (index.get("columns") or [])[:2] == ["content_type_id", "object_id"]:
                return True
        return False


class ForeignKeyPointsAtWrongTable(Rule):
    """JOIST-INT-010: a single-column ``*_id`` foreign key that references one
    table while a table named after the column exists and is a different one.

    The whole difficulty is that most name mismatches are deliberate aliases
    (``author_id -> users``). So the test is not "the names differ" but "the
    name names a table that actually exists, and the key points somewhere
    else". The rule stays quiet unless exactly one candidate resolves, and a
    prefixed schema is matched through the prefix of the referenced table.
    """

    code = "JOIST-INT-010"
    category = Category.INTEGRITY
    confidence = Confidence.HIGH
    default_severity = Severity.ERROR
    title = "Foreign key references a different table from the one it is named after"

    def check(self, snapshot: dict, connection: str) -> Iterable[Finding]:
        tables = snapshot.get("tables", [])
        table_names = [t["name"] for t in tables]

        for table in tables:
            column_names = table_columns(table)
            for fk in table.get("foreign_keys", []):
                columns = fk.get("columns") or []
                if len(columns) != 1:
                    continue
                column = columns[0]
                if not column.endswith("_id"):
                    continue
                base = column[:-3]
                if not base:
                    continue
                if base + "_type" in column_names:
                    continue  # a morph target's name is not a claim about one table
                if base == "content_type" and "object_id" in column_names:
                    continue  # Django's generic FK legitimately targets django_content_type

                referenced = fk.get("references_table")
                if not isinstance(referenced, str) or not referenced:
                    continue

                named = self._table_the_name_names(base, table_names, referenced)
                if named is None or named == referenced:
                    continue

                yield Finding(
                    code=self.code,
                    severity=self.default_severity,
                    connection=connection,
                    table=table["name"],
                    column=column,
                    message=(
                        f"Foreign key \"{table['name']}.{column}\" references "
                        f"\"{referenced}\", but a table named \"{named}\" exists and "
                        "is what the column name points to."
                    ),
                    hint=(
                        "A foreign key validates against the table it references, so "
                        "this one rejects a valid id unless the same id also exists "
                        "in the referenced table, and ON DELETE CASCADE fires when the "
                        "wrong parent row is deleted. If the reference is a deliberate "
                        "alias, add it to the doctor ignore list."
                    ),
                )

    @staticmethod
    def _table_the_name_names(base: str, table_names: list[str], referenced: str) -> str | None:
        candidates = list(dict.fromkeys([pluralize(base), base]))
        for candidate in candidates:
            matches = []
            for name in table_names:
                if name == candidate:
                    matches.append(name)
                    continue
                if not name.endswith("_" + candidate):
                    continue
                prefix = name[: -len(candidate)]
                # Same prefix as the table the key already points at, so this
                # is the same application's schema rather than another one
                # that happens to use the word.
                if referenced.startswith(prefix):
                    matches.append(name)
            if len(matches) == 1:
                return matches[0]
            if matches:
                return None
        return None


def _same_set(a: list[str], b: list[str]) -> bool:
    return sorted(a) == sorted(b)
