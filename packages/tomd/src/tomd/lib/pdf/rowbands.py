#
# Copyright (c) 2026 Rob Beeston (rob@cppalliance.org)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
#

"""Rows bounded by drawn rules (2026-10-24).

In a drawn grid whose records are separated by horizontal rules (comment forms such as national-
body ballots), every text line between the same pair of rules belongs to one record. A reader
that cuts a multi-line record into several rows leaves the continuation lines as rows whose key
(first) column is empty. Such a row is joined to the row above when it lies wholly below that
row and no drawn rule crosses the two rows' combined extent; the joined cell keeps its lines
("\n" span between them).

Only joins, never splits. Applies to single-page readings inside a ruled grid: at least
MIN_RULES horizontal rules each covering 60% of the table's width (segments at one height
merged). Measured on the tuning sets (REPORT.md, rule-bounded rows, version 4b): 14 tables
changed, all better, none worse; a version without the empty-key condition broke tables whose
grids rule only the header and border, and one testing only the gap between rows merged across
a rule running through a reading's rows.
"""
from .types import Span

MIN_RULES = 4
MIN_SEGMENT = 15.0      # pt: shorter strokes are not row separators
# a row filling this share of its other (non-key) columns is a record of its own, never a
# continuation (user, 2026-10-24): in a grouped grid the first column is blank on every row of a
# group after the first, and those rows are full. 0.67 is the strictest value that keeps every
# tuning-set gain (0.5 keeps 7 of 14).
MAX_FILL = 0.67


def _text(cell) -> str:
    return " ".join(s.text for s in cell if s.text != "\n").strip()


def _full_rules(rules, box) -> int:
    """number of rule heights covering 60% of the box width, segments at one height merged."""
    by_y: dict = {}
    for y, a, b in rules:
        a, b = max(a, box[0]), min(b, box[2])
        if b > a and box[1] - 4 <= y <= box[3] + 4:
            by_y.setdefault(round(y), []).append((a, b))
    n, last = 0, None
    for y, iv in sorted(by_y.items()):
        cov, end = 0.0, None
        for a, b in sorted(iv):
            if end is None or a > end:
                cov, end = cov + b - a, b
            elif b > end:
                cov, end = cov + b - end, b
        if cov >= 0.6 * (box[2] - box[0]) and (last is None or y - last > 2):
            n, last = n + 1, y
    return n


def merge_rule_bands(sec, rules) -> int:
    """Join empty-key continuation rows into the record above within one rule band; returns the
    number of rows joined. rules: the page's horizontal rule segments (y, x0, x1)."""
    rows = sec.columns or []
    pages = {ln.page_num for ln in sec.lines or []}
    if len(rows) < 2 or len(pages) != 1:
        return 0
    boxes = [s.bbox for r in rows for c in r for s in c if s.text.strip()]
    if not boxes:
        return 0
    box = (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
    if _full_rules(rules, box) < MIN_RULES:
        return 0
    segs = [y for y, a, b in rules if min(b, box[2]) - max(a, box[0]) >= MIN_SEGMENT
            and box[1] - 4 <= y <= box[3] + 4]
    out, ext, joined = [], [], 0
    for r in rows:
        sp = [s.bbox for c in r for s in c if s.text.strip()]
        e = (min(b[1] for b in sp), max(b[3] for b in sp)) if sp else None
        fill = sum(1 for c in r[1:] if _text(c)) / max(len(r) - 1, 1)
        if (out and e and ext[-1] and len(r) == len(out[-1]) and not _text(r[0]) and fill < MAX_FILL
                and e[0] >= ext[-1][1] - 1 and not any(ext[-1][0] + 1 < y < e[1] - 1 for y in segs)):
            out[-1] = [a + ([Span(text="\n")] if _text(a) and _text(b) else []) + b
                       for a, b in zip(out[-1], r)]
            ext[-1] = (ext[-1][0], e[1])
            joined += 1
        else:
            out.append(list(r))
            ext.append(e)
    if joined:
        sec.columns = out
        sec.metadata["rule_band_joins"] = joined
    return joined
