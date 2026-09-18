"""The four read/write CLI commands the suite never touched: ``joist_show``,
``joist_open``, ``joist_diff`` and ``joist_rebuild``.

Each is driven through ``handle()``, which is the documented exit-code
contract (``cli.JoistCommand`` turns that int into the process status), so the
assertions cover both the rendered output and the code the shell sees. The
commands are thin over the cache, the selection layer and the baseline store -
what is worth pinning here is the wiring: which alias, which exclusions, and
what a broken cache store or baseline degrades to.
"""

import io
import json

import pytest
from django.core.management import call_command
from django.urls import NoReverseMatch

from django_joist.cache import schema_cache
from django_joist.diff.baseline import BaselineStore
from django_joist.selection import without_excluded_tables

pytestmark = pytest.mark.django_db(databases=["default", "secondary"])

#: Every option each command needs, so a test overrides only what it is about.
OPTIONS = {
    "joist_show": {"database": None},
    "joist_open": {},
    "joist_diff": {"database": None, "json": False},
    "joist_rebuild": {"database": None},
}


# -- helpers -----------------------------------------------------------------
def _module(name):
    import importlib

    return importlib.import_module(f"django_joist.management.commands.{name}")


def _command(name):
    return _module(name).Command(stdout=io.StringIO(), stderr=io.StringIO())


def _run(name, **overrides):
    """Run a command through ``handle()``, returning (exit code, stdout, stderr)."""
    cmd = _command(name)
    code = cmd.handle(**{**OPTIONS[name], **overrides})
    return code, cmd.stdout.getvalue(), cmd.stderr.getvalue()


def _visible(alias="default"):
    """The tables the dashboard would serve for an alias: snapshot minus exclusions."""
    snapshot = schema_cache().get(alias)
    return without_excluded_tables(snapshot["tables"], snapshot["connection"])


def _rows(out):
    """The table-name cell of every data row of the rendered ``joist_show`` table."""
    lines = out.splitlines()
    body = lines[lines.index(next(l for l in lines if l.startswith("| Table"))) + 1 :]
    return [line.split("|")[1].strip() for line in body if line.startswith("|")]


@pytest.fixture()
def baselines(tmp_path, settings_overrides):
    """Redirect the baseline store to a temp dir, as the diff feature expects."""
    settings_overrides("diff.dir", str(tmp_path))
    return tmp_path


@pytest.fixture()
def opened(monkeypatch):
    """Capture the browser launch instead of performing it. Records (argv, kwargs)."""
    launched: list = []
    monkeypatch.setattr(
        _module("joist_open").subprocess,
        "run",
        lambda cmd, **kw: launched.append((cmd, kw)),
    )
    return launched


def _save_baseline(alter=None, alias="default", dropped=()):
    """Persist the current snapshot as the baseline, minus ``dropped`` tables
    (which the diff then reports as added), optionally altered first."""
    snapshot = json.loads(json.dumps(schema_cache().rebuild(alias)))
    if dropped:
        snapshot["tables"] = [t for t in snapshot["tables"] if t["name"] not in dropped]
    if alter is not None:
        alter(snapshot)
    store = BaselineStore()
    assert store.save(alias, snapshot) is True
    return snapshot


# -- joist_show --------------------------------------------------------------
def test_show_prints_every_visible_table():
    code, out, _ = _run("joist_show")
    assert code == 0

    for header in ("Table", "Columns", "Foreign keys"):
        assert header in out
    # The frame is drawn above the header, under it, and under the last row.
    assert sum(1 for line in out.splitlines() if line.startswith("+---")) == 3

    assert _rows(out) == [t["name"] for t in _visible()]  # in snapshot order
    assert "django_migrations" not in out  # excluded by default


def test_show_renders_column_and_foreign_key_counts():
    _, out, _ = _run("joist_show")
    book = next(t for t in _visible() if t["name"] == "testapp_book")
    row = next(line for line in out.splitlines() if line.startswith("| testapp_book "))
    assert [cell.strip() for cell in row.strip("|").split("|")] == [
        "testapp_book",
        str(len(book["columns"])),
        str(len(book["foreign_keys"])),
    ]


