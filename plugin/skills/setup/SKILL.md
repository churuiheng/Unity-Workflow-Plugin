---
name: setup
description: Set up unity-workflow in a Unity project — copy its small Unity package (editor-state beacon, play sessions with save protection, playtest steps, perf probe, player-compile checks) into Packages/, write .claude/unity-workflow.json from what the project already uses (code layout, helpers, generated folders, start scene, save files), scaffold playtest steps, recommend safe Unity settings, offer a starter CLAUDE.md, and check the hooks fire. Use when the user says "set up unity-workflow", "install the unity workflow", "configure the guard rails", or when another unity-workflow skill finds the package or config missing or outdated.
---

# Set up unity-workflow

Read the project before writing anything: every value in the config should come from code that exists. Ask only
what the code can't tell you. Show the user the config before saving it. Paths below: `<plugin>` = two folders up
from this skill's base directory.

## 1. Find the Unity project

The folder with both `Assets/` and `ProjectSettings/` (may be a subfolder of the git repo). Note the Unity version
(`ProjectSettings/ProjectVersion.txt`; 2022.3+ needed). Unity MCP (`mcp__UnityMCP__*`, the CoplayDev "MCP for Unity"
package) is needed for playtest, verify and perf-check; say so if it isn't connected.

## 2. Install or update the Unity package

Copy `<plugin>/unity-package/com.ruiheng.unity-workflow/` to `<project>/Packages/com.ruiheng.unity-workflow/` (an
embedded package: Unity imports it and makes the `.meta` files).
- Already there: compare `version` in both `package.json` files. Older → show what changed (the plugin's README
  changelog) and update with the user's OK, keeping the project's `.meta` files.
- **Never trigger a compile while the editor is playing** (`EditorApplication.isPlaying`): it reloads the running
  game. If playing, ask the user to stop first.
- Then compile (`refresh_unity` compile `request`) and check `read_console` for errors.

It adds:
- the editor-state beacon (the editor-lock hook's eyes);
- `UnityWorkflow.Editor.PlaySession` (start scene, save backup/restore);
- `UnityWorkflow.Playtest` (steps, snapshot, screenshots);
- `UnityWorkflow.PerfProbe` / `Editor.PerfCheck`;
- `Editor.BuildChecks` (release and development player compiles);
- menu *Tools ▸ Unity Workflow*.

If game code that will register playtest steps or perf providers lives in its own asmdef, add a reference to
`UnityWorkflow.Runtime` there.

## 3. Write `.claude/unity-workflow.json`

Start from `<plugin>/skills/setup/unity-workflow.example.json`. Fill each key from evidence:

| key | how to find it |
|---|---|
| `lint.runtimeRoots` | where game code lives (`Assets/Scripts/`, `Assets/_Game/`…): runtime asmdefs or most `.cs` files |
| `lint.ignoreDirs` / `devDirs` | third-party folders (Plugins, asset-store packs); dev/cheat/debug folders |
| `lint.requireNamespace` | true unless the user objects; legacy files are never nagged (only new types) |
| `lint.logHelper` | a wrapper around `Debug.Log` (grep `Conditional(`, classes named `*Log*`); null if none |
| `lint.poolHelper` / `physicsHelper` | an object pool API; a shared NonAlloc buffer helper; null if none |
| `lint.generatedPaths` | folders written by importers/codegen ("auto-generated" headers, `Generated/` folders, tool output) |
| `lint.bannedText` / `textCheckGlobs` | only the user's own rules ("never show X text"); ask, don't invent |
| `playtest.startScene` | build-settings scene 0, or a bootstrap scene the game must start from (`EditorBuildSettings.scenes`) |
| `playtest.saveFiles` | where the game saves (grep `persistentDataPath`, `PlayerPrefs` won't be covered: say so), with `{persistentDataPath}` tokens |
| `editorLock.*Patterns` | project helpers `execute_code` uses to start/stop play or recompile (bot launchers) |
| `commitNoise` | assets Unity or tools rewrite on open that the team never commits (ask; start empty) |
| `verify.botRun` | the project's automated play-through, if any; else omit |

Missing file = generic rules only. Key reference: the plugin README.

## 4. Playtest steps

If the game has no way to be driven from code, offer to add `<plugin>/skills/playtest/step-template.cs` to a
dev-only folder, with 3–6 real steps (start a game, go to a level, start/win a fight, open a menu) and a
`SnapshotProvider`, written against the game's actual classes. Compile, enter play
(`PlaySession.Play(owner: "setup")`), run each step once, stop.

## 5. Safe editor settings (ask; they are per-user preferences)

- *Script Changes While Playing* → **Recompile After Finished Playing**
  (`UnityEditor.EditorPrefs.SetInt("ScriptCompilationDuringPlay", 1)`), so a script saved during play (by another
  session or the IDE) never reloads a running game. The editor-lock skill explains why.

## 6. CLAUDE.md

No `CLAUDE.md`: offer `<plugin>/skills/setup/CLAUDE.template.md` filled in from what you found. Existing one: offer to
add only the Workflow lines that point at the unity-workflow skills. Keep it short; the user's own rules go first.

## 7. Check the hooks

- **Lint:** write a throwaway runtime script with a global-namespace class and an `Instantiate` in `Update`, confirm
  the `unity-lint` note arrives, then delete it (and its `.meta`).
- **Editor guard:** run `python <plugin>/hooks/editor_lock.py status` (`python3` on macOS/Linux). It should show the
  editor state from the beacon.
- No note, or "state unknown": Python missing, plugin hooks not enabled, or the package not compiled yet. Say which.

## Report

Package version installed, the config written (show it), steps registered, settings changed, CLAUDE.md status, hook
checks, and that perf-check needs a first baseline (`/unity-workflow:perf-check`).
