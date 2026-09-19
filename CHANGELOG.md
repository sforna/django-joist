# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- Fallback snapshot replay no longer aborts when one migration fails: the
  remaining migrations are still applied, so the reconstructed structure stays
  as close to the live schema as possible.

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

[Unreleased]: https://github.com/sforna/django-joist/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/sforna/django-joist/releases/tag/v0.1.0
