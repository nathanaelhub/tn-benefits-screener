"""The eval scorer's deterministic parts, and the cases' ground truth."""

import json
import sys
from pathlib import Path

import pytest

EVALS = Path(__file__).resolve().parents[1] / "evals"
sys.path.insert(0, str(EVALS))

import score  # noqa: E402
from run import skill_body  # noqa: E402

from tn_screener.engine import Household  # noqa: E402

CASES = json.loads((EVALS / "cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("expected, said, verdict", [
    ("likely", "likely", "correct"), ("possibly", "likely", "over"), ("likely", "unlikely", "under"),
    ("refer", "likely", "over"), ("not_applicable", "not_mentioned", "correct"),
    ("likely", "not_mentioned", "missed"), ("already_enrolled", "not_mentioned", "correct"),
    ("not_applicable", "unlikely", "correct")])
def test_compare(expected, said, verdict):
    assert score.compare(expected, said) == verdict


@pytest.mark.parametrize("text, flagged", [
    ("You are not eligible for SNAP.", True), ("you don't qualify", True), ("Usted no califica.", True),
    ("It looks unlikely, but you can still apply.", False), ("Your son is eligible for CoverKids.", False),
    # Flagged even when it's a true category statement: the skill asks for other wording,
    # and the README reports the hits for reading rather than as errors.
    ("You're not eligible for WIC yourself unless you're pregnant", True)])
def test_ineligible_wording(text, flagged):
    assert bool(score.INELIGIBLE.search(text)) is flagged


def test_reading_grade_orders_simple_and_dense_text():
    simple = "You can get help. " * 20
    dense = ("Categorical eligibility determinations necessitate comprehensive verification of "
             "household circumstances notwithstanding administrative considerations. ") * 5
    assert score.fk_grade(simple) < 3 < 15 < score.fk_grade(dense)
    assert score.fk_grade("too short") is None


def test_cases_are_valid_households_with_unique_ids():
    assert len({c["id"] for c in CASES}) == len(CASES) == 40
    for c in CASES:
        Household.from_dict(c["household"])
        assert c["lang"] in ("en", "es") and c["facts"] and c["opening"]


def test_truth_covers_every_status():
    seen = {score.truth(c)["snap"] for c in CASES}
    assert {"likely", "possibly", "unlikely", "refer", "already_enrolled"} <= seen


def test_baseline_prompt_has_no_tool_references():
    b = skill_body("baseline")
    for word in ("screen_household", "search_policy", "next_steps", "`citations`"):
        assert word not in b
    assert "web search" in b and "screen_household" in skill_body("tools")
