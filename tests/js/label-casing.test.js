import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

// The toolbar and overlay labels read in sentence case, matching the docs and
// the source text ("Filter", "Focus", "Legend", "Fit", "Export view"), so none
// of them may force ALL CAPS. Capitalisation is a typographic choice here, but a
// forced uppercase transform also makes short labels harder to scan and strips
// the case distinction screen readers rely on for acronyms.

const css = readFileSync(
  fileURLToPath(new URL('../../src/django_joist/static/joist/css/joist.css', import.meta.url)),
  'utf8',
);

/** The declaration block for a selector, or '' when it has none. */
function rule(selector) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return css.match(new RegExp(`${escaped}\\s*\\{[^}]*\\}`))?.[0] ?? '';
}

const SENTENCE_CASE = [
  '.joist-field-label',
  '.joist-zoom button',
  '.joist-legend-head',
  '.joist-diff-head',
  '.joist-popover-head',
];

for (const selector of SENTENCE_CASE) {
  test(`${selector} does not force uppercase`, () => {
    const block = rule(selector);
    assert.notEqual(block, '', `${selector} has no rule to check`);
    assert.doesNotMatch(block, /text-transform\s*:\s*uppercase/);
  });
}

test('uppercase stays available where it is a tag, not a label', () => {
  // The heuristic badge is a marker rather than a label, and it is the only
  // place the transform survives: this keeps the test above from being a
  // blanket ban that someone relaxes by deleting the rule.
  assert.match(rule('.joist-health-heuristic'), /text-transform\s*:\s*uppercase/);
});
