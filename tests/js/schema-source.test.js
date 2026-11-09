import test from 'node:test';
import assert from 'node:assert/strict';

import {
  EMBEDDED_PAYLOAD_SELECTOR,
  inlinePayload,
  readPayload,
} from '../../src/django_joist/static/joist/js/schema-source.js';

// The seam that lets the dashboard run on a payload it was handed rather than
// one it fetched: a host page renders `django_joist.payload()` with Django's
// json_script filter and the diagram never calls the endpoint.

/** A stand-in for the app container, so this stays a Node test. */
const container = (text) => ({
  querySelector: (selector) => (text !== null && selector === EMBEDDED_PAYLOAD_SELECTOR
    ? { textContent: text }
    : null),
});

test('reads every field of a full envelope', () => {
  const tables = [{ name: 'orders', columns: [] }];
  assert.deepEqual(readPayload({
    connection: 'default',
    tables,
    fallback: true,
    generated_at: '2026-11-09T10:00:00+00:00',
    diff: { tables_added: [{ name: 'orders' }] },
    doctor: { summary: { total: 1 } },
    cache_unavailable: true,
    diff_unavailable: true,
  }), {
    tables,
    fallback: true,
    generatedAt: '2026-11-09T10:00:00+00:00',
    diff: { tables_added: [{ name: 'orders' }] },
    doctor: { summary: { total: 1 } },
    cacheUnavailable: true,
    diffUnavailable: true,
  });
});

test('a bare or malformed envelope degrades to an empty, working state', () => {
  const empty = {
    tables: [],
    fallback: false,
    generatedAt: null,
    diff: null,
    doctor: null,
    cacheUnavailable: false,
    diffUnavailable: false,
  };
  assert.deepEqual(readPayload({ tables: [] }), empty);
  for (const junk of [null, undefined, 'tables', 42, [], { tables: 'nope' }]) {
    assert.deepEqual(readPayload(junk), empty, `for ${JSON.stringify(junk)}`);
  }
});

test('the unavailability flags must be strictly true', () => {
  const state = readPayload({ tables: [], cache_unavailable: 'true', diff_unavailable: 1 });
  assert.equal(state.cacheUnavailable, false);
  assert.equal(state.diffUnavailable, false);
});

test('a page with no embedded payload falls through to the fetch', () => {
  assert.equal(inlinePayload(container(null)), null);
  assert.equal(inlinePayload(null), null);
  assert.equal(inlinePayload(undefined), null);
});

test('the embedded payload is parsed as given, json_script escapes included', () => {
  // json_script writes <, > and & as \u003C, \u003E and \u0026, which JSON.parse
  // turns back into the characters: a default holding </script> survives intact.
  const embedded = '{"connection": "default", "tables": [{"name": "t", "columns": [{"name": "c", "default": "\\u003C/script\\u003E"}]}]}';
  const payload = inlinePayload(container(embedded));
  assert.equal(payload.connection, 'default');
  assert.equal(payload.tables[0].columns[0].default, '</script>');
});

test('an embedded payload that is not a JSON object fails loudly', () => {
  for (const bad of ['', '{not json', '[]', 'null', '"text"']) {
    assert.throws(() => inlinePayload(container(bad)), /could not be parsed as a JSON object/, `for ${bad}`);
  }
});

test('the selector is the one Django json_script produces for id "joist-payload"', () => {
  assert.equal(EMBEDDED_PAYLOAD_SELECTOR, 'script#joist-payload[type="application/json"]');
});
