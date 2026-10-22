// Release builds compile out the code that uses some fields (recording is editor/development only).
#pragma warning disable 0649
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using Unity.Profiling;
using Unity.Profiling.LowLevel.Unsafe;
using UnityEngine;
using UnityEngine.LowLevel;
using UnityEngine.PlayerLoop;
using UnityEngine.SceneManagement;
using Debug = UnityEngine.Debug;

namespace UnityWorkflow
{
    /// <summary>
    /// Records what every frame costs while the game plays: frame time, the game's own CPU time and garbage, batches,
    /// SetPass calls, script and physics time — per phase (e.g. "fight" / "explore") and per area (scene, room…), with
    /// area-load spikes kept apart. Writes Temp/UnityWorkflow/PerfReport_latest.json and .md.
    ///
    /// "Game" time is measured between markers placed first and last in Unity's player loop, so in the editor it leaves
    /// out the editor's own work. Game GC: in a development build the "GC Allocated In Frame" counter; in the editor
    /// that counter includes the editor's garbage (megabytes per update), so UnityWorkflow.Editor.PerfCheck feeds the
    /// Profiler's PlayerLoop GC through <see cref="ReportGameGc"/> instead. The probe allocates nothing per frame.
    ///
    /// Tell it about your game (optional, from any script, e.g. a [RuntimeInitializeOnLoadMethod]):
    ///   PerfProbe.AreaProvider  = () => currentRoom.name;          // default: the active scene's name
    ///   PerfProbe.PhaseProvider = () => inCombat ? "fight" : "explore";   // default: "play"
    ///   PerfProbe.CountProvider = () => enemies.Count;             // reported as "max count"
    ///   PerfProbe.StopWhen      = () => bot.Finished;              // optional end condition
    /// Start: PerfCheck.StartRun(seconds) in the editor, or PerfProbe.Begin("label", seconds) in a dev build.
    /// </summary>
    public sealed class PerfProbe : MonoBehaviour
    {
        public const string PendingKey = "UnityWorkflow.Perf.Pending";
        public const string ReportDir = "Temp/UnityWorkflow";
        public static string ReportJson => ReportDir + "/PerfReport_latest.json";
        public static string ReportMd => ReportDir + "/PerfReport_latest.md";

        public static Func<string> AreaProvider, PhaseProvider;
        public static Func<int> CountProvider;
        public static Func<bool> StopWhen;

        public static PerfProbe Active { get; private set; }
        public static string Status { get; private set; } = "idle";

        const int MaxFrames = 120000;
        const float SettleSeconds = 1.5f;
        const float PollSeconds = 0.5f;
        const float HitchMs = 50f;

        ProfilerRecorder batches, setPass, scripts, physics, gcCounter;
        readonly List<string> measured = new List<string> { "game loop time" };

        float[] frameMs, gameMs, gcKB, scriptMs, physicsMs;
        int[] batchCount, setPassCount;
        short[] bucketOf;
        int frames, statusFrames, gcFeeds, currentBucket = -1, lastHitchFrame = -1;
        readonly List<Bucket> buckets = new List<Bucket>();
        readonly Dictionary<string, int> bucketIndex = new Dictionary<string, int>();
        readonly List<Spike> spikes = new List<Spike>();
        string currentArea = "", runLabel = "";
        float areaChangedAt, nextPoll, lastHitchAt, startedAt, maxSeconds;
        bool lastFrameRecorded, finished;

        class Bucket { public string area, phase; public int maxCount, gcFrames; public double gcBytes; }

        // ------------------------------------------------------------------ the game's share of each frame

        struct PerfLoopBegin { }
        struct PerfLoopEnd { }

        static long loopStartTicks;
        static float lastLoopMs = -1f;

        static void OnLoopBegin() => loopStartTicks = Stopwatch.GetTimestamp();

        static void OnLoopEnd() => lastLoopMs = (float)((Stopwatch.GetTimestamp() - loopStartTicks) * 1000.0 / Stopwatch.Frequency);

