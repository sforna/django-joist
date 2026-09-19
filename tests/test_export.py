"""Export pipeline tests: generators' exact bytes, determinism, transforms,
annotation precedence, builder immutability, and the CLI exit codes."""

from __future__ import annotations

import copy
import io
import json

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from django_joist.export.annotator import Annotator, comments_from_snapshot
from django_joist.export.builder import ExportBuilder
from django_joist.export.exporter import SchemaExporter
from django_joist.export.transforms import CompactTransform, FocusTransform


# -- synthetic snapshot fixtures --------------------------------------------
def col(name, type_="integer", nullable=False, default=None, **extra):
    return {"name": name, "type": type_, "nullable": nullable, "default": default, **extra}


def idx(name, columns, unique=False):
    return {"name": name, "columns": list(columns), "unique": unique}


def fk(name, columns, ref_table, ref_columns=("id",), on_update=None, on_delete=None):
    return {
        "name": name,
        "columns": list(columns),
        "references_table": ref_table,
        "references_columns": list(ref_columns),
        "on_update": on_update,
        "on_delete": on_delete,
    }


def table(name, columns, pk=("id",), indexes=(), fks=(), **extra):
    return {
        "name": name,
        "columns": list(columns),
        "primary_key": list(pk),
        "indexes": list(indexes),
        "foreign_keys": list(fks),
        **extra,
    }


AUTHOR = table("author", [col("id", "bigint")])
BOOK = table(
    "book",
    [
        col("id", "bigint"),
        col("author_id", "bigint"),
        col("title", "varchar(255)", default="untitled"),
        col("kind", "enum('a','b')", nullable=True),
    ],
    indexes=[idx("uq_author_title", ["author_id", "title"], unique=True)],
    fks=[fk("book_author_fk", ["author_id"], "author", on_delete="cascade")],
)
BOOKTAG = table(
    "booktag",
    [col("id", "bigint"), col("book_id", "bigint"), col("tag_id", "bigint")],
    indexes=[idx("uq_pair", ["book_id", "tag_id"], unique=True), idx("i_tag", ["tag_id"])],
    fks=[fk("bt_book", ["book_id"], "book"), fk("bt_tag", ["tag_id"], "tag")],
)
TAG = table("tag", [col("id", "bigint"), col("slug", "varchar(50)", nullable=True)])


@pytest.fixture()
def fake_tables():
    return [copy.deepcopy(t) for t in (AUTHOR, BOOK, BOOKTAG, TAG)]


class FakeCache:
    """A SchemaCacheRepository stand-in over a fixed snapshot."""

    def __init__(self, tables, alias="default"):
        self.snapshot = {
            "connection": alias,
            "generated_at": "2026-01-01T00:00:00+00:00",
            "fallback": False,
            "fallback_error": None,
            "skipped_migrations": [],
            "tables": tables,
        }
        self.last_error = None
        self.rebuilds = 0
        self._alias = alias

    def managed_aliases(self):
        return [self._alias]

    def get(self, alias=None):
        return copy.deepcopy(self.snapshot)

    def rebuild(self, alias=None):
        self.rebuilds += 1
        return copy.deepcopy(self.snapshot)


@pytest.fixture()
def builder(fake_tables):
    return ExportBuilder(cache=FakeCache(fake_tables))


# -- generators: exact bytes --------------------------------------------------
def test_dbml_exact_output():
    # Generators render in the order given; ordering is tables_for()'s job.
    out = SchemaExporter().generate("dbml", [copy.deepcopy(AUTHOR), copy.deepcopy(BOOK)])
    assert out == (
        "Table author {\n"
        "  id bigint [pk]\n"
        "}\n"
        "\n"
        "Table book {\n"
        "  id bigint [pk]\n"
        "  author_id bigint [not null]\n"
        "  title varchar(255) [not null, default: 'untitled']\n"
        '  kind "enum(\'a\',\'b\')"\n'
        "\n"
        "  indexes {\n"
        "    (author_id, title) [unique]\n"
        "  }\n"
        "}\n"
        "\n"
        "Ref: book.author_id > author.id\n"
    )


