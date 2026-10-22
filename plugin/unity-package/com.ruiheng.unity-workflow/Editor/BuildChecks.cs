using System.Collections.Generic;
using UnityEditor;
using UnityEditor.Build.Player;
using UnityEngine;

namespace UnityWorkflow.Editor
{
    /// <summary>
    /// Compiles the project's scripts exactly as a player build would, without building anything. The editor only ever
    /// compiles the editor side of <c>#if UNITY_EDITOR</c> / <c>DEVELOPMENT_BUILD</c>, so player-only code can be broken
    /// without anyone noticing until a build fails. Used by the unity-workflow "verify" skill.
    /// </summary>
    public static class BuildChecks
    {
        [MenuItem("Tools/Unity Workflow/Verify: Release + Development Script Compile")]
        static void Menu() => Debug.Log("[BuildChecks] release: " + PlayerCompile(false) + "\ndevelopment: " + PlayerCompile(true));

        /// <summary>"ok: …" when every script compiles for that player build, else "FAILED: " + the errors.</summary>
        public static string PlayerCompile(bool development, BuildTarget target = BuildTarget.NoTarget)
        {
            if (target == BuildTarget.NoTarget) target = EditorUserBuildSettings.activeBuildTarget;
            var errors = new List<string>();
            void Capture(string message, string stack, LogType type)
            {
                if (type == LogType.Error || type == LogType.Exception) errors.Add(message);
            }

            Application.logMessageReceived += Capture;
            ScriptCompilationResult result;
            try
            {
                var settings = new ScriptCompilationSettings
                {
                    target = target,
                    group = BuildPipeline.GetBuildTargetGroup(target),
                    options = development ? ScriptCompilationOptions.DevelopmentBuild : ScriptCompilationOptions.None,
                };
                result = PlayerBuildInterface.CompilePlayerScripts(settings, "Temp/UnityWorkflow/PlayerCompile");
            }
            finally { Application.logMessageReceived -= Capture; }

            bool built = result.assemblies != null && result.assemblies.Count > 0;
            if (built && errors.Count == 0) return $"ok: {result.assemblies.Count} assemblies compile for a {(development ? "development" : "release")} {target} build";
            return "FAILED: " + (errors.Count > 0 ? string.Join("\n", errors) : "no assemblies produced");
        }
    }
}
