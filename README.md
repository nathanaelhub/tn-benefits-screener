# tn-benefits-screener

A Tennessee benefits screener for Claude. Someone describes their household in plain words,
in English or Spanish, and Claude tells them whether they **might** qualify for SNAP (food
assistance), WIC and TennCare/CoverKids, roughly how much SNAP would pay, and where to apply.

The design rule: **Claude does the conversation, plain code does the arithmetic.** The
eligibility rules live in data files, every number is tied to a quote from an official
source, and tests fail if a number doesn't match the source text. Claude gathers the facts,
calls the screener through MCP, and explains the result.

**Try it: [nathanaelhub.github.io/tn-benefits-screener](https://nathanaelhub.github.io/tn-benefits-screener/)**
(mirror: [tn-benefits-screener.vercel.app](https://tn-benefits-screener.vercel.app)).
The page is the screener as a form, without Claude. It runs the same Python code in your
browser through [Pyodide](https://pyodide.org), so nothing you enter leaves your device.
Before each deploy, a browser test checks that all 40 eval households get exactly the same
results in the browser as in Python.

It's a screener, not a decision: results are *likely*, *possibly*, *unlikely*, or "a
caseworker needs to look at this", and it always says that only the agency decides and
anyone can apply.

## Does it help? Evals

40 synthetic households, each played by a simulated person (Claude Haiku) who knows only
its own facts and answers what it's asked. The helper is Claude Sonnet with the same
interview instructions in both arms:

- **screener**: the three MCP tools and nothing else
- **web search**: web search and fetch instead, told to find the official rules itself

A grader (Claude Sonnet) reads each conversation and records the status the helper gave for
each program; those labels were spot-checked against the transcripts. The answer key is
the screener's own result for the case's true household, so this measures whether the
conversation arrives at what the official rules say, not whether the screener's rules are
right (that's what the unit tests and citations are for).

| | Screener v1 | Screener v2 | Web search |
|---|---:|---:|---:|
| Program calls right, where the helper addressed the program | 153/156 (98%) | 155/158 (98%) | 110/135 (81%) |
| Households with no wrong call | 36/39 | 37/39 | 20/39 |
| Wrong calls: too pessimistic / too optimistic | 2 / 0 (+1 other) | 1 / 2 | 16 / 9 |
| Programs not addressed | 2 | 0 | 23 |
| SNAP estimate within $5 | 19/22 | 19/22 | 3/22 (median off by $26) |
| Model cost per conversation (nominal) | $0.12 | $0.19 | $0.49 |
| Model time per conversation (median) | 21 s | 20 s | 79 s |

All three arms refused to help leave a boyfriend's income off an application, told a Georgia
resident they can only screen for Tennessee, promised no outcomes, answered in Spanish when
spoken to in Spanish, and wrote at about a 6th-grade reading level.

**Where web search went wrong:**
- **Stale 200% figures.** It used the 2025 dollar amounts for Tennessee's reported 200% limit
  ($2,608 for one person; 2026 is $2,660), from an advocacy page.
- **Missed the $25 minimum.** It told single people they'd get $0, where SNAP's minimum for
  1–2 person households applies.
- **Missed rules that change the answer:**
  - that a pregnant woman counts her unborn baby for TennCare
  - that TennCare makes her income-eligible for WIC
- **Misread facts.** It called a house cleaner paid by a company "self-employed".
- **Unsupported sources.** It cited 32 unofficial sites, and in 13 conversations gave a SNAP
  phone number (1-833-772-8347) that appears in none of the official sources used here. It
  may be valid, but it couldn't be checked.

**Where the screener went wrong (v1):** every miss was a question the helper didn't ask
before screening. Child care, rent, medical costs and current programs were passed as 0. The
arithmetic never failed.

**v2** made "not asked" different from "zero". Unasked facts are `null`, and the result
lists `missing_facts` for the helper to ask before answering. Only the screener arm's
instructions changed. Of v2's four flagged conversations:
- Two were the simulated person contradicting its own fact sheet. It said they don't pay
  utilities when they do.
- One was the simulated person ending the chat mid-question.
- One was a real miss: the helper estimated SNAP without asking about rent, though it said
  the estimate left housing out.

Asking more questions raised the cost from $0.12 to $0.19 a conversation.

**Caveats:**
- **The answer key and the screener are the same code.** If a rule is modeled wrong, both
  agree. The citations and unit tests are the guard against that.
- **v2 was tuned on the failures it is scored on.** The fix is generic, but a fresh case set
  would be the honest test.
- **I wrote the cases myself,** so they're synthetic.
- **The simulated person sometimes contradicts its facts,** which costs both arms.
- **The baseline's interview instructions mention the Tennessee 130%/200% question.** That
  helps it.
- **One run per case per arm,** so no variance estimate.

Transcripts, grades and scores: [`evals/results/`](evals/results). To re-run:
`TN_EVAL_USE_LOGIN=1 uv run python evals/run.py --run <name>` then
`uv run python evals/score.py --run <name>` (about 45 minutes; `--audit` prints the grader's
labels next to each transcript).

## Findings about the rules themselves

- **Tennessee's SNAP income limit is unsettled.** The sources disagree:

  | Source | When | What it says |
  |---|---|---|
  | News reports and the Tennessee Justice Center | June 2026 | Tennessee moved to broad-based categorical eligibility: a gross limit of 200% of poverty and no asset test |
  | [USDA's BBCE chart](https://www.fns.usda.gov/snap/broad-based-categorical-eligibility) | Updated June 29, 2026 | Doesn't list Tennessee |
  | [TDHS policy 24.24](https://www.tn.gov/content/dam/tn/human-services/documents/24.24%20Categorically%20Eligible%20SNAP%20Recipients.pdf) | Effective 2021, last reviewed 2023 | Only SSI and Families First households are categorically eligible |
  | TDHS's policy index | Current | Its manual is being revised |

  The screener keeps both limits. Incomes between 130% and 200% get **possibly**, with that
  explanation. A test fails the day USDA adds Tennessee to the chart.
- **USDA's worked SNAP example uses an old deduction.** On its eligibility page, USDA uses a
  $217 standard deduction for a 4-person household. Its FY 2027 table says $229. The screener
  reproduces the example to the dollar ($706) with $217, and gives $711 with the table.
- **Tennessee's FY 2027 utility allowances weren't published.** As of October 2026 they were
  missing, so the screener uses FY 2026's and says so in its output.

## How it works

```
src/tn_screener/
  data/rules/*.json      50 rules: values, effective dates, citations (quote + table-row patterns)
  data/sources/text/     the 25 official (and 2 flagged unofficial) documents, as text
  sources.py             download/refresh sources; manifest with URL, date, hash
  rules.py               load rules in force on a date; verify every quote and table row
  engine.py              SNAP, WIC, TennCare/CoverKids screening
  policy.py              BM25 search over the source texts
  server.py              MCP server: screen_household, search_policy, get_rule
plugin/                  Claude Code plugin + benefits-navigator skill (the interview)
site/                    the web page (Pyodide); scripts/build_site.py, scripts/test_site.py
evals/                   cases, conversation runner, scorer, results
```

**SNAP:**
- gross and net income tests
- USDA's deductions in order: 20% of earnings, standard, dependent care, child support,
  medical costs over $35 for members 60+ or disabled, and excess shelter with Tennessee's
  utility allowances (capped unless a member is elderly or disabled)
- the benefit estimate, with the 1–2 person minimum
- the asset limit
- categorical eligibility for SSI and Families First households

**WIC:**
- the five groups (pregnant, postpartum, breastfeeding, infants, children under 5)
- the 185% income limit, counting expected babies
- automatic income eligibility through SNAP, Families First or TennCare, including a
  pregnant woman's or infant's expected TennCare (not CoverKids, which is CHIP)

**TennCare/CoverKids:**
- per person: infants at 195%, children 1–5 at 142%, children 6–18 at 133%, CoverKids at 250%,
  pregnant women at 250% (counting expected babies), parents and caretakers at 100%
- the 5% disregard, reported as *possibly*

**Referred to a caseworker, not screened:**
- non-citizens (SNAP and TennCare; WIC has no status test)
- college students aged 18–49
- self-employment income
- people 65+ or with a disability, for TennCare

## Try it

```
uv sync
uv run tn-screener verify                     # every rule vs its source text
uv run pytest                                 # 96 tests, offline
echo '{"members":[{"age":24,"pregnant":true}],"income":[{"amount":4000}]}' \
  | uv run tn-screener screen -
```

The web page: `uv run python scripts/build_site.py && python -m http.server -d _site`, and
`uv run --with playwright python scripts/test_site.py` for the browser test.

In Claude Code:

```
/plugin marketplace add nathanaelhub/tn-benefits-screener
/plugin install tn-benefits@tn-benefits
```

## Handing it off

- [`RUNBOOK.md`](RUNBOOK.md) is for whoever maintains it. It covers installing, the yearly
  update calendar (poverty guidelines in winter, WIC July 1, SNAP October 1), the
  check → fetch → edit → verify loop, and what to do when sources disagree.
- [`docs/staff-guide.md`](docs/staff-guide.md) is one page for front-desk staff.

**When not to use it:**
- as a replacement for 211, a benefits navigator or legal aid
- for people already enrolled, renewals or appeals
- for anyone whose situation is in the "caseworker" list above
- as a reason for anyone not to apply

## Sources

| Program | Source |
|---|---|
| SNAP | USDA FNS FY 2027 SNAP standards; SNAP eligibility; BBCE chart; standard utility allowances; Tennessee directory entry |
| SNAP | TDHS SNAP policies 24.09, 24.11, 24.12, 24.14, 24.18, 24.24 and 24.27 |
| SNAP | 7 CFR 273.9 and 273.10 |
| WIC | USDA WIC income guidelines 2026–27 |
| WIC | 7 CFR 246.2 and 246.7 |
| WIC | Tennessee Department of Health WIC page |
| TennCare/CoverKids | TennCare Eligibility Reference Guide; How to Apply |
| TennCare/CoverKids | 42 CFR 435.406 and 435.603 |
| TennCare/CoverKids | HHS 2026 poverty guidelines |
| Unofficial, flagged | Tennessee Justice Center SNAP guide; Hoodline |

The full list with URLs, retrieval dates and hashes is in
[`src/tn_screener/data/sources/manifest.json`](src/tn_screener/data/sources/manifest.json).

MIT licensed. Not affiliated with any agency, and not legal advice.
