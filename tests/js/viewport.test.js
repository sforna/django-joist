import test from 'node:test';
import assert from 'node:assert/strict';

import { ZOOM_LIMITS, clamp, fitTransform, zoomAtPoint } from '../../src/django_joist/static/joist/js/viewport.js';

const content = { width: 1000, height: 500 };
const viewport = { width: 500, height: 500 };

test('clamp is inclusive on both bounds', () => {
  assert.equal(clamp(5, 0, 10), 5);
  assert.equal(clamp(-1, 0, 10), 0);
  assert.equal(clamp(11, 0, 10), 10);
});

test('fit centers the content', () => {
  const view = fitTransform(content, viewport);
  // The width is the binding axis at 0.95 padding: 500 / 1000 * 0.95.
  assert.equal(view.zoom, 0.475);
  assert.equal(view.x, (500 - 1000 * view.zoom) / 2);
  assert.equal(view.y, (500 - 500 * view.zoom) / 2);
});

test('fit never upscales past the natural size', () => {
  const view = fitTransform({ width: 100, height: 100 }, viewport);
  assert.equal(view.zoom, 1);
  assert.equal(view.x, 200);
  assert.equal(view.y, 200);
});

test('a readable floor wins over fitting the whole schema', () => {
  // A huge diagram fitted honestly is an illegible speck: the auto-fit stops at
  // min_zoom and the overflow is panned instead.
  const view = fitTransform({ width: 100_000, height: 100_000 }, viewport, { minScale: 0.7 });
  assert.equal(view.zoom, 0.7);
  assert.equal(view.x, (500 - 100_000 * 0.7) / 2);
});

test('fit refuses to zoom in past the overall maximum', () => {
  const view = fitTransform({ width: 10, height: 10 }, viewport, { maxScale: 99 });
  assert.equal(view.zoom, ZOOM_LIMITS.max);
});

test('a degenerate size yields the identity transform instead of NaN', () => {
  const identity = { zoom: 1, x: 0, y: 0 };
  assert.deepEqual(fitTransform({ width: 0, height: 10 }, viewport), identity);
  assert.deepEqual(fitTransform(content, { width: 0, height: 0 }), identity);
});

test('zoomAtPoint keeps the point under the cursor pinned', () => {
  const view = { zoom: 1, x: 0, y: 0 };
  const point = { x: 200, y: 100 };
  const zoomed = zoomAtPoint(view, point, 2);

  assert.equal(zoomed.zoom, 2);
  // The content coordinate under the cursor before and after must be the same:
  // (point - x) / zoom.
  assert.equal((point.x - view.x) / view.zoom, (point.x - zoomed.x) / zoomed.zoom);
  assert.equal((point.y - view.y) / view.zoom, (point.y - zoomed.y) / zoomed.zoom);
});

test('zoomAtPoint stops at the limits and keeps zooming around the point', () => {
  const atMax = zoomAtPoint({ zoom: ZOOM_LIMITS.max, x: 0, y: 0 }, { x: 10, y: 10 }, 2);
  assert.equal(atMax.zoom, ZOOM_LIMITS.max);

  const atMin = zoomAtPoint({ zoom: ZOOM_LIMITS.min, x: 0, y: 0 }, { x: 10, y: 10 }, 0.5);
  assert.equal(atMin.zoom, ZOOM_LIMITS.min);
});

test('zooming out then in around the same point returns to where it started', () => {
  const start = { zoom: 1, x: 40, y: 25 };
  const point = { x: 300, y: 200 };
  const out = zoomAtPoint(start, point, 0.5);
  const back = zoomAtPoint(out, point, 2);

  assert.equal(Math.round(back.zoom * 1000) / 1000, start.zoom);
  assert.equal(Math.round(back.x), start.x);
  assert.equal(Math.round(back.y), start.y);
});