def test_dbml_notes_render_as_project_block():
    out = SchemaExporter().generate("dbml", [copy.deepcopy(AUTHOR)], ["UTC everywhere."])
    assert out.startswith("Project joist {\n  Note: '''\n    UTC everywhere.\n  '''\n}\n\n")


def test_dbml_dangling_ref_is_omitted():
    ghost = table("x", [col("id"), col("phantom_id")], fks=[fk("g", ["phantom_id"], "phantom")])
    out = SchemaExporter().generate("dbml", [copy.deepcopy(AUTHOR), copy.deepcopy(BOOK), ghost])
    assert "Ref: book.author_id > author.id" in out
    assert "Ref: x.phantom_id > phantom.id" not in out


def test_json_is_bare_ordered_array():
    out = SchemaExporter().generate("json", [copy.deepcopy(AUTHOR)])
    parsed = json.loads(out)
    assert isinstance(parsed, list) and parsed[0]["name"] == "author"
    # wire field order preserved, not alphabetical
    assert list(parsed[0]["columns"][0].keys()) == ["name", "type", "nullable", "default"]


def test_csv_exact_bytes():
    out = SchemaExporter().generate("csv", [copy.deepcopy(AUTHOR), copy.deepcopy(BOOK)])
    assert out.splitlines() == [
        "table,name,type,nullable,default,key",
        "author,id,bigint,false,,PK",
        "book,id,bigint,false,,PK",
        "book,author_id,bigint,false,,FK",
        "book,title,varchar(255),false,untitled,",
        "book,kind,\"enum('a','b')\",true,,",
    ]


def test_markdown_sections_and_fk_actions():
    out = SchemaExporter().generate("markdown", [copy.deepcopy(BOOK)])
    assert out.startswith("# Data dictionary\n\n## book\n")
    assert "| id | bigint | no |  | PK |" in out
    assert "Indexes: uq_author_title (author_id, title) UNIQUE" in out
    assert "Foreign keys: author_id -> author.id (on delete: cascade)" in out


def test_mermaid_native_types_and_edge():
    out = SchemaExporter().generate("mermaid", [copy.deepcopy(AUTHOR), copy.deepcopy(BOOK)])
    assert out.startswith("erDiagram\n")
    assert "  author {\n    bigint id PK\n  }" in out
    assert "    enum kind" in out  # enum value list collapsed to the keyword
    assert '  author ||--o{ book : "book_author_fk"' in out


def test_llm_markers_and_notes():
    annotated = {**copy.deepcopy(BOOK), "annotation": "one row per book"}
    out = SchemaExporter().generate("llm", [annotated], ["All money is cents."])
    assert out.splitlines()[:3] == ["# 1 table", "# note: All money is cents.", ""]
    assert "book  -- one row per book" in out
    assert "  kind enum('a','b') null" in out
    assert "  author_id bigint pk -> author.id" not in out  # not pk; FK marker only
    assert "  author_id bigint -> author.id" in out


# -- transforms ----------------------------------------------------------------
def test_focus_depths(fake_tables):
    tables = copy.deepcopy(fake_tables)
    assert [t["name"] for t in FocusTransform().apply(tables, "book", 0)] == ["book"]
    one = {t["name"] for t in FocusTransform().apply(tables, "book", 1)}
    assert one == {"book", "author", "booktag"}  # parents and children, both directions
    two = {t["name"] for t in FocusTransform().apply(tables, "book", 2)}
    assert two == {"book", "author", "booktag", "tag"}
    assert FocusTransform().apply(tables, "book", 1)[0]["name"] == "author"  # input order kept


def test_focus_missing_root(fake_tables):
    with pytest.raises(ValueError, match="no such table"):
        FocusTransform().apply(copy.deepcopy(fake_tables), "ghost", 1)


def test_self_reference_is_not_an_edge():
    node = table(
        "node",
        [col("id"), col("parent_id", nullable=True)],
        fks=[fk("node_parent", ["parent_id"], "node")],
    )
    out = SchemaExporter().generate("mermaid", [node])
    assert "||--o{" not in out  # no phantom self-loop
    assert 'parent_id FK "self-ref"' in out


