# design-system — retired prototype

> Superseded by the InterviewLM design system. The shipped token layer and
> component library live in `frontend/src/ui/`, and the world it commits to is
> documented in `../DESIGN.md`. This folder is kept for the reasoning recorded
> in `DESIGN.md` beside it and for the screens it drew; nothing here is built
> from any more.

---

# design-system — tokens and prototype screens

Eight screens for the InterviewLM Interviewer. Each is **one responsive HTML
file**; `index.html` presents every screen at both a phone and a desktop width
so the two can be compared side by side.

## Viewing

Open `index.html` directly, or serve the folder so the gallery's iframes load:

```
cd design-system && python3 -m http.server 8899
# then open http://127.0.0.1:8899/index.html
```

## What's here

| File | Screen |
|---|---|
| `DESIGN.md` | Tokens, type scale and the design's stated intent — source of truth |
| `index.html` | Gallery — every screen in both frames |
| `screens/01-session-setup.html` | Choose Modules, duration and Provider |
| `screens/02-topic-visit.html` | The examination. Mobile is pure Q&A; desktop adds both rails |
| `screens/03-visit-result.html` | Score, provenance, cost, and the posterior it moved |
| `screens/04-session-summary.html` | Coverage and Mastery, reported separately |
| `screens/05-credits.html` | Balance, ledger, BYOK, and both failure messages |
| `screens/06-code-visit.html` | Code editor overlay — **future surface** |
| `screens/07-voice-visit.html` | Voice turn boundary — **future surface** |
| `screens/08-operator.html` | Pool headroom, metering health, per-Provider spend |
| `assets/app.css` | The token layer and every component style |
| `assets/app.js` | Beta-density renderer, Evidence Floor bands, overlays |

Violet marks every surface that is designed but not built, so a proposed
affordance is never mistaken for a shipped one.

## The one piece of real logic

`assets/app.js` computes the posterior ridge from actual α and β — a real Beta
density, with a numerically integrated credible interval behind the Evidence
Floor bands. `readTopic()` has no code path that returns a bare Mastery number
for a Topic below the floor; it returns the word *Untested* instead. Changing
the α/β on any element re-renders that curve honestly.

Every stated centre and Coverage figure on screen 04 is derived from that
element's own α and β. If you change one, change the other.

## Data provenance

**Real, from the scraped Corpus:** Track, Module and Topic names; Topic counts
(57 AIML, 14 DSA, 71 total); Answer Key counts (26 pairs, distributed
4/5/5/5/4/3 across AIML Modules 1–6, none in 7–8); the attention question and
its Answer Key, taken from *Assignment: Pillar 3 — Assessment*.

**Synthetic, and labelled as such on every screen:** all scores, balances,
transcripts, ids, provider prices, spend figures and operator metrics. No real
Candidate record exists.

## Motion

Two authored moments, and nothing else moves:

1. **The crossing.** Navigating between an examination screen and a scaffolding
   screen morphs the ground itself, via cross-document view transitions. This is
   the design's whole thesis, so it is the one place motion carries meaning
   rather than feedback.
2. **The update.** On `03-visit-result`, the posterior deforms from the prior it
   updated, so you watch one graded answer barely narrow the interval.

Both honour `prefers-reduced-motion`. Everything else is 160–220ms state
feedback: hover, focus, overlay entry.

## Known gaps

Recorded rather than hidden:

- The 66 untested Topics on `04-session-summary` are the product's central
  claim, and they still render as three list rows while the 5 examined Topics
  get a full table. Inverting that visual weight would put the argument in the
  composition instead of a heading. It is a redesign of that screen, not a fix.
- The desktop left rail on `02` and `06` runs about 60% empty.
- `07`'s waveform is hand-drawn rather than derived, the one place in the set
  where an abstraction stands in for data.

## Re-shooting the screens

```
node design-system/tools/shoot.mjs <output-dir>     # run from the project root
```
Captures every screen at 1440 and 390, plus the two overlay states, and reports
any console errors. Requires the local server above to be running.
