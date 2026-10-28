#
# Copyright (c) 2026 Rob Beeston (rob@cppalliance.org)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
#

"""A note on table pieces that may continue the previous page's table (2026-10-24).

When a table piece reaches the bottom of its page's content area and the next page's first table
piece starts at the top of that page's content area, the next piece is noted as possibly
continuing the previous one. The note names the evidence seen: reaches the bottom, starts at the
top, and, when present, the same header row and the first column's numbering continuing.

Since 2026-10-24 the note is written only when the first column's numbering also continues across
the break (US 019 → US 020): with the page-edge signals alone it was right 55 of 150 times on the
tuning sets. It never joins pieces, changes cells or changes
levels, so the note says "may", and the pieces stay separate.

The content area of a page excludes page furniture: lines whose text (digits ignored) repeats
within 3 pt of the same position on an adjacent page.
"""
import re

NEAR = 0.06        # within 6% of the page height of the content edge


def _text(cell) -> str:
    return " ".join(s.text for s in cell if s.text != "\n").strip()


def _lines(page):
    out = []
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            t = "".join(s["text"] for s in ln["spans"]).strip()
            if t:
                out.append((ln["bbox"][1], ln["bbox"][3], re.sub(r"\d+", "#", t)))
    return out


class _Areas:
    def __init__(self, doc):
        self.doc, self.lines, self.areas = doc, {}, {}

    def _ls(self, i):
        if i not in self.lines:
            self.lines[i] = _lines(self.doc[i]) if 0 <= i < len(self.doc) else []
        return self.lines[i]

    def area(self, i):
        """(top, bottom, height) of page i's content, page furniture left out."""
        if i not in self.areas:
            near = [(y0, t) for j in (i - 1, i + 1) for y0, _, t in self._ls(j)]
            body = [(y0, y1) for y0, y1, t in self._ls(i)
                    if not any(tt == t and abs(yy - y0) <= 3 for yy, tt in near)]
            h = self.doc[i].rect.height
            self.areas[i] = (min((a for a, _ in body), default=None), max((b for _, b in body), default=None), h)
        return self.areas[i]


def _extent(sec):
    bs = [ln.bbox for ln in sec.lines or [] if ln.text.strip()]
    return (min(b[1] for b in bs), max(b[3] for b in bs)) if bs else None


def _number(cell):
    m = re.search(r"(\d+)\s*$", cell) or re.match(r"\s*(\d+)", cell)
    return int(m.group(1)) if m else None


def annotate(doc, tables) -> int:
    """Set metadata["continues_from"] = {"page": N, "reasons": [...]} (N 1-based, the previous
    page) on table pieces that may continue the previous page's table. Returns the count."""
    pieces = []
    for sec in tables:
        pages = sorted({ln.page_num for ln in sec.lines or []})
        ext = _extent(sec)
        if pages and ext and sec.columns:
            pieces.append((pages[0], pages[-1], ext, sec))
    areas = _Areas(doc)
    n = 0
    for first_a, last_a, ext_a, a in pieces:
        # a must be the last table on its last page; b the first on the next page
        if any(f <= last_a <= l and e[0] > ext_a[0] and s is not a for f, l, e, s in pieces if l == last_a):
            continue
        nxt = [(e[0], s) for f, _, e, s in pieces if f == last_a + 1]
        if not nxt:
            continue
        b = min(nxt, key=lambda x: x[0])[1]
        top_a, bot_a, h_a = areas.area(last_a)
        top_b, _, h_b = areas.area(last_a + 1)
        ext_b = _extent(b)
        if bot_a is None or top_b is None or not ext_b:
            continue
        if bot_a - ext_a[1] > NEAR * h_a or ext_b[0] - top_b > NEAR * h_b:
            continue
        reasons = [f"reaches the bottom of page {last_a + 1}", f"starts at the top of page {last_a + 2}"]
        ra = [[_text(c) for c in r] for r in a.columns]
        rb = [[_text(c) for c in r] for r in b.columns]
        if ra and rb and ra[0] == rb[0] and any(ra[0]):
            reasons.append("same header row")
        last_key = next((r[0] for r in reversed(ra) if r and r[0]), "")
        body_b = rb[1:] if ra and rb and ra[0] == rb[0] else rb
        first_key = next((r[0] for r in body_b if r and r[0]), "")
        na, nb = _number(last_key), _number(first_key)
        if na is not None and nb is not None and 0 < nb - na <= 3:
            reasons.append(f"numbering continues ({last_key} → {first_key})")
        else:
            # noted only when the first column's numbering continues (user, 2026-10-24): the
            # page-edge signals alone were right 55 of 150 times on the tuning sets
            continue
        b.metadata["continues_from"] = {"page": last_a + 1, "reasons": reasons}
        n += 1
    return n
