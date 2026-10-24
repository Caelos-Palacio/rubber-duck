#!/usr/bin/env python3
# ---- suite kit (identical in every repo): 800x450, 15 fps, pure render(t) -> image ----
import os, sys, shutil, subprocess, tempfile, json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

W, H, FPS, S = 800, 450, 15, 2          # S = supersampling factor
BG, TEXT, MUTED = '#0d1117', '#e6edf3', '#8b949e'
ACCENT, OK, ERROR, WARN = '#58a6ff', '#3fb950', '#f85149', '#d29922'
FONT_DIRS = [Path.home() / '.local/share/fonts/JetBrainsMonoNerd']
FALLBACK = ['/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf']
FONT_FILES = {False: 'JetBrainsMonoNerdFont-Regular.ttf', True: 'JetBrainsMonoNerdFont-Bold.ttf'}


def rgb(h, a=1.0):
    h = h.lstrip('#')
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), round(255 * max(0, min(1, a))))


def clamp(x): return max(0.0, min(1.0, x))
def seg(t, a, b): return clamp((t - a) / (b - a))
def ease(x): x = clamp(x); return 4 * x ** 3 if x < .5 else 1 - (-2 * x + 2) ** 3 / 2   # cubic in-out
def lerp(a, b, k): return a + (b - a) * k
def typed(s, t, t0, cps=55): return s[:max(0, int((t - t0) * cps))]


_fonts = {}
def font(size, bold=False):
    key = (size, bold)
    if key not in _fonts:
        cands = [d / FONT_FILES[bold] for d in FONT_DIRS] + [Path(p) for p in FALLBACK]
        path = next(p for p in cands if p.exists())
        _fonts[key] = ImageFont.truetype(str(path), round(size * S))
    return _fonts[key]


class Cv:
    def __init__(self):
        self.img = Image.new('RGB', (W * S, H * S), BG)
        self.d = ImageDraw.Draw(self.img, 'RGBA')

    def text(self, x, y, s, size=13, color=TEXT, a=1.0, bold=False, anchor='la'):
        if a > .01 and s:
            self.d.text((x * S, y * S), s, font=font(size, bold), fill=rgb(color, a), anchor=anchor)

    def width(self, s, size=13, bold=False): return font(size, bold).getlength(s) / S

    def box(self, x0, y0, x1, y1, outline=MUTED, a=1.0, fill=None, fa=1.0, r=6, w=1):
        self.d.rounded_rectangle([x0 * S, y0 * S, x1 * S, y1 * S], radius=r * S,
                                 outline=rgb(outline, a), width=round(w * S),
                                 fill=rgb(fill, fa) if fill else None)

    def line(self, x0, y0, x1, y1, color=MUTED, a=1.0, w=1, dash=0):
        if not dash:
            self.d.line([x0 * S, y0 * S, x1 * S, y1 * S], fill=rgb(color, a), width=round(w * S))
            return
        n = int(max(abs(x1 - x0), abs(y1 - y0)) // dash)
        for i in range(0, n, 2):
            p, q = i / n, min(1, (i + 1) / n)
            self.d.line([lerp(x0, x1, p) * S, lerp(y0, y1, p) * S, lerp(x0, x1, q) * S, lerp(y0, y1, q) * S],
                        fill=rgb(color, a), width=round(w * S))

    def arrow(self, x0, y0, x1, y1, color=MUTED, a=1.0):
        self.line(x0, y0, x1, y1, color, a)
        s = 1 if x1 > x0 else -1
        self.d.polygon([(x1 * S, y1 * S), ((x1 - 7 * s) * S, (y1 - 4) * S), ((x1 - 7 * s) * S, (y1 + 4) * S)], fill=rgb(color, a))

    def dot(self, x, y, color=ACCENT, a=1.0, r=4.5):
        self.d.ellipse([(x - r) * S, (y - r) * S, (x + r) * S, (y + r) * S], fill=rgb(color, a))
        self.d.ellipse([(x - r * 2) * S, (y - r * 2) * S, (x + r * 2) * S, (y + r * 2) * S], fill=rgb(color, a * .16))


def envelope(t, T, fade=.5):
    """Loop envelope: blank at t=0 and t=T, so the GIF loops seamlessly."""
    return ease(seg(t, 0, fade)) * (1 - ease(seg(t, T - fade, T)))


def finish(cv, t, T):
    blank = Image.new('RGB', cv.img.size, BG)
    img = Image.blend(blank, cv.img, envelope(t, T))
    return img.resize((W, H), Image.LANCZOS)


def build(render, T, out, frame=None):
    if frame is not None:
        render(frame).save(out); return
    n = round(T * FPS)
    with tempfile.TemporaryDirectory() as tmp:
        for i in range(n):
            render(i / FPS).save(f'{tmp}/f{i:04d}.png')
        pal = f'{tmp}/pal.png'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-framerate', str(FPS), '-i', f'{tmp}/f%04d.png',
                        '-vf', 'palettegen=max_colors=128:stats_mode=full', pal], check=True)
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-framerate', str(FPS), '-i', f'{tmp}/f%04d.png', '-i', pal,
                        '-lavfi', 'paletteuse=dither=none', '-loop', '0', str(out)], check=True)
    print(f'{out}: {n} frames, {T}s, {Path(out).stat().st_size / 1e6:.2f} MB')


