# One Topic Visit produces one Evidence write, not one per turn

A **Topic Visit** — the opening question plus every follow-up, hint and probe on
that **Topic** — yields a single score and a single update to that Topic's
**Topic Confidence**, regardless of how many **Answer Turns** it took.

> **Amended by ISSUE-0044.** The unit is now **the Topic within a Session**,
> not the Topic Visit. **The count is unchanged** — one Beta observation per
> Topic per Session, before and after — and the reasoning below holds exactly
> as written, because it was never about Visits: it was about not counting one
> concept examined closely as several independent trials.
>
> What moved is how an observation is assembled. A question may now span up to
> three Topics (ISSUE-0042) and a Session may reach one Topic through more than
> one question, so an observation is assembled from every question that touched
> the Topic, and one spanning question contributes to several observations. The
> Session is graded once, at the end, from the transcript (ISSUE-0044).
>
> The refusal is stronger than it was, not weaker. There is no longer an
> in-loop write path at all, and `UNIQUE(session_id, topic_id)` on `evidence`
> makes a second observation *impossible* rather than merely absent — the
> constraint is this ADR, rather than a rule the code is trusted to keep.
>
> One thing this newly requires saying: a Topic the Session **never reached**
> gets no Evidence row and no posterior touch. Not a low score, not a zero.
> Untested is not zero — it is the **Evidence Floor**'s whole argument — and a
> Session that silently scored unreached material at zero would corrupt a
> Candidate's record for material they were never shown. The plan items behind
> those Topics are marked `unreached`, so the record can tell "answered badly"
> from "never asked".
>
> MCP Mode is unchanged and still grades per Visit (ADR-0006): its caller is a
> ReAct agent we do not control, and the Visit is the only unit it has.

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
