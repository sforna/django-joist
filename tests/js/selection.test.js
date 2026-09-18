import test from 'node:test';
import assert from 'node:assert/strict';

import {
  emptySelectionNotice,
  filterTables,
  focusTables,
  selectTables,
} from '../../src/django_joist/static/joist/js/selection.js';
import { schema, sortedNames } from './fixtures.js';

test('an empty or whitespace query keeps every table', () => {
  assert.equal(filterTables(schema, '').length, schema.length);
  assert.equal(filterTables(schema, '   ').length, schema.length);
  assert.equal(filterTables(schema, undefined).length, schema.length);
});

test('filtering is a case-insensitive substring match on the name', () => {
  assert.deepEqual(sortedNames(filterTables(schema, 'BOOK')), ['book_tags', 'books']);
  assert.deepEqual(sortedNames(filterTables(schema, 'oo')), ['book_tags', 'books']);
  assert.deepEqual(filterTables(schema, 'nothing-matches-this'), []);
});

test('filtering does not mutate or share the input array', () => {
  const copy = filterTables(schema, '');
  copy.pop();
  assert.equal(schema.length, 5);
});

test('the filter and the focus intersect rather than replace each other', () => {
  // Typing inside a focus searches within the neighbourhood. The reference
  // treated this as a bug report once: the two controls disagreed.
  assert.deepEqual(sortedNames(selectTables(schema, { focusRoot: 'books', depth: 1 })), [
    'authors',
    'book_tags',
    'books',
  ]);
  assert.deepEqual(sortedNames(selectTables(schema, { search: 'book' })), ['book_tags', 'books']);
  // Within the focus: `authors` is filtered out, `book_tags` survives.
  assert.deepEqual(
    sortedNames(selectTables(schema, { search: 'book', focusRoot: 'books', depth: 1 })),
    ['book_tags', 'books'],
  );
});

test('selections outside the focus narrow to nothing', () => {
  // `tags` matches the filter but not the root, so the neighbourhood has no
  // root to grow from: this is the empty diagram the notice explains.
  assert.deepEqual(selectTables(schema, { search: 'tag', focusRoot: 'books', depth: 1 }), []);
});

test('the focus neighbourhood is followed in both directions', () => {
  // books -> authors (its own foreign key) and books -> book_tags (a table that
  // references it). Only outbound edges would leave the join table out.
  assert.deepEqual(sortedNames(focusTables(schema, 'books', 1)), ['authors', 'book_tags', 'books']);
  assert.deepEqual(sortedNames(focusTables(schema, 'books', 2)), [
    'authors',
    'book_tags',
    'books',
    'tags',
  ]);
  assert.deepEqual(sortedNames(focusTables(schema, 'books', 0)), ['books']);
});

test('an unknown focus root shows nothing rather than everything', () => {
  assert.deepEqual(focusTables(schema, 'nope', 1), []);
});

test('a self-referencing table is its own neighbourhood and does not loop', () => {
  assert.deepEqual(sortedNames(focusTables(schema, 'folders', 3)), ['folders']);
});

test('the neighbourhood keeps the received order', () => {
  const names = focusTables(schema, 'books', 2).map((t) => t.name);
  assert.deepEqual(names, ['books', 'authors', 'tags', 'book_tags']);
});

test('no notice while tables are showing', () => {
  assert.equal(emptySelectionNotice(schema, {}), null);
  assert.equal(emptySelectionNotice(schema, { search: 'book' }), null);
  assert.equal(emptySelectionNotice(schema, { focusRoot: 'books', depth: 1 }), null);
});

test('the notice names the filter and the focus, and offers a way out', () => {
  assert.deepEqual(emptySelectionNotice(schema, { search: 'tags', focusRoot: 'books', depth: 1 }), {
    message: 'No tables match "tags" within focus: books.',
    clearFocus: true,
  });
});

test('a filter that matches nothing on its own does not blame the focus', () => {
  // Clearing the focus would leave the diagram just as empty, so it is not
  // offered: the advice has to be the one that works.
  assert.deepEqual(emptySelectionNotice(schema, { search: 'zzz', focusRoot: 'books', depth: 1 }), {
    message: 'No tables match "zzz".',
    clearFocus: false,
  });
  assert.deepEqual(emptySelectionNotice(schema, { search: 'zzz' }), {
    message: 'No tables match "zzz".',
    clearFocus: false,
  });
});

test('a focus that matches nothing on its own is named and clearable', () => {
  assert.deepEqual(emptySelectionNotice(schema, { focusRoot: 'nope', depth: 1 }), {
    message: 'No tables match focus: nope.',
    clearFocus: true,
  });
});

test('an empty search inside a broken focus still offers to clear it', () => {
  assert.deepEqual(emptySelectionNotice(schema, { search: '   ', focusRoot: 'nope' }), {
    message: 'No tables match focus: nope.',
    clearFocus: true,
  });
});

test('a schema with no tables at all explains itself without blaming a filter', () => {
  assert.deepEqual(emptySelectionNotice([], {}), {
    message: 'No tables match the current filter or focus.',
    clearFocus: false,
  });
});
