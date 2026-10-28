"""End-to-end test of the web page in headless Chromium.

1. Parity: every eval household screened in the browser (Pyodide) gives the
   same JSON as the Python engine.
2. The form: an example fills in and produces results; a hand-entered
   household works; a missing age shows an error; links are https.
3. Screenshots at desktop and phone width into _site_shots/.

    uv run --with playwright python scripts/test_site.py [URL]

Without a URL it builds and serves _site/ locally.
"""

from __future__ import annotations

import functools
import http.server
import os
import json
import subprocess
import sys
import threading
from datetime import date
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tn_screener.engine import screen  # noqa: E402

SHOTS = ROOT / "_site_shots"


def serve() -> str:
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_site.py")], check=True)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT / "_site"))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{httpd.server_address[1]}/"


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else serve()
    cases = json.loads((ROOT / "evals" / "cases.json").read_text(encoding="utf-8"))
    SHOTS.mkdir(exist_ok=True)
    failures = []
    with sync_playwright() as p:
        # PW_CHROMIUM: use an already-downloaded browser instead of `playwright install`.
        browser = p.chromium.launch(executable_path=os.environ.get("PW_CHROMIUM") or None)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(url)
        expect(page.locator("#go")).to_have_text("Check eligibility", timeout=120_000)

        # 1. Parity with the Python engine (same date on both sides).
        today = page.evaluate("new Date().toISOString().slice(0, 10)")
        for c in cases:
            got = page.evaluate("h => window.tnScreen(h)", c["household"])
            want = json.loads(json.dumps(screen(c["household"], date.fromisoformat(today))))
            if got != want:
                failures.append(f"parity: {c['id']}")
        print(f"parity: {len(cases) - sum(f.startswith('parity') for f in failures)}/{len(cases)} households match")

        # 2a. An example button fills the form and shows results.
        page.get_by_role("button", name="Pregnant, $4,000/month").click()
        cards = page.locator("article.program")
        expect(cards).to_have_count(3)
        wic = cards.filter(has_text="WIC").first
        expect(wic.locator(".badge").first).to_have_text("Possibly")
        expect(page.locator(".steps")).to_contain_text("855-259-0701")
        page.screenshot(path=str(SHOTS / "desktop-example.png"), full_page=True)

        # 2b. A hand-entered household: one adult, $1,100/month wages, nothing else.
        page.reload()
        expect(page.locator("#go")).to_have_text("Check eligibility", timeout=120_000)
        page.get_by_label("Person 1 age").fill("50")
        page.locator("#incomes .amount").fill("1100")
        page.get_by_role("button", name="Check eligibility").click()
        snap = cards.filter(has_text="Food assistance").first
        expect(snap.locator(".badge").first).to_have_text("Likely")
        expect(snap.locator(".estimate")).to_contain_text("$107")
        expect(page.locator(".ask")).to_contain_text("rent or mortgage")  # costs left blank -> asked
        page.locator("#rent").fill("650")
        page.locator("#utilities").select_option("heating_cooling")
        page.get_by_role("button", name="Check eligibility").click()
        expect(snap.locator(".estimate")).to_contain_text("$306")

        # The "babies expected" field only shows for someone pregnant.
        first = page.locator("#members .member").first
        expect(first.locator(".babies-wrap")).to_be_hidden()
        first.locator(".pregnant").check()
        expect(first.locator(".babies-wrap")).to_be_visible()
        first.locator(".pregnant").uncheck()

        # 2c. A missing age is a readable error, not a crash.
        page.get_by_role("button", name="+ Add a person").click()
        page.get_by_role("button", name="Check eligibility").click()
        expect(page.locator("#form-error")).to_contain_text("Enter an age")
        expect(cards).to_have_count(0)  # the earlier results are cleared, not left stale

        hrefs = page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
        if any(not h.startswith("https://") for h in hrefs):
            failures.append(f"non-https links: {[h for h in hrefs if not h.startswith('https://')]}")

        # An example picked before the screener has loaded runs once it's ready.
        # Hold the screener package back until after the click.
        early = browser.new_page(viewport={"width": 1280, "height": 900})
        held = []
        early.route("**/screener.zip", lambda r: held.append(r))
        early.goto(url)
        early.get_by_role("button", name="Retired, 70, Social Security").click()
        expect(early.locator("#go")).to_be_disabled()
        for _ in range(600):  # the zip is requested only after Pyodide itself loads
            if held:
                break
            early.wait_for_timeout(100)
        if not held:
            failures.append("early example: screener.zip was never requested")
        for r in held:
            r.continue_()
        expect(early.locator("article.program")).to_have_count(3, timeout=120_000)
        early.close()

        # Without examples.json the form still works and the empty examples row is hidden.
        bare = browser.new_page(viewport={"width": 1280, "height": 900})
        bare.on("pageerror", lambda e: errors.append(f"no-examples page: {e}"))
        bare.route("**/examples.json", lambda r: r.fulfill(status=404, body="not found"))
        bare.goto(url)
        expect(bare.locator(".examples")).to_be_hidden()
        expect(bare.locator("#go")).to_have_text("Check eligibility", timeout=120_000)
        bare.close()

        # 3. Phone width: no horizontal scroll.
        phone = browser.new_page(viewport={"width": 375, "height": 800})
        phone.goto(url)
        expect(phone.locator("#go")).to_have_text("Check eligibility", timeout=120_000)
        phone.get_by_role("button", name="Single mom, toddler, $450/week").click()
        expect(phone.locator("article.program")).to_have_count(3)
        if phone.evaluate("document.documentElement.scrollWidth > window.innerWidth"):
            failures.append("horizontal scroll at 375px")
        phone.screenshot(path=str(SHOTS / "phone-example.png"), full_page=True)
        dark = browser.new_page(viewport={"width": 1280, "height": 900}, color_scheme="dark")
        dark.goto(url)
        expect(dark.locator("#go")).to_have_text("Check eligibility", timeout=120_000)
        dark.get_by_role("button", name="Retired, 70, Social Security").click()
        expect(dark.locator("article.program")).to_have_count(3)
        dark.screenshot(path=str(SHOTS / "desktop-dark.png"), full_page=True)
        if errors:
            failures.append(f"page errors: {errors}")
        browser.close()
    print("\n".join(failures) if failures else "all site checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
