---
name: editor-lock
description: Share one Unity editor safely between the user and several Claude sessions — see who holds the editor (playing, compiling, a claimed batch job), claim it for long work and release it, understand why the unity-workflow hook refused a compile or play call, free a stale lock with the user's OK, and set Unity so saving scripts never reloads a running game. Use when a Unity MCP call was refused by the editor guard, when the user asks "is anyone using Unity?", "who has the editor?", before long editor work (batch edits, bake, bot runs), or when several Claude sessions work on the same Unity project.
---

# Editor lock

One Unity editor, several workers. Recompiling or stopping play under someone else's session breaks it: statics
reset, references go null, a bot run or the user's own test dies mid-way. The unity-workflow **editor guard**
(a PreToolUse hook on Unity MCP tools) prevents that.

## How it decides

The Unity package's beacon writes `Temp/UnityWorkflow/editor-state.json` (playing, paused, compiling, who started
play, a heartbeat). The guard keeps `Temp/UnityWorkflow/editor-lock.json` (which Claude session holds the editor,
why, until when). For each Unity MCP call:

| the call | another session holds the lock | editor playing, no Claude lock (the user) | free |
|---|---|---|---|
| read (console, find, reflect, test status) | allowed | allowed | allowed |
| scene/asset edits, other execute_code | allowed + warning | allowed + warning | allowed |
| recompile (refresh, script tools, EditMode tests, packages) | **refused** | **refused** | allowed |
| enter play (PlaySession.Play, EnterPlaymode, manage_editor play, PlayMode tests) | **refused** | **refused** | allowed, **takes the lock** |
| stop/pause play, load/save scenes | **refused** | **refused** | allowed |

- A play lock frees itself when that play session ends (or if play never started), and expires after
  `editorLock.playLockMinutes` (default 45) without activity; every call by the holder renews it.
- Saving `.cs`/`.asmdef` files while someone else holds the editor or the user is playing: allowed, with a warning
  (Unity recompiles on its next refresh).
- No beacon (package not installed, Unity closed, busy or behind a modal dialog): the lock still protects Claude
  sessions from each other, but the guard can't see the user playing, and says so.

## Claim the editor for long work (not play)

A batch edit, a bake or a long import that must not be interrupted by another session's compile:
```csharp
// unity-workflow:claim 30 batch-fixing 120 room prefabs
return "claimed";
```
(an `execute_code` call; the minutes and reason after the marker are optional; at most 120). Release it when done:
```csharp
// unity-workflow:release
return "released";
```

## When a call is refused

- **Another session holds it:** wait. If you're a Claude session, ask the user; don't poll in a tight loop. Use a
  cross-session "notify when idle" if your harness has one, or check every few minutes.
- **The user is playing:** ask the user. Never stop their play session.
- **The lock looks stale** (the holder is gone): `python <plugin>/hooks/editor_lock.py status` shows holder, reason
  and time left (`<plugin>` = two folders up from this skill's base directory). Free it only with the user's OK:
  `python <plugin>/hooks/editor_lock.py release --force`. Use `python3` on macOS/Linux.

## Make script saves safe during play (recommend once per machine)

Unity's default *Preferences ▸ General ▸ Script Changes While Playing* is **Recompile And Continue Playing**, so any
script saved while someone plays (by another session, or the user's IDE) reloads the running game. Recommend
**Recompile After Finished Playing**. It's a per-user editor preference, so change it only with the user's OK:
```csharp
UnityEditor.EditorPrefs.SetInt("ScriptCompilationDuringPlay", 1); return "ok";
```
`editor_lock.py status` reports the current setting.

## Configure (`.claude/unity-workflow.json`, optional)

```json
"editorLock": {
  "playLockMinutes": 45,
  "playStartPatterns": ["MyBot\\.StartRun\\("],
  "playStopPatterns": ["MyBot\\.Stop\\("],
  "reloadPatterns": []
}
```
Add a pattern for each project-specific way of entering play or recompiling that `execute_code` uses (bot launchers,
build helpers). The guard recognises Unity's own calls and the unity-workflow ones already.
