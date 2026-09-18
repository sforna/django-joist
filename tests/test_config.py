"""Configuration: the settings object's access API, its merge rules, and the
promise that importing the package needs no configured settings at all.
"""

import os
import pathlib
import subprocess
import sys

import pytest
from django.test import override_settings

from django_joist import conf
from django_joist.conf import DEFAULTS, joist_settings
from django_joist.introspection.builder import SnapshotBuilder


# -- merging -----------------------------------------------------------------
@override_settings(JOIST={"cache": {"ttl": 0}})
def test_a_partial_block_keeps_its_siblings():
    assert joist_settings.get("cache.ttl") == 0
    assert joist_settings.get("cache.key_prefix") == "joist"  # untouching default
    assert joist_settings.get("cache.alias") is None


@override_settings(
    JOIST={"doctor": {"rules": {"JOIST-INT-001": False}}, "excluded_tables": ["x"]}
)
def test_nested_blocks_merge_and_scalars_replace():
    assert joist_settings.get("doctor.rules.JOIST-INT-001") is False
    assert joist_settings.get("doctor.preset") == "recommended"
    assert joist_settings.get("excluded_tables") == ["x"]  # a list replaces, it does not merge


@override_settings(JOIST={"cache": {"ttl": 0}, "doctor": {"rules": {"JOIST-INT-001": False}}})
def test_merging_never_writes_into_the_defaults():
    # The merge runs over a deep copy: a host's config must not leak into the
    # next project (or into this process's defaults).
    assert joist_settings.get("cache.ttl") == 0
    assert DEFAULTS["cache"]["ttl"] == 3600
    assert DEFAULTS["cache"]["key_prefix"] == "joist"
    assert DEFAULTS["doctor"]["rules"] == {}


@pytest.mark.parametrize(
    "debug,user,expected",
    [
        (True, {}, True),  # unset follows DEBUG, the Django analog of "local"
        (False, {}, False),
        (True, {"enabled": False}, False),
        (False, {"enabled": True}, True),
    ],
)
def test_enabled_resolution(debug, user, expected):
    with override_settings(DEBUG=debug, JOIST=user):
        assert joist_settings.get("enabled") is expected


# -- access ------------------------------------------------------------------
def test_dotted_item_access_and_membership():
    assert joist_settings["cache.ttl"] == 3600
    assert "cache.ttl" in joist_settings
    assert "cache.nope" not in joist_settings
    with pytest.raises(KeyError):
        joist_settings["cache.nope"]


def test_get_falls_back_to_its_default():
    assert joist_settings.get("nope.at.all", "fallback") == "fallback"
    assert joist_settings.get("cache.ttl", "unused") == 3600


def test_attribute_access_reaches_a_config_block():
    assert joist_settings.cache["ttl"] == 3600
    assert joist_settings.doctor["preset"] == "recommended"
    with pytest.raises(AttributeError):
        joist_settings._not_a_block
    # An unknown name is a KeyError, not an AttributeError: pinned so that a
    # change to hasattr()-safe access has to be deliberate.
    with pytest.raises(KeyError):
        joist_settings.not_a_block


def test_reload_discards_the_cached_merge():
    first = joist_settings.wrapped
    assert joist_settings.reload() is None
    assert joist_settings.wrapped is not first  # rebuilt, not reused


def test_the_setting_changed_signal_reloads_the_merge(settings):
    assert joist_settings.get("fallback.enabled") is True
    settings.JOIST = {"fallback": {"enabled": False}}
    assert joist_settings.get("fallback.enabled") is False  # via setting_changed
    settings.JOIST = {}
    assert joist_settings.get("fallback.enabled") is True


# -- importing without a configured project ----------------------------------
def test_importing_the_package_needs_no_configured_settings():
    # The documented promise: a module that only reads structure must not need
    # a project to exist before it can be imported (the lazy SnapshotBuilder
    # export below is the same promise, one level up).
    src = pathlib.Path(__file__).resolve().parents[1] / "src"
    env = {k: v for k, v in os.environ.items() if k != "DJANGO_SETTINGS_MODULE"}
    env["PYTHONPATH"] = str(src)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import django_joist, django_joist.conf, django_joist.diff.differ, "
            "django_joist.introspection.serializer, django_joist.theme",
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr


def test_the_public_exports_are_lazy():
    import django_joist

    assert django_joist.SnapshotBuilder is SnapshotBuilder
    assert joist_settings is conf.joist_settings
    with pytest.raises(AttributeError):
        django_joist.NotAnExport
