"""Every user story in every PRD is mapped to code and to a test.

This makes "the stories are done" checkable rather than asserted, and it fails
if a PRD gains a story that nothing implements — so the claim cannot quietly
rot.
"""

import pathlib
import re

import pytest

from interviewer._audit.coverage import COVERAGE

DOCS = pathlib.Path(__file__).resolve().parents[2] / "docs" / "prd"
SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "interviewer"
TESTS = pathlib.Path(__file__).resolve().parent


def _stories() -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    for f in sorted(DOCS.glob("*.md")):
        body = f.read_text()
        if "## User Stories" not in body:
            continue
        sec = body.split("## User Stories")[1].split("## Implementation")[0]
        out[f.name[:4]] = [
            int(n) for n, _ in re.findall(r"^(\d+)\.\s+(As .+?)$", sec, re.M)
        ]
    return out


ALL = _stories()


def test_the_prds_still_hold_the_number_of_stories_we_audited():
    assert {k: len(v) for k, v in ALL.items()} == {
        "0001": 29, "0002": 38, "0003": 42, "0004": 35, "0005": 47,
    }
    assert sum(len(v) for v in ALL.values()) == 191


def test_every_story_is_mapped_to_an_implementation_and_a_test():
    unmapped = [
        f"PRD-{prd} §{n}"
        for prd, numbers in ALL.items()
        for n in numbers
        if (prd, n) not in COVERAGE
    ]
    assert not unmapped, unmapped


def test_the_map_contains_no_stories_the_prds_do_not_have():
    stale = [
        f"PRD-{prd} §{n}"
        for (prd, n) in COVERAGE
        if n not in ALL.get(prd, [])
    ]
    assert not stale, stale


@pytest.mark.parametrize("key", sorted(COVERAGE))
def test_each_mapped_module_and_test_file_exists(key):
    module, test = COVERAGE[key]
    path = SRC / module.split(":")[0]
    assert path.is_file(), f"{key} -> {module}"
    assert (TESTS / test).is_file(), f"{key} -> {test}"


def test_named_symbols_exist_where_the_map_says_they_do():
    missing = []
    for key, (module, _) in COVERAGE.items():
        if ":" not in module:
            continue
        file, symbol = module.split(":", 1)
        src = (SRC / file).read_text()
        if not re.search(rf"\b{re.escape(symbol)}\b", src):
            missing.append(f"{key} -> {module}")
    assert not missing, missing
