#!/usr/bin/env node
// Thin CLI shim: the real work is Python. This exists so that `npm i screenshotpro`
// gives you something to run (npx screenshotpro ...), instead of a package with no entry point.
import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, '..');

const COMMANDS = {
  render: { script: 'tools/render.py', usage: 'render <spec.json>', needArg: true },
  verify: { script: 'tools/verify.py', usage: 'verify <spec.json>', needArg: true },
  measure: { script: 'tools/measure_win.py', usage: 'measure --exe <app.exe> --out figures/<name>', needArg: false },
  'self-test': { script: 'tests/run_tests.py', usage: 'self-test', needArg: false },
  fixture: { script: 'tools/make_fixture.py', usage: 'fixture <dir>', needArg: true },
};

function help() {
  console.log('screenshotpro - measured, verified UI screenshots');
  console.log('');
  console.log('Usage:');
  for (const [, c] of Object.entries(COMMANDS)) console.log('  screenshotpro ' + c.usage);
  console.log('');
  console.log('Needs Python 3.9+ and Pillow. Set PYTHON=... to pick a specific interpreter.');
}

const [cmd, ...rest] = process.argv.slice(2);
if (!cmd || cmd === '-h' || cmd === '--help' || cmd === 'help') { help(); process.exit(0); }
const spec = COMMANDS[cmd];
if (!spec) { console.error('unknown command: ' + cmd); help(); process.exit(2); }
if (spec.needArg && rest.length === 0) { console.error('missing argument.'); console.error('  screenshotpro ' + spec.usage); process.exit(2); }

const scriptPath = join(ROOT, spec.script);
if (!existsSync(scriptPath)) { console.error('cannot find ' + scriptPath + ' - is the package installed completely?'); process.exit(2); }

const candidates = [process.env.PYTHON, 'python', 'python3'].filter(Boolean);
let lastErr = null;
let foundPython = false;
for (const py of candidates) {
  const probe = spawnSync(py, ['-c', 'import PIL'], { stdio: 'ignore' });
  if (probe.error || probe.status !== 0) { lastErr = probe.error || new Error(py + ' cannot import PIL'); continue; }
  foundPython = true;
  const r = spawnSync(py, [scriptPath, ...rest], { stdio: 'inherit' });
  if (r.error && r.error.code === 'ENOENT') { lastErr = r.error; continue; }
  if (r.error) { console.error(String(r.error)); process.exit(1); }
  process.exit(r.status === null ? 1 : r.status);
}
console.error('could not start Python (' + candidates.join(', ') + '). Install Python 3.9+ or set PYTHON=/path/to/python.');
if (lastErr) console.error(String(lastErr.message || lastErr));
process.exit(127);
