---
name: InterviewLM Interviewer
description: Text-first mock-interview surface built on Scaler's own palette and type
colors:
  ink: "#021028"
  ink-2: "#0f1c37"
  ink-3: "#1a2c47"
  primary: "#0041c9"
  primary-bright: "#0080ff"
  primary-deep: "#005ab3"
  violet: "#4c46d6"
  tint: "#f6faff"
  tint-2: "#e7f3ff"
  line: "#d7dee8"
  line-2: "#bac6d8"
  muted: "#61738e"
  muted-2: "#929698"
  success: "#56c68e"
  warning: "#ffc834"
  danger: "#d0021b"
  paper: "#ffffff"
  # ink-surface text ramp — the examination surface needs its own tints,
  # because grey on ink is unreadable and the light-surface semantics are
  # too dark to pass contrast there.
  on-ink-strong: "#ffffff"
  on-ink-body: "#e4edfa"
  on-ink-muted: "#8fa6c9"
  on-ink-dim: "#6d84a8"
  on-ink-code: "#cfe0f7"
  on-ink-link: "#57adff"
  on-ink-success: "#6fd6a4"
  on-ink-warning: "#ffc834"
  on-ink-danger: "#ffb3bd"  # reserved; not yet used by a built screen
  ink-hairline: "#2f4666"
  ink-selected: "#2f5c94"
  chrome: "#3a4d6b"
typography:
  display:
    fontFamily: "'Source Sans 3', 'Source Sans Pro', -apple-system, sans-serif"
    fontSize: "1.75rem"
    fontWeight: 600
    lineHeight: 1.15
    letterSpacing: "-0.02em"
  question:
    fontFamily: "'Source Sans 3', 'Source Sans Pro', -apple-system, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 400
    lineHeight: 1.35
    letterSpacing: "-0.01em"
  body:
    fontFamily: "'Source Sans 3', 'Source Sans Pro', -apple-system, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 400
    lineHeight: 1.55
    letterSpacing: "normal"
  label:
    fontFamily: "'Source Sans 3', 'Source Sans Pro', -apple-system, sans-serif"
    fontSize: "0.6875rem"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "0.08em"
  code:
    fontFamily: "'JetBrains Mono', ui-monospace, SFMono-Regular, monospace"
    fontSize: "0.8125rem"
    fontWeight: 400
    lineHeight: 1.6
    letterSpacing: "normal"
  code-inline:
    fontFamily: "'JetBrains Mono', ui-monospace, SFMono-Regular, monospace"
    fontSize: "0.92em"
    fontWeight: 400
    lineHeight: 1.55
    letterSpacing: "normal"
  turn:
    fontFamily: "'Source Sans 3', 'Source Sans Pro', -apple-system, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "normal"
  metric:
    fontFamily: "'JetBrains Mono', ui-monospace, SFMono-Regular, monospace"
    fontSize: "1.375rem"
    fontWeight: 500
    lineHeight: 1.1
    letterSpacing: "-0.02em"
rounded:
  xs: "2px"
  sm: "4px"
  md: "6px"
  lg: "12px"
  xl: "16px"
  device: "30px"
  device-screen: "22px"
  full: "999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "24px"
  xl: "40px"
  xxl: "64px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.paper}"
    rounded: "{rounded.md}"
    padding: "12px 20px"
    typography: "{typography.body}"
  button-primary-hover:
    backgroundColor: "{colors.primary-deep}"
    textColor: "{colors.paper}"
  button-quiet:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "12px 20px"
  panel:
    backgroundColor: "{colors.paper}"
    rounded: "{rounded.lg}"
    padding: "20px"
  panel-focus:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.tint}"
    rounded: "{rounded.lg}"
    padding: "24px"
  chip:
    backgroundColor: "{colors.tint-2}"
    textColor: "{colors.primary-deep}"
    rounded: "{rounded.full}"
    padding: "4px 10px"
    typography: "{typography.label}"
---

# Design

## Overview