def test_show_footer_counts_the_visible_scope():
    _, out, _ = _run("joist_show")
    assert f"{len(_visible())} tables on [default]." in out
    # The snapshot holds more than that: the count is the served scope, not the
    # cached one. The reference prints "9 of 15 tables" here; the count that
    # explains the visible subset is still missing (see TRUSS-LACKS.md).
    assert len(schema_cache().get("default")["tables"]) > len(_visible())


def test_show_points_at_the_diagram():
    _, out, _ = _run("joist_show")
    assert "joist_open" in out


def test_show_database_flag_follows_the_alias():
    out = io.StringIO()
    call_command("joist_show", "--database", "secondary", stdout=out)
    assert "on [secondary]." in out.getvalue()
    assert "testapp_book" in out.getvalue()


def test_show_drops_excluded_tables(settings_overrides):
    settings_overrides("excluded_tables", ["testapp_tag"])
    _, out, _ = _run("joist_show")
    assert "testapp_tag" not in _rows(out)
    assert "testapp_book" in _rows(out)


def test_show_honours_per_alias_exclusions(settings_overrides):
    settings_overrides("excluded_tables", [])
    settings_overrides("connections", {"secondary": {"excluded_tables": ["testapp_book"]}})
    _, out, _ = _run("joist_show", database="secondary")
    assert "testapp_book" not in _rows(out)
    assert "testapp_author" in _rows(out)


def test_show_reports_a_fully_excluded_schema_as_empty(settings_overrides):
    every = [t["name"] for t in schema_cache().get("default")["tables"]]
    settings_overrides("excluded_tables", every)
    code, out, _ = _run("joist_show")
    assert code == 0
    assert "No tables found" in out


def test_show_warns_but_succeeds_when_the_cache_store_is_unavailable(settings_overrides):
    settings_overrides("cache.alias", "not-a-cache")
    code, out, _ = _run("joist_show")
    assert code == 0
    assert "Cache unavailable" in out and "built live" in out
    assert "testapp_book" in out  # complete structure, just built rather than cached


# -- joist_open --------------------------------------------------------------
def test_open_prints_the_url_and_launches_the_browser(opened, settings_overrides):
    settings_overrides("enabled", True)
    code, out, _ = _run("joist_open")
    assert code == 0
    assert "http://127.0.0.1:8000/joist/" in out
    assert "not enabled" not in out

    (argv, kwargs) = opened[0]
    assert "http://127.0.0.1:8000/joist/" in argv
    # Detached and quiet: a launch never prints over the URL we just printed.
    assert kwargs == {"check": False, "timeout": 10, "capture_output": True}


def test_open_honours_base_url(opened, settings_overrides):
    settings_overrides("enabled", True)
    settings_overrides("base_url", "https://example.test/")
    _, out, _ = _run("joist_open")
    assert "https://example.test/joist/" in out
    assert "example.test//joist" not in out


def test_open_warns_when_joist_is_not_enabled(opened, settings):
    settings.DEBUG = False  # enabled follows DEBUG when unset
    code, out, _ = _run("joist_open")
    assert code == 0
    assert "not enabled in this environment" in out
    assert opened  # the printed URL is still the product on an enabled-less host


def test_open_survives_a_headless_host(monkeypatch, settings_overrides):
    settings_overrides("enabled", True)

    def no_opener(*args, **kwargs):
        raise OSError("xdg-open: not found")

    monkeypatch.setattr(_module("joist_open").subprocess, "run", no_opener)
    code, out, _ = _run("joist_open")
    assert code == 0
    assert "/joist/" in out


def test_open_reports_an_unmounted_route(opened, monkeypatch):
    def unmounted(*args, **kwargs):
        raise NoReverseMatch("joist:index")

    monkeypatch.setattr(_module("joist_open"), "reverse", unmounted)
    code, _, err = _run("joist_open")
    assert code == 1
    assert "not found" in err
    assert 'include("django_joist.urls")' in err
    assert not opened  # nothing to open


