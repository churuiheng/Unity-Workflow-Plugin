# UI review checklist

Go through it per capture. Each line is a question a player would never ask out loud but feels the answer to.

## Clarity: does it say the true thing at a glance?
- Does a bar/meter *look* like its value? Full must look full: no labels, numbers or empty zones inside the track
  that make a full bar read as part-full.
- Is every important number readable at gameplay distance and on the brightest and busiest backgrounds in the game
  (sky, sand, snow, VFX)? Text floating on the world without a backing usually isn't.
- Is the most urgent thing the most visible (a warning or parry cue over a popup, health over gold)?
- Are levels and caps shown as progress ("1/3"), not bare numbers, when a cap exists?
- Are numbers in descriptions picked out (colour/weight) and only the values that apply now shown ("+3 Power", not
  "+2 / +3 / +4 Power" when the player is level 2)?

## Consistency: does it look like one game?
- Corners: one radius scale, concentric insets (inner radius = outer − inset), capsules really round at both ends.
- Colours: one backing colour/opacity family, one text colour, one colour per meaning (keys, danger, stats,
  selection). The same meaning never has two colours, and one colour never has two meanings.
- Fonts: every text uses the game's font (nothing fell back to the engine default).
- Keys/inputs shown one way everywhere ("[E] Use" vs key caps vs pins: pick one per context).
- Rims/outlines: same width everywhere, or none.

## Overlap and overflow
- Does anything cover anything else in any state: selection rings over labels, tooltips over the hint line, popups
  over popups, a chip over a panel edge, notices over the minimap?
- Does every text fit its box at the longest real content (longest item name/description, 4-digit numbers,
  translated text if relevant)? Look for clipped, ellipsised or spilling lines.
- Does it stay on screen near edges (tooltips at the last slot, the right-hand player's panel)?

## Feel
- Does the UI react to the moment (pop, shake, fill, flash) proportionally? Big moments get more, routine ones less.
- Is nothing "grading" the player in text if the team decided feel comes from hitstop/sound/VFX?
- Do in-world indicators read at the real camera distance (tiny soft effects vanish)?

## Navigation and actions
- Does each key move the way the layout looks (vertical list: up/down; row: left/right)?
- One key, one meaning; no tap-vs-hold on the same key for different results.
- Does the UI show only the actions possible now, named by their result ("Swap with X", "Discard +20 gold")?
- Can every step be cancelled, and is the cancel key shown?
- Are destructive actions deliberate (a separate target or step) but not hidden?

## Less is more
- What could be removed without losing information? Headers that repeat the HUD, empty-state sentences for every
  empty section, duplicated hints, decorative bands/outlines.
- Could details move into a tooltip/hover card instead of always taking space?
- Is there one clear focal point per panel?
