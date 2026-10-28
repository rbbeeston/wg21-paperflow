#
# Copyright (c) 2026 Rob Beeston (rob@cppalliance.org)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
#

"""The fit witness: does the word layout fit the drawn cells evenly?

A drawn grid and the words on the page are two independent sources (paths
and words). When a reading is right, the words fit the drawn cells the way
a typesetter put them there: every word lies fully inside one cell, no word
crosses or touches a rule, and the padding is even - in each column the
text keeps the same inset from the cell edge it is aligned to (left, right
or centre), and in each row band the same inset from the top (or centre).
A misread grid - merged or split cells, a shifted column, a lost row -
breaks the even padding somewhere, or maps one cell of the reading onto two
drawn cells.

Content irregularities (a first column mixing "2022.3 Kona" with "2024.1",
many blank cells) do not count against a tight fit: the fit is what settles
them (user, 2026-10-20).

fit(...) returns a record: whether a drawn grid was found, whether the
fit passes, and why not. It passes only for a fully lined grid that
matches the reading one-to-one (rows and columns), whose drawn frame ends
where the reading ends, and whose cells hold the same characters as the
text layer in each drawn cell (a misread text is not a structure error, so
the fit checks it too).
"""
import unicodedata

_SNAP = 1.5          # points: rule segments this close are one rule
_CLEAR = 0.5         # points: a word this close to a rule touches it
_SPREAD = 1.5        # points: the most an aligned inset may vary in a column or row band
_MIN_SEG = 4.0


def _segments(page, bbox):
    """Horizontal (y, x0, x1) and vertical (x, y0, y1) rule segments in the region,
    from stroked lines, thin filled rectangles and stroked rectangle edges."""
    x0, y0, x1, y1 = bbox
    hs, vs = [], []
    for d in page.get_drawings():
        stroked = d.get("color") is not None
        for it in d.get("items", []):
            if it[0] == "l":
                a, b = it[1], it[2]
                if abs(a.y - b.y) <= 0.8 and abs(a.x - b.x) >= _MIN_SEG:
                    hs.append((a.y, min(a.x, b.x), max(a.x, b.x)))
                elif abs(a.x - b.x) <= 0.8 and abs(a.y - b.y) >= _MIN_SEG:
                    vs.append((a.x, min(a.y, b.y), max(a.y, b.y)))
            elif it[0] == "re":
                r = it[1]
                if r.height <= 1.5 and r.width >= _MIN_SEG:
                    hs.append(((r.y0 + r.y1) / 2, r.x0, r.x1))
                elif r.width <= 1.5 and r.height >= _MIN_SEG:
                    vs.append(((r.x0 + r.x1) / 2, r.y0, r.y1))
                elif stroked and r.width >= _MIN_SEG and r.height >= _MIN_SEG:
                    hs += [(r.y0, r.x0, r.x1), (r.y1, r.x0, r.x1)]
                    vs += [(r.x0, r.y0, r.y1), (r.x1, r.y0, r.y1)]
    pad = 6
    hs = [s for s in hs if x0 - pad <= s[1] and s[2] <= x1 + pad and y0 - pad <= s[0] <= y1 + pad]
    vs = [s for s in vs if y0 - pad <= s[1] and s[2] <= y1 + pad and x0 - pad <= s[0] <= x1 + pad]
    return hs, vs


def _clusters(vals):
    out = []
    for v in sorted(vals):
        if out and v - out[-1][-1] <= _SNAP:
            out[-1].append(v)
        else:
            out.append([v])
    return [sum(c) / len(c) for c in out]


def _covers(segs, at, lo, hi, share=0.7):
    """A rule at `at` covers most of [lo, hi]."""
    got = sorted((max(a, lo), min(b, hi)) for p, a, b in segs if abs(p - at) <= _SNAP and b > lo and a < hi)
    cov, end = 0.0, lo
    for a, b in got:
        if b > end:
            cov += b - max(a, end)
            end = b
    return cov >= share * (hi - lo)


def _spread(vals):
    if len(vals) < 2:
        return 0.0
    v = sorted(vals)
    return v[-1] - v[0] if len(v) < 5 else v[int(len(v) * 0.9) - 1] - v[int(len(v) * 0.1)]


