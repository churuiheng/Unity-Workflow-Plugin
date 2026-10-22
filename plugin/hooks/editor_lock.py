"""unity-workflow editor lock: who may compile, enter or stop play in a Unity editor right now.

Two files under <unity project>/Temp/UnityWorkflow/ (Temp is per-machine and never committed):
  editor-state.json  written by the Unity package (EditorStateBeacon): playing / compiling / who started play / heartbeat
  editor-lock.json   written by the editor-guard hook: which Claude session holds the editor, why, and until when

CLI (for people and skills; claims themselves are made through Unity MCP calls, see the editor-lock skill):
  python editor_lock.py status [project-dir]
  python editor_lock.py release --force [project-dir]     # only with the user's OK: frees a lock another session holds
"""
import datetime as dt
import json
import os
import sys

STATE_FRESH_SECONDS = 20
PLAY_LOCK_MINUTES = 45
RENEW_MINUTES = 15


def now():
    return dt.datetime.now(dt.timezone.utc)


def parse(ts):
    if not ts:
        return None
    try:
        t = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def iso(t):
    return t.isoformat()


def find_unity_root(start):
    """The Unity project at or above start, else one or two levels below it."""
    if not start:
        return None
    d = os.path.abspath(start)
    probe = d
    while True:
        if os.path.isdir(os.path.join(probe, "Assets")) and os.path.isdir(os.path.join(probe, "ProjectSettings")):
            return probe
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    for depth1 in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        p1 = os.path.join(d, depth1)
        if not os.path.isdir(p1) or depth1.startswith(".") or depth1 in ("Library", "Temp", "node_modules"):
            continue
        if os.path.isdir(os.path.join(p1, "Assets")) and os.path.isdir(os.path.join(p1, "ProjectSettings")):
            return p1
        for depth2 in sorted(os.listdir(p1)):
            p2 = os.path.join(p1, depth2)
            if os.path.isdir(os.path.join(p2, "Assets")) and os.path.isdir(os.path.join(p2, "ProjectSettings")):
                return p2
    return None


def _dir(root):
    return os.path.join(root, "Temp", "UnityWorkflow")


def read_json(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def read_state(root):
    """The beacon's state, or None when missing or stale (package not installed, Unity closed, busy or behind a dialog)."""
    s = read_json(os.path.join(_dir(root), "editor-state.json"))
    if not s:
        return None
    beat = parse(s.get("heartbeatUtc"))
    if beat is None or (now() - beat).total_seconds() > STATE_FRESH_SECONDS:
        return None
    return s


def read_lock(root, state=None):
    """The live lock, or None. Expired locks, and play locks whose play has ended (or never started), are dropped."""
    path = os.path.join(_dir(root), "editor-lock.json")
    lock = read_json(path)
    if not lock:
        return None
    t = now()
    expires, acquired = parse(lock.get("expiresUtc")), parse(lock.get("acquiredUtc"))
    stale = expires is None or t > expires
    if not stale and lock.get("kind") == "play" and state and acquired and not state.get("isPlaying") and not state.get("isCompiling"):
        exited, entered = parse(state.get("playExitedUtc")), parse(state.get("playEnteredUtc"))
        if exited and exited > acquired:
            stale = True                                   # that play session has ended
        elif (t - acquired).total_seconds() > 90 and not (entered and entered > acquired):
            stale = True                                   # play was asked for but never started
    if stale:
        remove_lock(root)
        return None
    return lock


def write_lock(root, session, kind, purpose, minutes, cwd=""):
    t = now()
    lock = {"session": session, "kind": kind, "purpose": purpose[:160], "cwd": cwd,
            "acquiredUtc": iso(t), "expiresUtc": iso(t + dt.timedelta(minutes=minutes))}
    os.makedirs(_dir(root), exist_ok=True)
    tmp = os.path.join(_dir(root), "editor-lock.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(lock, f, indent=2)
    os.replace(tmp, os.path.join(_dir(root), "editor-lock.json"))
    return lock


def renew(root, lock):
    t = now()
    exp = parse(lock.get("expiresUtc")) or t
    if exp < t + dt.timedelta(minutes=RENEW_MINUTES):
        lock["expiresUtc"] = iso(t + dt.timedelta(minutes=RENEW_MINUTES))
        tmp = os.path.join(_dir(root), "editor-lock.json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(lock, f, indent=2)
        os.replace(tmp, os.path.join(_dir(root), "editor-lock.json"))


def remove_lock(root):
    try:
        os.remove(os.path.join(_dir(root), "editor-lock.json"))
    except OSError:
        pass


def describe(lock):
    if not lock:
        return "free"
    exp = parse(lock.get("expiresUtc"))
    mins = max(0, int((exp - now()).total_seconds() // 60)) if exp else 0
    return f"held by session {lock.get('session', '?')[:8]} ({lock.get('kind')}: {lock.get('purpose') or 'no reason given'}), {mins} min left"


def describe_state(state):
    if state is None:
        return "editor state unknown (unity-workflow package not installed, or Unity closed / busy / behind a dialog)"
    parts = ["playing" + (f" (started by {state['playOwner']})" if state.get("playOwner") else " (started by the user)")
             if state.get("isPlaying") else "not playing"]
    if state.get("isPaused"): parts.append("paused")
    if state.get("isCompiling"): parts.append("compiling")
    if not state.get("focused"): parts.append("in the background")
    return ", ".join(parts)


def main(argv):
    try:
        sys.stdout.reconfigure(errors="replace")   # old Windows consoles can't print every character
    except AttributeError:
        pass
    args = [a for a in argv[1:] if not a.startswith("--")]
    cmd = args[0] if args else "status"
    root = find_unity_root(args[1] if len(args) > 1 else os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    if root is None:
        print("no Unity project found (a folder with Assets/ and ProjectSettings/)")
        return 1
    state = read_state(root)
    lock = read_lock(root, state)
    if cmd == "status":
        print(f"Unity project: {root}\nEditor: {describe_state(state)}\nLock: {describe(lock)}")
        if state and state.get("scriptChangesWhilePlaying", 1) == 0:
            print("Note: Unity is set to 'Recompile And Continue Playing': saving a script during play reloads it mid-session "
                  "(Preferences > General > Script Changes While Playing > Recompile After Finished Playing avoids that).")
        return 0
    if cmd == "release":
        if not lock:
            print("lock already free")
            return 0
        if "--force" not in argv:
            print("refusing: releasing someone else's lock needs --force, and the user's OK. " + describe(lock))
            return 1
        remove_lock(root)
        print("released: " + describe(lock))
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
