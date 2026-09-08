"""Doctor engine tests.

Rules are pure functions over synthetic snapshot dicts (no DB); the report
and command are exercised with monkeypatched caches so no test relies on the
test project's own schema."""

from __future__ import annotations

import io
import json

import pytest

from django_joist.doctor import DoctorReport, RuleRegistry, Severity, findings_for
from django_joist.doctor.collection import FindingCollection
from django_joist.doctor.enums import Category, Confidence
from django_joist.doctor.finding import Finding
from django_joist.doctor.rules import (
    BooleanAsString,
    DuplicateIndex,
    ForeignKeyPointsAtWrongTable,
    ForeignKeyTypeMismatch,
    ForeignKeyWithoutIndex,
    IndexDuplicatingPrimaryKey,
    LikelyMissingForeignKey,
    MissingPrimaryKey,
    MissingUniqueConstraint,
    MoneyAsFloat,
    PivotWithoutUniqueKey,
    PolymorphicWithoutIndex,
    RedundantPrefixIndex,
    UnindexedSoftDelete,
)
from django_joist.doctor.runner import DoctorRunner


# -- snapshot builders --------------------------------------------------------
def snap(tables, driver="sqlite"):
    return {"connection": "default", "driver": driver, "tables": tables}


def table(name, columns=None, pk=None, indexes=None, fks=None):
    return {
        "name": name,
        "columns": columns if columns is not None else [col("id")],
        "primary_key": pk if pk is not None else ["id"],
        "indexes": indexes or [],
        "foreign_keys": fks or [],
    }


def col(name, type_="integer", nullable=False, default=None):
    return {"name": name, "type": type_, "nullable": nullable, "default": default}


def idx(name, columns, unique=False):
    return {"name": name, "columns": columns, "unique": unique}


def fk(name, columns, ref_table, ref_columns=("id",), on_update=None, on_delete=None):
    return {
        "name": name,
        "columns": list(columns),
        "references_table": ref_table,
        "references_columns": list(ref_columns),
        "on_update": on_update,
        "on_delete": on_delete,
    }


def check(rule, snapshot):
    return list(rule.check(snapshot, "default"))


# -- registry / runner --------------------------------------------------------
def test_registry_recommended_skips_heuristics():
    codes = {r.code for r in RuleRegistry.default().resolve("recommended")}
    assert "JOIST-INT-001" in codes  # high
    assert "JOIST-TYP-001" not in codes  # heuristic
    assert "JOIST-INT-002" not in codes


def test_registry_strict_and_none():
    strict = RuleRegistry.default().resolve("strict")
    assert len(strict) == 14
    assert RuleRegistry.default().resolve("none") == []


def test_registry_enable_heuristic_disable_high():
    rules = RuleRegistry.default().resolve(
        "recommended",
        enabled={"JOIST-TYP-001": True, "JOIST-INT-001": False},
    )
    codes = {r.code for r in rules}
    assert "JOIST-TYP-001" in codes
    assert "JOIST-INT-001" not in codes


def test_registry_category_filters():
    rules = RuleRegistry.default().resolve("strict", only=["type"])
    assert {r.code for r in rules} == {"JOIST-TYP-001", "JOIST-TYP-002"}
    rules = RuleRegistry.default().resolve("strict", skip=["type", "index"])
    assert all(r.category is Category.INTEGRITY for r in rules)


def test_runner_severity_override_keeps_fingerprint():
    finding = Finding("JOIST-X-1", Severity.INFO, "default", "t", None, "m", "h")
    (overridden,) = (
        DoctorRunner()
        .run(
            [StaticRule([finding])],
            snap([]),
            "default",
            severity_overrides={"JOIST-X-1": Severity.ERROR},
        )
        .all()
    )
    assert overridden.severity is Severity.ERROR
    assert overridden.fingerprint() == finding.fingerprint()


class StaticRule:
    code = "JOIST-X-1"
    category = Category.INTEGRITY
    confidence = Confidence.HIGH
    default_severity = Severity.INFO
    title = "static"

    def __init__(self, findings):
        self._findings = findings

    def check(self, snapshot, connection):
        return self._findings