        static void HookPlayerLoop(bool on)
        {
            PlayerLoopSystem root = PlayerLoop.GetCurrentPlayerLoop();
            for (int i = 0; i < root.subSystemList.Length; i++)
            {
                ref PlayerLoopSystem phase = ref root.subSystemList[i];
                var list = new List<PlayerLoopSystem>(phase.subSystemList ?? new PlayerLoopSystem[0]);
                list.RemoveAll(s => s.type == typeof(PerfLoopBegin) || s.type == typeof(PerfLoopEnd));
                if (on && phase.type == typeof(Initialization))
                    list.Insert(0, new PlayerLoopSystem { type = typeof(PerfLoopBegin), updateDelegate = OnLoopBegin });
                if (on && phase.type == typeof(PostLateUpdate))
                    list.Add(new PlayerLoopSystem { type = typeof(PerfLoopEnd), updateDelegate = OnLoopEnd });
                phase.subSystemList = list.ToArray();
            }
            PlayerLoop.SetPlayerLoop(root);
        }

        /// <summary>The game's (PlayerLoop's) managed allocation for one finished frame, from the editor's Profiler.</summary>
        public static void ReportGameGc(float bytes)
        {
            PerfProbe p = Active;
            if (p == null || p.finished || !p.lastFrameRecorded || p.currentBucket < 0) return;
            Bucket b = p.buckets[p.currentBucket];
            b.gcBytes += bytes;
            b.gcFrames++;
            p.gcFeeds++;
        }

        // ------------------------------------------------------------------ start / record / stop

#if UNITY_EDITOR
        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void BeginIfPending()
        {
            if (!UnityEditor.SessionState.GetBool(PendingKey, false)) return;
            UnityEditor.SessionState.SetBool(PendingKey, false);
            Begin(UnityEditor.SessionState.GetString(PendingKey + ".label", "editor run"),
                  UnityEditor.SessionState.GetFloat(PendingKey + ".seconds", 0f));
        }
#endif

        /// <summary>Starts recording (editor and development builds only). Stops after <paramref name="seconds"/> when above 0.</summary>
        public static void Begin(string label = "manual session", float seconds = 0f)
        {
#if UNITY_EDITOR || DEVELOPMENT_BUILD
            if (Active != null) return;
            var go = new GameObject("Perf Probe");
            DontDestroyOnLoad(go);
            Active = go.AddComponent<PerfProbe>();
            Active.runLabel = label + (seconds > 0 ? $", {seconds:0} s" : "");
            Active.maxSeconds = seconds;
            Status = "recording";
#endif
        }

        /// <summary>Call when your game starts loading a new area (a room, a level chunk) so the load counts as its entry spike.</summary>
        public static void MarkAreaChange(string area)
        {
            if (Active != null && !Active.finished) Active.MarkArea(area, Time.realtimeSinceStartup);
        }

        void Awake()
        {
            frameMs = new float[MaxFrames]; gameMs = new float[MaxFrames]; gcKB = new float[MaxFrames];
            scriptMs = new float[MaxFrames]; physicsMs = new float[MaxFrames];
            batchCount = new int[MaxFrames]; setPassCount = new int[MaxFrames];
            bucketOf = new short[MaxFrames];

            var handles = new List<ProfilerRecorderHandle>();
            ProfilerRecorderHandle.GetAvailable(handles);
            batches = Recorder(handles, "Batches Count");
            setPass = Recorder(handles, "SetPass Calls Count");
            scripts = Recorder(handles, "BehaviourUpdate");
            physics = Recorder(handles, "Physics.Simulate");
            if (!physics.Valid) physics = Recorder(handles, "Physics.Processing");
            if (!Application.isEditor) gcCounter = Recorder(handles, "GC Allocated In Frame");

            lastLoopMs = -1f;
            startedAt = Time.realtimeSinceStartup;
            HookPlayerLoop(true);
            SceneManager.activeSceneChanged += OnActiveSceneChanged;
        }

        ProfilerRecorder Recorder(List<ProfilerRecorderHandle> handles, string name)
        {
            foreach (ProfilerRecorderHandle h in handles)
            {
                ProfilerRecorderDescription d = ProfilerRecorderHandle.GetDescription(h);
                if (d.Name != name) continue;
                measured.Add(name);
                return ProfilerRecorder.StartNew(d.Category, d.Name, 1);
            }
            return default;
        }

        void OnActiveSceneChanged(Scene from, Scene to)
        {
            if (AreaProvider == null) MarkArea(to.name, Time.realtimeSinceStartup);
        }

