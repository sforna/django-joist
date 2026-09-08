"""Foundation tests: snapshot shape, serialization, cache behaviour, selection."""

import pytest

from django_joist.cache import schema_cache
from django_joist.selection import excluded_tables_for, without_excluded_tables

pytestmark = pytest.mark.django_db


def test_snapshot_wire_shape(snapshot):
    assert snapshot["connection"] == "default"
    assert snapshot["fallback"] is False
    assert snapshot["skipped_migrations"] == []
    assert "generated_at" in snapshot
    assert isinstance(snapshot["tables"], list)
    for table in snapshot["tables"]:
        assert set(table) >= {"name", "columns", "primary_key", "indexes", "foreign_keys"}
        for col in table["columns"]:
            assert set(col) >= {"name", "type", "nullable", "default"}
            assert isinstance(col["nullable"], bool)
        assert isinstance(table["primary_key"], list)
        for idx in table["indexes"]:
            assert set(idx) == {"name", "columns", "unique"}
        for fk in table["foreign_keys"]:
            assert set(fk) == {
                "name",
                "columns",
                "references_table",
                "references_columns",
                "on_update",
                "on_delete",
            }


def test_tables_sorted_deterministic(snapshot):
    names = [t["name"] for t in snapshot["tables"]]
    assert names == sorted(names)


def test_foreign_key_captured(tables_by_name):
    book = tables_by_name["testapp_book"]
    fks = {fk["columns"][0]: fk for fk in book["foreign_keys"]}
    assert fks["author_id"]["references_table"] == "testapp_author"
    assert fks["author_id"]["references_columns"] == ["id"]
    # Django on SQLite omits referential actions from the DDL (cascade is
    # app-level), so the DB honestly reports "no action" here. The PRAGMA
    # reader must pass that through, not invent "cascade".
    assert fks["author_id"]["on_delete"] == "no action"


def test_native_types_and_nullability(tables_by_name):
    cols = {c["name"]: c for c in tables_by_name["testapp_book"]["columns"]}
    assert cols["title"]["type"] == "varchar(255)"
    assert cols["title"]["nullable"] is False
    assert cols["price_cents"]["nullable"] is True
    assert cols["data"]["type"] in ("text", "TEXT")  # sqlite JSON storage


def test_composite_unique_constraint_is_an_index(tables_by_name):
    book = tables_by_name["testapp_book"]
    uqs = {i["name"]: i for i in book["indexes"] if i["unique"]}
    assert uqs["uq_book_author_title"]["columns"] == ["author_id", "title"]


def test_primary_key_hoisted_out_of_indexes(tables_by_name):
    book = tables_by_name["testapp_book"]
    assert book["primary_key"] == ["id"]
    assert all(not idx["name"] == "__primary__" for idx in book["indexes"])
    assert all("id" != idx["columns"][0] or idx["columns"] != ["id"] for idx in book["indexes"])


def test_cache_round_trip_and_freshness(snapshot):
    cache = schema_cache()
    again = cache.get("default")
    assert again["generated_at"] == snapshot["generated_at"]  # served from cache
    fresh = cache.rebuild("default")
    assert cache.last_error is None
    assert fresh["generated_at"] >= snapshot["generated_at"]
    assert cache.peek("default") is not None


def test_peek_never_builds():
    from django_joist.cache import schema_cache

    assert schema_cache().peek("default") is None  # nothing cached yet, no DB hit


def test_exclusions_are_server_side(tables_by_name, settings_overrides):
    settings_overrides("excluded_tables", ["testapp_tag"])
    served = without_excluded_tables(list(tables_by_name.values()), "default")
    assert "testapp_tag" not in [t["name"] for t in served]
    assert "testapp_tag" in [t["name"] for t in schema_cache().get()["tables"]]


def test_per_alias_exclusions_merge(settings_overrides):
    settings_overrides("connections.default.excluded_tables", ["testapp_label"])
    assert "testapp_label" in excluded_tables_for("default")
    assert "django_migrations" in excluded_tables_for("default")  # global default kept