def test_runner_ignore_patterns():
    finding = Finding("JOIST-X-1", Severity.ERROR, "default", "audit_log", "actor_id", "m", "h")
    rules = [StaticRule([finding])]
    run = lambda ignore: len(DoctorRunner().run(rules, snap([]), "default", ignore=ignore))
    assert run({}) == 1
    assert run({"JOIST-X-1": ["audit_log.*"]}) == 0
    assert run({"JOIST-X-1": ["audit_log.actor_id"]}) == 0
    assert run({"JOIST-X-1": ["other*"]}) == 1
    # a pattern registered under a different code does not silence it
    assert run({"JOIST-Y-9": ["audit_log"]}) == 1


def test_collection_sort_order():
    f_err = Finding("JOIST-B", Severity.ERROR, "d", "zeta", None, "m", "h")
    f_warn = Finding("JOIST-A", Severity.WARNING, "d", "alpha", None, "m", "h")
    f_info = Finding("JOIST-C", Severity.INFO, "d", "mid", None, "m", "h")
    ordered = FindingCollection([f_info, f_warn, f_err]).sorted()
    assert [f.code for f in ordered] == ["JOIST-B", "JOIST-A", "JOIST-C"]


# -- integrity rules ------------------------------------------------------------
def test_missing_primary_key():
    findings = check(MissingPrimaryKey(), snap([table("logs", pk=[])]))
    assert len(findings) == 1
    assert findings[0].code == "JOIST-INT-001"
    assert check(MissingPrimaryKey(), snap([table("ok")])) == []


def test_likely_missing_foreign_key():
    snapshot = snap(
        [
            table("orders", columns=[col("id"), col("customer_id", "bigint")]),
            table("customers"),
            table("morphed", columns=[col("id"), col("imageable_id", "bigint"), col("imageable_type", "varchar(255)")]),
            table("generic", columns=[col("id"), col("object_id", "integer"), col("content_type_id", "integer")]),
        ]
    )
    findings = check(LikelyMissingForeignKey(), snapshot)
    assert [f.column for f in findings] == ["customer_id"]  # singular/plural match
    # morph and generic pairs are skipped; object_id's base matches no table anyway


def test_fk_type_mismatch():
    snapshot = snap(
        [
            table(
                "child",
                columns=[col("id"), col("parent_id", "integer")],
                fks=[fk("fk_p", ["parent_id"], "parent")],
            ),
            table("parent", columns=[col("id", "bigint unsigned")]),
        ]
    )
    findings = check(ForeignKeyTypeMismatch(), snapshot)
    assert len(findings) == 1
    assert findings[0].code == "JOIST-INT-003"
    assert "bigint unsigned" in findings[0].message
    # matching types silent
    snapshot["tables"][1]["columns"][0]["type"] = "integer"
    assert check(ForeignKeyTypeMismatch(), snapshot) == []


def test_pivot_without_unique_key():
    pivot_bad = table(
        "book_tag",
        columns=[col("book_id", "bigint"), col("tag_id", "bigint")],
        pk=["book_id", "tag_id"][:0],  # no composite pk
        fks=[fk("fk_b", ["book_id"], "book"), fk("fk_t", ["tag_id"], "tag")],
    )
    pivot_bad["primary_key"] = []
    findings = check(PivotWithoutUniqueKey(), snap([pivot_bad]))
    assert len(findings) == 1
    assert findings[0].code == "JOIST-INT-007"

    # composite PK on the pair satisfies
    good = dict(pivot_bad, primary_key=["book_id", "tag_id"])
    assert check(PivotWithoutUniqueKey(), snap([good])) == []
    # unique index over the pair satisfies
    good = dict(pivot_bad, indexes=[idx("uq", ["tag_id", "book_id"], unique=True)])
    assert check(PivotWithoutUniqueKey(), snap([good])) == []
    # unique index over part of the pair satisfies
    good = dict(pivot_bad, indexes=[idx("uq", ["book_id"], unique=True)])
    assert check(PivotWithoutUniqueKey(), snap([good])) == []
    # ...but a nullable partial unique does not
    maybe = dict(pivot_bad, indexes=[idx("uq", ["book_id"], unique=True)])
    maybe["columns"] = [col("book_id", "bigint", nullable=True), col("tag_id", "bigint")]
    assert len(check(PivotWithoutUniqueKey(), snap([maybe]))) == 1


