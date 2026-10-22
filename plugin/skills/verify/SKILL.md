---
name: verify
description: Check a code or content change to a Unity project is safe before it is committed or called done — compile and console, the EditMode (and relevant PlayMode) tests, release AND development player script compiles (catches broken #if UNITY_EDITOR / DEVELOPMENT_BUILD code the editor never compiles), and the project's own automated play-through if it has one — then a short pass/fail report. Use whenever the user asks to verify, check, test or validate a change, asks "is this safe to commit/ship?", before committing scripts, and after refactors or batch edits.
---

# Verify

Cheapest check first; stop at the first hard failure, fix it, start again from the top. Uses Unity MCP
(`mcp__UnityMCP__*`). Unity must be **focused** for compiles, tests and play to progress (an unfocused editor barely
ticks): `sh <plugin>/skills/playtest/scripts/unity_window.sh focus` when calls time out (`<plugin>` = two folders up
from this skill's base directory). **Never compile or enter play while the editor is playing someone else's
session**: the editor-lock hook refuses it; wait or ask the user (`/unity-workflow:editor-lock`).

## 1. Compile and console

- `refresh_unity` with `compile: request`, `wait_for_ready: true`.
- `execute_code` → `return UnityEditor.EditorApplication.isCompiling.ToString();` must be `False`.
- `read_console` types `error` (and `warning` for new code). MCP connection lines are the bridge, not the game.

## 2. Tests

- `run_tests` mode `EditMode` with `include_failed_tests: true`, then `get_test_job` (`wait_timeout: 60`) until done.
  "Tests did not start" usually means Unity was in the background: focus it and rerun.
- PlayMode tests that cover the touched area (`run_tests` mode `PlayMode`, a longer `init_timeout`).
- Any failure is a finding: say whether the change or the test is wrong. Never weaken a test to pass.

## 3. Player script compiles

```csharp
return "release: " + UnityWorkflow.Editor.BuildChecks.PlayerCompile(false) + "\ndevelopment: " + UnityWorkflow.Editor.BuildChecks.PlayerCompile(true);
```
Both must say `ok`. (Needs the unity-workflow package: `/unity-workflow:setup`.) Takes 10–60 s each.

## 4. Play-through (for anything that touches play)

If `.claude/unity-workflow.json` has `verify.botRun` (or CLAUDE.md names a bot/autopilot), run it, wait for its
report — poll its own "finished" state, not just a report file's timestamp (many recorders rewrite their report
during the run) — then stop play and read the report: deaths, soft locks, errors. Errors in the console during the
run count as a failure. No bot: say so, and for gameplay changes use `/unity-workflow:playtest` to play and look
instead. Keep Unity in front during long runs (`unity_window.sh keep <minutes>`, in the background).

## Report

```
Verify: PASS / FAIL
- Compile: clean
- Tests: EditMode 81/81, PlayMode ClassSmoke 4/4
- Player compiles: release ok, development ok
- Play-through: 14 rooms, 0 deaths, no errors   (or: skipped — no bot; looked at it in play instead)
```
Never claim a check passed if it was skipped or cut short; say which and why.
