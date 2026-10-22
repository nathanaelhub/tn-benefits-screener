"""The eligibility arithmetic, kept out of the model's hands.

``screen(household, as_of)`` takes the facts of one Tennessee household and
returns, for SNAP, WIC and TennCare/CoverKids, a status with the reasons and
the rule ids behind each step. It is a *screener*: the agencies decide, and
the output always says so. Statuses:

``likely``            meets every test the screener checks
``possibly``          passes only under an unconfirmed rule or a disregard, or
                      depends on something the screener can't check
``unlikely``          fails a test; the person can still apply
``refer``             a situation the screener doesn't handle (non-citizens,
                      college students, self-employment, disability rules);
                      a caseworker or 211 should look at it
``already_enrolled``  the household said it already gets this program
``not_applicable``    nobody in the household is in a group the program serves

Simplifications, stated in the output where they matter: the SNAP household
is everyone listed (people who buy and cook food together), the TennCare
household is the same people (really the tax household), and gross monthly
income stands in for MAGI.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import date

from .rules import Rule, RuleSet, in_force

FREQUENCIES = ("monthly", "weekly", "biweekly", "semimonthly", "yearly")
UTILITIES = ("heating_cooling", "other", "phone_only", "none")
PROGRAMS = ("snap", "wic", "tenncare")
DISCLAIMER = ("This is a screening, not a decision. Only the state agency decides who qualifies, "
              "and anyone can apply even if this screening says they probably won't qualify.")


class InvalidHousehold(ValueError):
    pass


@dataclass
class Person:
    age: int
    label: str | None = None
    pregnant: bool = False
    babies_expected: int = 1
    months_since_pregnancy_ended: int | None = None
    breastfeeding: bool = False
    disabled: bool = False
    college_student: bool = False
    us_citizen: bool | None = True
    former_foster_youth: bool = False
    gets_ssi: bool = False
    gets_families_first: bool = False

    def name(self, i: int) -> str:
        return self.label or f"person {i + 1} (age {self.age})"


@dataclass
class Income:
    amount: float
    frequency: str = "monthly"
    kind: str = "earned"  # earned, unearned or self_employment


@dataclass
class Household:
    members: list[Person]
    income: list[Income] = field(default_factory=list)
    rent_or_mortgage: float = 0
    utilities: str = "none"
    dependent_care: float = 0
    child_support_paid: float = 0
    medical_costs: float = 0  # out of pocket, for members 60+ or disabled
    homeless: bool = False
    resources: float | None = None  # cash and bank accounts
    receives: list[str] = field(default_factory=list)  # snap, wic, tenncare

    @staticmethod
    def from_dict(d: dict) -> Household:
        try:
            members = [Person(**m) for m in d["members"]]
            income = [Income(**i) for i in d.get("income", [])]
            rest = {k: v for k, v in d.items() if k not in ("members", "income")}
            h = Household(members=members, income=income, **rest)
        except (KeyError, TypeError) as e:
            raise InvalidHousehold(f"bad household: {e}") from None
        h.validate()
        return h

    def validate(self) -> None:
        if not self.members:
            raise InvalidHousehold("the household needs at least one member")
        for p in self.members:
            if not 0 <= p.age <= 120:
                raise InvalidHousehold(f"age {p.age} is out of range")
            if p.pregnant and not 1 <= p.babies_expected <= 8:
                raise InvalidHousehold("babies_expected must be 1-8")
        for i in self.income:
            if i.frequency not in FREQUENCIES:
                raise InvalidHousehold(f"income frequency must be one of {FREQUENCIES}")
            if i.kind not in ("earned", "unearned", "self_employment"):
                raise InvalidHousehold("income kind must be earned, unearned or self_employment")
            if i.amount < 0:
                raise InvalidHousehold("income amounts can't be negative")
        if self.utilities not in UTILITIES:
            raise InvalidHousehold(f"utilities must be one of {UTILITIES}")
        for k in ("rent_or_mortgage", "dependent_care", "child_support_paid", "medical_costs"):
            if getattr(self, k) < 0:
                raise InvalidHousehold(f"{k} can't be negative")
        unknown = set(self.receives) - set(PROGRAMS)
        if unknown:
            raise InvalidHousehold(f"receives: unknown programs {sorted(unknown)}")

    @property
    def size(self) -> int:
        return len(self.members)

    @property
    def elderly_or_disabled(self) -> bool:
        return any(p.age >= 60 or p.disabled for p in self.members)

    @property
    def has_child_under_18(self) -> bool:
        return any(p.age < 18 for p in self.members)


@dataclass
class Result:
    program: str
    status: str
    summary: str
    reasons: list[str] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)
    estimate: dict | None = None
    people: list[dict] | None = None
    notes: list[str] = field(default_factory=list)

    def use(self, *rule_ids: str) -> None:
        for r in rule_ids:
            if r not in self.rules:
                self.rules.append(r)


def money(x: float) -> str:
    return f"${x:,.2f}" if x != round(x) else f"${round(x):,}"


class Screen:
    def __init__(self, h: Household, rs: RuleSet):
        self.h, self.rs = h, rs

    def r(self, rule_id: str) -> Rule:
        return self.rs[rule_id]

    def monthly(self, kinds: tuple[str, ...]) -> float:
        conv = self.r("snap.income_conversion").table
        total = 0.0
        for i in self.h.income:
            if i.kind in kinds:
                total += i.amount / 12 if i.frequency == "yearly" else i.amount * conv[i.frequency]
        return round(total, 2)

    @property
    def gross(self) -> float:
        return self.monthly(("earned", "unearned", "self_employment"))

    # SNAP ----------------------------------------------------------------

    def snap(self) -> Result:
        h = self.h
        res = Result("snap", "", "")
        res.use("snap.income_conversion")
        if "snap" in h.receives:
            res.status, res.summary = "already_enrolled", "The household already gets SNAP."
            return res

        refer = []
        if any(p.us_citizen is False for p in h.members):
            refer.append("Someone in the household isn't a U.S. citizen. Non-citizen rules changed in 2025 "
                         "and depend on immigration status, so a caseworker needs to check this. Citizens in "
                         "the household (including U.S.-born children) can still get SNAP.")
            res.use("snap.noncitizens")
        if any(p.college_student and 18 <= p.age <= 49 for p in h.members):
            refer.append("A college student aged 18-49 is in the household. Students usually need an "
                         "exemption (such as working 20 hours a week or caring for a young child).")
            res.use("snap.students")
        if any(i.kind == "self_employment" for i in h.income):
            refer.append("Self-employment income is counted after business costs, which this screener "
                         "doesn't calculate.")

        categorical = all(p.gets_ssi or p.gets_families_first for p in h.members)
        ed = h.elderly_or_disabled
        n = h.size
        gross = self.gross
        earned = self.monthly(("earned", "self_employment"))
        g130 = self.r("snap.gross_limit").for_size(n)
        g200 = self.r("snap.gross_limit_200_reported").for_size(n)
        res.use("snap.gross_limit")

        # Net income, in the order USDA lists the deductions.
        steps = [f"Gross monthly income: {money(gross)}."]
        adj = gross
        ded = self.r("snap.earned_income_deduction").value * earned
        if ded:
            adj -= ded
            steps.append(f"Minus 20% of earnings ({money(round(ded, 2))}).")
            res.use("snap.earned_income_deduction")
        std = self.r("snap.standard_deduction").for_size(n)
        adj -= std
        steps.append(f"Minus the standard deduction ({money(std)}).")
        res.use("snap.standard_deduction")
        if h.dependent_care:
            adj -= h.dependent_care
            steps.append(f"Minus dependent care ({money(h.dependent_care)}).")
            res.use("snap.dependent_care_deduction")
        if h.child_support_paid:
            adj -= h.child_support_paid
            steps.append(f"Minus child support paid ({money(h.child_support_paid)}).")
            res.use("snap.child_support_deduction")
        if ed and h.medical_costs > self.r("snap.medical_deduction").value:
            med = h.medical_costs - self.r("snap.medical_deduction").value
            adj -= med
            steps.append(f"Minus medical costs over $35 ({money(med)}).")
            res.use("snap.medical_deduction")
        adj = max(adj, 0.0)

        if h.homeless:
            shelter_ded = self.r("snap.homeless_shelter").value
            steps.append(f"Minus the homeless shelter deduction ({money(shelter_ded)}).")
            res.use("snap.homeless_shelter")
        else:
            util = 0.0
            if h.utilities == "heating_cooling":
                util = self.r("snap.sua_heating_cooling").for_size(n)
                res.use("snap.sua_heating_cooling")
            elif h.utilities == "other":
                util = self.r("snap.sua_basic").value
                res.use("snap.sua_basic")
            elif h.utilities == "phone_only":
                util = self.r("snap.sua_phone").value
                res.use("snap.sua_phone")
            costs = h.rent_or_mortgage + util
            shelter_ded = max(0.0, costs - self.r("snap.excess_shelter").value * adj)
            if costs:
                res.use("snap.excess_shelter")
            if not ed and shelter_ded > self.r("snap.shelter_cap").value:
                shelter_ded = self.r("snap.shelter_cap").value
                res.use("snap.shelter_cap")
            if shelter_ded:
                steps.append(f"Minus excess shelter costs ({money(round(shelter_ded, 2))}): housing and "
                             f"utilities of {money(costs)} above half the remaining income.")
        net = round(max(0.0, adj - shelter_ded), 2)
        steps.append(f"Net monthly income: {money(net)}.")
        net_limit = self.r("snap.net_limit").for_size(n)
        res.use("snap.net_limit")

        max_allot = self.r("snap.max_allotment").for_size(n)
        benefit = max_allot - math.ceil(self.r("snap.benefit_formula").value * net)
        res.use("snap.max_allotment", "snap.benefit_formula")
        if n <= 2 and benefit < self.r("snap.min_allotment").value:
            benefit = self.r("snap.min_allotment").value
            res.use("snap.min_allotment")
        benefit = max(benefit, 0)

        limit_key = "elderly_or_disabled" if ed else "other"
        asset_limit = self.r("snap.asset_limit").table[limit_key]
        assets_ok = h.resources is None or h.resources <= asset_limit

        gross_ok_130 = ed or gross <= g130
        gross_ok_200 = ed or gross <= g200
        net_ok = net <= net_limit
        if ed:
            res.use("snap.elderly_disabled_net_only")
            res.reasons.append("Someone is 60 or older or has a disability, so only the net income limit "
                               "applies.")
        if categorical:
            res.use("snap.categorical")
            res.reasons.append("Everyone in the household gets SSI or Families First, so SNAP's income and "
                               "resource limits don't apply.")
        res.reasons.extend(steps)
        res.reasons.append(f"Limits for {n} {'person' if n == 1 else 'people'}: gross {money(g130)}, "
                           f"net {money(net_limit)}.")
        if h.resources is not None:
            res.use("snap.asset_limit")

        # Within the net limit the formula always leaves a benefit (1-2 person
        # households get the minimum), so only categorical households can
        # qualify for $0.
        official_ok = categorical or (gross_ok_130 and net_ok and assets_ok)
        reported_ok = gross_ok_200 and net_ok
        if official_ok:
            status = "likely"
            summary = f"Likely eligible for SNAP, with an estimated {money(benefit)} a month."
            if benefit == 0:
                summary = "Likely eligible for SNAP, but with this income the benefit formula works out to $0."
        elif reported_ok:
            status = "possibly"
            res.use("snap.gross_limit_200_reported")
            why = []
            if not gross_ok_130:
                why.append(f"gross income ({money(gross)}) is over the federal limit of {money(g130)} "
                           f"but under {money(g200)}")
            if not assets_ok:
                why.append(f"savings ({money(h.resources)}) are over the {money(asset_limit)} resource limit")
            summary = ("Possibly eligible for SNAP: " + " and ".join(why) + ". News reports and advocates "
                       "say Tennessee raised its limit to 200% of poverty and dropped the resource limit in "
                       "2026, but no official source confirms it yet, so it's worth applying.")
            res.notes.append("Tennessee's SNAP income limit is unsettled: USDA's June 2026 chart of states with "
                             "broad-based categorical eligibility doesn't list Tennessee, and TDHS's manual "
                             "says its policies are being revised.")
        else:
            status = "unlikely"
            if not gross_ok_200:
                summary = (f"Unlikely to qualify for SNAP: gross income ({money(gross)}) is over the limit "
                           f"of {money(g130)} for this household size.")
            else:
                summary = (f"Unlikely to qualify for SNAP: net income after deductions ({money(net)}) is over "
                           f"the limit of {money(net_limit)}.")
        if h.resources is None and status in ("likely", "possibly") and not categorical:
            res.notes.append(f"Savings weren't asked about. Under the federal rules the limit is "
                             f"{money(asset_limit)} in cash and bank accounts.")
            res.use("snap.asset_limit")
        if status in ("likely", "possibly"):
            res.estimate = {"monthly_benefit": benefit, "net_income": net, "gross_income": gross}
        adults_without_kids = [p for p in h.members if 18 <= p.age <= 64 and not p.disabled and not p.pregnant]
        if adults_without_kids and not h.has_child_under_18 and status in ("likely", "possibly"):
            res.use("snap.work_rules")
            res.notes.append("Adults without children may only get SNAP for 3 months in 3 years unless they "
                             "work or train 20 hours a week, and these work rules changed in 2025. The "
                             "caseworker will explain what applies.")
        if refer:
            res.reasons = refer + res.reasons
            res.estimate = None
            res.status = "refer"
            res.summary = ("A caseworker needs to look at this: " + refer[0] + f" (Without that, the screener's "
                           f"result would be: {summary[0].lower()}{summary[1:]})")
            return res
        res.status, res.summary = status, summary
        return res

    # TennCare --------------------------------------------------------------

    def fpl_limit(self, pct: int, n: int) -> float:
        return self.r(f"tenncare.fpl_{pct}").for_size(n)

    def tenncare(self) -> Result:
        h = self.h
        res = Result("tenncare", "", "", people=[])
        if "tenncare" in h.receives:
            res.status, res.summary = "already_enrolled", "The household already has TennCare."
            return res
        gross = self.gross
        res.use("tenncare.fpl_100")
        res.reasons.append(f"Monthly household income used: {money(gross)} (gross income stands in for "
                           f"the tax-based income TennCare uses).")
        for i, p in enumerate(h.members):
            res.people.append(self.tenncare_person(i, p, gross, res))
        order = ["likely", "possibly", "refer", "unlikely"]
        best = min((x["status"] for x in res.people), key=order.index)
        res.status = best
        names = {s: [x["name"] for x in res.people if x["status"] == s] for s in order}
        parts = []
        if names["likely"]:
            parts.append("likely eligible: " + ", ".join(names["likely"]))
        if names["possibly"]:
            parts.append("possibly eligible: " + ", ".join(names["possibly"]))
        if names["refer"]:
            parts.append("needs a caseworker: " + ", ".join(names["refer"]))
        if names["unlikely"]:
            parts.append("unlikely: " + ", ".join(names["unlikely"]))
        res.summary = "TennCare/CoverKids — " + "; ".join(parts) + "."
        if any(x["status"] == "possibly" and "disregard" in x["reason"] for x in res.people):
            res.use("tenncare.disregard")
        return res

    def tenncare_person(self, i: int, p: Person, gross: float, res: Result) -> dict:
        h = self.h
        n = h.size + (p.babies_expected if p.pregnant else 0)
        name = p.name(i)

        def test(pct: int, rule_id: str, program: str, group: str) -> dict | None:
            limit = self.fpl_limit(pct, n)
            res.use(rule_id, f"tenncare.fpl_{pct}")
            if p.pregnant:
                res.use("tenncare.pregnant_family_size")
            if gross <= limit:
                return {"name": name, "status": "likely", "program": program,
                        "reason": f"{group}: income {money(gross)} is within the {pct}% limit "
                                  f"of {money(limit)} for a household of {n}."}
            bumped = limit + 0.05 * self.fpl_limit(100, n)
            if gross <= bumped:
                return {"name": name, "status": "possibly", "program": program,
                        "reason": f"{group}: income {money(gross)} is just over the {pct}% limit of "
                                  f"{money(limit)}, but within the 5% income disregard."}
            return None

        if p.pregnant:
            r = test(250, "tenncare.pregnant", "TennCare", "Pregnant")
            if r:
                return r
            return {"name": name, "status": "unlikely", "program": "TennCare",
                    "reason": f"Pregnant: income {money(gross)} is over the 250% limit of "
                              f"{money(self.fpl_limit(250, n))}."}
        if p.age < 19:
            if p.age < 1:
                r = test(195, "tenncare.infant", "TennCare", "Child under 1")
            elif p.age < 6:
                r = test(142, "tenncare.child_1_5", "TennCare", "Child 1-5")
            else:
                r = test(133, "tenncare.child_6_18", "TennCare", "Child 6-18")
            if r:
                return r
            r = test(250, "tenncare.coverkids", "CoverKids", "Child under 19 (CoverKids)")
            if r:
                return r
            return {"name": name, "status": "unlikely", "program": "CoverKids",
                    "reason": f"Child: income {money(gross)} is over CoverKids' 250% limit of "
                              f"{money(self.fpl_limit(250, n))}."}
        if p.age >= 65 or p.disabled or p.gets_ssi:
            res.use("tenncare.aged_blind_disabled")
            return {"name": name, "status": "refer", "program": "TennCare",
                    "reason": "People 65 or older or with a disability are screened under different rules "
                              "(including resource limits); TennCare Connect can check."}
        if p.former_foster_youth and p.age < 26:
            res.use("tenncare.other_adults")
            return {"name": name, "status": "likely", "program": "TennCare",
                    "reason": "Former foster youth can get TennCare until age 26."}
        if h.has_child_under_18:
            r = test(100, "tenncare.caretaker", "TennCare", "Parent or caretaker")
            if r:
                return r
            return {"name": name, "status": "unlikely", "program": "TennCare",
                    "reason": f"Parent or caretaker: income {money(gross)} is over the 100% limit of "
                              f"{money(self.fpl_limit(100, n))}."}
        res.use("tenncare.other_adults")
        return {"name": name, "status": "unlikely", "program": "TennCare",
                "reason": "Tennessee doesn't cover adults 19-64 who aren't pregnant, disabled, caring for a "
                          "child, or former foster youth."}

    # WIC -----------------------------------------------------------------

    def wic(self, tenncare: Result) -> Result:
        h = self.h
        res = Result("wic", "", "")
        res.use("wic.categories")
        eligible = []
        for i, p in enumerate(h.members):
            m = p.months_since_pregnancy_ended
            if p.pregnant:
                eligible.append((p.name(i), "pregnant"))
            elif m is not None and m <= 6:
                eligible.append((p.name(i), "postpartum"))
            elif m is not None and m <= 12 and p.breastfeeding:
                eligible.append((p.name(i), "breastfeeding"))
            elif p.age < 1:
                eligible.append((p.name(i), "infant"))
            elif p.age < 5:
                eligible.append((p.name(i), "child under 5"))
        if not eligible:
            res.status = "not_applicable"
            res.summary = ("WIC is for pregnant women, new mothers, babies and children under 5; no one in "
                           "the household is in those groups.")
            return res
        who = ", ".join(f"{n} ({g})" for n, g in eligible)
        if "wic" in h.receives:
            res.status, res.summary = "already_enrolled", "The household already gets WIC."
            return res
        res.use("wic.nutrition_risk")
        res.notes.append("WIC also does a short health and nutrition check at the clinic.")
        res.reasons.append(f"In WIC's groups: {who}.")

        adjunct = [p for p in ("snap", "tenncare") if p in h.receives]
        if any(p.gets_families_first for p in h.members):
            adjunct.append("Families First")
        if adjunct:
            res.use("wic.adjunctive")
            res.status = "likely"
            res.summary = (f"Likely eligible for WIC: getting {', '.join(adjunct)} automatically meets "
                           f"WIC's income test. In WIC's groups: {who}.")
            return res

        extra = sum(p.babies_expected for p in h.members if p.pregnant)
        n = h.size + extra
        limit = self.r("wic.income_limit").for_size(n)
        res.use("wic.income_limit")
        if extra:
            res.use("wic.unborn")
            res.reasons.append(f"The expected {'baby counts' if extra == 1 else 'babies count'} toward "
                               f"household size, making it {n}.")
        gross = self.gross
        res.reasons.append(f"Income {money(gross)} a month against WIC's limit of {money(limit)} for {n}.")
        if gross <= limit:
            res.status = "likely"
            res.summary = f"Likely eligible for WIC. In WIC's groups: {who}."
            return res
        # A pregnant woman or infant who qualifies for TennCare (Medicaid, not
        # CoverKids) makes the family's WIC applicants income-eligible.
        medicaid = [x for x, p in zip(tenncare.people or [], h.members, strict=False)
                    if x["program"] == "TennCare" and x["status"] in ("likely", "possibly")
                    and (p.pregnant or p.age < 1)]
        if medicaid:
            res.use("wic.adjunctive")
            res.status = "possibly"
            res.summary = (f"Possibly eligible for WIC: income is over WIC's own limit of {money(limit)}, but "
                           f"if {medicaid[0]['name']} is approved for TennCare, that counts as meeting WIC's "
                           f"income test. Apply for TennCare first.")
            return res
        res.status = "unlikely"
        res.summary = f"Unlikely to qualify for WIC: income {money(gross)} is over the limit of {money(limit)}."
        return res


CONTACTS = {"snap": "apply.snap", "tenncare": "apply.tenncare", "wic": "apply.wic"}


def screen(household: Household | dict, as_of: date | None = None) -> dict:
    """Screen one household; the result is plain JSON-ready data."""
    h = household if isinstance(household, Household) else Household.from_dict(household)
    rs = in_force(as_of)
    s = Screen(h, rs)
    tenncare = s.tenncare()
    results = {"snap": s.snap(), "wic": s.wic(tenncare), "tenncare": tenncare}
    next_steps = []
    for prog, res in results.items():
        if res.status in ("likely", "possibly", "refer", "unlikely"):
            c = rs[CONTACTS[prog]]
            next_steps.append({"program": prog, "how": c.title, "url": c.url, "phone": c.phone})
            res.use(CONTACTS[prog])
    help_ = rs["apply.211"]
    next_steps.append({"program": "any", "how": help_.title, "url": None, "phone": help_.phone})
    used = sorted({r for res in results.values() for r in res.rules} | {"apply.211"})
    return {
        "as_of": rs.as_of.isoformat(),
        "programs": {k: {key: v for key, v in asdict(r).items() if key != "program"} for k, r in results.items()},
        "next_steps": next_steps,
        "warnings": rs.warnings,
        "disclaimer": DISCLAIMER,
        "citations": {rid: {"rule": rs.rules[rid].title, "status": rs.rules[rid].status,
                            "sources": rs.rules[rid].citations()} for rid in used},
    }