        void MarkArea(string area, float now)
        {
            if (string.IsNullOrEmpty(area) || area == currentArea) return;
            currentArea = area;
            areaChangedAt = now;
            var spike = new Spike { area = area };
            // A hitch just before the area changed is usually its load (built first, entered a moment later).
            if (lastHitchFrame >= 0 && now - lastHitchAt < SettleSeconds)
            {
                spike.maxMs = frameMs[lastHitchFrame];
                bucketOf[lastHitchFrame] = -1;
            }
            lastHitchFrame = -1;
            spikes.Add(spike);
        }

        void Update()
        {
            if (finished) return;
            float now = Time.realtimeSinceStartup;
            if ((maxSeconds > 0f && now - startedAt >= maxSeconds) || (StopWhen != null && SafeStop())) { Finish(); return; }

            // The loop markers and unscaledDeltaTime both describe the previous frame.
            float ms = Time.unscaledDeltaTime * 1000f;
            float loopMs = lastLoopMs;
            lastFrameRecorded = false;
            if (now >= nextPoll) { nextPoll = now + PollSeconds; Poll(now); }

            if (Time.timeScale > 0.01f && currentBucket >= 0 && loopMs >= 0f)
            {
                if (now - areaChangedAt < SettleSeconds)
                {
                    if (spikes.Count > 0 && ms > spikes[spikes.Count - 1].maxMs) spikes[spikes.Count - 1].maxMs = ms;
                }
                else if (frames < MaxFrames)
                {
                    frameMs[frames] = ms;
                    gameMs[frames] = loopMs;
                    gcKB[frames] = gcCounter.Valid ? gcCounter.LastValue / 1024f : 0f;
                    scriptMs[frames] = scripts.Valid ? scripts.LastValue * 1e-6f : -1f;
                    physicsMs[frames] = physics.Valid ? physics.LastValue * 1e-6f : -1f;
                    batchCount[frames] = batches.Valid ? (int)batches.LastValue : -1;
                    setPassCount[frames] = setPass.Valid ? (int)setPass.LastValue : -1;
                    bucketOf[frames] = (short)currentBucket;
                    if (ms > HitchMs) { lastHitchFrame = frames; lastHitchAt = now; }
                    frames++;
                    lastFrameRecorded = true;
                }
            }
            if (frames - statusFrames >= 600) { statusFrames = frames; Status = $"recording: {frames} frames, {currentArea}"; }
        }

        bool SafeStop()
        {
            try { return StopWhen(); }
            catch (Exception e) { Debug.LogWarning("[PerfProbe] StopWhen threw: " + e.Message); StopWhen = null; return false; }
        }

        void Poll(float now)
        {
            string area = SceneManager.GetActiveScene().name, phase = "play";
            try
            {
                if (AreaProvider != null) area = AreaProvider() ?? "";
                if (PhaseProvider != null) phase = PhaseProvider() ?? "play";
            }
            catch (Exception e) { Debug.LogWarning("[PerfProbe] provider threw: " + e.Message); AreaProvider = null; PhaseProvider = null; }
            if (string.IsNullOrEmpty(area)) { currentBucket = -1; return; }   // loading / nothing to measure yet
            MarkArea(area, now);
            string key = area + "|" + phase;
            if (!bucketIndex.TryGetValue(key, out currentBucket))
            {
                currentBucket = buckets.Count;
                bucketIndex[key] = currentBucket;
                buckets.Add(new Bucket { area = area, phase = phase });
            }
            if (CountProvider != null)
            {
                Bucket b = buckets[currentBucket];
                try { b.maxCount = Mathf.Max(b.maxCount, CountProvider()); } catch { CountProvider = null; }
            }
        }

        /// <summary>Stops recording and writes the report. Returns where it is.</summary>
        public string Finish()
        {
            if (finished) return Status;
            finished = true;
            try
            {
                Report report = BuildReport();
                Directory.CreateDirectory(ReportDir);
                File.WriteAllText(ReportJson, JsonUtility.ToJson(report, true));
                File.WriteAllText(ReportMd, report.ToMarkdown());
                Status = $"finished: {frames} frames, report at {Path.GetFullPath(ReportMd)}";
                Debug.Log("[PerfProbe] " + Status);
            }
            catch (Exception e) { Status = "failed writing the report: " + e.Message; Debug.LogException(e); }
            finally
            {
                Unhook();
                if (Active == this) Active = null;
                if (isActiveAndEnabled) Destroy(gameObject);
            }
            return Status;
        }