An Operate surface. The Candidate is in a task — being examined — and the
interface should disappear into it. Familiarity is a feature here; strangeness
without purpose is the failure mode.

One structural idea carries the whole system: **the examination is dark, the
scaffolding is light.** The live Topic Visit renders on Scaler ink (`#021028`);
setup, results, ledgers and the operator console render on Scaler's tint ground
(`#f6faff`). This is not decoration. It is attention: the exchange is the only
place the Candidate should be looking, and the ground change says so without a
word of copy. Leaving the exchange returns you to daylight.

Palette and type are taken from Scaler's own shipped stylesheet, not from a
screenshot. Layout structure is inherited from two supplied references — a mobile
shell built around a single conversation, a desktop surface with a persistent
right rail — with their video-call content removed. There is no video, no avatar,
and no face anywhere in this product.

## Colors

Restrained: ink and tint carry the surface, `primary` is reserved for the primary
action, current selection and state.

- `ink` — the live exchange ground, and text on light surfaces.
- `primary` `#0041c9` — primary actions, current Topic, focus rings. Never decoration.
- `primary-bright` `#0080ff` — the Candidate's own turn in the exchange, and links on ink.
- `violet` `#4c46d6` — reserved exclusively for **future surfaces** (voice, code editor). A Candidate should be able to tell a shipped affordance from a designed-but-unbuilt one at a glance.
- `success` / `warning` / `danger` — Evidence Floor bands, balance states, provider health.

**Never carry state by colour alone.** Every Evidence Floor band, balance state
and provider status also carries a word. A Topic below the floor reads
*Untested* in text; its colour is redundant reinforcement, never the message.

## Typography

One family, Source Sans 3 (Scaler's own Source Sans Pro, in its variable
successor). A well-tuned sans carries headings, labels, body and data; this
product needs no display pairing.

Fixed rem scale, ratio ~1.2. The one exception is `question` at 1.5rem — the
interview question is set larger than anything around it because it is the only
thing on screen the Candidate must actually answer.

JetBrains Mono appears for exactly three things: code, ids (`topic_visit_id`,
cuids), and measured quantities (Credits, α/β, token counts). Never as a costume
for "technical".

## Layout

- **Mobile (≤767px)** — single column, app shell. A slim header naming the Topic, the conversation, and a fixed composer. The exchange is *purely* question and answer; every secondary reading (cost, provenance, posterior) collapses behind a pull-up sheet.
- **Desktop (≥1024px)** — three zones inherited from the reference: a left rail for Session scope, the exchange centre, and a right rail carrying the Visit list with its state. Code and dossier open as overlays over the exchange, never replacing it.
- **1024px is where the right rail appears**; 768–1023px runs the two-zone form.
- Content max-width 68ch for prose. Tables and ledgers may run denser.

## Elevation & Depth

Two elevations only. Panels sit on the ground with a 1px `line` border and a soft
low shadow (`0 1px 2px rgba(2,16,40,.06), 0 8px 24px -12px rgba(2,16,40,.18)`).
Overlays (code editor, dossier, sheets) sit above with a deeper offset shadow.

Every shadow carries an offset and a soft blur. No zero-offset colored halos.

## Shapes

Scaler's own radii: 4/6/12/16px, tighter than the reference images' pill
language. Buttons and inputs at 6px, panels at 12px, overlays at 16px. Pills
(`full`) only for chips and status tokens.

## Components

- **Question** — 1.5rem, on ink, no bubble. The question is the surface, not a message in a list.
- **Answer** — the Candidate's turn, `primary-bright` left-aligned on ink, in a bordered field while composing.
- **Turn thread** — follow-ups, hints and probes stack under the opening question inside one Visit. The thread visibly resolves into **one** score at the end; this is the interface making ADR-0004 legible.
- **Posterior ridge** — the signature reading. Topic Confidence drawn as a Beta density curve, showing spread rather than a point. Wide and flat = unknown. Narrow = known. This replaces the progress bar the category ships, and it is the one place a chart is the content rather than a stand-in for it.
- **Provenance chip** — grader identity + provider, attached to every score. Always present, never hidden behind a hover.
- **Cost chip** — Credits for this Visit, in mono. Under BYOK it reads `—`, never `0`.
- **Band token** — Untested / Hedged / Firm, word first.
- States: every interactive element ships default, hover, focus, active, disabled, loading. Skeletons for loading, never a centred spinner.

