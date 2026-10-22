// Release builds compile out the code that uses some fields (recording is editor/development only).
#pragma warning disable 0414
using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace UnityWorkflow
{
    /// <summary>
    /// Named, scriptable steps for driving a game in play mode, so Claude (through Unity MCP) or a test can get to the
    /// thing it needs to check — and a one-line snapshot of the game state to confirm it got there.
    ///
    /// Register your game's steps once, from game code (dev-only is fine):
    /// <code>
    /// [RuntimeInitializeOnLoadMethod]
    /// static void RegisterSteps()
    /// {
    ///     Playtest.Register("start-run", StartRun, "dismiss the title and start a run");
    ///     Playtest.Register("go-to", arg => GoTo(arg), "go-to &lt;room&gt;: walk to a room by name");
    ///     Playtest.SnapshotProvider = () => $"room={Rooms.Current} hp={Player.Hp} enemies={Enemies.Count}";
    /// }
    /// static IEnumerator StartRun() { ...; yield return null; Playtest.Done("run started"); }
    /// </code>
    /// Then: <c>Playtest.Run("start-run")</c>, poll <see cref="Status"/> ("busy: …" → "done: …" / "failed: …"),
    /// <c>Playtest.Snapshot()</c>, <c>Playtest.Steps()</c>. Built in: <c>wait &lt;seconds&gt;</c>,
    /// <c>timescale &lt;value&gt;</c>, <c>shot &lt;name&gt;</c>. Steps run only in the editor and development builds.
    /// </summary>
    public static class Playtest
    {
        class Step { public string help; public Func<string, IEnumerator> run; }

        static readonly Dictionary<string, Step> steps = new Dictionary<string, Step>(StringComparer.OrdinalIgnoreCase);
        static Runner runner;
        static string current;

        /// <summary>"idle", "busy: step", "done: step — what happened", "failed: step — why".</summary>
        public static string Status { get; private set; } = "idle";
        public static bool Busy => Status.StartsWith("busy");

        /// <summary>Your game's state in one line (room, player, enemies, menus…), appended to <see cref="Snapshot"/>.</summary>
        public static Func<string> SnapshotProvider;

        /// <summary>Where <c>shot</c> writes (Temp/UnityWorkflow/Shots in the editor, persistent data in a build).</summary>
        public static string ShotsFolder => Application.isEditor
            ? Path.GetFullPath("Temp/UnityWorkflow/Shots")
            : Path.Combine(Application.persistentDataPath, "UnityWorkflowShots");

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
        static void ResetStatics()
        {
            steps.Clear();
            SnapshotProvider = null;
            Status = "idle";
            current = null;
            runner = null;
            Register("wait", arg => Wait(arg), "wait <seconds>: let the game run (real time)");
            Register("timescale", arg => SetTimeScale(arg), "timescale <value>: speed the game up or slow it down");
            Register("shot", arg => Shot(arg), "shot <name>: screenshot the game view to " + "Temp/UnityWorkflow/Shots/<name>.png");
        }

        public static void Register(string name, Func<string, IEnumerator> run, string help = "") =>
            steps[name] = new Step { run = run, help = help };

        public static void Register(string name, Func<IEnumerator> run, string help = "") => Register(name, _ => run(), help);

        /// <summary>Every registered step with its help line.</summary>
        public static string Steps() =>
            string.Join("\n", steps.OrderBy(s => s.Key).Select(s => s.Key + (string.IsNullOrEmpty(s.Value.help) ? "" : " — " + s.Value.help)));

        /// <summary>Starts a step; returns at once. "name" or "name argument".</summary>
        public static string Run(string nameAndArg)
        {
#if UNITY_EDITOR || DEVELOPMENT_BUILD
            if (!Application.isPlaying) return "not playing";
            if (Busy) return Status;
            string name = nameAndArg.Trim(), arg = null;
            int space = name.IndexOf(' ');
            if (space > 0) { arg = name.Substring(space + 1).Trim(); name = name.Substring(0, space); }
            if (!steps.TryGetValue(name, out Step step)) return $"no step '{name}'. Steps:\n{Steps()}";
            if (runner == null)
            {
                var go = new GameObject("Playtest Runner") { hideFlags = HideFlags.HideInHierarchy };
                UnityEngine.Object.DontDestroyOnLoad(go);
                runner = go.AddComponent<Runner>();
            }
            current = name;
            Status = "busy: " + nameAndArg;
            runner.StartCoroutine(Wrap(name, step.run(arg)));
            return Status;
#else
            return "playtest steps are disabled in release builds";
#endif
        }

        /// <summary>Call from a step when it has done its job (optional: a step that ends without failing is "done").</summary>
        public static void Done(string what) => Status = $"done: {current} — {what}";

        /// <summary>Call from a step when it cannot go on; then <c>yield break</c>.</summary>
        public static void Fail(string why)
        {
            Status = $"failed: {current} — {why}";
            Debug.LogWarning("[Playtest] " + Status);
        }

        /// <summary>The game right now in one line: time, scenes, speed, frame rate, then the game's own snapshot.</summary>
        public static string Snapshot()
        {
            if (!Application.isPlaying) return "not playing";
            var sb = new StringBuilder();
            sb.Append($"t={Time.time:0.0}s scenes=[");
            for (int i = 0; i < SceneManager.sceneCount; i++) sb.Append(i > 0 ? ", " : "").Append(SceneManager.GetSceneAt(i).name);
            sb.Append($"] timeScale={Time.timeScale:0.##} fps={1f / Mathf.Max(0.0001f, Time.unscaledDeltaTime):0}");
            if (SnapshotProvider != null)
            {
                try { sb.Append(" | ").Append(SnapshotProvider()); }
                catch (Exception e) { sb.Append(" | snapshot failed: ").Append(e.Message); }
            }
            return sb.Append(" | ").Append(Status).ToString();
        }

        static IEnumerator Wrap(string name, IEnumerator routine)
        {
            while (true)
            {
                object next;
                try
                {
                    if (!routine.MoveNext()) break;
                    next = routine.Current;
                }
                catch (Exception e)
                {
                    Fail(e.GetType().Name + ": " + e.Message);
                    Debug.LogException(e);
                    yield break;
                }
                if (Status.StartsWith("failed")) yield break;
                yield return next;
            }
            if (Busy) Status = $"done: {name}";
        }

        static IEnumerator Wait(string arg)
        {
            float seconds = float.TryParse(arg, System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out float s) ? s : 1f;
            yield return new WaitForSecondsRealtime(seconds);
            Done($"waited {seconds:0.#} s");
        }

        static IEnumerator SetTimeScale(string arg)
        {
            if (!float.TryParse(arg, System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out float value) || value < 0f)
            {
                Fail("timescale needs a number ≥ 0");
                yield break;
            }
            Time.timeScale = value;
            yield return null;
            Done($"timeScale {value}");
        }

        static IEnumerator Shot(string arg)
        {
            string name = string.IsNullOrWhiteSpace(arg) ? DateTime.Now.ToString("HHmmss") : arg.Trim();
            foreach (char c in Path.GetInvalidFileNameChars()) name = name.Replace(c, '_');
            Directory.CreateDirectory(ShotsFolder);
            string path = Path.Combine(ShotsFolder, name + ".png");
            if (File.Exists(path)) File.Delete(path);
            yield return new WaitForEndOfFrame();
            ScreenCapture.CaptureScreenshot(path);
            float until = Time.realtimeSinceStartup + 5f;
            while (!File.Exists(path) && Time.realtimeSinceStartup < until) yield return null;
            if (File.Exists(path)) Done(path);
            else Fail("no screenshot written (is the Game view visible and the editor focused?)");
        }

        sealed class Runner : MonoBehaviour { }
    }
}