def cli(render, T, default_out):
    a = sys.argv[1:]
    if a[:1] == ['--frame']:          # python demo.py --frame 5.5 out.png
        build(render, T, a[2], float(a[1]))
    else:
        build(render, T, a[0] if a else default_out)
# ---- end kit ----

# ---- local helpers (per-demo) ----
HERE = Path(__file__).resolve().parent
PANEL, LINE = '#161b22', '#30363d'


def header(cv, title, subtitle):
    cv.text(32, 20, title, 22, ACCENT)
    cv.text(32, 52, subtitle, 13, MUTED)
    cv.line(32, 82, W - 32, 82, LINE)


def panel(cv, box, label, border=LINE, ba=1.0):
    x0, y0, x1, y1 = box
    cv.box(x0, y0, x1, y1, border, ba, fill=PANEL, r=8)
    cv.text(x0 + 14, y0 + 8, label, 11, MUTED)


def mono(cv, x, y, s, size, color, a=1.0, bold=False):
    """monospace text without programming ligatures"""
    if a <= .01 or not s:
        return
    try:
        cv.d.text((x * S, y * S), s, font=font(size, bold), fill=rgb(color, a), features=['-liga', '-calt'])
    except (KeyError, ValueError, OSError):
        cv.text(x, y, s, size, color, a, bold)


def fit(cv, s, px, size):
    """abridge with an ellipsis so s fits in px pixels"""
    if cv.width(s, size) <= px:
        return s
    while s and cv.width(s + '…', size) > px:
        s = s[:-1]
    return s.rstrip() + '…'


def wrap(s, cols):
    out, cur = [], ''
    for w in s.split(' '):
        if cur and len(cur) + 1 + len(w) > cols:
            out.append(cur); cur = w
        else:
            cur = (cur + ' ' + w).strip()
    return out + [cur]


def duck(cv, cx, cy, u=1.0):
    """tiny rubber duck from simple shapes"""
    def el(x0, y0, x1, y1, c):
        cv.d.ellipse([(cx + x0 * u) * S, (cy + y0 * u) * S, (cx + x1 * u) * S, (cy + y1 * u) * S], fill=rgb(c))
    el(-16, -2, 14, 16, WARN)                       # body
    el(2, -16, 18, 0, WARN)                         # head
    cv.d.polygon([((cx + 16 * u) * S, (cy - 10 * u) * S), ((cx + 26 * u) * S, (cy - 6 * u) * S),
                  ((cx + 16 * u) * S, (cy - 3 * u) * S)], fill=rgb('#e3722b'))   # beak
    el(9, -11, 12, -8, BG)                          # eye
    cv.d.arc([(cx - 14 * u) * S, (cy + 1 * u) * S, (cx + 2 * u) * S, (cy + 12 * u) * S], 200, 330,
             fill=rgb('#a87a14'), width=round(1.4 * S))   # wing


