import { expect, test } from '@playwright/test';

// The two overlay panels and the popover. Both panels are rendered from a payload
// the server has already computed (the diff against the recorded baseline, and
// the doctor findings), so what is checked here is that the payload reaches the
// panel and the diagram in a usable shape.

test.beforeEach(async ({ page }) => {
  await page.goto('/joist/');
  await expect(page.locator('#joist-canvas svg')).toBeVisible();
});

test('the changes panel lists what moved since the last migration', async ({ page }) => {
  // tests/browser/serve.py seeds a baseline with one table missing.
  const button = page.locator('#joist-diff-btn');
  await expect(button).toBeVisible();
  await button.click();

  const panel = page.locator('#joist-diff-panel');
  await expect(panel).toBeVisible();
  await expect(panel).toContainText('Changes since last migration');
  await expect(panel.locator('.joist-diff-item')).toContainText('testapp_tag');

  // And the diagram marks the table the panel is talking about.
  await expect(page.locator('#joist-canvas svg g.node.joist-diff-added')).toHaveCount(1);

  await button.click();
  await expect(panel).toBeHidden();
});

test('the health panel carries the doctor findings, with the node marked', async ({ page }) => {
  const button = page.locator('#joist-health-btn');
  await expect(button).toBeVisible();
  await expect(page.locator('#joist-health-count')).not.toBeEmpty();

  await button.click();
  const panel = page.locator('#joist-health-panel');
  await expect(panel).toBeVisible();

  // The PK-less table and the unindexed foreign key come from the raw-DDL
  // fixtures, so these are findings over a real database rather than a mock. The
  // default preset is `recommended`, which leaves the heuristic rules out: the
  // float-as-money finding is asserted in the Python doctor tests instead.
  await expect(panel).toContainText('testapp_nopk');
  await expect(panel).toContainText('JOIST-INT-001');
  await expect(panel).toContainText('testapp_fkaction');
  await expect(panel).toContainText('JOIST-IDX-001');
  await expect(panel.locator('.joist-health-code').first()).toHaveText(/^JOIST-/);

  // The offending column is marked on the diagram, not only listed in the panel.
  await expect(page.locator('#joist-canvas svg .joist-health-marker')).not.toHaveCount(0);
  const marked = '#joist-canvas svg g.node.joist-health-error, #joist-canvas svg g.node.joist-health-warning';
  await expect(page.locator(marked)).not.toHaveCount(0);

  // Maximize is a toggle, and it reports its state.
  const max = page.locator('#joist-health-max-btn');
  await expect(max).toHaveAttribute('aria-pressed', 'false');
  await max.click();
  await expect(max).toHaveAttribute('aria-pressed', 'true');
  await expect(panel).toHaveClass(/is-maximized/);

  await button.click();
  await expect(panel).toBeHidden();
});

test('clicking a table opens its action menu, and Escape closes it', async ({ page }) => {
  // dispatchEvent rather than click(): Mermaid replaces the label elements when
  // the font arrives late (the redraw after the face gate), so an actionability
  // check can spend its time chasing a node that no longer exists.
  const label = page.locator('#joist-canvas svg .nodeLabel.joist-table-name', { hasText: 'testapp_book' }).first();
  await label.dispatchEvent('click');

  const popover = page.locator('#joist-popover');
  await expect(popover).toBeVisible();
  await expect(popover).toContainText('testapp_book');
  // The dialog is named after the table it is about, not left generic.
  await expect(popover).toHaveAttribute('aria-label', 'testapp_book');
  await expect(popover).toContainText('Focus this table');

  // The action is offered because the server route exists: without it the
  // download items would be disabled instead of failing silently.
  await expect(popover.locator('[data-act="json"]')).toBeEnabled();

  // Focusing from here narrows the diagram, and the item inverts so it cannot
  // be a no-op the second time.
  await popover.locator('[data-act="focus"]').click();
  await expect(page.locator('#joist-canvas svg g.node')).toHaveCount(4);

  await label.dispatchEvent('click');
  await expect(popover).toContainText('Unfocus this table');

  await page.keyboard.press('Escape');
  await expect(popover).toBeHidden();
});

test('the legend explains the diagram vocabulary', async ({ page }) => {
  const legend = page.locator('#joist-legend');
  await expect(legend).toBeHidden();

  await page.locator('#joist-legend-btn').click();
  await expect(legend).toBeVisible();
  await expect(legend).toContainText('Primary key');
  await expect(legend).toContainText('Foreign key');
});
