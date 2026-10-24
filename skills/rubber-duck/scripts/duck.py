#!/usr/bin/env python3
"""duck: a deterministic ledger for rubber-duck debugging by an agent.

The agent narrates the execution path as claims, checks each claim with a
command, and may only edit source once a claim is refuted. Standard library only.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

DIR = '.duck'
SESSION = 'session.json'
LEDGER = 'ledger.jsonl'
EDIT_TOOLS = {'Edit', 'Write', 'MultiEdit', 'NotebookEdit'}
TEST_MARKERS = ('/test/', '/tests/', '/spec/', '/__tests__/', 'test_', '_test.', '.test.', '.spec.', 'conftest.py')
TIMEOUT = 300
TAIL = 20


class DuckError(Exception):
    pass


def git_root(start):
    try:
        out = subprocess.run(['git', '-C', str(start), 'rev-parse', '--show-toplevel'],
                             capture_output=True, text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def find_dir(start):
    """Nearest .duck directory walking up from start, or None."""
    p = Path(start).resolve()
    for d in (p, *p.parents):
        if (d / DIR / SESSION).is_file():
            return d / DIR
    return None


def load(start):
    d = find_dir(start)
    if not d:
        raise DuckError('no duck session here; run `duck start` first')
    return d, json.loads((d / SESSION).read_text())


def save(d, s, event):
    tmp = d / (SESSION + '.tmp')
    tmp.write_text(json.dumps(s, indent=2, ensure_ascii=False) + '\n')
    os.replace(tmp, d / SESSION)
    with open(d / LEDGER, 'a', encoding='utf-8') as f:
        f.write(json.dumps({'at': now(), 'session': s['id'], **event}, ensure_ascii=False) + '\n')


def now():
    return time.strftime('%Y-%m-%dT%H:%M:%S%z')


def run(cmd, cwd):
    try:
        p = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT)
        out, code = (p.stdout + p.stderr), p.returncode
    except subprocess.TimeoutExpired as e:
        out, code = f'{e.stdout or ""}{e.stderr or ""}\n[timed out after {TIMEOUT}s]', 124
    lines = out.rstrip().splitlines()
    return code, '\n'.join(lines[-TAIL:])


def root_cause(s):
    """The first refuted claim in narration order: where the model of the code diverges from the code."""
    return next((c['id'] for c in s['claims'] if c['status'] == 'refuted'), None)


def require_open(s):
    if s['status'] != 'open':
        raise DuckError(f"session {s['id']} is {s['status']}; run `duck start` for a new bug")


# --- commands -----------------------------------------------------------------

def cmd_start(a):
    cwd = Path.cwd()
    existing = find_dir(cwd)
    if existing:
        s = json.loads((existing / SESSION).read_text())
        if s['status'] == 'open':
            raise DuckError(f"session {s['id']} is still open; `duck close` or `duck abandon` it first")
    base = existing.parent if existing else (git_root(cwd) or cwd)
    d = base / DIR
    d.mkdir(exist_ok=True)
    (d / '.gitignore').write_text('*\n')
    code, tail = (None, '') if a.no_run else run(a.repro, base)
    if code == 0:
        raise DuckError('the repro command exits 0, so it does not reproduce the bug; '
                        'make it fail first (a failing test or an assert), or pass --no-run')
    s = {'id': time.strftime('%Y%m%d-%H%M%S'), 'status': 'open', 'root': str(base),
         'expected': a.expected, 'actual': a.actual, 'repro': a.repro,
         'repro_runs': [] if a.no_run else [{'at': now(), 'exit': code, 'output': tail}],
         'claims': [], 'created': now()}
    save(d, s, {'event': 'start', 'repro_exit': code})
    print(f"duck session {s['id']} opened in {d}")
    if code is not None:
        print(f'repro fails as expected (exit {code}):\n{indent(tail)}')
    print('\nNow narrate the execution path, one `duck claim` per step, in order.')


def cmd_claim(a):
    d, s = load(Path.cwd())
    require_open(s)
    cid = f"c{len(s['claims']) + 1}"
    s['claims'].append({'id': cid, 'location': a.location, 'statement': a.statement,
                        'status': 'claimed', 'evidence': []})
    save(d, s, {'event': 'claim', 'claim': cid, 'location': a.location, 'statement': a.statement})
    print(f'{cid}  {a.location}  {a.statement}')


def cmd_check(a):
    d, s = load(Path.cwd())
    require_open(s)
    c = next((c for c in s['claims'] if c['id'] == a.id), None)
    if not c:
        raise DuckError(f'no claim {a.id}')
    code, tail = run(a.cmd, s['root'])
    c['status'] = 'verified' if code == a.expect_exit else 'refuted'
    c['evidence'].append({'at': now(), 'cmd': a.cmd, 'expect_exit': a.expect_exit, 'exit': code, 'output': tail})
    save(d, s, {'event': 'check', 'claim': c['id'], 'status': c['status'], 'exit': code})
    print(f"{c['id']} {c['status'].upper()} (exit {code}, expected {a.expect_exit})")
    if tail:
        print(indent(tail))
    rc = root_cause(s)
    if c['status'] == 'refuted' and rc == c['id']:
        print(f"\nFirst refuted claim: {c['id']} at {c['location']}. Your model of the code is wrong here.\n"
              'Explain why the claim was false; that explanation is the bug. Source edits are now allowed.')
    elif c['status'] == 'refuted':
        print(f'\nRefuted, but {rc} is earlier on the path and remains the root cause.')
    return 0


def cmd_status(a):
    d, s = load(Path.cwd())
    rc = root_cause(s)
    if a.json:
        print(json.dumps({**s, 'root_cause': rc, 'edits_allowed': rc is not None or s['status'] != 'open'}, indent=2))
        return
    print(explain(s, rc))


def cmd_explain(a):
    _, s = load(Path.cwd())
    print(explain(s, root_cause(s), evidence=True))


def cmd_close(a):
    d, s = load(Path.cwd())
    require_open(s)
    rc = root_cause(s)
    if not rc and not a.force:
        raise DuckError('no refuted claim yet: the bug is not located. Keep narrating and checking, '
                        'or `duck abandon` with a reason')
    code, tail = run(s['repro'], s['root'])
    s['repro_runs'].append({'at': now(), 'exit': code, 'output': tail})
    if code != 0:
        save(d, s, {'event': 'close_failed', 'repro_exit': code})
        raise DuckError(f'repro still fails (exit {code}); the session stays open:\n{indent(tail)}')
    s.update(status='closed', closed=now(), root_cause=rc, fix=a.note)
    save(d, s, {'event': 'close', 'root_cause': rc})
    print(f"closed: repro passes. Root cause {rc}: {claim(s, rc)['location']}" if rc else 'closed: repro passes')
    print('\n' + explain(s, rc, evidence=True))


def cmd_abandon(a):
    d, s = load(Path.cwd())
    require_open(s)
    s.update(status='abandoned', closed=now(), reason=a.reason)
    save(d, s, {'event': 'abandon', 'reason': a.reason})
    print(f"session {s['id']} abandoned: {a.reason}")


def cmd_hook(a):
    """PreToolUse gate. Fails open: any internal error lets the tool run."""
    try:
        data = json.load(sys.stdin)
        if data.get('tool_name') not in EDIT_TOOLS:
            return 0
        inp = data.get('tool_input') or {}
        path = inp.get('file_path') or inp.get('notebook_path') or ''
        d = find_dir(data.get('cwd') or Path.cwd())
        if not d:
            return 0
        s = json.loads((d / SESSION).read_text())
        if s['status'] != 'open' or root_cause(s):
            return 0
        norm = '/' + path.replace(os.sep, '/')
        if f'/{DIR}/' in norm or any(m in norm for m in TEST_MARKERS):
            return 0
        n = len(s['claims'])
        checked = sum(c['status'] != 'claimed' for c in s['claims'])
        print(f"rubber-duck: source edits are blocked until a claim is refuted (session {s['id']}: "
              f'{n} claims, {checked} checked, none refuted). You have not located the bug yet. '
              'Narrate the next step of the execution path with `duck claim`, check it with `duck check`, '
              'and only edit once your explanation and the program disagree. Test files may be edited. '
              'If the method does not fit, run `duck abandon --reason ...`.', file=sys.stderr)
        return 2
    except Exception:
        return 0


# --- rendering ----------------------------------------------------------------

MARK = {'claimed': '?', 'verified': 'ok', 'refuted': 'XX'}


def claim(s, cid):
    return next(c for c in s['claims'] if c['id'] == cid)


def indent(t, p='    '):
    return '\n'.join(p + l for l in t.splitlines())


def explain(s, rc, evidence=False):
    out = [f"duck session {s['id']} [{s['status']}]",
           f"  expected: {s['expected']}", f"  actual:   {s['actual']}", f"  repro:    {s['repro']}", '']
    if not s['claims']:
        out.append('  (no claims yet: narrate the execution path from the entry point)')
    for c in s['claims']:
        tag = '  <- root cause' if c['id'] == rc else ''
        out.append(f"  [{MARK[c['status']]:>2}] {c['id']} {c['location']}: {c['statement']}{tag}")
        if evidence and c['evidence']:
            e = c['evidence'][-1]
            out.append(f"         $ {e['cmd']}  (exit {e['exit']}, expected {e['expect_exit']})")
    unchecked = [c['id'] for c in s['claims'] if c['status'] == 'claimed']
    out.append('')
    if s['status'] == 'closed':
        out.append(f"  closed: repro passes. Root cause: {rc or 'none recorded (forced)'}." + (f" Fix: {s['fix']}" if s.get('fix') else ''))
    elif s['status'] == 'abandoned':
        out.append(f"  abandoned: {s.get('reason', '')}")
    elif rc:
        out.append(f'  located: {rc}. Edits allowed.')
    elif unchecked:
        out.append(f"  next: check {unchecked[0]} (unchecked: {', '.join(unchecked)})")
    elif s['claims']:
        out.append('  every claim holds, yet the repro fails: the narration skipped a step. Add the missing claims between them.')
    return '\n'.join(out)


def main(argv=None):
    p = argparse.ArgumentParser(prog='duck', description='Rubber-duck debugging ledger for agents.')
    sub = p.add_subparsers(dest='command', required=True)
    s = sub.add_parser('start', help='open a session with a failing repro')
    s.add_argument('--expected', required=True)
    s.add_argument('--actual', required=True)
    s.add_argument('--repro', required=True, help='shell command that fails while the bug exists')
    s.add_argument('--no-run', action='store_true', help='do not run the repro now')
    s = sub.add_parser('claim', help='record the next step of the narration')
    s.add_argument('location', help='file:line or function')
    s.add_argument('statement', help='what the code does and what the state is there')
    s = sub.add_parser('check', help='verify a claim with a command')
    s.add_argument('id')
    s.add_argument('--cmd', required=True, help='command that exits with --expect-exit only if the claim is true')
    s.add_argument('--expect-exit', type=int, default=0)
    s = sub.add_parser('status')
    s.add_argument('--json', action='store_true')
    sub.add_parser('explain', help='print the narration with evidence')
    s = sub.add_parser('close', help='rerun the repro; closes only if it now passes')
    s.add_argument('--note', default='')
    s.add_argument('--force', action='store_true', help='close without a refuted claim')
    s = sub.add_parser('abandon')
    s.add_argument('--reason', required=True)
    sub.add_parser('hook', help='PreToolUse gate (reads hook JSON on stdin)')
    a = p.parse_args(argv)
    try:
        return globals()['cmd_' + a.command](a) or 0
    except DuckError as e:
        print(f'duck: {e}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
