import test from 'node:test';
import assert from 'node:assert/strict';

import {
  changeList,
  columnBadges,
  diffSummary,
  hasDiff,
  tableStatus,
  tableStatuses,
} from '../../src/django_joist/static/joist/js/diff-view.js';

// The API `diff` field is already computed server-side; these helpers only turn
// it into render models. Every one of them has to survive an absent diff: the
// dashboard asks before the diff feature is even enabled.

const diff = {
  has_changes: true,
  tables_added: [{ name: 'fresh' }],
  tables_removed: [{ name: 'gone' }],
  tables_changed: [
    {
      name: 'books',
      columns_added: [{ name: 'subtitle', type: 'varchar(255)' }],
      columns_removed: [{ name: 'legacy' }],
      columns_changed: [{ name: 'title', changes: { type: { before: 'varchar(100)', after: 'varchar(255)' } } }],
      indexes_added: [{ name: 'idx_new' }],
      indexes_removed: [{ name: 'idx_old' }],
      indexes_changed: [{ name: 'idx_same' }],
      foreign_keys_added: [{ name: 'fk_new' }],
      foreign_keys_removed: [{ name: 'fk_old' }],
      foreign_keys_changed: [{ name: 'fk_same' }],
      changes: { primary_key: { before: ['id'], after: ['id', 'title'] } },
    },
  ],
};

const unchanged = { has_changes: false, tables_added: [], tables_removed: [], tables_changed: [] };

test('a diff is present only when it reports changes', () => {
  assert.equal(hasDiff(diff), true);
  assert.equal(hasDiff(unchanged), false);
  assert.equal(hasDiff(null), false);
  assert.equal(hasDiff(undefined), false);
});

test('the summary counts each kind and totals them', () => {
  assert.deepEqual(diffSummary(diff), { added: 1, removed: 1, changed: 1, total: 3 });
});

test('an absent diff summarizes as zeroes rather than throwing', () => {
  assert.deepEqual(diffSummary(null), { added: 0, removed: 0, changed: 0, total: 0 });
  assert.deepEqual(diffSummary(unchanged), { added: 0, removed: 0, changed: 0, total: 0 });
});

test('table statuses map the three kinds and omit everything else', () => {
  const statuses = tableStatuses(diff);
  assert.equal(statuses.get('fresh'), 'added');
  assert.equal(statuses.get('gone'), 'removed');
  assert.equal(statuses.get('books'), 'changed');
  assert.equal(statuses.has('authors'), false);
});

test('a single status defaults to unchanged', () => {
  assert.equal(tableStatus(diff, 'books'), 'changed');
  assert.equal(tableStatus(diff, 'authors'), 'unchanged');
  assert.equal(tableStatus(null, 'books'), 'unchanged');
});

test('column badges cover only the named table', () => {
  const badges = columnBadges(diff, 'books');
  assert.equal(badges.get('subtitle'), 'added');
  assert.equal(badges.get('legacy'), 'removed');
  assert.equal(badges.get('title'), 'changed');
  assert.deepEqual([...columnBadges(diff, 'authors').keys()], []);
});

test('the change list is ordered added tables, removed tables, changed tables', () => {
  assert.deepEqual(changeList(diff).map((item) => `${item.kind}:${item.table}`), [
    'table-added:fresh',
    'table-removed:gone',
    'table-changed:books',
  ]);
});

test('the changed table carries its details in a stable order', () => {
  const details = changeList(diff).find((item) => item.table === 'books').details;
  assert.deepEqual(details.map((d) => d.kind), [
    'column-added',
    'column-removed',
    'column-changed',
    'index-added',
    'index-removed',
    'index-changed',
    'fk-added',
    'fk-removed',
    'fk-changed',
    'primary-key-changed',
  ]);
  assert.deepEqual(details.find((d) => d.kind === 'column-changed').changes, {
    type: { before: 'varchar(100)', after: 'varchar(255)' },
  });
  assert.deepEqual(details.at(-1), {
    kind: 'primary-key-changed',
    before: ['id'],
    after: ['id', 'title'],
  });
});

test('a missing diff is an empty list, not a broken panel', () => {
  assert.deepEqual(changeList(null), []);
  assert.deepEqual(changeList(unchanged), []);
});
