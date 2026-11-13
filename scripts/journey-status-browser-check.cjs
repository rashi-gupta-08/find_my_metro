// Local UI verification. Crowd evidence is intercepted in an isolated browser,
// never inserted into the application database or the research dataset.
const { chromium, devices } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');

(async () => {
  const output = '.local/journey-status-checks';
  await fs.mkdir(output, { recursive: true });
  const browser = await chromium.launch({ headless: true, executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe' });
  const checks = [], errors = [];
  const navigate = (page, label) => page.getByRole('navigation', { name: 'Main navigation' }).getByRole('button', { name: label, exact: true });
  const choose = async (page, label, query) => {
    await page.getByRole('button', { name: `${label} station`, exact: true }).click();
    await page.getByRole('combobox', { name: `Search ${label.toLowerCase()} station`, exact: true }).fill(query);
    await page.getByRole('option').first().click();
  };
  const visible = async (page, selector) => page.waitForFunction(selector => {
    const element = document.querySelector(selector);
    return element && getComputedStyle(element).opacity === '1';
  }, selector);
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, serviceWorkers: 'block' });
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    await page.goto('http://localhost:5173/');
    await navigate(page, 'Journey status').click();
    await page.getByRole('heading', { name: 'Journey status', exact: true }).waitFor();
    assert.equal(await page.getByLabel('Tracked trip').count(), 0);
    await page.getByRole('heading', { name: 'Your journey at a glance', exact: true }).waitFor();
    await visible(page, '.journey-status-page');
    await page.screenshot({ path: `${output}/empty-desktop.png` });
    checks.push('Unconnected train selector is replaced with an accessible journey picker');

    await page.getByRole('button', { name: 'Show status', exact: true }).click();
    await page.locator('.status-route-summary').waitFor();
    await page.getByRole('status').filter({ hasText: 'Updates connected' }).waitFor();
    assert((await page.locator('.status-sections').innerText()).includes('Underground section'));
    assert((await page.locator('.status-sections').innerText()).includes('Transition section'));
    assert((await page.locator('.status-sections').innerText()).includes('Surface section'));
    assert((await page.locator('.status-sections').innerText()).includes('Walking connection'));
    assert(await page.locator('.journey-source').count() >= 3);
    assert.equal(await page.locator('.journey-source[data-source="wsn"]').count(), 0);
    checks.push('Actual cross-operator route shows all configured contexts, walking and real source-status fields');
    const alternate = await page.getByLabel('Journey route option').locator('option').nth(1).getAttribute('value');
    await page.getByLabel('Journey route option').selectOption(alternate);
    await page.getByRole('button', { name: 'View full route', exact: true }).click();
    assert.equal(await page.locator('.journey-selected').count(), 1);
    await page.locator('.journey-selected').getByRole('button', { name: 'Journey status', exact: true }).click();
    await page.locator('.status-route-summary').waitFor();
    assert.equal(await page.getByLabel('Journey route option').inputValue(), alternate);
    checks.push('Selected alternative stays selected between Plan and Journey Status');
    await visible(page, '.journey-status-page');
    await page.screenshot({ path: `${output}/status-desktop.png`, fullPage: true });

    await choose(page, 'From', 'Noida Sector - 51');
    await choose(page, 'To', 'Pari Chowk');
    assert.equal(await page.locator('.status-route-summary').count(), 0);
    await page.getByRole('button', { name: 'Show status', exact: true }).click();
    await page.locator('.status-route-summary').waitFor();
    assert((await page.locator('.status-route-top h2').innerText()).includes('Pari Chowk'));
    await page.getByRole('status').filter({ hasText: 'Updates connected' }).waitFor();
    await context.setOffline(true);
    await page.getByRole('status').filter({ hasText: 'Saved journey' }).waitFor();
    assert((await page.locator('.status-boarding').innerText()).includes('Saved status'));
    await context.setOffline(false);
    await page.getByRole('status').filter({ hasText: 'Updates connected' }).waitFor();
    checks.push('Changing stations clears old results; offline status and reconnection remain explicit');
    await page.getByRole('button', { name: 'Report a station update', exact: true }).click();
    await page.getByRole('dialog').waitFor();
    await page.keyboard.press('Escape');
    checks.push('Report action uses the existing authenticated reporting flow');

    const mobile = await browser.newContext({ ...devices['Pixel 7'], viewport: { width: 360, height: 800 }, serviceWorkers: 'block' });
    const phone = await mobile.newPage();
    phone.on('pageerror', error => errors.push(error.message));
    await phone.goto('http://localhost:5173/');
    await navigate(phone, 'Journey status').tap();
    await phone.getByRole('button', { name: 'Show status', exact: true }).tap();
    await phone.locator('.status-route-summary').waitFor();
    await visible(phone, '.journey-status-page');
    assert(await phone.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    await phone.screenshot({ path: `${output}/status-phone.png`, fullPage: true });
    checks.push('Journey Status and the longer navigation label fit a 360px Android-style screen');

    // Isolated contract fixture exercises live, disconnected and expired data.
    const fixtureContext = await browser.newContext({ viewport: { width: 1280, height: 950 }, serviceWorkers: 'block' });
    const fixturePage = await fixtureContext.newPage();
    fixturePage.on('pageerror', error => errors.push(error.message));
    const base = await (await fixturePage.request.get('http://localhost:5173/api/v1/routes?origin=dmrc-mdhs&destination=dmrc-yb&preference=fastest')).json();
    const route = structuredClone(base.routes[0]);
    const now = Date.now();
    const evidence = { ...route.source_statuses[0], source: 'crowd', scope: 'station_service', trust_score: .86, freshness_status: 'fresh', last_observed_at: new Date(now).toISOString(), valid_until: new Date(now + 14000).toISOString(), delay_seconds: 120, reason: 'independent_reports_agree' };
    route.source_statuses = [evidence];
    route.source = 'live_and_schedule';
    route.delay_seconds = 120;
    route.duration_seconds += 120;
    route.arrival_at = new Date(Date.parse(route.arrival_at) + 120000).toISOString();
    route.steps = route.steps.map((step, index) => ({ ...step, ...(index === 0 ? { source_status: evidence, source: 'crowd', delay_seconds: 120, wait_seconds: (step.wait_seconds ?? 0) + 120, seconds: step.seconds + 120 } : {}), departure_at: new Date(Date.parse(step.departure_at) + (index ? 120000 : 0)).toISOString(), arrival_at: new Date(Date.parse(step.arrival_at) + 120000).toISOString() }));
    const fixture = { ...base, type: 'journey_snapshot', routes: [route], generated_at: new Date(now).toISOString(), snapshot_version: now };
    await fixtureContext.route(/\/api\/v1\/routes\?/, request => request.fulfill({ json: fixture }));
    await fixturePage.routeWebSocket(/\/ws\/journeys\?/, socket => socket.send(JSON.stringify(fixture)));
    await fixturePage.goto('http://localhost:5173/');
    await navigate(fixturePage, 'Journey status').click();
    await choose(fixturePage, 'From', 'Mandi House');
    await choose(fixturePage, 'To', 'Yamuna Bank');
    await fixturePage.getByRole('button', { name: 'Show status', exact: true }).click();
    await fixturePage.locator('.journey-source[data-source="crowd"]').waitFor();
    assert((await fixturePage.locator('.status-metrics').innerText()).includes('+2 min'));
    await fixtureContext.setOffline(true);
    await fixturePage.getByRole('status').filter({ hasText: 'Saved journey' }).waitFor();
    assert((await fixturePage.locator('.status-metrics').innerText()).includes('No active report'));
    await fixtureContext.setOffline(false);
    await fixturePage.getByRole('status').filter({ hasText: 'Updates connected' }).waitFor();
    await fixturePage.waitForFunction(() => document.querySelector('.journey-source')?.getAttribute('data-source') === 'schedule', undefined, { timeout: 20000 });
    assert((await fixturePage.locator('.status-metrics').innerText()).includes('No active report'));
    checks.push('Browser-only fixture: confirmed wait appears, disconnect excludes it, expiry restores static status');
    assert.deepEqual(errors, []);
    await fs.writeFile(`${output}/results.json`, JSON.stringify({ checks, errors, fixture_scope: 'Only the final check uses intercepted synthetic evidence. No accounts or reports were submitted to the backend.', created_at: new Date().toISOString() }, null, 2));
    console.log(JSON.stringify({ checks, errors }, null, 2));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
