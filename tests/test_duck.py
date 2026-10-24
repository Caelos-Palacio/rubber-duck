import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

DUCK = Path(__file__).resolve().parents[1] / 'skills' / 'rubber-duck' / 'scripts' / 'duck.py'
BUGGY = 'def total(xs):\n    acc = 0\n    for i in range(1, len(xs)):\n        acc += xs[i]\n    return acc\n'
FIXED = BUGGY.replace('range(1, len(xs))', 'range(len(xs))')
REPRO = f'{sys.executable} -c "import cart; assert cart.total([10, 20]) == 30"'


def duck(cwd, *args, stdin=None):
    return subprocess.run([sys.executable, str(DUCK), *args], cwd=cwd, input=stdin,
                          capture_output=True, text=True)


class Base(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        (self.root / 'cart.py').write_text(BUGGY)
        (self.root / 'pkg').mkdir()

    def tearDown(self):
        shutil.rmtree(self.root)

    def start(self, repro=REPRO):
        return duck(self.root, 'start', '--expected', 'total([10,20]) == 30', '--actual', '20', '--repro', repro)

    def session(self):
        return json.loads((self.root / '.duck' / 'session.json').read_text())

    def hook(self, path, tool='Edit', cwd=None):
        payload = json.dumps({'tool_name': tool, 'cwd': str(cwd or self.root),
                              'tool_input': {'file_path': str(self.root / path)}})
        return duck(self.root, 'hook', stdin=payload)


class Start(Base):
    def test_refuses_repro_that_passes(self):
        r = self.start(f'{sys.executable} -c "pass"')
        self.assertEqual(r.returncode, 1)
        self.assertIn('does not reproduce', r.stderr)
        self.assertFalse((self.root / '.duck' / 'session.json').exists())

    def test_opens_at_git_root_from_subdir(self):
        r = duck(self.root / 'pkg', 'start', '--expected', 'e', '--actual', 'a', '--repro', REPRO)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.root / '.duck' / 'session.json').is_file())
        self.assertEqual((self.root / '.duck' / '.gitignore').read_text(), '*\n')

    def test_one_open_session_at_a_time(self):
        self.start()
        r = self.start()
        self.assertEqual(r.returncode, 1)
        self.assertIn('still open', r.stderr)


class Method(Base):
    def test_full_walkthrough(self):
        self.assertEqual(self.start().returncode, 0)
        duck(self.root, 'claim', 'cart.py:2', 'acc starts at 0')
        duck(self.root, 'claim', 'cart.py:3', 'the loop visits both items')
        duck(self.root, 'claim', 'cart.py:5', 'returns 30')

        r = duck(self.root, 'check', 'c1', '--cmd', f'{sys.executable} -c "import cart; assert cart.total([]) == 0"')
        self.assertIn('VERIFIED', r.stdout)
        self.assertEqual(self.hook('cart.py').returncode, 2, 'edits blocked before any refutation')

        visits = 'import cart; assert len(range(1, len([10, 20]))) == 2'
        r = duck(self.root, 'check', 'c2', '--cmd', f'{sys.executable} -c "{visits}"')
        self.assertIn('REFUTED', r.stdout)
        self.assertIn('First refuted claim: c2', r.stdout)
        self.assertEqual(self.hook('cart.py').returncode, 0, 'edits allowed once located')

        r = duck(self.root, 'close')
        self.assertEqual(r.returncode, 1, 'repro still fails before the fix')
        self.assertEqual(self.session()['status'], 'open')

        (self.root / 'cart.py').write_text(FIXED)
        r = duck(self.root, 'close', '--note', 'loop started at 1')
        self.assertEqual(r.returncode, 0, r.stderr)
        s = self.session()
        self.assertEqual((s['status'], s['root_cause']), ('closed', 'c2'))
        events = [json.loads(l)['event'] for l in (self.root / '.duck' / 'ledger.jsonl').read_text().splitlines()]
        self.assertEqual(events, ['start', 'claim', 'claim', 'claim', 'check', 'check', 'close_failed', 'close'])

    def test_root_cause_is_first_refuted_in_narration_order(self):
        self.start()
        duck(self.root, 'claim', 'a', 'x')
        duck(self.root, 'claim', 'b', 'y')
        duck(self.root, 'check', 'c2', '--cmd', 'false')
        duck(self.root, 'check', 'c1', '--cmd', 'false')
        st = json.loads(duck(self.root, 'status', '--json').stdout)
        self.assertEqual(st['root_cause'], 'c1')

    def test_expect_exit(self):
        self.start()
        duck(self.root, 'claim', 'a', 'grep finds nothing')
        r = duck(self.root, 'check', 'c1', '--cmd', 'false', '--expect-exit', '1')
        self.assertIn('VERIFIED', r.stdout)

    def test_close_requires_located_bug(self):
        self.start()
        (self.root / 'cart.py').write_text(FIXED)
        r = duck(self.root, 'close')
        self.assertEqual(r.returncode, 1)
        self.assertIn('not located', r.stderr)
        self.assertEqual(duck(self.root, 'close', '--force').returncode, 0)

    def test_all_verified_hints_missing_step(self):
        self.start()
        duck(self.root, 'claim', 'a', 'x')
        duck(self.root, 'check', 'c1', '--cmd', 'true')
        self.assertIn('skipped a step', duck(self.root, 'status').stdout)

    def test_abandon_unblocks_edits(self):
        self.start()
        self.assertEqual(self.hook('cart.py').returncode, 2)
        duck(self.root, 'abandon', '--reason', 'environment issue')
        self.assertEqual(self.hook('cart.py').returncode, 0)


class Hook(Base):
    def test_no_session_allows(self):
        self.assertEqual(self.hook('cart.py').returncode, 0)

    def test_test_files_and_non_edit_tools_allowed(self):
        self.start()
        for p in ('tests/test_cart.py', 'cart_test.go', 'src/cart.test.ts', 'conftest.py', '.duck/notes.md'):
            self.assertEqual(self.hook(p).returncode, 0, p)
        self.assertEqual(self.hook('cart.py', tool='Read').returncode, 0)

    def test_blocks_write_and_explains(self):
        self.start()
        r = self.hook('cart.py', tool='Write')
        self.assertEqual(r.returncode, 2)
        self.assertIn('duck claim', r.stderr)

    def test_fails_open_on_garbage(self):
        self.start()
        self.assertEqual(duck(self.root, 'hook', stdin='not json').returncode, 0)


if __name__ == '__main__':
    unittest.main()
