#!/usr/bin/env python3
"""Offline self-test for screenshotpro.

Round-trip with no real application and no network:
  1. tools/make_fixture.py  -> synthetic shot.png + dump.json + spec.json
  2. tools/render.py        -> out/<name>.png + render-report.json
  3. tools/verify.py        -> 15 assertions, must all PASS (exit 0)
  4. tools/verify.py on a deliberately corrupted report -> must FAIL (exit 1)

Step 4 matters as much as step 3: a checker that never fails proves nothing.

Usage: python tests/run_tests.py [--keep]
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(os.path.dirname(HERE), 'tools')
PY = sys.executable

EXPECTED_ROWS = ['1', '2', '3', '4', '5', '6a', '6b', '6c', '7', '8',
                 '9', '10', '11', '12', '13']


def run(args):
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    proc = subprocess.run([PY] + args, capture_output=True, text=True,
                          encoding='utf-8', errors='replace', env=env)
    return proc.returncode, (proc.stdout or ''), (proc.stderr or '')


def parse_table(stdout):
    rows = {}
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith('[PASS]') or line.startswith('[FAIL]'):
            verdict = line[1:5]
            rest = line[6:].strip()
            num = rest.split(' ', 1)[0]
            rows[num] = (verdict, rest)
    return rows


def find_report(base):
    hits = glob.glob(os.path.join(base, '**', 'render-report.json'), recursive=True)
    return hits[0] if hits else None


def main(argv):
    # A Windows console may be cp936 while the child prints UTF-8; never crash on it.
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, OSError):
        pass
    keep = '--keep' in argv[1:]
    failures = []
    tmp = tempfile.mkdtemp(prefix='screenshotpro-test-')
    fixture = os.path.join(tmp, 'fixture')
    spec = os.path.join(fixture, 'spec.json')
    print('workdir : %s' % tmp)

    # --- 1. build the synthetic fixture -------------------------------------
    rc, out, err = run([os.path.join(TOOLS, 'make_fixture.py'), fixture])
    print('[1/4] make_fixture.py exit=%d' % rc)
    for name in ('shot.png', 'dump.json', 'spec.json'):
        if not os.path.isfile(os.path.join(fixture, name)):
            failures.append('fixture is missing %s' % name)
    if rc != 0:
        failures.append('make_fixture.py failed: %s' % (err.strip() or out.strip()))

    # --- 2. render ----------------------------------------------------------
    rc, out, err = run([os.path.join(TOOLS, 'render.py'), spec])
    print('[2/4] render.py     exit=%d' % rc)
    report = find_report(fixture)
    if rc != 0:
        failures.append('render.py failed: %s' % (err.strip() or out.strip()))
    if report is None:
        failures.append('render.py wrote no render-report.json')

    # --- 3. verify: 15 rows, all PASS ---------------------------------------
    if report is not None:
        rc, out, err = run([os.path.join(TOOLS, 'verify.py'), spec, '--report', report])
        rows = parse_table(out)
        print('[3/4] verify.py     exit=%d rows=%d' % (rc, len(rows)))
        print('-' * 72)
        print(out.rstrip())
        print('-' * 72)
        missing = [n for n in EXPECTED_ROWS if n not in rows]
        if missing:
            failures.append('verify.py did not report assertion(s) %s' % ', '.join(missing))
        bad = [n for n in EXPECTED_ROWS if n in rows and rows[n][0] == 'FAIL']
        if bad:
            failures.append('assertion(s) FAILED: %s' % ', '.join(bad))
        if rc != 0:
            failures.append('verify.py exit=%d on a clean fixture' % rc)
        if len(rows) != len(EXPECTED_ROWS):
            failures.append('expected %d rows, got %d' % (len(EXPECTED_ROWS), len(rows)))

    # --- 4. the checker must fail on a corrupted report ---------------------
    if report is not None:
        broken_dir = os.path.join(tmp, 'broken')
        shutil.copytree(fixture, broken_dir)
        broken_report = find_report(broken_dir)
        with open(broken_report, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        data['steps'][0]['image_rect']['x'] += 1   # 1 px of silent re-conversion
        with open(broken_report, 'w', encoding='utf-8') as fh:
            json.dump(data, fh, indent=2)
        rc, out, err = run([os.path.join(TOOLS, 'verify.py'),
                            os.path.join(broken_dir, 'spec.json'), '--report', broken_report])
        rows = parse_table(out)
        caught = [n for n in rows if rows[n][0] == 'FAIL']
        print('[4/4] verify.py on a corrupted report: exit=%d FAIL rows=%s'
              % (rc, caught or 'none'))
        if rc == 0:
            failures.append('verify.py passed a corrupted report (exit 0)')
        if '3' not in caught:
            failures.append('assertion 3 did not catch a 1px image_rect mismatch (caught: %s)'
                            % (caught or 'none'))

    if not keep:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if failures:
        for item in failures:
            print('RESULT: FAIL -- %s' % item)
        return 1
    print('RESULT: PASS -- 15/15 assertions on the fixture, and the checker rejects a')
    print('         corrupted report. Figure at %s' % (report or '(none)'))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))

