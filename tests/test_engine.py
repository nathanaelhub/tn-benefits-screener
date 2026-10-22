"""Hand-computed screenings. Each expected number is worked out in the comment above it."""

import dataclasses
import re
from datetime import date
from pathlib import Path

import pytest

from tn_screener import engine, rules
from tn_screener.engine import InvalidHousehold, screen

AS_OF = date(2026, 10, 22)


def run(h, as_of=AS_OF):
    return screen(h, as_of)


def snap(h):
    return run(h)["programs"]["snap"]


def tenncare(h):
    return run(h)["programs"]["tenncare"]


def wic(h):
    return run(h)["programs"]["wic"]


def people(n_adults=1, kids=()):
    return [{"age": 30}] * n_adults + [{"age": a} for a in kids]


def pay(amount, kind="earned", frequency="monthly"):
    return {"amount": amount, "kind": kind, "frequency": frequency}


# The household in USDA's "How much could I receive" worked example.
USDA_EXAMPLE = {"members": people(2, (8, 5)), "income": [pay(1500), pay(550, "unearned")],
                "dependent_care": 362, "rent_or_mortgage": 700}


# SNAP -----------------------------------------------------------------------


def test_usda_worked_example_reproduced_with_its_standard_deduction(monkeypatch):
    # USDA's example subtracts $217 for a 4-person household: 2,050 - 300 - 217
    # - 362 = 1,171; shelter 700 - 585.50 = 114.50; net 1,056.50; 30% = 317
    # (rounded up); 1,023 - 317 = $706, exactly as published.
    rs = rules.in_force(AS_OF)
    std = rs.rules["snap.standard_deduction"]
    rs.rules["snap.standard_deduction"] = dataclasses.replace(std, table={**std.table, "4": 217})
    monkeypatch.setattr(engine, "in_force", lambda as_of=None: rs)
    s = snap(USDA_EXAMPLE)
    assert s["estimate"] == {"monthly_benefit": 706, "net_income": 1056.5, "gross_income": 2050}


def test_usda_worked_example_with_the_published_table():
    # The FY 2027 table says $229 for 4 people, not $217: 2,050 - 300 - 229 -
    # 362 = 1,159; shelter 700 - 579.50 = 120.50; net 1,038.50; 30% = 312;
    # 1,023 - 312 = $711.
    s = snap(USDA_EXAMPLE)
    assert s["status"] == "likely"
    assert s["estimate"] == {"monthly_benefit": 711, "net_income": 1038.5, "gross_income": 2050}


def test_gross_limit_is_inclusive():
    # One adult earning exactly $1,729 (130%): passes gross. Net: 1,729 -
    # 345.80 - 217 = 1,166.20 <= 1,330.
    assert snap({"members": people(), "income": [pay(1729)]})["status"] == "likely"


def test_between_130_and_200_percent_is_possibly():
    # $1 over the federal gross limit but well under the reported 200% limit
    # ($2,660). Net: 1,730 - 346 - 217 = 1,167 <= 1,330.
    s = snap({"members": people(), "income": [pay(1730)]})
    assert s["status"] == "possibly"
    assert "snap.gross_limit_200_reported" in s["rules"]
    assert "no official source confirms" in s["summary"]


def test_over_200_percent_is_unlikely():
    s = snap({"members": people(), "income": [pay(2700)]})
    assert s["status"] == "unlikely" and "over the limit of $1,729" in s["summary"]


def test_net_test_can_fail_after_gross_passes():
    # Unearned income gets no 20% deduction: 1,700 - 217 = 1,483 > 1,330.
    s = snap({"members": people(), "income": [pay(1700, "unearned")]})
    assert s["status"] == "unlikely" and "net income after deductions ($1,483)" in s["summary"]


def test_elderly_skip_gross_test_and_get_medical_and_uncapped_shelter():
    # One person, 67, $2,000 Social Security (over the $1,729 gross limit, but
    # elderly households only face the net test). 2,000 - 217 - (135 - 35) =
    # 1,683. Shelter: 800 rent + 451 SUA = 1,251 - 841.50 = 409.50, uncapped.
    # Net 1,273.50 <= 1,330. 30% = 383 > $306 maximum, so the 1-person
    # minimum of $25 applies.
    h = {"members": [{"age": 67}], "income": [pay(2000, "unearned")], "medical_costs": 135,
         "rent_or_mortgage": 800, "utilities": "heating_cooling"}
    s = snap(h)
    assert s["status"] == "likely"
    assert s["estimate"]["net_income"] == 1273.5 and s["estimate"]["monthly_benefit"] == 25
    assert {"snap.elderly_disabled_net_only", "snap.medical_deduction", "snap.min_allotment"} <= set(s["rules"])