def _frame_continues(page, bbox, xs, ys) -> bool:
    """The drawn frame runs on above or below the grid found in the region: the
    reading covers only part of a larger drawn table."""
    big = (bbox[0] - 6, 0, bbox[2] + 6, page.rect.height)
    _, vs = _segments(page, big)
    for x in (xs[0], xs[-1]):
        for p, a, b in vs:
            if abs(p - x) <= _SNAP and (a < ys[0] - 3 < b or a < ys[-1] + 3 < b):
                return True
    return False


def _squash(text: str) -> str:
    return "".join(unicodedata.normalize("NFKC", text).split())


def grid_of(page, bbox):
    """(xs, ys, has_v, has_h) of the drawn grid, or None: at least 3 column
    lines and 3 row lines that span the region."""
    hs, vs = _segments(page, bbox)
    xs, ys = _clusters([s[0] for s in vs]), _clusters([s[0] for s in hs])
    if len(xs) < 3 or len(ys) < 3:
        return None

    def has_v(i, j):
        return _covers(vs, xs[i], ys[j], ys[j + 1])

    def has_h(j, i):
        return _covers(hs, ys[j], xs[i], xs[i + 1])
    # the outer frame must be drawn (an open table is not a drawn grid)
    if not all(has_v(0, j) and has_v(len(xs) - 1, j) for j in range(len(ys) - 1)):
        return None
    return xs, ys, has_v, has_h


