# Unity Workflow

A Claude Code plugin for working fast in Unity without losing quality. It was built and battle-tested on a Unity 6 URP
co-op action game, then made generic.

| Piece | What it does |
|---|---|
| **Guard-rail hooks** | After every edit Claude makes, reads only the lines it **added** to C# and flags Unity rule breaks: new types outside a namespace, `Instantiate`/`Destroy`/`GetComponent`/`Find*`/LINQ/allocations/string building in `Update`, allocating physics queries, `Debug.Log`, debug keys not behind `#if`, `using UnityEditor` in runtime code, a removed `[MovedFrom]`, and your own banned text. Legacy code is never nagged. Before an edit, refuses hand edits to folders you mark as generated. |
| **unity-reviewer** agent | Reviews a diff against Unity's real failure modes (player builds, serialized data, hot paths, lifecycle, reuse) plus your `CLAUDE.md`. Read-only, ranked findings. |
| `/unity-workflow:setup` | Installs the small Unity package, writes `.claude/unity-workflow.json` from what your project already uses, offers a starter `CLAUDE.md`, checks the hooks. |
| `/unity-workflow:verify` | Compile + console, EditMode/PlayMode tests, **release and development player script compiles**, and your bot run if you have one. |
| `/unity-workflow:perf-check` | Records real frames in play: frame time, the **game's own** CPU time and GC (editor overhead excluded), hitches, batches, scripts, physics, per phase and area, plus area-load spikes. Compares with a committed baseline and reports PASS / WARN / FAIL. |
| `/unity-workflow:unity-commit` | Sorts changes into real work and Unity noise (re-serialisation, font atlases, rebakes), summarises prefab/scene diffs by field, stages only your hunks when another session touched the same file, runs the reviewer, writes the message. |

## Install

```
/plugin marketplace add churuiheng/Unity-Workflow-Plugin
/plugin install unity-workflow@unity-workflow
```
Then, in your Unity project: `/unity-workflow:setup`.

**Needs:** Python 3 on the PATH (`python3`, `python` or `py`) for the hooks and the commit script; a POSIX shell for
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

## The Unity package

`setup` copies `plugin/unity-package/com.ruiheng.unity-workflow` into your project's `Packages/`. Everything records
only in the editor and development builds.

- `UnityWorkflow.PerfProbe`: tell it about your game with `AreaProvider`, `PhaseProvider`, `CountProvider` and
  `StopWhen`, and call `MarkAreaChange(name)` where an area starts loading.
- `UnityWorkflow.Editor.PerfCheck`: `StartRun(seconds, startScene, label)`, `State()`, `Compare()`, `SaveBaseline()`.
  The baseline is `UnityWorkflow/perf-baseline.json`; commit it.
- `UnityWorkflow.Editor.BuildChecks.PlayerCompile(development)`.

Menu: *Tools ▸ Unity Workflow*.

### Why "game" time and GC, and not the Profiler's counters

In editor play mode, Unity's `GC Allocated In Frame` and `Main Thread` counters include the **editor's** own work. An
idle editor allocates megabytes per update, which drowns the game's few KB. `GC.GetAllocatedBytesForCurrentThread()`
always reads 0 under Unity's Mono. So the probe:
- times the player loop between its own markers;
- in the editor, takes GC from the Profiler's `PlayerLoop` root, which leaves out `EditorLoop`;
- in development builds, where the counter is game-only, reads it directly.

## License

MIT
