# Runbook

For the person who owns this screener at an organization: how to install it, keep its
numbers current, and know when something is wrong. No programming is needed for the yearly
update beyond editing numbers in a text file and running three commands.

## What it is, in one paragraph

Staff or clients describe a household to Claude. Claude asks a few questions, then calls the
screener, which applies the official income limits for SNAP (food assistance), WIC and
TennCare/CoverKids, and says whether the household is *likely*, *possibly* or *unlikely* to
qualify, or needs a caseworker. Every number comes from a government document saved in this
repository, and the screener refuses to run on rules that have expired. It never decides
anything: it points people to the real applications and to 211.

## Install

**Claude Code** (one command, then restart):

```
/plugin marketplace add nathanaelhub/tn-benefits-screener
/plugin install tn-benefits@tn-benefits
```

**Claude Desktop**: Settings → Developer → Edit Config, and add to `mcpServers`:

```json
"tn-benefits": {
  "command": "uvx",
  "args": ["--from", "git+https://github.com/nathanaelhub/tn-benefits-screener@v0.1.0", "tn-screener", "serve"]
}
```

`uvx` comes with [uv](https://docs.astral.sh/uv/getting-started/installation/). For Desktop,
also paste the contents of `plugin/skills/benefits-navigator/SKILL.md` into a Project's
instructions, so Claude interviews the way the screener expects.

## The calendar

| When | What changes | Rules file |
|---|---|---|
| Late January / February | HHS poverty guidelines; TennCare's chart follows | `tenncare.json` (`tenncare.fpl_*`) |
| July 1 | WIC income limits | `wic.json` (`wic.income_limit`) |
| October 1 | SNAP limits, deductions, maximum benefits | `snap.json` |
| Whenever USDA posts them | Tennessee's utility allowances (SUAs) | `snap.json` (`snap.sua_*`) |
| Any time | Tennessee's SNAP 200% question (below) | `snap.json` |

The screener **stops working** on the day a rule expires (for example, SNAP rules end
September 30, 2027) rather than quietly using old numbers. That's deliberate. The only
exception is the utility allowance, which is marked `carry_forward` because USDA often
publishes it late; the screener uses the latest one and says so in its output.

## The yearly update

All commands run from a copy of this repository (`git clone`, then `uv sync`).

1. **See what changed:** `uv run tn-screener sources check`
   Lists every official source whose text changed upstream and every rule past its end date.
2. **Download the new text:** `uv run tn-screener sources fetch`
   This saves the new documents under `src/tn_screener/data/sources/text/` and then checks
   every rule against them. Rules whose numbers no longer appear in the source are listed:
   that's your to-do list. (PDF sources need `pdftotext`: `brew install poppler`.)
3. **Edit the numbers** in `src/tn_screener/data/rules/*.json`. For each listed rule, open the
   source text, find the new table, and update `table`/`value`, `effective_from`,
   `effective_to`, and the `quote` if the heading changed (e.g. "FY 2027" → "FY 2028").
4. **Check:** `uv run tn-screener verify` must say *all rules check out*, and
   `uv run pytest` must pass. Some tests use exact dollar results for this year's tables;
   when a table changes, recompute those by hand from the comments above each test and
   update them. That hand check is the point: it's how you know the arithmetic still
   matches the rules.
5. **Re-run the evals** (optional but recommended after a big change; about 45 minutes and
   included in a Claude plan): `TN_EVAL_USE_LOGIN=1 uv run python evals/run.py --run <date>`
   then `uv run python evals/score.py --run <date>`. Compare with the last results in
   `evals/results/`.
6. **Web page:** pushing to `main` rebuilds the GitHub Pages site, after a browser test
   checks it against the Python engine. The Vercel mirror is deployed by hand:
   `uv run python scripts/build_site.py && cd _site && vercel link --yes --project tn-benefits-screener && vercel deploy --prod`.
   The build recreates `_site/`, which drops its Vercel link; without `vercel link` the
   deploy creates a new, separate project instead of updating the mirror.
7. **Release:** commit, tag (`git tag v0.1.1`), push, and bump the version in
   `plugin/.claude-plugin/plugin.json` and the Desktop config above.

## When sources disagree

Tennessee's SNAP gross income limit is the live example. Federal rules say 130% of poverty;
news reports and advocates said in mid-2026 that Tennessee moved to 200% (broad-based
categorical eligibility), but USDA's own chart of states doing that doesn't list Tennessee,
and TDHS's policy manual still describes only the narrow version. The screener keeps both:
households between the two limits get **possibly**, with that explanation.

To resolve it, ask TDHS SNAP Policy (SnapPolicy.DHS@tn.gov, listed on the TDHS policy
page) or check USDA's [BBCE chart](https://www.fns.usda.gov/snap/broad-based-categorical-eligibility).
If it's confirmed:

- add the confirming document to `SOURCES` in `src/tn_screener/sources.py` and fetch it
- in `snap.json`, change `snap.gross_limit_200_reported` to `"status": "official"`, cite the
  new source, and remove the `contradicted_by` entries that no longer hold
- in the engine, the 130% rule then no longer applies to most households; that's a code
  change (`Screen.snap` in `engine.py`), and the 130–200% tests need updating.

`tests/test_rules.py::test_tennessee_is_missing_from_the_bbce_chart` fails on its own
the day USDA adds Tennessee to its chart, which is your signal.

## When something looks wrong

- **A client says the screener was wrong:** run the same facts through
  `uv run tn-screener screen household.json` (see `tests/test_engine.py` for the format) and
  read the `reasons`. If the arithmetic follows the rules, the difference is usually a fact
  (household members, income frequency, utilities) or a rule the screener doesn't model.
  If the arithmetic is wrong, add a failing test first, then fix `engine.py`.
- **Claude asks odd questions or skips one:** that's the skill (`SKILL.md`), not the
  screener. Edit it and re-run the evals for the affected cases with `--cases`.
- **The tool errors with "expired":** do the yearly update above.

## What it doesn't do

It doesn't handle non-citizens' SNAP or TennCare eligibility, college student exemptions,
self-employment income, disability-based Medicaid, or anyone already receiving benefits.
For those it says "a caseworker needs to look at this". It doesn't store anything, and it
should never be the reason someone doesn't apply.

## Contacts

- SNAP applications: [OneDHS](https://onedhs.tn.gov/csp?id=start_snap_application), 866-311-4287
- TennCare/CoverKids: [TennCare Connect](https://tenncareconnect.tn.gov/), 855-259-0701
- WIC: 1-800-DIAL-WIC (1-800-342-5942), [tn.gov/health/wic](https://www.tn.gov/health/wic.html)
- Free local help: dial 211
- TDHS SNAP policy questions: SnapPolicy.DHS@tn.gov