def fit(page, bbox, words, columns) -> dict:
    """Does the reading `columns` (rows of cells of spans) fit the drawn grid?"""
    g = grid_of(page, bbox)
    if g is None:
        return {"ruled": False}
    xs, ys, has_v, has_h = g
    ncol, nrow = len(xs) - 1, len(ys) - 1
    if _frame_continues(page, bbox, xs, ys):
        return {"ruled": True, "pass": False, "why": "the drawn frame continues past the reading"}

    # drawn cells: grid cells joined where the rule between them is absent
    parent = {(j, i): (j, i) for j in range(nrow) for i in range(ncol)}

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k
    for j in range(nrow):
        for i in range(ncol):
            if i + 1 < ncol and not has_v(i + 1, j):
                parent[find((j, i + 1))] = find((j, i))
            if j + 1 < nrow and not has_h(j + 1, i):
                parent[find((j + 1, i))] = find((j, i))
    cells: dict = {}
    for k in parent:
        cells.setdefault(find(k), []).append(k)
    box = {r: (xs[min(i for _, i in ks)], ys[min(j for j, _ in ks)], xs[max(i for _, i in ks) + 1],
               ys[max(j for j, _ in ks) + 1]) for r, ks in cells.items()}
    why = []
    # every word fully inside one drawn cell, clear of its rules
    owner = {}
    inside_frame = [w for w in words if w[4].strip() and xs[0] - 1 <= (w[0] + w[2]) / 2 <= xs[-1] + 1
                    and ys[0] - 1 <= (w[1] + w[3]) / 2 <= ys[-1] + 1]
    for w in inside_frame:
        xc, yc = (w[0] + w[2]) / 2, (w[1] + w[3]) / 2
        hit = [r for r, b in box.items() if b[0] <= xc <= b[2] and b[1] <= yc <= b[3]]
        if len(hit) != 1:
            why.append("word in no drawn cell")
            break
        b = box[hit[0]]
        if w[0] < b[0] + _CLEAR or w[2] > b[2] - _CLEAR or w[1] < b[1] - 1.0 or w[3] > b[3] + 1.0:
            why.append(f"word touches or crosses a rule: {w[4]!r}")
            break
        owner[id(w)] = hit[0]
    if why:
        return {"ruled": True, "pass": False, "why": why[0]}
    # rows and columns are drawn: the drawn row bands and columns that hold words
    # match the reading's rows and columns one to one
    def band_of(v, edges):
        return next((k for k in range(len(edges) - 1) if edges[k] <= v <= edges[k + 1]), None)
    # a merged cell's band is the top band its words sit in; a word's column the
    # drawn cell's first column (a spanning row is one cell of the reading)
    bands = {min(band_of((w[1] + w[3]) / 2, ys) for w in inside_frame if owner.get(id(w)) == c)
             for c in {owner[id(w)] for w in inside_frame if id(w) in owner}}
    cols_used = {i for w in inside_frame if id(w) in owner for _, i in cells[owner[id(w)]]}
    nread = max((len(r) for r in columns), default=0)
    if len(bands) != len(columns) or len(cols_used) != nread:
        return {"ruled": True, "pass": False,
                "why": f"drawn grid {len(bands)}x{len(cols_used)} vs reading {len(columns)}x{nread}"}
    # stacked entries: several aligned records inside one drawn row (two or more
    # columns with several lines on shared baselines) are rows the rules do not draw
    for j in bands:
        per_col = []
        for r, ks in cells.items():
            if min(jj for jj, _ in ks) != j:
                continue
            ws = [w for w in inside_frame if owner.get(id(w)) == r]
            lines: dict = {}
            for w in ws:
                lines.setdefault(round((w[1] + w[3]) / 2), []).append(w)
            ys_ = sorted(lines)
            b = box[r]
            # wrapped prose fills its lines to the cell's right edge (all but the last);
            # stacked entries are short lines that stop well before it
            short = all(max(w[2] for w in lines[y]) < b[2] - 0.15 * (b[2] - b[0]) for y in ys_[:-1])
            if len(ys_) >= 2 and short:
                per_col.append(ys_)
        if len(per_col) >= 2:
            shared = [y for y in per_col[0] if all(any(abs(y - z) <= 2 for z in other) for other in per_col[1:])]
            if len(shared) >= 2:
                return {"ruled": True, "pass": False, "why": "stacked entries inside a drawn row"}
    # even padding: per grid column, the alignment with the least spread; per row band, top or middle
    by_col: dict = {}
    by_row: dict = {}
    for r, ks in cells.items():
        ws = [w for w in inside_frame if owner.get(id(w)) == r]
        if not ws:
            continue
        b = box[r]
        cols = {i for _, i in ks}
        rows = {j for j, _ in ks}
        lx, rx = min(w[0] for w in ws), max(w[2] for w in ws)
        ty, by = min(w[1] for w in ws), max(w[3] for w in ws)
        if len(cols) == 1:
            by_col.setdefault(min(cols), []).append((lx - b[0], b[2] - rx, (lx + rx) / 2 - (b[0] + b[2]) / 2))
        if len(rows) == 1:
            by_row.setdefault(min(rows), []).append((ty - b[1], (ty + by) / 2 - (b[1] + b[3]) / 2))
    worst_col = max((min(_spread([t[k] for t in v]) for k in range(3)) for v in by_col.values() if len(v) >= 2),
                    default=0.0)
    tops = [t for v in by_row.values() for t in v]
    worst_row = min(_spread([t[0] for t in tops]), _spread([t[1] for t in tops])) if len(tops) >= 2 else 0.0
    if worst_col > _SPREAD:
        why.append(f"uneven padding in a column ({worst_col:.1f}pt)")
    if worst_row > 2 * _SPREAD:
        why.append(f"uneven top padding ({worst_row:.1f}pt)")
    # the reading against the drawn cells: one reading cell <-> one drawn cell
    seen: dict = {}
    for ri, row in enumerate(columns):
        for ci, cell in enumerate(row):
            hits = set()
            for s in cell:
                if not s.text.strip() or s.text == "\n" or not s.bbox or s.bbox[2] <= s.bbox[0]:
                    continue
                xc, yc = (s.bbox[0] + s.bbox[2]) / 2, (s.bbox[1] + s.bbox[3]) / 2
                hits |= {r for r, b in box.items() if b[0] <= xc <= b[2] and b[1] <= yc <= b[3]}
            if len(hits) > 1:
                why.append("a cell of the reading spans two drawn cells")
            for h in hits:
                if h in seen and seen[h] != (ri, ci):
                    why.append("a drawn cell is split across cells of the reading")
                seen[h] = (ri, ci)
    filled = {owner[id(w)] for w in inside_frame if id(w) in owner}
    if filled - set(seen):
        why.append("a drawn cell with words is missing from the reading")
    # the text: each drawn cell's text-layer characters (spaces aside) are the
    # reading cell's, allowing a line-end hyphen either way
    for h, (ri, ci) in seen.items():
        ws = sorted((w for w in inside_frame if owner.get(id(w)) == h), key=lambda w: (round(w[3]), w[0]))
        layer = _squash("".join(w[4] for w in ws))
        got = _squash("".join(sp.text for sp in columns[ri][ci] if sp.text != "\n"))
        if got not in (layer, layer.replace("-", "")) and got.replace("-", "") != layer.replace("-", ""):
            why.append(f"cell text differs from the text layer in its drawn cell ({got[:20]!r})")
            break
    return {"ruled": True, "pass": not why, "why": why[0] if why else "",
            "cells": len(cells), "col_spread": round(worst_col, 2), "row_spread": round(worst_row, 2)}