def test_medical_costs_only_count_for_elderly_or_disabled():
    h = {"members": people(), "income": [pay(1000, "unearned")], "medical_costs": 500}
    assert "snap.medical_deduction" not in snap(h)["rules"]
    h["members"] = [{"age": 40, "disabled": True}]
    assert "snap.medical_deduction" in snap(h)["rules"]


def test_shelter_deduction_is_capped_without_elderly_or_disabled():
    # 2 adults, $1,500 earnings: 1,500 - 300 - 217 = 983; rent 2,000 - 491.50
    # = 1,508.50, capped at 769; net 214; 30% = 64.20 -> 65; 562 - 65 = $497.
    s = snap({"members": people(2), "income": [pay(1500)], "rent_or_mortgage": 2000})
    assert "snap.shelter_cap" in s["rules"]
    assert s["estimate"]["net_income"] == 214 and s["estimate"]["monthly_benefit"] == 497


def test_homeless_shelter_deduction():
    # 1,000 unearned - 217 = 783 - 205.66 = 577.34 net; 30% = 173.20 -> 174;
    # 306 - 174 = $132.
    s = snap({"members": people(), "income": [pay(1000, "unearned")], "homeless": True})
    assert s["estimate"]["net_income"] == 577.34 and s["estimate"]["monthly_benefit"] == 132


@pytest.mark.parametrize("utilities, allowance", [("heating_cooling", 485), ("other", 162),
                                                  ("phone_only", 36), ("none", 0)])
def test_utility_allowances(utilities, allowance):
    # 3 people, no income: adjusted income 0, so the whole shelter cost
    # (rent 500 + allowance) is excess, capped at 769.
    h = {"members": people(1, (4, 7)), "rent_or_mortgage": 500, "utilities": utilities}
    r = run(h)
    assert r["programs"]["snap"]["estimate"]["net_income"] == 0
    reasons = " ".join(r["programs"]["snap"]["reasons"])
    if allowance:
        assert f"housing and utilities of ${500 + allowance:,}" in reasons
    if utilities == "heating_cooling":
        assert any("most recent published figures" in w for w in r["warnings"])


def test_income_frequency_conversion():
    # $400 a week x 4.3 = $1,720; $800 every two weeks x 2.15 = $1,720;
    # $20,640 a year / 12 = $1,720.
    for p in (pay(400, frequency="weekly"), pay(800, frequency="biweekly"), pay(20640, frequency="yearly")):
        assert snap({"members": people(), "income": [p]})["estimate"]["gross_income"] == 1720


def test_savings_over_the_limit_make_it_possibly():
    s = snap({"members": people(), "income": [pay(1000)], "resources": 5000})
    assert s["status"] == "possibly" and "over the $3,000 resource limit" in s["summary"]
    s = snap({"members": [{"age": 61}], "income": [pay(1000)], "resources": 4000})
    assert s["status"] == "likely"  # $4,750 limit with a member 60+


def test_unasked_savings_are_noted():
    s = snap({"members": people(), "income": [pay(1000)]})
    assert any("Savings weren't asked about" in n for n in s["notes"])


def test_categorical_households_skip_the_limits():
    s = snap({"members": [{"age": 50, "gets_ssi": True}], "income": [pay(3000, "unearned")]})
    assert s["status"] == "likely" and "snap.categorical" in s["rules"]


def test_non_citizens_are_referred_with_the_indicative_result():
    h = {"members": [{"age": 30, "us_citizen": False}, {"age": 3}], "income": [pay(1200)]}
    s = snap(h)
    assert s["status"] == "refer" and s["estimate"] is None
    assert "snap.noncitizens" in s["rules"] and "likely eligible" in s["summary"]


def test_college_students_18_to_49_are_referred():
    assert snap({"members": [{"age": 20, "college_student": True}]})["status"] == "refer"
    assert snap({"members": [{"age": 52, "college_student": True}]})["status"] == "likely"


