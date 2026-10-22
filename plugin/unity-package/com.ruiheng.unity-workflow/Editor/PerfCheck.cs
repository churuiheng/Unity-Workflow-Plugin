using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace UnityWorkflow.Editor
{
    /// <summary>
    /// The perf check behind the unity-workflow "perf-check" skill. StartRun enters play and records with
    /// <see cref="PerfProbe"/>; Compare checks the latest report against the committed baseline per phase with noise
    /// allowances (FAIL on a real regression, WARN on a softer one); SaveBaseline makes the latest report the baseline.
    /// All callable from code (Unity MCP execute_code) or Tools ▸ Unity Workflow.
    /// </summary>
    public static class PerfCheck
    {
        public const string BaselinePath = "UnityWorkflow/perf-baseline.json";
        public static string ComparePath => PerfProbe.ReportDir + "/PerfCompare_latest.md";
        const string StartedKey = "UnityWorkflow.Perf.started";
        const string RestoreSceneKey = "UnityWorkflow.Perf.restoreStartScene";

        [MenuItem("Tools/Unity Workflow/Perf Check: Record 2 Minutes of Play")]
        static void StartRunMenu() => StartRun(120f);

        /// <summary>
        /// Enters play and records for <paramref name="seconds"/> (0 = until <see cref="PerfProbe.StopWhen"/> or play
        /// stops). <paramref name="startScene"/> (asset path) is used as the play-mode start scene for this run only.
        /// Drive the game during the run yourself, with your project's bot, or let it idle in a busy scene.
        /// </summary>
        public static string StartRun(float seconds = 120f, string startScene = null, string label = "editor run")
        {
            if (EditorApplication.isPlaying) return "stop play mode first";
            SessionState.SetString(StartedKey, System.DateTime.Now.ToString("o"));
            SessionState.SetBool(PerfProbe.PendingKey, true);
            SessionState.SetString(PerfProbe.PendingKey + ".label", label);
            SessionState.SetFloat(PerfProbe.PendingKey + ".seconds", seconds);
            if (!string.IsNullOrEmpty(startScene))
            {
                var scene = AssetDatabase.LoadAssetAtPath<SceneAsset>(startScene);
                if (scene == null) { SessionState.SetBool(PerfProbe.PendingKey, false); return "no scene at " + startScene; }
                SessionState.SetString(RestoreSceneKey, EditorSceneManager.playModeStartScene != null
                    ? AssetDatabase.GetAssetPath(EditorSceneManager.playModeStartScene) : "");
                EditorSceneManager.playModeStartScene = scene;
            }
            // Directly, not via delayCall: a delayCall queued right after a domain reload can fail to fire.
            EditorApplication.EnterPlaymode();
            return "starting";
        }

        [InitializeOnLoadMethod]
        static void RestoreStartSceneAfterPlay()
        {
            EditorApplication.playModeStateChanged += state =>
            {
                if (state != PlayModeStateChange.EnteredEditMode) return;
                string restore = SessionState.GetString(RestoreSceneKey, null);
                if (restore == null) return;
                EditorSceneManager.playModeStartScene = restore == "" ? null : AssetDatabase.LoadAssetAtPath<SceneAsset>(restore);
                SessionState.EraseString(RestoreSceneKey);
            };
        }

        /// <summary>"running: …", "finished: report at …", a failure, or "not running".</summary>
        public static string State()
        {
            if (PerfProbe.Active != null) return "running: " + PerfProbe.Status;
            if (PerfProbe.Status.StartsWith("failed") || PerfProbe.Status.StartsWith("stopped")) return PerfProbe.Status;
            string started = SessionState.GetString(StartedKey, "");
            if (started == "") return "not started";
            var since = System.DateTime.Parse(started, null, System.Globalization.DateTimeStyles.RoundtripKind);
            if (File.Exists(PerfProbe.ReportMd) && File.GetLastWriteTime(PerfProbe.ReportMd) > since)
                return "finished: report at " + Path.GetFullPath(PerfProbe.ReportMd);
            return EditorApplication.isPlaying ? "running: probe not started yet" : "not running (no report written since it started)";
        }

        [MenuItem("Tools/Unity Workflow/Perf Check: Compare With Baseline")]
        static void CompareMenu() => Debug.Log("[PerfCheck] " + Compare());

        /// <summary>First line "PASS", "WARN …" or "FAIL …", then the per-metric table (also written to Temp/UnityWorkflow).</summary>
        public static string Compare()
        {
            if (!File.Exists(PerfProbe.ReportJson)) return "no report yet: run PerfCheck.StartRun() first";
            if (!File.Exists(BaselinePath)) return "no baseline yet: PerfCheck.SaveBaseline() after a run you trust";
            var now = JsonUtility.FromJson<PerfProbe.Report>(File.ReadAllText(PerfProbe.ReportJson));
            var was = JsonUtility.FromJson<PerfProbe.Report>(File.ReadAllText(BaselinePath));

            var rows = new StringBuilder();
            var fails = new List<string>();
            var warns = new List<string>();
            rows.AppendLine("| phase | metric | baseline | now | change | |");
            rows.AppendLine("|---|---|---|---|---|---|");

            void Check(string phase, string metric, float a, float b, float rel, float abs, bool hard)
            {
                if (a < 0 || b < 0) return;   // not measured in one of the runs
                string verdict = "";
                if (b > a * (1 + rel) + abs) { verdict = hard ? "FAIL" : "warn"; (hard ? fails : warns).Add($"{phase} {metric} {a:0.##} -> {b:0.##}"); }
                else if (b < a * (1 - rel) - abs) verdict = "better";
                float pct = a > 0.0001f ? (b - a) / a * 100f : 0f;
                rows.AppendLine($"| {phase} | {metric} | {a:0.##} | {b:0.##} | {pct:+0;-0}% | {verdict} |");
            }

            var phases = was.phases.Select(p => p.label).Where(l => l != "all").Union(now.phases.Select(p => p.label).Where(l => l != "all"));
            foreach (string phase in phases)
            {
                PerfProbe.Stats a = was.Phase(phase), b = now.Phase(phase);
                if (a == null || b == null || a.frames == 0 || b.frames == 0) { rows.AppendLine($"| {phase} | (only in one run) | | | | |"); continue; }
                Check(phase, "frame p95 ms", a.frameP95, b.frameP95, 0.15f, 1f, true);
                Check(phase, "game loop p95 ms", a.gameP95, b.gameP95, 0.15f, 1f, true);
                Check(phase, "game loop avg ms", a.gameAvg, b.gameAvg, 0.15f, 0.5f, true);
                Check(phase, "GC KB/frame", a.gcKBAvg, b.gcKBAvg, 0.25f, 0.5f, true);
                Check(phase, "hitches/min (>50 ms)", a.hitchesPerMin, b.hitchesPerMin, 0.5f, 2f, true);
                Check(phase, "frame avg ms", a.frameAvg, b.frameAvg, 0.15f, 0.5f, false);
                Check(phase, "batches", a.batchesAvg, b.batchesAvg, 0.2f, 20f, false);
                Check(phase, "SetPass calls", a.setPassAvg, b.setPassAvg, 0.2f, 10f, false);
                Check(phase, "scripts ms", a.scriptsAvg, b.scriptsAvg, 0.25f, 0.3f, false);
                Check(phase, "physics ms", a.physicsAvg, b.physicsAvg, 0.25f, 0.3f, false);
            }
            Check("entry", "worst area-load frame ms", Worst(was.entries), Worst(now.entries), 0.3f, 20f, false);

            var notes = new List<string>();
            if (was.screen != now.screen) notes.Add($"screen differs ({was.screen} vs {now.screen}): frame times are not comparable");
            if (was.unityVersion != now.unityVersion) notes.Add($"Unity version differs ({was.unityVersion} vs {now.unityVersion})");
            if (was.quality != now.quality) notes.Add($"quality level differs ({was.quality} vs {now.quality})");
            if (was.editor != now.editor) notes.Add("one run is the editor, the other a build: not comparable");
            if (UnityEditorInternal.ProfilerDriver.deepProfiling) notes.Add("Deep Profile is on: game times are inflated");

            string head = fails.Count > 0 ? "FAIL: " + string.Join("; ", fails)
                        : warns.Count > 0 ? "WARN: " + string.Join("; ", warns)
                        : "PASS";
            string text = head + "\n" + (notes.Count > 0 ? "Note: " + string.Join("; ", notes) + "\n" : "") +
                          $"Baseline {was.date}{(string.IsNullOrEmpty(was.commit) ? "" : " @ " + was.commit)} vs now {now.date}\n\n" + rows;
            Directory.CreateDirectory(PerfProbe.ReportDir);
            File.WriteAllText(ComparePath, text);
            return text;
        }

        static float Worst(List<PerfProbe.Spike> entries)
        {
            float worst = -1f;
            if (entries != null) foreach (var e in entries) worst = Mathf.Max(worst, e.maxMs);
            return worst;
        }

        [MenuItem("Tools/Unity Workflow/Perf Check: Save Latest As Baseline")]
        static void SaveBaselineMenu() => Debug.Log("[PerfCheck] " + SaveBaseline());

        /// <summary>Copies the latest report to UnityWorkflow/perf-baseline.json, stamped with the current commit.</summary>
        public static string SaveBaseline()
        {
            if (!File.Exists(PerfProbe.ReportJson)) return "no report yet: run PerfCheck.StartRun() first";
            var report = JsonUtility.FromJson<PerfProbe.Report>(File.ReadAllText(PerfProbe.ReportJson));
            report.commit = GitHead();
            Directory.CreateDirectory(Path.GetDirectoryName(BaselinePath));
            File.WriteAllText(BaselinePath, JsonUtility.ToJson(report, true));
            return $"baseline saved: {BaselinePath} ({report.date}, commit {report.commit})";
        }

        static string GitHead()
        {
            try
            {
                var p = System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo("git", "rev-parse --short HEAD")
                {
                    RedirectStandardOutput = true, UseShellExecute = false, CreateNoWindow = true,
                });
                string head = p.StandardOutput.ReadToEnd().Trim();
                p.WaitForExit(3000);
                return head;
            }
            catch { return ""; }
        }

        // ------------------------------------------------------------------ the game's garbage, from the Profiler

        /// <summary>
        /// While a <see cref="PerfProbe"/> records in play mode, profiles the game (not the editor) and feeds each frame's
        /// PlayerLoop GC Alloc to the probe; the editor's own garbage sits under EditorLoop and is left out. Hands the
        /// Profiler back (and the user's Edit Mode target) when the probe finishes.
        /// </summary>
        [InitializeOnLoad]
        static class GameGcFeed
        {
            static int lastFrame = -1;
            static bool profilerOurs, userProfiledEditor;
            static readonly List<int> children = new List<int>();

            static GameGcFeed() => EditorApplication.update += Tick;

            static void Tick()
            {
                if (!EditorApplication.isPlaying || PerfProbe.Active == null)
                {
                    if (profilerOurs)
                    {
                        UnityEditorInternal.ProfilerDriver.enabled = false;
                        UnityEditorInternal.ProfilerDriver.profileEditor = userProfiledEditor;
                        profilerOurs = false;
                    }
                    lastFrame = -1;
                    return;
                }
                if (!UnityEditorInternal.ProfilerDriver.enabled)
                {
                    userProfiledEditor = UnityEditorInternal.ProfilerDriver.profileEditor;
                    UnityEditorInternal.ProfilerDriver.profileEditor = false;
                    UnityEditorInternal.ProfilerDriver.enabled = true;
                    profilerOurs = true;
                }
                int last = UnityEditorInternal.ProfilerDriver.lastFrameIndex;
                if (lastFrame < 0) { lastFrame = last; return; }
                for (int f = Mathf.Max(lastFrame + 1, UnityEditorInternal.ProfilerDriver.firstFrameIndex); f <= last; f++)
                {
                    using (var view = UnityEditorInternal.ProfilerDriver.GetHierarchyFrameDataView(f, 0,
                               UnityEditor.Profiling.HierarchyFrameDataView.ViewModes.Default,
                               UnityEditor.Profiling.HierarchyFrameDataView.columnGcMemory, false))
                    {
                        if (view == null || !view.valid) continue;
                        children.Clear();
                        view.GetItemChildren(view.GetRootItemID(), children);
                        foreach (int id in children)
                            if (view.GetItemName(id) == "PlayerLoop")
                                PerfProbe.ReportGameGc(view.GetItemColumnDataAsFloat(id, UnityEditor.Profiling.HierarchyFrameDataView.columnGcMemory));
                    }
                }
                lastFrame = last;
            }
        }
    }
}
