"""Finding the notebook's own answer keys.

A Candidate's sources sometimes already contain the strongest structure any
Corpus can offer: a question, and the worked answer to it. Where that structure
is present it is *recognised*, never manufactured.

Nothing in this module writes text. It classifies spans that already exist, so
every Ground Truth leaf is quotable back to the source it came from — which is
the difference between Ground-Truth grading and model judgment wearing its badge
(Principle 4).
"""

from __future__ import annotations

import re

from .chunking import Chunk

#: A heading that announces worked answers. These are the words people actually
#: write above them.
KEY_HEADING = re.compile(
    r"^\s{0,3}#{1,6}\s*(answer\s*key|answers?|solutions?|worked\s+(answers?|solutions?)|"
    r"model\s+answers?|mark\s*scheme)\b",
    re.IGNORECASE | re.MULTILINE,
)
#: A heading that announces the questions those answers belong to.
PROMPT_HEADING = re.compile(
    r"^\s{0,3}#{1,6}\s*(exercises?|questions?|problems?|assignment|quiz|practice)\b",
    re.IGNORECASE | re.MULTILINE,
)
_ANSWER_ITEM = re.compile(r"(?:^|\n)\W{0,4}A\s?\d+[.):]", re.IGNORECASE)
_QUESTION_ITEM = re.compile(r"(?:^|\n)\W{0,4}Q\s?\d+[.):]", re.IGNORECASE)
_NUMBERED = re.compile(r"(?:^|\n)\s{0,3}\d+[.)]\s")

#: How many question or answer items a passage needs before it is called one.
#: A single stray "Q1." in prose is a mention; three of them is a structure.
ITEM_THRESHOLD = 2


def looks_like_answers(text: str) -> bool:
    if KEY_HEADING.search(text):
        return True
    return len(_ANSWER_ITEM.findall(text)) >= ITEM_THRESHOLD


def looks_like_questions(text: str) -> bool:
    if looks_like_answers(text):
        return False
    if len(_QUESTION_ITEM.findall(text)) >= ITEM_THRESHOLD:
        return True
    if PROMPT_HEADING.search(text) and (
        text.count("?") >= ITEM_THRESHOLD or len(_NUMBERED.findall(text)) >= ITEM_THRESHOLD
    ):
        return True
    return False


def classify(chunks: list[Chunk]) -> dict[str, str]:
    """Label a Topic's chunks as `prompt`, `ground_truth` or `content`.

    An answers passage is Ground Truth only when the questions it answers are in
    the same Topic: a key with no reachable prompt would be an authoritative
    answer to a question nobody can see, which grades nothing.
    """
    ordered = sorted(chunks, key=lambda c: c.char_start)
    out: dict[str, str] = {}
    last_prompt: str | None = None
    for chunk in ordered:
        if looks_like_answers(chunk.text):
            if last_prompt is not None:
                out[chunk.chunk_id] = "ground_truth"
                continue
            out[chunk.chunk_id] = "content"
        elif looks_like_questions(chunk.text):
            out[chunk.chunk_id] = "prompt"
            last_prompt = chunk.chunk_id
        else:
            out[chunk.chunk_id] = "content"
    return out


def answered_by(chunks: list[Chunk], kinds: dict[str, str]) -> dict[str, str]:
    """Map each Ground Truth chunk to the prompt chunk it answers."""
    ordered = sorted(chunks, key=lambda c: c.char_start)
    pairs: dict[str, str] = {}
    last_prompt: str | None = None
    for chunk in ordered:
        kind = kinds.get(chunk.chunk_id)
        if kind == "prompt":
            last_prompt = chunk.chunk_id
        elif kind == "ground_truth" and last_prompt is not None:
            pairs[chunk.chunk_id] = last_prompt
    return pairs
