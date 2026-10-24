---
name: rubber-duck
description: Debug like a programmer explaining code to a rubber duck - reproduce the bug, narrate the execution path line by line as explicit claims, check each claim with a command, and fix only where a claim turns out false. Use when a bug is not obvious after one look, after a fix attempt failed, when you notice yourself guessing ("probably", "should work"), or when the user asks for rubber-duck debugging.
---

# Rubber-duck debugging

You are the programmer. The duck knows nothing: not the codebase, not the language, not what you "obviously" meant. You explain the code to it, step by step, in the order the program actually runs. The bug is the first place where your explanation and the program disagree.

Guessing fixes skips the explanation, which is the step that finds bugs. So this skill has one hard rule:

> **Do not edit source code until one of your claims has been refuted by evidence.**

A `PreToolUse` hook enforces it while a session is open: edits to non-test files are blocked until a claim is refuted. Test files and `.duck/` stay editable.

The ledger tool is `scripts/duck.py` in this skill's directory (Python 3.9+, standard library only). Below, `duck` means `python3 <this skill's dir>/scripts/duck.py`. Run it from inside the project.

## 1. Reproduce

State the bug as expected vs actual, with a command that **fails while the bug exists** (a failing test, a script with an `assert`, a curl piped to a check). Write a failing test if none exists; test files are editable.

```sh
duck start --expected "total() returns 30 for [10, 20]" \
           --actual   "returns 20" \
           --repro    "python -m pytest tests/test_cart.py::test_total -q"
```

`start` runs the repro and refuses if it passes. A bug you cannot reproduce is not located yet.

## 2. Narrate to the duck

Walk the execution path from the entry point toward the failure. For each step that matters, record one claim: where, what the code does, and what the state is there. Be literal: concrete values, types, which branch is taken, how many iterations.

```sh
duck claim tests/test_cart.py:8   "test calls total([10, 20]) on a fresh Cart"
duck claim cart.py:14             "total() starts acc at 0"
duck claim cart.py:15             "the loop visits both items, 10 then 20"
duck claim cart.py:16             "acc is 30 after the loop"
```

Rules for a good narration:
- **One step per claim**, in execution order. The order matters: the root cause is the *first* refuted claim on the path.
- **No hedging.** "Probably", "should", "I think" are not claims. If you are unsure, that is exactly the claim to write and check.
- **Say what you skip.** "Lines 20-40 only log" is a claim too.
- **Read the code before claiming about it.** Narrate the code as written, not as intended.

## 3. Check claims with evidence

Check each claim with a command that exits 0 **only if the claim is true** (or pass `--expect-exit N`). Go along the path, cheapest checks first. Good evidence: `python -c` / `node -e` snippets importing the real code, a targeted test, a debugger one-liner, `grep` for a definition, reading a value from a log. Do not add prints to source to check; use a scratch script or a test instead.

```sh
duck check c3 --cmd "python -c 'import cart; c=cart.Cart(); seen=[]; ...; assert seen==[10,20], seen'"
```

`check` records the command, exit code and output tail, and marks the claim `verified` or `refuted`.

- **A claim is refuted:** this is where your mental model of the program is wrong. Before touching code, say *why* the claim was false. That sentence is the bug. Edits are now allowed.
- **Every claim holds but the repro still fails:** your narration skipped a step. Add claims between the last verified one and the failure, and check them.
- `duck status` shows the narration and the next claim to check. `duck explain` adds the evidence.

## 4. Fix and close

Make the smallest fix that addresses the refuted claim. Then:

```sh
duck close --note "loop started at index 1; changed range(1, n) to range(n)"
```

`close` reruns the repro and only closes the session if it now passes. If it still fails, the session stays open: the refuted claim was real but not the whole story. Continue narrating from there.

If the method genuinely does not fit (the bug is in the environment, or the user asks you to stop), run `duck abandon --reason "..."` and say so.

## 5. Report

Show the user the output of `duck explain`, then answer in plain words:
- where the explanation and the program disagreed (the refuted claim),
- why, which is the bug,
- the fix,
- the evidence that the repro now passes.

## Notes

- The ledger lives in `.duck/` at the git root (self-ignored via its own `.gitignore`): `session.json` holds the current session and `ledger.jsonl` the append-only history.
- One open session per project. Close or abandon before starting the next bug.
- The duck is deterministic: verdicts come from exit codes, not from the model's opinion of its own claims.
