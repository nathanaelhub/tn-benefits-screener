"""Build the static web page into _site/.

The page runs the real screener in the browser with Pyodide, so there is no
second implementation to drift out of step: this script zips the package's
Python modules and rules (not the 0.5 MB of source texts, which only
``verify`` and policy search need) next to the page's HTML, CSS and JS.

    uv run python scripts/build_site.py && python -m http.server -d _site
"""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "src" / "tn_screener"
OUT = ROOT / "_site"


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    shutil.copytree(ROOT / "site", OUT)
    with zipfile.ZipFile(OUT / "screener.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(PKG.glob("*.py")):
            z.write(f, f"tn_screener/{f.name}")
        for f in sorted((PKG / "data" / "rules").glob("*.json")):
            z.write(f, f"tn_screener/data/rules/{f.name}")
        z.write(PKG / "data" / "sources" / "manifest.json", "tn_screener/data/sources/manifest.json")
    # Example households for the page's "try an example" buttons, from the eval cases.
    cases = {c["id"]: c for c in json.loads((ROOT / "evals" / "cases.json").read_text(encoding="utf-8"))}
    picks = {"Single mom, toddler, $450/week": "clear-single-mom-toddler",
             "Pregnant, $4,000/month": "wic-pregnant-via-tenncare",
             "Retired, 70, Social Security": "net-elderly-medical",
             "Family of 4 (USDA's example)": "clear-usda-family",
             "Single, $1,770/month": "threshold-just-over-130"}
    examples = [{"name": name, "household": cases[cid]["household"]} for name, cid in picks.items()]
    (OUT / "examples.json").write_text(json.dumps(examples, indent=1), encoding="utf-8")
    print(f"built {OUT} ({(OUT / 'screener.zip').stat().st_size // 1024} KB package)")


if __name__ == "__main__":
    main()
