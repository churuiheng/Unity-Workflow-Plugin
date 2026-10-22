---
name: setup
description: Set up unity-workflow in a Unity project — copy its small Unity package (perf probe, player-compile checks) into Packages/, write .claude/unity-workflow.json from what the project already uses (namespaces, logging, pooling, physics helpers, generated folders, noise rules), offer a starter CLAUDE.md, and check the hooks fire. Use when the user says "set up unity-workflow", "install the unity workflow", "configure the guard rails", or when another unity-workflow skill finds the package or config missing.
---

# Set up unity-workflow

Read the project before writing anything; every value in the config should come from code that exists. Ask only
about what the code can't tell you. Show the user the config before saving it.

## 1. Find the Unity project

The folder with both `Assets/` and `ProjectSettings/` (may be a subfolder of the git repo). Note the Unity version
(`ProjectSettings/ProjectVersion.txt`). Unity MCP (`mcp__UnityMCP__*`, the CoplayDev "MCP for Unity" package) is
needed for verify and perf-check; say so if it isn't connected.

## 2. Install the Unity package

Copy `${CLAUDE_PLUGIN_ROOT}/unity-package/com.ruiheng.unity-workflow/` to `<project>/Packages/com.ruiheng.unity-workflow/`
(an embedded package: Unity imports it and makes the `.meta` files). If it already exists, compare the `version` in
both `package.json` files and only overwrite with the user's OK. Then compile (`refresh_unity` compile `request`,
`read_console` errors). **Never compile while the editor is in play mode** (`EditorApplication.isPlaying`): a reload
mid-play breaks the running game. It adds:
- `UnityWorkflow.PerfProbe` (runtime, records only in the editor and development builds) and
  `UnityWorkflow.Editor.PerfCheck` (run / compare / baseline);
- `UnityWorkflow.Editor.BuildChecks.PlayerCompile(development)` (release and development player script compiles);
- menu *Tools ▸ Unity Workflow*.

If the project's game code is in its own asmdef and should feed the probe (area/phase providers), add a reference to
`UnityWorkflow.Runtime` in that asmdef.

## 3. Write `.claude/unity-workflow.json`

Start from `${CLAUDE_PLUGIN_ROOT}/skills/setup/unity-workflow.example.json`. Fill each key from evidence:

| key | how to find it |
|---|---|
| `lint.runtimeRoots` | where game code lives (`Assets/Scripts/`, `Assets/_Game/`…): the folders with runtime asmdefs or most `.cs` files |
| `lint.ignoreDirs` / `devDirs` | third-party folders (Plugins, asset-store packs); dev/cheat/debug folders |
| `lint.requireNamespace` | true unless the user objects; legacy files are never nagged (only new types) |
| `lint.logHelper` | a project wrapper around `Debug.Log` (grep `Conditional(` or classes named `*Log*`); null if none |
| `lint.poolHelper` | an object pool API (grep `class .*Pool`, `ObjectPool<`); null if none |
| `lint.physicsHelper` | a shared NonAlloc buffer helper; null if none |
| `lint.generatedPaths` | folders written by importers/codegen (grep "auto-generated", look for `Generated/` folders, tool output dirs) |
| `lint.bannedText` / `textCheckGlobs` | only the user's own rules ("never show X text"); ask, don't invent |
| `commitNoise` | assets Unity or tools rewrite on open that the team never commits (ask; start empty) |
| `verify.botRun` | the project's automated play-through, if any (an autopilot/bot entry point); else omit |

Config keys and defaults are in the README. Missing file = generic Unity rules only.

## 4. CLAUDE.md

If the project has no `CLAUDE.md`, offer `${CLAUDE_PLUGIN_ROOT}/skills/setup/CLAUDE.template.md` filled in from what you
found (structure, assemblies, helpers, workflow). If it has one, offer to add only the "Workflow" lines that point
at the unity-workflow skills. Keep it short; the user's own rules go first.

## 5. Check the hooks

Write a throwaway runtime script with a global-namespace class and an `Instantiate` in `Update`, confirm the
`unity-lint` note arrives, then delete it (and its `.meta` if Unity made one). If no note arrives: Python missing
(`python3`/`python`/`py` all failed), or the plugin hooks aren't enabled; say which.

## Report

What was installed (package version, where), the config written (show it), CLAUDE.md status, hook check result, and
that `perf-check` needs a first baseline (`/unity-workflow:perf-check`).