def test_self_employment_is_referred():
    assert snap({"members": people(), "income": [pay(900, "self_employment")]})["status"] == "refer"


def test_work_rule_note_for_adults_without_children():
    s = snap({"members": people(), "income": [pay(800)]})
    assert "snap.work_rules" in s["rules"]
    s = snap({"members": people(1, (6,)), "income": [pay(800)]})
    assert "snap.work_rules" not in s["rules"]


def test_child_support_paid_is_deducted():
    # 1,600 unearned - 217 - 300 = 1,083 <= 1,330 (without it, 1,383 fails).
    h = {"members": people(), "income": [pay(1600, "unearned")]}
    assert snap(h)["status"] == "unlikely"
    assert snap({**h, "child_support_paid": 300})["status"] == "likely"


def test_already_enrolled():
    assert snap({"members": people(), "receives": ["snap"]})["status"] == "already_enrolled"


# TennCare ---------------------------------------------------------------------


def test_infant_limit_is_inclusive_and_parent_limit_is_lower():
    # Mother and baby (2 people) at $3,517: exactly 195% for the baby; far
    # over the parent limit of 100% ($1,804) plus 5% ($90.20).
    t = tenncare({"members": [{"age": 28}, {"age": 0}], "income": [pay(3517)]})
    by = {p["name"]: p for p in t["people"]}
    assert by["person 2 (age 0)"]["status"] == "likely"
    assert by["person 1 (age 28)"]["status"] == "unlikely"
    assert t["status"] == "likely"


def test_five_percent_disregard():
    # 3 people, caretaker limit $2,277; 5% of poverty adds $113.85 -> $2,390.85.
    t = tenncare({"members": people(1, (2, 9)), "income": [pay(2350)]})
    parent = t["people"][0]
    assert parent["status"] == "possibly" and "disregard" in parent["reason"]
    assert "tenncare.disregard" in t["rules"]
    t = tenncare({"members": people(1, (2, 9)), "income": [pay(2400)]})
    assert t["people"][0]["status"] == "unlikely"


def test_children_over_medicaid_limits_fall_to_coverkids():
    # 3 people at $4,000: over 133% ($3,028) and 142% ($3,233), under 250% ($5,692).
    t = tenncare({"members": people(1, (3, 10)), "income": [pay(4000)]})
    kids = t["people"][1:]
    assert [k["program"] for k in kids] == ["CoverKids", "CoverKids"]
    assert all(k["status"] == "likely" for k in kids)


def test_children_over_250_percent():
    t = tenncare({"members": people(1, (10,)), "income": [pay(4600)]})  # 250% for 2 = $4,509
    assert t["people"][1]["status"] == "unlikely"


def test_pregnancy_counts_expected_babies():
    # Single woman expecting twins counts as 3: 250% = $5,692, so $5,000 qualifies
    # (as a household of 1 the limit would be $3,325).
    t = tenncare({"members": [{"age": 26, "pregnant": True, "babies_expected": 2}], "income": [pay(5000)]})
    assert t["people"][0]["status"] == "likely"
    assert "tenncare.pregnant_family_size" in t["rules"]


def test_adults_without_children_generally_dont_qualify():
    t = tenncare({"members": people(), "income": [pay(0)]})
    assert t["status"] == "unlikely" and "doesn't cover adults" in t["people"][0]["reason"]


def test_older_or_disabled_adults_are_referred():
    assert tenncare({"members": [{"age": 70}]})["status"] == "refer"
    assert tenncare({"members": [{"age": 40, "disabled": True}]})["status"] == "refer"


def test_former_foster_youth_under_26():
    assert tenncare({"members": [{"age": 22, "former_foster_youth": True}]})["status"] == "likely"
    assert tenncare({"members": [{"age": 27, "former_foster_youth": True}]})["status"] == "unlikely"


def test_tenncare_already_enrolled():
    assert tenncare({"members": people(), "receives": ["tenncare"]})["status"] == "already_enrolled"


# WIC ------------------------------------------------------------------------


def test_wic_needs_someone_in_its_groups():
    assert wic({"members": people(2, (6, 9))})["status"] == "not_applicable"


def test_wic_child_under_5():
    # 2 people at $3,000 <= $3,337 (185% for 2).
    w = wic({"members": people(1, (3,)), "income": [pay(3000)]})
    assert w["status"] == "likely" and "wic.nutrition_risk" in w["rules"]