        void Unhook()
        {
            HookPlayerLoop(false);
            SceneManager.activeSceneChanged -= OnActiveSceneChanged;
            batches.Dispose(); setPass.Dispose(); scripts.Dispose(); physics.Dispose(); gcCounter.Dispose();
        }

        void OnDisable()
        {
            if (!finished && frames > 0) Finish();
            else if (!finished) { finished = true; Unhook(); Status = "stopped: no frames recorded"; }
            if (Active == this) Active = null;
        }

        // ------------------------------------------------------------------ report

        [Serializable] public class Spike { public string area; public float maxMs; }

        [Serializable]
        public class Stats
        {
            public string label;
            public int frames, maxCount;
            public float seconds, frameAvg, frameP95, frameP99, frameMax, hitchesPerMin;
            public float gameAvg, gameP95, gcKBAvg, gcKBP95, gcKBMax, gcFramePct;
            public float batchesAvg, setPassAvg, scriptsAvg, physicsAvg;
        }

        [Serializable]
        public class Report
        {
            public string date, unityVersion, commit, screen, quality, counters, run;
            public bool editor;
            public List<Stats> phases = new List<Stats>();
            public List<Stats> areas = new List<Stats>();
            public List<Spike> entries = new List<Spike>();

            public Stats Phase(string label) => phases.Find(p => p.label == label);

            public string ToMarkdown()
            {
                var sb = new StringBuilder();
                sb.AppendLine($"# Perf report {date}");
                sb.AppendLine($"{run}; Unity {unityVersion}{(editor ? " (editor play mode)" : "")}; screen {screen}; quality {quality}{(string.IsNullOrEmpty(commit) ? "" : "; commit " + commit)}");
                sb.AppendLine($"Measured: {counters}. \"Game\" = the player loop only (no editor work); frame = wall clock.");
                sb.AppendLine();
                sb.AppendLine("| | frames | s | frame avg | p95 | p99 | max | hitches/min | game avg ms | game p95 ms | GC KB/frame | GC KB p95 | GC KB max | frames allocating | batches | SetPass | scripts ms | physics ms | max count |");
                sb.AppendLine("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|");
                foreach (Stats s in phases) Row(sb, "**" + s.label + "**", s);
                foreach (Stats s in areas) Row(sb, s.label, s);
                sb.AppendLine();
                sb.AppendLine("Area entry (first 1.5 s, loading): worst frame");
                foreach (Spike e in entries) sb.AppendLine($"- {e.area}: {e.maxMs:0} ms");
                return sb.ToString();
            }

            static void Row(StringBuilder sb, string name, Stats s) =>
                sb.AppendLine($"| {name} | {s.frames} | {s.seconds:0} | {s.frameAvg:0.0} | {s.frameP95:0.0} | {s.frameP99:0.0} | {s.frameMax:0} | {s.hitchesPerMin:0.0} | " +
                              $"{s.gameAvg:0.0} | {s.gameP95:0.0} | {N(s.gcKBAvg, "0.00")} | {N(s.gcKBP95, "0.0")} | {N(s.gcKBMax, "0")} | {N(s.gcFramePct, "0'%'")} | " +
                              $"{N(s.batchesAvg, "0")} | {N(s.setPassAvg, "0")} | {N(s.scriptsAvg, "0.00")} | {N(s.physicsAvg, "0.00")} | {s.maxCount} |");

            // -1 marks a value that was not measured (e.g. per-frame GC shape in the editor).
            static string N(float v, string format) => v < 0f ? "n/a" : v.ToString(format);
        }

