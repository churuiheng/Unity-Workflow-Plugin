"""Find and remove old review/playtest captures (screenshots, clips) from a Unity project.

    python clean_captures.py                      # dry run: list what would go (default: Captures/, older than 30 days)
    python clean_captures.py --days 14            # a different age
    python clean_captures.py --apply              # actually delete (after you have looked at the dry run)

Options:
    --root PATH          project root (default: the current folder)
    --dir DIR            a captures folder, relative to the root; repeatable (default: config, else Captures)
    --days N             keep anything modified in the last N days (default: config, else 30)
    --keep GLOB          never delete files matching this glob (relative to the captures folder); repeatable
    --apply              delete; without it nothing is touched
    --json               machine-readable summary

Config (optional): .claude/unity-workflow.json -> "captures": {"dirs": [...], "maxAgeDays": 30, "keep": [...]}.
A file named .keep inside a captures folder adds one glob per line.

Safety: never follows a folder outside the project root, never deletes files tracked by git, refuses folders under
Assets/ (Unity .meta files would be orphaned; captures don't belong there), only deletes captures (images, clips,
bug-report zips and their .json sidecars), and removes emptied sub-folders only when --apply is given.
"""
import argparse
import fnmatch
import json
import os
import subprocess
import sys
import time

MEDIA = {".png", ".jpg", ".jpeg", ".gif", ".mp4", ".webm", ".mov", ".exr", ".tga", ".bmp", ".zip", ".json"}


def load_config(root):
    path = os.path.join(root, ".claude", "unity-workflow.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("captures", {}) or {}
    except (OSError, ValueError):
        return {}


def tracked_files(root):
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True).stdout
        return {os.path.normcase(os.path.normpath(os.path.join(root, p))) for p in out.decode("utf-8", "replace").split("\0") if p}
    except (OSError, subprocess.CalledProcessError):
        return set()


def keep_globs(folder, extra):
    globs = list(extra)
    keep_file = os.path.join(folder, ".keep")
    if os.path.isfile(keep_file):
        with open(keep_file, encoding="utf-8") as f:
            globs += [line.strip() for line in f if line.strip() and not line.startswith("#")]
    return globs


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=os.getcwd())
    ap.add_argument("--dir", action="append", default=None)
    ap.add_argument("--days", type=float, default=None)
    ap.add_argument("--keep", action="append", default=[])
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    root = os.path.realpath(a.root)
    cfg = load_config(root)
    dirs = a.dir or cfg.get("dirs") or ["Captures"]
    days = a.days if a.days is not None else float(cfg.get("maxAgeDays", 30))
    cutoff = time.time() - days * 86400
    tracked = tracked_files(root)

    old, kept, refused = [], 0, []
    for d in dirs:
        folder = os.path.realpath(os.path.join(root, d))
        rel = os.path.relpath(folder, root)
        if rel.startswith("..") or os.path.isabs(rel):
            refused.append(f"{d}: outside the project")
            continue
        if rel.replace("\\", "/").split("/")[0] == "Assets":
            refused.append(f"{d}: under Assets/ (would orphan .meta files)")
            continue
        if not os.path.isdir(folder):
            continue
        globs = keep_globs(folder, a.keep + list(cfg.get("keep", [])))
        for base, _, files in os.walk(folder):
            for name in files:
                path = os.path.join(base, name)
                inner = os.path.relpath(path, folder).replace("\\", "/")
                if os.path.splitext(name)[1].lower() not in MEDIA or name == ".keep":
                    continue
                if any(fnmatch.fnmatch(inner, g) for g in globs) or os.path.normcase(os.path.normpath(path)) in tracked:
                    kept += 1
                    continue
                st = os.stat(path)
                if st.st_mtime < cutoff:
                    old.append((path, st.st_size, st.st_mtime))
                else:
                    kept += 1

    old.sort(key=lambda t: t[2])
    total = sum(s for _, s, _ in old)
    deleted = 0
    if a.apply:
        for path, _, _ in old:
            try:
                os.remove(path)
                deleted += 1
            except OSError as e:
                refused.append(f"{path}: {e}")
        for d in dirs:
            folder = os.path.realpath(os.path.join(root, d))
            for base, subdirs, files in os.walk(folder, topdown=False):
                if base != folder and not os.listdir(base):
                    os.rmdir(base)

    if a.json:
        print(json.dumps({"days": days, "dirs": dirs, "old": len(old), "bytes": total, "kept": kept,
                          "deleted": deleted, "applied": a.apply, "refused": refused,
                          "files": [os.path.relpath(p, root) for p, _, _ in old]}, indent=2))
        return
    for path, size, mtime in old[:40]:
        print(f"  {time.strftime('%Y-%m-%d', time.localtime(mtime))}  {human(size):>9}  {os.path.relpath(path, root)}")
    if len(old) > 40:
        print(f"  ... and {len(old) - 40} more")
    verb = "Deleted" if a.apply else "Would delete"
    print(f"{verb} {deleted if a.apply else len(old)} file(s), {human(total)}, older than {days:g} days in {', '.join(dirs)}; kept {kept}.")
    for r in refused:
        print(f"  skipped {r}")
    if not a.apply and old:
        print("Dry run: nothing touched. Re-run with --apply to delete.")


if __name__ == "__main__":
    sys.exit(main())
