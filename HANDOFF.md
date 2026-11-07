# Handoff

Updated: 2026-11-06. This file started as the screener's handoff (sections below up to "Outside the
repo"). Since then the session moved on to the other Claude Corps projects; that work is in
"Since the last handoff" at the end. Nothing is running, and every repo below is committed and
pushed with nothing waiting in a branch, except this HANDOFF.md update: it's committed in
`tn-benefits-screener` but not pushed (run `git push` there).

## What this is

`tn-benefits-screener` is a cited screener for Tennessee SNAP, WIC and TennCare/CoverKids, with
an eval harness. It was built (Oct 22–25, 2026) as a portfolio project for the 2027 Claude Corps
application. Claude handles the conversation (plugin skill + MCP server); plain Python does the
arithmetic, and every number is a rule tied to a quoted, fetched government source.

- Repo: https://github.com/nathanaelhub/tn-benefits-screener (`main`, tag `v0.1.0`)
- Live page: https://nathanaelhub.github.io/tn-benefits-screener/
- Vercel mirror: https://tn-benefits-screener.vercel.app

The last sessions published the web page (the real engine in the browser via Pyodide), tested it,
fixed two page bugs, and started Vercel auto-deploy.

## Finished

- Engine and rules: 50 rules, all verified against their source texts. 96 tests pass. CI is green on Python 3.11–3.14.
- MCP server and Claude Code plugin (`plugin/`, `.claude-plugin/marketplace.json`).
- Evals (`evals/results/2026-10-22-v1`, `-v2`): with the screener, 98% of program calls were right, compared with 81% for plain web search. Results are in the README.
- `RUNBOOK.md` and `docs/staff-guide.md`.
- Web page (`site/`), built by `scripts/build_site.py`. The browser test `scripts/test_site.py` checks that all 40 households give the same results as the Python engine, plus form, phone-width and dark-mode checks. The GitHub Pages deploy only goes out if that test passes.
- Oct 24 fix: an error in the form now clears the previous results.
- `vercel.json` is committed. Vercel builds the site from the repo, and a preview build succeeded.

## Unfinished

- **Vercel auto-deploy is not connected yet.** `vercel git connect` failed because Vercel's GitHub app
  can't access this repo. Until it's connected, the mirror only updates by a manual deploy (see below).
- `RUNBOOK.md` step 6 still describes the manual Vercel deploy. Update it once auto-deploy works.
- Optional: Vercel deploys don't run the browser test that gates the Pages deploy. To gate Vercel the same way, deploy to Vercel from
  `.github/workflows/pages.yml` after the test passes. That needs a `VERCEL_TOKEN` repo secret, which hasn't been set up and needs the owner's OK first.

## Next steps

