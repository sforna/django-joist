import { expect, test } from '@playwright/test';

// The smoke layer: the app boots, the schema endpoint answers, Mermaid renders,
// and the footer counts what is on screen. Everything below this in the suite
// assumes at least this much.

test.beforeEach(async ({ page }) => {
  await page.goto('/joist/');
  await expect(page.locator('#joist-canvas svg')).toBeVisible();
});

test('the dashboard renders the schema as an SVG diagram', async ({ page }) => {
  await expect(page.locator('#joist-canvas svg .nodeLabel')).toContainText(['testapp_book']);
  // Mermaid's own accessibility output (WCAG 1.1.1): without it the SVG
  // announces itself as a graphics document with nothing to say.
  await expect(page.locator('#joist-canvas svg title')).toHaveText('Database structure diagram');
  await expect(page.locator('#joist-canvas svg desc')).toContainText('tables');
});

test('the footer counts the tables it is showing', async ({ page }) => {
  const tables = await page.locator('#joist-canvas svg g.node').count();
  await expect(page.locator('#joist-stat-tables')).toHaveText(new RegExp(`\\b${tables}\\b`));
  await expect(page.locator('#joist-stat-conn')).toContainText('default');
});

test('the fallback flag stays hidden when the live database answered', async ({ page }) => {
  await expect(page.locator('#joist-stat-fallback')).toBeHidden();
  await expect(page.locator('#joist-banners')).toBeEmpty();
});

/** The scale currently applied to the canvas, read off the real transform. */
const scaleOf = async (page) => {
  const transform = await page.locator('#joist-canvas').evaluate((el) => el.style.transform);
  return Number(/scale\(([\d.]+)\)/.exec(transform)?.[1]);
};

test('the zoom control drives the canvas transform', async ({ page }) => {
  // The dashboard auto-fits on load, floored at the readable minimum, so the
  // starting scale is the fit rather than 1.
  const fitted = await scaleOf(page);
  expect(fitted).toBeGreaterThan(0);

  await page.locator('#joist-zoom-range').fill('1.5');
  await expect(page.locator('#joist-zoom-pct')).toHaveText('150%');
  expect(await scaleOf(page)).toBeCloseTo(1.5, 2);

  await page.locator('button[data-fit]').click();
  await expect(page.locator('#joist-zoom-pct')).not.toHaveText('150%');
  // Fit is honest: it ignores the readable floor the auto-fit applies, so on a
  // large schema it lands below the scale the page opened with.
  expect(await scaleOf(page)).toBeLessThanOrEqual(fitted);
  await expect(page.locator('#joist-canvas svg')).toBeVisible();
});
