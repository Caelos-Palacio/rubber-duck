# rubber-duck

**Rubber-duck debugging for coding agents.** The agent explains the code to a duck, one step at a time, as claims it then checks with commands. It may only edit source after a claim is refuted, and a hook enforces that.

Zero dependencies (Python 3.9+ standard library). A Claude Code plugin: one skill, one hook, one ledger script.

## Why

Agents that hit a bug tend to guess: change something plausible, rerun, change something else. Each attempt skips the step that actually finds bugs, which is explaining what the code does and noticing where that explanation is wrong.

Programmers have a name for forcing that step: explain the code, line by line, to a rubber duck. This plugin makes the agent do it, and makes the result checkable:

1. **Reproduce.** `duck start` takes expected vs actual and a repro command, and refuses if the repro passes.
2. **Narrate.** The agent walks the execution path in order, recording one `duck claim` per step ("`cart.py:10` the loyalty check sees the original subtotal, 110").
3. **Check.** Each claim gets a command that exits 0 only if it is true. Verdicts come from exit codes, not from the model's opinion of itself.
4. **Locate.** The **first refuted claim** on the path is where the agent's model of the program is wrong. That is the bug. Until one exists, a `PreToolUse` hook blocks edits to non-test files.
5. **Close.** `duck close` reruns the repro and only closes the session if it passes.

## Example

The unedited `duck explain` from a real headless run (Claude Sonnet with only this plugin), on a cart where a coupon was applied before the "over 100" loyalty check:

```text
duck session 20261024-014603 [closed]
  expected: total([('chair',110,1)],{'pct':10}) == 94.05 (loyalty on original subtotal)
  actual:   assertion fails in test_cart.py
  repro:    python3 test_cart.py

  [ok] c1 test_cart.py:3: case 1: subtotal 80, coupon 10 gives 72, no loyalty
         $ python3 -c 'import cart; assert cart.total([("mug",40,2)],{"pct":10})==72'  (exit 0, expected 0)
  [ ?] c2 cart.py:7: acc is the subtotal 110 for the chair case
  [ok] c3 cart.py:9: coupon applied first: acc becomes 99.0
         $ python3 -c 'import cart; assert cart.apply_discount(110,10)==99.0'  (exit 0, expected 0)
  [ok] c4 cart.py:10: loyalty check uses the post-coupon acc (99), so 99 > 100 is False and loyalty is skipped
         $ python3 -c 'import cart; assert cart.total([("chair",110,1)],{"pct":10})==94.05'  (exit 1, expected 1)
  [ok] c5 cart.py:12: result is 99.0, but test expects 94.05
         $ python3 -c 'import cart; assert cart.total([("chair",110,1)],{"pct":10})==99.0'  (exit 0, expected 0)
  [XX] c6 cart.py:10: the loyalty check is made on the original subtotal (110 > 100), so the 5% discount is applied for the chair case  <- root cause
         $ python3 -c 'import cart; assert cart.total([("chair",110,1)])==104.5 and cart.total([("chair",110,1)],{"pct":10})==94.05'  (exit 1, expected 0)

  closed: repro passes. Root cause: c6. Fix: loyalty check ran after the coupon on the reduced total; moved loyalty before the coupon so it is decided on the original subtotal
```

Claims c3 to c5 narrate what the code does and hold. c6 states what the code must do for the test's contract, and its check fails: the loyalty threshold is evaluated after the coupon, not on the original subtotal. The agent moved the loyalty block before the coupon, and `duck close` reran the repro, which passed. (`c2` was never checked; the ledger keeps that visible instead of hiding it.)

Before that claim was refuted, a direct `Edit` of `cart.py` was blocked with:

```text
rubber-duck: source edits are blocked until a claim is refuted (session ...: 0 claims, 0 checked,
none refuted). You have not located the bug yet. Narrate the next step of the execution path with
`duck claim`, check it with `duck check`, and only edit once your explanation and the program disagree.
```

## Install

In Claude Code:

```text
/plugin marketplace add Caelos-Palacio/rubber-duck
/plugin install rubber-duck@rubber-duck
```

Or try it from a local clone without installing:

```sh
git clone https://github.com/Caelos-Palacio/rubber-duck
claude --plugin-dir ./rubber-duck
```

Then ask for it ("use rubber-duck debugging on this failing test"), or let the skill trigger when a bug is not obvious or a fix attempt has failed.

## The `duck` ledger

The script lives at `skills/rubber-duck/scripts/duck.py` and works without Claude Code too:

| command | what it does |
|---|---|
| `duck start --expected E --actual A --repro CMD` | open a session; runs `CMD` and refuses if it exits 0 (`--no-run` skips this) |
| `duck claim LOCATION "STATEMENT"` | record the next step of the narration (`c1`, `c2`, ...) |
| `duck check ID --cmd CMD [--expect-exit N]` | run `CMD`; the claim is `verified` if it exits `N` (default 0), else `refuted` |
| `duck status [--json]` | narration, root cause if any, next claim to check |
| `duck explain` | narration with the evidence command for each claim |
| `duck close [--note TEXT]` | rerun the repro; closes only if it passes and a claim was refuted (`--force` skips the latter) |
| `duck abandon --reason TEXT` | give up explicitly; edits are unblocked |
| `duck hook` | the `PreToolUse` gate (reads hook JSON on stdin) |

State lives in `.duck/` at the git root: `session.json` for the open session and `ledger.jsonl` as an append-only history. The directory ignores itself in git.

If every claim is verified and the repro still fails, `duck status` says so: the narration skipped a step, and the agent adds claims between the last verified one and the failure.

## Limits

- The gate blocks the `Edit`, `Write`, `MultiEdit` and `NotebookEdit` tools. An agent can still change files through the shell. The hook enforces the method; it is not a sandbox.
- Test files are always editable (paths with `test_`, `_test.`, `.test.`, `.spec.`, `/test/`, `/tests/`, `/spec/`, `__tests__`, `conftest.py`), so the agent can write the failing test first.
- A claim is only as good as its check. A weak command can "verify" a false claim. `duck explain` shows every command so a reviewer can judge.
- The hook fails open: if it cannot read its input or the session, the edit goes through.
- One open session per repository.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

## License

[MIT](LICENSE)
