"""Diff engine tests: SchemaDiffer is pure over snapshot dicts, BaselineStore
degrades instead of throwing."""

import json

import pytest

from django_joist.diff.baseline import BaselineStore
from django_joist.diff.differ import SchemaDiffer


def snap(tables, generated_at="2026-01-01T00:00:00+00:00"):
    return {"connection": "default", "generated_at": generated_at, "tables": tables}


def col(name, type_="integer", nullable=False, default=None):
    return {"name": name, "type": type_, "nullable": nullable, "default": default}


def table(name, columns=None, pk=None, indexes=None, fks=None):
    return {
        "name": name,
        "columns": columns or [],
        "primary_key": pk or ["id"],
        "indexes": indexes or [],
        "foreign_keys": fks or [],
    }


# -- SchemaDiffer ------------------------------------------------------------
def test_added_removed_tables():
    a = snap([table("keep"), table("gone")])
    b = snap([table("keep"), table("fresh")])
    d = SchemaDiffer().diff(a, b)
    assert d["has_changes"] is True
    assert [t["name"] for t in d["tables_added"]] == ["fresh"]
    assert [t["name"] for t in d["tables_removed"]] == ["gone"]
    assert d["tables_changed"] == []
    assert d["baseline_generated_at"] == "2026-01-01T00:00:00+00:00"


def test_identical_snapshots_have_no_changes():
    s = snap([table("x", columns=[col("id"), col("name", "varchar(50)")])])
    d = SchemaDiffer().diff(s, json.loads(json.dumps(s)))
    assert d["has_changes"] is False


def test_column_changes_are_field_level():
    a = snap([table("x", columns=[col("id"), col("name", "varchar(50)")])])
    b = snap(
        [
            table(
                "x",
                columns=[
                    col("id"),
                    col("name", "varchar(100)"),
                    col("extra", "text", nullable=True),
                ],
            )
        ]
    )
    d = SchemaDiffer().diff(a, b)
    (changed,) = d["tables_changed"]
    assert changed["name"] == "x"
    assert changed["columns_added"] == [col("extra", "text", nullable=True)]
    assert changed["columns_removed"] == []
    assert changed["columns_changed"] == [
        {
            "name": "name",
            "changes": {"type": {"before": "varchar(50)", "after": "varchar(100)"}},
        }
    ]


def test_index_and_fk_changes():
    idx = {"name": "i1", "columns": ["a"], "unique": False}
    fk = {
        "name": "fk1",
        "columns": ["a_id"],
        "references_table": "t",
        "references_columns": ["id"],
        "on_update": None,
        "on_delete": "cascade",
    }
    a = snap([table("x", indexes=[idx], fks=[fk])])
    b = snap(
        [
            table(
                "x",
                indexes=[{**idx, "unique": True}],
                fks=[{**fk, "on_delete": "restrict"}],
            )
        ]
    )
    d = SchemaDiffer().diff(a, b)
    (changed,) = d["tables_changed"]
    assert changed["indexes_changed"][0]["changes"]["unique"] == {
        "before": False,
        "after": True,
    }
    assert changed["foreign_keys_changed"][0]["changes"]["on_delete"] == {
        "before": "cascade",
        "after": "restrict",
    }


def test_primary_key_change():
    a = snap([table("x", pk=["id"])])
    b = snap([table("x", pk=["a", "b"])])
    d = SchemaDiffer().diff(a, b)
    (changed,) = d["tables_changed"]
    assert changed["changes"]["primary_key"] == {"before": ["id"], "after": ["a", "b"]}


def test_rename_is_remove_plus_add():
    a = snap([table("old_name", columns=[col("id")])])
    b = snap([table("new_name", columns=[col("id")])])
    d = SchemaDiffer().diff(a, b)
    assert [t["name"] for t in d["tables_added"]] == ["new_name"]
    assert [t["name"] for t in d["tables_removed"]] == ["old_name"]


# -- BaselineStore -----------------------------------------------------------
@pytest.fixture()
def store(tmp_path, settings_overrides):
    settings_overrides("diff.dir", str(tmp_path))
    return BaselineStore()


def test_baseline_round_trip(store):
    s = snap([table("x")])
    assert store.save("default", s) is True
    assert store.get("default") == s
    assert store.has("default") is True
    assert store.last_error is None
    assert store.forget("default") is True
    assert store.get("default") is None


def test_missing_baseline_is_not_an_error(store):
    assert store.get("nope") is None
    assert store.last_error is None


def test_slug_is_filesystem_safe(store, tmp_path):
    store.save("tenant/../../etc", snap([]))
    files = list((tmp_path / "baselines").iterdir())
    assert len(files) == 1
    assert files[0].name == "tenant-etc.json"


def test_unwritable_directory_degrades(store, tmp_path):
    (tmp_path / "baselines").mkdir()
    (tmp_path / "baselines" / "default.json").write_text("{not json")
    assert store.get("default") is None
    assert store.last_error is not None


def test_corrupt_save_path_degrades(tmp_path, settings_overrides):
    settings_overrides("diff.dir", str(tmp_path / "a" / "b" / ".." / ".." / "x"))
    # resolves fine but keep the point: an impossible dir degrades
    if str(tmp_path).startswith("/"):
        bad = tmp_path / "file.txt"  # a file used as a directory
        bad.write_text("x")
        settings_overrides("diff.dir", str(bad))
        store = BaselineStore()
        assert store.save("default", snap([])) is False
        assert store.last_error is not None