def fit_rows(page, bbox, words, columns) -> dict:
    """The partial fit for ruled-row tables (horizontal rules, no vertical ones):
    row bands come from the drawn rules, columns from the reading's own gutters.
    Every word lies inside one band and one column with a clear gutter on both
    sides, the bands holding words match the reading's rows one to one, no
    band holds stacked entries, and each cell's characters equal the text
    layer's in its band and column. Measured apart from the grid fit; it never
    counts as a witness unless it separates as well."""
    hs, vs = _segments(page, bbox)
    if vs or len(_clusters([s[0] for s in hs])) < 3:
        return {"rows_ruled": False}
    ys = _clusters([s[0] for s in hs])
    nread = max((len(r) for r in columns), default=0)
    if nread < 2:
        return {"rows_ruled": True, "pass": False, "why": "one column"}
    # columns: the x-span of each reading column's spans
    spans_x = []
    for c in range(nread):
        xs_ = [(s.bbox[0], s.bbox[2]) for row in columns if c < len(row) for s in row[c]
               if s.text.strip() and s.text != "\n" and s.bbox and s.bbox[2] > s.bbox[0]]
        if not xs_:
            return {"rows_ruled": True, "pass": False, "why": "an empty column"}
        spans_x.append((min(a for a, _ in xs_), max(b for _, b in xs_)))
    if any(spans_x[i][1] + 3.0 > spans_x[i + 1][0] for i in range(nread - 1)):
        return {"rows_ruled": True, "pass": False, "why": "no clear gutter between columns"}
    inside = [w for w in words if w[4].strip() and ys[0] - 1 <= (w[1] + w[3]) / 2 <= ys[-1] + 1]
    cell_words: dict = {}
    for w in inside:
        yc = (w[1] + w[3]) / 2
        j = next((k for k in range(len(ys) - 1) if ys[k] <= yc <= ys[k + 1]), None)
        c = next((k for k, (a, b) in enumerate(spans_x) if a - 1 <= w[0] and w[2] <= b + 1), None)
        if j is None or c is None:
            return {"rows_ruled": True, "pass": False, "why": f"word outside the bands and columns: {w[4]!r}"}
        if w[1] < ys[j] - 1.0 or w[3] > ys[j + 1] + 1.0:
            return {"rows_ruled": True, "pass": False, "why": f"word crosses a rule: {w[4]!r}"}
        cell_words.setdefault((j, c), []).append(w)
    bands = sorted({j for j, _ in cell_words})
    if len(bands) != len(columns):
        return {"rows_ruled": True, "pass": False, "why": f"{len(bands)} ruled bands vs {len(columns)} rows"}
    for j in bands:
        per_col = [sorted({round((w[1] + w[3]) / 2) for w in ws}) for (jj, _), ws in cell_words.items() if jj == j]
        per_col = [p for p in per_col if len(p) >= 2]
        if len(per_col) >= 2 and len([y for y in per_col[0] if all(any(abs(y - z) <= 2 for z in o)
                                                                   for o in per_col[1:])]) >= 2:
            return {"rows_ruled": True, "pass": False, "why": "stacked entries inside a ruled band"}
    for ri, j in enumerate(bands):
        for c in range(nread):
            ws = sorted(cell_words.get((j, c), []), key=lambda w: (round(w[3]), w[0]))
            layer = _squash("".join(w[4] for w in ws))
            got = _squash("".join(sp.text for sp in columns[ri][c] if sp.text != "\n")) if c < len(columns[ri]) else ""
            if got not in (layer, layer.replace("-", "")) and got.replace("-", "") != layer.replace("-", ""):
                return {"rows_ruled": True, "pass": False, "why": "cell text differs from the text layer"}
    return {"rows_ruled": True, "pass": True, "why": ""}
