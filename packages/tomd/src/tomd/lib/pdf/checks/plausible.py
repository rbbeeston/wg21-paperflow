#
# Copyright (c) 2026 Rob Beeston (rob@cppalliance.org)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
#

"""Content plausibility: does the reading make sense as data? A meaning-based
witness, independent of geometry: it reads only the cells' text.

  sequence order   a key column that is mostly ordered (dates "2022.3",
                   "2024-01-05", section numbers, versions, paper numbers,
                   row numbers) with one or two values out of place
  poll counts      a poll (SF F N A SA header) whose count cells hold words
                   or non-integers
  column type      a column of numbers, marks or code with a cell of prose
                   (four or more words) in it
  duplication      identical non-trivial cell text in adjacent rows (a
                   misread or a doubled text layer)

plausibility(rows) -> list of (check, detail) violations; an empty list is
"no violation". Measured on the keys before it may count for anything
(plausible_measure.py).
"""
import re

_DATE = re.compile(r"^(\d{4})[.\-/](\d{1,2})(?:[.\-/](\d{1,2}))?\b")
_SECTION = re.compile(r"^(\d+(?:\.\d+)+)\b")
_PAPER = re.compile(r"^[PN](\d{3,5})(?:R(\d+))?\b", re.I)
_INT = re.compile(r"^\d{1,6}$")
_NUM = re.compile(r"^[-+−]?\d[\d.,]*%?$")
_MARK = re.compile(r"^[✔✓✗✘×xX\-—–?yYnN]$|^(yes|no|n/a)$", re.I)
_CODE = re.compile(r"[(){}<>;=]|::|->|\w_\w")
_VOTES = {"SF", "F", "N", "A", "SA"}


def _key(v: str):
    v = v.strip()
    for rx, kind in ((_DATE, "date"), (_SECTION, "section"), (_PAPER, "paper")):
        m = rx.match(v)
        if m:
            parts = [g for g in m.groups() if g is not None]
            return kind, tuple(int(x) for g in parts for x in g.split("."))
    if _INT.match(v):
        return "int", (int(v),)
    return None


def sequence_order(rows) -> list:
    body = rows[1:] if len(rows) > 2 else rows
    out = []
    for c in range(min(2, max((len(r) for r in body), default=0))):
        keys = [_key(r[c]) for r in body if c < len(r) and r[c].strip()]
        keys = [k for k in keys if k]
        if len(keys) < 4 or len({k[0] for k in keys}) != 1:
            continue
        vals = [k[1] for k in keys]
        up = sum(a <= b for a, b in zip(vals, vals[1:]))
        down = sum(a >= b for a, b in zip(vals, vals[1:]))
        n = len(vals) - 1
        best = max(up, down)
        if 0.8 * n <= best < n:
            out.append(("sequence order", f"column {c}: {n - best} of {n} steps out of order"))
    return out


def poll_counts(rows) -> list:
    out = []
    for i, r in enumerate(rows):
        head = [x.strip() for x in r]
        cols = [j for j, x in enumerate(head) if x in _VOTES]
        if len(cols) < 3:
            continue
        for r2 in rows[i + 1:]:
            cells = [r2[j].strip() for j in cols if j < len(r2)]
            if any(x in _VOTES for x in cells):
                break                           # the next poll's header
            bad = [x for x in cells if x and x not in ("-", "\u2013", "\u2014") and not _INT.match(x)]   # a dash: no count
            if bad:
                out.append(("poll counts", f"non-integer count cells: {bad[:3]}"))
                return out
    return out


def column_type(rows) -> list:
    body = rows[1:] if len(rows) > 2 else rows
    out = []
    for c in range(max((len(r) for r in body), default=0)):
        cells = [r[c].strip() for r in body if c < len(r) and r[c].strip()]
        if len(cells) < 4:
            continue
        kinds = {"number": [bool(_NUM.match(x)) for x in cells], "mark": [bool(_MARK.match(x)) for x in cells]}
        for kind, hits in kinds.items():
            if sum(hits) >= 0.8 * len(cells) and sum(hits) < len(cells):
                prose = [x for x, h in zip(cells, hits) if not h and len(re.findall(r"[A-Za-z]{2,}", x)) >= 4]
                if prose:
                    out.append(("column type", f"column {c} of {kind}s holds prose: {prose[0][:30]!r}"))
    return out


def duplication(rows) -> list:
    out = []
    for a, b in zip(rows, rows[1:]):
        for c, (x, y) in enumerate(zip(a, b)):
            if x.strip() and x.strip() == y.strip() and len(x.strip()) >= 15:
                out.append(("duplication", f"column {c}: the same text in two adjacent rows: {x.strip()[:30]!r}"))
                return out
    return out


def plausibility(rows) -> list:
    """Every violation of the content checks for a reading (rows of cell strings)."""
    if not rows or len(rows) < 2:
        return []
    return sequence_order(rows) + poll_counts(rows) + column_type(rows) + duplication(rows)
