import test from 'node:test';
import assert from 'node:assert/strict';

import { toShortLabel } from '../../src/django_joist/static/joist/js/type-labels.js';

// A lossy, one-way presentation convenience: the native type stays the source of
// truth, and this only names the closest Django field family. It must never be
// written back into the schema.

test('integer widths map onto their Django families', () => {
  assert.equal(toShortLabel('bigint'), 'big integer field');
  assert.equal(toShortLabel('bigint unsigned'), 'big integer field');
  assert.equal(toShortLabel('int8'), 'big integer field');
  assert.equal(toShortLabel('smallint'), 'small integer field');
  assert.equal(toShortLabel('mediumint'), 'integer field');
  assert.equal(toShortLabel('integer'), 'integer field');
  assert.equal(toShortLabel('int unsigned'), 'integer field');
});

test('tinyint is a boolean only at width 1', () => {
  // The classic boolean storage is tinyint(1); a wider tinyint is a plain small
  // integer, and calling it a boolean would mislabel real data.
  assert.equal(toShortLabel('tinyint(1)'), 'boolean field');
  assert.equal(toShortLabel('tinyint( 1 )'), 'boolean field');
  assert.equal(toShortLabel('tinyint(4)'), 'small integer field');
  assert.equal(toShortLabel('tinyint'), 'small integer field');
});

test('character and text families', () => {
  assert.equal(toShortLabel('varchar(255)'), 'char field');
  assert.equal(toShortLabel('character varying(255)'), 'char field');
  assert.equal(toShortLabel('char(2)'), 'char field');
  assert.equal(toShortLabel('nvarchar(20)'), 'char field');
  assert.equal(toShortLabel('text'), 'text field');
  assert.equal(toShortLabel('longtext'), 'text field');
});

test('exact and floating point families', () => {
  assert.equal(toShortLabel('decimal(10,2)'), 'decimal field');
  assert.equal(toShortLabel('numeric(10,2)'), 'decimal field');
  assert.equal(toShortLabel('double precision'), 'float field');
  assert.equal(toShortLabel('float8'), 'float field');
  assert.equal(toShortLabel('real'), 'float field');
});

test('temporal, boolean, json, uuid and binary families', () => {
  assert.equal(toShortLabel('timestamp with time zone'), 'datetime field');
  assert.equal(toShortLabel('timestamptz'), 'datetime field');
  assert.equal(toShortLabel('datetime(6)'), 'datetime field');
  assert.equal(toShortLabel('date'), 'date field');
  assert.equal(toShortLabel('time'), 'time field');
  assert.equal(toShortLabel('bool'), 'boolean field');
  assert.equal(toShortLabel('boolean'), 'boolean field');
  assert.equal(toShortLabel('jsonb'), 'json field');
  assert.equal(toShortLabel('json'), 'json field');
  assert.equal(toShortLabel('uuid'), 'uuid field');
  assert.equal(toShortLabel('bytea'), 'binary field');
  assert.equal(toShortLabel('varbinary(16)'), 'binary field');
});

test('enum and set keep their keyword', () => {
  // The value list is shown in its own popover, so the label stays short.
  assert.equal(toShortLabel("enum('draft','published')"), 'enum');
  assert.equal(toShortLabel("set('a','b')"), 'set');
});

test('an unknown type is passed through rather than guessed', () => {
  assert.equal(toShortLabel('geometry'), 'geometry');
  assert.equal(toShortLabel('inet'), 'inet');
});

test('case, padding and vendor decoration do not matter', () => {
  assert.equal(toShortLabel('  BIGINT UNSIGNED  '), 'big integer field');
  assert.equal(toShortLabel('VARCHAR(255)'), 'char field');
  assert.equal(toShortLabel(''), '');
});
