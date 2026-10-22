---
name: perf-check
description: Measure whether a change made a Unity game slower or more garbage-heavy — record real frames in play with the unity-workflow PerfProbe (frame time, the game's own CPU time and GC without the editor's overhead, hitches, batches/SetPass, script and physics time, per phase and per area, plus area-load spikes), compare against the committed baseline, and report PASS / WARN / FAIL. Use whenever the user asks about performance, FPS, stutter, hitches, GC or allocations, "is this optimised?", "did this make it slower?", before committing hot-path changes (combat, spawning, VFX, pooling, loading, UI), and after an optimisation to prove it.
---

# Perf check

The lint hook catches bad patterns; this measures real cost. Needs the unity-workflow package (`/unity-workflow:setup`)
and Unity MCP. Unity must stay **focused** during the run. Don't start while the editor is playing someone else's
session.

## Make the numbers mean something (once per project)

The probe splits stats by **phase** and **area**. Defaults: phase "play", area = active scene. If the game has
rooms, levels or combat, add a small dev-only adapter (in game code, so it compiles everywhere):
```csharp
#if UNITY_EDITOR || DEVELOPMENT_BUILD
static class PerfAdapter
{
    [UnityEngine.RuntimeInitializeOnLoadMethod]
    static void Init()
    {
        UnityWorkflow.PerfProbe.AreaProvider  = () => RoomManager.Current ? RoomManager.Current.name : null;   // null = not measuring yet
        UnityWorkflow.PerfProbe.PhaseProvider = () => CombatState.InFight ? "fight" : "explore";
        UnityWorkflow.PerfProbe.CountProvider = () => EnemyRegistry.Count;
        UnityWorkflow.PerfProbe.StopWhen      = () => Autopilot.Finished;                          // optional
    }
}
#endif
```
Providers run twice a second; keep them cheap and allocation-free where possible. Call
`UnityWorkflow.PerfProbe.MarkAreaChange(name)` where a level/room starts loading so its hitch counts as the area's
entry spike, not as a stutter in the area before.

## Run

1. Same scenario every time, or the comparison is meaningless: the project's bot/autoplay if it has one (best), a
   scripted path, or a fixed busy scene left idle. Write down which.
2. `execute_code`: `return UnityWorkflow.Editor.PerfCheck.StartRun(120f, "Assets/Scenes/<Start>.unity", "<scenario>");`
   (seconds 0 = until `StopWhen` or play stops; start scene optional, restored after). Then start the scenario.
3. Poll `return UnityWorkflow.Editor.PerfCheck.State();` until `finished` (or a failure), then stop play.
4. `return UnityWorkflow.Editor.PerfCheck.Compare();` and read `Temp/UnityWorkflow/PerfReport_latest.md` for the
   per-area table.

**No baseline yet:** measure the commit *before* the change first, `PerfCheck.SaveBaseline()` (writes
`UnityWorkflow/perf-baseline.json`, stamped with the commit), then the change. Commit the baseline with the change that
justifies it. **Never re-baseline to make a failure go away**, only when the method or the scenario changed (say so).

## Reading it

FAIL (per phase) when now > baseline × (1 + rel) + abs: frame p95 and game-loop p95 (15% + 1 ms), game-loop avg
(15% + 0.5 ms), GC KB/frame (25% + 0.5 KB), hitches/min over 50 ms (50% + 2). Batches, SetPass, scripts, physics,
frame avg and the worst area-load frame only WARN; they point at where.

- **Game loop** time and **GC** leave out the editor. Never judge GC by the Profiler's "GC Allocated In Frame" or
  "Main Thread" in the editor: an idle editor allocates megabytes per update. In the editor GC is an average per
  area/phase (p95/max read n/a); a development build gives the per-frame shape.
- Frame time is wall clock (includes the editor): compare runs, don't judge one alone.
- Run-to-run noise is ~5–15%; near a threshold, run again before calling it. `Note:` lines (screen size, Unity
  version, quality, editor vs build, Deep Profile) mean the runs aren't comparable: fix the setup and rerun.

## When it fails

The per-area table says where (area, phase) and what (GC vs scripts vs physics vs batches). Read the diff's hot
paths; for the exact function, record a Profiler capture (`manage_profiler` `profiler_start` with `log_file` and
`enable_callstacks: true`), reproduce in that area, `profiler_stop`, and have the user open the .raw (Hierarchy, sort
by GC Alloc / Self ms). Fix, rerun.

## Report

```
Perf: PASS / WARN / FAIL  (scenario, editor, baseline <date @ commit>)
- fight:   frame p95 23.2 ms (base 23.5), game p95 13.7 ms, GC 7.6 KB/frame (base 7.3), hitches 0/min
- explore: frame p95 23.0 ms, game p95 12.9 ms, GC 9.9 KB/frame
- Worst area: <area (phase)>, <what stands out>
```
