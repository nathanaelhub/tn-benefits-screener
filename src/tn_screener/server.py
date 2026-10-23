"""MCP server: the screener's engine, rules and policy search as tools.

The model gathers the facts in conversation and calls ``screen_household``;
it never does the eligibility arithmetic itself. ``search_policy`` and
``get_rule`` let it quote the official text behind an answer.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from . import engine, policy, rules

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False, idempotent_hint=True)

INSTRUCTIONS = """\
Screens a Tennessee household for SNAP (food assistance), WIC and TennCare/CoverKids,
using official 2026-27 limits. Gather the facts first, then call screen_household; do
not compute eligibility yourself. Results are likely / possibly / unlikely / refer;
none is a decision, and anyone can apply. Cite the sources in the result's
`citations`. Tennessee's SNAP gross income limit is unsettled (130% officially, 200%
reported): pass on the result's wording rather than picking one."""


class PersonIn(BaseModel):
    age: int = Field(description="Age in years; 0 for a baby under 1.")
    label: str | None = Field(None, description="How to refer to this person, e.g. 'you', 'your son'. "
                                                 "Don't use full names.")
    pregnant: bool = False
    babies_expected: int = Field(1, description="If pregnant: how many babies (2 for twins).")
    months_since_pregnancy_ended: int | None = Field(
        None, description="For a woman who gave birth or whose pregnancy ended in the last year.")
    breastfeeding: bool = False
    disabled: bool = Field(False, description="Has a disability or gets disability benefits.")
    college_student: bool = Field(False, description="Enrolled in college at least half time.")
    us_citizen: bool | None = Field(True, description="False if not a U.S. citizen; null if they'd rather "
                                                      "not say.")
    former_foster_youth: bool = Field(False, description="Was in foster care at 18.")
    gets_ssi: bool = Field(False, description="Gets Supplemental Security Income (SSI).")
    gets_families_first: bool = Field(False, description="Gets Families First (Tennessee's TANF cash aid).")


class IncomeIn(BaseModel):
    amount: float = Field(description="Before taxes.")
    frequency: Literal["monthly", "weekly", "biweekly", "semimonthly", "yearly"] = "monthly"
    kind: Literal["earned", "unearned", "self_employment"] = Field(
        "earned", description="earned = wages; unearned = Social Security, SSI, unemployment, child support "
                              "received, etc.; self_employment = own business or gig work.")


class HouseholdIn(BaseModel):
    members: list[PersonIn] = Field(description="Everyone who lives together and buys and cooks food "
                                                "together, including the person asking.")
    income: list[IncomeIn] = Field(default_factory=list, description="Every source of income for anyone in "
                                                                      "the household; empty if none.")
    rent_or_mortgage: float | None = Field(None, description="Monthly rent or mortgage, including property "
                                                             "tax and home insurance; 0 if none; null if not asked.")
    utilities: Literal["heating_cooling", "other", "phone_only", "none"] | None = Field(
        None, description="What the household pays for separately from rent: heating_cooling = pays for "
                          "heat or air conditioning; other = pays other utilities (electric, water) but not "
                          "heating or cooling; phone_only; none = all included in rent; null if not asked.")
    dependent_care: float | None = Field(None, description="Monthly child or adult care paid so someone can "
                                                           "work or go to school; null if not asked.")
    child_support_paid: float = Field(0, description="Monthly court-ordered child support paid out.")
    medical_costs: float | None = Field(None, description="Monthly out-of-pocket medical costs for members "
                                                          "60+ or disabled; null if not asked.")
    homeless: bool = False
    resources: float | None = Field(None, description="Cash and bank account balances; null if not asked.")
    receives: list[Literal["snap", "wic", "tenncare"]] | None = Field(
        None, description="Programs the household already gets; [] if none; null if not asked.")


def build_server() -> MCPServer:
    mcp = MCPServer("tn-benefits", instructions=INSTRUCTIONS, version="0.1.0")

    @mcp.tool(annotations=READ_ONLY)
    def screen_household(household: HouseholdIn, as_of: str | None = None) -> dict:
        """Screen a Tennessee household for SNAP, WIC and TennCare/CoverKids.

        Leave a fact null if it wasn't asked: the result's `missing_facts` then
        lists the questions that could change the answer.

        Returns each program's status (likely / possibly / unlikely / refer /
        already_enrolled / not_applicable), a plain-language summary, the
        arithmetic as steps, notes, next steps (where to apply), warnings, and
        citations for every rule used. `as_of` (YYYY-MM-DD) defaults to today.
        """
        try:
            when = date.fromisoformat(as_of) if as_of else None
            return engine.screen(household.model_dump(), when)
        except (engine.InvalidHousehold, rules.StaleRules, ValueError) as e:
            raise ToolError(str(e)) from e

    @mcp.tool(annotations=READ_ONLY)
    def search_policy(query: str, program: Literal["snap", "wic", "tenncare"] | None = None,
                      limit: int = 5, official_only: bool = True) -> list[dict]:
        """Search the official SNAP, WIC and TennCare policy texts the screener is built on.

        For questions the screening doesn't answer (what counts as income, a
        special situation). Returns passages with their source, publisher and
        URL; quote them rather than paraphrasing from memory.
        """
        if not query.strip():
            raise ToolError("query is empty")
        return policy.search(query, max(1, min(limit, 10)), program, official_only)

    @mcp.tool(annotations=READ_ONLY)
    def get_rule(rule_id: str | None = None) -> dict:
        """One rule's figures, effective dates and cited sources; with no id, the list of rule ids."""
        all_rules = rules.load()
        if not rule_id:
            return {"rules": {r.id: r.title for r in all_rules.values()}}
        r = all_rules.get(rule_id)
        if r is None:
            raise ToolError(f"unknown rule {rule_id!r}; call get_rule with no id for the list")
        return {
            "id": r.id, "title": r.title, "status": r.status, "value": r.value, "table": r.table,
            "each_additional": r.each_additional, "note": r.note,
            "effective_from": r.effective_from.isoformat(),
            "effective_to": r.effective_to.isoformat() if r.effective_to else None,
            "sources": r.citations(),
            "contradicted_by": [c.as_dict() for c in r.contradicted_by],
        }

    return mcp


def main() -> None:
    build_server().run("stdio")


if __name__ == "__main__":
    main()
