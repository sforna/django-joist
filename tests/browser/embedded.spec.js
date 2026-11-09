import { expect, test } from '@playwright/test';

// The dashboard on a payload embedded in the page, the way a host page renders
// `{{ payload|json_script:"joist-payload" }}` inside the app container. The
// real page is served and only the embedded block is added, so the markup,
// assets and loader are the shipped ones; the schema endpoint is made to fail,
// so a diagram can only come from the embedded payload.

/** The page as served, with `payload` embedded the way json_script writes it. */
async function embed(page, payload) {
  const endpointCalls = [];
  await page.route('**/joist/api/schema**', (route) => {
    endpointCalls.push(route.request().url());
    return route.fulfill({ status: 500, body: 'the endpoint must not be called' });
  });
  await page.route('**/joist/', async (route) => {
    const response = await route.fetch();
    const html = await response.text();
    // json_script's escaping, so the test embeds what Django would write.
    const json = JSON.stringify(payload)
      .replace(/</g, '\\u003C').replace(/>/g, '\\u003E').replace(/&/g, '\\u0026');
    const block = `<script id="joist-payload" type="application/json">${json}</script>`;
    const marker = /(<div\s+id="joist-app"[^>]*>)/;
    expect(marker.test(html)).toBe(true);
    await route.fulfill({ response, body: html.replace(marker, `$1${block}`) });
  });
  return endpointCalls;
}

/** A real payload from the endpoint, so the embedded shape is the served one. */
async function servedPayload(request) {
  const response = await request.get('/joist/api/schema');
  expect(response.ok()).toBe(true);
  return response.json();
}

test('renders an embedded payload without calling the schema endpoint', async ({ page, request }) => {
  const payload = await servedPayload(request);
  // A table only this payload has, with a default json_script has to escape:
  // the diagram can only draw it by reading the embedded block intact.
  payload.tables.push({
    name: 'embedded_only',
    columns: [{ name: 'note', type: 'varchar(20)', nullable: true, default: '</script>&' }],
    primary_key: [],
    indexes: [],
    foreign_keys: [],
  });
  const calls = await embed(page, payload);

  await page.goto('/joist/');
  const labels = page.locator('#joist-canvas svg .nodeLabel');
  await expect(labels.filter({ hasText: /^embedded_only$/ })).toHaveCount(1);
  await expect(labels.filter({ hasText: /^testapp_book$/ })).toHaveCount(1);
  await expect(page.locator('#joist-stat-conn')).toContainText('default');
  await expect(page.locator('#joist-banners')).toBeEmpty();
  expect(calls).toEqual([]);
});

test('the filter still narrows an embedded payload', async ({ page, request }) => {
  await embed(page, await servedPayload(request));
  await page.goto('/joist/');
  await expect(page.locator('#joist-canvas svg')).toBeVisible();

  await page.locator('#joist-search').fill('testapp_book');
  await expect(page.locator('#joist-canvas svg .nodeLabel')).toContainText(['testapp_book']);
  const shown = await page.locator('#joist-canvas svg g.node').count();
  expect(shown).toBeGreaterThan(0);
  await expect(page.locator('#joist-canvas svg .nodeLabel', { hasText: 'testapp_label' })).toHaveCount(0);
});

test('a malformed embedded payload is reported, not silently fetched', async ({ page }) => {
  const calls = [];
  await page.route('**/joist/api/schema**', (route) => {
    calls.push(route.request().url());
    return route.fulfill({ status: 500, body: '' });
  });
  await page.route('**/joist/', async (route) => {
    const response = await route.fetch();
    const html = (await response.text()).replace(
      /(<div\s+id="joist-app"[^>]*>)/,
      '$1<script id="joist-payload" type="application/json">{not json</script>',
    );
    await route.fulfill({ response, body: html });
  });

  await page.goto('/joist/');
  await expect(page.locator('#joist-banners')).toContainText('could not be parsed as a JSON object');
  expect(calls).toEqual([]);
});

// The same, through the server-side hook rather than an injected block: a
// host view calling views.embedded_dashboard() (tests/urls.py).
test('a host page served by embedded_dashboard() draws without the endpoint', async ({ page }) => {
  const calls = [];
  await page.route('**/joist/api/schema**', (route) => {
    calls.push(route.request().url());
    return route.fulfill({ status: 500, body: '' });
  });

  await page.goto('/host/embedded/?connection=secondary');
  const labels = page.locator('#joist-canvas svg .nodeLabel');
  await expect(labels.filter({ hasText: /^joist_secondary_only$/ })).toHaveCount(1);
  await expect(page.locator('#joist-stat-conn')).toContainText('secondary');
  // One embedded connection, so no switcher that could not be honoured.
  await expect(page.locator('#joist-connection').locator('xpath=ancestor::*[contains(@class,"joist-field")][1]')).toBeHidden();
  await expect(page.locator('#joist-banners')).toBeEmpty();
  expect(calls).toEqual([]);
});
