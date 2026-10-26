# Handoff

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
5. Next portfolio project (from the pitch list): Nashville Metro Council meeting digests (#3), unless a
   host nonprofit is found for the intake assistant (#1). The workshop kit (#4) pairs with #1.

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
