import { expect, test } from '@playwright/test';

// The toolbar controls, driven the way a person drives them. The pure logic
// behind each one is unit-tested in tests/js; what this layer proves is the
// wiring - that a control changes the diagram rather than only its own label.
//
// Names are the test project's own tables (testapp_book, testapp_booktag, ...),
// not the JS fixtures: this runs against the real schema.

// textContent, not innerText: SVG elements have no innerText, and Mermaid
// inlines its stylesheet into the SVG, so read the labels instead.
const diagram = async (page) =>
  (await page.locator('#joist-canvas svg .nodeLabel').allTextContents()).join(' ');
const nodes = (page) => page.locator('#joist-canvas svg g.node');

/** Focus a table through the picker, the way the keyboard does it. */
async function focusOn(page, table) {
  await page.fill('#joist-focus', table);
  await expect(page.locator('#joist-focus-list')).toContainText(table);
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('Enter');
  await expect(page.locator('#joist-focus')).toHaveValue(table);
}

test.beforeEach(async ({ page }) => {
  await page.goto('/joist/');
  await expect(page.locator('#joist-canvas svg')).toBeVisible();
});

test('the filter narrows the diagram and restores it', async ({ page }) => {
  const all = await nodes(page).count();

  // `testapp_book` is a substring of `testapp_booktag`, so two tables match.
  await page.fill('#joist-search', 'testapp_book');
  await expect(nodes(page)).toHaveCount(2);
  expect(await diagram(page)).toContain('testapp_book');
  expect(await diagram(page)).not.toContain('testapp_author');

  await page.fill('#joist-search', '');
  await expect(nodes(page)).toHaveCount(all);
});

test('a filter that matches nothing explains itself', async ({ page }) => {
  await page.fill('#joist-search', 'zzz-no-such-table');
  await expect(page.locator('#joist-banners')).toContainText('No tables match "zzz-no-such-table".');
  // The way out is not offered: clearing a focus would not bring anything back.
  await expect(page.locator('#joist-banners [data-clear-focus]')).toHaveCount(0);
});

test('the focus picker matches substrings and narrows to the neighbourhood', async ({ page }) => {
  await page.fill('#joist-focus', 'book');
  const list = page.locator('#joist-focus-list');
  await expect(list).toBeVisible();
  // A native select only jumps by prefix, so `book` would never reach
  // `testapp_booktag` there; the listbox is searched by substring instead.
  await expect(list).toContainText('testapp_booktag');

  await page.fill('#joist-focus', 'testapp_book');
  await page.keyboard.press('ArrowDown');
  // The ARIA combobox pattern: focus stays in the input and the highlighted
  // option is named by aria-activedescendant.
  const active = await page.locator('#joist-focus').getAttribute('aria-activedescendant');
  expect(active).toBeTruthy();
  await expect(page.locator(`#${active}`)).toHaveClass(/is-active/);
  await expect(page.locator(`#${active}`)).toHaveAttribute('role', 'option');
  await page.keyboard.press('Enter');

  await expect(page.locator('#joist-focus-list')).toBeHidden();
  // The neighbourhood: the table, both of its foreign-key parents, and the
  // join table that references it.
  await expect(nodes(page)).toHaveCount(4);
  const text = await diagram(page);
  expect(text).toContain('testapp_author');
  expect(text).toContain('testapp_publisher');
  expect(text).toContain('testapp_booktag');
  expect(text).not.toContain('testapp_label'); // two hops away
});

test('a filter inside a focus that matches nothing names both and offers the way out', async ({ page }) => {
  await focusOn(page, 'testapp_book');
  await page.fill('#joist-search', 'testapp_label');

  const banners = page.locator('#joist-banners');
  await expect(banners).toContainText(
    'No tables match "testapp_label" within focus: testapp_book.',
  );

  await banners.locator('[data-clear-focus]').click();
  await expect(page.locator('#joist-focus')).toHaveValue('');
  await expect(nodes(page)).toHaveCount(1);
  await expect(page.locator('#joist-canvas svg')).toContainText('testapp_label');
});

test('the depth control widens and narrows the neighbourhood', async ({ page }) => {
  await focusOn(page, 'testapp_book');

  await page.fill('#joist-depth', '0');
  await page.locator('#joist-depth').dispatchEvent('change');
  await expect(nodes(page)).toHaveCount(1);

  await page.fill('#joist-depth', '2');
  await page.locator('#joist-depth').dispatchEvent('change');
  expect(await nodes(page).count()).toBeGreaterThan(1);
});

test('the Django-types toggle relabels the diagram', async ({ page }) => {
  expect(await diagram(page)).toContain('varchar_255');

  await page.check('#joist-labels');
  await expect(page.locator('#joist-canvas svg')).toContainText('char_field');
  expect(await diagram(page)).not.toContain('varchar_255');
});

test('switching connection loads the other database', async ({ page }) => {
  // tests/browser/serve.py gives the secondary alias one table the default one
  // does not have, so this cannot pass by re-rendering the same payload.
  await page.selectOption('#joist-connection', 'secondary');

  await expect(page.locator('#joist-canvas svg')).toContainText('joist_secondary_only');
  await expect(page.locator('#joist-stat-conn')).toContainText('secondary');
  await expect(nodes(page)).toHaveCount(14);
});