def test_compact_drops_defaults_and_plain_indexes(fake_tables):
    compacted = CompactTransform().apply(copy.deepcopy(fake_tables))
    book = next(t for t in compacted if t["name"] == "book")
    assert all("default" not in c for c in book["columns"])
    assert book["indexes"] == [{"name": "", "columns": ["author_id", "title"], "unique": True}]
    tag = next(t for t in compacted if t["name"] == "tag")
    assert tag["indexes"] == []
    # no tables, columns, or FKs were lost
    assert len(compacted) == len(fake_tables)
    assert len(next(t for t in compacted if t["name"] == "booktag")["foreign_keys"]) == 2


# -- selection and ordering ------------------------------------------------------
def test_config_exclusions_beat_only(fake_tables):
    exporter = SchemaExporter()
    tables = copy.deepcopy(fake_tables)
    # an excluded table cannot be filtered *in*
    out = exporter.tables_for(tables, only=["tag"], config_excluded=["tag"])
    assert out == []


def test_determinism_reordered_input(fake_tables):
    exporter = SchemaExporter()
    a = exporter.generate("dbml", exporter.tables_for(copy.deepcopy(fake_tables)))
    b = exporter.generate(
        "dbml", exporter.tables_for(list(reversed(copy.deepcopy(fake_tables))))
    )
    assert a == b
    ja = exporter.generate("json", exporter.tables_for(copy.deepcopy(fake_tables)))
    jb = exporter.generate(
        "json", exporter.tables_for(list(reversed(copy.deepcopy(fake_tables))))
    )
    assert ja == jb


# -- annotations --------------------------------------------------------------------
def test_comments_are_read_off_the_snapshot(fake_tables):
    tables = copy.deepcopy(fake_tables)
    tables[1]["comment"] = "native book note"
    tables[1]["columns"][2]["comment"] = "native title note"
    comments = comments_from_snapshot(tables)
    assert comments["book"] == "native book note"
    assert comments["book.title"] == "native title note"
    assert "author" not in comments


def test_annotation_precedence_config_over_database(fake_tables, settings_overrides):
    tables = copy.deepcopy(fake_tables)
    tables[1]["comment"] = "db says one thing"
    cache = FakeCache(tables)
    settings_overrides("annotations.tables", {"book": "config wins"})
    settings_overrides("annotations.columns", {"book.title": "the catalog title"})
    builder = ExportBuilder(cache=cache)
    out = builder.to_markdown()
    assert "db says one thing" not in out
    assert "config wins" in out
    assert "the catalog title" in out


def test_empty_config_falls_through_to_database(fake_tables, settings_overrides):
    tables = copy.deepcopy(fake_tables)
    tables[1]["comment"] = "db comment survives"
    settings_overrides("annotations.tables", {"book": "   "})
    out = ExportBuilder(cache=FakeCache(tables)).to_markdown()
    assert "db comment survives" in out


def test_database_source_only(fake_tables, settings_overrides):
    tables = copy.deepcopy(fake_tables)
    tables[1]["comment"] = "from the database"
    settings_overrides("annotations.source", ["database"])
    settings_overrides("annotations.tables", {"book": "ignored"})
    out = ExportBuilder(cache=FakeCache(tables)).to_markdown()
    assert "from the database" in out
    assert "ignored" not in out


def test_without_annotations_strips_everything(fake_tables, settings_overrides):
    settings_overrides("annotations.tables", {"book": "nope"})
    settings_overrides("annotations.notes", ["also nope"])
    builder = ExportBuilder(cache=FakeCache(copy.deepcopy(fake_tables))).without_annotations()
    assert builder.notes() == []
    assert all("annotation" not in t for t in builder.to_array())
    assert "nope" not in builder.to_markdown()


def test_annotator_notes_are_trimmed_and_dropped_when_empty():
    ann = Annotator(source=["config"], notes=["  keep me  ", "", "   "])
    assert ann.notes_list() == ["keep me"]


# -- builder ---------------------------------------------------------------------------
def test_terminals_end_with_exactly_one_newline(builder):
    for fmt in SchemaExporter.formats():
        out = builder.render(fmt)
        assert out.endswith("\n") and not out.endswith("\n\n")


