#
# Copyright (c) 2026 Rob Beeston (rob@cppalliance.org)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
#

"""Content record-pattern reader: a table seen as runs of records that share a
schema of kinds, with no geometry.

The text layer gives a region's lines in reading order. Each line has a kind
(an identifier such as P1234R0 or [expr.add], a date, a number, a check mark,
code, words). In most PDFs a table's cells come out one per line, so a table
reads as a sequence whose kinds repeat with a period: name, number, number,
name, number, number, ... A run of at least three periods with at least two
kinds in a period is a run of records; the period is the column count and
each period a row. The k lines just before the run become the header when
they are short labels.

Rows and columns come from the text's own pattern (meaning), not from
positions, so this is a different way to see a table from every other
reader. Measured on the answer keys first: alone it is noisy (code listings
repeat too), so it reads only regions other cues nominated, never votes for
HIGH, and is an alternative that escalation may switch to when the emitted
reading fails verification and this one passes.
"""
import re

from .types import Line, Span, TableCandidate

_KINDS = [
    ("id", re.compile(r"^(\[?[PN]\d{3,5}(R\d+)?\]?|#\d+|LWG\d+|CWG\d+|\[[a-z][\w.:-]*\])[,.;]?$", re.I)),
    ("date", re.compile(r"^\d{4}-\d{2}(-\d{2})?$")),
    ("num", re.compile(r"^[-+−]?\d[\d.,]*%?$")),
    ("mark", re.compile(r"^[✔✓✗✘×•]$")),
]
_CODE = re.compile(r"[(){}<>;=]|::|->|\w_\w")
_MIN_RECORDS = 3
_MAX_PERIOD = 8


def _token_kind(t: str) -> str:
    for k, r in _KINDS:
        if r.match(t):
            return k
    return "code" if _CODE.search(t) else "word"


def line_kind(text: str) -> str:
    """One kind for a line: its tokens' kind when they all share one, else 'mixed'."""
    kinds = {_token_kind(t) for t in text.split()}
    return kinds.pop() if len(kinds) == 1 else "mixed"


def periodic_runs(kinds: list[str]) -> list[tuple[int, int, int]]:
    """(start, period, records) for runs whose kinds repeat with a period, longest first."""
    out = []
    for k in range(2, _MAX_PERIOD + 1):
        i = 0
        while i + _MIN_RECORDS * k <= len(kinds):
            j = i
            while j + k < len(kinds) and kinds[j] == kinds[j + k]:
                j += 1
            n = (j + k - i) // k
            if n >= _MIN_RECORDS and len(set(kinds[i:i + k])) >= 2:
                out.append((i, k, n))
                i += n * k
            else:
                i += 1
    return sorted(out, key=lambda r: -r[1] * r[2])


def _lines_in(page, bbox) -> list[Line]:
    x0, y0, x1, y1 = bbox
    out = []
    for b in page.get_text("dict", clip=(x0 - 2, y0 - 2, x1 + 2, y1 + 2))["blocks"]:
        for ln in b.get("lines", []):
            if abs(ln.get("dir", (1, 0))[0] - 1.0) > 0.01:
                continue                     # rotated text is a header question, not a record
            spans = [Span(text=s["text"], font_size=s["size"], bold=bool(s["flags"] & 16),
                          italic=bool(s["flags"] & 2), monospace=bool(s["flags"] & 8),
                          bbox=tuple(s["bbox"]), origin=tuple(s["origin"]))
                     for s in ln["spans"] if s["text"]]
            if "".join(sp.text for sp in spans).strip():      # the spaces between words may be spans of their own
                out.append(Line(spans=spans, bbox=tuple(ln["bbox"])))
    return out


def _text(line: Line) -> str:
    return "".join(s.text for s in line.spans).strip()


def read_region(page, page_num: int, bbox) -> list[TableCandidate]:
    """Every run of records in the region (longest first, not overlapping), each
    with its header and its own box; none unless together they cover most of
    the region's lines (a region holding two stacked tables reads as two)."""
    lines = _lines_in(page, bbox)
    for ln in lines:
        ln.page_num = page_num
    kinds = [line_kind(_text(ln)) for ln in lines]
    used: set = set()
    picked = []
    for start, k, n in periodic_runs(kinds):
        span = set(range(start, start + n * k))
        if span & used:
            continue
        head = list(range(start - k, start)) if start >= k else []
        if not (head and not set(head) & used
                and all(kinds[i] == "word" and len(_text(lines[i]).split()) <= 5 for i in head)):
            head = []
        used |= span | set(head)
        picked.append((start, k, n, head))
    if not picked or len(used) < 0.6 * len(lines):
        return []
    out = []
    for start, k, n, head in sorted(picked):
        rows = ([[[lines[i]] for i in head]] if head else []) + \
               [[[ln] for ln in lines[start + r * k:start + (r + 1) * k]] for r in range(n)]
        mine = [ln for row in rows for cell in row for ln in cell]
        box = (min(ln.bbox[0] for ln in mine), min(ln.bbox[1] for ln in mine),
               max(ln.bbox[2] for ln in mine), max(ln.bbox[3] for ln in mine))
        cand = TableCandidate("records", rows, {page_num: box})
        if len(picked) > 1:
            cand.flags = cand.flags + ["records-split"]
        if head:
            cand.flags = cand.flags + ["records-headed"]
        if {"code", "mixed"} & set(kinds[start:start + k]):
            cand.flags = cand.flags + ["records-code"]     # code repeats too: an alternative only
        out.append(cand)
    return out


def records_candidates(pages, regions) -> list[TableCandidate]:
    """The record-pattern reading of every located region (page, bbox)."""
    out, seen = [], set()
    for page_num, bbox in regions:
        key = (page_num, tuple(round(v) for v in bbox))
        if key in seen or page_num not in pages:
            continue
        seen.add(key)
        out += read_region(pages[page_num], page_num, bbox)
    return out
