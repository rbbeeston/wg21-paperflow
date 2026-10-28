#
# Copyright (c) 2026 Rob Beeston (rob@cppalliance.org)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
#

"""Full-width rows in drawn tables: titles and spanning rows read as spans.

A boxed table often has rows that run across every column: a title over the
table ("[comma.value-category]", set right-aligned), a link or an
explanation under the code. The page shows it directly: the internal vertical
rules that separate the columns elsewhere do not cross that row. A reader
that follows the structure tree or the cell grid puts the row's text in
whichever column it happens to start in; under the span convention a cell
spanning several columns holds its text in the first column, with empty
cells after it.

So: in a table with internal vertical rules, a row that none of them
crosses and that has exactly one non-empty cell is a full-width row; its
text moves to the first column and the row is recorded in the metadata
(full_width_rows: title for the first row, data otherwise). Tables without
internal rules are left alone - no rule is not evidence of a span.
"""
_MIN_RULE = 4.0       # points: a vertical segment at least this tall is a rule


def _vertical_rules(page, bbox) -> list[tuple[float, float, float]]:
    """(x, y0, y1) of vertical rules inside the table's box."""
    x0, y0, x1, y1 = bbox
    out = []
    for d in page.get_drawings():
        for item in d.get("items", []):
            if item[0] == "l":
                a, b = item[1], item[2]
                if abs(a.x - b.x) <= 0.8 and abs(a.y - b.y) >= _MIN_RULE:
                    out.append((a.x, min(a.y, b.y), max(a.y, b.y)))
            elif item[0] == "re":
                r = item[1]
                if r.width <= 1.5 and r.height >= _MIN_RULE:
                    out.append(((r.x0 + r.x1) / 2, r.y0, r.y1))
    return [(x, a, b) for x, a, b in out if x0 + 3 < x < x1 - 3 and b > y0 - 2 and a < y1 + 2]


def _row_band(row):
    ys = [s.bbox for cell in row for s in cell if s.text.strip() and s.text != "\n"
          and s.bbox and s.bbox[3] > s.bbox[1]]
    return (min(b[1] for b in ys), max(b[3] for b in ys)) if ys else None


def full_width_rows(columns, page, bbox) -> list[int]:
    rules = _vertical_rules(page, bbox)
    if not rules or not columns or max(len(r) for r in columns) < 2:
        return []
    out = []
    for i, row in enumerate(columns):
        filled = [c for c in row if any(s.text.strip() for s in c if s.text != "\n")]
        band = _row_band(row)
        if len(filled) != 1 or band is None:
            continue
        lo, hi = band
        if not any(a < hi - 1 and b > lo + 1 for _, a, b in rules):
            out.append(i)
    return out


def apply(sec, page, bbox) -> list[int]:
    """Move each full-width row's text to its first cell; record the spans."""
    rows = full_width_rows(sec.columns, page, bbox)
    if not rows:
        return []
    ncol = max(len(r) for r in sec.columns)
    for i in rows:
        row = sec.columns[i]
        cell = next(c for c in row if any(s.text.strip() for s in c if s.text != "\n"))
        sec.columns[i] = [cell] + [[] for _ in range(ncol - 1)]
    # recorded apart from "spans" (the emitter would fill or join span cells)
    sec.metadata["full_width_rows"] = [{"r": i, "cols": ncol, "kind": "title" if i == 0 else "data"} for i in rows]
    sec.text = "\n".join(" | ".join("".join(s.text for s in c if s.text != "\n") for c in r) for r in sec.columns)
    return rows