def test_builder_is_immutable_and_branchable(builder):
    author_only = builder.only(["author"])
    no_tag = builder.exclude(["tag"])
    assert {t["name"] for t in author_only.to_array()} == {"author"}
    # exclude removes exactly the named table (booktag survives - not a
    # substring match)
    assert {t["name"] for t in no_tag.to_array()} == {"author", "book", "booktag"}
    # the base is untouched by either branch
    assert {t["name"] for t in builder.to_array()} == {"author", "book", "booktag", "tag"}


def test_fresh_rebuilds_once_and_is_memoised(builder):
    cache = builder._cache
    fresh = builder.fresh()
    fresh.to_array()
    fresh.render("dbml")
    assert cache.rebuilds == 1


def test_focus_depth_defaults_to_setting(builder, settings_overrides):
    settings_overrides("focus.default_depth", 2)
    names = {t["name"] for t in builder.focus("book").to_array()}
    assert names == {"book", "author", "booktag", "tag"}


def test_unmanaged_alias_raises(builder):
    with pytest.raises(ValueError, match="not managed"):
        builder.connection("replica").to_array()


def test_zero_tables_raises(builder):
    with pytest.raises(ValueError, match="No tables matched"):
        builder.only(["ghost"]).to_array()


def test_unknown_format_raises_without_touching_the_cache(builder):
    with pytest.raises(ValueError, match="Unknown export format"):
        builder.render("toml")
    assert builder._resolved is None


# -- command ----------------------------------------------------------------------------
def _opts(**over):
    options = {
        "format": None,
        "output": None,
        "database": None,
        "tables": "",
        "exclude": "",
        "focus": None,
        "depth": None,
        "compact": False,
        "no_annotations": False,
        "fresh": False,
        "check": False,
    }
    options.update(over)
    return options


def _run(**over):
    from django_joist.management.commands.joist_export import Command

    out, err = io.StringIO(), io.StringIO()
    cmd = Command(stdout=out, stderr=err)
    code = cmd.handle(**_opts(**over))
    return code, out.getvalue(), err.getvalue()


@pytest.mark.django_db
def test_command_stdout_is_the_deterministic_artifact(tmp_path):
    code, out, _ = _run(format="dbml")
    assert code == 0
    assert "Table testapp_book" in out
    # no volatile envelope: rerunning yields identical bytes
    _, out2, _ = _run(format="dbml")
    assert out == out2


@pytest.mark.django_db
def test_command_writes_file_and_check_gate(tmp_path):
    target = tmp_path / "schema.dbml"
    code, _, _ = _run(format="dbml", output=str(target))
    assert code == 0
    assert target.is_file()

    # unchanged -> up to date, exit 0
    code, out, _ = _run(format="dbml", output=str(target), check=True)
    assert code == 0 and "up to date" in out

    # drifted -> exit 1, nothing rewritten
    stale = target.read_text() + "\n-- drift --\n"
    target.write_text(stale)
    code, _, err = _run(format="dbml", output=str(target), check=True)
    assert code == 1 and "out of date" in err
    assert target.read_text() == stale  # --check writes nothing


@pytest.mark.django_db
def test_command_usage_errors_exit_2(tmp_path):
    with pytest.raises(CommandError) as exc:
        _run(format="toml")
    assert exc.value.returncode == 2

    with pytest.raises(CommandError) as exc:
        _run(check=True)  # --check without --output
    assert exc.value.returncode == 2

    with pytest.raises(CommandError) as exc:
        _run(tables="nosuch_table")
    assert exc.value.returncode == 2

    with pytest.raises(CommandError) as exc:
        _run(database="not_configured")
    assert exc.value.returncode == 2

    with pytest.raises(CommandError) as exc:
        _run(output=str(tmp_path / "no" / "such" / "dir.dbml"))
    assert exc.value.returncode == 2


@pytest.mark.django_db
def test_command_config_exclusion_wins_over_tables_flag():
    # Asking only for a config-excluded table selects nothing, and the command
    # says so with a usage error rather than emitting an empty artifact.
    with pytest.raises(CommandError) as exc:
        _run(format="json", tables="django_migrations")
    assert exc.value.returncode == 2