def test_pivot_detection_requires_join_table_shape():
    # two FKs + payload columns = entity, not pivot
    entity = table(
        "orders",
        columns=[
            col("id"),
            col("customer_id", "bigint"),
            col("address_id", "bigint"),
            col("note", "text"),
            col("created_at", "datetime"),
            col("updated_at", "datetime"),
        ],
        fks=[fk("fk_c", ["customer_id"], "customers"), fk("fk_a", ["address_id"], "addresses")],
    )
    assert check(PivotWithoutUniqueKey(), snap([entity])) == []


def test_polymorphic_without_index():
    bait = table(
        "labels",
        columns=[col("id"), col("content_type_id", "integer"), col("object_id", "integer")],
    )
    findings = check(PolymorphicWithoutIndex(), snap([bait]))
    assert len(findings) == 1
    assert findings[0].code == "JOIST-INT-009"

    covered = dict(bait, indexes=[idx("i", ["content_type_id", "object_id"])])
    assert check(PolymorphicWithoutIndex(), snap([covered])) == []
    # leading-with-content_type only: index over object_id alone does not satisfy
    wrong = dict(bait, indexes=[idx("i2", ["object_id"])])
    assert len(check(PolymorphicWithoutIndex(), snap([wrong]))) == 1


def test_fk_points_at_wrong_table():
    snapshot = snap(
        [
            table(
                "books",
                columns=[col("id"), col("author_id", "bigint")],
                fks=[fk("fk_author", ["author_id"], "users")],
            ),
            table("users"),
            table("authors"),
        ]
    )
    findings = check(ForeignKeyPointsAtWrongTable(), snapshot)
    assert [f.code for f in findings] == ["JOIST-INT-010"]
    # an alias with no same-named table stays quiet
    del snapshot["tables"][2]
    assert check(ForeignKeyPointsAtWrongTable(), snapshot) == []


# -- index rules ------------------------------------------------------------------
def test_fk_without_index_engine_aware():
    t = table("books", columns=[col("id"), col("author_id", "bigint")], fks=[fk("fk", ["author_id"], "authors")])
    (finding,) = check(ForeignKeyWithoutIndex(), snap([t], driver="postgresql"))
    assert finding.severity is Severity.ERROR
    assert finding.code == "JOIST-IDX-001"
    (finding,) = check(ForeignKeyWithoutIndex(), snap([t], driver="mysql"))
    assert finding.severity is Severity.INFO
    # covered by a leading index
    covered = dict(t, indexes=[idx("i", ["author_id", "extra"])])
    assert check(ForeignKeyWithoutIndex(), snap([covered], driver="postgresql")) == []


def test_duplicate_index():
    t = table("x", indexes=[idx("i1", ["a", "b"]), idx("i2", ["a", "b"])])
    findings = check(DuplicateIndex(), snap([t]))
    assert len(findings) == 1 and findings[0].column == "i2"
    # order matters
    t2 = table("x", indexes=[idx("i1", ["a", "b"]), idx("i2", ["b", "a"])])
    assert check(DuplicateIndex(), snap([t2])) == []


def test_redundant_prefix_index():
    t = table("x", indexes=[idx("short", ["a"]), idx("long", ["a", "b"])])
    assert [f.column for f in check(RedundantPrefixIndex(), snap([t]))] == ["short"]
    # a unique short index is kept (enforces a constraint)
    t2 = table("x", indexes=[idx("short", ["a"], unique=True), idx("long", ["a", "b"])])
    assert check(RedundantPrefixIndex(), snap([t2])) == []


