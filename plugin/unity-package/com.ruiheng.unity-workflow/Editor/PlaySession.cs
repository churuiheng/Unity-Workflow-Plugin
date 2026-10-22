using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace UnityWorkflow.Editor
{
    /// <summary>
    /// Plays the game the way a player starts it, for the unity-workflow "playtest" skill (Unity MCP execute_code) and
    /// Tools ▸ Unity Workflow: from the project's start scene, with its save files backed up and put back when play
    /// stops, and with the play session marked as a tool's (not the user's) so the editor-lock hook can tell them apart.
    ///
    /// Config (.claude/unity-workflow.json): "playtest": { "startScene": "Assets/Scenes/Boot.unity",
    ///   "saveFiles": ["{persistentDataPath}/save.json"] }   tokens: {persistentDataPath}, {dataPath}, {projectPath}
    /// </summary>
    public static class PlaySession
    {
        const string BackupKey = "UnityWorkflow.Play.backup";          // JSON list of original → backup ("" = did not exist)
        const string StartSceneKey = "UnityWorkflow.Play.prevStartScene";
        static string BackupDir => Path.GetFullPath("Temp/UnityWorkflow/SaveBackup");

        [Serializable] class Config { public PlaytestConfig playtest = new PlaytestConfig(); }
        [Serializable] class PlaytestConfig { public string startScene = ""; public string[] saveFiles = new string[0]; }
        [Serializable] class Backup { public List<string> originals = new List<string>(); public List<string> copies = new List<string>(); }

        static PlaytestConfig LoadConfig()
        {
            try
            {
                string p = Path.Combine(".claude", "unity-workflow.json");
                if (File.Exists(p)) return JsonUtility.FromJson<Config>(File.ReadAllText(p)).playtest ?? new PlaytestConfig();
            }
            catch (Exception e) { Debug.LogWarning("[PlaySession] .claude/unity-workflow.json: " + e.Message); }
            return new PlaytestConfig();
        }

        [MenuItem("Tools/Unity Workflow/Play From Start Scene (Keep Saves)")]
        static void PlayMenu() => Debug.Log("[PlaySession] " + Play(owner: "menu"));

        /// <summary>
        /// Enters play from <paramref name="startScene"/> (default: config playtest.startScene; none = the open scene).
        /// Returns "starting", or why it did not. <paramref name="owner"/> names who is playing (shown to other sessions).
        /// With unsaved scenes open, entering play from another start scene makes Unity ask to save them; that is refused
        /// unless <paramref name="allowSaveDialog"/> (then dismiss it with the skill's dialog helper: Cancel keeps the edits).
        /// </summary>
        public static string Play(string startScene = null, string owner = "claude", bool allowSaveDialog = false)
        {
            if (EditorApplication.isPlayingOrWillChangePlaymode) return "already playing" + Owner();
            if (EditorApplication.isCompiling || EditorApplication.isUpdating) return "busy compiling/importing: try again in a moment";

            PlaytestConfig cfg = LoadConfig();
            string scenePath = string.IsNullOrEmpty(startScene) ? cfg.startScene : startScene;
            SceneAsset scene = null;
            if (!string.IsNullOrEmpty(scenePath))
            {
                scene = AssetDatabase.LoadAssetAtPath<SceneAsset>(scenePath);
                if (scene == null) return "no scene at " + scenePath;
                var dirty = Enumerable.Range(0, SceneManager.sceneCount).Select(SceneManager.GetSceneAt)
                    .Where(s => s.isDirty).Select(s => string.IsNullOrEmpty(s.path) ? "(untitled)" : s.path).ToList();
                if (dirty.Count > 0 && !allowSaveDialog)
                    return "blocked: unsaved changes in " + string.Join(", ", dirty) + ". Entering play from " + scenePath +
                           " makes Unity ask to save them. Ask the user to save (never save or discard their edits yourself), " +
                           "or retry with allowSaveDialog: true and dismiss the dialog with Cancel.";
            }

            BackUp(cfg.saveFiles);
            if (scene != null)
            {
                SessionState.SetString(StartSceneKey, EditorSceneManager.playModeStartScene != null ? AssetDatabase.GetAssetPath(EditorSceneManager.playModeStartScene) : "");
                EditorSceneManager.playModeStartScene = scene;
            }
            EditorStateBeacon.SetPlayOwner(owner);
            EditorApplication.EnterPlaymode();   // deferred by Unity: this call returns first
            return "starting" + (scene != null ? " from " + scenePath : "") + (cfg.saveFiles.Length > 0 ? $", {cfg.saveFiles.Length} save file(s) backed up" : "");
        }

        /// <summary>Stops play; saves and the start scene are put back automatically.</summary>
        public static string Stop()
        {
            if (!EditorApplication.isPlaying) return "not playing";
            EditorApplication.ExitPlaymode();
            return "stopping";
        }

        /// <summary>One line: editor state, who is playing, and (in play) <see cref="UnityWorkflow.Playtest.Snapshot"/>.</summary>
        public static string State() =>
            (EditorApplication.isPlaying ? "playing" + Owner() + (EditorApplication.isPaused ? " (paused)" : "") : "not playing") +
            (EditorApplication.isCompiling ? ", compiling" : "") +
            (EditorApplication.isPlaying ? " | " + UnityWorkflow.Playtest.Snapshot() : "");

        static string Owner()
        {
            string o = SessionState.GetString(EditorStateBeacon.PlayOwnerKey, "");
            return o == "" ? " (by the user)" : $" (by {o})";
        }

        // ------------------------------------------------------------------ save files

        static string Expand(string path) => path
            .Replace("{persistentDataPath}", Application.persistentDataPath)
            .Replace("{dataPath}", Application.dataPath)
            .Replace("{projectPath}", Path.GetDirectoryName(Application.dataPath));

        static void BackUp(string[] files)
        {
            var b = new Backup();
            if (files != null && files.Length > 0)
            {
                Directory.CreateDirectory(BackupDir);
                for (int i = 0; i < files.Length; i++)
                {
                    string original = Path.GetFullPath(Expand(files[i]));
                    string copy = "";
                    if (File.Exists(original))
                    {
                        copy = Path.Combine(BackupDir, i + "_" + Path.GetFileName(original));
                        File.Copy(original, copy, true);
                    }
                    b.originals.Add(original);
                    b.copies.Add(copy);
                }
            }
            SessionState.SetString(BackupKey, JsonUtility.ToJson(b));
        }

        [InitializeOnLoadMethod]
        static void RestoreAfterPlay()
        {
            EditorApplication.playModeStateChanged += change =>
            {
                if (change != PlayModeStateChange.EnteredEditMode) return;
                string prev = SessionState.GetString(StartSceneKey, null);
                if (prev != null)
                {
                    EditorSceneManager.playModeStartScene = prev == "" ? null : AssetDatabase.LoadAssetAtPath<SceneAsset>(prev);
                    SessionState.EraseString(StartSceneKey);
                }
                string json = SessionState.GetString(BackupKey, "");
                if (json == "") return;
                SessionState.EraseString(BackupKey);
                var b = JsonUtility.FromJson<Backup>(json);
                int restored = 0;
                for (int i = 0; i < b.originals.Count; i++)
                {
                    try
                    {
                        if (b.copies[i] != "" && File.Exists(b.copies[i])) { File.Copy(b.copies[i], b.originals[i], true); restored++; }
                        else if (b.copies[i] == "" && File.Exists(b.originals[i])) { File.Delete(b.originals[i]); restored++; }   // the run created it
                    }
                    catch (Exception e) { Debug.LogWarning($"[PlaySession] could not restore {b.originals[i]}: {e.Message}"); }
                }
                if (b.originals.Count > 0) Debug.Log($"[PlaySession] {restored}/{b.originals.Count} save file(s) back as they were before play.");
            };
        }
    }
}
