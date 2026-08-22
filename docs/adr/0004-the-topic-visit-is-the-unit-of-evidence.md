# One Topic Visit produces one Evidence write, not one per turn

A **Topic Visit** — the opening question plus every follow-up, hint and probe on
that **Topic** — yields a single score and a single update to that Topic's
**Topic Confidence**, regardless of how many **Answer Turns** it took.

## Why

A Beta distribution accumulates independent trials. Follow-ups are not
independent: probing one concept three times is one observation examined
closely. Writing three updates inflates **Coverage** threefold on a single
question's worth of information, and the inflation is not cosmetic — Thompson
sampling reads those posteriors, so an over-counted Topic stops being selected
long before the **Candidate** actually understands it.

This is what makes the accepted meaning of `α + β` true. Having defined it as
effective evidence rather than a question count, per-turn writes would
quietly restore the count and break everything reading the posterior.

## Consequence

Finer-grained per-turn feedback is given up. The agentic region runs the whole
exchange, then hands the **Judge** the exchange for that Topic Visit and
receives one score.

Hint assistance is expressed in the score `s`, never in the weight `w`. `w`
is trust in the **Grading Mode**; `s` is quality of the answer. Conflating them
makes both uninterpretable.