def test_index_duplicating_primary_key():
    t = table("x", pk=["id", "tenant_id"], indexes=[idx("dup", ["id", "tenant_id"])])
    findings = check(IndexDuplicatingPrimaryKey(), snap([t]))
    assert len(findings) == 1 and findings[0].code == "JOIST-IDX-004"


def test_unindexed_soft_delete(settings_overrides):
    settings_overrides("doctor.soft_delete_columns", ["deleted_at"])
    t = table("x", columns=[col("id"), col("deleted_at", "datetime", nullable=True)])
    findings = check(UnindexedSoftDelete(), snap([t]))
    assert len(findings) == 1 and findings[0].code == "JOIST-IDX-005"
    covered = dict(t, indexes=[idx("i", ["tenant_id", "deleted_at"])])
    assert check(UnindexedSoftDelete(), snap([covered])) == []
    # non-date typed or non-nullable markers are not soft deletes
    wrong_type = dict(t, columns=[col("id"), col("deleted_at", "varchar(255)", nullable=True)])
    assert check(UnindexedSoftDelete(), snap([wrong_type])) == []


def test_missing_unique_constraint():
    t = table("users", columns=[col("id"), col("email", "varchar(254)")])
    findings = check(MissingUniqueConstraint(), snap([t]))
    assert len(findings) == 1 and findings[0].code == "JOIST-IDX-006"
    scoped = dict(t, indexes=[idx("uq", ["team_id", "email"], unique=True)])
    assert check(MissingUniqueConstraint(), snap([scoped])) == []


# -- type rules ---------------------------------------------------------------------
def test_money_as_float():
    t = table("orders", columns=[col("id"), col("total_price", "double precision"), col("weight", "double precision")])
    findings = check(MoneyAsFloat(), snap([t]))
    assert [f.column for f in findings] == ["total_price"]


def test_boolean_as_string():
    t = table("t", columns=[col("id"), col("is_active", "varchar(6)"), col("has_children", "boolean"), col("issue", "varchar")])
    findings = check(BooleanAsString(), snap([t]))
    assert [f.column for f in findings] == ["is_active"]


# -- report payload (the HTTP contract) -------------------------------------------------
def test_for_snapshot_payload_shape(settings_overrides):
    snapshot = {
        "connection": "default",
        "tables": [
            table("logs", pk=[], columns=[col("id", "integer", nullable=False)]),
            table("bad_money", columns=[col("id"), col("amount", "double precision")]),
        ],
    }
    payload = DoctorReport().for_snapshot("default", snapshot, preset="strict")
    assert set(payload) == {"summary", "findings"}
    assert payload["summary"]["total"] >= 2
    assert payload["summary"]["error"] >= 2  # missing pk + money as float
    finding = next(f for f in payload["findings"] if f["code"] == "JOIST-INT-001")
    assert finding == {
        "code": "JOIST-INT-001",
        "severity": "error",
        "connection": "default",
        "table": "logs",
        "column": None,
        "message": 'Table "logs" has no primary key.',
        "hint": finding["hint"],
        "suggestion": None,
        "confidence": "high",
        "category": "integrity",
        "fingerprint": finding["fingerprint"],
    }
    assert len(finding["fingerprint"]) == 64


def test_for_snapshot_respects_excluded_tables(settings_overrides):
    settings_overrides("excluded_tables", ["logs"])
    snapshot = {"connection": "default", "tables": [table("logs", pk=[])]}
    payload = DoctorReport().for_snapshot("default", snapshot, preset="strict")
    assert payload["summary"]["total"] == 0


def test_findings_for_returns_collection():
    snapshot = {"connection": "default", "tables": [table("logs", pk=[])]}
    collection = findings_for("default", snapshot, preset="strict")
    assert isinstance(collection, FindingCollection)
    assert len(collection) == 1


# -- command ------------------------------------------------------------
class FakeCache:
    def __init__(self, snapshot, last_error=None):
        self._snapshot = snapshot
        self.last_error = last_error

    def get(self, alias=None):
        return self._snapshot


