---
name: clean-captures
description: Clean up old screenshots, GIFs and clips that play-testing, UI reviews and bug captures pile up in a Unity project — find media older than a cut-off (default 30 days) in the captures folders, show what would go and how much space it frees, and delete only after a look at the dry run, never touching git-tracked files, anything under Assets/, or files pinned in a .keep list. Use when the user asks to clean, prune, tidy or free up space from Captures / screenshots / recordings, mentions the captures folder getting big, or as housekeeping at the end of a long run of playtest or ui-review work.
---

# Clean captures

Play-tests and UI reviews write a lot of screenshots (hundreds of MB in weeks). They're evidence while work is fresh
and clutter after. This prunes them by age, safely.

Script: `<this skill's base directory>/scripts/clean_captures.py` (Python 3, no extra packages). Run it from the
project root.

1. **Dry run first**, always:
   `python <skill>/scripts/clean_captures.py` (config folders and age, else `Captures/`, 30 days).
   Use `--days N` or `--dir Folder` when the user names something else.
2. **Show the user** the count, the space freed and a few of the oldest file names. If any of them look like they
   matter (a baseline, an image referenced in a doc or a ticket, a capture queued for posting somewhere), pin them:
   add a glob to the folder's `.keep` file (one per line, relative to that folder, e.g. `baseline-*.png`,
   `biomes/*-overview.png`) or to `captures.keep` in `.claude/unity-workflow.json`, then dry-run again.
3. **Delete** with `--apply` only after the user agreed to that list, or when they asked for it to happen without a
   review ("just clean anything older than 30 days"). Report what was deleted and the space freed.

What it will never do: delete files git tracks, touch folders under `Assets/` (deleting there orphans `.meta` files;
captures don't belong there), follow a folder outside the project, or delete anything but captures (images, GIFs/clips, bug-report zips and
the .json sidecars beside them).

Config (optional), in `.claude/unity-workflow.json`:
```json
"captures": { "dirs": ["Captures"], "maxAgeDays": 30, "keep": ["baseline-*.png"] }
```

If a project keeps captures somewhere else (a Showcase folder outside the repo, a library queue), leave those to
the tool that owns them: a queued-but-unposted capture deleted here is lost work.
