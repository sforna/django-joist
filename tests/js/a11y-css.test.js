import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

// WCAG 2.4.7 (Focus Visible). The three in-diagram triggers are given
// role="button" and tabindex="0" by joist.js, so they are reachable by Tab:
// without a visible indicator they are reachable and invisible, which is worse
// than not being reachable at all.

const css = readFileSync(
  fileURLToPath(new URL('../../src/django_joist/static/joist/css/joist.css', import.meta.url)),
  'utf8',
);

const TRIGGERS = ['joist-table-name', 'joist-enum-type', 'joist-health-marker'];

/** Every declaration block whose selector list mentions the pattern. */
function blocksMatching(pattern) {
  const escaped = pattern.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return [...css.matchAll(new RegExp(`[^{}]*${escaped}[^{}]*\\{[^}]*\\}`, 'g'))].map((m) => m[0]);
}

for (const trigger of TRIGGERS) {
  test(`.${trigger} has a focus indicator`, () => {
    const blocks = blocksMatching(`${trigger}:focus-visible`);
    assert.ok(blocks.length > 0, `no :focus-visible rule mentions .${trigger}`);
    assert.ok(
      blocks.some((block) => /outline\s*:/.test(block)),
      `.${trigger} is focused without a shape change`,
    );
  });
}

test('every focus style draws an outline rather than only recolouring', () => {
  // A rule that only changes colour is not an indicator for someone who cannot
  // distinguish the two colours.
  const blocks = blocksMatching(':focus-visible');
  assert.ok(blocks.length >= 3);
  for (const block of blocks) {
    const selector = block.slice(0, block.indexOf('{')).trim();
    // The menu items recolour *and* the shared rule outlines; recolouring alone
    // is only acceptable where the outline comes from the trigger's own rule.
    if (!/joist-(table-name|enum-type|health-marker)/.test(selector)) continue;
    assert.match(block, /outline\s*:/, selector);
  }
});

test('the canvas keeps its pointer affordance on the clickable labels', () => {
  // Focusable without a pointer cursor reads as a plain label that happens to
  // swallow clicks.
  const blocks = blocksMatching('.joist-table-name');
  assert.ok(blocks.some((block) => /cursor\s*:\s*pointer/.test(block)));
});
