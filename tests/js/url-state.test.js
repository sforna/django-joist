import test from 'node:test';
import assert from 'node:assert/strict';

import { buildQuery, parseQuery } from '../../src/django_joist/static/joist/js/url-state.js';

// A focused/filtered view is shareable through the URL, so these two functions
// have to round-trip exactly: a lossy one silently reopens a different diagram
// than the link promised.

test('an empty view serializes to nothing', () => {
  assert.equal(buildQuery(), '');
  assert.equal(buildQuery({}), '');
  assert.equal(buildQuery({ connection: '', filter: '', focus: '', depth: null, labels: false }), '');
});

test('only the fields that are set are serialized', () => {
  assert.equal(buildQuery({ focus: 'books' }), '?focus=books');
  assert.equal(buildQuery({ filter: 'book' }), '?filter=book');
  assert.equal(buildQuery({ connection: 'analytics' }), '?connection=analytics');
});

test('depth 0 is a depth, not an absent value', () => {
  // `depth != null` rather than a truthiness check: 0 is a real value here and
  // dropping it would show a neighbourhood the link did not ask for.
  assert.equal(buildQuery({ depth: 0 }), '?depth=0');
  assert.equal(buildQuery({ depth: 2 }), '?depth=2');
  assert.equal(buildQuery({ depth: null }), '');
});

test('the django label mode is the one that is written down', () => {
  assert.equal(buildQuery({ labels: true }), '?labels=django');
  assert.equal(buildQuery({ labels: false }), '');
});

test('a full view round-trips', () => {
  const view = { connection: 'analytics', filter: 'book', focus: 'books', depth: 3, labels: true };
  const query = buildQuery(view);
  assert.equal(query.includes('connection=analytics'), true);
  assert.equal(query.includes('focus=books'), true);
  assert.deepEqual(parseQuery(query), view);
});

test('parsing an empty or missing search string yields the defaults', () => {
  const empty = { connection: null, filter: '', focus: '', depth: null, labels: false };
  assert.deepEqual(parseQuery(), empty);
  assert.deepEqual(parseQuery(''), empty);
  assert.deepEqual(parseQuery('?'), empty);
});

test('an unparsable depth is dropped rather than passed on as NaN', () => {
  // Anything non-numeric came from a hand-edited URL: treating it as "no depth"
  // keeps the default neighbourhood instead of a NaN that reaches the query.
  assert.equal(parseQuery('?depth=abc').depth, null);
  assert.equal(parseQuery('?depth=').depth, null);
  assert.equal(parseQuery('?depth=2.5').depth, 2.5);
});

test('only the django label value turns the toggle on', () => {
  assert.equal(parseQuery('?labels=django').labels, true);
  assert.equal(parseQuery('?labels=laravel').labels, false);
  assert.equal(parseQuery('?labels=').labels, false);
});
