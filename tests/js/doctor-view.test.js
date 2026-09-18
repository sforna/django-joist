import test from 'node:test';
import assert from 'node:assert/strict';

import {
  columnMarkers,
  doctorSummary,
  findingGroups,
  hasDoctor,
  tableBadges,
  tableSeverity,
  worstSeverity,
} from '../../src/django_joist/static/joist/js/doctor-view.js';

// The API `doctor` field is already computed server-side; these helpers only
// turn findings into render models. Absent or empty payloads are the normal case
// on a healthy schema, so every helper has to survive them.

const doctor = {
  summary: { error: 1, warning: 2, info: 1, total: 4 },
  findings: [
    { code: 'JOIST-INT-001', severity: 'error', table: 'logs', column: null },
    { code: 'JOIST-TYP-001', severity: 'warning', table: 'money', column: 'balance' },
    { code: 'JOIST-TYP-002', severity: 'info', table: 'money', column: 'total' },
    { code: 'JOIST-IDX-001', severity: 'warning', table: 'money', column: null },
  ],
};

test('a doctor payload is present only when it reports findings', () => {
  assert.equal(hasDoctor(doctor), true);
  assert.equal(hasDoctor({ summary: { total: 0 }, findings: [] }), false);
  assert.equal(hasDoctor(null), false);
  assert.equal(hasDoctor(undefined), false);
});

test('the summary counts each severity and totals them', () => {
  assert.deepEqual(doctorSummary(doctor), { error: 1, warning: 2, info: 1, total: 4 });
});

test('an absent summary is zeroes, and a partial one is completed', () => {
  assert.deepEqual(doctorSummary(null), { error: 0, warning: 0, info: 0, total: 0 });
  assert.deepEqual(doctorSummary({ summary: { warning: 2 } }), { error: 0, warning: 2, info: 0, total: 2 });
});

test('the worst severity wins regardless of the order findings arrive in', () => {
  assert.equal(worstSeverity(doctor), 'error');
  assert.equal(worstSeverity({ findings: [{ severity: 'info' }, { severity: 'warning' }] }), 'warning');
  assert.equal(worstSeverity({ findings: [] }), null);
  assert.equal(worstSeverity(null), null);
});

test('table badges count findings and keep the worst severity per table', () => {
  const badges = tableBadges(doctor);
  assert.deepEqual(badges.get('logs'), { severity: 'error', count: 1 });
  assert.deepEqual(badges.get('money'), { severity: 'warning', count: 3 });
  assert.equal(badges.has('authors'), false);
});

test('a single table severity defaults to none', () => {
  assert.equal(tableSeverity(doctor, 'logs'), 'error');
  assert.equal(tableSeverity(doctor, 'authors'), 'none');
  assert.equal(tableSeverity(null, 'logs'), 'none');
});

test('column markers key only real columns of that table', () => {
  const markers = columnMarkers(doctor, 'money', ['id', 'balance', 'total']);
  assert.deepEqual([...markers.keys()].sort(), ['balance', 'total']);
  assert.equal(markers.get('balance').severity, 'warning');
  assert.equal(markers.get('balance').findings.length, 1);
});

test('a finding whose column is not a column of the table is left to the node badge', () => {
  // Index and constraint findings carry that name in `column`, and table-level
  // findings carry none: neither has a row on the diagram to mark.
  const markers = columnMarkers(doctor, 'money', ['id', 'balance']);
  assert.equal(markers.has('total'), false); // not among this table's columns
  assert.equal(markers.has(null), false);
  assert.equal(columnMarkers(doctor, 'logs', ['id']).size, 0); // its only finding is table-level
});

test('markers group several findings on one column and keep the worst', () => {
  const two = {
    findings: [
      { severity: 'info', table: 'money', column: 'total' },
      { severity: 'error', table: 'money', column: 'total' },
    ],
  };
  const marker = columnMarkers(two, 'money', ['total']).get('total');
  assert.equal(marker.findings.length, 2);
  assert.equal(marker.severity, 'error');
});

test('the panel groups findings per table, in first-appearance order', () => {
  const groups = findingGroups(doctor);
  assert.deepEqual(groups.map((g) => g.table), ['logs', 'money']);
  assert.deepEqual(groups.map((g) => g.severity), ['error', 'warning']);
  assert.equal(groups[1].findings.length, 3);
  // The payload arrives sorted, and the panel keeps that order inside a group.
  assert.deepEqual(groups[1].findings.map((f) => f.code), ['JOIST-TYP-001', 'JOIST-TYP-002', 'JOIST-IDX-001']);
});

test('the worst severity of a group is independent of which finding opened it', () => {
  const groups = findingGroups({
    findings: [
      { severity: 'info', table: 'a' },
      { severity: 'error', table: 'a' },
    ],
  });
  assert.equal(groups[0].severity, 'error');
});

test('an absent doctor payload renders as nothing at all', () => {
  assert.deepEqual(findingGroups(null), []);
  assert.deepEqual([...tableBadges(null).keys()], []);
  assert.equal(columnMarkers(null, 'money', ['balance']).size, 0);
});
