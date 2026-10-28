#
# Copyright (c) 2026 Rob Beeston (rob@cppalliance.org)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
#

"""Tables inside figures: label them with the figure they belong to.

Convention (decided by a person): small tables drawn inside a figure are converted
as tables, labelled with the figure they belong to, e.g. "Figure 4(a)". The
label line goes before the table and is taken from the sub-caption under the
table ("(a) Table of actors.") and the figure caption below the figure
("Figure 4: ...").

A table belongs to a figure when a figure caption lies below it on the same
page and nothing between them is ordinary prose (a wide text block that is
not a sub-caption). A table with its own "Table N" caption close by is a
table in its own right, never labelled.
"""
import re

_FIGURE = re.compile(r"^\s*(?:Figure|Fig\.?)\s*(\d+(?:\.\d+)*[A-Za-z]?)\s*[:.\u2014\u2013]\s*(.*)", re.S)
_SUB = re.compile(r"^\s*\(([a-z])\)\s*(.*)", re.S)
_TABLE = re.compile(r"^\s*(?:Table|Tab\.)\s*\d", re.I)
_REACH = 300.0       # points: how far below the table a figure caption may sit
_SUB_GAP = 40.0      # points: a sub-caption sits just under its table


def _blocks(page):
    out = []
    for b in page.get_text("dict")["blocks"]:
        if b.get("type", 0) != 0:
            continue
        text = " ".join("".join(s["text"] for s in ln["spans"]).strip() for ln in b["lines"]).strip()
        text = re.sub(r"(\w)- (\w)", r"\1\2", text)          # words split at a line end
        if text:
            out.append((tuple(b["bbox"]), text))
    return out


def figure_label(blocks, bbox, text_width: float) -> str | None:
    """blocks: (bbox, text) of the page's text blocks; bbox: the table's box."""
    x0, y0, x1, y1 = bbox
    near = [t for b, t in blocks if (y0 - 36 <= b[3] <= y0 + 2 or y1 - 2 <= b[1] <= y1 + 36)
            and min(b[2], x1 + 40) > max(b[0], x0 - 40)]
    if any(_TABLE.match(t) for t in near):
        return None
    caps = sorted((b, t) for b, t in blocks if _FIGURE.match(t) and y1 - 2 <= b[1] <= y1 + _REACH)
    if not caps:
        return None
    cap_box, cap_text = min(caps, key=lambda bt: bt[0][1])
    # nothing between the table and the caption may be prose
    for b, t in blocks:
        if b[1] >= y1 - 2 and b[3] <= cap_box[1] + 2 and (b[2] - b[0]) >= 0.75 * text_width \
                and not _SUB.match(t) and not _FIGURE.match(t):
            return None
    num, rest = _FIGURE.match(cap_text).groups()
    subs = [(b, t) for b, t in blocks if _SUB.match(t) and y1 - 2 <= b[1] <= y1 + _SUB_GAP
            and min(b[2], x1) > max(b[0], x0)]
    if len({_SUB.match(t).group(1) for _, t in subs}) == 1:
        # one sub-caption under the table: the table is that sub-figure; a table
        # spanning several sub-figures (a code comparison) is the whole figure
        b, t = min(subs, key=lambda bt: bt[0][1])
        letter, desc = _SUB.match(t).groups()
        return f"Figure {num}({letter}): {desc.strip()}"
    return f"Figure {num}: {rest.strip()}"


def label_figure_tables(doc, table_sections) -> int:
    """Set metadata["figure_label"] on single-page tables drawn inside a figure."""
    cache: dict = {}
    n = 0
    for sec in table_sections:
        if sec.metadata.get("page_bboxes") or not sec.metadata.get("region_bbox"):
            continue                       # continued across pages, or no located region
        pg, bbox = sec.metadata["region_bbox"]
        if pg not in cache:
            page = doc[pg]
            blocks = _blocks(page)
            wide = sorted(b[2] - b[0] for b, _ in blocks)
            cache[pg] = (blocks, wide[-1 - len(wide) // 10] if wide else page.rect.width)
        blocks, text_width = cache[pg]
        label = figure_label(blocks, bbox, text_width)
        if label:
            sec.metadata["figure_label"] = label
            n += 1
    return n
