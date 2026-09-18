import { defineConfig, devices } from '@playwright/test';

// Drives the real Django app in a headless browser: the page the host mounts,
// the shipped assets, the JSON endpoint and the export route. Vitest-free
// concerns live here - actual Mermaid rendering, focus/filter interaction, the
// pan/zoom transform, keyboard operation, and the axe scan.
//
// The test server is `tests/browser/serve.py` (see its docstring for the two
// fixtures it seeds). Set JOIST_PYTHON to the interpreter that has Django and
// this package installed when running outside a project virtualenv.
const python = process.env.JOIST_PYTHON ?? 'python';
const port = process.env.JOIST_BROWSER_PORT ?? '8899';

export default defineConfig({
  testDir: './tests/browser',
  timeout: 30_000,
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    trace: 'retain-on-failure',
  },
  webServer: {
    command: `${python} tests/browser/serve.py`,
    url: `http://127.0.0.1:${port}/joist/`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    env: { JOIST_BROWSER_PORT: port },
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
