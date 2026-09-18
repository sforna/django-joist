import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';

// The accessibility layer: the axe scan a browser is needed for, plus the
// keyboard operation a scan cannot see (WCAG 2.1.1). Contrast is deliberately
// not scanned - it is computed straight from the shipped token values in
// tests/js/palette-contrast.test.js, which also covers the light and dark
// palettes; axe cannot see through the diagram's SVG backgrounds anyway.

// The WCAG-tagged rules rather than every best-practice rule, as the reference
// does: `region` (landmark structure) is a design opinion, and enforcing it here
// would make the scan depend on how the dashboard is embedded. The landmark
// structure this dashboard promises is asserted in tests/js/a11y-css.test.js.
const WCAG = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'];

const scan = (page) =>
  new AxeBuilder({ page }).withTags(WCAG).disableRules(['color-contrast']).analyze();

const report = (violations) =>
  violations.map((v) => `${v.id} (${v.impact}) x${v.nodes.length}: ${v.help} -> ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`);

async function openDashboard(page) {
  await page.goto('/joist/');
  await expect(page.locator('#joist-canvas svg')).toBeVisible();
  // Scans need a settled DOM: the label-face gate redraws the diagram once if
  // the mono face arrives late, and axe walking the SVG mid-rebuild can report
  // the container it could not place rather than a real violation.
  await page.waitForLoadState('networkidle');
}

test('the dashboard has no detectable violations', async ({ page }) => {
  await openDashboard(page);
  const results = await scan(page);
  expect(report(results.violations)).toEqual([]);
});

test('the overlays have no detectable violations either', async ({ page }) => {
  await openDashboard(page);
  await page.locator('#joist-health-btn').click();
  await page.locator('#joist-diff-btn').click();
  await page.locator('#joist-legend-btn').click();
  await page.locator('#joist-export-btn').click();
  await expect(page.locator('#joist-popover')).toBeVisible();

  const results = await scan(page);
  expect(report(results.violations)).toEqual([]);
});

test('a table in the diagram is reachable and operable by keyboard', async ({ page }) => {
  await openDashboard(page);

  // The label is a tab stop: reachable but invisible when focused would be
  // worse than not reachable at all (WCAG 2.4.7).
  const label = page.locator('#joist-canvas svg .nodeLabel.joist-table-name').first();
  await label.focus();
  await expect(label).toBeFocused();
  const outline = await label.evaluate((el) => {
    const style = getComputedStyle(el);
    return `${style.outlineStyle} ${style.outlineWidth}`;
  });
  expect(outline).not.toMatch(/none/);
  expect(outline).not.toMatch(/0px/);

  await page.keyboard.press('Enter');
  await expect(page.locator('#joist-popover')).toBeVisible();

  await page.keyboard.press('Escape');
  await expect(page.locator('#joist-popover')).toBeHidden();
});

test('the focus picker reports its state to assistive technology', async ({ page }) => {
  await openDashboard(page);
  const input = page.locator('#joist-focus');
  await expect(input).toHaveAttribute('aria-expanded', 'false');

  await input.fill('testapp_book');
  await expect(input).toHaveAttribute('aria-expanded', 'true');
  await expect(input).toHaveAttribute('aria-controls', 'joist-focus-list');

  // The listbox is the accessible surface; the count is announced politely
  // rather than on every keystroke.
  await expect(page.locator('#joist-focus-status')).not.toBeEmpty();

  await page.keyboard.press('Escape');
  await expect(input).toHaveAttribute('aria-expanded', 'false');
});

test('the zoom slider has an accessible name', async ({ page }) => {
  await openDashboard(page);
  // A title attribute is a tooltip, not a name: assistive technology is not
  // required to expose it (WCAG 4.1.2).
  await expect(page.locator('#joist-zoom-range')).toHaveAttribute('aria-label', 'Zoom');
});