# ---------------------------------------------------------------------------
# rubber-duck demo.
#   python3 docs/media/demo.py capture   -> runs the REAL duck CLI in a temp git project, writes capture.json
#   python3 docs/media/demo.py [out.gif] -> renders docs/media/demo.gif from capture.json
#   python3 docs/media/demo.py --frame 5.5 out.png   (single frame)
# render(t) is a pure function of time; no randomness, no wall clock.
# ---------------------------------------------------------------------------
CAP = HERE / 'capture.json'
DUCK = HERE.parent.parent / 'skills' / 'rubber-duck' / 'scripts' / 'duck.py'
T = 12.8

CART = '''LOYALTY_MIN = 100


def subtotal(items):
    return sum(p * q for _, p, q in items)


def apply_discount(acc, pct):
    return round(acc * (1 - pct / 100), 2)


def total(items, coupon=None):
    acc = subtotal(items)
    if coupon:
        acc = apply_discount(acc, coupon["pct"])
    if acc > LOYALTY_MIN:
        acc *= 0.95
    return round(acc, 2)
'''
TEST = '''from cart import total

got = total([("chair", 110, 1)], {"pct": 10})
assert got == 94.05, f"expected 94.05, got {got}"
'''
CHAIR = "[('chair',110,1)]"
CLAIMS = [  # (location, statement, check command)
    ('cart.py:10', 'subtotal of the chair order is 110',
     f'python3 -c "import cart; assert cart.subtotal({CHAIR})==110"'),
    ('cart.py:12', 'the coupon is applied first: 110 -> 99.0',
     'python3 -c "import cart; assert cart.apply_discount(110,10)==99.0"'),
    ('cart.py:1', 'the loyalty threshold is 100',
     'python3 -c "import cart; assert cart.LOYALTY_MIN==100"'),
    ('cart.py:13', 'loyalty sees 99.0, and 99.0 > 100 is False',
     f'python3 -c "import cart; assert cart.total({CHAIR},{{\'pct\':10}})==99.0"'),
    ('cart.py:13', 'without a coupon, 110 > 100 gives 104.5',
     f'python3 -c "import cart; assert cart.total({CHAIR})==104.5"'),
    ('cart.py:13', 'loyalty is decided on the original 110',
     f'python3 -c "import cart; assert cart.total({CHAIR},{{\'pct\':10}})==94.05"'),
]
HOOK_IN = {'tool_name': 'Edit', 'tool_input': {'file_path': 'cart.py', 'old_string': 'x', 'new_string': 'y'}}


def capture():
    root = Path(tempfile.mkdtemp(prefix='duck-demo-'))
    try:
        (root / 'cart.py').write_text(CART)
        (root / 'test_cart.py').write_text(TEST)
        g = ['git', '-c', 'user.name=demo', '-c', 'user.email=demo@example.com']
        subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
        subprocess.run(['git', 'add', '.'], cwd=root, check=True)
        subprocess.run([*g, 'commit', '-qm', 'cart'], cwd=root, check=True)
        steps = []

        def duck_run(label, args, shown, stdin=None):
            r = subprocess.run([sys.executable, str(DUCK), *args], cwd=root, capture_output=True, text=True, input=stdin)
            out = (r.stdout + r.stderr).replace(str(root), '…').rstrip('\n')
            steps.append({'id': label, 'cmd': shown, 'out': out.split('\n'), 'rc': r.returncode})
            return r

        duck_run('start', ['start', '--expected', 'total([chair 110],{pct 10}) == 94.05', '--actual', 'assertion fails',
                           '--repro', 'python3 test_cart.py'],
                 'duck start --expected … --actual … --repro "python3 test_cart.py"')
        for i, (loc, st, cmd) in enumerate(CLAIMS, 1):
            duck_run(f'claim{i}', ['claim', loc, st], f'duck claim {loc} "{st}"')
        for i, (loc, st, cmd) in enumerate(CLAIMS, 1):
            if i == 6:
                break
            duck_run(f'check{i}', ['check', f'c{i}', '--cmd', cmd], f"duck check c{i} --cmd '{cmd}'")
        # an agent tries to edit source before any claim is refuted: the real hook decides
        payload = json.dumps({**HOOK_IN, 'cwd': str(root)})
        duck_run('hook', ['hook'], 'echo \'{"tool_name":"Edit","tool_input":{"file_path":"cart.py",…}}\' | duck hook',
                 stdin=payload)
        cmd = CLAIMS[5][2]
        duck_run('check6', ['check', 'c6', '--cmd', cmd], f"duck check c6 --cmd '{cmd}'")
        # the located bug: the loyalty check must use the original subtotal
        src = (root / 'cart.py').read_text()
        src = src.replace('    acc = subtotal(items)\n', '    acc = subtotal(items)\n    base = acc\n')
        src = src.replace('if acc > LOYALTY_MIN', 'if base > LOYALTY_MIN')
        (root / 'cart.py').write_text(src)
        r = subprocess.run(['git', 'diff', '-U0', 'cart.py'], cwd=root, capture_output=True, text=True)
        steps.append({'id': 'diff', 'cmd': 'git diff -U0 cart.py', 'out': r.stdout.rstrip('\n').split('\n'), 'rc': r.returncode})
        duck_run('close', ['close', '--note', 'loyalty is decided on the original subtotal'],
                 'duck close --note "loyalty is decided on the original subtotal"')
    finally:
        shutil.rmtree(root, ignore_errors=True)
    CAP.write_text(json.dumps({'claims': [{'id': f'c{i}', 'loc': c[0], 'st': c[1]} for i, c in enumerate(CLAIMS, 1)],
                               'steps': steps}, indent=2, ensure_ascii=False) + '\n')