        Report BuildReport()
        {
            bool haveGc = gcCounter.Valid || gcFeeds > frames / 2;
            measured.Add(gcCounter.Valid ? "game GC (counter)" : haveGc ? $"game GC (Profiler PlayerLoop, {gcFeeds} feeds)" : "game GC NOT measured");
            var r = new Report
            {
                date = DateTime.Now.ToString("yyyy-MM-dd HH:mm"),
                unityVersion = Application.unityVersion,
                editor = Application.isEditor,
                screen = $"{Screen.width}x{Screen.height}",
                quality = QualitySettings.names[QualitySettings.GetQualityLevel()],
                counters = string.Join(", ", measured),
                run = runLabel,
            };
            foreach (string phase in buckets.Select(b => b.phase).Distinct())
                r.phases.Add(Summarise(phase, i => buckets[bucketOf[i]].phase == phase, b => b.phase == phase));
            r.phases.Add(Summarise("all", i => true, b => true));
            for (int k = 0; k < buckets.Count; k++)
            {
                int bucket = k;
                r.areas.Add(Summarise($"{buckets[k].area} ({buckets[k].phase})", i => bucketOf[i] == bucket, b => b == buckets[bucket]));
            }
            r.areas.RemoveAll(s => s.frames == 0);
            if (!haveGc)
                foreach (Stats s in r.phases.Concat(r.areas)) s.gcKBAvg = s.gcKBP95 = s.gcKBMax = s.gcFramePct = -1f;
            r.entries.AddRange(spikes);
            return r;
        }

        Stats Summarise(string label, Func<int, bool> frameIn, Func<Bucket, bool> bucketIn)
        {
            var frame = new List<float>();
            var game = new List<float>();
            var gc = new List<float>();
            double frameSum = 0, gameSum = 0, gcSum = 0, batchSum = 0, setPassSum = 0, scriptSum = 0, physicsSum = 0;
            int hitches = 0, allocating = 0, batchN = 0, scriptN = 0, physicsN = 0;
            for (int i = 0; i < frames; i++)
            {
                if (bucketOf[i] < 0 || !frameIn(i)) continue;
                frame.Add(frameMs[i]); frameSum += frameMs[i];
                if (frameMs[i] > HitchMs) hitches++;
                game.Add(gameMs[i]); gameSum += gameMs[i];
                gc.Add(gcKB[i]); gcSum += gcKB[i];
                if (gcKB[i] > 0) allocating++;
                if (batchCount[i] >= 0) { batchSum += batchCount[i]; setPassSum += setPassCount[i]; batchN++; }
                if (scriptMs[i] >= 0) { scriptSum += scriptMs[i]; scriptN++; }
                if (physicsMs[i] >= 0) { physicsSum += physicsMs[i]; physicsN++; }
            }
            var s = new Stats { label = label, frames = frame.Count };
            double fedBytes = 0; int fedFrames = 0;
            foreach (Bucket b in buckets)
                if (bucketIn(b)) { s.maxCount = Mathf.Max(s.maxCount, b.maxCount); fedBytes += b.gcBytes; fedFrames += b.gcFrames; }
            if (frame.Count == 0) return s;
            frame.Sort(); game.Sort(); gc.Sort();
            int n = frame.Count;
            s.seconds = (float)(frameSum / 1000.0);
            s.frameAvg = (float)(frameSum / n);
            s.frameP95 = Percentile(frame, 0.95f);
            s.frameP99 = Percentile(frame, 0.99f);
            s.frameMax = frame[n - 1];
            s.hitchesPerMin = s.seconds > 0 ? hitches / (s.seconds / 60f) : 0;
            s.gameAvg = (float)(gameSum / n);
            s.gameP95 = Percentile(game, 0.95f);
            if (gcCounter.Valid)
            {
                s.gcKBAvg = (float)(gcSum / n);
                s.gcKBP95 = Percentile(gc, 0.95f);
                s.gcKBMax = gc[n - 1];
                s.gcFramePct = 100f * allocating / n;
            }
            else   // editor: Profiler-fed totals over the game frames recorded (the Profiler sends several feeds per frame)
            {
                s.gcKBAvg = fedFrames > 0 ? (float)(fedBytes / n / 1024.0) : -1f;
                s.gcKBP95 = s.gcKBMax = s.gcFramePct = -1f;
            }
            s.batchesAvg = batchN > 0 ? (float)(batchSum / batchN) : -1;
            s.setPassAvg = batchN > 0 ? (float)(setPassSum / batchN) : -1;
            s.scriptsAvg = scriptN > 0 ? (float)(scriptSum / scriptN) : -1;
            s.physicsAvg = physicsN > 0 ? (float)(physicsSum / physicsN) : -1;
            return s;
        }

        static float Percentile(List<float> sorted, float p) => sorted[Mathf.Clamp(Mathf.CeilToInt(p * sorted.Count) - 1, 0, sorted.Count - 1)];
    }
}
