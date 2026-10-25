# Unity Workflow

A Claude Code plugin for working fast in Unity without losing quality. It was built and battle-tested on a Unity 6 URP
co-op action game, then made generic.

| Piece | What it does |
|---|---|
| **Guard-rail hooks** | After every edit Claude makes, reads only the lines it **added** to C# and flags Unity rule breaks: new types outside a namespace, `Instantiate`/`Destroy`/`GetComponent`/`Find*`/LINQ/allocations/string building in `Update`, allocating physics queries, `Debug.Log`, debug keys not behind `#if`, `using UnityEditor` in runtime code, a removed `[MovedFrom]`, and your own banned text. Legacy code is never nagged. Before an edit, refuses hand edits to folders you mark as generated. |
| **unity-reviewer** agent | Reviews a diff against Unity's real failure modes (player builds, serialized data, hot paths, lifecycle, reuse) plus your `CLAUDE.md`. Read-only, ranked findings. |
| **Editor lock** (hook) | One Unity editor, several workers. Before a Unity MCP call, it refuses to recompile, enter, stop or pause play, or load/save scenes while another Claude session holds the editor, or while you are playing. Entering play takes the lock; it frees itself when play ends. Saving scripts during someone else's session gets a warning. See `/unity-workflow:editor-lock`. |
| `/unity-workflow:playtest` | Play the game to check a change works: start from the project's start scene with save files backed up and restored, drive it with your registered **Playtest steps**, read a state snapshot, take Game-view screenshots and look at them, stop and put everything back. Window helpers keep Unity in front (Windows, macOS, Linux). |
| `/unity-workflow:editor-lock` | See who holds the editor, claim it for long work, free a stale lock with the user's OK, and make script saves safe during play. |
| `/unity-workflow:setup` | Installs the small Unity package, writes `.claude/unity-workflow.json` from what your project already uses, offers a starter `CLAUDE.md`, checks the hooks. |
| `/unity-workflow:verify` | Compile + console, EditMode/PlayMode tests, **release and development player script compiles**, and your bot run if you have one. |
| `/unity-workflow:ui-review` | Reviews UI by looking at it: captures the HUD, menus and in-world indicators in the states players see, crops/zooms and lines them up (`ui_shots.py`), checks them against a clarity/consistency/navigation checklist and **your recorded UI rules** (`.claude/ui-rules.md`), fixes, and proves each fix with a before/after strip. Includes a table of Unity UI traps (sliced-corner multiplier math, oval pills, Filled images, world-space units, fallback fonts, letterboxed masks). |
| `/unity-workflow:clean-captures` | Prunes old screenshots/clips from your captures folders (default `Captures/`, older than 30 days): dry run first with count and space freed, `.keep` globs to pin evidence, deletes only on `--apply`; never touches git-tracked files, `Assets/` or anything outside the project. |
| `/unity-workflow:perf-check` | Records real frames in play: frame time, the **game's own** CPU time and GC (editor overhead excluded), hitches, batches, scripts, physics, per phase and area, plus area-load spikes. Compares with a committed baseline and reports PASS / WARN / FAIL. |
| `/unity-workflow:unity-commit` | Sorts changes into real work and Unity noise (re-serialisation, font atlases, rebakes), summarises prefab/scene diffs by field, stages only your hunks when another session touched the same file, runs the reviewer, writes the message. |

## Install

```
/plugin marketplace add churuiheng/Unity-Workflow-Plugin
/plugin install unity-workflow@unity-workflow
```
Then, in your Unity project: `/unity-workflow:setup`.