@pytest.mark.django_db
def test_command_excludes_django_noise_by_default():
    code, out, _ = _run(format="dbml")
    assert code == 0
    assert "django_migrations" not in out


@pytest.mark.django_db
def test_command_focus_and_compact():
    code, out, _ = _run(format="llm", focus="testapp_book", depth=1)
    assert code == 0
    lines = out.splitlines()
    # depth 1: book's parents (author, publisher) and child (booktag) appear
    # as blocks; tag is a depth-2 neighbour: no block, though booktag's inline
    # `-> testapp_tag.id` reference may still name it.
    assert "testapp_book" in lines
    assert "testapp_author" in lines
    assert "testapp_booktag" in lines
    assert "testapp_tag" not in lines

    # compact in action: the unique index survives with its internal name
    # cleared, and (in markdown, where indexes render) that is visible.
    _, full_md, _ = _run(format="markdown", tables="testapp_book")
    assert "uq_book_author_title (author_id, title) UNIQUE" in full_md
    _, compact_md, _ = _run(format="markdown", tables="testapp_book", compact=True)
    assert "uq_book_author_title" not in compact_md
    assert "(author_id, title) UNIQUE" in compact_md


# -- CLI surface: the argument parser and the process exit status -----------
# The runs above build the options dict by hand, so ``add_arguments`` is never
# exercised: a typo'd ``dest``, a flag that never reached the parser or a missing
# ``type=int`` would pass every one of them. These go through the real argv path.
# Both aliases are marked because ``execute()`` runs Django's own system checks,
# which read the connection's feature flags; the snapshot itself stays the test
# project's.
@pytest.mark.django_db(databases=["default", "secondary"])
def test_argv_flags_reach_the_builder(settings_overrides):
    settings_overrides("annotations.tables", {"testapp_book": "nope"})
    out = io.StringIO()
    call_command(
        "joist_export",
        "--format", "json",
        "--database", "default",
        "--tables", "testapp_book,testapp_author",
        "--exclude", "testapp_author",
        "--compact",
        "--no-annotations",
        stdout=out,
    )
    text = out.getvalue()
    payload = json.loads(text)
    # --tables selects and --exclude subtracts: the author survives only as a
    # foreign-key target name, never as an exported table.
    assert [t["name"] for t in payload] == ["testapp_book"]
    assert "uq_book_author_title" not in text  # --compact drops the index name
    assert "nope" not in text  # --no-annotations wins over annotations.tables


@pytest.mark.django_db(databases=["default", "secondary"])
def test_argv_depth_is_parsed_as_an_int():
    out = io.StringIO()
    call_command(
        "joist_export", "--format", "llm", "--focus", "testapp_book", "--depth", "1", stdout=out
    )
    lines = out.getvalue().splitlines()
    assert "testapp_author" in lines  # depth 1: a parent
    assert "testapp_tag" not in lines  # depth 2, so out of reach


@pytest.mark.django_db(databases=["default", "secondary"])
def test_argv_check_drift_is_the_process_status(tmp_path):
    target = tmp_path / "schema.dbml"
    call_command("joist_export", "--format", "dbml", "--output", str(target))
    assert target.is_file()
    target.write_text(target.read_text() + "\n-- drift --\n")

    err = io.StringIO()
    with pytest.raises(SystemExit) as exc:
        call_command("joist_export", "--check", "--output", str(target), stderr=err)
    # 1 is the gate CI reads, not a return value Django would discard.
    assert exc.value.code == 1
    assert "out of date" in err.getvalue()


@pytest.mark.django_db(databases=["default", "secondary"])
def test_argv_usage_error_is_reported_and_exits_two():
    from django_joist.management.commands.joist_export import Command

    cmd = Command(stdout=io.StringIO(), stderr=io.StringIO())
    with pytest.raises(SystemExit) as exc:
        cmd.run_from_argv(["manage.py", "joist_export", "--format", "toml"])
    assert exc.value.code == 2
    # run_from_argv is the only place that prints a CommandError and turns its
    # returncode into the process status; call_command lets it propagate instead.
    assert "CommandError: Unknown --format [toml]" in cmd.stderr.getvalue()
