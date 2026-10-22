---
name: unity-commit
description: Prepare a clean git commit in a Unity project — sort the working tree into real changes and Unity noise (line-ending/timestamp-only files, re-serialised settings, TMP font atlas resets, NavMesh/lighting rebakes, project noise rules), summarise big prefab/scene diffs by the fields that changed, stage only this task's files (and only this task's hunks when another session edited the same file), have the unity-reviewer agent check staged C#, and write the commit message. Use whenever the user asks to commit, push, "what changed?", "clean up git status", or when git status shows more files than the task touched.
---

# Unity commit

Unity rewrites files it was only asked to open. Committing that noise hides the real change, causes merge conflicts,
and can put a broken value into the repo. Keep commits to what the task changed.

## 1. Look

`python "<this skill's base directory>/scripts/review_changes.py" [path filters]` (use `python3` on macOS/Linux). Read-only. Lists each changed file with status, real size of change (line endings ignored), kind, and
either the YAML fields that changed (`m_LocalPosition x3, enabled x1`) or a noise flag with the reason; warns about
files over 50 MB and new assets missing a `.meta`. Project noise rules: `commitNoise` in `.claude/unity-workflow.json`.

## 2. Sort

For each file: **this task**, **noise**, or **someone else's work** (the user's own edits, or another Claude session's).
- `NO REAL CHANGE`: leave unstaged.
- `NOISE?`: read the reason; restore (`git checkout -- <path>`) only when sure. A recurring noise source is a bug to
  fix in code, not something to restore in every commit.
- Asset changes the task doesn't explain: open the diff (`git diff HEAD --ignore-cr-at-eol -- <path>`). A changed
  field nobody asked for is a finding.
- Not sure whose a change is? Ask. `.meta` files travel with their asset: both or neither.
- **One file, two people's work:** stage only this task's hunks (`git diff -U0 -- <file>` → keep yours →
  `git apply --cached --unidiff-zero <patch>`), or build the index copy from `git show HEAD:<file>` plus your change
  (`git hash-object -w --path=<file> <tmp>` + `git update-index --cacheinfo 100644,<hash>,<repo-relative path>`).
  Then make sure the commit **compiles on its own**: every type/member the staged code uses exists at HEAD or is
  staged too (`git grep -F "<name>" HEAD`). Someone else's uncommitted file can easily be what your code calls.

## 3. Review

Staged C#: run the **unity-reviewer** agent on `git diff --cached`. Fix blocker/high findings, or tell the user why
not; mention medium ones. If the project has a verify step (`/unity-workflow:verify`), run it for code changes.

## 4. Stage and commit

- Stage by explicit path, never `git add -A` / `git add .` on a dirty tree. Check `git diff --cached --stat`.
- Message: a title ≤ 72 characters saying what changed for the game; a blank line; short bullets on what and why;
  one line on how it was verified (and what was skipped); then the attribution lines the environment specifies.
- Push only when asked. Never `--no-verify`, never force-push.
- Run the script again: what's left should be explainable (someone else's work, or noise left aside).

## Report

Committed (what, hash, pushed or not), left out as noise (what, why), left for the user / other sessions (what).
