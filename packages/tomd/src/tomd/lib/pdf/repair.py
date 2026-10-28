#
# Copyright (c) 2026 Rob Beeston (rob@cppalliance.org)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
#

"""Stage 3 (relationship plan): blind smallest-set repair and inferred cells.

A flagged table whose region holds page words that lie in no cell (the
relational checker's "word outside every cell") lost text. The smallest
correction that explains it, made without the answer key (amendment D):

  - a stray word inside a column's span and a row's span belongs to that
    cell: it is placed there, in reading order;
  - stray words outside every row (above the first, between two, below the
    last) form an inferred row, one cell per column;
  - a stray word in no column means the column structure itself does not
    explain it: no smallest repair, the table is left as it was.

The repair is kept only when the relational check of the result has fewer
violations and no kind it did not have before. Inferred cells are marked in
the output (a comment after the table) and the table stays UNCERTAIN; the
first reading, the stray words and the repair go in the metadata
(amendment E: no erasure).
"""
import re

from .types import Span

_TOL = 1.5
_VISIBLE = re.compile(r"[^\s\u200b-\u200f\u2060\ufeff]")   # zero-width characters are not words
_MAX_SHARE = 0.4        # more stray words than this: the reading is wrong, not short of a few words


def _box(cell):
    bs = [s.bbox for s in cell if s.text.strip() and s.text != "\n" and s.bbox and s.bbox[2] > s.bbox[0]]
    if not bs:
        return None
    return (min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs))


def _lines(cell):
    out, cur = [], []
    for s in cell:
        if s.text == "\n":
            if cur:
                out.append(cur)
            cur = []
        elif s.text.strip():
            cur.append(s)
    if cur:
        out.append(cur)
    return out


def _span_for(word, like: list) -> Span:
    mono = sum(len(s.text) for s in like if s.monospace) > 0.5 * max(sum(len(s.text) for s in like), 1)
    size = like[0].font_size if like else word[3] - word[1]
    return Span(text=word[4], font_size=size, monospace=mono, bbox=tuple(word[:4]),
                origin=(word[0], word[3]))


def _place(lines: list, sp: Span) -> None:
    """Put a word's span on the line it shares a baseline with (a new line otherwise),
    with the spaces its neighbours on the page leave around it."""
    yc = (sp.bbox[1] + sp.bbox[3]) / 2
    h = max(sp.bbox[3] - sp.bbox[1], 1.0)
    target = None
    for ln in lines:
        ly = sum((s.bbox[1] + s.bbox[3]) / 2 for s in ln) / len(ln)
        if abs(ly - yc) < 0.5 * h:
            target = ln
            break
    if target is None:
        lines.append([sp])
        lines.sort(key=lambda ln: min(s.bbox[1] for s in ln))
        return
    target.append(sp)
    target.sort(key=lambda s: s.bbox[0])
    i = target.index(sp)
    if i > 0 and sp.bbox[0] - target[i - 1].bbox[2] > 1.0 and not target[i - 1].text.endswith(" "):
        sp.text = " " + sp.text
    if i + 1 < len(target) and target[i + 1].bbox[0] - sp.bbox[2] > 1.0 and not target[i + 1].text.startswith(" "):
        sp.text = sp.text + " "


def _join(lines, nl):
    out = []
    for i, ln in enumerate(lines):
        if i:
            out.append(nl)
        out.extend(ln)
    return out


def place_stray_words(columns: list, words: list, nl: Span):
    """(new columns, inferred [(row, col)], stray words) or None when the stray
    words are not explained by the table's own rows and columns."""
    ncol = max((len(r) for r in columns), default=0)
    boxes = {(r, c): b for r, row in enumerate(columns) for c, cell in enumerate(row) if (b := _box(cell))}
    if not boxes or ncol < 2:
        return None
    cols = {}
    rows = {}
    for (r, c), b in boxes.items():
        x0, x1 = cols.get(c, (b[0], b[2]))
        cols[c] = (min(x0, b[0]), max(x1, b[2]))
        y0, y1 = rows.get(r, (b[1], b[3]))
        rows[r] = (min(y0, b[1]), max(y1, b[3]))

    def inside(w, b):
        xc, yc = (w[0] + w[2]) / 2, (w[1] + w[3]) / 2
        return b[0] - _TOL <= xc <= b[2] + _TOL and b[1] - _TOL <= yc <= b[3] + _TOL

    stray = [w for w in words if _VISIBLE.search(w[4]) and not any(inside(w, b) for b in boxes.values())]
    if not stray or len(stray) > _MAX_SHARE * len(words):
        return None
    # columns: the one whose span holds the word; between two spans, the nearer
    order = sorted(cols)
    placed_in = []
    for w in stray:
        xc = (w[0] + w[2]) / 2
        hit = [c for c in order if cols[c][0] - _TOL <= xc <= cols[c][1] + _TOL]
        if not hit:
            near = min(order, key=lambda c: min(abs(xc - cols[c][0]), abs(xc - cols[c][1])))
            gap = min(abs(xc - cols[near][0]), abs(xc - cols[near][1]))
            if gap > 12.0:
                return None                # outside every column: the columns do not explain it
            hit = [near]
        yc = (w[1] + w[3]) / 2
        row = next((r for r in sorted(rows) if rows[r][0] - _TOL <= yc <= rows[r][1] + _TOL), None)
        placed_in.append((w, hit[0], row, yc))
    new = [[_lines(cell) for cell in row] + [[] for _ in range(ncol - len(row))] for row in columns]
    inferred = set()
    # words in an existing row: into that row's cell
    for w, c, r, _ in placed_in:
        if r is not None:
            like = [s for ln in new[r][c] for s in ln] or [s for row in new for ln in row[c] for s in ln]
            _place(new[r][c], _span_for(w, like))
            inferred.add((r, c))
    # words outside every row: one inferred row per gap they fall in
    loose = sorted((x for x in placed_in if x[2] is None), key=lambda x: x[3])
    bands: dict = {}
    for w, c, _, yc in loose:
        after = max((r for r in rows if rows[r][1] < yc), default=-1)     # the row above the gap
        if after < 0:
            return None      # above the first row: a header or caption question (add_header_above), not a lost row
        bands.setdefault(after, []).append((w, c))
    shift = 0
    for after in sorted(bands):
        at = after + 1 + shift
        row = [[] for _ in range(ncol)]
        for w, c in bands[after]:
            like = [s for r2 in new for ln in r2[c] for s in ln]
            _place(row[c], _span_for(w, like))
        new.insert(at, row)
        inferred = {(r + 1 if r >= at else r, c) for r, c in inferred}
        inferred |= {(at, c) for c in range(ncol) if row[c]}
        shift += 1
    out = [[_join(lines, nl) for lines in row] for row in new]
    return out, sorted(inferred), [w[4] for w in stray]
