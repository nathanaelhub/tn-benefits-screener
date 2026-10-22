"""The official documents every rule cites, and how to refresh them.

Each source is downloaded, reduced to plain text and saved under
``data/sources/text/<id>.txt``; ``data/sources/manifest.json`` records where it came
from, when, and a hash of what was downloaded. The text files are committed
so that tests can check every rule's quoted wording offline, and so that a
re-fetch shows exactly what changed upstream.

``check`` re-downloads everything and reports sources whose text changed and
rules whose effective dates have run out. It is the yearly maintenance step:
WIC limits change every July 1, SNAP every October 1, and the poverty
guidelines (used by TennCare) each January or February.
"""

from __future__ import annotations

import hashlib
import html
import io
import json
import re
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
SOURCES_DIR = DATA / "sources"
TEXT_DIR = SOURCES_DIR / "text"
MANIFEST = SOURCES_DIR / "manifest.json"

# tn.gov and usda.gov turn away clients that don't look like a browser.
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 Safari/605.1.15"
ECFR = "https://www.ecfr.gov/api/versioner/v1/full/{date}/title-{title}.xml?part={part}&section={section}"
ECFR_PAGE = "https://www.ecfr.gov/current/title-{title}/section-{section}"
TDHS = "https://www.tn.gov/content/dam/tn/human-services/documents/"


@dataclass(frozen=True)
class Source:
    id: str
    title: str
    publisher: str
    url: str
    kind: str  # html, pdf, xlsx or ecfr
    official: bool = True
    # The page a person should open; differs from ``url`` for eCFR, whose
    # API serves the XML but whose readable page lives elsewhere.
    cite_url: str | None = None

    @property
    def link(self) -> str:
        return self.cite_url or self.url


def _ecfr(id: str, title: int, part: int, section: str, name: str) -> Source:
    return Source(id, f"{title} CFR {section} {name}", "Electronic Code of Federal Regulations",
                  ECFR.format(date="{ecfr_date}", title=title, part=part, section=section), "ecfr",
                  cite_url=ECFR_PAGE.format(title=title, section=section))