# ---- schedule: (start time, typing seconds) per step; output lands right after typing ----
SCHED = {'start': (0.5, 0.7)}
for _i in range(6):
    SCHED[f'claim{_i + 1}'] = (1.8 + 0.34 * _i, 0.2)
for _i in range(5):
    SCHED[f'check{_i + 1}'] = (4.0 + 0.4 * _i, 0.25)
SCHED.update(hook=(6.1, 0.55), check6=(7.7, 0.3), diff=(9.0, 0.3), close=(9.9, 0.45))
GAP = 0.12            # pause between end of typing and output
BLOCK = (6.8, 7.7)    # window where the hook's refusal is highlighted


def out_time(step_id):
    t0, d = SCHED[step_id]
    return t0 + d + GAP


def shown_lines(cv, step, px):
    """(text, color) lines picked from the captured output; long lines are abridged with an ellipsis"""
    sid, out = step['id'], [l for l in step['out'] if l.strip()]
    res = []
    if sid == 'start':
        res = [(out[0], MUTED), (out[1], MUTED), ('    …', MUTED), (next(l for l in out if 'AssertionError' in l), ERROR)]
    elif sid.startswith('claim'):
        res = [(out[0], TEXT)]
    elif sid.startswith('check'):
        bad = 'REFUTED' in out[0]
        res = [(out[0], ERROR if bad else OK)]
        if bad:
            res += [(next(l for l in out if l.startswith('First refuted')), WARN)]
    elif sid == 'hook':
        msg = out[0]
        first, rest = msg.split('). ', 1)[0] + ').', msg.split('). ', 1)[1]
        res = [(l, ERROR) for l in wrap(first, 98)] + [(rest, MUTED), (f"[exit {step['rc']}]", MUTED)]
    elif sid == 'diff':
        for l in out:
            if l.startswith(('+++', '---', '@@')) or not l.startswith(('+', '-')):
                continue
            res.append((l, OK if l[0] == '+' else ERROR))
    elif sid == 'close':
        res = [(out[0], OK), (f"[exit {step['rc']}]", MUTED)]
    return [(fit(cv, s, px, 11), c) for s, c in res]


def transcript(cv, cap, px):
    rows = []   # (t, text segs, type_dur)
    for st in cap['steps']:
        t0, d = SCHED[st['id']]
        rows.append((t0, [('$ ', OK), (fit(cv, st['cmd'], px - 14, 11), TEXT)], d))
        for text, c in shown_lines(cv, st, px):
            rows.append((out_time(st['id']), [(text, c)], 0))
    return rows


