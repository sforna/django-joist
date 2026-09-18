import test from 'node:test';
import assert from 'node:assert/strict';

import { matchTables } from '../../src/django_joist/static/joist/js/table-match.js';

// The Focus picker matches substrings, exactly like the toolbar filter: a native
// <select> only jumps by prefix, so `item` never reached `order_items` and the
// two controls contradicted each other. Deliberately not fuzzy.

test('an empty query lists every table without a span to highlight', () => {
  assert.deepEqual(matchTables(['books', 'tags'], ''), [
    { name: 'books', start: -1, end: -1 },
    { name: 'tags', start: -1, end: -1 },
  ]);
  assert.deepEqual(matchTables(['books'], '   '), [{ name: 'books', start: -1, end: -1 }]);
});

test('matching is substring, case-insensitive, and reports the span', () => {
  assert.deepEqual(matchTables(['order_items'], 'item'), [{ name: 'order_items', start: 6, end: 10 }]);
  assert.deepEqual(matchTables(['OrderItems'], 'orders'), []);
  assert.deepEqual(matchTables(['order_items'], 'ORDER'), [{ name: 'order_items', start: 0, end: 5 }]);
});

test('the query is literal text, not a pattern', () => {
  // indexOf, not a regular expression: a dot a user typed has to mean a dot.
  assert.deepEqual(matchTables(['a.b'], 'a.b'), [{ name: 'a.b', start: 0, end: 3 }]);
  assert.deepEqual(matchTables(['axb'], 'a.b'), []);
});

test('exact matches come first, then prefixes, then matches further in', () => {
  // Input order is fixed, so only the rank can move a name: the exact hit
  // leads, the two prefixes follow in the order they arrived, and the match
  // from further inside the name comes last.
  const names = matchTables(['order_items', 'items', 'item', 'item_notes'], 'item').map((m) => m.name);
  assert.deepEqual(names, ['item', 'items', 'item_notes', 'order_items']);
});

test('equal ranks keep the order they arrived in', () => {
  const names = matchTables(['b_items', 'a_items'], 'item').map((m) => m.name);
  assert.deepEqual(names, ['b_items', 'a_items']);
});

test('table objects are accepted as well as bare names', () => {
  const tables = [{ name: 'books' }, { name: 'tags' }];
  assert.deepEqual(matchTables(tables, 'tag'), [{ name: 'tags', start: 0, end: 3 }]);
});

test('a table with no match is left out entirely', () => {
  assert.deepEqual(matchTables(['books', 'tags'], 'book').map((m) => m.name), ['books']);
  assert.deepEqual(matchTables(['books'], 'nope'), []);
});
