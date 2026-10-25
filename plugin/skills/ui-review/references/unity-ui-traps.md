# Unity UI traps: symptom → cause → fix

Found the hard way on a Unity 6 URP game; all apply to uGUI + TextMeshPro.

## Rounded corners (sliced sprites)

**The math.** On a Sliced `Image`, a corner's on-screen radius in canvas units is

    radius = spriteBorderTexels / (sprite.pixelsPerUnit / canvas.referencePixelsPerUnit) / image.pixelsPerUnitMultiplier

With the usual 100/100 PPU: `radius = borderTexels / multiplier`. So the multiplier is not a style knob, it's
derived: `multiplier = borderTexels / wantedRadius`.

| Symptom | Cause | Fix |
|---|---|---|
| Corners differ between elements that "should match" | Hand-typed multipliers (1.5 here, 2.2 there) on different source sprites | One helper: `Round(image, radiusInCanvasUnits)` picks the sprite and sets the multiplier. Never type a multiplier. Keep a small radius scale (e.g. 6/12/18 + capsule). |
| Ends of a pill look oval, not round | Sprite border bigger than half the box on ONE axis: Unity shrinks borders per axis, so corners become ellipses | Capsule = radius exactly height/2 (`Pill(image, height)`). Don't use a big-radius sprite on small boxes. |
| Corners soft/blurry at 4K | Canvas scale ≥2 stretches a small texture corner | Draw masters at ~2× the shown radius (texture radius 8/16/32/64, multiplier ~2). |
| Inner box corners look wrong inside a frame | Not concentric | inner radius = outer radius − inset. |
| A rim's width varies between elements | A rim sprite's line width scales with the multiplier too | Generate rim sprites per (radius, width) so the shown width is exact. |
| Corners on Filled images (cooldown sweeps, bar fills) look wrong/oval | `Image.Type.Filled` ignores the multiplier and stretches the whole sprite | Bake a non-sliced sprite at the element's own aspect ratio (a capsule texture W×H for a bar). |
| A world-space panel's corners are huge (circles) | Radius helper clamped to ≥1, but world canvases measure in metres (0.1–0.5) | Never clamp radii to pixel-scale minimums; ask in the canvas's own units. |

## Images

| Symptom | Cause | Fix |
|---|---|---|
| Portrait shows dark bands inside a circular mask | Non-square art with `preserveAspect` → letterboxed | Size the image to *cover* the mask (shorter side = mask size), preserveAspect off; refit when the sprite changes. |
| Particles under a UI/outlined object draw as black squares | An outline component adds materials to every child renderer | Keep effects outside the outlined hierarchy. |

## Text

| Symptom | Cause | Fix |
|---|---|---|
| A text uses a different (default) font | Built in code with no font set → TMP default (LiberationSans) | One "game font" resolver used by every runtime-built text. |
| A label vanishes entirely | `Ellipsis` overflow with a box shorter than the font's line height | Use `Overflow` + size the box to `GetPreferredValues(text, width, 0)`. |
| Text spills out of a card | `NoWrap` lines, fixed-height boxes | Wrap every line and size the card to the preferred heights. |
| Text over the world is unreadable on bright ground | No backing | Put it on the game's dark backing (or a strong outline if a backing is wrong for it). |
| Building TMP with outline under an inactive parent throws | Material instancing on inactive objects | Configure, then deactivate last. |
| Per-instance outline/material changes on pooled text | Each change makes a material instance | Do it once per pooled object (Awake), never per spawn. |

## Layout and state

| Symptom | Cause | Fix |
|---|---|---|
| Several popups over a head cover each other | Each positions itself at the same "above head" offset | A shared stack: fixed order by urgency, each layer lifts by what's below it, eased. |
| A selection ring covers the label under an item | Focus scales the cell / ring overlaps the label zone | Labels outside the ring's extent; focus = ring only, no scale. |
| A full bar looks part-full | Numbers/empty zones inside the bar's track | The track wraps only the bar; numbers beside it. |

## Capturing (for the review itself)

| Symptom | Cause | Fix |
|---|---|---|
| `ScreenCapture.CaptureScreenshot` writes nothing | Game view hidden/covered or editor unfocused | Focus the editor and show the Game view; check the file exists before reading. |
| A scripted capture sequence stops halfway | The coroutine host was destroyed by a scene load | Start drivers after the scene you test is loaded, or host them on a DontDestroyOnLoad object. |
| States differ between "before" and "after" | Hand-driven captures | Script the sequence (keys + waits + shots) and re-run it for the after pass. |
| Can't test a physics/NavMesh UI effect (knockback numbers) in a sandbox | Sandbox lacks NavMesh, agents clamp moves to 0 | Measure in a real level. |
