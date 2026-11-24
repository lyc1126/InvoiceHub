/** Shared lifecycle for synthetic localhost browser regressions. */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export const repo = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const require = createRequire(resolve(repo, 'frontend/package.json'));
export const python = process.env.PYTHON || resolve(repo, process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python');

export async function runBrowserScenario({ name, fixture, prefix, args = [], run }) {
  const output = resolve(process.env[`${prefix}_OUTPUT`] || `output/playwright/${name}`);
  await mkdir(output, { recursive: true });
  const socket = createServer();
  await new Promise((done, reject) => { socket.once('error', reject); socket.listen(0, '127.0.0.1', done); });
  const port = socket.address().port;
  await new Promise((done, reject) => socket.close(error => error ? reject(error) : done()));
  const dataRoot = await mkdtemp(resolve(tmpdir(), 'invoicehub-e2e-'));
  // Every fixture creates its own temporary root/config. Do not inherit a host
  // token or default-config override from a running desktop instance.
  const env = { ...process.env, PYTHONPATH: resolve(repo, 'src'), INVOICE_HUB_DISABLE_NOTIFY: '1', PYTHONUNBUFFERED: '1' };
  for (const key of Object.keys(env)) if (key.startsWith('INVOICE_HUB_') && !['INVOICE_HUB_DISABLE_NOTIFY'].includes(key)) delete env[key];
  const child = spawn(python, [resolve(repo, 'scripts/dev', fixture), '--port', String(port), '--root', dataRoot, ...args], {
    cwd: repo, env, stdio: ['ignore', 'pipe', 'pipe'],
  });
  let logs = '', spawnError, browser, context, page, failure, interrupted = false;
  const exited = new Promise(done => { child.once('close', done); child.once('error', error => { spawnError = error; done(); }); });
  const append = data => { logs = (logs + data).slice(-100000); };
  child.stdout.on('data', append);
  child.stderr.on('data', append);
  const interrupt = () => {
    interrupted = true;
    if (context) void context.close().catch(() => {});
    if (browser) void browser.close().catch(() => {});
    child.kill('SIGINT');
  };
  process.once('SIGINT', interrupt);
  process.once('SIGTERM', interrupt);
  const base = `http://127.0.0.1:${port}`;
  try {
    const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
    const cdp = process.env[`${prefix}_CDP`] || process.env.BROWSER_E2E_CDP;
    const channel = process.env[`${prefix}_BROWSER`] || process.env.BROWSER_E2E_BROWSER || 'chromium';
    browser = cdp ? await chromium.connectOverCDP(cdp) : await chromium.launch({
      ...(channel === 'chromium' ? {} : { channel }),
      headless: !process.env[`${prefix}_HEADED`] && !process.env.BROWSER_E2E_HEADED,
    });
    assert(!interrupted, 'Browser scenario interrupted');
    context = await browser.newContext({ viewport: { width: 1440, height: 900 }, acceptDownloads: true });
    await context.tracing.start({ screenshots: true, snapshots: true, sources: true });
    page = await context.newPage();
    page.setDefaultTimeout(15000);
    let ready = false;
    // Probe through the browser: some local agent environments restrict Node
    // loopback access even when Chromium can reach the same isolated fixture.
    for (const deadline = Date.now() + 30000; Date.now() < deadline;) {
      if (spawnError) throw spawnError;
      if (child.exitCode !== null || child.signalCode !== null) throw Error(`Fixture exited: ${logs}`);
      try { ready = (await page.goto(`${base}/api/v1/health`, { timeout: 2000 }))?.ok() ?? false; } catch {}
      if (ready) break;
      await new Promise(done => setTimeout(done, 200));
    }
    assert(ready, `Fixture unavailable: ${logs}`);
    await run({ page, context, base, output, python, repo });
  } catch (error) {
    failure = error;
    if (page) await page.screenshot({ path: resolve(output, 'failure.png'), fullPage: true }).catch(() => {});
    await writeFile(resolve(output, 'failure.txt'), String(error.stack || error));
    throw error;
  } finally {
    process.removeListener('SIGINT', interrupt);
    process.removeListener('SIGTERM', interrupt);
    // Closing our own context before stopping Uvicorn releases its SSE clients.
    // CDP browser.close only disconnects; the user's other contexts survive.
    if (context) {
      await context.tracing.stop({ path: resolve(output, 'trace.zip') }).catch(() => {});
      await context.close().catch(() => {});
    }
    if (browser) await browser.close().catch(() => {});
    if (!spawnError && child.exitCode === null && child.signalCode === null) {
      child.kill('SIGINT');
      let timer;
      await Promise.race([exited, new Promise(done => { timer = setTimeout(done, 5000); })]);
      clearTimeout(timer);
      if (child.exitCode === null && child.signalCode === null) { child.kill('SIGKILL'); await exited; }
    }
    await writeFile(resolve(output, 'backend.log'), logs);
    // The parent owns the synthetic root, so a forced fixture exit cannot leave
    // temporary invoice projections behind. Never remove a caller's directory.
    await rm(dataRoot, { recursive: true, force: true });
    if (failure) console.error(logs.slice(-5000));
  }
}
