"""Eligibility rules as data, each tied to the official wording it comes from.

Every rule in ``data/rules/*.json`` has an id, effective dates and one or more
citations. A citation names a source (see ``sources.py``) and a quote that must
appear in that source's text. Table rules also give a ``rows`` pattern: for
every household size, the pattern filled in with that size and value must
match the source near the quote, so a mistyped number fails ``verify``.

A rule marked ``"status": "reported"`` is one that no official source
confirms; ``contradicted_by`` lists the official evidence against it, and
``absent`` asserts that a word does *not* appear in a source (Tennessee is
missing from USDA's chart of states with broad-based categorical
eligibility).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from functools import cache
from pathlib import Path

from . import sources

RULES_DIR = sources.DATA / "rules"
ROW_WINDOW = 4000  # how far past a quote a table's rows may sit


@dataclass(frozen=True)
class Citation:
    source: str
    quote: str
    rows: str | None = None
    extra: str | None = None
    absent: str | None = None

    def as_dict(self) -> dict:
        s = sources.BY_ID[self.source]
        return {"source": s.title, "publisher": s.publisher, "url": s.link,
                "official": s.official, "quote": self.quote}


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    cite: tuple[Citation, ...]
    effective_from: date
    effective_to: date | None = None
    value: float | None = None
    table: dict[str, float] | None = None
    each_additional: float | None = None
    status: str = "official"
    kind: str = "rule"
    carry_forward: bool = False
    note: str | None = None
    url: str | None = None
    phone: str | None = None
    contradicted_by: tuple[Citation, ...] = field(default_factory=tuple)

    def for_size(self, n: int) -> float:
        """A per-household-size table value; sizes past the table add ``each_additional``."""
        assert self.table is not None, self.id
        sizes = sorted(int(k) for k in self.table if k.isdigit())
        if n <= sizes[-1]:
            return self.table[str(max(1, n))]
        return self.table[str(sizes[-1])] + (n - sizes[-1]) * (self.each_additional or 0)

    def citations(self) -> list[dict]:
        return [c.as_dict() for c in self.cite]


def _citation(d: dict) -> Citation:
    return Citation(d["source"], d["quote"], d.get("rows"), d.get("extra"), d.get("absent"))


def _rule(d: dict) -> Rule:
    return Rule(
        id=d["id"], title=d["title"],
        cite=tuple(_citation(c) for c in d["cite"]),
        effective_from=date.fromisoformat(d["effective_from"]),
        effective_to=date.fromisoformat(d["effective_to"]) if d.get("effective_to") else None,
        value=d.get("value"), table=d.get("table"), each_additional=d.get("each_additional"),
        status=d.get("status", "official"), kind=d.get("kind", "rule"),
        carry_forward=d.get("carry_forward", False), note=d.get("note"),
        url=d.get("url"), phone=d.get("phone"),
        contradicted_by=tuple(_citation(c) for c in d.get("contradicted_by", [])),
    )


@cache
def load(rules_dir: Path = RULES_DIR) -> dict[str, Rule]:
    rules: dict[str, Rule] = {}
    for path in sorted(rules_dir.glob("*.json")):
        for d in json.loads(path.read_text(encoding="utf-8"))["rules"]:
            if d["id"] in rules:
                raise ValueError(f"duplicate rule id {d['id']}")
            rules[d["id"]] = _rule(d)
    return rules


class StaleRules(Exception):
    """A rule needed for a screening has expired and has no replacement."""


@dataclass
class RuleSet:
    """The rules in force on one date, with warnings about stale ones."""

    as_of: date
    rules: dict[str, Rule]
    warnings: list[str] = field(default_factory=list)

    def __getitem__(self, rule_id: str) -> Rule:
        r = self.rules[rule_id]
        if r.effective_from > self.as_of:
            raise StaleRules(f"{rule_id} takes effect {r.effective_from}, after {self.as_of}")
        if r.effective_to and r.effective_to < self.as_of:
            if not r.carry_forward:
                raise StaleRules(f"{rule_id} expired {r.effective_to}; update the rules (see RUNBOOK.md)")
            msg = (f"{r.title}: using the most recent published figures (in effect until "
                   f"{r.effective_to}); newer ones weren't available.")
            if msg not in self.warnings:
                self.warnings.append(msg)
        return r


def in_force(as_of: date | None = None) -> RuleSet:
    return RuleSet(as_of or date.today(), load())


def _fmt(v: float) -> str:
    return f"{v:,.2f}" if v != int(v) else f"{int(v):,}"


def check_citation(c: Citation, rule: Rule | None = None) -> list[str]:
    """Problems with one citation (empty when the quote and every row are found)."""
    if c.source not in sources.BY_ID:
        return [f"unknown source {c.source}"]
    if not sources.text_path(c.source).exists():
        return [f"no text for {c.source}; run tn-screener sources fetch"]
    text = sources.normalize(sources.source_text(c.source))
    quote = sources.normalize(c.quote)
    at = text.find(quote)
    if at < 0:
        return [f"quote not found in {c.source}: {c.quote[:80]!r}"]
    problems = []
    # Dollar signs come and go between table rows; compare without them.
    window = text[at:at + ROW_WINDOW].replace("$", "")
    if c.rows and rule and rule.table:
        for n, v in rule.table.items():
            pattern = c.rows.replace("{n}", re.escape(n)).replace("{v}", re.escape(_fmt(v)))
            if not re.search(pattern, window):
                problems.append(f"{c.source}: no row for {n} = {_fmt(v)}")
    if c.extra and not re.search(c.extra, window):
        problems.append(f"{c.source}: {c.extra!r} not found after the quote")
    if c.absent and c.absent in text:
        problems.append(f"{c.source}: expected {c.absent!r} to be absent")
    return problems


def verify(rules: dict[str, Rule] | None = None) -> dict[str, list[str]]:
    """Every rule's problems, keyed by rule id; an empty dict means all citations check out."""
    out = {}
    for r in (rules or load()).values():
        problems = [p for c in r.cite for p in check_citation(c, r)]
        problems += [p for c in r.contradicted_by for p in check_citation(c)]
        if problems:
            out[r.id] = problems
    return out
