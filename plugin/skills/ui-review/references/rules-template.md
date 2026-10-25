# UI rules — <project name>

The UI decisions this team has made. Read before any UI review; add a dated line when the user decides something.
Newest decision wins; strike or delete superseded lines.

## Never
- (e.g.) No text that grades timing ("PERFECT!"); feel comes from hitstop, sound, shake.
- (e.g.) No top-centre banners for in-run feedback.

## Shapes
- Corner helper: `<Namespace.Class.Round(image, radius)>`; radius scale: small 6 / medium 12 / large 18 / capsule.
- Rims: <width> px, or none.

## Colours (one meaning each)
- Backing: <colour/alpha>. Text: <colour>. Muted text: <colour>.
- Keys/prompts: <colour>. Danger/health: <colour>. Stats/numbers in descriptions: <colour>. Selection: <colour>.

## Text
- Font: <asset>; runtime-built text gets it from <resolver>.
- Keys written as <"[E] Use" / key caps>; levels as "1/3".

## Layout
- What sits where (HUD corner, over heads in which order, menus anchored to what), and what must never overlap.

## Interaction
- Key per action in menus; how to cancel; how destructive actions are confirmed.

## Decisions log
- YYYY-MM-DD: <decision> (<why, in the user's words if possible>)
