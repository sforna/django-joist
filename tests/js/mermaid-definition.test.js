import test from 'node:test';
import assert from 'node:assert/strict';

import { generateErDiagram } from '../../src/django_joist/static/joist/js/mermaid-definition.js';
import { authors, books, schema, selfRef } from './fixtures.js';

// The sink of the selection pipeline: whatever the filter and the focus reduced
// the schema to arrives here and becomes the diagram. Mermaid's ER grammar is
// whitespace and quote sensitive, so most of what is worth checking is what the
// generator does to get text safely into it.

const lines = (definition) => definition.split('\n');

test('the diagram opens with erDiagram and an accessible name', () => {
  const definition = generateErDiagram([books, authors]);
  assert.equal(lines(definition)[0], 'erDiagram');
  assert.match(definition, /^ {2}accTitle: Database structure diagram$/m);
});

test('every table becomes an entity block with its columns', () => {
  const definition = generateErDiagram([books]);
  assert.match(definition, /^ {2}books \{$/m);
  assert.match(definition, /^ {4}bigint id PK$/m);
  assert.match(definition, /^ {4}varchar_255 title$/m);
  assert.match(definition, /^ {2}\}$/m);
});

test('a whitespace or punctuation bearing type becomes one token', () => {
  // The grammar splits attributes on whitespace: `bigint unsigned` would read
  // as an attribute named `unsigned`.
  const definition = generateErDiagram([books]);
  assert.match(definition, /^ {4}int_unsigned price_cents$/m);
  assert.match(definition, /^ {4}enum status$/m);
});

test('the django label mode shortens the type and keeps it one token', () => {
  const definition = generateErDiagram([books], { typeLabels: 'django' });
  assert.match(definition, /^ {4}big_integer_field id PK$/m);
  assert.match(definition, /^ {4}char_field title$/m);
  assert.match(definition, /^ {4}integer_field price_cents$/m);
});

test('a type that sanitizes to nothing is not left blank', () => {
  const odd = { ...books, name: 'odd', columns: [{ name: 'x', type: '???', nullable: true, default: null }] };
  assert.match(generateErDiagram([odd]), /^ {4}unknown x$/m);
});

test('keys are derived from primary_key and foreign_keys, not stored on columns', () => {
  const definition = generateErDiagram([books, authors]);
  assert.match(definition, /^ {4}bigint id PK$/m);
  assert.match(definition, /^ {4}bigint author_id FK$/m);
});

test('an edge is drawn per foreign key, labelled with the constraint name', () => {
  const definition = generateErDiagram([books, authors]);
  assert.match(definition, /^ {2}authors \|\|--o\{ books : "books_author_id_fk"$/m);
});

test('an unnamed constraint falls back to its columns', () => {
  const unnamed = {
    ...books,
    foreign_keys: [{ ...books.foreign_keys[0], name: '' }],
  };
  assert.match(generateErDiagram([unnamed, authors]), /: "author_id"$/m);
});

test('no edge is drawn to a table the selection left out', () => {
  // Focus mode must not conjure a phantom entity for an out-of-scope table.
  const definition = generateErDiagram([books]);
  assert.doesNotMatch(definition, /authors/);
});

test('a self-reference is a column note, not a self-loop edge', () => {
  // Mermaid draws a self-loop as a large sweeping curve across the diagram.
  const definition = generateErDiagram([selfRef]);
  assert.match(definition, /^ {4}bigint parent_id FK "self-ref"$/m);
  assert.doesNotMatch(definition, /folders \|\|--o\{ folders/);
});

test('the accessible description counts tables and relationships', () => {
  assert.match(generateErDiagram([books, authors]), /accDescr: 2 tables, 1 relationship\./);
  assert.match(generateErDiagram([selfRef]), /accDescr: 1 table, no relationships\./);
  assert.match(generateErDiagram([]), /accDescr: 0 tables, no relationships\./);
});

test('the accessible description says what the view is scoped to', () => {
  const definition = generateErDiagram([books], { view: { filter: 'book', focus: 'books', depth: 2 } });
  assert.match(definition, /accDescr: 1 table, no relationships, filtered by "book", focused on books, depth 2\./);
});

test('user text reaches the description without breaking the directive', () => {
  // The filter is typed by a user: a quote would close the quoted value and a
  // newline would end the directive, corrupting the rest of the diagram.
  const definition = generateErDiagram([books], { view: { filter: 'a"b\nc  d' } });
  assert.match(definition, /accDescr: 1 table, no relationships, filtered by "ab c d"\./);
  assert.equal(lines(definition).filter((l) => l.includes('accDescr')).length, 1);
});

test('the whole schema renders with one edge per foreign key', () => {
  const definition = generateErDiagram(schema);
  // books -> authors, book_tags -> books, book_tags -> tags; folders refers to
  // itself, which is a note rather than an edge.
  assert.equal(lines(definition).filter((l) => l.includes('||--o{')).length, 3);
  for (const table of schema) {
    assert.match(definition, new RegExp(`^ {2}${table.name} \\{$`, 'm'));
  }
});
