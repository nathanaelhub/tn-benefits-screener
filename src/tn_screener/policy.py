"""Keyword search over the official source texts (BM25, stdlib only).

The screener's rules cover the common cases; this is for everything else a
person asks about ("does SNAP count my child's SSI?"), so the model can quote
the actual policy rather than paraphrase from memory. Sources are split into
overlapping passages of about 120 words; results carry the source's title,
publisher, URL and whether it is official.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import cache

from . import sources

WORDS = 120
STRIDE = 80
K1, B = 1.5, 0.75
STOP = set("a an and are as at be by can do does for from has have how i if in is it its my of on or "
           "the their there this to was what when who will with you your".split())


def tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", text.lower()) if t not in STOP]


@dataclass(frozen=True)
class Passage:
    source: str
    text: str


@cache
def index() -> tuple[list[Passage], list[Counter], dict[str, int], float]:
    passages = []
    for s in sources.SOURCES:
        if not sources.text_path(s.id).exists():
            continue
        words = sources.normalize(sources.source_text(s.id)).split(" ")
        for start in range(0, max(1, len(words) - WORDS + STRIDE), STRIDE):
            passages.append(Passage(s.id, " ".join(words[start:start + WORDS])))
    tfs = [Counter(tokens(p.text)) for p in passages]
    df: Counter = Counter()
    for tf in tfs:
        df.update(tf.keys())
    avg = sum(sum(tf.values()) for tf in tfs) / max(1, len(tfs))
    return passages, tfs, dict(df), avg


def search(query: str, limit: int = 5, program: str | None = None, official_only: bool = False) -> list[dict]:
    """The best-matching passages for ``query``, most relevant first."""
    passages, tfs, df, avg = index()
    q = tokens(query)
    if not q:
        return []
    n = len(passages)
    scored = []
    for p, tf in zip(passages, tfs, strict=True):
        src = sources.BY_ID[p.source]
        if official_only and not src.official:
            continue
        if program and program not in _programs(p.source):
            continue
        length = sum(tf.values())
        score = 0.0
        for t in q:
            if t in tf:
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                score += idf * tf[t] * (K1 + 1) / (tf[t] + K1 * (1 - B + B * length / avg))
        if score > 0:
            scored.append((score, p))
    scored.sort(key=lambda x: -x[0])
    out, seen = [], set()
    for score, p in scored:
        # Overlapping passages repeat each other; keep one per stretch of text.
        key = (p.source, p.text[:60])
        if key in seen:
            continue
        seen.add(key)
        src = sources.BY_ID[p.source]
        out.append({"source": src.title, "publisher": src.publisher, "url": src.link,
                    "official": src.official, "text": p.text, "score": round(score, 2)})
        if len(out) == limit:
            break
    return out


def _programs(source_id: str) -> set[str]:
    if source_id.startswith(("tdhs_", "fns_snap", "fns_bbce", "fns_sua", "ecfr_7_273", "tjc_", "hoodline")):
        return {"snap"}
    if source_id.startswith(("fns_wic", "ecfr_7_246", "tn_wic")):
        return {"wic"}
    if source_id.startswith(("tenncare", "ecfr_42")):
        return {"tenncare"}
    return {"snap", "wic", "tenncare"}