**Needs:** Python 3 on the PATH (`python3`, `python` or `py`) for the hooks and the commit script (plus Pillow for `ui-review`'s image script); a POSIX shell for
hooks (Git Bash on Windows, which Claude Code uses); [MCP for Unity](https://github.com/CoplayDev/unity-mcp) connected
for verify and perf-check; Unity 2022.3 or newer (tested on Unity 6.3).

## Project config: `.claude/unity-workflow.json`

Optional; without it the generic rules apply. `setup` writes it from evidence in your project.

| key | default | meaning |
|---|---|---|
| `lint.runtimeRoots` | `["Assets/"]` | folders holding player code |
| `lint.ignoreDirs` | Editor, Tests, Plugins, ThirdParty, Samples | never treated as runtime code |
| `lint.devDirs` | Dev, Debug, Cheats | dev-only code: debug keys, logs and hot-path rules skipped |
| `lint.requireNamespace` | `true` | new runtime types must be in a namespace |
| `lint.logHelper` | `null` | your logging wrapper; when set, any runtime `Debug.Log` is flagged (otherwise only in `Update`) |
| `lint.poolHelper` / `lint.physicsHelper` | `null` | named in the Instantiate / physics-query warnings |
| `lint.generatedPaths` | `[]` | globs Claude may not hand-edit (e.g. `Assets/Data/Generated/*`) |
| `lint.generatedHint` | | what to tell Claude to edit instead |
| `lint.bannedText` | `[]` | `{ "pattern", "message", "in": "string" \| "code" \| "any" }` checked on added lines |
| `lint.textCheckGlobs` | `[]` | extra files (e.g. data JSON) checked against `bannedText` |
| `commitNoise` | `[]` | `{ "path", "keys"?, "reason" }` extra noise rules for unity-commit |
| `verify.botRun` | `null` | how to start your automated play-through, if you have one |
| `playtest.startScene` | `""` | scene play starts from (a bootstrap scene); empty = the open scene |
| `playtest.saveFiles` | `[]` | files backed up before play and restored after; tokens `{persistentDataPath}`, `{dataPath}`, `{projectPath}` |
| `uiReview.rulesFile` | `.claude/ui-rules.md` | the project's UI decisions, read before every review and updated after |
| `uiReview.capturesDir` | `Captures` | where review screenshots go |
| `captures.dirs` / `captures.maxAgeDays` / `captures.keep` | `["Captures"]` / `30` / `[]` | what `clean-captures` prunes, how old, and globs it never deletes |
| `editorLock.playLockMinutes` | `45` | how long a play lock lasts without activity |
| `editorLock.playStartPatterns` / `playStopPatterns` / `reloadPatterns` | `[]` | regexes for project helpers that `execute_code` uses to enter/stop play or recompile (bot launchers) |

## The Unity package

`setup` copies `plugin/unity-package/com.ruiheng.unity-workflow` into your project's `Packages/`. Everything records
only in the editor and development builds.

- `UnityWorkflow.PerfProbe`: tell it about your game with `AreaProvider`, `PhaseProvider`, `CountProvider` and
  `StopWhen`, and call `MarkAreaChange(name)` where an area starts loading.
- `UnityWorkflow.Editor.PerfCheck`: `StartRun(seconds, startScene, label)`, `State()`, `Compare()`, `SaveBaseline()`.
  The baseline is `UnityWorkflow/perf-baseline.json`; commit it.
- `UnityWorkflow.Editor.BuildChecks.PlayerCompile(development)`.
- `UnityWorkflow.Editor.PlaySession`: `Play(startScene, owner, allowSaveDialog)`, `Stop()`, `State()`.
- `UnityWorkflow.Playtest`: `Register(name, step, help)`, `Run("name arg")`, `Status`, `Snapshot()`, `SnapshotProvider`, and the built-in steps `wait`, `timescale`, `shot`. Template: `plugin/skills/playtest/step-template.cs`.
- `UnityWorkflow.Editor.EditorStateBeacon`: writes `Temp/UnityWorkflow/editor-state.json` (playing, compiling, who started play, heartbeat) for the editor-lock hook.

Menu: *Tools ▸ Unity Workflow*.

### Why "game" time and GC, and not the Profiler's counters

In editor play mode, Unity's `GC Allocated In Frame` and `Main Thread` counters include the **editor's** own work. An
idle editor allocates megabytes per update, which drowns the game's few KB. `GC.GetAllocatedBytesForCurrentThread()`
always reads 0 under Unity's Mono. So the probe:
- times the player loop between its own markers;
- in the editor, takes GC from the Profiler's `PlayerLoop` root, which leaves out `EditorLoop`;
- in development builds, where the counter is game-only, reads it directly.

## Tests

`python tests/test_hooks.py` covers the lint rules and the editor-lock decision table against fake editor state (stdlib only).

## Changelog

- **0.2.0**
  - Editor lock: the editor-guard hook, the editor-state beacon, the `editor_lock.py` CLI and the editor-lock skill.
  - Playtest: PlaySession (start scene, save backup and restore, play owner), Playtest steps, snapshot and screenshots, cross-platform window helpers, and the playtest skill.
  - The setup skill now configures playtest and the lock, and recommends *Recompile After Finished Playing*.
  - Hook tests.
- **0.1.0**: the guard-rail lint hooks, the unity-reviewer agent, and the setup, verify, perf-check and unity-commit skills; the Unity package with PerfProbe, PerfCheck and BuildChecks.

## License

MIT
