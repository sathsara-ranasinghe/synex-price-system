// End-to-end smoke test: starts a throw-away backend (SQLite, port 8200) serving the built frontend,
// loads sample QuickBooks data through a simulated Web Connector session, then opens every page,
// every entity list, every "new" form and the first record of each list in a headless browser.
// Fails on JavaScript errors, 5xx responses or failed requests.
//
//   npm run build && npm run e2e
//
// Browser: CHROME_PATH, or Microsoft Edge / Google Chrome in their default Windows/Linux locations.

import { spawn, spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, rmSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import puppeteer from 'puppeteer-core';

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '..', '..');
const backend = join(root, 'backend');
const dist = join(root, 'frontend', 'dist', 'frontend', 'browser');
const port = 8200;
const base = `http://127.0.0.1:${port}`;
const work = join(here, '.run');
const isWin = process.platform === 'win32';
const python = join(backend, '.venv', isWin ? 'Scripts/python.exe' : 'bin/python');

const browserPath = process.env.CHROME_PATH || [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser', '/usr/bin/microsoft-edge',
].find((p) => existsSync(p));

if (!existsSync(join(dist, 'index.html'))) throw new Error('Build the frontend first (ng build)');
if (!browserPath) throw new Error('No Chrome/Edge found - set CHROME_PATH');

rmSync(work, { recursive: true, force: true });
mkdirSync(work, { recursive: true });
const env = {
  ...process.env,
  DATABASE_URL: `sqlite:///${join(work, 'e2e.db').replace(/\\/g, '/')}`,
  QBWC_USERNAME: 'qbwc', QBWC_PASSWORD: 'secret', ADMIN_PASSWORD: 'Admin@123', JWT_SECRET: 'e2e',
  STATIC_DIR: dist, ATTACHMENTS_DIR: join(work, 'att'), QBWC_RUN_EVERY_MINUTES: '1', SMTP_HOST: '', REQUIRE_2FA: 'off',
};

const server = spawn(python, ['run.py', String(port)], { cwd: backend, env, stdio: ['ignore', 'pipe', 'pipe'] });
let serverLog = '';
server.stdout.on('data', (d) => (serverLog += d));
server.stderr.on('data', (d) => (serverLog += d));

const failures = [];
let browser;
try {
  for (let i = 0; ; i++) {
    try { if ((await fetch(`${base}/api/health`)).ok) break; } catch { /* starting */ }
    if (i > 60) throw new Error('backend did not start:\n' + serverLog);
    await new Promise((r) => setTimeout(r, 500));
  }

  // sample QuickBooks data via a simulated Web Connector session
  const sim = spawnSync(python, ['-m', 'scripts.simulate_qbwc', base, 'qbwc', 'secret'], { cwd: backend, env, encoding: 'utf8' });
  if (sim.status !== 0) throw new Error('simulator failed: ' + sim.stderr);

  browser = await puppeteer.launch({ executablePath: browserPath, headless: 'new' });
  const page = await browser.newPage();
  await page.setViewport({ width: 1366, height: 860 });
  let current = '';
  page.on('pageerror', (e) => failures.push(`${current}: JS error ${e.message}`));
  page.on('console', (m) => { if (m.type() === 'error' && !/favicon|manifest|ERR_ABORTED/.test(m.text())) failures.push(`${current}: console ${m.text()}`); });
  page.on('response', (r) => { if (r.status() >= 500) failures.push(`${current}: ${r.status()} ${r.url()}`); });
  page.on('requestfailed', (r) => {
    const err = r.failure()?.errorText ?? '';
    if (!/ERR_ABORTED/.test(err)) failures.push(`${current}: request failed ${r.url()} ${err}`);
  });

  // sign in through the real form
  current = '/login';
  await page.goto(`${base}/login`, { waitUntil: 'networkidle0' });
  await page.type('#u', 'admin');
  await page.type('#p', 'Admin@123');
  await Promise.all([page.waitForNavigation({ waitUntil: 'networkidle0' }), page.click('button.go')]);
  if (new URL(page.url()).pathname !== '/') failures.push('login did not reach the home page');

  const meta = await page.evaluate(async () => {
    const token = localStorage.getItem('synex_token');
    return (await fetch('/api/qb/meta', { headers: { Authorization: `Bearer ${token}` } })).json();
  });

  const visit = async (path, expectSelector) => {
    current = path;
    await page.goto(base + path, { waitUntil: 'networkidle0' });
    await new Promise((r) => setTimeout(r, 150));
    if (expectSelector && !(await page.$(expectSelector))) failures.push(`${path}: missing ${expectSelector}`);
  };

  const pages = ['/', '/qb-reports', '/qb-changes', '/sync', '/companies', '/users', '/roles', '/audit', '/notifications', '/aging', '/aging?side=ap', '/stock-alerts', '/account'];
  for (const p of pages) await visit(p, 'h1');

  let records = 0;
  for (const e of meta.entities) {
    await visit(`/qb/${e.key}`, 'h1');
    const first = await page.$('table.simple tr.clickable');
    if (first) {
      records++;
      current = `/qb/${e.key}/<first>`;
      await Promise.all([page.waitForNavigation({ waitUntil: 'networkidle0' }), first.click()]);
    }
    if (e.can_add && e.permissions.create) {
      await visit(`/qb/${e.key}/new`, 'h1');
      await visit(`/qb/${e.key}/import`, 'h1');
    }
  }

  console.log(`Visited ${pages.length} pages, ${meta.entities.length} entity lists, ` +
    `${meta.entities.filter((e) => e.can_add).length} new-record forms + import pages and ${records} record pages.`);
} catch (e) {
  failures.push(String(e?.stack ?? e));
} finally {
  await browser?.close();
  server.kill();
}

if (failures.length) {
  console.error(`\n${failures.length} problem(s):\n- ` + [...new Set(failures)].join('\n- '));
  process.exit(1);
}
console.log('E2E smoke test passed');
