# django-joist

<p align="center">
  <a href="https://pypi.org/project/django-joist/"><img alt="Latest version on PyPI" src="https://img.shields.io/pypi/v/django-joist.svg?style=flat"></a>
  <a href="https://pypi.org/project/django-joist/"><img alt="Downloads" src="https://img.shields.io/pypi/dm/django-joist.svg?style=flat"></a>
  <a href="https://github.com/sforna/django-joist/actions/workflows/tests.yml"><img alt="Tests" src="https://img.shields.io/github/actions/workflow/status/sforna/django-joist/tests.yml?branch=main&amp;label=tests&amp;style=flat"></a>
  <a href="https://pypi.org/project/django-joist/"><img alt="Python versions" src="https://img.shields.io/pypi/pyversions/django-joist.svg?style=flat"></a>
  <a href="https://pypi.org/project/django-joist/"><img alt="Django 5.2+" src="https://img.shields.io/badge/Django-5.2%2B-0C4B33?style=flat&amp;logo=django&amp;logoColor=white"></a>
  <a href="LICENSE"><img alt="License: MIT AND OFL-1.1" src="https://img.shields.io/pypi/l/django-joist.svg?style=flat"></a>
</p>

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
  narrow to one neighbourhood. Only the schema is read — row data is never touched.
- Schema diff: what changed since the last migration, in the dashboard's
  Changes panel and via `manage.py joist_diff`.
- Schema doctor: `manage.py joist_doctor` reviews the structure for problems
  (missing primary keys, unindexed foreign keys, duplicate indexes, risky
  types) — deterministic, structure-only, safe in CI, with `--fail-on` exit
  codes; the same findings power the dashboard's Health panel.
- Multiple databases: list aliases under `JOIST["connections"]` and switch
  diagrams from the toolbar, each scoped to its own database.
- Light/dark drafting-grid theme, or bring your own: a handful of semantic
  colour/font knobs re-skin the whole dashboard, served as a same-origin
  stylesheet (CSP-safe, no inline styles).
- Rebuilds itself: the cached snapshot refreshes after every `migrate` and
  degrades gracefully when the cache store is unreachable.
- Production-safe by design: routes answer 404 unless enabled, denials never
  confirm the dashboard exists, and excluded tables are filtered server-side
  so their structure never reaches the browser.

## Installation

```bash
uv add django-joist
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

Requires Python 3.13+ and Django 5.2+. No migrations, no models, no
`collectstatic` needed (assets are served by the package, gated with the
rest of the dashboard). The dashboard HTML is a template shipped inside the
app, so your `TEMPLATES` must keep `"APP_DIRS": True` for `django_joist`
(the default in `django-admin startproject`); if you disabled it, add the
package's template directory to `DIRS`.

### Development-only install

To keep Joist out of production builds entirely, declare it as a development
dependency of your project, the way `composer require --dev` would:

```bash
uv add --dev django-joist              # deploy with: uv sync --no-dev
poetry add --group dev django-joist    # deploy with: poetry install --without dev
```

Unlike Laravel's auto-discovery, Django imports everything named in
`INSTALLED_APPS` and `urls.py`, so a production build without the package
fails at startup unless both entries are conditional. Test for the package
itself rather than for `DEBUG`, so a deploy that turns `DEBUG` on by mistake
still boots:

```python
# settings.py
from importlib.util import find_spec

if find_spec("django_joist"):
    INSTALLED_APPS += ["django_joist"]

# urls.py
from importlib.util import find_spec

if find_spec("django_joist"):
    urlpatterns += [path("joist/", include("django_joist.urls"))]
```

Removing Joist leaves nothing behind: it has no models and no migrations. The
management commands go with it, so a CI job that runs `joist_doctor` or
`joist_export --check` must install the development dependencies.

To run Joist gated on staging or production instead, install it as a regular
dependency (above) and see the next section.

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
uv sync --extra dev   # creates .venv with the package editable and the test tools
uv run pytest
```

Supported versions are declared once, in `pyproject.toml`, and the CI matrix is
derived from them rather than the other way round: `requires-python` gives the
Python floor, the `Framework :: Django :: *` classifiers give the Django list,
and every combination of the two runs. Because `Django>=5.2` carries no ceiling,
the newest Django release is additionally tested in its own job, so a new Django
is caught here instead of by users — a version added to the metadata belongs in
`.github/workflows/tests.yml` (and in `release.yml`, which repeats the matrix to
gate a tag) in the same commit.

The suite runs on SQLite by default. The PostgreSQL and MySQL lanes are the
same suite against a real server: install the driver (`psycopg[binary]` for
PostgreSQL, `pymysql[rsa]` for MySQL — `tests/settings.py` registers it as
`MySQLdb`) and point the run at one:

```bash
JOIST_TEST_ENGINE=postgres JOIST_TEST_USER=joist JOIST_TEST_PASSWORD=password uv run pytest
```

`JOIST_TEST_HOST`, `JOIST_TEST_PORT`, `JOIST_TEST_DB` and
`JOIST_TEST_DB_SECONDARY` override the rest. `tests/test_backends.py` skips the
server-only assertions when the lane is SQLite, and its canary fails the run if
the snapshot fell back to SQLite instead of reading the server.

The client-side logic has its own suite on Node's built-in test runner (no build
step: the assets ship as native ES modules), and the browser lane drives the real
app in Chromium - plus Firefox for the label-geometry spec, which is the one
thing only a second engine can check (see its comment for why).

```bash
npm install
npm test                                  # the client-side logic and the stylesheet invariants
npx playwright install chromium firefox   # once
JOIST_PYTHON=.venv/bin/python npm run test:e2e
```

`npm run test:e2e` starts the test project itself (`tests/browser/serve.py`) on a
throwaway SQLite file, so it needs the interpreter that has Django and this
package installed: `JOIST_PYTHON` points at it, defaulting to `python`.

## License

MIT. See [LICENSE](LICENSE) (includes the attribution to Laravel Truss).
Vendored assets carry their own licenses (Mermaid MIT, IBM Plex Mono SIL OFL)
under `src/django_joist/static/joist/`.
