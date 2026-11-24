/** Repeat independent, isolated scenarios without hiding failures behind retries. */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { parseArgs } from 'node:util';

const { values } = parseArgs({ args: process.argv.slice(2).filter(arg => arg !== '--'), options: {
  repeat: { type: 'string', default: '1' }, suite: { type: 'string', default: 'all' },
  output: { type: 'string', default: 'output/playwright' }, 'verify-refresh-guard': { type: 'boolean', default: false },
} });
const repeat = Number(values.repeat);
assert(Number.isInteger(repeat) && repeat >= 1 && repeat <= 5, '--repeat must be an integer from 1 to 5');
const suites = {
  workspace: { script: 'workspace_p3_e2e.mjs', prefix: 'P3_E2E' },
  costs: { script: 'cost_v2_e2e.mjs', prefix: 'COST_V2_E2E' },
  classic: { script: 'classic_home_e2e.mjs', prefix: 'CLASSIC_E2E' },
};
const selected = values.suite === 'all' ? Object.keys(suites) : values.suite.split(',');
assert(selected.length && selected.every(name => Object.hasOwn(suites, name)), '--suite must be all, workspace, costs or classic');
const { repo } = await import('./browser_e2e_support.mjs');
const output = resolve(repo, values.output);
await mkdir(output, { recursive: true });
const results = [];

async function execute(name, directory, extraEnv = {}) {
  const { script, prefix } = suites[name];
  await mkdir(directory, { recursive: true });
  const child = spawn(process.execPath, [resolve(repo, 'scripts/dev', script)], {
    cwd: repo, env: { ...process.env, [`${prefix}_OUTPUT`]: directory, ...extraEnv }, stdio: ['ignore', 'pipe', 'pipe'],
  });
  let logs = '', timedOut = false, interrupted = false;
  const append = data => { logs = (logs + data).slice(-1000000); };
  child.stdout.on('data', append);
  child.stderr.on('data', append);
  const terminate = () => { interrupted = true; child.kill('SIGTERM'); };
  process.once('SIGINT', terminate);
  process.once('SIGTERM', terminate);
  const timer = setTimeout(() => { timedOut = true; child.kill('SIGTERM'); }, 180000);
  try {
    const code = await new Promise((done, reject) => { child.once('close', done); child.once('error', reject); });
    await writeFile(resolve(directory, 'runner.log'), logs);
    assert(!timedOut && !interrupted, `${name}: scenario timed out or was interrupted`);
    return { code, logs };
  } finally {
    clearTimeout(timer);
    process.removeListener('SIGINT', terminate);
    process.removeListener('SIGTERM', terminate);
  }
}

try {
  for (let iteration = 1; iteration <= repeat; iteration++) {
    for (const name of selected) {
      const directory = resolve(output, `run-${iteration}`, name);
      const { code, logs } = await execute(name, directory);
      assert.equal(code, 0, `${name} failed; see ${directory}\n${logs.slice(-6000)}`);
      const result = JSON.parse(await readFile(resolve(directory, 'result.json'), 'utf8'));
      assert.equal(result.status, 'passed');
      results.push({ iteration, name, ...result });
      console.log(`PASS run ${iteration}: ${name}`);
    }
  }
  if (values['verify-refresh-guard']) {
    // An expected failure counts only if the real browser reaches the specific
    // row-identity assertion. Missing dependencies/startup failures cannot pass.
    const directory = resolve(output, 'refresh-mutation');
    const { code } = await execute('classic', directory, { CLASSIC_E2E_MUTATE_REFRESH: '1' });
    assert.notEqual(code, 0, 'The deliberately broken whole-table repaint escaped the regression');
    const failure = await readFile(resolve(directory, 'failure.txt'), 'utf8');
    assert.match(failure.split('\n')[0], /AssertionError.*CLASSIC_LOCAL_REFRESH_LOST/);
    results.push({ name: 'refresh-mutation', status: 'detected' });
    console.log('PASS mutation: whole-table repaint was rejected by the browser assertion');
  }
  await writeFile(resolve(output, 'summary.json'), JSON.stringify({ status: 'passed', repeat, results }, null, 2));
} catch (error) {
  await writeFile(resolve(output, 'summary.json'), JSON.stringify({ status: 'failed', repeat, results, error: String(error) }, null, 2));
  throw error;
}
