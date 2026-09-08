"""Shared fixtures for the joist test suite."""

import json

import pytest
from django.core.cache import caches

from django_joist.cache import reset_schema_cache, schema_cache
from django_joist.conf import joist_settings


@pytest.fixture(autouse=True)
def _clean_state():
    caches["default"].clear()
    reset_schema_cache()
    yield
    caches["default"].clear()
    reset_schema_cache()


@pytest.fixture()
def snapshot(db):
    """Fresh (uncached) snapshot for the default alias, as a dict."""
    return schema_cache().rebuild("default")


@pytest.fixture()
def tables_by_name(snapshot):
    return {t["name"]: t for t in snapshot["tables"]}


@pytest.fixture()
def settings_overrides():
    """Temporarily deep-set a JOIST key, restoring after the test."""
    applied = []

    def override(path, value):
        applied.append((path, _get(joist_settings.wrapped, path)))
        _set(joist_settings.wrapped, path, value)

    yield override
    for path, (existed, original) in reversed(applied):
        if existed:
            _set(joist_settings.wrapped, path, original)
        else:
            _del(joist_settings.wrapped, path)


def _get(node, path):
    """Return (existed, value) for a dotted path."""
    cur: object = node
    parts = path.split(".")
    for part in parts:
        if not isinstance(cur, dict) or part not in cur:
            return (False, None)
        cur = cur[part]
    return (True, cur)


def _set(node, path, value):
    parts = path.split(".")
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value


def _del(node, path):
    parts = path.split(".")
    for part in parts[:-1]:
        node = node.get(part)
        if not isinstance(node, dict):
            return
    if isinstance(node, dict):
        node.pop(parts[-1], None)
