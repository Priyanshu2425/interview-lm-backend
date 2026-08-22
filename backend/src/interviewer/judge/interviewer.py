"""The agentic region — probe, hint, or close (ADR-0001).

Agency lives here and nowhere else. The loop around it is rigid, and off-script
Candidate behaviour gets explicit handling rather than emerging from the model.

A Visit may contain many Answer Turns and yields exactly one score. Probing one
concept three times is one observation examined closely, not three observations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from ..corpus.loader import Dossier
from ..graph.ports import ModelClient

Action = Literal["probe", "hint", "close"]

SYSTEM = """You are conducting a technical interview on one topic.

Decide what to do next with the candidate's latest answer. Reply with exactly
two lines:

ACTION: probe | hint | close
TEXT: <what you say next, one or two sentences — omit entirely if closing>

probe — the answer is vague, incomplete, or names the wrong reason. Push on the
        specific thing that is missing. Do not reveal the answer.
hint  — the candidate is stuck or has asked for help. Give the next step in the
        chain, not the conclusion.
close — the answer is complete, or the candidate has said they do not know, or
        further probing would only repeat itself.

Ask one thing at a time. Never state the expected answer."""


@dataclass(frozen=True, slots=True)
class Move:
    action: Action
    text: str


_GIVE_UP = re.compile(
    r"\b(i don'?t know|no idea|not sure|skip|pass|move on|next question)\b", re.I
)
_ASK_HELP = re.compile(r"\b(hint|help|stuck|a clue|nudge)\b", re.I)


class Interviewer:
    """Bounded, and explicit about the cases we refuse to leave to the model."""

    def __init__(self, max_turns: int = 6) -> None:
        self.max_turns = max_turns

    def next_move(
        self,
        *,
        question: str,
        exchange: list[dict],
        dossier: Dossier,
        turn_count: int,
        topic_visit_id: str,
        model: ModelClient,
    ) -> Move:
        latest = self._latest_answer(exchange)

        # Explicit handling, not emergent behaviour:
        # a Candidate who says they do not know is taken at their word, so one
        # blank Topic does not consume the Session.
        if _GIVE_UP.search(latest or ""):
            return Move("close", "")

        # A bound on how long one Visit can run — a single evasive exchange
        # cannot consume a Session.
        if turn_count >= self.max_turns:
            return Move("close", "")

        wants_help = bool(_ASK_HELP.search(latest or ""))

        transcript = "\n".join(
            f"{t.get('kind','turn').upper()}: {t.get('text','')}" for t in exchange
        )
        user = (
            f"TOPIC: {dossier.topic_title}\n\n"
            f"OPENING QUESTION: {question}\n\n"
            f"EXCHANGE SO FAR\n{transcript}\n\n"
            + ("The candidate has asked for help.\n" if wants_help else "")
            + f"Turns used: {turn_count} of {self.max_turns}."
        )
        reply = model.complete(
            topic_visit_id=topic_visit_id, role="interviewer",
            system=SYSTEM, user=user,
        )
        return self._parse(reply.text, wants_help)

    @staticmethod
    def _latest_answer(exchange: list[dict]) -> str:
        for t in reversed(exchange):
            if t.get("role") == "candidate":
                return t.get("text", "")
        return ""

    @staticmethod
    def _parse(text: str, wants_help: bool) -> Move:
        m = re.search(r"ACTION:\s*(probe|hint|close)", text, re.I)
        action: Action = m.group(1).lower() if m else "close"
        body = re.search(r"TEXT:\s*(.+)", text, re.I | re.S)
        said = body.group(1).strip() if body else ""
        # A Candidate who asked for help gets help, whatever the model chose.
        if wants_help and action == "probe":
            action = "hint"
        if action in ("probe", "hint") and not said:
            return Move("close", "")
        return Move(action, said)
