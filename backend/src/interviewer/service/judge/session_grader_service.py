"""Grading the Session, once, at the end (ISSUE-0044).

Until ISSUE-0042 a Topic Visit was graded the moment it closed, because the
sampler needed a posterior before it could choose the next Topic. The plan is
fixed up front now, nothing downstream waits on a score, and so the grade can
happen where it always belonged: after the conversation, against the whole of
what was said.

What that buys is a unit that matches the material rather than the mechanism.
The unit of Evidence is **the Topic within a Session** — ADR-0004's count is
unchanged, one Beta observation per Topic per Session, but the observation may
now be assembled from several questions (a spanning one plus a dedicated one),
and one question may contribute to several observations. `UNIQUE(session_id,
topic_id)` is that rule, and it makes a second write impossible rather than
merely absent.

**A Topic the Session never reached scores nothing at all.** No Evidence row, no
posterior touch — not a low score. Untested is not zero: it is the Evidence
Floor's whole argument, and a Session that quietly scored unreached material at
zero would corrupt a Candidate's record for material they were never shown. The
plan items behind those Topics are marked `unreached`, so the difference between
"asked and answered badly" and "never reached" survives in the record.

**Blindness is at risk from spanning questions, not from the transcript.** One
answer to a question spanning three Topics is graded three times, against three
different groundings, so each per-Topic bundle carries that Topic's questions
and the Candidate's answers and nothing else. Probes, hints and turn counts are
dropped here, and dropped again by `Judge._answer_only` — one implementation of
blindness, not two that drift.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...model.corpus_models import GradingMode
from interviewer.model.evidence_models import EvidenceWrite
from ..corpus.citations import resolve
from .judge_service import Judge
from .question_writer_service import mode_for

__all__ = ["SessionGrader", "TopicBundle"]

#: What a Judge is allowed to see of an interviewer's turn. Probes and hints
#: shaped the answer; they are not evidence about it, and a grader shown who
#: needed help is grading the help.
GRADED_KIND = "question"


@dataclass(frozen=True, slots=True)
class TopicBundle:
    """One Topic's share of the transcript, already blind.

    Assembled before anything is loaded or graded, so what the Judge will be
    given can be read — and asserted on — without running a model.
    """

    topic_id: str
    question: str
    turns: list[dict]
    question_count: int
    topic_visit_id: str | None
    grounding_ref: dict | None


class SessionGrader:
    """Turns a finished Session's transcript into one Evidence row per Topic.

    Safe to call from anywhere and as often as anyone likes, which is what lets
    the graph, `/end` and the resumption path all call it without coordinating:
    the second call writes nothing.
    """

    def __init__(
        self, *, sessions, visits, evidence, loader, transcript, judge: Judge,
        model, plans=None, bindings=None, metered=None,
        provider: str = "deepseek",
    ) -> None:
        self._sessions = sessions
        self._visits = visits
        self._evidence = evidence
        self._loader = loader
        self._transcript = transcript
        self._judge = judge
        self._model = model
        self._plans = plans
        self._bindings = bindings
        self._metered = metered
        self._provider = provider

    # -- the whole of it ---------------------------------------------------

    def grade(self, session_id: str) -> list[EvidenceWrite]:
        """Every reached Topic, once. Returns what was written this time.

        Marking the unasked items `unreached` happens here rather than in the
        graph node, so the three callers do not each have to remember it —
        a Session ended by `/end` has the same plan states as one ended by the
        clock, because the same call put them there.
        """
        row = self._sessions.get(session_id)
        if row is None:
            return []
        if self._plans is not None:
            self._plans.mark_unreached(session_id)

        messages = self._transcript.of(session_id)
        visits = self._visits.for_session(session_id)
        written: list[EvidenceWrite] = []
        for bundle in self.bundles(messages, visits):
            out = self._grade_one(row, bundle)
            if out is not None:
                written.append(out)
        # An answered Visit in a graded Session owes nothing more. MCP Mode
        # still grades per Visit and closes its own; this closes the managed
        # loop's, which ISSUE-0042 left terminal at `answered`.
        self._visits.mark_graded(session_id)
        return written

    # -- assembling --------------------------------------------------------

    def bundles(self, messages: list[dict], visits: list[dict]) -> list[TopicBundle]:
        """One bundle per Topic that appears in any message's `topic_ids`.

        A Topic with no messages gets no bundle, which is the whole of "planned
        but never reached is not a zero" — it is an absence, and absences are
        not iterated over.
        """
        order: list[str] = []
        per_topic: dict[str, list[dict]] = {}
        for m in messages:
            for topic_id in m.get("topic_ids") or ():
                if topic_id not in per_topic:
                    per_topic[topic_id] = []
                    order.append(topic_id)
                per_topic[topic_id].append(m)

        out = []
        for topic_id in order:
            rows = per_topic[topic_id]
            questions = [
                m for m in rows
                if m["role"] == "interviewer" and m["kind"] == GRADED_KIND
            ]
            if not questions:
                # Only ever reachable from a hand-written transcript: the loop
                # writes a question before it writes anything else about a
                # Topic. Nothing to grade against, so nothing is graded.
                continue
            turns = [
                {"role": m["role"], "kind": m["kind"], "text": m["text"]}
                for m in rows
                if m["role"] == "candidate"
                or (m["role"] == "interviewer" and m["kind"] == GRADED_KIND)
            ]
            visit = self._last_visit(topic_id, rows, visits)
            out.append(TopicBundle(
                topic_id=topic_id,
                question="\n\n".join(m["text"] for m in questions),
                turns=turns,
                question_count=len(questions),
                topic_visit_id=(visit or {}).get("topic_visit_id"),
                grounding_ref=(visit or {}).get("grounding_ref"),
            ))
        return out

    @staticmethod
    def _last_visit(topic_id: str, rows: list[dict], visits: list[dict]) -> dict | None:
        """The last question that examined this Topic.

        Kept on the row so a grade stays traceable to a question that was
        actually asked, and so `/spend` and the re-judge path keep finding a
        Visit where they always did. The column is nullable since ISSUE-0039
        because an Evidence row need not descend from any single question — it
        is not nullable because nothing knows which ones it did.
        """
        ids = {m["topic_visit_id"] for m in rows if m.get("topic_visit_id")}
        found = [v for v in visits if v["topic_visit_id"] in ids]
        return found[-1] if found else None

    # -- grading -----------------------------------------------------------

    def _grade_one(self, row: dict, b: TopicBundle) -> EvidenceWrite | None:
        try:
            dossier = self._loader.load(b.topic_id)
        except LookupError:
            # The material was withdrawn under the Session (ISSUE-0027). There
            # is nothing left to grade against, and a Verdict reached against
            # no grounding is a measurement nobody made.
            return None

        # The Topic's *own* mode, not the weakest across a spanning question's
        # dossiers: this grade is against this dossier, so a Topic with an
        # Answer Key is graded on it even where it shared a question with one
        # that has none.
        mode = mode_for(dossier)
        self._bind(row, b.topic_visit_id)
        verdict = self._judge.grade(
            question=b.question,
            exchange=b.turns,
            dossier=dossier,
            mode=mode,
            topic_visit_id=b.topic_visit_id or f"grade_{row['session_id']}",
            model=self._model,
        )
        write = self._evidence.write_topic(
            session_id=row["session_id"],
            candidate_id=row["candidate_id"],
            topic_id=b.topic_id,
            topic_visit_id=b.topic_visit_id,
            score=verdict.score,
            source_score=verdict.source_score,
            truth_score=verdict.truth_score,
            question_count=b.question_count,
            mode=mode,
            grader_kind="server_judge",
            provider=row.get("provider_chosen") or self._provider,
            rubric_version=verdict.rubric_version,
            rationale=verdict.rationale,
            exchange_snapshot={"turns": b.turns},
            citations=resolve(dossier, b.grounding_ref),
            topic_title=dossier.topic_title,
            module_title=dossier.module_title,
        )
        return None if write.already_existed else write

    def _bind(self, row: dict, topic_visit_id: str | None) -> None:
        """Point the metered client at the question this grade came from.

        Grading is a model call and therefore a charge. It is attributed to a
        Visit that actually happened rather than to a new reference, so
        `/spend`'s per-Visit lines still add up to what the ledger took.
        """
        if self._metered is None or not topic_visit_id:
            return
        binding = None
        if self._bindings is not None:
            binding = self._bindings.get(topic_visit_id)
            if binding is None:
                from ..metering.client_service import Binding

                binding = self._bindings.bind(Binding(
                    topic_visit_id,
                    row.get("provider_chosen") or self._provider,
                    row.get("payment_route") or "credits",
                ))
        if binding is not None:
            self._metered.bind(
                binding,
                session_id=row["session_id"],
                candidate_id=row["candidate_id"],
            )
