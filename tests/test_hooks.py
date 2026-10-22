"""Tests for the unity-workflow hooks (stdlib only):  python tests/test_hooks.py

Builds throwaway Unity projects in a temp folder, writes fake editor-state / lock files, pipes hook JSON into the
hook scripts exactly as Claude Code does, and checks the decisions.
"""
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS = os.path.join(ROOT, "plugin", "hooks")
GUARD = os.path.join(HOOKS, "editor_guard.py")
LINT = os.path.join(HOOKS, "unity_lint.py")
ME, OTHER = "session-me-1234", "session-other-5678"


def save_json(obj, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


def save_text(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def utc(seconds_ago=0):
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=seconds_ago)).isoformat()


class Project:
    def __init__(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = self.dir.name
        for d in ("Assets/Scripts", "ProjectSettings", "Temp/UnityWorkflow", ".claude"):
            os.makedirs(os.path.join(self.root, d), exist_ok=True)

    def path(self, *p):
        return os.path.join(self.root, *p)

    def state(self, playing=False, owner="", entered=None, exited=None, beat_ago=1, recompile_mid_play=0, compiling=False):
        s = {"isPlaying": playing, "isPaused": False, "isCompiling": compiling, "isUpdating": False, "focused": True,
             "playOwner": owner, "playEnteredUtc": entered or "", "playExitedUtc": exited or "",
             "heartbeatUtc": utc(beat_ago), "projectPath": self.root, "scriptChangesWhilePlaying": recompile_mid_play,
             "unityPid": 1}
        save_json(s, self.path("Temp/UnityWorkflow/editor-state.json"))

    def lock(self, session, kind="play", acquired_ago=10, expires_in=600):
        save_json({"session": session, "kind": kind, "purpose": "test", "cwd": self.root, "acquiredUtc": utc(acquired_ago),
                   "expiresUtc": utc(-expires_in)}, self.path("Temp/UnityWorkflow/editor-lock.json"))

    def read_lock(self):
        try:
            with open(self.path("Temp/UnityWorkflow/editor-lock.json"), encoding="utf-8") as f:
                return json.load(f)
        except OSError:
            return None

    def close(self):
        self.dir.cleanup()


def run(script, payload, *args):
    p = subprocess.run([sys.executable, script, *args], input=json.dumps(payload), capture_output=True, text=True, timeout=20)
    out = p.stdout.strip()
    return json.loads(out) if out else {}


def mcp(project, tool, session=ME, **tool_input):
    return run(GUARD, {"session_id": session, "cwd": project.root, "hook_event_name": "PreToolUse",
                       "tool_name": "mcp__UnityMCP__" + tool, "tool_input": tool_input})


def decision(result):
    return result.get("hookSpecificOutput", {}).get("permissionDecision", "allow")


def context(result):
    return result.get("hookSpecificOutput", {}).get("additionalContext", "")


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.p = Project()

    def tearDown(self):
        self.p.close()

    def test_reads_always_allowed(self):
        self.p.state(playing=True)
        self.assertEqual(mcp(self.p, "read_console", action="get"), {})
        self.assertEqual(mcp(self.p, "execute_code", action="get_history"), {})

    def test_user_playing_blocks_compile_stop_and_play(self):
        self.p.state(playing=True)                      # playing, no Claude lock: the user
        self.assertEqual(decision(mcp(self.p, "refresh_unity", compile="request")), "deny")
        self.assertEqual(decision(mcp(self.p, "manage_editor", action="stop")), "deny")
        self.assertEqual(decision(mcp(self.p, "execute_code", code="UnityEditor.EditorApplication.ExitPlaymode();")), "deny")
        self.assertEqual(decision(mcp(self.p, "execute_code", code="UnityWorkflow.Editor.PlaySession.Play();")), "deny")
        self.assertEqual(decision(mcp(self.p, "run_tests", mode="EditMode")), "deny")
        self.assertEqual(decision(mcp(self.p, "manage_scene", action="load", name="X")), "deny")

    def test_user_playing_edits_warn_only(self):
        self.p.state(playing=True)
        r = mcp(self.p, "manage_gameobject", action="modify", target="Cube")
        self.assertEqual(decision(r), "allow")
        self.assertIn("user's play session", context(r))

    def test_free_editor_play_takes_lock_and_other_session_is_refused(self):
        self.p.state(playing=False)
        r = mcp(self.p, "execute_code", code="UnityWorkflow.Editor.PlaySession.Play(); return \"ok\";")
        self.assertEqual(decision(r), "allow")
        self.assertEqual(self.p.read_lock()["session"], ME)
        self.p.state(playing=True, owner="playtest", entered=utc(1))
        other = mcp(self.p, "refresh_unity", session=OTHER, compile="request")
        self.assertEqual(decision(other), "deny")
        self.assertIn("held by session", other["hookSpecificOutput"]["permissionDecisionReason"])
        # the holder may stop its own play
        self.assertEqual(decision(mcp(self.p, "manage_editor", action="stop")), "allow")

    def test_own_compile_during_own_play_warns(self):
        self.p.lock(ME)
        self.p.state(playing=True, owner="me", entered=utc(5))
        r = mcp(self.p, "refresh_unity", compile="request")
        self.assertEqual(decision(r), "allow")
        self.assertIn("your own play session", context(r))

    def test_play_lock_freed_when_play_ended(self):
        self.p.lock(OTHER, acquired_ago=120)
        self.p.state(playing=False, entered=utc(110), exited=utc(5))
        self.assertEqual(decision(mcp(self.p, "refresh_unity", compile="request")), "allow")
        self.assertIsNone(self.p.read_lock())

    def test_play_lock_freed_when_play_never_started(self):
        self.p.lock(OTHER, acquired_ago=200)
        self.p.state(playing=False, entered=utc(5000))
        self.assertEqual(decision(mcp(self.p, "refresh_unity", compile="request")), "allow")

    def test_expired_lock_is_ignored(self):
        self.p.lock(OTHER, kind="claim", expires_in=-5)
        self.p.state(playing=False)
        self.assertEqual(decision(mcp(self.p, "refresh_unity", compile="request")), "allow")

    def test_claim_and_release(self):
        self.p.state(playing=False)
        r = mcp(self.p, "execute_code", code="// unity-workflow:claim 25 batch edit of prefabs\nreturn 1;")
        self.assertIn("claimed for 25 min", context(r))
        self.assertEqual(self.p.read_lock()["kind"], "claim")
        self.assertEqual(decision(mcp(self.p, "refresh_unity", session=OTHER, compile="request")), "deny")
        self.assertEqual(decision(mcp(self.p, "execute_code", session=OTHER, code="// unity-workflow:claim\n")), "deny")
        mcp(self.p, "execute_code", code="// unity-workflow:release\nreturn 1;")
        self.assertIsNone(self.p.read_lock())

    def test_unknown_state_still_protects_sessions_and_notes_it(self):
        self.p.state(playing=True, beat_ago=120)        # stale beacon = unknown
        r = mcp(self.p, "refresh_unity", compile="request")
        self.assertEqual(decision(r), "allow")
        self.assertIn("state unknown", context(r))
        self.p.lock(OTHER, kind="claim")
        self.assertEqual(decision(mcp(self.p, "refresh_unity", compile="request")), "deny")

    def test_project_play_pattern(self):
        save_json({"editorLock": {"playStartPatterns": ["MyBot\\.Launch\\("]}}, self.p.path(".claude/unity-workflow.json"))
        self.p.state(playing=True)
        self.assertEqual(decision(mcp(self.p, "execute_code", code="MyBot.Launch(); return 1;")), "deny")

    def test_script_save_during_user_play_warns(self):
        self.p.state(playing=True, recompile_mid_play=0)
        r = run(GUARD, {"session_id": ME, "tool_name": "Write",
                        "tool_input": {"file_path": self.p.path("Assets/Scripts/A.cs"), "content": "class A {}"}})
        self.assertEqual(decision(r), "allow")
        self.assertIn("Recompile And Continue Playing", context(r))
        self.p.state(playing=False)
        self.assertEqual(run(GUARD, {"session_id": ME, "tool_name": "Write",
                                     "tool_input": {"file_path": self.p.path("Assets/Scripts/A.cs")}}), {})

    def test_outside_a_unity_project_is_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(run(GUARD, {"session_id": ME, "cwd": d, "tool_name": "mcp__UnityMCP__refresh_unity",
                                         "tool_input": {}}), {})


class LintTests(unittest.TestCase):
    def setUp(self):
        self.p = Project()

    def tearDown(self):
        self.p.close()

    def write(self, rel, text):
        path = self.p.path(rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        save_text(path, text)
        return path

    def notes(self, path, tool="Write", **extra):
        r = run(LINT, {"tool_name": tool, "tool_input": dict(file_path=path, **extra)})
        return context(r)

    def test_generic_rules(self):
        path = self.write("Assets/Scripts/P.cs", "using UnityEngine;\npublic class MenuItem : MonoBehaviour\n{\n"
                          "    void Update()\n    {\n        Instantiate(gameObject);\n        var c = GetComponent<Rigidbody>();\n"
                          "        string s = \"GetComponent<X> in a string\";\n    }\n}\n")
        n = self.notes(path)
        self.assertIn("global namespace", n)
        self.assertIn("shadows a UnityEditor attribute", n)
        self.assertIn("Instantiate in Update", n)
        self.assertIn("GetComponent in Update", n)
        self.assertEqual(n.count("GetComponent"), 1)    # the string literal is not code

    def test_only_added_lines(self):
        path = self.write("Assets/Scripts/Q.cs", "namespace G {\nclass Q : UnityEngine.MonoBehaviour {\n void Update() {\n"
                          "  Instantiate(gameObject);\n  var x = 1;\n }\n}\n}\n")
        self.assertEqual(self.notes(path, tool="Edit", old_string="a", new_string="  var x = 1;"), "")

    def test_editor_and_dev_folders(self):
        path = self.write("Assets/Scripts/Editor/E.cs", "using UnityEditor;\nclass E { void Update() { Object.Instantiate(null); } }\n")
        self.assertEqual(self.notes(path), "")
        path = self.write("Assets/Scripts/Dev/D.cs", "namespace G { class D { void Update() { if (UnityEngine.Input.GetKeyDown(0)) {} } } }\n")
        self.assertNotIn("raw key read", self.notes(path))

    def test_generated_paths_denied(self):
        save_json({"lint": {"generatedPaths": ["Assets/Gen/*"], "generatedHint": "edit the JSON"}},
                  self.p.path(".claude/unity-workflow.json"))
        r = run(LINT, {"tool_name": "Write", "tool_input": {"file_path": self.p.path("Assets/Gen/x.asset")}}, "--pre")
        self.assertEqual(decision(r), "deny")
        self.assertIn("edit the JSON", r["hookSpecificOutput"]["permissionDecisionReason"])

    def test_banned_text_with_json_backspace_mistake(self):
        # "\b" here is a backspace character, exactly what a hand-written JSON "\bperfect\b" turns into
        save_json({"lint": {"bannedText": [{"pattern": "\bperfect\b", "in": "string", "message": "no Perfect"}]}},
                  self.p.path(".claude/unity-workflow.json"))
        path = self.write("Assets/Scripts/T.cs", "namespace G { class T { string s = \"Perfect Dodge!\"; } }\n")
        self.assertIn("no Perfect", self.notes(path))


if __name__ == "__main__":
    unittest.main(verbosity=2)
