"""The backend-specific half of the suite: what only a real server can show.

SQLite is the local default; CI runs this suite once per backend
(``JOIST_TEST_ENGINE=postgres|mysql`` plus connection variables, see
tests/settings.py). Tests that every backend can answer run everywhere with
per-vendor expectations - the exact native types live in test_foundation.py -
while the ones that need a real server are marked ``native``.

The point is the opposite of portability: the snapshot promises the type, the
default, the referential action and the comment *exactly as the database
reports them*, so each lane asserts its own spelling instead of a common one.
The structure the model fixtures cannot express (explicit foreign-key actions,
a composite primary key, a table without one, defaults, comments) lives in
tests/testapp/migrations/0002_backend_structure.py.
"""

import os

import pytest
from django.db import connection

import django_joist
from django.db import connection, connections

from django_joist.cache import schema_cache
from django_joist.doctor import findings_for

#: Which backend this run is against: "sqlite", "postgres" or "mysql".
LANE = os.environ.get("JOIST_TEST_ENGINE", "sqlite")
VENDOR = {"sqlite": "sqlite", "postgres": "postgresql", "mysql": "mysql"}[LANE]

native = pytest.mark.skipif(LANE == "sqlite", reason="needs a real PostgreSQL or MySQL server")

pytestmark = pytest.mark.django_db


def tables(alias="default"):
    return {t["name"]: t for t in schema_cache().rebuild(alias)["tables"]}


def columns(table):
    return {c["name"]: c for c in table["columns"]}


# -- the lane itself ---------------------------------------------------------
@native
def test_the_lane_really_is_on_its_backend():
    # The canary for these jobs. A server that failed to answer would route the
    # snapshot through the SQLite replay, and the whole lane could pass while
    # testing nothing it was meant to test.
    assert connection.vendor == VENDOR
    snapshot = schema_cache().rebuild("default")
    assert snapshot["fallback"] is False
    assert snapshot["fallback_error"] is None
    assert snapshot["skipped_migrations"] == []
    assert snapshot["tables"]


# -- defaults ----------------------------------------------------------------
def test_a_database_level_default_is_reported_verbatim():
    nopk = tables()["testapp_nopk"]
    assert columns(nopk)["qty"]["default"] == "7"


def test_a_string_default_keeps_the_backends_own_spelling():
    composite = tables()["testapp_compositepk"]
    # 'n/a' with the quotes on SQLite, 'n/a'::character varying on PostgreSQL,
    # a bare n/a on MySQL: whatever the catalog holds, not a normalized value.
    assert "n/a" in columns(composite)["note"]["default"]


def test_a_model_default_is_not_a_database_default():
    # Django writes no DEFAULT clause for migration-created tables: the model's
    # default=0 on price_cents is application-level, so the catalog has none.
    # Only raw DDL (testapp_nopk) carries a real column default.
    assert columns(tables()["testapp_book"])["price_cents"]["default"] is None


# -- referential actions -----------------------------------------------------
def test_explicit_database_level_actions_are_reported():
    fk = tables()["testapp_fkaction"]["foreign_keys"][0]
    assert fk["columns"] == ["author_id"]
    assert fk["references_table"] == "testapp_author"
    assert fk["references_columns"] == ["id"]
    assert fk["on_delete"] == "cascade"
    assert fk["on_update"] == "restrict"


def test_a_model_level_on_delete_never_reaches_the_catalog():
    # The contrast that makes the test above worth having: book.author_id is
    # on_delete=CASCADE on the model and still reads "no action" in the
    # database, on every backend.
    fks = {tuple(f["columns"]): f for f in tables()["testapp_book"]["foreign_keys"]}
    assert fks[("author_id",)]["on_delete"] == "no action"


# -- keys --------------------------------------------------------------------
def test_a_composite_primary_key_keeps_its_column_order():
    table = tables()["testapp_compositepk"]
    assert table["primary_key"] == ["a", "b"]
    assert all(i["columns"] != ["a", "b"] for i in table["indexes"])  # hoisted out


def test_a_table_without_a_primary_key_is_reported_as_such():
    table = tables()["testapp_nopk"]
    assert table["primary_key"] == []
    assert sorted(columns(table)) == ["label", "qty"]


# -- the doctor --------------------------------------------------------------
#: The whole strict verdict on the test app, as (severity, code, table,
#: column). Every rule is unit-tested on synthetic snapshots in test_doctor.py;
#: this is the other half - what the doctor says about a schema each backend
#: really built, so a catalog reader that drops or respells something shows up
#: as a finding gained or lost. Exact on purpose: a new false positive fails
#: here as surely as a missed bait.
_EVERY_LANE = {
    ("error", "JOIST-INT-001", "testapp_nopk", None),
    ("error", "JOIST-TYP-001", "testapp_publisher", "balance"),
    ("warning", "JOIST-INT-009", "testapp_label", "content_type_id"),
    ("warning", "JOIST-IDX-005", "testapp_legacyrow", "deleted_at"),
    ("warning", "JOIST-TYP-002", "testapp_legacyrow", "is_active"),
    ("warning", "JOIST-IDX-006", "testapp_tag", "slug"),
}
_SQLITE_AND_POSTGRES = {
    # The raw-DDL key has no index at all.
    ("error", "JOIST-IDX-001", "testapp_fkaction", "author_id"),
    # Django indexes every foreign key, including one that already leads a
    # unique constraint.
    ("warning", "JOIST-IDX-003", "testapp_book", "testapp_book_author_id_b4b7b7bf"),
    ("warning", "JOIST-IDX-003", "testapp_booktag", "testapp_booktag_book_id_7d7e8ab9"),
    # SlugField's own db_index next to Meta.indexes on the same column.
    ("warning", "JOIST-IDX-002", "testapp_tag", "testapp_tag_slug_c93666de"),
}
DOCTOR_VERDICT = {
    "sqlite": _EVERY_LANE | _SQLITE_AND_POSTGRES,
    "postgres": _EVERY_LANE | _SQLITE_AND_POSTGRES,
    # InnoDB indexes each foreign key itself, under the constraint's name, and
    # Django skips its own index there: nothing is unindexed and nothing is a
    # redundant prefix. Index order also differs, so the duplicate reported is
    # the other one of the pair.
    "mysql": _EVERY_LANE | {("warning", "JOIST-IDX-002", "testapp_tag", "testapp_tag_slug_267481_idx")},
}


