"""unity-workflow editor guard (PreToolUse on Unity MCP tools and on script edits).

Stops one session from breaking another's work in a shared Unity editor:
- entering / stopping / pausing play, recompiling (refresh, script tools, tests), loading or saving scenes: refused
  while another Claude session holds the editor, or while the editor is playing a session no Claude session started
  (that is the user playing);
- entering play takes the lock for this session; it is released when that play ends (or expires);
- a session can claim the editor for other long work with a marker in an execute_code call:
    // unity-workflow:claim <minutes> <why>        and later        // unity-workflow:release
- scene/asset edits and script saves during someone else's session are allowed, with a warning.
Reads Temp/UnityWorkflow/editor-state.json (the Unity package's beacon) and writes editor-lock.json. Fails open: if
it can't tell, it allows and says so.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import editor_lock as L  # noqa: E402

READ_ONLY = {"read_console", "find_gameobjects", "find_in_file", "get_sha", "get_test_job", "unity_docs", "unity_reflect",
             "debug_request_context", "validate_script", "manage_script_capabilities", "set_active_instance"}
SCRIPT_TOOLS = {"create_script", "delete_script", "script_apply_edits", "apply_text_edits", "manage_script"}
RELOAD_TOOLS = {"refresh_unity", "manage_packages", "manage_build"} | SCRIPT_TOOLS
SCENE_WRITE_ACTIONS = {"load", "create", "save", "close", "open", "new", "set_active"}

DEFAULT_PATTERNS = {
    "playStart": [r"EnterPlaymode\s*\(", r"isPlaying\s*=\s*true", r"ExecuteMenuItem\(\s*\"Edit/Play\"", r"PlaySession\.Play\s*\(",
                  r"PerfCheck\.StartRun\s*\("],
    "playStop": [r"ExitPlaymode\s*\(", r"isPlaying\s*=\s*false", r"PlaySession\.Stop\s*\(", r"isPaused\s*=\s*true"],
    "reload": [r"RequestScriptCompilation", r"AssetDatabase\.Refresh\s*\(", r"RequestScriptReload", r"ImportAsset\([^)]*\.cs\b"],
}
CLAIM = re.compile(r"unity-workflow:claim(?:\s+(\d+))?(?:\s+([^\n\r*]*))?")
RELEASE = re.compile(r"unity-workflow:release")


def config_patterns(root):
    pats = {k: list(v) for k, v in DEFAULT_PATTERNS.items()}
    cfg = L.read_json(os.path.join(root, ".claude", "unity-workflow.json")) or {}
    extra = cfg.get("editorLock", {})
    for key in pats:
        pats[key] += extra.get(key + "Patterns", [])
    return pats, int(extra.get("playLockMinutes", L.PLAY_LOCK_MINUTES))


def classify(tool, tin, pats):
    """('read'|'edit'|'scene'|'reload'|'play'|'stop'|'claim'|'release', detail)"""
    short = tool.split("__")[-1]
    action = str(tin.get("action", "")).lower()
    if short in READ_ONLY:
        return "read", ""
    if short == "manage_editor":
        if action in ("play", "enter_play", "enter_play_mode"):
            return "play", "manage_editor play"
        if action in ("stop", "pause", "exit_play", "exit_play_mode"):
            return "stop", "manage_editor " + action
        return "read" if action.startswith(("get", "telemetry")) else "edit", action
    if short == "run_tests":
        return ("play", "PlayMode tests") if str(tin.get("mode", "EditMode")).lower() == "playmode" else ("reload", "EditMode tests")
    if short in RELOAD_TOOLS:
        if short == "manage_script" and action in ("read", "get", "get_sha", "validate"):
            return "read", ""
        if short == "refresh_unity" and tin.get("compile", "none") == "none" and tin.get("scope") == "assets":
            return "edit", "asset refresh"
        return "reload", short + (" " + action if action else "")
    if short == "manage_scene":
        return ("scene", "manage_scene " + action) if action in SCENE_WRITE_ACTIONS else ("read", "")
    if short == "execute_code":
        code = str(tin.get("code", ""))
        if tin.get("action", "execute") != "execute":
            return "read", ""
        if RELEASE.search(code):
            return "release", ""
        m = CLAIM.search(code)
        if m:
            return "claim", m.group(0)
        if any(re.search(p, code) for p in pats["playStart"]):
            return "play", "execute_code (enters play)"
        if any(re.search(p, code) for p in pats["playStop"]):
            return "stop", "execute_code (stops/pauses play)"
        if any(re.search(p, code) for p in pats["reload"]):
            return "reload", "execute_code (recompile/refresh)"
        return "edit", "execute_code"
    if short.startswith(("manage_", "create_", "delete_")) and not action.startswith(("get", "find", "read", "list", "search")):
        return "edit", short + (" " + action if action else "")
    return "read", ""


def out(decision=None, reason=None, context=None):
    o = {"hookEventName": "PreToolUse"}
    if decision:
        o["permissionDecision"] = decision
        if reason:
            o["permissionDecisionReason"] = reason
    if context:
        o["additionalContext"] = context
    print(json.dumps({"hookSpecificOutput": o}))
    return 0


def guard_mcp(data, root):
    me = data.get("session_id", "")
    tool, tin = data.get("tool_name", ""), data.get("tool_input", {}) or {}
    pats, play_minutes = config_patterns(root)
    tier, detail = classify(tool, tin, pats)
    if tier == "read":
        return 0
    state = L.read_state(root)
    lock = L.read_lock(root, state)
    mine = bool(lock) and lock.get("session") == me
    other = bool(lock) and not mine
    playing = bool(state and state.get("isPlaying"))
    user_playing = playing and not lock   # playing, and no Claude session holds the editor
    who = L.describe(lock)
    if mine:
        L.renew(root, lock)

    if tier == "release":
        if mine:
            L.remove_lock(root)
            return out(context="unity-workflow: editor lock released.")
        return out(context="unity-workflow: nothing to release (" + who + ").")
    if tier == "claim":
        if other:
            return out("deny", f"The Unity editor is {who}. Wait for it (ask the user, or check `editor_lock.py status`), "
                               "don't work around the lock.")
        m = CLAIM.search(str(tin.get("code", "")))
        minutes = int(m.group(1)) if m and m.group(1) else 20
        purpose = (m.group(2) or "").strip() if m else ""
        L.write_lock(root, me, "claim", purpose or "claimed", min(minutes, 120), data.get("cwd", ""))
        return out(context=f"unity-workflow: editor claimed for {min(minutes, 120)} min. Release it with an execute_code "
                           "call containing `// unity-workflow:release` when done.")

    if tier in ("play", "stop", "reload", "scene"):
        if other:
            return out("deny", f"Not now: the Unity editor is {who}. Running `{detail}` would break that session. Wait "
                               "for it to finish (or ask the user); a lock that is no longer needed expires on its own.")
        if user_playing and tier != "play":
            return out("deny", f"Not now: the editor is in play mode and no Claude session started it, so the user is "
                               f"probably playing. `{detail}` would reload scripts or end their session. Ask the user first.")
        if tier == "play":
            if playing:
                return out("deny", "The editor is already in play mode" + (" (your session)." if mine else
                                   " (not started by this session: probably the user). Ask before taking it over."))
            L.write_lock(root, me, "play", detail, play_minutes, data.get("cwd", ""))
            note = "" if state else " Editor state unknown (" + L.describe_state(None) + "): the lock still holds for other Claude sessions."
            return out(context="unity-workflow: editor lock taken for this play session; it frees itself when play ends." + note)
        if tier == "reload" and mine and playing:
            return out(context="unity-workflow: you are recompiling during your own play session; scripts reload mid-play "
                               "(statics reset, references can go null). Stop play first unless that is intended.")
        if state is None and tier in ("reload", "stop"):
            return out(context="unity-workflow: " + L.describe_state(None) + "; can't tell whether the user is playing.")
        return 0

    # tier == "edit": allowed, with a warning when it lands in someone else's session
    if other or user_playing:
        whose = who if other else "the user's play session"
        return out(context=f"unity-workflow: careful, this edits the editor while it is {whose}. In play mode, scene "
                           "edits are lost when play stops; prefer to wait.")
    return 0


def guard_script_edit(data, root):
    path = (data.get("tool_input", {}) or {}).get("file_path", "")
    if not path.endswith((".cs", ".asmdef", ".asmref")):
        return 0
    state = L.read_state(root)
    lock = L.read_lock(root, state)
    me = data.get("session_id", "")
    other = bool(lock) and lock.get("session") != me
    user_playing = bool(state and state.get("isPlaying")) and not lock
    if not (other or user_playing):
        return 0
    recompiles_mid_play = bool(state) and state.get("scriptChangesWhilePlaying", 0) == 0
    whose = L.describe(lock) if other else "in a play session no Claude session started (probably the user)"
    msg = f"unity-workflow: the Unity editor is {whose}. Saving scripts now makes Unity recompile when it next refreshes"
    msg += (", and it is set to 'Recompile And Continue Playing', so a running game reloads mid-session (statics reset, "
            "references go null)." if recompiles_mid_play else ".")
    msg += " Prefer to finish the edit after that session, or tell the user."
    return out(context=msg)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    tool = data.get("tool_name", "")
    if tool.startswith("mcp__"):
        root = L.find_unity_root(data.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR"))
        return guard_mcp(data, root) if root else 0
    if tool in ("Edit", "Write", "MultiEdit"):
        path = (data.get("tool_input", {}) or {}).get("file_path", "")
        root = L.find_unity_root(os.path.dirname(path)) if path else None
        return guard_script_edit(data, root) if root else 0
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:   # a guard must never break the tool call it watches
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                 "additionalContext": f"unity-workflow editor guard error (ignored): {e}"}}))
        sys.exit(0)
