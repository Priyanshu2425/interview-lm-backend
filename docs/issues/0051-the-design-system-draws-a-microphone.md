# ISSUE-0051 — The design system draws a microphone

Status: resolved
Type: AFK
Source: ISSUE-0049
Covers: the tokens, icons and CSS both voice screens are built from

Blocked by: — · Blocks: 0053, 0054

> Nothing uses any of this when the slice lands. That is the point: a token
> added across five themes and an icon added to the one file icons may live in
> are each worth reviewing on their own, and neither is reviewable buried in a
> screen.

## What to build

### One new token: `--live`

Recording red. It is **not** `--risk` — recording is not danger, and a Candidate
whose microphone is open is not in trouble. `--risk` is `oklch(.680 .190 24)` in
graphite; `--live` sits near `oklch(.700 .200 20)` there.

It goes in **all five theme blocks** in `src/ui/styles/tokens.css` — graphite,
paper, clinical, signal, dusk — tuned per theme rather than copied. Match each
theme's existing `--risk` lightness (paper's sits on a near-white ground and must
be much darker) and push hue toward 20.

That is the only new token. Everything else in both prototypes maps onto
`--warn`, `--ok`, `--accent-line`, `--surface-2/3`, `--r-full`, `--d-2`, `--e-out`,
which all exist.

### Three icons

`src/ui/Icon.tsx`'s `PATHS` is the only place an icon may live, and `IconName`
widens from it automatically. Add:

- `mic` — the capsule, the arc, the stand
- `stop` — note that every other path in the file is stroked; either stroke a
  square outline for consistency or accept the one fill and say why
- `level` — vertical bars, for the engine tag

The prototypes draw at 24×24. `Icon.tsx` is a 16×16 grid at stroke-width 1.6 —
redraw, do not paste.

### Two CSS sections in `patterns.css`

Placed adjacent to the existing `.composer*` block (~543–622) so the composer's
whole story reads in one place.

**The voice composer:** `.vbox` `.vbox-main` `.vbox-foot` `.mic` `.mic-wrap`
`.levels` `.timer` `.said` `.stream` `.low` `.notice` `.notice-ico` `.modes`
`.hint-row` `.kbd` `.load`.

**The setup screen:** `.setup` `.setup-top` `.setup-body` `.setup-col`
`.setup-foot` `.steps` `.step` `.step-mark` `.step-t` `.step-sub` `.step-r`
`.spin` `.facts` `.fact` `.mods`, plus `details/summary` scoped under `.setup`.

All of those class names were checked against every stylesheet and none collides.
Watch one neighbour: `patterns.css:600` already defines `.step-n`, which is a
different selector from the setup screen's `.step` family — keep them named
exactly as the prototype names them and they stay apart.

State lives in `data-*` attributes, per the house rule (`.scope-item[data-unusable]`,
`.agenda-item[data-current]`):

```
.vbox[data-live]            .vbox[data-busy]
.mic[data-state=listening]  .mic[data-state=ready]
.mic-wrap[data-live]        .levels[data-idle]
.timer[data-warn]           .notice[data-tone=risk|warn|ok]
```

`.low` — the low-confidence underline — ships **unused**. Transformers.js cannot
supply per-word confidence (ISSUE-0049 §corrections), so nothing renders it yet.
It ships anyway so that adding it later is a data change and not a redesign. Say
that in the comment above it, or somebody will delete it as dead code.

### Reuse rather than redraw

- The prototypes' `.meter` is the existing `@/ui` `Meter` (`Feedback.tsx:71`,
  already `role="progressbar"`). Use it. For the stalled state set `data-stalled`
  on a **wrapper** and select `[data-stalled] .meter > i` — no change to a
  design-system primitive for one colour.
- Check whether `Thinking` can stand in for the setup step's 12px spinner before
  adding `.spin`. The prototype's own comment justifies it if not ("the spinner
  that is allowed, because it is 22px and inside a step").
- Do **not** port `.ring` from setup variant A. Variant B uses steps and a `Meter`.
- Do **not** add a sixth stylesheet. `main.tsx` imports five in a load-bearing
  cascade order, and `patterns.css` is the file for exactly this.

## Acceptance criteria

- [ ] `--live` is defined in all five theme blocks and is distinct from `--risk` in each
- [ ] `npm run audit` reports no new contrast finding in any theme
- [ ] `mic`, `stop` and `level` are in `PATHS` and nowhere else; `IconName` includes them without being edited
- [ ] The new icons sit on the 16×16 grid at the file's stroke width
- [ ] No literal colour appears outside `tokens.css`
- [ ] No new class name collides with an existing selector
- [ ] `.low` ships with a comment saying why it is unused
- [ ] `Meter` is unmodified
- [ ] `npm run verify` green
