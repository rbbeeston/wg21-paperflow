#
# Copyright (c) 2026 Rob Beeston (rob@cppalliance.org)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
#

"""Meaning: column coherence of the area's best reading - items per cell,
fragments, header vs body, the weakest column's shape uniformity, and the
first column as a list of keys (local shape tier; no Jev)."""
import re
from collections import Counter

from .base import Check

_NUM = re.compile(r"^[\s$€£~≈<>=+\-–−]*[\d.,]+\s*(%|[a-zA-Zµ]{0,3}|[KMGkmgx×])?\s*$")
_MARK = re.compile(r"^(yes|no|y|n|✓|✔|✗|✘|x|-|–|-|n/a|tbd|\?|ok|none|true|false|partial)\.?$", re.I)
_IDENT = re.compile(r"^[~&*]?[A-Za-z_][\w:<>,\[\]~*&.\-]*(\(\))?$")
_CODE = re.compile(r"[;{}]|::|->|\(.*\)|<.*>|==|&&")


def shape(cell: str) -> str:
    t = cell.strip()
    if not t:
        return "empty"
    if _NUM.match(t):
        return "number"
    if _MARK.match(t):
        return "mark"
    words = t.split()
    if len(words) == 1 and _IDENT.match(t):
        return "identifier"
    if _CODE.search(t) and not re.search(r"[a-z]{3,}\s+[a-z]{3,}\s+[a-z]{3,}", t):
        return "code"
    if len(words) <= 4:
        return "name" if all(w[:1].isupper() or not w[:1].isalpha() for w in words) else "phrase"
    return "sentence"


def column_coherence(rows, skip_header=True):
    """Per column: share of the dominant shape among filled body cells, or None (abstain)."""
    body = rows[1:] if skip_header and len(rows) > 2 else rows
    ncol = max((len(r) for r in rows), default=0)
    out = []
    for c in range(ncol):
        kinds = [shape(r[c]) for r in body if c < len(r)]
        kinds = [k for k in kinds if k != "empty"]
        if len(kinds) < 3:
            out.append(None)
            continue
        # sentences and phrases are one family (notes columns mix them)
        fam = ["text" if k in ("sentence", "phrase", "name") else k for k in kinds]
        out.append(Counter(fam).most_common(1)[0][1] / len(fam))
    return out


def table_coherence(rows):
    cs = [c for c in column_coherence(rows) if c is not None]
    return min(cs) if cs else None


_TOKEN = re.compile(r"[A-Za-z_][\w:]*(?:<[^>]*>)?|\d[\d.,]*%?|[✓✔✗✘]")
_SENT_END = re.compile(r"[.!?]\s+[A-Z]")
_DANGLING_END = re.compile(r"(,|-|\(|\b(and|or|of|the|a|an|to|in|for|with|by|on|that|is|are|as)\b)\s*$", re.I)


def merged_share(rows):
    """Items per cell: the worst column's share of body cells holding several
    items of the column's own single-item kind (identifiers, numbers, marks),
    or several sentences. High means rows were merged."""
    body = rows[1:] if len(rows) > 2 else rows
    ncol = max((len(r) for r in rows), default=0)
    worst = None
    for c in range(ncol):
        cells = [r[c].strip() for r in body if c < len(r) and r[c].strip()]
        if len(cells) < 2:
            continue
        single = [shape(x) for x in cells]
        kind = Counter(single).most_common(1)[0][0]
        if kind in ("identifier", "number", "mark", "name"):
            many = sum(1 for x in cells if len(_TOKEN.findall(x)) >= 3 and len(x.split()) >= 3
                       and all(shape(w) in ("identifier", "number", "mark", "name", "phrase") for w in x.split()))
        else:
            many = sum(1 for x in cells if len(_SENT_END.findall(x)) >= 2)
        v = many / len(cells)
        worst = v if worst is None else max(worst, v)
    return worst


def fragment_share(rows):
    """Fragments: body cells that start as a continuation (lowercase first word
    after a cell above that ended mid-phrase) or end mid-phrase."""
    body = rows[1:] if len(rows) > 2 else rows
    n = frag = 0
    for i, r in enumerate(body):
        for c, x in enumerate(r):
            x = x.strip()
            if not x or shape(x) not in ("sentence", "phrase"):
                continue
            n += 1
            above = body[i - 1][c].strip() if i and c < len(body[i - 1]) else ""
            if (x[0].islower() and above and _DANGLING_END.search(above)) or _DANGLING_END.search(x):
                frag += 1
    return frag / n if n >= 3 else None


def header_contrast(rows):
    """Header vs body: share of columns whose header cell is a different kind
    from the column's body (a category over instances)."""
    if len(rows) < 3:
        return None
    head, body = rows[0], rows[1:]
    cols = 0
    diff = 0
    for c, h in enumerate(head):
        cells = [shape(r[c]) for r in body if c < len(r) and r[c].strip()]
        if len(cells) < 2 or not h.strip():
            continue
        cols += 1
        dom = Counter(cells).most_common(1)[0][0]
        hk = shape(h)
        if hk != dom or (dom in ("sentence", "phrase") and len(h.split()) <= 3
                         and sum(len(r[c].split()) for r in body if c < len(r)) / len(body) > 6):
            diff += 1
    return diff / cols if cols >= 2 else None



def _best_reading(a):
    order = ("tags", "poll", "grid", "rules", "codepair", "content", "tomd")
    rs = sorted(a["readings"], key=lambda r: order.index(r[0]) if r[0] in order else 99)
    return rs[0][3] if rs else None


def content_features(rows) -> dict:
    f = {}
    if not rows or len(rows) < 2:
        return {"c_has_reading": 0.0}
    f["c_has_reading"] = 1.0
    f["c_rows"] = float(len(rows))
    f["c_cols"] = float(max(len(r) for r in rows))
    for name, fn in (("c_items_per_cell", merged_share), ("c_fragments", fragment_share),
                     ("c_header_vs_body", header_contrast), ("c_min_coherence", table_coherence)):
        v = fn(rows)
        f[name] = -1.0 if v is None else float(v)
    first = [shape(r[0]) for r in rows[1:] if r and r[0].strip()]
    f["c_first_col_keys"] = (Counter(first).most_common(1)[0][1] / len(first)
                             if len(first) >= 3 and all(len(r[0].split()) <= 6 for r in rows[1:] if r) else -1.0)
    return f




def run(ctx) -> dict:
    return content_features(_best_reading(ctx.area))


CHECK = Check("coherence", ("region", "columns", "cells"), "meaning", 0, False, run)
