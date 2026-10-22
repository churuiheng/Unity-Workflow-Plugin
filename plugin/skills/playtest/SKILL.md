---
name: playtest
description: Play a Unity game in the editor to check that a change really works in game — enter play from the project's start scene with its save files protected, drive the game with the project's registered Playtest steps (or by hand-written execute_code), read the game state, take Game-view screenshots and look at them, check the console, then stop play and put everything back. Use whenever a change needs seeing or trying in play mode ("test it in game", "does it work now?", "screenshot it", "reproduce this bug", "check the HUD/camera/VFX"), and before reporting gameplay, UI, camera, VFX or level work as done.
---

# Playtest

Logic checks miss what looks or feels wrong, so a gameplay, UI, camera or VFX change isn't done until someone has
looked at it in play. Uses Unity MCP (`mcp__UnityMCP__*`) and the unity-workflow package (`/unity-workflow:setup`).
The editor-lock hook stops you entering or stopping play while someone else is playing. If it refuses, wait or ask
the user; never work around it.

Scripts are in this skill's `scripts/` folder (`<this skill's base directory>/scripts/unity_window.sh`; run them with
`sh`, through the Bash tool):
- `focus [project]`: bring Unity to the front. **An editor in the background barely ticks**, so play steps,
  compiles and MCP calls stall or time out. Run it whenever a call times out or a wait drags.
- `keep <minutes> [project]`: keep it in front; run in the background (`run_in_background`) during long play work.
- `dismiss-save-dialog [seconds]`: presses **Cancel** on "Scene(s) Have Been Modified". Cancel keeps the user's
  unsaved scene edits and play still starts. Never press Save or Don't Save for the user.

## The loop

1. **Check the editor** (read-only): `return UnityWorkflow.Editor.PlaySession.State();`. Already playing and not
   yours: stop here and ask the user.
2. **Start play**:
   `return UnityWorkflow.Editor.PlaySession.Play(owner: "playtest: <what you're checking>");`
   It starts from `playtest.startScene` (config) or the open scene, backs up `playtest.saveFiles` and restores them
   when play stops. If it answers `blocked: unsaved changes…`, tell the user. Only with their OK, retry with
   `allowSaveDialog: true`, after first running `sh .../unity_window.sh dismiss-save-dialog` in the background.
3. **Wait until the game is ready**: poll `return UnityWorkflow.Playtest.Snapshot();`. "Unity is reloading" or
   "not playing" right after entering play just means: wait a few seconds and retry; don't enter play again.
4. **Drive it.** `return UnityWorkflow.Playtest.Steps();` lists what the project registered. Start one:
   `return UnityWorkflow.Playtest.Run("go-to-fight");` (or `"wait 3"`, `"timescale 2"`), then poll
   `UnityWorkflow.Playtest.Status` until `done: …` or `failed: …`. A failure says why: fix the cause, don't retry
   blindly. With no step for what you need, write a short `execute_code` snippet against the live game (fully
   qualified types, no `using`), and suggest registering it as a step (see `step-template.cs`).
5. **Look.** `Playtest.Run("shot <name>")`, wait for `done: <path>`, then **Read the PNG**. Judge what a player
   would see: size at gameplay camera distance, colour after post-processing, overlap, readability. Crop or zoom
   into the area in question if the frame is busy. Also `read_console` for errors and warnings that appeared during
   play.
6. **Stop**: `return UnityWorkflow.Editor.PlaySession.Stop();` (saves and start scene come back by themselves).
   Always stop when finished, even after a failure, so the editor isn't left in play mode holding the lock.

## When the project has no steps yet

Offer to add them. Copy `step-template.cs` into a dev-only folder of the game, and register 3–6 steps for what tests
keep needing (start a run, go to a level/room, start a fight, win it, open a menu). A good snapshot line includes
where the player is and what the game thinks is happening (scene/room, player state, enemies, open menus). Steps
should drive the game through its real code paths (the real damage, the real door), not by setting results directly.

## Report

What was checked and what was seen, with the screenshot path for anything visual, and what `Status` / the console
said if something failed. Never report a change as working in game unless it was actually played and looked at.

## Traps

- Entering play from a different start scene with unsaved scenes open pops Unity's save dialog; `Play` refuses
  rather than risk the user's edits.
- Domain reload: right after entering play (and after compiles) MCP calls can fail with "reloading" for a few
  seconds. Retry the read, don't repeat the action.
- `ScreenCapture` needs the Game view visible and the editor focused, or the PNG never appears.
- Unity set to "Recompile And Continue Playing" reloads scripts mid-play when files are saved. Don't edit scripts
  during someone else's play session; the hook warns about it.
