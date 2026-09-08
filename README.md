# django-joist

**A live database structure viewer for Django.** Joist introspects your live
schema and renders it as a scrollable, zoomable ER diagram right inside your
app, so you can see how tables actually connect without opening a DB client.
It reads **structure only** — tables, columns, keys, indexes, foreign keys;
row data is never queried or exposed.

> django-joist is a Django port of the concept implemented by
> [Laravel Truss](https://github.com/albertoarena/laravel-truss) (MIT,
> Alberto Arena), which inspired it. The name, branding and Django wiring are
> original; selected front-end code is adapted under MIT with attribution.

## Features

- Live ER diagram of your database, rendered with Mermaid — self-hosted, no
  CDN, no build step.
- Focus mode: a table and its foreign-key neighbours, with a searchable
  picker that stays usable on schemas with hundreds of tables.
- Filter by table name; toggle native DB types against Django-style labels.
- Map-style pan and zoom, auto-fit with a legible floor, plus a Fit button.
- Exports: PNG/SVG from the browser; DBML, JSON, CSV, Markdown data
  dictionary, Mermaid, or a token-trimmed `llm` format — from the dashboard
  or from CI with `manage.py joist_export`. Deterministic: the same schema
  always produces the same bytes, so `joist_export --check` fails the build
  when a committed schema file drifts.
- Feed your real structure to a coding agent as grounding context:
  annotations for business meaning, `--compact` to trim tokens, `--focus` to
  narrow to one neighbourhood. Structure only, never data.
- Schema diff: what changed since the last migration, in the dashboard's
  Changes panel and via `manage.py joist_diff`.
- Schema doctor: `manage.py joist_doctor` reviews the structure for problems
  (missing primary keys, unindexed foreign keys, duplicate indexes, risky
  types) — deterministic, structure-only, safe in CI, with `--fail-on` exit
  codes; the same findings power the dashboard's Health panel.
- Multiple databases: list aliases under `JOIST["connections"]` and switch
  diagrams from the toolbar, each scoped to its own database.
- Light/dark "blueprint" theme, or bring your own: a handful of semantic
  colour/font knobs re-skin the whole dashboard, served as a same-origin
  stylesheet (CSP-safe, no inline styles).
- Rebuilds itself: the cached snapshot refreshes after every `migrate` and
  degrades gracefully when the cache store is unreachable.
- Production-safe by design: routes answer 404 unless enabled, denials never
  confirm the dashboard exists, and excluded tables are filtered server-side
  so their structure never reaches the browser.

## Installation

```bash
pip install django-joist
```

Add the app and mount the dashboard:

```python
# settings.py
INSTALLED_APPS = [
    ...,
    "django_joist",
]

# urls.py
from django.urls import include, path

urlpatterns = [
    ...,
    path("joist/", include("django_joist.urls")),
]
```

Requires Python 3.10+ and Django 4.2+. No migrations, no models, no
`collectstatic` needed (assets are served by the package, gated with the
rest of the dashboard).

## Quick start

By default Joist is enabled when `DEBUG = True`. Start your dev server and
visit `/joist/`.

To run Joist gated on staging or production, set both switches:

```python
JOIST = {
    "enabled": True,
    "authorization": {
        "allowed_emails": ["ada@example.com", "grace@example.com"],
    },
}
```

Outside `DEBUG` the shipped default authorizer admits only allow-listed
emails and **fails closed** on an empty list. To authorize by role instead,
point `authorization.callable` at your own `request -> bool` (a callable or a
dotted path); it fully replaces the default. Denials always return **404**.

> Your project's `AuthenticationMiddleware` must run for the mounted URLs
> (the normal case). Joist's own guard is part of the views and cannot be
> configured away.

## Command line

