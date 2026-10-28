#
# Copyright (c) 2026 Rob Beeston (rob@cppalliance.org)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
#

"""Stage 1: the relationship record and the relational checker.

A table asserts relationships between the words of its region: two words
share a row, share a column, share a cell. The page shows others, observed
from the word positions and drawings: two words sit on one baseline, two
lines start at the same x, a drawn rule or a row gap lies between two lines,
a gutter lies between two words. Each record keeps where it came from
(observed on the page, or inferred by a reader) - never mixed.

The checker lists every contradiction between the two as a violated
relationship, by dimension, instead of stopping at the first failure:

  rows     words on one baseline put in different rows (a row split), or a
           drawn rule / row gap inside one row (rows merged)
  columns  words across a gutter put in one cell (a column merged), or one
           line's words split across cells with no gutter between (a column
           split)
  cells    a page word in no cell, or in two (extent: cut short / swallowed)

No output change: the record goes into the table's metadata and the evidence
record, and drives per-dimension confidence (stage 2) and diagnosis.
"""
import re
from dataclasses import dataclass, field

_TOL = 1.5
_VISIBLE = re.compile(r"[^\s\u200b-\u200f\u2060\ufeff]")   # zero-width characters are not words
_GUTTER = 8.0          # points: a gap this wide between neighbouring words is a column gap


@dataclass
class Violation:
    dimension: str      # rows | columns | cells
    kind: str           # row split, rows merged, column merged, column split, word outside, word in two cells
    where: tuple        # (row, col) or a word's text and position
    evidence: str       # the observed relationship it contradicts and where it came from


@dataclass
class RelationRecord:
    observed: list = field(default_factory=list)    # (kind, a, b, source)
    asserted: list = field(default_factory=list)    # (kind, a, b, reader)
    violations: list = field(default_factory=list)

    def by_dimension(self) -> dict:
        out: dict = {"rows": 0, "columns": 0, "cells": 0}
        for v in self.violations:
            out[v.dimension] = out.get(v.dimension, 0) + 1
        return out


def _cell_of(word, boxes):
    xc, yc = (word[0] + word[2]) / 2, (word[1] + word[3]) / 2
    return [(r, c) for (r, c), b in boxes.items()
            if b[0] - _TOL <= xc <= b[2] + _TOL and b[1] - _TOL <= yc <= b[3] + _TOL]