def test_wic_counts_the_unborn_baby():
    # Alone she'd be 1 ($2,461 limit); with the baby she's 2 ($3,337).
    w = wic({"members": [{"age": 24, "pregnant": True}], "income": [pay(3000)]})
    assert w["status"] == "likely" and "wic.unborn" in w["rules"]


def test_wic_adjunctive_through_snap():
    w = wic({"members": people(1, (2,)), "income": [pay(9000)], "receives": ["snap"]})
    assert w["status"] == "likely" and "wic.adjunctive" in w["rules"]


def test_wic_adjunctive_through_families_first():
    w = wic({"members": [{"age": 30, "gets_families_first": True}, {"age": 1}], "income": [pay(9000)]})
    assert w["status"] == "likely"


def test_wic_through_tenncare_for_pregnant_women():
    # Pregnant, alone, $4,000: over WIC's $3,337 (household of 2) but under
    # TennCare's 250% for 2 ($4,509). TennCare is Medicaid, which makes her
    # income-eligible for WIC.
    w = wic({"members": [{"age": 31, "pregnant": True}], "income": [pay(4000)]})
    assert w["status"] == "possibly" and "Apply for TennCare first" in w["summary"]


def test_coverkids_does_not_carry_wic_income_eligibility():
    # A 3-year-old at $3,600 for 2: over WIC's $3,337, and on CoverKids
    # (over 142% = $2,561), which is CHIP, not Medicaid.
    h = {"members": people(1, (3,)), "income": [pay(3600)]}
    assert tenncare(h)["people"][1]["program"] == "CoverKids"
    assert wic(h)["status"] == "unlikely"


@pytest.mark.parametrize("months, breastfeeding, expected", [
    (6, False, "likely"), (7, False, "not_applicable"), (7, True, "likely"), (13, True, "not_applicable")])
def test_wic_postpartum_window(months, breastfeeding, expected):
    h = {"members": [{"age": 29, "months_since_pregnancy_ended": months, "breastfeeding": breastfeeding}],
         "income": [pay(1000)]}
    assert wic(h)["status"] == expected


# Output ---------------------------------------------------------------------


def test_every_rule_used_is_cited_with_sources():
    r = run(USDA_EXAMPLE)
    used = {rid for p in r["programs"].values() for rid in p["rules"]}
    assert used <= set(r["citations"])
    for c in r["citations"].values():
        assert c["sources"] and all(s["url"].startswith("https://") and s["quote"] for s in c["sources"])


def test_next_steps_always_include_211_and_applications():
    r = run({"members": people(1, (2,)), "income": [pay(1200)]})
    steps = {s["program"]: s for s in r["next_steps"]}
    assert steps["snap"]["url"] == "https://onedhs.tn.gov/csp?id=start_snap_application"
    assert steps["tenncare"]["phone"] == "855-259-0701"
    assert steps["wic"]["phone"] == "1-800-342-5942"
    assert steps["any"]["phone"] == "211"
    assert "anyone can apply" in r["disclaimer"]


def test_unlikely_programs_still_get_application_steps():
    r = run({"members": people(), "income": [pay(5000)]})
    assert r["programs"]["snap"]["status"] == "unlikely"
    assert "snap" in {s["program"] for s in r["next_steps"]}


@pytest.mark.parametrize("bad", [
    {"members": []},
    {"members": [{"age": -1}]},
    {"members": [{"age": 30}], "income": [{"amount": 10, "frequency": "daily"}]},
    {"members": [{"age": 30}], "income": [{"amount": -5}]},
    {"members": [{"age": 30}], "utilities": "gas"},
    {"members": [{"age": 30}], "receives": ["ssi"]},
    {"members": [{"age": 30, "favorite_color": "blue"}]},
    {"income": []},
])
def test_invalid_households_are_rejected(bad):
    with pytest.raises(InvalidHousehold):
        run(bad)


def test_expired_rules_refuse_to_screen():
    with pytest.raises(rules.StaleRules):
        run(USDA_EXAMPLE, date(2027, 10, 1))


def test_every_rule_id_in_the_engine_exists():
    src = Path(engine.__file__).read_text()
    ids = set(re.findall(r'"((?:snap|wic|tenncare|apply)\.[a-z0-9_]+)"', src))
    assert ids and ids <= set(rules.load())