# -- joist_diff --------------------------------------------------------------
def test_diff_prints_every_kind_of_change(baselines):
    snapshot = schema_cache().rebuild("default")
    baseline = json.loads(json.dumps(snapshot))
    book = next(t for t in baseline["tables"] if t["name"] == "testapp_book")

    # Tables: one added (absent from the baseline), one removed (only there).
    baseline["tables"] = [t for t in baseline["tables"] if t["name"] != "testapp_tag"]
    baseline["tables"].append(
        {
            "name": "legacy_widget",
            "columns": [],
            "primary_key": [],
            "indexes": [],
            "foreign_keys": [],
        }
    )

    # Columns: one added (absent from the baseline), one removed (only there),
    # and a changed type and nullability.
    book["columns"] = [c for c in book["columns"] if c["name"] != "data"]
    book["columns"].append(
        {"name": "legacy_flag", "type": "bool", "nullable": True, "default": None}
    )
    title = next(c for c in book["columns"] if c["name"] == "title")
    title["type"] = "varchar(100)"
    title["nullable"] = True
    book["primary_key"] = ["id", "title"]

    # Indexes: one changed, one added (dropped from the baseline), one removed
    # (present only there).
    uq = next(i for i in book["indexes"] if i["unique"])
    author_index = next(i for i in book["indexes"] if i["columns"] == ["author_id"])
    uq["unique"] = False
    book["indexes"] = [i for i in book["indexes"] if i["name"] != author_index["name"]]
    book["indexes"].append({"name": "idx_legacy", "columns": ["title"], "unique": False})

    # Foreign keys: the same three cases.
    publisher_fk = next(f for f in book["foreign_keys"] if f["columns"] == ["publisher_id"])
    author_fk = next(f for f in book["foreign_keys"] if f["columns"] == ["author_id"])
    publisher_fk["on_delete"] = "cascade"
    book["foreign_keys"] = [f for f in book["foreign_keys"] if f["name"] != author_fk["name"]]
    book["foreign_keys"].append(
        {
            "name": "fk_legacy",
            "columns": ["publisher_id"],
            "references_table": "testapp_publisher",
            "references_columns": ["id"],
            "on_update": None,
            "on_delete": "restrict",
        }
    )

    assert BaselineStore().save("default", baseline) is True
    code, out, _ = _run("joist_diff")
    assert code == 0

    assert "Added tables" in out and "+ testapp_tag" in out
    assert "Removed tables" in out and "- legacy_widget" in out
    assert "~ testapp_book" in out
    assert "column added: data (" in out
    assert "column removed: legacy_flag" in out
    assert "column changed: title (" in out
    assert "type: varchar(100) -> varchar(255)" in out
    assert "nullable: true -> false" in out
    assert f"index added: {author_index['name']}" in out
    assert f"index changed: {uq['name']}" in out
    assert "index removed: idx_legacy" in out
    assert f"foreign key added: {author_fk['name']}" in out
    assert f"foreign key changed: {publisher_fk['name']}" in out
    assert "foreign key removed: fk_legacy" in out
    assert "primary key: [id, title] -> [id]" in out


def test_diff_reports_when_there_are_no_structural_changes(baselines):
    _save_baseline()
    code, out, _ = _run("joist_diff")
    assert code == 0
    assert "No structural changes on [default]" in out


def test_diff_reports_when_no_baseline_has_been_recorded(baselines):
    code, out, _ = _run("joist_diff")
    assert code == 0
    assert "No baseline recorded for [default]" in out
    assert "next migration" in out


def test_diff_reports_when_the_feature_is_disabled(settings_overrides):
    settings_overrides("diff.enabled", False)
    code, out, _ = _run("joist_diff")
    assert code == 0
    assert "Schema diff is disabled" in out
    assert "JOIST['diff']['enabled'] = True" in out


def test_diff_emits_json_when_asked(baselines):
    _save_baseline(dropped=["testapp_tag"])
    out = io.StringIO()
    call_command("joist_diff", "--json", stdout=out)
    payload = json.loads(out.getvalue())
    assert payload["has_changes"] is True
    assert [t["name"] for t in payload["tables_added"]] == ["testapp_tag"]


def test_diff_database_flag_diffs_that_alias(baselines):
    _save_baseline(dropped=["testapp_tag"], alias="secondary")
    code, out, _ = _run("joist_diff", database="secondary")
    assert code == 0
    assert "+ testapp_tag" in out