```bash
python manage.py joist_show                 # the structure as a terminal table
python manage.py joist_open                 # print/open the dashboard URL
python manage.py joist_rebuild              # rebuild the cached snapshot (CI)
python manage.py joist_diff                 # what changed since the last migration
python manage.py joist_doctor               # structure review; exits non-zero on findings
python manage.py joist_export               # DBML to stdout by default
python manage.py joist_export --format=json --output=docs/schema.json
python manage.py joist_export --format=dbml --output=docs/schema.dbml --check  # CI drift check
python manage.py joist_export --tables=orders,order_lines --focus=orders --depth=1 --compact
```

`joist_doctor --format=json` and `--fail-on=warning` make it a CI gate;
`joist_export --check` regenerates, compares, writes nothing and exits `1` on
drift (`2` on usage errors), so a migration that changes the schema without
refreshing the committed file fails the build.

## As AI context

The same export doubles as grounding context for a coding agent, so it stops
inventing columns:

```bash
python manage.py joist_export --format=llm          # dense, token-trimmed plaintext
python manage.py joist_export --compact             # drop defaults and non-unique indexes
python manage.py joist_export --focus=orders --depth=1
```

Annotations add the business meaning a type cannot — declare them in
settings under `JOIST["annotations"]` (per-table, per-column, global notes)
or let Joist read native database comments (Postgres/MySQL) by keeping
`"database"` in `annotations["source"]`. The `llm` format and Markdown/DBML
all render annotations; `--no-annotations` strips them.

Programmatically, the builder is immutable and mirrors the CLI byte-for-byte:

```python
from django_joist import snapshot

text = (
    snapshot()
    .only(["orders", "order_lines"])
    .focus("orders", depth=1)
    .compact()
    .to_dbml()
)
```

## Configuration

Everything lives in one `JOIST` dict; unset keys keep their defaults (nested
dicts merge key-by-key). The common knobs:

| Key | Purpose |
|---|---|
| `enabled` | Master switch; defaults to `DEBUG`. Off = every route 404s |
| `connections` | Visualizable database aliases + per-alias overrides, e.g. `{"analytics": {"excluded_tables": [...]}}`; empty = just `default` |
| `excluded_tables` | Hidden server-side (never sent to the browser). Django bookkeeping tables are pre-listed |
| `authorization.callable` / `.allowed_emails` | Who may view outside `DEBUG`; a custom callable replaces the email allow-list |
| `cache.ttl` / `cache.alias` | Snapshot cache (seconds, `<= 0` = forever) and which `CACHES` entry to use |
| `diagram.type_labels` | `native` (default) or `django` short labels |
| `diagram.mermaid_url` | Point at your own copy/CDN; default self-hosts from the gated asset route |
| `focus.default_depth` | FK-neighbour hops shown on focus |
| `large_schema.warn_above` | Table count that triggers the "use focus/filter" hint |
| `diff.enabled` / `diff.dir` | Schema-diff switch and where the structure-only baseline lives (default `BASE_DIR/var/joist`) |
| `doctor.*` | Preset, per-rule severity/enable, ignore patterns, `fail_on`, dashboard panel switches |
| `annotations.*` | Global notes, per-table/per-column meaning, comment sources |
| `theme.*` | Semantic colour/font knobs for both light and dark |
| `base_url` | Used by `joist_open` to build a browsable URL |

The baseline file under `diff.dir` is the only thing Joist writes to disk;
it is derived and safe to delete — worth gitignoring alongside `var/`.

## The no-data promise

Structure is the `CREATE TABLE` definition: tables, columns (name, native
type, nullability, defaults), primary keys, indexes, foreign keys with
referential actions, and native comments. Row contents are never queried —
not by the dashboard, the API, the CLI, or the doctor. Config
`excluded_tables` are stripped server-side, so an excluded table never
reaches the client, the diff, or an export.

## Development

```bash
pip install -e ".[dev]"
python -m pytest
```

## License

MIT. See [LICENSE](LICENSE) (includes the attribution to Laravel Truss).
Vendored assets carry their own licenses (Mermaid MIT, IBM Plex Mono SIL OFL)
under `src/django_joist/static/joist/`.
