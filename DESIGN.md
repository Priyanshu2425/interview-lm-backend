# Design

<!-- impeccable:design-schema 1 -->

## Visual World

**InterviewLM.** An examination room, not a dashboard. Near-black ground, one
cyan accent used at most twice per screen, a geometric display face against a
neutral grotesque body, and hairline borders carrying every structural
boundary — no shadow is used to separate things that a 1px rule can separate.

The world is set by the design files in `~/Documents/cortex-interviewer`
(`foundations.html`, `components.html`, `design-system.html`, `screens/*.html`,
desktop and mobile). Those files ship markup only; their `tokens.css`,
`system.css`, `patterns.css`, `mobile.css`, `theme.js` and `viz.js` were not in
the folder. The token layer in `frontend/src/ui/styles/` is a reconstruction
from that markup: every token name and every class name there is one the
shipped screens reference, and the exact type steps, space scale, radii, motion
durations and the five accents are all recoverable from it. What could not be
recovered — the neutral ramps of the four non-Graphite variations — is derived
by the same oklch formula the Graphite ramp uses.

This replaces the earlier Scaler-blue prototype in `design-system/`, which is
retired. PRODUCT.md's *Brand Commitments* section describes that older world.

## Palette

Five variations, each one block of tokens. Adding a sixth costs that block and
one entry in `shared/stores/theme.ts` — nothing else, because every product
semantic is derived rather than declared per variation.

| Variation | Scene | Ground | Accent | Display / body / mono |
|---|---|---|---|---|
| **Graphite** (default) | The examination room | `oklch(0.170 0.006 265)` | cyan `oklch(0.800 0.150 190)` | Space Grotesk 600 / Inter / JetBrains Mono |
| **Paper** | The filed record | warm off-white `oklch(0.972 0.006 85)` | ink blue `oklch(0.470 0.192 262)` | Instrument Serif 400 / IBM Plex Sans / IBM Plex Mono |
| **Clinical** | The audit surface | cool paper `oklch(0.978 0.002 235)` | teal `oklch(0.532 0.118 196)` | Sora 600 / Inter / IBM Plex Mono |
| **Signal** | Engineering | black-green `oklch(0.155 0.004 150)` | lime `oklch(0.900 0.190 122)` | JetBrains Mono 700 / IBM Plex Sans / JetBrains Mono |
| **Dusk** | The long session | warm dark `oklch(0.178 0.012 55)` | amber `oklch(0.822 0.142 72)` | Space Grotesk 500 / Sora / IBM Plex Mono |

**Accent economy.** One accent per variation, at most twice per screen — in
practice the primary action and the single highest-signal data mark. `risk`,
`warn` and `ok` are state hues and appear only when a state is true. Judge
surfaces are locked achromatic and cannot receive the accent.

## The confidence ramp

Mastery is the mean of a Beta distribution; Coverage is its evidence count.
The ramp is **sequential toward the accent**, so higher mastery reads as more
of the brand rather than as a different topic, and only the lowest band borrows
the risk hue — which keeps a wall of Topics calm and makes the fragile ones
unmissable.

```
--m-fragile   var(--risk)
--m-partial   color-mix(in oklch, var(--accent) 42%, var(--muted))
--m-working   color-mix(in oklch, var(--accent) 72%, var(--muted))
--m-solid     var(--accent)
```

A Beta plot in Dusk and a Beta plot in Clinical encode the same fact with
different pigment and neither needs a hardcoded hue.

**Untested is not on the ramp at all.** Below the Evidence Floor there is no
fill, no numeral and no bar — a `--floor-stroke` hairline in the `--floor-dash`
pattern, and the word. There is no prop, token or variation that overrides
this: `Reading` renders the word even when a mastery figure is passed in
alongside an untested band, and that behaviour is under test.

The API reports four bands and this maps them one-to-one:
`untested → band-untested`, `early → band-partial`, `firm_weak → band-fragile`,
`firm_strong → band-solid`. The design system also ships `band-working`; no API
band produces it, and inventing a fifth here to fill the palette would be
exactly the kind of derived number this product refuses.

## Scale

Invariant across every variation.

- **Type** — 64 / 48 / 38 / 30 / 24 / 20 / 18 / 16 / 14 / 13 / 12 / 11 px. Body
  never below 13px in app surfaces; 12 and 11 are for mono metadata, captions
  and labels. The examiner's question is 16px; a Candidate's own answer is 14.
