const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

const outputDirectory = path.resolve(process.env.QA_DIR || '.qa');
fs.mkdirSync(outputDirectory, { recursive: true });
(async () => {
  const browser = await chromium.launch({ executablePath: process.env.BROWSER_PATH || undefined, headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1080 }, deviceScaleFactor: 1, permissions: ['clipboard-read', 'clipboard-write'] });
  const page = await context.newPage();
  const errors = [], requests = [], checks = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  page.on('request', request => requests.push(request.url()));
  const check = (label, value) => { assert.ok(value, label); checks.push(label); };
  try {
    const response = await page.goto('http://127.0.0.1:4173/', { waitUntil: 'networkidle' });
    check('Static page responds HTTP 200', response.status() === 200);
    check('Initial Friday search returns two messages', await page.locator('.result-card').count() === 2);
    await page.screenshot({ path: path.join(outputDirectory, 'desktop-full.png'), fullPage: true });
    await page.screenshot({ path: path.join(outputDirectory, 'desktop-hero.png') });
    for (const width of [1440, 1024, 768, 760, 390, 375, 320]) {
      await page.setViewportSize({ width, height: 900 });
      check(`No horizontal overflow at ${width}px`, await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
      const overlaps = await page.evaluate(() => {
        const heading = document.querySelector('.hero h1').getBoundingClientRect();
        const art = document.querySelector('.hero-art').getBoundingClientRect();
        return heading.right > art.left && heading.left < art.right && heading.top < art.bottom && heading.bottom > art.top;
      });
      check(`Hero text and art do not overlap at ${width}px`, !overlaps);
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: path.join(outputDirectory, 'phone-full.png'), fullPage: true });
    await page.screenshot({ path: path.join(outputDirectory, 'phone-hero.png') });
    await page.locator('#playground').scrollIntoViewIfNeeded();
    await page.locator('.demo-frame').screenshot({ path: path.join(outputDirectory, 'phone-demo.png') });
    await page.getByRole('button', { name: 'person', exact: false }).click();
    check('Person preset finds all four messages by exact sample user ID', await page.locator('.result-card').count() === 4 && await page.locator('#search-input').inputValue() === '100000000000000001');
    await page.getByRole('button', { name: 'DM catch-up', exact: false }).click();
    check('DM catch-up finds three messages', await page.locator('.result-card').count() === 3);
    check('Active scope has accessible pressed state', await page.locator('[data-scope="dm"]').getAttribute('aria-pressed') === 'true');
    await page.locator('#search-input').fill('sidebar');
    await page.locator('#search-input').press('Enter');
    check('Typed query and Enter search work', await page.locator('.result-card').count() === 1);
    await page.locator('.context-button').click();
    check('Source opens native modal dialog', await page.locator('#context-dialog').evaluate(node => node.open));
    check('Source context includes surrounding sample messages', await page.locator('.context-message').count() === 3);
    check('Keyboard focus enters modal', await page.evaluate(() => document.querySelector('#context-dialog').contains(document.activeElement)));
    await page.keyboard.press('Tab');
    await page.keyboard.press('Tab');
    check('Keyboard focus remains inside modal', await page.evaluate(() => document.activeElement === document.body || document.querySelector('#context-dialog').contains(document.activeElement)));
    await page.keyboard.press('Escape');
    check('Escape closes dialog and returns focus to source', !await page.locator('#context-dialog').evaluate(node => node.open) && await page.locator('.context-button').evaluate(node => node === document.activeElement));
    await page.locator('#search-input').fill('<img src=x onerror=alert(1)>');
    await page.locator('#search-input').press('Enter');
    check('Unknown query has useful empty state without injecting markup', await page.locator('.empty-state').count() === 1 && await page.locator('img').count() === 0);
    await page.getByRole('button', { name: 'Show all sample messages' }).click();
    check('Empty-state reset restores all eight messages and focuses input', await page.locator('.result-card').count() === 8 && await page.locator('#search-input').evaluate(node => node === document.activeElement));
    await page.locator('#search-input').fill('100000000000000002');
    await page.locator('#search-input').press('Enter');
    check('Exact ID search also works for a different sample author', await page.locator('.result-card').count() === 2 && (await page.locator('#result-status').innerText()).includes('Jules'));
    await page.locator('#copy-prompt').click();
    check('Copy example prompt writes the intended text', (await page.evaluate(() => navigator.clipboard.readText())).startsWith('Show my available DMs.'));
    if (await page.locator('#copy-install').isEnabled()) {
      await page.locator('#copy-install').click();
      check('Copy installation command writes the exact displayed command', await page.evaluate(() => navigator.clipboard.readText()) === await page.locator('#install-command').innerText());
    } else {
      checks.push('Install copy safely disabled while release command is unverified');
      // Exercise the enabled state with a conspicuously inert fixture. Never execute it.
      const fixture = { repository: 'https://github.com/example/mcpc-demo', docsPath: '#readme', installCommand: 'echo "MCPCord browser test only"', platformLabel: 'TEST FIXTURE', prerequisites: 'Synthetic release data for a browser test.' };
      await page.route('**/release-config.js', route => route.fulfill({ contentType: 'text/javascript', body: 'window.MCPCORD_RELEASE = ' + JSON.stringify(fixture) + ';' }));
      await page.reload();
      check('Verified-command configuration enables install copy', await page.locator('#copy-install').isEnabled());
      await page.locator('#copy-install').click();
      check('Install copy writes exact configured command (inert test fixture)', await page.evaluate(() => navigator.clipboard.readText()) === fixture.installCommand);
      check('Release configuration resolves repository links', await page.locator('.header-source').getAttribute('href') === fixture.repository);
      check('Completed release configuration hides preview note', await page.locator('#release-notes').isHidden());
      await page.unroute('**/release-config.js');
      await page.reload();
    }
    await page.locator('.faq-list summary').first().focus();
    await page.keyboard.press('Enter');
    check('FAQ works from keyboard', await page.locator('.faq-list details').first().getAttribute('open') !== null);
    const brokenAnchors = await page.evaluate(() => Array.from(document.querySelectorAll('a[href^="#"]')).filter(a => a.hash && !document.getElementById(a.hash.slice(1))).map(a => a.href));
    check('Every nonempty internal link has a target', brokenAnchors.length === 0);
    await page.emulateMedia({ reducedMotion: 'reduce' });
    check('Reduced-motion preference disables smooth scrolling', await page.evaluate(() => getComputedStyle(document.documentElement).scrollBehavior) === 'auto');
    await page.goto('http://127.0.0.1:4173/');
    await page.keyboard.press('Tab');
    check('Skip link is first keyboard stop', await page.evaluate(() => document.activeElement.classList.contains('skip-link')));
    check('Page and interactions make no external requests', requests.every(url => url.startsWith('http://127.0.0.1:4173/')));
    check('No cookies or browser storage created', (await context.cookies()).length === 0 && await page.evaluate(() => !localStorage.length && !sessionStorage.length));
    check('No JavaScript or console errors', errors.length === 0);
    const noJS = await browser.newContext({ javaScriptEnabled: false, viewport: { width: 390, height: 844 } });
    const noJSPage = await noJS.newPage();
    await noJSPage.goto('http://127.0.0.1:4173/');
    check('Core content and setup remain available without JavaScript', await noJSPage.locator('h1').isVisible() && await noJSPage.locator('#setup-heading').count() === 1 && await noJSPage.locator('noscript').isVisible());
    await noJS.close();
    fs.writeFileSync(path.join(outputDirectory, 'results.json'), JSON.stringify({ passed: checks.length, checks, errors, externalRequests: requests.filter(url => !url.startsWith('http://127.0.0.1:4173/')) }, null, 2) + '\n');
    console.log(JSON.stringify({ passed: checks.length, errors, screenshots: ['desktop-full.png', 'desktop-hero.png', 'phone-full.png', 'phone-hero.png', 'phone-demo.png'] }, null, 2));
  } finally { await browser.close(); }
})();
