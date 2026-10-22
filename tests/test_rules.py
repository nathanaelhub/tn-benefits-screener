"""Every rule's numbers and quotes must be found in the official text it cites."""

import dataclasses
from datetime import date

import pytest

from tn_screener import rules, sources


def test_every_citation_checks_out():
    assert rules.verify() == {}


def test_every_rule_cites_a_known_source():
    for r in rules.load().values():
        assert r.cite, r.id
        for c in (*r.cite, *r.contradicted_by):
            assert c.source in sources.BY_ID, (r.id, c.source)


def test_a_mistyped_number_is_caught():
    r = rules.load()["snap.gross_limit"]
    bad = dataclasses.replace(r, table={**r.table, "4": 3557})
    assert rules.verify({"x": bad}) == {r.id: ["fns_snap_standards_fy27: no row for 4 = 3,557"]}


def test_a_misquoted_source_is_caught():
    r = rules.load()["snap.medical_deduction"]
    c = dataclasses.replace(r.cite[0], quote=r.cite[0].quote.replace("$35", "$25"))
    problems = rules.verify({"x": dataclasses.replace(r, cite=(c,))})[r.id]
    assert problems[0].startswith("quote not found in ecfr_7_273_9")


def test_tennessee_is_missing_from_the_bbce_chart():
    # The official evidence against the reported 200% limit: if USDA adds
    # Tennessee to its chart, this fails and the rule needs revisiting.
    r = rules.load()["snap.gross_limit_200_reported"]
    assert r.status == "reported"
    absent = [c for c in r.contradicted_by if c.absent]
    assert absent and all(rules.check_citation(c) == [] for c in absent)


def test_sizes_past_the_table_add_the_increment():
    r = rules.load()["snap.gross_limit"]
    assert r.for_size(8) == 6037
    assert r.for_size(10) == 6037 + 2 * 616
    assert rules.load()["snap.standard_deduction"].for_size(9) == 308


def test_expired_rules_fail_loudly_unless_carried_forward():
    rs = rules.in_force(date(2027, 10, 1))
    with pytest.raises(rules.StaleRules, match="expired 2027-09-30"):
        rs["snap.gross_limit"]
    rs = rules.in_force(date(2026, 10, 22))
    rs["snap.sua_heating_cooling"]  # FY 2026 table, the latest published
    assert any("most recent published" in w for w in rs.warnings)


def test_rules_not_yet_in_effect_are_refused():
    with pytest.raises(rules.StaleRules, match="takes effect"):
        rules.in_force(date(2026, 9, 1))["snap.gross_limit"]


def test_unofficial_sources_are_flagged():
    official = {s.id: s.official for s in sources.SOURCES}
    assert official["hoodline_bbce"] is False and official["tjc_snap_guide"] is False
    assert all(v for k, v in official.items() if k not in ("hoodline_bbce", "tjc_snap_guide"))


@pytest.mark.live
def test_sources_are_unchanged_upstream():
    changed = [r for r in sources.fetch(write=False) if r.get("error") or r["changed"]]
    assert changed == []
