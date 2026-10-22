"""unity-workflow guard rails for Claude's edits in a Unity project.

PreToolUse  (--pre): refuses hand edits to paths the project marks as generated (config "generatedPaths").
PostToolUse (default): reads the edited C# (or a configured data file) and reports rule breaks on the lines the
edit ADDED, so legacy code is never nagged about. Warnings go back to Claude as additional context; nothing is
blocked. Stdlib only, fast.

Project config (optional): <unity project>/.claude/unity-workflow.json, see the plugin README. Without it the
generic Unity rules apply.

Test by hand (use a real Windows/posix path to a file inside a Unity project):
  echo '{"tool_name":"Edit","tool_input":{"file_path":"C:/proj/Assets/X.cs","new_string":"..."}}' | python unity_lint.py
"""
import fnmatch
import json
import os
import re
import subprocess
import sys

MAX_NOTES = 12

DEFAULTS = {
    "runtimeRoots": ["Assets/"],                       # where player code lives
    "ignoreDirs": ["/Editor/", "/Tests/", "/Plugins/", "/ThirdParty/", "/Samples/"],
    "devDirs": ["/Dev/", "/Debug/", "/Cheats/"],       # dev-only code: debug keys and logs allowed
    "requireNamespace": True,
    "logHelper": None,                                 # e.g. "Game.Core.GameLog.Info": flags Debug.Log in runtime code
    "poolHelper": None,                                # e.g. "Pool.Spawn": named in the Instantiate warning
    "physicsHelper": None,                             # e.g. "Game.Core.QueryBuffer": named in the physics warning
    "generatedPaths": [],                              # globs (project-relative) Claude must not hand-edit
    "generatedHint": "Edit the source it is generated from instead.",
    "textCheckGlobs": [],                              # extra non-C# files to scan with "bannedText" (e.g. data JSON)
    "bannedText": [],                                  # [{ "pattern": regex, "message": str, "in": "string|code|any" }]
}

GUARD_SYMBOLS = ("UNITY_EDITOR", "DEVELOPMENT_BUILD")
EDITOR_SHADOWS = {"MenuItem", "CustomEditor", "InitializeOnLoad", "CustomPropertyDrawer", "ContextMenu"}
HOT_METHOD = re.compile(r"\bvoid\s+(Update|FixedUpdate|LateUpdate|OnGUI)\s*\(\s*\)")
LINQ_CALL = re.compile(r"(?<!Mathf)(?<!Math)\.(Where|Select|SelectMany|Any|All|First|FirstOrDefault|Last|LastOrDefault|"
                       r"OrderBy|OrderByDescending|ToList|ToArray|ToDictionary|Count|Sum|Max|Min|Average|Distinct)\s*\(")
ALLOC_PHYSICS = re.compile(r"\bPhysics2?D?\.(OverlapSphere|OverlapBox|OverlapCapsule|OverlapCircleAll|OverlapAreaAll|"
                           r"RaycastAll|SphereCastAll|CapsuleCastAll|BoxCastAll|CircleCastAll)\s*\(")
DEBUG_KEY = re.compile(r"\bInput\.GetKey(Down|Up)?\s*\(|\bKeyboard\.current\b")
DEBUG_LOG = re.compile(r"\bDebug\.Log\s*\(")
TYPE_DECL = re.compile(r"^[ \t]*(?:\[[^\]]*\]\s*)*(?:(?:public|internal|private|protected|static|sealed|abstract|partial|readonly)\s+)*"
                       r"(class|struct|interface|enum|record)\s+(\w+)", re.MULTILINE)
STRING_LIT = re.compile(r'"(?:[^"\\\n]|\\.)*"')


