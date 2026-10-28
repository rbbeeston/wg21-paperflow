#
# Copyright (c) 2026 Rob Beeston (rob@cppalliance.org)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
#

"""Stacked entries are one row each (table convention, "Rows: one row per entry").

Several entries stacked in one drawn band, on baselines shared across columns
("Linux / QNX / NetBSD" beside three function names), are one row each; a cell
whose text wraps is still one row (a wrap breaks at a space, so a line of one
token followed by another line is a new entry). Learned from the vision readers (Table
Transformer, Docling): a line is its own row unless something shows it wraps.

A row is split between two baselines when the lower baseline holds lines in
two or more columns, one of them the row's first column (where an entry's key
sits), and, in every column with a line on both baselines, the
upper line did not run to the column's edge (the next line's first word would
have fitted after it) and the lower line is not a word joined to the upper
one. Rows of C++ statements (a line ending in ; { or }, a preprocessor line, a
comment) are code blocks and are
never split, nor are rows holding a listing (monospace lines with words on them,
such as assembly); the header row and all-bold rows are left as they are.
"""
import re

from .types import Line, TableCandidate

_SOURCES = {"rules", "grid", "content", "tomd"}
_STATEMENT = re.compile(r"[;{}]\s*$|^\s*#\s*[a-z]+|//")
_IDENT = re.compile(r"_|::|<|\(|\)|\[")


def _baseline(ln: Line) -> float:
    o = [s.origin[1] for s in ln.spans if s.text.strip() and s.origin != (0, 0)]
    return max(o) if o else ln.bbox[3]


def _height(ln: Line) -> float:
    return max(ln.bbox[3] - ln.bbox[1], 1.0)


def _first_word_width(ln: Line) -> float:
    t = ln.text.strip()
    if not t:
        return 0.0
    w = ln.bbox[2] - ln.bbox[0]
    first = t.split()[0]
    return w * len(first) / max(len(t), 1)


def _code_block(cell: list[Line]) -> bool:
    """a cell of monospace lines with words on them (instructions, statements) is a listing"""
    ls = [ln for ln in cell if ln.text.strip()]
    if len(ls) < 2:
        return False
    mono = all(all(sp.monospace for sp in ln.spans if sp.text.strip()) for ln in ls)
    return mono and any(len(ln.text.split()) > 1 for ln in ls)


def split_stacked(cand: TableCandidate) -> TableCandidate:
    if cand.source not in _SOURCES or len(cand.rows) < 2:
        return cand
    ncol = max(len(r) for r in cand.rows)
    # each column's right edge: the furthest any of its lines reaches, over the whole table
    right = [max((ln.bbox[2] for r in cand.rows if c < len(r) for ln in r[c] if ln.text.strip()), default=0.0)
             for c in range(ncol)]
    out: list[list[list[Line]]] = []
    changed = False
    for ri, row in enumerate(cand.rows):
        lines = [(c, ln) for c, cell in enumerate(row) for ln in cell if ln.text.strip()]
        if ri == 0 or len(lines) < 4 or any(_STATEMENT.search(ln.text) for _, ln in lines) \
                or all(ln.is_bold for _, ln in lines) \
                or any(_code_block(cell) for cell in row):                  # a header row, a listing
            out.append(row)
            continue
        pages = {ln.page_num for _, ln in lines}
        if len(pages) > 1:
            out.append(row)
            continue
        h = min(_height(ln) for _, ln in lines)
        groups: list[list[tuple[int, Line]]] = []
        for c, ln in sorted(lines, key=lambda t: _baseline(t[1])):
            if groups and _baseline(ln) - _baseline(groups[-1][-1][1]) < 0.45 * h:
                groups[-1].append((c, ln))
            else:
                groups.append([(c, ln)])
        if len(groups) < 2:
            out.append(row)
            continue
        cuts = []
        last: dict[int, Line] = {}
        for c, ln in groups[0]:
            last[c] = ln
        for k in range(1, len(groups)):
            # each column's line just above (in any earlier group: baselines differ a little
            # between columns, and a column may skip a group)
            up = dict(last)
            low = {c: ln for c, ln in groups[k]}
            for c, ln in groups[k]:
                last[c] = ln
            if len(low) < 2:
                continue
            # each column with lines on both baselines votes: a new entry, or a wrap
            starts = wraps = 0
            strong = False
            for c, ln in low.items():
                if getattr(ln, "joins_prev", False):
                    strong = True                     # a word split by the cell: certainly a wrap
                    break
                if c not in up:
                    continue                          # nothing above in this column: no evidence
                a = up[c]
                if a.text.rstrip().endswith(("-", ",", "(")):
                    strong = True
                    break
                space = 0.3 * max(a.font_size, 1.0)
                # only lists of code names are split: one identifier-like token on the line
                # above and one below ("Mohammad" over "Nejati" is a name that wrapped; a
                # token starting "(" continues the line above)
                if len(a.text.split()) == 1 and len(ln.text.split()) == 1 and not ln.text.lstrip().startswith("(") \
                        and (_IDENT.search(a.text) or _IDENT.search(ln.text)):
                    starts += 1
                else:
                    wraps += 1
            # a new entry starts in the row's first column (its key); lines stacked only in
            # later columns (badges, notes beside one entry) stay in their cell
            lead = min(c for c, _ in lines)
            ok = not strong and starts >= 2 and starts > wraps and lead in low
            if ok:
                cuts.append(k)
        if not cuts:
            out.append(row)
            continue
        changed = True
        bounds = [0] + cuts + [len(groups)]
        for a, b in zip(bounds, bounds[1:]):
            part = [[] for _ in range(len(row))]
            for g in groups[a:b]:
                for c, ln in g:
                    part[c].append(ln)
            out.append(part)
    if not changed:
        return cand
    split = TableCandidate(source=cand.source, rows=out, bboxes=dict(cand.bboxes),
                           flags=list(cand.flags) + ["stacked-split"])
    if getattr(cand, "section", None) is not None:
        split.section = cand.section          # the reading it came from keeps its rendering
    return split