def test_diff_names_the_setting_when_the_baseline_cannot_be_read(baselines, settings_overrides):
    # "no baseline yet" and "the baseline is unreadable" both read as None from
    # the store; only last_error tells them apart, and they need different advice.
    (baselines / "baselines").mkdir()
    (baselines / "baselines" / "default.json").write_text("{not json")
    code, out, _ = _run("joist_diff")
    assert code == 0
    assert "Could not read the diff baseline" in out
    assert "JOIST['diff']['dir']" in out


def test_diff_still_diffs_when_the_cache_store_is_unavailable(baselines, settings_overrides):
    _save_baseline(dropped=["testapp_tag"])
    settings_overrides("cache.alias", "not-a-cache")
    code, out, _ = _run("joist_diff")
    assert code == 0
    assert "Cache unavailable" in out
    assert "+ testapp_tag" in out


@pytest.mark.parametrize(
    "value,rendered",
    [
        (None, "null"),
        (True, "true"),
        (False, "false"),
        (["a", "b"], "[a, b]"),
        ("varchar(255)", "varchar(255)"),
        (7, "7"),
    ],
)
def test_diff_scalar_rendering(value, rendered):
    assert _command("joist_diff")._scalar(value) == rendered


# -- joist_rebuild -----------------------------------------------------------
def test_rebuild_writes_the_snapshot_and_reports_it():
    code, out, _ = _run("joist_rebuild")
    assert code == 0
    assert "Rebuilt schema snapshot for [default]." in out
    assert schema_cache().peek("default") is not None


def test_rebuild_without_a_database_covers_every_managed_alias(settings_overrides):
    settings_overrides("connections", {"default": {}, "secondary": {}})
    code, out, _ = _run("joist_rebuild")
    assert code == 0
    assert "Rebuilt schema snapshot for [default]." in out
    assert "Rebuilt schema snapshot for [secondary]." in out
    assert schema_cache().peek("secondary") is not None


def test_rebuild_database_flag_targets_one_alias():
    code, out, _ = _run("joist_rebuild", database="secondary")
    assert code == 0
    assert "Rebuilt schema snapshot for [secondary]." in out
    assert schema_cache().peek("default") is None


def test_rebuild_fails_when_the_store_rejects_the_snapshot(settings_overrides):
    # Everywhere else a broken store degrades quietly; here it is the thing the
    # user ran the command to fix, so it must not report success.
    settings_overrides("cache.alias", "not-a-cache")
    code, out, err = _run("joist_rebuild")
    assert code == 1
    assert "could not cache it" in err
    assert "Check your cache backend" in out


def test_rebuild_notes_the_sqlite_fallback(monkeypatch):
    class FallbackCache:
        last_error = None

        def managed_aliases(self):
            return ["default"]

        def rebuild(self, alias):
            return {"connection": alias, "fallback": True}

    monkeypatch.setattr(_module("joist_rebuild"), "schema_cache", lambda: FallbackCache())
    code, out, _ = _run("joist_rebuild")
    assert code == 0
    assert "Rebuilt schema snapshot for [default] (SQLite fallback)." in out


# -- exit-code plumbing ------------------------------------------------------
def test_a_non_zero_exit_code_becomes_the_process_status(settings_overrides):
    settings_overrides("cache.alias", "not-a-cache")
    out, err = io.StringIO(), io.StringIO()
    with pytest.raises(SystemExit) as exc:
        call_command("joist_rebuild", stdout=out, stderr=err)
    assert exc.value.code == 1
    # The wrapper exists because Django would otherwise write a truthy return
    # value to stdout: the exit code must not appear as output.
    assert out.getvalue().strip().splitlines()[-1] == (
        "Check your cache backend (CACHES), then run this again."
    )
    assert "could not cache it" in err.getvalue()


def test_a_clean_run_exits_zero():
    out = io.StringIO()
    call_command("joist_rebuild", stdout=out)  # no SystemExit: a clean run is 0
    assert "Rebuilt schema snapshot for [default]." in out.getvalue()