def test_the_doctor_verdict_on_the_test_app_is_exactly_the_expected_one():
    snapshot = schema_cache().rebuild("default")
    findings = findings_for("default", snapshot, preset="strict")
    verdict = {
        (f.severity.value, f.code, f.table, f.column)
        for f in findings
        if f.table.startswith("testapp_")
    }
    assert verdict == DOCTOR_VERDICT[LANE]


def test_the_recommended_preset_keeps_only_the_high_confidence_findings():
    # The CI default. Heuristic rules stay quiet, so on a Django-made schema
    # only the raw-DDL bait and Django's own index layout remain.
    snapshot = schema_cache().rebuild("default")
    codes = {f.code for f in findings_for("default", snapshot) if f.table.startswith("testapp_")}
    assert not codes & {"JOIST-INT-002", "JOIST-INT-009", "JOIST-IDX-005", "JOIST-IDX-006", "JOIST-TYP-001", "JOIST-TYP-002"}
    assert "JOIST-INT-001" in codes


def test_the_doctor_sees_no_type_mismatch_in_keys_django_created():
    # Django pairs each key with the type of the one it references (bigint to
    # bigint, and on SQLite bigint to integer, which the rule reads by
    # affinity). Any JOIST-INT-003 here, on any table, is a false positive.
    snapshot = schema_cache().rebuild("default")
    assert [f for f in findings_for("default", snapshot, preset="strict") if f.code == "JOIST-INT-003"] == []


@native
def test_the_doctor_reads_the_live_vendor_not_the_fallback():
    snapshot = schema_cache().rebuild("default")
    assert snapshot["fallback"] is False
    from django_joist.doctor import DoctorReport

    assert DoctorReport._driver_for("default") == VENDOR


# -- comments ----------------------------------------------------------------
def test_comments_come_from_the_catalog_when_the_backend_has_them():
    noted = tables()["testapp_noted"]
    if LANE == "sqlite":
        # SQLite stores no comments at all: the reader must report none rather
        # than invent one.
        assert noted.get("comment") is None
        assert columns(noted)["label"].get("comment") is None
        return
    assert noted["comment"] == "Every noted thing"
    assert columns(noted)["label"]["comment"] == "Human label"


@native
def test_database_comments_reach_the_export(settings_overrides):
    settings_overrides("annotations.source", ["database"])
    text = django_joist.snapshot().only(["testapp_noted"]).to_markdown()
    assert "> Every noted thing" in text
    assert "Human label" in text


@native
def test_configured_annotations_win_over_the_catalog(settings_overrides):
    settings_overrides("annotations.tables", {"testapp_noted": "From config"})
    settings_overrides("annotations.columns", {"testapp_noted.label": "Column from config"})
    text = django_joist.snapshot().only(["testapp_noted"]).to_markdown()
    assert "From config" in text
    assert "Column from config" in text
    assert "Every noted thing" not in text  # config outranks the catalog comment


# -- isolation ---------------------------------------------------------------
@native
@pytest.mark.django_db(databases=["default", "secondary"])
def test_each_alias_reads_only_its_own_database():
    # Two databases on one server: the secondary alias holds a table the
    # default one must never see, so a snapshot keyed by the wrong connection
    # (or an introspection that ignores the selected database) shows up here.
    other = "joist_secondary_only"
    with connections["secondary"].cursor() as cur:
        cur.execute(f"CREATE TABLE {other} (id integer)")
    try:
        assert other in tables("secondary")
        assert other not in tables("default")
    finally:
        with connections["secondary"].cursor() as cur:
            cur.execute(f"DROP TABLE {other}")


@native
@pytest.mark.skipif(LANE != "postgres", reason="schemas are a PostgreSQL concept")
def test_introspection_ignores_tables_outside_the_search_path():
    # A schema the connection cannot see is not part of "this database's
    # structure": pg_table_is_visible is what keeps the diagram honest.
    with connection.cursor() as cur:
        cur.execute("CREATE SCHEMA joist_elsewhere")
        cur.execute("CREATE TABLE joist_elsewhere.outsider (id integer)")
    try:
        assert "outsider" not in tables()
    finally:
        with connection.cursor() as cur:
            cur.execute("DROP SCHEMA joist_elsewhere CASCADE")
