// Playtest steps for <Game>: named, scriptable ways to drive the game in play mode, used by Claude's
// /unity-workflow:playtest skill (through Unity MCP) and handy for tests. Dev-only: lives in the editor and development
// builds. Put this file in a dev/debug folder of the game's runtime code; if that code has its own asmdef, add a
// reference to UnityWorkflow.Runtime. Replace the commented lines with your game's own calls.
#if UNITY_EDITOR || DEVELOPMENT_BUILD
using System.Collections;
using UnityEngine;
using UnityWorkflow;

namespace MyGame.Dev   // your game's namespace
{
    static class PlaytestSteps
    {
        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Register()
        {
            Playtest.Register("start", StartGame, "leave the title screen and start a game");
            Playtest.Register("go-to", arg => GoTo(arg), "go-to <level>: load a level by name");

            // One line Claude reads to know where the game is: level, player, enemies, open menus. Runs on demand only.
            // Playtest.SnapshotProvider = () => $"level={Levels.Current} hp={Player.Hp} enemies={Enemies.Alive} menu={Menus.Open}";
        }

        static IEnumerator StartGame()
        {
            // Wait for what the step needs, with a timeout, and say why when it can't go on.
            float until = Time.realtimeSinceStartup + 20f;
            while (!TitleReady() && Time.realtimeSinceStartup < until) yield return null;
            if (!TitleReady()) { Playtest.Fail("title screen never appeared"); yield break; }
            // TitleScreen.Instance.Begin();   // drive the game through its own code paths, as a player would
            yield return new WaitForSeconds(0.5f);
            Playtest.Done("game started");
        }

        static IEnumerator GoTo(string level)
        {
            if (string.IsNullOrEmpty(level)) { Playtest.Fail("go-to needs a level name"); yield break; }
            // var op = UnityEngine.SceneManagement.SceneManager.LoadSceneAsync(level);
            // while (!op.isDone) yield return null;
            yield return null;
            Playtest.Done("in " + level);
        }

        static bool TitleReady() => true;   // e.g. TitleScreen.Instance != null && TitleScreen.Instance.isActiveAndEnabled
    }
}
#endif