def ledger_state(cap, t):
    """per-claim (visible, mark, color, t_changed) at time t, from the captured verdicts"""
    res = []
    for c in cap['claims']:
        i = int(c['id'][1:])
        vis = t >= out_time(f'claim{i}')
        verdict = next(s for s in cap['steps'] if s['id'] == f'check{i}')['out'][0] if i <= 6 else ''
        done = t >= out_time(f'check{i}')
        if done and 'REFUTED' in verdict: mark, col = 'XX', ERROR
        elif done and 'VERIFIED' in verdict: mark, col = 'ok', OK
        else: mark, col = '?', MUTED
        res.append((vis, mark, col, out_time(f'check{i}') if done else out_time(f'claim{i}')))
    return res


def render(t, cap=None):
    cap = cap or json.loads(CAP.read_text())
    cv = Cv()
    header(cv, 'rubber-duck', 'the agent explains the code as claims; a hook blocks edits until one is refuted')
    duck(cv, W - 58, 40, 1.15)
    # terminal -------------------------------------------------------------
    blk = ease(seg(t, BLOCK[0], BLOCK[0] + .2)) * (1 - ease(seg(t, BLOCK[1] - .4, BLOCK[1])))
    panel(cv, (32, 96, 768, 252), 'terminal   output captured from the real duck CLI',
          border=ERROR if blk > .01 else LINE, ba=1.0 if blk > .01 else 1.0)
    if blk > .01:
        cv.d.rounded_rectangle([32 * S, 96 * S, 768 * S, 252 * S], radius=8 * S, fill=rgb(ERROR, .10 * blk),
                               outline=rgb(ERROR, blk), width=round(2 * S))
        cv.text(754, 104, 'BLOCKED', 12, ERROR, a=blk, bold=True, anchor='ra')
    rows = transcript(cv, cap, 708)
    vis = [r for r in rows if t >= r[0]][-8:]
    for k, (t0, segs, d) in enumerate(vis):
        y, x = 118 + 16 * k, 46
        n = sum(len(s) for s, _ in segs)
        shown = n if d == 0 else min(n, int((t - t0) / d * n))
        left = shown
        for s, c in segs:
            part = s[:max(0, left)]
            mono(cv, x, y, part, 11, c)
            x += cv.width(part, 11)
            left -= len(s)
        if d and (t - t0) < d + GAP:
            cv.d.rectangle([(x + 1) * S, (y + 1) * S, (x + 7) * S, (y + 14) * S], fill=rgb(TEXT, .8))
    # ledger ---------------------------------------------------------------
    closed = t >= out_time('close')
    located = t >= out_time('check6')
    status, scol = (('closed: repro passes', OK) if closed else (('root cause located: c6', WARN) if located else ('open', MUTED)))
    panel(cv, (32, 264, 768, 412), 'ledger', border=OK if closed else LINE)
    cv.text(754, 272, status, 11, scol, anchor='ra')
    for k, (c, (vis_, mark, col, tc)) in enumerate(zip(cap['claims'], ledger_state(cap, t))):
        if not vis_:
            continue
        a = ease(seg(t, out_time(f'claim{k + 1}'), out_time(f'claim{k + 1}') + .2))
        y = 292 + 19 * k
        fl = 1 - seg(t, tc, tc + .4) if mark != '?' else 0
        if fl > 0:
            cv.d.rounded_rectangle([42 * S, (y - 3) * S, 758 * S, (y + 15) * S], radius=4 * S, fill=rgb(col, .16 * fl))
        mono(cv, 52, y, f'[{mark:>2}]', 12, col, a, bold=mark != '?')
        mono(cv, 100, y, c['id'], 12, TEXT, a)
        mono(cv, 128, y, c['loc'].ljust(11), 12, MUTED, a)
        mono(cv, 232, y, c['st'], 12, TEXT, a)
        if mark == 'XX':
            mono(cv, 232 + cv.width(c['st'], 12) + 12, y, '← root cause', 12, ERROR, a, bold=True)
    cv.text(32, 424, 'zero dependencies  |  Python >= 3.9  |  edits stay blocked until a claim is refuted', 12, MUTED)
    return finish(cv, t, T)


if __name__ == '__main__':
    if sys.argv[1:2] == ['capture']:
        capture()
    else:
        cli(render, T, HERE / 'demo.gif')
