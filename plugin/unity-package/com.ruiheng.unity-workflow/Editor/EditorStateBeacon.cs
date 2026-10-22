using System;
using System.IO;
using UnityEditor;
using UnityEditor.Compilation;
using UnityEditorInternal;
using UnityEngine;

namespace UnityWorkflow.Editor
{
    /// <summary>
    /// Publishes what the editor is doing to Temp/UnityWorkflow/editor-state.json, so tools outside Unity (the
    /// unity-workflow editor-lock hook) can tell whether compiling or entering/stopping play right now would break
    /// someone's session: playing, paused, compiling, who started play, and whether Unity recompiles scripts mid-play.
    /// Written on every play-mode and compile change, and as a heartbeat every few seconds; a stale heartbeat means the
    /// editor is closed, busy or behind a modal dialog.
    /// </summary>
    [InitializeOnLoad]
    public static class EditorStateBeacon
    {
        public const string StatePath = "Temp/UnityWorkflow/editor-state.json";
        /// <summary>SessionState key holding who started the current play session ("" = not a tool: the user).</summary>
        public const string PlayOwnerKey = "UnityWorkflow.playOwner";
        const string PlayEnteredKey = "UnityWorkflow.playEnteredUtc";
        const string PlayExitedKey = "UnityWorkflow.playExitedUtc";
        const double HeartbeatSeconds = 3.0;

        [Serializable]
        class State
        {
            public bool isPlaying, isPaused, isCompiling, isUpdating, focused;
            public string playOwner, playEnteredUtc, playExitedUtc, heartbeatUtc, projectPath;
            /// <summary>Unity's "Script Changes While Playing": 0 recompile and continue, 1 recompile after finished playing, 2 stop playing and recompile.</summary>
            public int scriptChangesWhilePlaying;
            public int unityPid;
        }

        static double nextBeat;
        static bool compiling;

        static EditorStateBeacon()
        {
            EditorApplication.playModeStateChanged += OnPlayModeChanged;
            CompilationPipeline.compilationStarted += _ => { compiling = true; Write(); };
            CompilationPipeline.compilationFinished += _ => { compiling = false; Write(); };
            EditorApplication.update += Tick;
            Write();
        }

        /// <summary>Records who is starting play (a skill or session name); call right before entering play.</summary>
        public static void SetPlayOwner(string owner) => SessionState.SetString(PlayOwnerKey, owner ?? "");

        static void OnPlayModeChanged(PlayModeStateChange change)
        {
            string now = DateTime.UtcNow.ToString("o");
            if (change == PlayModeStateChange.ExitingEditMode) SessionState.SetString(PlayEnteredKey, now);
            if (change == PlayModeStateChange.EnteredEditMode)
            {
                SessionState.SetString(PlayExitedKey, now);
                SessionState.EraseString(PlayOwnerKey);   // the next play is the user's unless a tool says otherwise
            }
            Write();
        }

        static void Tick()
        {
            if (EditorApplication.timeSinceStartup < nextBeat) return;
            nextBeat = EditorApplication.timeSinceStartup + HeartbeatSeconds;
            Write();
        }

        static void Write()
        {
            try
            {
                var s = new State
                {
                    isPlaying = EditorApplication.isPlayingOrWillChangePlaymode,
                    isPaused = EditorApplication.isPaused,
                    isCompiling = compiling || EditorApplication.isCompiling,
                    isUpdating = EditorApplication.isUpdating,
                    focused = InternalEditorUtility.isApplicationActive,
                    playOwner = SessionState.GetString(PlayOwnerKey, ""),
                    playEnteredUtc = SessionState.GetString(PlayEnteredKey, ""),
                    playExitedUtc = SessionState.GetString(PlayExitedKey, ""),
                    heartbeatUtc = DateTime.UtcNow.ToString("o"),
                    projectPath = Path.GetDirectoryName(Application.dataPath),
                    scriptChangesWhilePlaying = EditorPrefs.GetInt("ScriptCompilationDuringPlay", 0),
                    unityPid = System.Diagnostics.Process.GetCurrentProcess().Id,
                };
                Directory.CreateDirectory(Path.GetDirectoryName(StatePath));
                string tmp = StatePath + ".tmp";
                File.WriteAllText(tmp, JsonUtility.ToJson(s, true));
                if (File.Exists(StatePath)) File.Replace(tmp, StatePath, null);   // readers never see a half-written file
                else File.Move(tmp, StatePath);
            }
            catch (IOException) { }   // a reader has it open; the next heartbeat writes it
        }
    }
}
