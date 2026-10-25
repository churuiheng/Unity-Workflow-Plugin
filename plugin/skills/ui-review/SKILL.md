---
name: ui-review
description: Review and refine a Unity game's UI by looking at it, not by reading code — capture the HUD, menus and in-world indicators (health bars, prompts, popups over heads, damage numbers) in the states players see, crop and zoom into them, check them against a clarity/consistency checklist and the project's own UI rules, fix what's wrong, and prove each fix with a before/after strip. Use whenever the user asks to review, polish, revise, refine, clean up or "make consistent" any game UI or HUD, says a UI is cluttered, confusing, misleading, hard to read or "looks off", asks about rounded corners, pixelsPerUnitMultiplier, fonts, colours, tooltips, inventory or menu layout, navigation of a menu, or wants feedback on UI "game feel", clarity or uniqueness — even if they only send a screenshot of a UI problem.
---

# UI review

UI is judged on screen. Code review misses the things players notice: a bar that looks 3/4 full when it's full, oval
"rounded" corners, a label covered by a selection ring, text that runs out of its box, a menu that moves the wrong
way. So every round of this skill is: **capture → crop → check → fix → before/after**, using the playtest skill to
drive the game.

## 0. Know the house rules first

Read the project's UI rules before judging anything: `uiReview.rulesFile` in `.claude/unity-workflow.json`
(default `.claude/ui-rules.md`), plus anything about UI in `CLAUDE.md` and project memory. They record decisions the
user already made (e.g. "no top-centre banners", "keys are gold", "white highlights, no cyan"). Never re-litigate a
recorded decision; a new user correction in this session wins over an old rule, and then gets written into the rules
file (step 6). If the project has no rules file, offer to start one from `references/rules-template.md` once the first
round has taught you something.

## 1. Capture the states players see

Use `/unity-workflow:playtest` (or the project's own playtest skill) to get into play. One screenshot is never
enough: UI breaks in particular states. Plan a short list before starting, e.g.:

- **HUD**: idle/exploring, in a fight, low health, full resources, a pickup/notice showing.
- **World indicators**: enemies hit (health bars, damage numbers), prompts near interactables, several popups over
  one character at once (they overlap), co-op (two players' UI at once) if the game has it.
- **Menus / panels**: open, every tab/section, an empty section, the longest item text, every action state (e.g.
  selecting, moving/dragging, confirming, cancelling), and the narrowest supported resolution if layout scales.

Drive states through real code paths where possible, and fake only what's slow to reach (grant items, set health,
trigger a popup directly). Script a sequence in one `execute_code` coroutine that presses keys and takes a
screenshot after each step, so states are consistent and repeatable for the "after" pass. Name captures
`<area>-<state>.png` so before/after pairs line up.

## 2. Crop and zoom

UI is small at 1080p; judge it at 2-4x. Use the bundled script (needs Pillow: `pip install pillow`):

```bash
S=<this skill's base directory>/scripts/ui_shots.py
python "$S" crop  Captures/hud-idle.png 20,25,500,145 out/hud-idle-x3.png --zoom 3
python "$S" strip out/inventory-flow.png Captures/inv-1.png Captures/inv-2.png Captures/inv-3.png --crop 20,120,520,560 --labels "open,lifted,swap"
python "$S" compare Captures/before/hud.png Captures/hud.png out/hud-compare.png --crop 20,25,500,145 --zoom 2
```

Crop boxes are `x,y,width,height` in screenshot pixels. Put scratch crops in a temp/scratch folder, not the
project. Then **Read every image** you made: you are the reviewer, the script only frames it.

## 3. Check

Walk `references/checklist.md` for each capture (clarity, consistency, overlap, overflow, feel, navigation, less is
more), then the project's rules. Write findings as *what a player would misread or miss*, not as code: "a full health
bar reads as 3/4 because the numbers sit inside the track" beats "BarZone is 160 of 268".

Before proposing a fix, find the cause in code; `references/unity-ui-traps.md` lists the Unity causes behind the
usual symptoms (corner radius/multiplier math, squashed slices, filled images, world-space units, fonts falling back,
letterboxed images, text overflow). Many "looks off" findings trace to one shared helper, so fix it there once
instead of patching each screen.

## 4. Decide what to fix now vs ask

- **Fix now**: bugs (misleading readouts, overlaps, overflow, wrong font, broken corners, mismatched colours that
  the rules already define), and anything the user explicitly asked for.
- **Ask first**: changes to the look or feel that aren't settled — new layouts, new colours, removing an element the
  user designed, new interaction schemes. Present 2-4 concrete options with a recommendation and what each costs.
  The user wants **less, clearer UI**: prefer removing or merging over adding.

Interaction changes need extra care: one key = one meaning (no tap vs hold on the same key), the direction a key
moves must match the layout (up/down for a vertical list, left/right for a row), and every state shows only the
actions possible right now, in words the player can act on ("[E] Swap with Blood Bloom", not "[E] Confirm").

## 5. Fix and prove it

Make the change, compile, then re-run the **same capture script** and build before/after strips with
`compare`/`strip`. Read them. Check that nothing else moved (overlap with neighbours, other screens sharing the
helper you changed). Run the project's verify (compile, tests, release compile). A fix isn't done until the after
image has been looked at.

## 6. Keep the rules

When the user makes a UI decision or correction ("remove the outline", "numbers go outside the bar", "white not
cyan"), add one line to the project's UI rules file with the date, and update it when it's superseded. That file is
what stops the next session from undoing today's decisions.

## Report

Lead with what the player now sees differently, then the list of fixes (one line each, in player terms), then the
before/after image paths, then open questions with options. Keep it short; the images carry the detail.