@pytest.fixture()
def command(monkeypatch):
    def make(snapshot, last_error=None):
        from django_joist.management.commands.joist_doctor import Command

        monkeypatch.setattr(
            "django_joist.cache.schema_cache",
            lambda: FakeCache(snapshot, last_error),
        )
        return Command(stdout=io.StringIO(), stderr=io.StringIO())

    return make


def _opts(**kw):
    opts = dict(database=None, table=None, only=None, skip=None, preset=None, format="console", fail_on=None)
    opts.update(kw)
    return opts


def test_command_clean_exit_zero(command):
    snapshot = {"connection": "default", "tables": [table("ok")]}
    cmd = command(snapshot)
    assert cmd.handle(**_opts()) == 0
    assert "no findings" in cmd.stdout.getvalue()


def test_command_fail_on_and_severity_thresholds(command, settings_overrides):
    snapshot = {"connection": "default", "tables": [table("logs", pk=[])]}
    # error finding vs default fail-on=error -> exit 1
    cmd = command(snapshot)
    assert cmd.handle(**_opts(preset="strict")) == 1
    out = cmd.stdout.getvalue()
    assert "JOIST-INT-001" in out and "logs" in out

    # info threshold does not fail on errors?? it does; never disables
    cmd = command(snapshot)
    assert cmd.handle(**_opts(preset="strict", fail_on="never")) == 0

    # recommended preset hides heuristic info findings: warning-only snapshot passes
    snapshot_warn = {
        "connection": "default",
        "tables": [table("m", columns=[col("id"), col("amount", "double precision")])],
    }
    cmd = command(snapshot_warn)
    assert cmd.handle(**_opts(fail_on="error")) == 0  # heuristic off in recommended
    cmd = command(snapshot_warn)
    assert cmd.handle(**_opts(preset="strict", fail_on="warning")) == 1


def test_command_json_format_parses_back(command):
    snapshot = {"connection": "default", "tables": [table("logs", pk=[])]}
    cmd = command(snapshot)
    assert cmd.handle(**_opts(format="json", preset="strict")) == 1
    payload = json.loads(cmd.stdout.getvalue())
    assert payload["summary"]["total"] == len(payload["findings"])
    assert payload["findings"][0]["code"] == "JOIST-INT-001"


def test_command_invalid_option_exit_two(command):
    cmd = command({"connection": "default", "tables": []})
    assert cmd.handle(**_opts(format="yaml")) == 2
    assert "--format" in cmd.stderr.getvalue()
    cmd = command({"connection": "default", "tables": []})
    assert cmd.handle(**_opts(preset="galaxy")) == 2


def test_command_snapshot_error_exit_two(monkeypatch):
    class Boom:
        last_error = None

        def get(self, alias=None):
            raise RuntimeError("no connection")

    from django_joist.management.commands.joist_doctor import Command

    monkeypatch.setattr("django_joist.cache.schema_cache", lambda: Boom())
    cmd = Command(stdout=io.StringIO(), stderr=io.StringIO())
    assert cmd.handle(**_opts()) == 2
    assert "Could not load the schema" in cmd.stderr.getvalue()


def test_command_warns_when_uncached(command):
    snapshot = {"connection": "default", "tables": [table("ok")]}
    cmd = command(snapshot, last_error="no such table: cache")
    assert cmd.handle(**_opts()) == 0
    out = cmd.stdout.getvalue()
    assert "cache store is unavailable" in out
    assert "read live" in out


def test_command_table_and_category_filters(command):
    snapshot = {
        "connection": "default",
        "tables": [table("logs", pk=[]), table("money", columns=[col("id"), col("total", "float")])],
    }
    # recommended hides the heuristic money rule: filtered to "money" there is
    # nothing left to report
    cmd = command(snapshot)
    assert cmd.handle(**_opts(table="money")) == 0

    cmd = command(snapshot)
    rc = cmd.handle(**_opts(table="logs", preset="strict", only="integrity"))
    assert rc == 1
    assert "JOIST-INT-001" in cmd.stdout.getvalue()
    assert "JOIST-TYP" not in cmd.stdout.getvalue()