- **Space** — 4px base, 15 steps: 2 4 6 8 12 16 20 24 32 40 56 72 96 128 160.
  Component padding uses steps 4–8; section rhythm uses 9–13. Nothing between.
- **Radius** — xs 4 (controls' inner marks), sm 6 (controls), md 10 (cards),
  lg 14 (panels, dialogs), xl 20, full. Data marks are 1–2px and never rounded
  into illegibility.
- **Edge** — hairline 1px carries structure. Shadows are for elevation only,
  and they are theme-tinted through `--shadow-a` / `--shadow-b`.
- **Layout** — topbar 56, control 28 / 36 / 44 (44 is the touch floor), rail
  232, side panel 348, wrap 1320, prose 68ch.

## Motion

Three durations and one authored moment.

- `--d-1` **110ms** — state feedback: hover, focus, press.
- `--d-3` **260ms** — entering surfaces: dialog, popover, drawer, the crossing.
- `--d-5` **700ms** — the score reveal, and only that. A Visit resolves once; it
  is allowed to take a beat.

Two moments carry meaning rather than feedback:

1. **The update.** When a Visit closes, the posterior deforms out of the prior
   it updated, so you watch one graded answer barely narrow the interval. The
   prior is reconstructed from the posterior and the weighted score the server
   returned — not re-derived.
2. **The crossing.** Moving between the examination and the scaffolding around
   it morphs the ground via a cross-document view transition.

Nothing loops except live-state indicators. `prefers-reduced-motion` collapses
every duration to 1ms, and the two authored moments render at their end state.

## Composition

One responsive shell, not two builds. Above 1080px it is the working surface
from the desktop designs — a persistent left rail and an optional right panel.
Below it the panel stacks under the stage; below 900px the rail becomes a
drawer. The same `Workbench` expresses all five screens the design set drew
that layout for.

- **The examination** is the product, so its stage is at reading measure
  (760px) and centred, and the composer sits at the foot of a stage that is at
  least a screen tall. It is deliberately **not** sticky: a bottom-pinned
  composer floats over the turn it is a reply to whenever the transcript is
  shorter than the viewport, which is exactly when the question matters most.
  The transcript scrolls it back into view after every turn instead.
- **The transcript is a stream of events**, not a list of sentences. A closed
  Visit is one of those events and renders where it happened — after the answer
  it graded and before the question that opens the next Topic.

## Copy

The product's own vocabulary, from `CONTEXT.md`, and the words it refuses.

- **Coverage** and **Mastery** are named separately and never fused. No screen
  contains a combined figure, and `ReadingPair`-style APIs have no combined
  output.
- **Untested**, never *0.00*, never *not started*. It is a fact about the
  evidence, not a score.
- **"Progress" is retired.** Cortex owns the word and means "classes opened".
- **No difficulty label.** Cortex records none and none is derived; no screen
  calls a question easy or hard. Under test.
- **A Credit is one US cent of provider cost.** Off the Credits route every
  figure is an em dash, never `0` — zero reads as "it was free" rather than
  "this ledger does not apply to you". Under test.
- **Failure copy renders from the API's own `code` and `message`.** The surface
  composes no billing copy, which is what keeps a Credit message from reaching
  a BYOK Candidate.
- Controls name their action. Errors name the problem and the recovery.

## Accessibility

Verified by `npm run audit`, which measures rather than asserts: every rendered
text node's real contrast against its real backdrop, every target's real box,
every control's accessible name, in all five variations across all eight
routes, plus a touch pass and a 320px overflow pass.

- Body and placeholder text ≥ 4.5:1, large text ≥ 3:1. Currently zero failures.
- **Score and state are never carried by colour alone.** Every band renders its
  word; every pressed control carries `aria-pressed`; the Untested mark is a
  dashed outline, distinguishable in greyscale.
- The exchange surface is fully keyboard-operable, since the Answer Turn is a
  submit event: ⌘/Ctrl+Enter submits, the dialog traps focus and restores it,
  Escape closes, and the first tab stop is a skip link.
- Touch targets are 44px. The one documented exception is the corpus map, where
  a mark is 15px on a pointing device — 75 cells at 24px stop being one wall of
  Topics — and grows to a 24px hit box on a coarse pointer. Every mark that
  opens something also has a full-width row in the Topic list on the same
  screen. Cells nobody has been examined on are not controls at all.
