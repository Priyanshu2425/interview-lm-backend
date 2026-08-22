# ISSUE-0004 — Confidence math and the Evidence Floor

Status: ready-for-agent
Type: AFK
Source: PRD-0002; ADR-0003, ADR-0004
Covers: PRD-0002 §1–§8, §32; PRD-0003 §18, §19

## What to build

The deepest module in the system: pure functions over `(α, β)`. Apply
**Evidence**, read **Mastery**, read **Coverage**, read the credible interval,
band a Topic against the **Evidence Floor**, sample a posterior. No storage, no
clock, no randomness it does not receive.

A **Topic Visit** yields a score `s` and carries a weight `w` set by its
**Grading Mode** — 1.0 Ground-Truth-graded, 0.7 Text-grounded, 0.5 Model
judgment. The update is `α += w·s` and `β += w·(1−s)`. `s` and `w` are never
conflated: `w` is trust in the mode, `s` is quality of the answer, and hint
assistance lands in `s`.

An untested Topic is the uniform prior, and it reads as *unknown* rather than
*weak*. **Evidence Floor** bands are read off the posterior as a credible
interval, not chosen by hand. Below the floor the tracker reports *Untested* and
nothing more — and the reporting module has no call that returns a bare Mastery
figure for such a Topic.

**Coverage and Mastery are separate outputs. There is no combined figure**, and
the response model has no field for one, so it cannot be added by accident.

Screen 03 gains the posterior ridge — the prior deforming into the posterior it
updated — and screen 04 gains the two readings side by side.

## Acceptance criteria

- [ ] Confidence math has no imports from the graph or the store; an import contract enforces the direction
- [ ] Applying Evidence at each of the three weights moves `α` and `β` by exactly `w·s` and `w·(1−s)`
- [ ] An answer reached after hints is scored in `s` and carries its mode's full weight
- [ ] A Topic with no rows and a Topic at the uniform prior are indistinguishable to every reader
- [ ] `alpha` and `beta` cannot be driven below the prior, enforced by constraint
- [ ] Repeated identical Evidence narrows the credible interval while leaving the mean stable
- [ ] Bands are derived from interval width; no band boundary is a count of answers
- [ ] A Topic below the floor reports *Untested* and there is no code path that returns a number for it
- [ ] Coverage and Mastery are separate return values, and no function returns them fused
- [ ] Coverage is reported as effective Topic Visits, and every surface that shows it says so
- [ ] The posterior update is `alpha = alpha + $1` in SQL, never read-modify-write, so a concurrent Visit cannot be lost
- [ ] `alpha_delta` and `beta_delta` are stored on the Evidence row and a rebuilt posterior matches the stored value
- [ ] Screen 03's ridge animates from the prior it updated and honours `prefers-reduced-motion`
- [ ] Screen 04 shows Coverage and Mastery as two readings, with untested Topics named as such

## Blocked by

- ISSUE-0003 — the update needs a real score and a real Grading Mode
