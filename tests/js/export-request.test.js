import test from 'node:test';
import assert from 'node:assert/strict';

import { buildExportUrl } from '../../src/django_joist/static/joist/js/export-request.js';

// The structural formats are generated server-side, so the browser's only job is
// to ask the right question: the same pipeline as the CLI answers, which is what
// makes a download byte-identical to `manage.py joist_export`.

const TEMPLATE = '/joist/export/__format__/';

test('the format replaces the placeholder in the template', () => {
  assert.equal(buildExportUrl(TEMPLATE, 'dbml'), '/joist/export/dbml/');
  assert.equal(buildExportUrl(TEMPLATE, 'mermaid'), '/joist/export/mermaid/');
});

test('no route means no URL, rather than a broken one', () => {
  // A dashboard served without the export route (a static demo, or the route
  // turned off) has to be able to say so; throwing left the menu item doing
  // nothing at all, with no error and no file.
  assert.equal(buildExportUrl(undefined, 'dbml'), null);
  assert.equal(buildExportUrl(null, 'dbml'), null);
  assert.equal(buildExportUrl('', 'dbml'), null);
  assert.equal(buildExportUrl('   ', 'dbml'), null);
});

test('nothing selected means no query string', () => {
  assert.equal(buildExportUrl(TEMPLATE, 'json'), '/joist/export/json/');
  assert.equal(buildExportUrl(TEMPLATE, 'json', { only: [], except: [], compact: false }), '/joist/export/json/');
});

test('only and except travel as comma-separated lists', () => {
  const url = buildExportUrl(TEMPLATE, 'dbml', { only: ['books', 'authors'] });
  // The comma is left literal for readability; the server decodes it before
  // splitting, so the round-trip is still exact.
  assert.equal(url, '/joist/export/dbml/?only=books,authors');
  assert.equal(buildExportUrl(TEMPLATE, 'dbml', { except: ['logs'] }), '/joist/export/dbml/?except=logs');
});

test('depth only means something next to a focus', () => {
  assert.equal(buildExportUrl(TEMPLATE, 'dbml', { focus: 'books' }), '/joist/export/dbml/?focus=books');
  assert.equal(
    buildExportUrl(TEMPLATE, 'dbml', { focus: 'books', depth: 2 }),
    '/joist/export/dbml/?focus=books&depth=2',
  );
  assert.equal(buildExportUrl(TEMPLATE, 'dbml', { depth: 2 }), '/joist/export/dbml/');
});

test('focus depth 0 is sent rather than dropped', () => {
  assert.equal(
    buildExportUrl(TEMPLATE, 'dbml', { focus: 'books', depth: 0 }),
    '/joist/export/dbml/?focus=books&depth=0',
  );
});

test('compact and connection are passed through when set', () => {
  assert.equal(buildExportUrl(TEMPLATE, 'llm', { compact: true }), '/joist/export/llm/?compact=1');
  assert.equal(
    buildExportUrl(TEMPLATE, 'llm', { connection: 'analytics' }),
    '/joist/export/llm/?connection=analytics',
  );
});

test('a narrowed export carries every part of the selection', () => {
  const url = buildExportUrl(TEMPLATE, 'markdown', {
    only: ['books'],
    focus: 'books',
    depth: 1,
    compact: true,
    connection: 'secondary',
  });
  assert.equal(
    url,
    '/joist/export/markdown/?only=books&focus=books&depth=1&compact=1&connection=secondary',
  );
});