def check(rows_boxes: dict, words: list, hrules=(), reader: str = "?", mono=frozenset()) -> RelationRecord:
    """rows_boxes: {(row, col): bbox of the cell's text}; words: fitz word tuples in the
    table's region; hrules: (y, x0, x1) of drawn horizontal rules - only those
    crossing most of the table are row boundaries (an underline, a strike-through
    or one cell's own rule is not)."""
    if rows_boxes:
        tx0 = min(b[0] for b in rows_boxes.values())
        tx1 = max(b[2] for b in rows_boxes.values())
        hrules = [r[0] if isinstance(r, tuple) else r for r in hrules
                  if not isinstance(r, tuple) or min(r[2], tx1) - max(r[1], tx0) >= 0.6 * (tx1 - tx0)]
    rec = RelationRecord()
    owner = {}
    words = [w for w in words if _VISIBLE.search(w[4])]
    for i, w in enumerate(words):
        hits = _cell_of(w, rows_boxes)
        if not hits:
            rec.violations.append(Violation("cells", "word outside every cell", (w[4], round(w[0]), round(w[1])),
                                            "observed: the word lies in the table's region"))
        elif len(hits) > 1:
            rec.violations.append(Violation("cells", "word in two cells", (w[4], hits),
                                            "observed: cell boxes overlap"))
        else:
            owner[i] = hits[0]
            rec.asserted.append(("in-cell", i, hits[0], reader))
    # rows: words sharing a baseline must share a row
    by_line: dict = {}
    for i, w in enumerate(words):
        key = round((w[1] + w[3]) / 2 / 2)
        by_line.setdefault(key, []).append(i)
    for key, ids in by_line.items():
        rows = {owner[i][0] for i in ids if i in owner}
        if len(rows) > 1:
            rec.observed.append(("same-baseline", ids[0], ids[-1], "page"))
            rec.violations.append(Violation("rows", "row split: one baseline in several rows",
                                            (sorted(rows),), "observed: words on one baseline"))
    # rows: a drawn rule inside a row means rows merged
    row_span: dict = {}
    for (r, c), b in rows_boxes.items():
        lo, hi = row_span.get(r, (b[1], b[3]))
        row_span[r] = (min(lo, b[1]), max(hi, b[3]))
    centres: dict = {}
    for (r, c), b in rows_boxes.items():
        centres.setdefault(r, []).append((b[1] + b[3]) / 2)
    line_ys: dict = {}
    for i, (r, c) in owner.items():
        line_ys.setdefault(r, []).append((words[i][1] + words[i][3]) / 2)
    for r, (lo, hi) in row_span.items():
        # a rule merges rows only with the row's text on both sides of it: text
        # boxes carry the line's leading, so a row's own border can fall inside
        ys = line_ys.get(r) or centres.get(r, [])
        inside = [y for y in hrules if lo + 2 < y < hi - 2
                  and any(c < y - 1 for c in ys) and any(c > y + 1 for c in ys)]
        if inside:
            rec.observed.append(("rule-between", r, inside[0], "paths"))
            rec.violations.append(Violation("rows", "rows merged: a drawn rule inside one row", (r,),
                                            "observed: a horizontal rule crosses the row"))
    # columns: a gutter-sized gap between two words of one cell (column merged)
    lines = {k: [words[i] for i in ids] for k, ids in by_line.items()}
    for key, ids in by_line.items():
        ws = sorted((i for i in ids if i in owner), key=lambda i: words[i][0])
        gaps = sorted(words[b][0] - words[a][2] for a, b in zip(ws, ws[1:]) if owner[a] == owner[b])
        usual = gaps[len(gaps) // 2] if gaps else 0.0
        code = re.search(r"[;{}]|//|::", " ".join(words[i][4] for i in ws))
        for a, b in zip(ws, ws[1:]):
            gap = words[b][0] - words[a][2]
            # a gutter: wide in absolute terms and against the cell's own spacing
            # (justified text stretches every gap; code aligns comments)
            if owner[a] == owner[b] and gap >= max(_GUTTER, 3 * usual) and not code \
                    and owner[a] not in mono \
                    and _recurs(words, lines, key, words[a][2] + 1, words[b][0] - 1):
                rec.violations.append(Violation("columns", "column merged: a gutter inside one cell",
                                                (owner[a],), "observed: wide gap between neighbouring words"))
            if owner[a][0] == owner[b][0] and owner[a][1] != owner[b][1] and gap < 1.0:
                rec.violations.append(Violation("columns", "column split: touching words in two cells",
                                                (owner[a], owner[b]), "observed: no gap between the words"))
    return rec


def _recurs(words, lines, key, x0, x1) -> bool:
    """A column gutter runs down the table: the band [x0, x1] is empty in at
    least two other lines that cross it, and in at least half of them. A wide
    space in one line of prose is not a gutter."""
    if x1 <= x0:
        return False
    crossing = empty = 0
    for k, ln in lines.items():
        if k == key or min(w[0] for w in ln) > x0 or max(w[2] for w in ln) < x1:
            continue
        crossing += 1
        empty += not any(w[0] < x1 and w[2] > x0 for w in ln)
    return empty >= 2 and empty >= 0.5 * crossing


def record_for(sec, words, hrules=()) -> RelationRecord:
    """The relationship record of an emitted table section (cells from its spans)."""
    boxes = {}
    mono = set()        # code cells: aligned operands and comments are the code's own layout
    for r, row in enumerate(sec.columns):
        for c, cell in enumerate(row):
            text = [s for s in cell if s.text.strip() and s.text != "\n"]
            if text and sum(len(s.text) for s in text if s.monospace) >= 0.6 * sum(len(s.text) for s in text):
                mono.add((r, c))
            bs = [s.bbox for s in cell if s.text.strip() and s.text != "\n" and s.bbox and s.bbox[2] > s.bbox[0]]
            if bs:
                boxes[(r, c)] = (min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs),
                                 max(b[3] for b in bs))
    return check(boxes, words, hrules, sec.metadata.get("table_source", "?"), frozenset(mono))
