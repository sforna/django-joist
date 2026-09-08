"""Typed value objects for the schema snapshot.

Pure data: no database, no framework, no serialization knowledge. The
serialization boundary lives in :mod:`django_joist.introspection.serializer`.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Column:
    name: str
    type: str  # native full type exactly as the database reports it
    nullable: bool
    default: str | None = None
    comment: str | None = None


@dataclass(frozen=True)
class Index:
    name: str
    columns: tuple[str, ...]
    unique: bool


@dataclass(frozen=True)
class ForeignKey:
    name: str
    columns: tuple[str, ...]
    references_table: str
    references_columns: tuple[str, ...]
    on_update: str | None = None
    on_delete: str | None = None


@dataclass(frozen=True)
class Table:
    name: str
    columns: list[Column] = field(default_factory=list)
    primary_key: tuple[str, ...] = ()
    indexes: list[Index] = field(default_factory=list)
    foreign_keys: list[ForeignKey] = field(default_factory=list)
    comment: str | None = None
