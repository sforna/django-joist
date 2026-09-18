import test from 'node:test';
import assert from 'node:assert/strict';

import {
  MAX_RASTER_PIXELS,
  pngAvailability,
  rasterScale,
  serverExportsAvailable,
} from '../../src/django_joist/static/joist/js/export-menu.js';

// Both rules here replace a silent failure: a format that throws inside a
// promise (no file, no error, nothing) and a PNG past the canvas ceiling that
// comes back blank because toBlob yields null.

test('the server-backed formats need a route to call', () => {
  assert.equal(serverExportsAvailable('/joist/export/__format__/'), true);
  assert.equal(serverExportsAvailable(''), false);
  assert.equal(serverExportsAvailable('   '), false);
  assert.equal(serverExportsAvailable(null), false);
  assert.equal(serverExportsAvailable(undefined), false);
});

test('a diagram that fits is rasterised at the preferred 2x', () => {
  assert.equal(rasterScale(2000, 1500), 2);
  assert.equal(pngAvailability(2000, 1500).available, true);
  assert.equal(pngAvailability(2000, 1500).scale, 2);
  assert.equal(pngAvailability(2000, 1500).reason, null);
});

test('the scale drops to what fits, and never below 1', () => {
  // 8000x8000 is 64MP at 1x, inside the ceiling, but 2x would be 256MP: the
  // scale comes down to exactly what fits instead of being refused.
  const scale = rasterScale(8000, 8000);
  assert.equal(scale, 1.25);
  assert.ok(8000 * 8000 * scale * scale <= MAX_RASTER_PIXELS);

  // Just under the ceiling the computed scale rounds down to 1 rather than
  // slipping a fraction of a percent above the budget.
  assert.equal(rasterScale(9999, 9999), 1);
});

test('a diagram too large for any whole-pixel export is withheld', () => {
  // Downscaling is not a rescue: it throws away the pixels that make the labels
  // readable, which is the only reason to want a PNG.
  const tooBig = Math.ceil(Math.sqrt(MAX_RASTER_PIXELS)) + 1;
  assert.equal(rasterScale(tooBig, tooBig), null);

  const verdict = pngAvailability(tooBig, tooBig);
  assert.equal(verdict.available, false);
  assert.equal(verdict.scale, null);
  assert.match(verdict.reason, /too large to save as a PNG/);
  assert.match(verdict.reason, /SVG/); // and what to do instead
});

test('an empty or unmeasured diagram is not explained as a size problem', () => {
  // Nothing drawn (a schema that failed to load, a filter that matches nothing)
  // must not be reported as "too large".
  for (const [width, height] of [[0, 0], [0, 500], [500, 0], [Number.NaN, 500]]) {
    const verdict = pngAvailability(width, height);
    assert.deepEqual(verdict, { available: false, scale: null, reason: null }, `${width}x${height}`);
    assert.equal(rasterScale(width, height), null);
  }
});

test('the ceiling leaves the common sizes untouched', () => {
  // A 33-table schema measured at 98MP at 2x in the reference; it still exports.
  const wide = Math.sqrt(98_000_000 / 4);
  assert.equal(rasterScale(wide, wide), 2);
});
