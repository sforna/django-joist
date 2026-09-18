"""The introspection paths a live SQLite connection never reaches: the generic
type composition used when a vendor has no native type string, the two
normalizers that absorb backend shape differences, the comment fields the
serializer only emits on backends that have them, and the rule that enrichment
is never fatal.

Pure functions over plain values - no database here on purpose, so they can be
pinned for PostgreSQL and MySQL while those lanes are still missing.
"""

import logging

import pytest
from django.db import models

from django_joist.introspection import native
from django_joist.introspection.builder import SnapshotBuilder
from django_joist.introspection.data import Column, ForeignKey, Index, Table
from django_joist.introspection.native import (
    native_column_comments,
    native_column_types,
    native_fk_actions,
    native_table_comments,
)
from django_joist.introspection.serializer import SchemaSerializer


class Description:
    """The DB-API ``description`` field the generic type path reads."""

    def __init__(self, type_code, internal_size=None, precision=None, scale=None):
        self.type_code = type_code
        self.internal_size = internal_size
        self.precision = precision
        self.scale = scale


# -- column types ------------------------------------------------------------
def test_a_native_type_is_used_verbatim():
    field = Description("numeric", precision=10, scale=2)
    assert SnapshotBuilder._column_type(field, "numeric(10,2)") == "numeric(10,2)"


@pytest.mark.parametrize(
    "type_code,internal_size,expected",
    [
        ("varchar", 10, "varchar(10)"),
        ("char", 1, "char(1)"),
        ("nvarchar", 255, "nvarchar(255)"),
        ("nchar", 4, "nchar(4)"),
        ("varbinary", 16, "varbinary(16)"),
        ("binary", 8, "binary(8)"),
        ("VARCHAR", 20, "VARCHAR(20)"),  # matched case-insensitively, spelled as reported
    ],
)
def test_generic_type_composes_a_length(type_code, internal_size, expected):
    assert SnapshotBuilder._column_type(Description(type_code, internal_size), None) == expected


def test_generic_type_composes_precision_and_scale():
    field = Description("numeric", precision=10, scale=2)
    assert SnapshotBuilder._column_type(field, None) == "numeric(10,2)"


@pytest.mark.parametrize(
    "field",
    [
        Description("text"),
        Description("varchar"),  # no internal size to report
        Description("varchar", internal_size=0),
        Description("int", internal_size=10),  # a length only counts for char-likes
        Description("numeric", precision=None, scale=None),
        Description("numeric", precision=None, scale=2),  # scale alone is not a type
    ],
)
def test_generic_type_falls_back_to_the_bare_type_code(field):
    assert SnapshotBuilder._column_type(field, None) == str(field.type_code)


# -- foreign key references --------------------------------------------------
@pytest.mark.parametrize(
    "refs,expected",
    [
        (("authors", ["id"]), ("authors", ("id",))),
        (("authors", ["id", "tenant_id"]), ("authors", ("id", "tenant_id"))),
        (("authors", "id"), ("authors", ("id",))),  # some backends report one column bare
        (("authors", []), ("authors", ())),
        (("authors", None), ("authors", ())),
        ({"related_table": "authors", "related_columns": ["id"]}, ("authors", ("id",))),
        ({"table": "authors", "columns": ["id"]}, ("authors", ("id",))),
        ({"related_table": "authors", "related_column": "id"}, ("authors", ("id",))),
        ("not-a-pair", (None, ())),
        (None, (None, ())),
        (("a", "b", "c"), (None, ())),
    ],
)
def test_fk_reference_shapes_are_normalized(refs, expected):
    assert SnapshotBuilder._normalize_fk_ref(refs) == expected


# -- referential actions -----------------------------------------------------
@pytest.mark.parametrize(
    "action,expected",
    [
        (None, None),
        ("", None),
        ("   ", None),
        ("CASCADE", "cascade"),
        ("  SET   NULL ", "set null"),
        (models.CASCADE, "cascade"),
        (models.RESTRICT, "restrict"),
        (models.SET_NULL, "set null"),
        (models.SET_DEFAULT, "set default"),
        # Django-level only: the database clause is RESTRICT or absent, so the
        # honest answer is "not specified" rather than inventing one.
        (models.PROTECT, None),
        (models.DO_NOTHING, None),
    ],
)
def test_referential_actions_are_normalized(action, expected):
    assert SnapshotBuilder._normalize_action(action) == expected


def test_an_unknown_callable_is_not_guessed():
    def SOMETHING_ELSE():
        pass

    assert SnapshotBuilder._normalize_action(SOMETHING_ELSE) is None


# -- serializer comments -----------------------------------------------------
def test_serializer_emits_comments_when_the_backend_has_them():
    table = Table(
        name="books",
        columns=[Column("title", "varchar(255)", nullable=False, comment="Human title")],
        primary_key=("id",),
        indexes=[Index("idx_title", ("title",), unique=False)],
        foreign_keys=[
            ForeignKey("fk_author", ("author_id",), "authors", ("id",), on_delete="cascade")
        ],
        comment="Every published book",
    )
    out = SchemaSerializer().table(table)
    assert out["comment"] == "Every published book"
    assert out["columns"][0]["comment"] == "Human title"


@pytest.mark.parametrize("comment", [None, ""])
def test_serializer_omits_empty_comments(comment):
    column = Column("title", "varchar(255)", nullable=False, comment=comment)
    out = SchemaSerializer().table(Table(name="books", columns=[column], comment=comment))
    assert "comment" not in out
    assert "comment" not in out["columns"][0]


# -- enrichment is never fatal -----------------------------------------------
class FakeConnection:
    """Just enough connection for the vendor dispatch: alias and vendor."""

    vendor = "postgresql"
    alias = "default"


def call(helper, connection):
    """Call one of the four readers; only the type reader takes a description map."""
    if helper is native_column_types:
        return helper(connection, ["books"], {})
    return helper(connection, ["books"])


@pytest.mark.parametrize(
    "helper,broken",
    [
        (native_column_types, "_pg_column_types"),
        (native_column_comments, "_pg_column_comments"),
        (native_table_comments, "_pg_table_comments"),
        (native_fk_actions, "_pg_fk_actions"),
    ],
)
def test_a_failed_catalog_query_degrades_to_no_enrichment(monkeypatch, caplog, helper, broken):
    # The four readers are called while building every snapshot: a catalog query
    # that fails (permissions revoked, a dropped extension, a driver quirk) must
    # cost the enrichment, never the diagram.
    def explode(*args, **kwargs):
        raise RuntimeError("catalog query failed")

    monkeypatch.setattr(native, broken, explode)
    with caplog.at_level(logging.DEBUG, logger="joist"):
        result = call(helper, FakeConnection())
    assert result == {}
    assert "unavailable" in caplog.text


@pytest.mark.parametrize(
    "helper",
    [native_column_types, native_column_comments, native_table_comments, native_fk_actions],
)
def test_an_unknown_vendor_simply_has_no_enrichment(helper):
    class UnknownVendor(FakeConnection):
        vendor = "oracle"

    assert call(helper, UnknownVendor()) == {}