SOURCES = [
    Source("fns_snap_standards_fy27", "SNAP Cost-of-Living Adjustments: FY 2027 standards, allotments and deductions",
           "USDA Food and Nutrition Service", "https://www.fns.usda.gov/snap/allotment/cola", "html"),
    Source("fns_snap_eligibility", "SNAP Eligibility", "USDA Food and Nutrition Service",
           "https://www.fns.usda.gov/snap/recipient/eligibility", "html"),
    Source("fns_bbce_chart", "Broad-Based Categorical Eligibility (BBCE) state chart",
           "USDA Food and Nutrition Service", "https://www.fns.usda.gov/snap/broad-based-categorical-eligibility",
           "html"),
    Source("fns_sua_table", "SNAP Standard Utility Allowances by State (FY 2026 table)",
           "USDA Food and Nutrition Service",
           "https://www.fns.usda.gov/sites/default/files/resource-files/2026-05-21-SUA-Table-FY26.xlsx", "xlsx"),
    Source("tdhs_policy_index", "TDHS Publications and Manuals (SNAP policy index)",
           "Tennessee Department of Human Services",
           "https://www.tn.gov/humanservices/information-and-resources/dhs-publications.html", "html"),
    Source("tdhs_24_09", "SNAP Policy 24.09: Citizenship Requirement", "Tennessee Department of Human Services",
           TDHS + "24.09%20SNAP%20Citizenship%20Requirement.pdf", "pdf"),
    Source("tdhs_24_11", "SNAP Policy 24.11: Work Requirements", "Tennessee Department of Human Services",
           TDHS + "24.11_SNAP_Work_Requirements_-_Esigned_unlined.pdf", "pdf"),
    Source("tdhs_24_12", "SNAP Policy 24.12: Resources", "Tennessee Department of Human Services",
           TDHS + "Policy_24.12_SNAP_Resources_-esigned.pdf", "pdf"),
    Source("tdhs_24_14", "SNAP Policy 24.14: Income", "Tennessee Department of Human Services",
           TDHS + "24.14%20SNAP%20Income.pdf", "pdf"),
    Source("tdhs_24_18", "SNAP Policy 24.18: Deductions from Income", "Tennessee Department of Human Services",
           TDHS + "Policy%2024.18%20SNAP%20Deductions%20from%20Income_Esigned.pdf", "pdf"),
    Source("tdhs_24_24", "SNAP Policy 24.24: Categorically Eligible SNAP Recipients",
           "Tennessee Department of Human Services",
           TDHS + "24.24%20Categorically%20Eligible%20SNAP%20Recipients.pdf", "pdf"),
    Source("tdhs_24_27", "SNAP Policy 24.27: Students in Higher Education", "Tennessee Department of Human Services",
           TDHS + "Policy%2024.27%20SNAP%20Students%20in%20Higher%20Educ.pdf", "pdf"),
    Source("fns_wic_ieg", "WIC Income Eligibility Guidelines, July 1, 2026 to June 30, 2027",
           "USDA Food and Nutrition Service", "https://www.fns.usda.gov/wic/fr-042926", "html"),
    Source("tenncare_erg", "TennCare Eligibility Reference Guide", "Division of TennCare",
           "https://www.tn.gov/coverkids/coverkids/redirect-income-guidelines.html", "html"),
    Source("hhs_poverty_2026", "2026 Poverty Guidelines", "U.S. Department of Health and Human Services (ASPE)",
           "https://aspe.hhs.gov/topics/poverty-economic-mobility/poverty-guidelines", "html"),
    Source("fns_snap_tn_directory", "SNAP State Directory: Tennessee", "USDA Food and Nutrition Service",
           "https://www.fns.usda.gov/snap-directory-entry/tennessee", "html"),
    Source("tn_wic", "Tennessee Women, Infants & Children (WIC) Program", "Tennessee Department of Health",
           "https://www.tn.gov/health/wic.html", "html"),
    Source("tenncare_apply", "How Do I Apply for TennCare?", "Division of TennCare",
           "https://www.tn.gov/tenncare/members-applicants/how-do-i-apply-for-tenncare.html", "html"),
    _ecfr("ecfr_7_273_9", 7, 273, "273.9", "SNAP income and deductions"),
    _ecfr("ecfr_7_273_10", 7, 273, "273.10", "SNAP determining household eligibility and benefit levels"),
    _ecfr("ecfr_7_246_2", 7, 246, "246.2", "WIC definitions"),
    _ecfr("ecfr_7_246_7", 7, 246, "246.7", "WIC certification of participants"),
    _ecfr("ecfr_42_435_406", 42, 435, "435.406", "Medicaid citizenship and non-citizen eligibility"),
    _ecfr("ecfr_42_435_603", 42, 435, "435.603", "Medicaid MAGI-based income methodologies"),
    # Not official: the only places the reported 200% SNAP limit appears.
    Source("tjc_snap_guide", "SNAP Guide for Tennesseans (updated 06.25.2026)", "Tennessee Justice Center",
           "https://www.tnjustice.org/_files/ugd/07a490_b27db0ba3f0f4d5b80207832c4a81583.pdf", "pdf",
           official=False),
    Source("hoodline_bbce", "SNAP shakeup could put more food on Memphis tables (June 2026)", "Hoodline",
           "https://hoodline.com/2026/06/snap-shakeup-could-put-more-food-on-memphis-tables/", "html",
           official=False),
]
BY_ID = {s.id: s for s in SOURCES}


def normalize(text: str) -> str:
    """Whitespace and ligatures folded, so a quote matches however the source was laid out."""
    for a, b in (("\ufb01", "fi"), ("\ufb02", "fl"), ("\u2019", "'"), ("\u00a0", " "), ("\u2011", "-")):
        text = text.replace(a, b)
    return re.sub(r"\s+", " ", text).strip()


def html_to_text(raw: bytes) -> str:
    t = raw.decode("utf-8", errors="replace")
    t = re.sub(r"(?is)<(script|style|nav|header|footer|noscript)\b.*?</\1>", "", t)
    # Keep the targets of absolute links: application portals live in them.
    t = re.sub(r'(?is)<a\b[^>]*href="(https?://[^"]+)"[^>]*>(.*?)</a>', r"\2 [\1]", t)
    t = re.sub(r"(?i)<(br|/p|/tr|/li|/h\d|/div|/table)[^>]*>", "\n", t)
    t = re.sub(r"(?i)</t[dh]>", " | ", t)
    t = html.unescape(re.sub(r"<[^>]+>", "", t))
    t = re.sub(r"[ \t ]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n", t).strip() + "\n"


