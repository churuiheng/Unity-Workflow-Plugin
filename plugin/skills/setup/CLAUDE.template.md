# CLAUDE.md

<Game name>: <one line on the game>. Unity <version>, <render pipeline>. Orientation: <doc link, if any>.

## Rules (decided; don't re-litigate)

- <The team's own design rules, one line each.>

## Code rules

- New runtime types go in a namespace (`<RootNamespace>.<Domain>`).
- Runtime code: `<runtime folder>` (`<asmdef>`); editor code in `Editor/` folders (`<editor asmdef>`).
- Debug/cheat input behind `#if UNITY_EDITOR || DEVELOPMENT_BUILD`.
- Hot paths (`Update`, per-hit, per-enemy): no `Instantiate` (use `<pool helper>`), no LINQ, no allocations, no
  `GetComponent`/`Find*` (cache or keep a registry), no allocating physics queries (`<physics helper>`).
- Logging: `<log helper>` for info logs.
- Generated folders (`<paths>`): edit the source, never the output.

The unity-workflow hook flags new code that breaks these rules; treat its notes as review comments.

## Workflow

- Build → look at it in play → `/unity-workflow:verify` → `/unity-workflow:unity-commit`.
- Hot-path changes (combat, spawning, VFX, loading) also get `/unity-workflow:perf-check`.
- Never compile or enter play while someone else's play session is running.