def find_unity_root(path):
    d = os.path.dirname(os.path.abspath(path))
    while True:
        if os.path.isdir(os.path.join(d, "Assets")) and os.path.isdir(os.path.join(d, "ProjectSettings")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def load_config(root):
    cfg = dict(DEFAULTS)
    p = os.path.join(root, ".claude", "unity-workflow.json")
    try:
        with open(p, encoding="utf-8-sig") as f:
            user = json.load(f)
        cfg.update({k: v for k, v in user.get("lint", user).items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    return cfg


def matches_any(rel, globs):
    return any(fnmatch.fnmatch(rel, g) or fnmatch.fnmatch(rel, g.rstrip("/") + "/*") for g in globs)


def strip_code(text):
    """Comments and string/char contents become spaces (newlines kept), so braces and patterns are code-only."""
    out = list(text)
    i, n = 0, len(text)

    def blank(a, b):
        for k in range(a, b):
            if out[k] != "\n":
                out[k] = " "

    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":
            j = text.find("\n", i)
            j = n if j < 0 else j
            blank(i, j)
            i = j
        elif c == "/" and nxt == "*":
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            blank(i, j)
            i = j
        elif c == '"' or (c in "$@" and nxt == '"') or (c in "$@" and nxt in "$@" and i + 2 < n and text[i + 2] == '"'):
            start = i
            verbatim = False
            while text[i] != '"':
                verbatim |= text[i] == "@"
                i += 1
            i += 1
            while i < n:
                if verbatim and text[i] == '"' and i + 1 < n and text[i + 1] == '"':
                    i += 2
                    continue
                if not verbatim and text[i] == "\\":
                    i += 2
                    continue
                if text[i] == '"' or (not verbatim and text[i] == "\n"):
                    i += 1
                    break
                i += 1
            marker_end = text.find('"', start) + 1
            blank(marker_end, max(marker_end, i - 1))
        elif c == "'":
            j = i + 1
            while j < n and text[j] not in "'\n":
                j += 2 if text[j] == "\\" else 1
            blank(i + 1, min(j, n))
            i = j + 1
        else:
            i += 1
    return "".join(out)


def line_of(text, index):
    return text.count("\n", 0, index) + 1


def hot_ranges(code):
    ranges = []
    for m in HOT_METHOD.finditer(code):
        open_at = code.find("{", m.end())
        arrow = code.find("=>", m.end())
        if arrow >= 0 and (open_at < 0 or arrow < open_at):
            end = code.find(";", arrow)
            ranges.append((line_of(code, m.start()), line_of(code, end if end >= 0 else arrow), m.group(1)))
            continue
        if open_at < 0:
            continue
        depth, i = 0, open_at
        while i < len(code):
            if code[i] == "{":
                depth += 1
            elif code[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        ranges.append((line_of(code, m.start()), line_of(code, i), m.group(1)))
    return ranges


def guarded_lines(lines):
    guarded, stack = set(), []
    for no, raw in enumerate(lines, 1):
        s = raw.strip()
        if s.startswith("#if"):
            stack.append(any(g in s for g in GUARD_SYMBOLS) and "!" not in s)
        elif s.startswith("#elif"):
            if stack:
                stack[-1] = any(g in s for g in GUARD_SYMBOLS) and "!" not in s
        elif s.startswith("#else"):
            if stack:
                stack[-1] = False
        elif s.startswith("#endif"):
            if stack:
                stack.pop()
        elif any(stack):
            guarded.add(no)
    return guarded


def head_lines(root, rel):
    try:
        out = subprocess.run(["git", "-C", root, "show", f"HEAD:./{rel}"], capture_output=True, timeout=5)
    except Exception:
        return None
    if out.returncode != 0:
        return None
    return {l.strip() for l in out.stdout.decode("utf-8", "replace").splitlines()}


def added_line_numbers(tool, tin, root, rel, lines):
    """1-based numbers of file lines the edit added, and whether the file is new."""
    if tool == "Write":
        before = head_lines(root, rel)
        if before is None:
            return set(range(1, len(lines) + 1)), True
        return {i for i, l in enumerate(lines, 1) if l.strip() and l.strip() not in before}, False
    if tool == "MultiEdit":
        text = "\n".join(e.get("new_string", "") for e in tin.get("edits", []))
    else:
        text = tin.get("new_string", "")
    new = {l.strip() for l in text.splitlines() if len(l.strip()) > 2}
    return {i for i, l in enumerate(lines, 1) if l.strip() in new}, False


def banned_notes(cfg, rel, no, raw, code_line):
    notes = []
    for rule in cfg["bannedText"]:
        try:
            # JSON "\b" is a backspace, not a regex word boundary: forgive the common mistake.
            pattern = rule["pattern"].replace("\x08", "\\b")
            pat = re.compile(pattern, re.IGNORECASE if rule.get("ignoreCase", True) else 0)
        except (re.error, KeyError):
            continue
        where = rule.get("in", "any")
        haystacks = {"string": [m.group(0) for m in STRING_LIT.finditer(raw)], "code": [code_line], "any": [raw]}[where]
        if any(pat.search(h) for h in haystacks):
            notes.append(f"{rel}:{no}: {rule.get('message', 'matches a banned pattern: ' + rule['pattern'])}")
    return notes


def lint_cs(cfg, tool, tin, root, rel, text):
    notes = []
    lines = text.splitlines()
    code = strip_code(text)
    code_lines = code.splitlines()
    added, is_new = added_line_numbers(tool, tin, root, rel, lines)
    if not added:
        return notes

    runtime = any(rel.startswith(r) for r in cfg["runtimeRoots"]) and not any(d in "/" + rel for d in cfg["ignoreDirs"])
    dev_code = any(d in "/" + rel for d in cfg["devDirs"])
    guarded = guarded_lines(lines)
    has_linq = re.search(r"^\s*using\s+System\.Linq\s*;", text, re.MULTILINE) is not None
    hot = hot_ranges(code)
    has_ns = re.search(r"^\s*namespace\s+[\w.]+", code, re.MULTILINE) is not None

    def hot_method(no):
        for a, b, m in hot:
            if a <= no <= b:
                return m
        return None

    if tool == "Edit" and "MovedFrom" in tin.get("old_string", "") and "MovedFrom" not in tin.get("new_string", ""):
        notes.append(f"{rel}: a [MovedFrom] attribute was removed. Assets serialized under the old name lose their data; put it back unless that data is truly gone.")
    if runtime and cfg["requireNamespace"] and is_new and not has_ns:
        decl = TYPE_DECL.search(code)
        if decl:
            notes.append(f"{rel}: new runtime type '{decl.group(2)}' is in the global namespace. Put it in a namespace.")
    if runtime and not has_ns:
        for decl in TYPE_DECL.finditer(code):
            no = line_of(code, decl.start())
            if no in added and decl.group(2) in EDITOR_SHADOWS:
                notes.append(f"{rel}:{no}: global type '{decl.group(2)}' shadows a UnityEditor attribute and breaks every editor script using it.")

    pool = f"spawn through {cfg['poolHelper']}" if cfg["poolHelper"] else "use an object pool"
    physics = f"use {cfg['physicsHelper']}" if cfg["physicsHelper"] else "use the NonAlloc variant with a reused buffer"
    hot_rules = [
        (re.compile(r"\bInstantiate\s*[<(]"), "Instantiate in {m}: " + pool),
        (re.compile(r"\bDestroy\s*\("), "Destroy in {m}: deactivate and return it to a pool"),
        (re.compile(r"\bGetComponents?(InChildren|InParent)?\s*<"), "GetComponent in {m}: cache it in Awake"),
        (re.compile(r"\b(FindObjectOfType|FindObjectsOfType|FindFirstObjectByType|FindAnyObjectByType|FindObjectsByType)\b|\bGameObject\.Find\w*\("),
         "Find* in {m}: keep a registry or a cached reference"),
        (re.compile(r"\bnew\s+(List|Dictionary|HashSet|Queue|Stack)\s*<|\bnew\s+\w+\s*\[\s*\w*\s*\]"), "allocation in {m}: keep a field and Clear() it"),
        (re.compile(r'\$"|\$@"|\bstring\.Format\s*\(|\bstring\.Concat\s*\('), "string building in {m}: allocates every frame"),
    ]

    for no in sorted(added):
        if no > len(code_lines):
            continue
        c, raw, where = code_lines[no - 1], lines[no - 1], f"{rel}:{no}"
        notes += banned_notes(cfg, rel, no, raw, c)
        if not runtime:
            continue
        if re.search(r"^\s*using\s+UnityEditor\b", c) and no not in guarded:
            notes.append(f"{where}: 'using UnityEditor' in runtime code outside #if UNITY_EDITOR breaks player builds.")
        if dev_code:
            continue
        if DEBUG_KEY.search(c) and no not in guarded:
            notes.append(f"{where}: raw key read. If it is a debug/cheat key, wrap it in #if UNITY_EDITOR || DEVELOPMENT_BUILD.")
        m = hot_method(no)
        if DEBUG_LOG.search(c) and no not in guarded and (cfg["logHelper"] or m):
            notes.append(f"{where}: Debug.Log " + (f"in runtime code. Use {cfg['logHelper']}." if cfg["logHelper"] else f"in {m}: logs every frame and allocates."))
        if ALLOC_PHYSICS.search(c):
            notes.append(f"{where}: allocating physics query. {physics[0].upper() + physics[1:]}.")
        if not m:
            continue
        for rule, msg in hot_rules:
            if rule.search(c) and not re.search(r"Debug\.Log(Warning|Error|Exception)|throw\s", c):
                notes.append(f"{where}: " + msg.format(m=m))
        if has_linq and LINQ_CALL.search(c):
            notes.append(f"{where}: LINQ in {m}: allocates enumerators every frame; use a loop.")
    return notes


def lint_text(cfg, tool, tin, root, rel, text):
    lines = text.splitlines()
    added, _ = added_line_numbers(tool, tin, root, rel, lines)
    notes = []
    for no in sorted(added):
        notes += banned_notes(cfg, rel, no, lines[no - 1], lines[no - 1])
    return notes


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    tool = data.get("tool_name", "")
    tin = data.get("tool_input", {}) or {}
    path = tin.get("file_path") or tin.get("path")
    if not path:
        return 0
    root = find_unity_root(path)
    if root is None:
        return 0
    rel = os.path.relpath(os.path.abspath(path), root).replace("\\", "/")
    cfg = load_config(root)

    if "--pre" in sys.argv:
        if cfg["generatedPaths"] and matches_any(rel, cfg["generatedPaths"]):
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": f"{rel} is generated. {cfg['generatedHint']}",
            }}))
        return 0

    is_cs = rel.endswith(".cs")
    is_text = bool(cfg["textCheckGlobs"]) and matches_any(rel, cfg["textCheckGlobs"])
    if not (is_cs or is_text):
        return 0
    try:
        with open(os.path.join(root, rel), encoding="utf-8-sig", errors="replace") as f:
            text = f.read()
    except OSError:
        return 0

    notes = lint_cs(cfg, tool, tin, root, rel, text) if is_cs else lint_text(cfg, tool, tin, root, rel, text)
    if not notes:
        return 0
    more = len(notes) - MAX_NOTES
    body = "\n".join("- " + n for n in notes[:MAX_NOTES]) + (f"\n- ... and {more} more" if more > 0 else "")
    print(json.dumps({
        "systemMessage": f"unity-lint: {len(notes)} note(s) on {rel}",
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": "unity-lint (unity-workflow rules + the project's .claude/unity-workflow.json). "
                                 "Fix these, or tell the user why a line is fine:\n" + body,
        },
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