## Settled by the first build

Three things the build decided that the seed did not:

- **Both rails share the exchange's ground.** The first pass gave the Session
  rail ink and the Visit rail paper, which read as two applications joined at a
  seam. The whole interview screen is one place; light is what you return to
  when the examination ends.
- **The Evidence Floor for a hedged reading is one effective Visit, not two.**
  At two, a Candidate who had just been examined on a Topic was told *Untested*
  on the very next screen, which is false. One graded answer is an early signal
  and reads as one. The floor for a *firm* reading stays at five.
- **`muted` is darker than it first shipped.** `#61738e` clears 4.5:1 on paper
  and on the tint ground, and fails it at 4.29:1 on the selected-option ground —
  which is exactly where the provider descriptions sit. Measuring against one
  background is how that hides; it is now `#596a83`.
- **Semantic colour is darker than Scaler's brand palette.** `#56c68e` and
  `#ffc834` are the values Scaler ships, and both fail 4.5:1 at the sizes the
  Evidence Floor bands use. The bands are the one place PRODUCT.md forbids
  colour-only meaning, so the brand hues were darkened for the light surface and
  kept at full brightness on ink, where they pass comfortably.
- **The bands read off the interval, not off a count.** The boundary between
  Untested, hedged and firm is the *width* of the 80% credible interval
  (≥0.70 → Untested, <0.40 → firm). This is what CONTEXT.md asks for and the
  reason no count of answers appears in `readTopic()`.
- **Coverage renders as `α + β − 2`, not `α + β`.** CONTEXT.md defines it as
  `α + β`; the build subtracts the uniform prior so an untested Topic reads 0
  rather than 2. Recorded as a deliberate divergence, not drift.
- **The crossing is animated, the rest is not.** Cross-document view
  transitions morph the ground between the ink exchange and the light page, and
  carry the top bar across. This is the system's one authored moment: the
  thesis is about crossing a threshold, and eight separate documents would
  otherwise discard it at every navigation. Everything else stays at 160–220ms
  state feedback. Browsers without support navigate normally.
- **The posterior ridge animates only where it names its own prior.** A ridge
  carrying `data-from-alpha`/`data-from-beta` deforms from that prior into the
  posterior on scroll-in; every other ridge paints once. The band is read from
  the final posterior, so no mid-tween frame shows a reading the Topic does not
  have.
- **Dense tables keep their columns on small screens.** They gain a fade and a
  stated scroll affordance rather than collapsing into stacked label/value
  pairs. An operator reading a ledger wants the columns; what they lacked was
  any signal that the columns continued.

## Do's and Don'ts

**Do**

- Show Coverage and Mastery as two separate readings, always.
- Render a Topic below the Evidence Floor as the word *Untested*, with no number.
- Show grader, provider and cost next to every score.
- Say "ends after this Topic" when a Session is winding down.
- Label every synthetic transcript, score and balance as sample data.
- Use `violet` for future/unbuilt surfaces so they are unmistakable.

**Don't**

- Never fuse Coverage and Mastery into one percentage. The call does not exist.
- Never label a question easy, hard, or by difficulty. The Corpus records none.
- Never use the word "progress" for anything but InterviewLM's own number, where it reads *InterviewLM Progress*.
- Never show a Session price before it runs, or an estimate dressed as one.
- Never show a Credit message on a BYOK surface — name the provider and the reason.
- Never render an Answer Key on a Candidate surface before the answer is graded.
- Never put a face, avatar or video frame in this product.
- No progress rings or sparklines standing in for content; the posterior ridge is real data or it is not drawn.