1. Owner: open https://github.com/settings/installations, then Vercel, then Configure, and add `tn-benefits-screener`.
2. From the repo root, run `vercel link --yes --project tn-benefits-screener`, then `vercel git connect --yes`.
3. Push a small real change and confirm https://tn-benefits-screener.vercel.app updates by itself.
4. Edit `RUNBOOK.md` step 6 to say the Vercel mirror deploys on push.
5. ~~Next portfolio project~~ Done since: council digests (#3) and the workshop kit (#4) are built
   (see below). Only the intake assistant (#1) is left, and it needs a host nonprofit.

## Commands

```bash
uv sync
uv run pytest                          # 96 tests, offline
uv run tn-screener verify              # every rule's quote/table found in its source text
uv run tn-screener screen household.json
uv run tn-screener serve               # MCP server (stdio)
uv run tn-screener sources check       # upstream changes / expired rules (network)

uv run python scripts/build_site.py    # builds _site/
PW_CHROMIUM=<path to chromium headless shell> uv run --with playwright python scripts/test_site.py [URL]

# Manual Vercel mirror deploy (from the repo root, uses vercel.json):
vercel link --yes --project tn-benefits-screener && vercel deploy --prod

# Evals (about 45 min, uses the Claude login; concurrency 2 max on an 8 GB machine)
TN_EVAL_USE_LOGIN=1 uv run python evals/run.py --run <date>
uv run python evals/score.py --run <date>
```

## Outside the repo

- **Tools:** `uv`; `gh` (logged in as nathanaelhub); the Vercel CLI (logged in, team `nathanaelhubs-projects`);
  `claude` CLI (for evals); `pdftotext` from poppler (only for `sources fetch`); a Playwright
  Chromium (`PW_CHROMIUM` points at it, or run `playwright install chromium`).
- **Env vars:**
  - `TN_EVAL_USE_LOGIN=1`: evals use the Claude login and drop `ANTHROPIC_API_KEY`.
  - `PW_CHROMIUM`: path to an already-downloaded Chromium.
  - `ANTHROPIC_API_KEY`: not needed. It's commented out in `~/.zshrc` and should be revoked.
  - No secrets are needed to run, test or deploy.
- **Local, untracked:** `.vercel/` (Vercel project link, gitignored; recreate with `vercel link`), `_site/`,
  `_site_shots/`, `evals/runs/`.
- **Hosting:** GitHub Pages (Actions workflow), Vercel project `tn-benefits-screener`.
- **Commit identity:** nathanaeljdj@gmail.com.

## Since the last handoff (Oct 29 – Nov 4, 2026)

All repos are under `~/opt/program/portfolio-projects/` except the portfolio site
(`~/GitHub/my-portfolio`). From Nov 3 on, changes went through GitHub issues and squash-merged
pull requests (the `github-flow` skill); commit email nathanaeljdj@gmail.com.

### Finished

- **nashville-council-digest** (https://nathanaelhub.github.io/nashville-council-digest/):
  plain-language, fact-checked Metro Council digests, Jan 20 – Oct 20, 2026 (21 meetings, 1,125
  bills and resolutions). Zoning glossary with every quote tested against Metro Planning sources
  (no known gaps); a second Claude reading ("judge") gates publishing; `scripts/update.sh` runs
  fetch → locate → summarize → judge → tests → commit; Atom feeds per district (`district/<n>.xml`,
  `feed.xml`) and a history page for every bill (PR #3).
- **nonprofit-ai-workshop** (https://nathanaelhub.github.io/nonprofit-ai-workshop/): a one-hour
  "Using Claude at a Nonprofit" kit: facilitator guide, slides, four exercises with answer keys,
  privacy sheet quoting Anthropic's Privacy Center (tested against cached copies), quiz, tally,
  feedback form, takeaway, RUNBOOK, host flyer and outreach email (`docs/outreach-email.md`), and a
  full Spanish version under `content/es/` (PR #24). `workshop check` runs the exercises through
  Claude and scores the answers (runs saved in `checks/results/`). `main` is protected (PRs only).
- **public-interest-ai** (https://nathanaelhub.github.io/public-interest-ai/): one-page overview of
  the screener, digest and workshop; every figure is in `facts.json` and a live test checks the
  source README still says it.
- **judge-audit**: second dataset (`datasets/council`, `council-v2`) auditing the digest's judge;
  findings in the README "Second dataset" section (PR #2): Sonnet 96%, Haiku 94%, the digest's 4
  batch false alarms never recurred one at a time, errors locked to items.
- **my-portfolio** (https://www.nathanaeljohnson.net/work): nine Oct–Nov projects added with
  covers and a Civic filter (PR #17).

### In progress or waiting on a decision

- **Digest issue #4 (owner's call):** the judge's rule ("leaving details out is fine") lets
  meaning-changing omissions through; BL2026-1565 on the live site omits two exemptions. Options:
  adopt the stricter rule and re-judge everything (about $7.50), or hide BL2026-1565 by hand.
- **Council meeting of Nov 5, 2026** (moved from Election Day) isn't in the digest yet.
- **Workshop:** not yet run with real people; the Spanish hasn't been reviewed by a native speaker.
- **Screener Vercel auto-deploy:** connected Nov 6, 2026; RUNBOOK step 6 updated.
- Pre-existing, not fixed: one "Unexpected token '.'" console error on nathanaeljohnson.net/work;
  some project pages there use light cover colors as text accents (low contrast).

### Next steps

1. Decide digest issue #4. Then, after Legistar posts the Nov 5 actions, in `nashville-council-digest`:
   `git switch -c data/nov-5-meeting && scripts/update.sh`, then open a PR and merge.
2. Send the workshop outreach email to one or two groups; have a fluent speaker read `content/es/`.
3. Optional: protect `main` on `public-interest-ai` (asked, not done).
4. Remaining feature ideas from the list (not started): screener TANF/LIHEAP + "what to bring";
   10k-diff cross-company search; diffusion browser demo; rust-backtester portfolio backtests;
   open-finance-mcp quarterly trends; overview-page video.

### Commands

```bash
# nashville-council-digest
uv run pytest
scripts/update.sh [--since YYYY-MM-DD] [--push]   # after a meeting; uses the Claude login
uv run council-digest build                       # -> _site/

# nonprofit-ai-workshop
uv run pytest
uv run workshop build                             # -> _site/
uv run workshop refresh-sources && uv run pytest  # re-check cached sources
WORKSHOP_USE_LOGIN=1 uv run workshop check        # exercises through Claude (~$0.20)

# public-interest-ai
uv run pytest                                     # includes live checks against GitHub

# judge-audit
uv run --with-editable ../nashville-council-digest python scripts/council_dataset.py ../nashville-council-digest [v2]
JUDGE_AUDIT_USE_LOGIN=1 uv run judge-audit run datasets/council --judges sonnet --samples 5 --log runs/x.jsonl
uv run judge-audit report datasets/council runs/x.jsonl

# my-portfolio (~/GitHub/my-portfolio): static export
npm ci && npm run build                           # -> out/; preview: cd out && python3 -m http.server
```

### Outside the repos

- **Env vars (names only):** `COUNCIL_DIGEST_USE_LOGIN`, `WORKSHOP_USE_LOGIN`, `JUDGE_AUDIT_USE_LOGIN`
  (each `=1` makes the `claude` CLI use the Claude login and drop `ANTHROPIC_API_KEY`); `PW_CHROMIUM`.
- **Tools:** `claude` CLI logged in; `gh` as nathanaelhub; Playwright Chromium in
  `~/Library/Caches/ms-playwright/`; Node 24 for my-portfolio.
- **Hosting:** GitHub Pages for every project here; nathanaeljohnson.net is my-portfolio's Pages
  custom domain (CNAME), deployed by its "Simple Deploy to GitHub Pages" workflow on push to `main`.
- **Data sources:** Legistar web API (council body 138), Metro ArcGIS Parcels_view, Metro Planning
  staff reports, Anthropic Privacy Center (English and Spanish), USDA FNS. No keys needed.
