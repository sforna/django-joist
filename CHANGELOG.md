# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- The vendored Mermaid moves from 11.16.0 to 11.17.2 - the verbatim
  `dist/mermaid.min.js` of that npm release, as before. The version is now
  recorded in `mermaid.LICENSE` and asserted by `tests/test_static.py`
  together with the bundle's flavour (the IIFE that assigns the `mermaid`
  global), so a swapped file, a forgotten note and an ESM-only build each fail
  there instead of shipping a blank diagram with no error.

- A default palette of its own. The shipped colours were byte-for-byte those
  of the reference implementation, so a default install was indistinguishable
  from it: a navy blueprint on a blue-tinted canvas. The default is now a
  neutral graphite canvas with an indigo ink and a magenta accent, in both
  themes. Only colours changed - the drafting grid, the layout and the JS are
  untouched, and every host-configured `JOIST["theme"]` knob still wins.
- The FK connector lines now meet 3:1 against the canvas in light mode
  (`--bp-rel` was 2.92:1, a pre-existing miss). A new
  `tests/test_palette_contrast.py` holds the whole default palette to 4.5:1
  for text pairs and 3:1 for graphic pairs, in all three palette blocks, and
  fails if the two dark blocks drift apart.

### Fixed

- ``JOIST-INT-003`` no longer reports Django's own ``BigAutoField`` DDL as a
  type mismatch on SQLite. The backend declares such a primary key ``integer``
  (SQLite's rowid alias) and every foreign key pointing at it ``bigint``
  (``BigAutoField.rel_db_type``), so the raw names differ on every foreign key
  of every project on the modern default - all of them on the one engine where
  the two are the same column (both INTEGER affinity). Types are now compared
  by affinity on SQLite, and by name everywhere else, because there they must
  match. On the bundled demo schema this turns 30 errors into 1: the 29 false
  positives go, the deliberate unindexed foreign key stays.

- ``JOIST-INT-003`` compares a fallback snapshot's types by SQLite affinity.
  The replay behind `fallback: true` is SQLite whatever the alias's own
  backend, so on an unreachable PostgreSQL or MySQL database the rule compared
  SQLite's type names under the live vendor's rules and reported every foreign
  key as an error. The other rules are still told the live vendor, as in the
  reference, since the findings are about the real database.

- On MySQL the snapshot keeps the index InnoDB builds for each foreign key.
  InnoDB names it after the constraint and Django's introspection reports the
  two as one entry, which the snapshot read as a foreign key only - Django
  creates no index of its own there, so the key looked unindexed.
  ``JOIST-IDX-001`` reported every such key, and the diagram and exports were
  missing the index.

- The shared popover's explanatory comment no longer renders as visible text at
  the bottom of the dashboard. Django's template lexer matches `{# ... #}`
  comments without `re.DOTALL`, so the wrapped four-line comment was emitted as
  literal text instead of being stripped.

## [0.1.1] - 2026-09-19

### Fixed

- Fallback snapshot replay no longer aborts when one migration fails: the
  remaining migrations are still applied, so the reconstructed structure stays
  as close to the live schema as possible.
- The dashboard's landmark and live-region structure (WCAG 4.1.3): the toolbar
  is a `<header>`, the three overlays are named `<aside>`s, and the notice
  banner is a polite status region, so a failure to load the schema is
  announced and not only drawn.
- The shared popover is a labelled non-modal dialog, so each of the four menus
  it holds (a table's, a column list, an enum list, the export menu) announces
  what it is.

## [0.1.0] - 2026-09-11

Initial release.

### Added

- Live ER diagram of the database structure, rendered with self-hosted Mermaid
  (no CDN, no build step), with map-style pan/zoom, auto-fit and focus mode
  over a table and its foreign-key neighbours.
- Table-name filter and toggling between native DB types and Django-style
  field labels.
- Structure introspection that reads tables, columns, keys, indexes and
  foreign keys only — row data is never queried.
- Multiple database support: list aliases under `JOIST["connections"]` and
  switch diagrams from the toolbar.
- Exports, from the dashboard and from the CLI: PNG/SVG in the browser;
  DBML, JSON, CSV, Markdown data dictionary, Mermaid and a token-trimmed
  `llm` format via `manage.py joist_export`. Deterministic output, with
  `--check` to fail the build when a committed schema file drifts.
- AI grounding context through `joist_export --format=llm`, with annotations
  for business meaning, `--compact` to trim tokens and `--focus`/`--depth` to
  narrow the export to one neighbourhood.
- Schema diff against the last migration, shown in the dashboard's Changes
  panel and via `manage.py joist_diff`.
- Schema doctor (`manage.py joist_doctor`): 14 deterministic structure rules
  (missing primary keys, unindexed foreign keys, duplicate and
  prefix-redundant indexes, risky types), console and JSON formatters,
  `--fail-on` exit codes for CI, and the same findings in the dashboard's
  Health panel.
- Management commands `joist_show`, `joist_open`, `joist_diff`,
  `joist_rebuild`, `joist_doctor` and `joist_export`, with exit codes wired
  through a common command base.
- Theme support: light/dark "blueprint" by default, re-skinnable through a
  handful of semantic colour and font settings, served as a same-origin
  stylesheet with no inline styles (CSP-safe).
- Automatic snapshot refresh after every `migrate`, degrading gracefully when
  the cache store is unreachable.
- Gated dashboard routes: on by default when `DEBUG = True`, otherwise
  requires an explicit `enabled` flag plus an email allow-list or a custom
  callable authorizer.

### Security

- Routes answer 404 unless explicitly enabled and denials never confirm that
  the dashboard exists.
- Excluded tables are filtered server-side, so their structure never reaches
  the browser.

[Unreleased]: https://github.com/sforna/django-joist/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/sforna/django-joist/releases/tag/v0.1.1
[0.1.0]: https://github.com/sforna/django-joist/releases/tag/v0.1.0
