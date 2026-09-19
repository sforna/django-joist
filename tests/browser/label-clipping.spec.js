import { readFileSync } from 'node:fs';
import { expect, test } from '@playwright/test';

// Issue #59: every label in the diagram lost its last character in Firefox on
// Windows, because Mermaid measured the label boxes in the fallback face and
// the webfont painted them ~9 percent wider (Consolas 0.55em against IBM Plex
// Mono 0.60em). The boxes carry no slack, so the overflow is clipped.
//
// Firefox runs this spec and not the rest of the suite (see playwright.config.js):
// the interaction specs would re-verify logic that is not engine-specific, at
// roughly double the lane's time, while label geometry is exactly what only a
// second engine can add.
//
// These assert the *ordering* and the *ratio*, not metrics. A metric assertion
// would be green on every machine we can run it on - macOS falls back to Menlo
// and Linux to DejaVu Sans Mono, both within a third of a percent of IBM Plex
// Mono - which is precisely why the suite never caught this.

const FACE = 'ibm-plex-mono-400.woff2'; // the weight the diagram labels paint in

/** Records when the diagram first appeared, and whether the face was usable then. */
const instrument = async (page) => {
  await page.addInitScript(() => {
    window.__faceAtFirstDraw = null;
    new MutationObserver((records) => {
      for (const record of records) {
        for (const node of record.addedNodes) {
          if (node.nodeType === 1 && node.tagName.toLowerCase() === 'svg'
            && node.parentElement?.id === 'joist-canvas') {
            // The invariant, sampled at the only moment it matters. Resource
            // Timing is the wrong instrument here: it says when bytes landed,
            // not whether the face was usable when the diagram was measured,
            // and the reference found it disagreeing with itself per engine.
            window.__faceAtFirstDraw ??= document.fonts.check('13px "IBM Plex Mono"');
          }
        }
      }
    }).observe(document, { childList: true, subtree: true });
  });
};

/**
 * Holds the face back by `ms`, so the race is deterministic.
 *
 * The bytes are served from here rather than passed through, and marked
 * no-store: a cached face is never re-requested, so the route would not fire,
 * the delay would not apply, and a spec whose whole premise is a slow font
 * would quietly test the fast path instead.
 */
const FACE_BYTES = readFileSync(`src/django_joist/static/joist/fonts/${FACE}`);
const delayFace = (page, ms) =>
  page.route(`**/${FACE}`, async (route) => {
    await new Promise((resolve) => setTimeout(resolve, ms));
    await route.fulfill({
      status: 200,
      headers: { 'content-type': 'font/woff2', 'cache-control': 'no-store' },
      body: FACE_BYTES,
    });
  });

test('waits for the label face before measuring the diagram', async ({ page }) => {
  await instrument(page);
  // Long enough that an ungated render is certain to draw before the face
  // lands, short enough that the gate (1500ms) still waits it out rather than
  // giving up and redrawing.
  await delayFace(page, 1000);
  await page.goto('/joist/');
  await page.locator('#joist-canvas svg').waitFor();

  // Ungated this is false, and for the most direct reason there is: nothing
  // asks for the 400 weight until the labels exist, so at the moment the
  // diagram is measured the face is not there to measure in.
  expect(
    await page.evaluate(() => window.__faceAtFirstDraw),
    'the diagram was measured before the label face was usable',
  ).toBe(true);
});

test('no label is clipped by its own box', async ({ page }) => {
  await page.goto('/joist/');
  await page.locator('#joist-canvas svg').waitFor();
  await page.evaluate(() => document.fonts.ready);

  // Painted ink against the box it was given, both in screen pixels so the
  // canvas zoom cancels. Anything above 1 is a clipped glyph.
  const worst = await page.evaluate(() => {
    const range = document.createRange();
    let max = 0;
    let label = '';
    for (const box of document.querySelectorAll('#joist-canvas svg foreignObject')) {
      // Only entity labels: an edge's own label is not measured into one of
      // these boxes, so including it would assert nothing about clipping.
      const el = box.querySelector('.nodeLabel');
      if (!el?.textContent.trim()) continue;
      range.selectNodeContents(el);
      const rect = box.getBoundingClientRect();
      if (!rect.width) continue;
      const ratio = range.getBoundingClientRect().width / rect.width;
      if (ratio > max) [max, label] = [ratio, el.textContent.trim()];
    }
    return { max, label };
  });

  expect(worst.max, `"${worst.label}" overflows its box`).toBeLessThanOrEqual(1.002);
});