def xml_to_text(raw: bytes) -> str:
    t = html.unescape(re.sub(r"<[^>]+>", " ", raw.decode("utf-8", errors="replace")))
    return re.sub(r"\s+", " ", t).strip() + "\n"


def pdf_to_text(raw: bytes) -> str:
    if not shutil.which("pdftotext"):
        raise RuntimeError("pdftotext (poppler) is needed to refresh PDF sources: brew install poppler")
    with tempfile.TemporaryDirectory() as d:
        pdf = Path(d) / "in.pdf"
        pdf.write_bytes(raw)
        subprocess.run(["pdftotext", "-layout", str(pdf), str(pdf.with_suffix(".txt"))], check=True)
        return pdf.with_suffix(".txt").read_text(encoding="utf-8")


def xlsx_to_text(raw: bytes) -> str:
    """Every row of every sheet as ``a | b | c`` lines (stdlib only)."""
    z = zipfile.ZipFile(io.BytesIO(raw))
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in re.findall(r"<si>(.*?)</si>", z.read("xl/sharedStrings.xml").decode(), re.S):
            shared.append(html.unescape(re.sub(r"<[^>]+>", "", si)))
    lines = []
    for name in sorted(n for n in z.namelist() if n.startswith("xl/worksheets/sheet")):
        for row in re.findall(r"<row[^>]*>(.*?)</row>", z.read(name).decode(), re.S):
            cells = []
            for attrs, body in re.findall(r"<c ([^>]*?)(?:/>|>(.*?)</c>)", row, re.S):
                v = re.search(r"<v>(.*?)</v>", body or "")
                value = v.group(1) if v else ""
                if 't="s"' in attrs and value:
                    value = shared[int(value)]
                cells.append(value)
            lines.append(" | ".join(cells))
    return "\n".join(lines) + "\n"


EXTRACT = {"html": html_to_text, "pdf": pdf_to_text, "xlsx": xlsx_to_text, "ecfr": xml_to_text}


def download(url: str, timeout: float = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            import gzip

            data = gzip.decompress(data)
        return data


def latest_ecfr_date() -> str:
    """eCFR serves a title only up to its last processed date, which lags today by a day or two."""
    titles = json.loads(download("https://www.ecfr.gov/api/versioner/v1/titles.json"))["titles"]
    return min(t["up_to_date_as_of"] for t in titles if t["number"] in (7, 42))


def load_manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}


def text_path(source_id: str) -> Path:
    return TEXT_DIR / f"{source_id}.txt"


def source_text(source_id: str) -> str:
    return text_path(source_id).read_text(encoding="utf-8")


def fetch(ids: list[str] | None = None, write: bool = True, ecfr_date: str | None = None) -> list[dict]:
    """Download sources; with ``write`` update the text files and manifest.

    Returns one report per source: whether the extracted text changed, or the
    error that stopped the download.
    """
    manifest = load_manifest()
    ecfr_date = ecfr_date or latest_ecfr_date()
    reports = []
    for s in SOURCES:
        if ids and s.id not in ids:
            continue
        url = s.url.format(ecfr_date=ecfr_date)
        try:
            raw = download(url)
            text = EXTRACT[s.kind](raw)
        except Exception as e:  # noqa: BLE001 - report every failure, keep going
            reports.append({"id": s.id, "error": f"{type(e).__name__}: {e}"})
            continue
        old = text_path(s.id).read_text(encoding="utf-8") if text_path(s.id).exists() else None
        changed = old is None or normalize(old) != normalize(text)
        reports.append({"id": s.id, "changed": changed})
        if write:
            TEXT_DIR.mkdir(parents=True, exist_ok=True)
            text_path(s.id).write_text(text, encoding="utf-8")
            manifest[s.id] = {
                "title": s.title, "publisher": s.publisher, "url": s.link, "official": s.official,
                "retrieved": date.today().isoformat(),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
    if write:
        MANIFEST.write_text(json.dumps(dict(sorted(manifest.items())), indent=2) + "\n", encoding="utf-8")
    return reports
