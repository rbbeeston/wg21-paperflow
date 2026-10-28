#
# Copyright (c) 2026 Rob Beeston (rob@cppalliance.org)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
#

"""Table detection from ruling lines (vector drawings).

An extractor independent of the MuPDF text blocks that table.py uses: it
looks only at the lines and thin rectangles a page draws, and at character
positions to fill cells.

Two techniques:
  Grid tables: PyMuPDF's page.find_tables(strategy="lines") for tables
    ruled in both directions (Word, Google Docs, LibreOffice exports).
  Rule-band tables: LaTeX/booktabs and ReportLab tables draw only
    horizontal rules. Rules sharing an x-extent form a group; rows come
    from the bands between rules, columns from x positions where a column
    starts in most rows, plus x ranges that no word covers.

Cell text is rebuilt from the page's characters (rawdict), grouped into
Lines and Spans the same way extract.py builds them, so fonts, bold,
italic and monospace survive. Words are assigned to a cell whole, by
their starting x, so text that overruns into the next column stays in its
own cell.

Known gaps: a booktabs table split by a page break is not detected (each
part has too few rules); column boundaries are ambiguous for tables with
very few rows. Both are caught downstream by the rule checks or by
disagreement with the other extractors.
"""

import logging
import re
from collections import Counter

from .mono import classify_monospace
from .pagecache import rawdict as _rawdict
from .runctx import current
from .select import BAD_TABLE_FLAGS, CLOSED_GRID_EXEMPT, closed_exempt, sparse_mapping, table_flags
from .types import Line, Span, TableCandidate

_log = logging.getLogger(__name__)

_MUPDF_BOLD_BIT = 1 << 4
_MUPDF_ITALIC_BIT = 1 << 1

_RULE_MAX_THICK = 2.5     # a "rule" is a line or a very thin filled rect
_RULE_MIN_LEN = 40.0
_FILL_MAX_HEIGHT = 90.0   # taller filled boxes are panels, not row shading (3-line headers fit)
_RULE_JOIN_GAP = 2.0      # Word draws one segment per cell; join them
_RULE_MERGE_Y = 3.5       # booktabs double rules collapse to one
_RULE_SAME_X = 3.0
_MIN_RULES = 3            # top + mid + bottom
_CONTINUATION_TOP = 0.2   # a 2-rule fragment this near the page top may continue a table
_PER_ROW_RULES = 5        # at least this many rules: one rule per row (booktabs has 3)
_HEADER_PADDING = 1.5     # a table's shaded header box is this much taller than its text
_HEADER_ABOVE = 16.0      # height of a header line above a double rule
_COL_GAP_MIN = 1.5        # x range no word covers separates columns...
_COL_GAP_EM = 0.6         # ...if this share of a line height wide, or if
_COL_GAP_PAIRS = 3        #    this many distinct rows straddle it
_COL_START_TOL = 3.0      # word starts within this distance share a column
_COL_START_SUPPORT = 0.6  # a column start must occur in this share of rows
_LINE_Y_TOL = 3.0         # characters within this y distance share a line
_ZERO_WIDTH = frozenset("\u200b\u200c\u200d\u2060\ufeff")
_CAPTION_INDENT = 4.0     # captions start this far left of padded cell text
_CAPTION_SPACE = 3.0      # a prose band this many times taller than its text
_MAX_PROSE_ROW_LINES = 6  # more lines of plain prose than this is running text
_OVERPRINT = 1.0          # a char starting this far left of the previous one
_RAISE = 2.0              # a superscript's bottom sits this far above its neighbour's,
_RAISE_TOP = 1.0          # and its top at least this far (code text shares the line's top)
_MAX_MARK = 8             # longest raised run treated as a superscript mark


# --------------------------------------------------------------------------
# Characters -> Lines/Spans
# --------------------------------------------------------------------------


def _page_chars(raw: dict) -> list[tuple]:
    """(char, bbox, font, size, flags, color) for every character on the page."""
    out = []
    for blk in raw.get("blocks", []):
        if blk.get("type") != 0:
            continue
        for ln in blk.get("lines", []):
            for sp in ln.get("spans", []):
                for ch in sp.get("chars", []):
                    if ch.get("c"):
                        out.append((ch["c"], tuple(ch["bbox"]), sp.get("font", ""),
                                    sp.get("size", 0.0), sp.get("flags", 0),
                                    sp.get("color", 0)))
    return out


def _unrotate(raw: dict) -> dict:
    """Rotated lines (column headers set at 90 degrees) as one horizontal unit each:
    a single character carrying the whole label, at the label's centre, so the label
    lands whole in the cell it sits in (its letters, read by position, interleave
    with its neighbours': "s d a e r h T")."""
    if not any(abs(ln.get("dir", (1, 0))[0] - 1) > 0.01 for blk in raw.get("blocks", []) if blk.get("type") == 0
               for ln in blk.get("lines", [])):
        return raw
    out = {**raw, "blocks": []}
    for blk in raw.get("blocks", []):
        if blk.get("type") != 0:
            out["blocks"].append(blk)
            continue
        lines = []
        for ln in blk.get("lines", []):
            d = ln.get("dir", (1, 0))
            if abs(d[0] - 1) <= 0.01:
                lines.append(ln)
                continue
            if abs(d[0]) > 0.01:
                continue                  # slanted text: no cell content
            sps = [sp for sp in ln.get("spans", []) if sp.get("chars")]
            text = "".join(c["c"] for sp in sps for c in sp["chars"]).strip()
            if not sps or not text:
                continue
            x0, y0, x1, y1 = ln["bbox"]
            cx, cy, h = (x0 + x1) / 2, (y0 + y1) / 2, max(x1 - x0, 1.0)
            ch = {"c": " ".join(text.split()), "bbox": (cx - 0.5, cy - h / 2, cx + 0.5, cy + h / 2),
                  "origin": (cx - 0.5, cy + h / 2)}
            sp = {**sps[0], "chars": [ch], "bbox": ch["bbox"], "origin": ch["origin"]}
            lines.append({**ln, "dir": (1.0, 0.0), "bbox": ch["bbox"], "spans": [sp]})
        if lines:
            out["blocks"].append({**blk, "lines": lines})
    return out


def _page_words(raw: dict) -> list[tuple]:
    """Words from the PDF's own character runs.

    Each word is (x0, y0, x1, y1, text, chars, space_after): every character
    belongs to exactly one word even where text from two columns overprints,
    and space_after records whether the PDF put a space character after it.
    """
    words = []
    for blk in raw.get("blocks", []):
        if blk.get("type") != 0:
            continue
        for ln in blk.get("lines", []):
            cur: list[tuple] = []

            def flush(space_after):
                if cur:
                    bbs = [c[1] for c in cur]
                    words.append((min(b[0] for b in bbs), min(b[1] for b in bbs),
                                  max(b[2] for b in bbs), max(b[3] for b in bbs),
                                  "".join(c[0] for c in cur), list(cur), space_after))
                    cur.clear()

            for sp in ln.get("spans", []):
                for ch in sp.get("chars", []):
                    c = ch.get("c")
                    if not c:
                        continue
                    if c.isspace():
                        flush(True)
                        continue
                    bb = tuple(ch["bbox"])
                    if cur and bb[0] < cur[-1][1][2] - _OVERPRINT:
                        # text jumps back: another column's text drawn over
                        # this one (an overrunning identifier) - new word
                        flush(False)
                    elif cur and classify_monospace(sp.get("font", "")) != classify_monospace(cur[-1][2]):
                        # code font meets body font with no space: a code
                        # identifier running into the next column. Split;
                        # no space is inserted, so "noexcept," reads the same.
                        flush(False)
                    cur.append((c, bb, sp.get("font", ""), sp.get("size", 0.0),
                                sp.get("flags", 0), sp.get("color", 0)))
            flush(False)
    return words


def _word_chars(ws: list[tuple]) -> list[tuple]:
    """Characters of a cell's words, with the PDF's spaces between them."""
    out: list[tuple] = []
    for w in ws:
        out += w[5]
        if w[6]:   # the PDF has a space after this word; trailing ones are stripped later
            last = w[5][-1]
            out.append((" ", (last[1][2], last[1][1], last[1][2] + 0.01, last[1][3])) + last[2:])
    return out


def _merge_tall_glyph_rows(rows):
    """A glyph set larger than its line (an arrow or symbol at twice the size) has its
    box centre off the line's, so it formed a row of its own and was read before the
    line ("→ then(sender, fn) sender"). Rows whose centres each lie inside the other's
    vertical extent, and whose glyphs do not overlap horizontally, are one line."""
    if len(rows) < 2:
        return rows
    def ext(row):
        return min(c[1][1] for c in row[1]), max(c[1][3] for c in row[1])
    out = [rows[0]]
    for row in rows[1:]:
        prev = out[-1]
        (a0, a1), (b0, b1) = ext(prev), ext(row)
        ca, cb = (a0 + a1) / 2, (b0 + b1) / 2
        ink_a = [c for c in prev[1] if not c[0].isspace()]
        ink_b = [c for c in row[1] if not c[0].isspace()]
        apart = not any(min(x[1][2], y[1][2]) - max(x[1][0], y[1][0]) > 1.0 for x in ink_a for y in ink_b)
        if b0 <= ca <= b1 and a0 <= cb <= a1 and apart and min(len(ink_a), len(ink_b)) <= 3:
            prev[1].extend(row[1])
            continue
        out.append(row)
    return out


def _chars_to_lines(chars: list[tuple], page_num: int) -> list[Line]:
    """Group characters into Lines of Spans (same font run = one span).

    Superscripts (reference marks) are raised, so they would form a line of
    their own; they join the line whose height they overlap instead and stay
    after the word they follow.
    """
    chars = [c for c in chars if c[0] not in _ZERO_WIDTH]    # invisible: never cell content
    def raised(c):
        # smaller than a vertically overlapping character and shifted up
        # against it at both top and bottom: a superscript
        return any(o[3] > c[3] and min(o[1][3], c[1][3]) > max(o[1][1], c[1][1])
                   and o[1][1] - c[1][1] > _RAISE_TOP and o[1][3] - c[1][3] > _RAISE
                   for o in chars if not o[0].isspace())
    small = [c for c in chars if raised(c)]       # including the mark's own spaces
    # Reference marks are short ("[10]"); a long raised run is a line of
    # smaller text above another line, not a superscript.
    runs: list[list] = []
    for c in sorted(small, key=lambda c: (round((c[1][1] + c[1][3]) / 4), c[1][0])):
        if runs and abs((runs[-1][-1][1][1] + runs[-1][-1][1][3]) / 2 - (c[1][1] + c[1][3]) / 2) < 2 \
                and c[1][0] - runs[-1][-1][1][2] < 3:
            runs[-1].append(c)
        else:
            runs.append([c])
    small = [c for r in runs if sum(not x[0].isspace() for x in r) <= _MAX_MARK for c in r]
    normal = [c for c in chars if not any(c is x for x in small)]
    rows: list[list] = []
    for ch in sorted(normal, key=lambda c: (c[1][1] + c[1][3]) / 2):
        yc = (ch[1][1] + ch[1][3]) / 2
        if rows and yc - rows[-1][0] < _LINE_Y_TOL:
            rows[-1][1].append(ch)
        else:
            rows.append([yc, [ch]])
    for ch in small:
        def overlap(row):
            top = min(c[1][1] for c in row[1]); bot = max(c[1][3] for c in row[1])
            return min(bot, ch[1][3]) - max(top, ch[1][1])
        best = max(rows, key=overlap, default=None)
        if best is not None and overlap(best) > 0:
            best[1].append(ch)
        else:
            rows.append([(ch[1][1] + ch[1][3]) / 2, [ch]])
    rows.sort(key=lambda r: r[0])
    rows = _merge_tall_glyph_rows(rows)
    has_spaces = any(c[0] == " " for c in chars)
    lines = []
    for _, row in rows:
        # by centre, not left edge: in ligatures ("ff", "fi") a zero-width
        # glyph can start right of the next character's left edge
        row.sort(key=lambda c: (c[1][0] + c[1][2]) / 2)
        # A space belongs where there is a gap between two characters of the
        # line; a stray one (a trailing space of the line above whose box
        # overlaps this line) would split a word: "ch anges".
        ink = [c for c in row if not c[0].isspace()]
        row[:] = [c for c in row if not c[0].isspace() or any(
            a[1][2] - 1.0 <= (c[1][0] + c[1][2]) / 2 <= b[1][0] + 1.0
            and b[1][0] - a[1][2] > 0.5
            for a, b in zip(ink, ink[1:]))]
        spans: list[Span] = []
        prev = None
        for ch in row:
            c, bb, font, size, flags, color = ch
            gap = bb[0] - prev[1][2] if prev else 0.0
            # Infer a space from a gap only when the PDF encodes none of its
            # own here (kerned text otherwise gains spaces: "ch anges").
            # where the PDF does encode spaces, a gap still means a space when it
            # is word-sized (a third of the font size): LaTeX leaves some word
            # gaps as positioning only ("Recommendedpractice"); kerning never
            # reaches that width
            # (sized by the larger glyph: a symbol set at twice the size has side bearings
            # to match, "→sender" is not "→ sender")
            ref = max(size, prev[3]) if prev is not None else size
            limit = (0.25 if not has_spaces else 0.33) * max(ref, 1.0)
            space = (prev is not None and gap > limit and c != " " and prev[0] != " "
                     or
                     (not has_spaces and prev is not None and gap > 0.25 * max(ref, 1.0)
                      and c != " " and prev[0] != " "))
            same_run = (spans and prev is not None and font == prev[2]
                        and size == prev[3] and flags == prev[4] and color == prev[5])
            if same_run:
                s = spans[-1]
                s.text += (" " if space else "") + c
                s.bbox = (s.bbox[0], min(s.bbox[1], bb[1]), bb[2], max(s.bbox[3], bb[3]))
            else:
                if space and spans:
                    spans[-1].text += " "
                spans.append(Span(
                    text=c, font_name=font, font_size=size,
                    bold=bool(flags & _MUPDF_BOLD_BIT),
                    italic=bool(flags & _MUPDF_ITALIC_BIT),
                    monospace=classify_monospace(font),
                    bbox=bb, origin=(bb[0], bb[3]), color=color,
                ))
            prev = ch
        spans = [s for s in spans if s.text]
        if spans and "".join(s.text for s in spans).strip():
            x0 = min(s.bbox[0] for s in spans); x1 = max(s.bbox[2] for s in spans)
            y0 = min(s.bbox[1] for s in spans); y1 = max(s.bbox[3] for s in spans)
            lines.append(Line(spans=spans, bbox=(x0, y0, x1, y1), page_num=page_num))
    return lines


def _chars_in(chars, rect, start=None) -> list[tuple]:
    """characters whose centre lies in rect; with `start` (character -> x of its word's
    first character), placed by where the word starts instead of by their own x"""
    x0, y0, x1, y1 = rect
    if start:
        return [c for c in chars
                if x0 <= start.get((c[0], c[1]), (c[1][0] + c[1][2]) / 2) <= x1
                and y0 <= (c[1][1] + c[1][3]) / 2 <= y1]
    return [c for c in chars
            if x0 <= (c[1][0] + c[1][2]) / 2 <= x1 and y0 <= (c[1][1] + c[1][3]) / 2 <= y1]


# --------------------------------------------------------------------------
# Grid tables (ruled both ways)
# --------------------------------------------------------------------------


def _vertical_rule_count(drawings) -> int:
    n = 0
    for d in drawings:
        for it in d["items"]:
            if it[0] == "l" and abs(it[1].x - it[2].x) < 1.0 and abs(it[1].y - it[2].y) >= 8.0:
                n += 1
            elif it[0] == "re" and it[1].width <= _RULE_MAX_THICK and it[1].height >= 8.0:
                n += 1
    return n


def _vertical_spans(drawings) -> list[tuple[float, float, float, float]]:
    """Bounding boxes of groups of vertical rules that overlap in y: the
    real extent of each ruled grid (section underlines have no verticals)."""
    vs = []
    for d in drawings:
        for it in d["items"]:
            if it[0] == "l" and abs(it[1].x - it[2].x) < 1.0 and abs(it[1].y - it[2].y) >= 8.0:
                vs.append((it[1].x, min(it[1].y, it[2].y), it[1].x, max(it[1].y, it[2].y)))
            elif it[0] == "re" and it[1].width <= _RULE_MAX_THICK and it[1].height >= 8.0:
                vs.append((it[1].x0, it[1].y0, it[1].x1, it[1].y1))
    boxes: list[list[float]] = []
    for x0, y0, x1, y1 in sorted(vs, key=lambda v: v[1]):
        if boxes and y0 <= boxes[-1][3] + 2.0:
            b = boxes[-1]
            b[0], b[2], b[3] = min(b[0], x0), max(b[2], x1), max(b[3], y1)
        else:
            boxes.append([x0, y0, x1, y1])
    return [tuple(b) for b in boxes if b[2] - b[0] > _RULE_MIN_LEN]


def _segments(drawings):
    """(horizontal, vertical) drawn segments as (position, lo, hi): lines, thin
    rectangles and the edges of stroked rectangles"""
    hs, vs = [], []
    for d in drawings:
        stroked = "s" in (d.get("type") or "")
        for it in d["items"]:
            if it[0] == "l":
                a, b = it[1], it[2]
                if abs(a.y - b.y) < 1.0:
                    hs.append(((a.y + b.y) / 2, min(a.x, b.x), max(a.x, b.x)))
                elif abs(a.x - b.x) < 1.0:
                    vs.append(((a.x + b.x) / 2, min(a.y, b.y), max(a.y, b.y)))
            elif it[0] == "re":
                r = it[1]
                if r.height <= _RULE_MAX_THICK:
                    hs.append(((r.y0 + r.y1) / 2, r.x0, r.x1))
                elif r.width <= _RULE_MAX_THICK:
                    vs.append(((r.x0 + r.x1) / 2, r.y0, r.y1))
                elif stroked or d.get("fill") is not None:
                    # a stroked box, or a filled one (cells drawn as coloured boxes)
                    hs += [(r.y0, r.x0, r.x1), (r.y1, r.x0, r.x1)]
                    vs += [(r.x0, r.y0, r.y1), (r.x1, r.y0, r.y1)]
    return hs, vs


def _covered(segs, pos, lo, hi, tol=2.0) -> float:
    """share of [lo, hi] that drawn segments at pos (within tol) cover"""
    iv = sorted((max(a, lo), min(b, hi)) for p, a, b in segs if abs(p - pos) <= tol and b > lo and a < hi)
    tot, end = 0.0, lo
    for a, b in iv:
        if b > end:
            tot += b - max(a, end)
            end = b
    return tot / max(hi - lo, 1e-6)


def _closed_frame(bb, drawings) -> bool:
    """a grid drawn closed on all four sides (learned from the vision readers: a
    drawn grid is the table's structure, empty and merged cells included); a
    junk grid (a section underline joined to a table's verticals) is open"""
    hs, vs = _segments(drawings)
    x0, y0, x1, y1 = bb
    return (min(_covered(vs, x0, y0, y1), _covered(vs, x1, y0, y1)) >= 0.9
            and min(_covered(hs, y0, x0, x1), _covered(hs, y1, x0, x1)) >= 0.9)


def _bad_flags(t) -> set:
    bad = set(table_flags(t)) & BAD_TABLE_FLAGS
    if closed_exempt(t):
        bad -= CLOSED_GRID_EXEMPT
        if sparse_mapping(t):
            bad.discard("single-cell-rows")
    return bad


def drawn_spans(page, columns, spans) -> list[dict]:
    """the spans a closed grid's own lines allow: a span inferred from the text's
    position is dropped when a drawn line separates the cells it would join (the
    grid draws every cell it has; an empty drawn cell is not part of its neighbour)"""
    hs, vs = _segments(page.get_drawings())
    boxes = [[[s.bbox for s in cell] for cell in row] for row in columns]
    def rng(bs, a, b):
        return (min(x[a] for x in bs), max(x[b] for x in bs)) if bs else None
    rows_y = [rng([b for cell in row for b in cell], 1, 3) for row in boxes]
    ncol = max((len(r) for r in boxes), default=0)
    cols_x = [rng([b for row in boxes if c < len(row) for b in row[c]], 0, 2) for c in range(ncol)]
    def h_between(i, c):            # a drawn line under row i, across column c
        a, b = rows_y[i], next((rows_y[j] for j in range(i + 1, len(rows_y)) if rows_y[j]), None)
        if not a or not b or not cols_x[c]:
            return False
        xm = (cols_x[c][0] + cols_x[c][1]) / 2
        return any(a[1] - 1 <= y <= b[0] + 1 and x0 <= xm <= x1 for y, x0, x1 in hs)
    def v_between(r, j):            # a drawn line right of column j, across row r
        a, b = cols_x[j], next((cols_x[k] for k in range(j + 1, ncol) if cols_x[k]), None)
        if not a or not b or not rows_y[r]:
            return False
        ym = (rows_y[r][0] + rows_y[r][1]) / 2
        return any(a[1] - 1 <= x <= b[0] + 1 and y0 <= ym <= y1 for x, y0, y1 in vs)
    out = []
    for sp in spans:
        if sp["kind"] == "header":
            out.append(sp)            # a header's own layout (sub-headers under it) is read by its rows
            continue
        cut = any(h_between(i, sp["c"]) for i in range(sp["r"], sp["r"] + sp["rows"] - 1) if i < len(rows_y)) \
            or any(v_between(sp["r"], j) for j in range(sp["c"], sp["c"] + sp["cols"] - 1) if j < ncol and sp["r"] < len(rows_y))
        if not cut:
            out.append(sp)
    return out


def _mark_icon_cells(page, page_num, tables) -> None:
    """flag tables whose empty body cells hold images (check, cross and question
    icons): a matrix of marks the vision readers see, sparse only in the text layer"""
    if not tables:
        return
    try:
        imgs = [tuple(i["bbox"]) for i in page.get_image_info()]
    except Exception as e:  # a page whose images cannot be listed keeps its cells: recorded
        current().reader_error("icon cells", page_num, e)
        return
    imgs = [b for b in imgs if 3 <= b[2] - b[0] <= 40 and 3 <= b[3] - b[1] <= 40]
    if len(imgs) < 3:
        return
    for t in tables:
        if page_num not in t.bboxes or len(t.rows) < 2:
            continue
        ncol = max(len(r) for r in t.rows)
        cols = []
        for c in range(ncol):
            bs = [ln.bbox for r in t.rows if c < len(r) for ln in r[c] if ln.text.strip()]
            cols.append((min(b[0] for b in bs), max(b[2] for b in bs)) if bs else None)
        empty = with_icon = 0
        for r in t.rows[1:]:
            bs = [ln.bbox for cell in r for ln in cell if ln.text.strip()]
            if not bs:
                continue
            y0, y1 = min(b[1] for b in bs) - 4, max(b[3] for b in bs) + 4
            for c in range(ncol):
                if c < len(r) and any(ln.text.strip() for ln in r[c]):
                    continue
                if not cols[c]:
                    continue
                empty += 1
                x0, x1 = cols[c][0] - 4, cols[c][1] + 4
                if any(x0 <= (b[0] + b[2]) / 2 <= x1 and y0 <= (b[1] + b[3]) / 2 <= y1 for b in imgs):
                    with_icon += 1
        if empty >= 3 and with_icon >= 0.6 * empty:
            t.flags = list(t.flags) + ["icon-cells"]


def _merged_holds_columns(t, chars) -> bool:
    """a cell the grid draws as merged across columns whose text has a gap at a column
    boundary: the text of several columns read as one cell (a frame around a table and
    its notes, a slide overlay), so the grid's lines do not describe the table"""
    bounds = sorted({round(c[0], 1) for r in t.rows for c in r.cells if c} - {round(t.bbox[0], 1)})
    for r in t.rows:
        for c in r.cells:
            if not c:
                continue
            inner = [x for x in bounds if c[0] + 3 < x < c[2] - 3]
            if not inner:
                continue
            ink = sorted((ch for ch in _chars_in(chars, c) if not ch[0].isspace()),
                         key=lambda ch: (round((ch[1][1] + ch[1][3]) / 6), ch[1][0]))
            for a, b in zip(ink, ink[1:]):
                if abs((a[1][1] + a[1][3]) - (b[1][1] + b[1][3])) > 4:
                    continue
                if b[1][0] - a[1][2] >= 6 and any(a[1][2] - 3 <= x <= b[1][0] + 3 for x in inner):
                    return True
    return False


def _without_decorations(drawings, chars):
    """The page's drawings without text decorations (None when there are none): an underline or strike-through
    (inserted and deleted wording) hugs a run of characters - at their baseline or
    their middle - and spans only those characters, where a cell border runs between
    rows and meets the column rules at its ends. Read as borders, decorations add
    phantom rows and columns (p2988r12's wording tables)."""
    if not chars:
        return None
    ink = [c for c in chars if not c[0].isspace()]
    vx = [(it[1].x, min(it[1].y, it[2].y), max(it[1].y, it[2].y)) for d in drawings for it in d["items"]
          if it[0] == "l" and abs(it[1].x - it[2].x) < 1.0 and abs(it[1].y - it[2].y) >= 3]
    vx += [((it[1].x0 + it[1].x1) / 2, it[1].y0, it[1].y1) for d in drawings for it in d["items"]
           if it[0] == "re" and it[1].width <= _RULE_MAX_THICK and it[1].height >= 3]

    def decoration(y, x0, x1) -> bool:
        if x1 - x0 < 3:
            return False
        if any(abs(x - x0) <= 1.5 or abs(x - x1) <= 1.5 for x, a, b in vx if a - 1.5 <= y <= b + 1.5):
            return False                  # meets a column rule: a border
        hit = []
        for c in ink:
            cx = (c[1][0] + c[1][2]) / 2
            if not (x0 - 1 <= cx <= x1 + 1):
                continue
            top, bot = c[1][1], c[1][3]
            h = max(bot - top, 1.0)
            if top + 0.2 * h <= y <= bot - 0.2 * h or bot - 0.3 * h <= y <= bot + 0.35 * h:
                hit.append(c)
        if len(hit) < 2:
            return False
        covered = sum(c[1][2] - c[1][0] for c in hit)
        return covered >= 0.6 * (x1 - x0)

    out, dropped = [], 0
    for d in drawings:
        items = []
        for it in d["items"]:
            if it[0] == "l" and abs(it[1].y - it[2].y) < 1.0:
                if decoration((it[1].y + it[2].y) / 2, min(it[1].x, it[2].x), max(it[1].x, it[2].x)):
                    dropped += 1
                    continue
            elif it[0] == "re" and it[1].height <= 1.5 and it[1].width > it[1].height:
                if decoration((it[1].y0 + it[1].y1) / 2, it[1].x0, it[1].x1):
                    dropped += 1
                    continue
            items.append(it)
        if items:
            out.append({**d, "items": items})
    return out if dropped else None


def _tiled_cells(drawings) -> int:
    """edges shared by two filled boxes side by side: a grid drawn as coloured
    cells with no lines (slides, macOS exports)"""
    boxes = [it[1] for d in drawings if d.get("fill") is not None for it in d["items"]
             if it[0] == "re" and it[1].width > _RULE_MAX_THICK and it[1].height > _RULE_MAX_THICK]
    boxes = [b for b in boxes if b.height <= _FILL_MAX_HEIGHT * 2][:400]
    n = 0
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            if abs(a.x1 - b.x0) <= 1.0 or abs(b.x1 - a.x0) <= 1.0:
                if min(a.y1, b.y1) - max(a.y0, b.y0) >= 0.8 * min(a.height, b.height):
                    n += 1
    return n


def _grid_tables(page, page_num, chars, drawings) -> list[TableCandidate]:
    # find_tables is the costliest step of conversion; a grid needs at least
    # two vertical rules, or cells drawn as boxes side by side, so pages
    # without them are skipped.
    tiled_only = _vertical_rule_count(drawings) < 2
    if tiled_only and _tiled_cells(drawings) < 3:
        return []
    out = _grid_tables_in(page, page_num, chars, None, drawings)
    if any(_bad_flags(t) for t in out):
        # A junk grid (a section underline joined to a real table): look
        # again inside each area that vertical rules actually span.
        good = [t for t in out if not _bad_flags(t)]
        for x0, y0, x1, y1 in _vertical_spans(drawings):
            clip = (x0 - 2, y0 - 2, x1 + 2, y1 + 2)
            if any(_overlaps(clip, t.bboxes[page_num]) for t in good):
                continue
            good.extend(t for t in _grid_tables_in(page, page_num, chars, clip, drawings)
                        if not _bad_flags(t))
        out = good + [t for t in out if _bad_flags(t)]
    if tiled_only:
        # cells drawn only as coloured boxes: a grid is read where the boxes close it on
        # every side (zebra stripes beside a column of boxes do not delimit rows)
        out = [t for t in out if "closed-grid" in t.flags]
    return out


def _with_overflow(cell_chars, chars, right):
    """a cell's characters plus those that continue its lines past the table's right
    edge (same baseline, no gap): text overflowing the last column"""
    if not cell_chars:
        return cell_chars
    out = list(cell_chars)
    have = {id(c) for c in out}
    beyond = sorted((c for c in chars if c[1][0] >= right - 1 and id(c) not in have), key=lambda c: c[1][0])
    for c in beyond:
        yc = (c[1][1] + c[1][3]) / 2
        h = (c[1][3] - c[1][1]) or 8.0
        same = [d for d in out if abs((d[1][1] + d[1][3]) / 2 - yc) < 0.3 * h]
        if same and 0 <= c[1][0] - max(d[1][2] for d in same) <= 0.3 * h:
            out.append(c)
    return out


def _grid_tables_in(page, page_num, chars, clip, drawings=()) -> list[TableCandidate]:
    out = []
    # (None: no decorations on the page, find_tables reads the page's own drawings)
    paths = _without_decorations(list(drawings), chars) if drawings else None
    kw = {"paths": paths} if paths is not None else {}
    finder = page.find_tables(strategy="lines", clip=clip, **kw) if clip else page.find_tables(strategy="lines", **kw)
    # each character placed by where its word starts: a word overrunning its cell's
    # right edge (struck wording, a long identifier) stays whole in its own cell
    start = {}
    for w in _page_words(_unrotate(_rawdict(page))):
        fc = w[5][0][1]
        sx = (fc[0] + fc[2]) / 2
        for ch in w[5]:
            start[(ch[0], ch[1])] = sx
    for t in finder.tables:
        rows = []
        tx1 = t.bbox[2]
        for r in t.rows:
            row = []
            for cell in r.cells:
                cc = _chars_in(chars, cell, start) if cell else []
                if cell and abs(cell[2] - tx1) < 1.0:
                    cc = _with_overflow(cc, chars, tx1)
                row.append(_chars_to_lines(cc, page_num) if cell else [])
            rows.append(row)
        rows = _drop_empty(rows)
        if len(rows) == 1:
            cells = [c for c in t.rows[0].cells]
            visual = [_visual_lines(_chars_in(chars, c), page_num) if c else [] for c in cells]
            visual = [v for v in visual] if len(visual) == len(rows[0]) else rows[0]
            rows = _split_stacked_cells(visual)
        if len(rows) < 2 or max(len(r) for r in rows) < 2:
            continue
        closed = bool(drawings) and _closed_frame(tuple(t.bbox), drawings) and not _merged_holds_columns(t, chars)
        out.append(TableCandidate("grid", rows, {page_num: tuple(t.bbox)}, flags=["closed-grid"] if closed else []))
    return out


def _visual_lines(chars, page_num: int) -> list[Line]:
    """Lines of a cell where characters that overlap vertically share a line
    (a formula's glyphs sit on slightly different baselines): each group's
    characters get one common box, so the line builder orders them by x."""
    groups: list[list] = []
    for ch in sorted(chars, key=lambda c: c[1][1]):
        g = next((g for g in groups if min(g[1], ch[1][3]) - max(g[0], ch[1][1])
                  > 0.5 * min(g[1] - g[0], ch[1][3] - ch[1][1])), None)
        if g:
            g[0], g[1] = min(g[0], ch[1][1]), max(g[1], ch[1][3])
            g[2].append(ch)
        else:
            groups.append([ch[1][1], ch[1][3], [ch]])
    flat = [(c[0], (c[1][0], g[0], c[1][2], g[1])) + tuple(c[2:]) for g in groups for c in g[2]]
    return _chars_to_lines(flat, page_num)


def _split_stacked_cells(row):
    """A single drawn row whose filled cells each hold the same number of
    lines on shared baselines is that many rows (entries stacked in one
    box, e.g. "Complexity / O(...)" beside "Throws? / Multi-edge?"); any
    other single row stays one row."""
    filled = [c for c in row if c]
    if len(filled) < 2:
        return [row]
    k = len(filled[0])
    if k < 2 or any(len(c) != k for c in filled):
        return [row]
    def overlaps(a, b):
        return min(a.bbox[3], b.bbox[3]) - max(a.bbox[1], b.bbox[1]) > \
            0.5 * min(a.bbox[3] - a.bbox[1], b.bbox[3] - b.bbox[1])
    if not all(overlaps(a, b) for c in filled[1:] for a, b in zip(c, filled[0])):
        return [row]                     # lines not on shared baselines
    return [[[c[i]] if c else [] for c in row] for i in range(k)]


def _drop_empty(rows):
    """Remove rows and columns in which every cell is empty."""
    rows = [r for r in rows if any(r)]
    if not rows:
        return rows
    ncol = max(len(r) for r in rows)
    keep = [j for j in range(ncol) if any(j < len(r) and r[j] for r in rows)]
    return [[r[j] if j < len(r) else [] for j in keep] for r in rows]


# --------------------------------------------------------------------------
# Rule-band tables (horizontal rules only)
# --------------------------------------------------------------------------


def _horizontal_rules(drawings) -> list[tuple[float, float, float, bool]]:
    """(y, x0, x1, shaded) for every horizontal rule; shaded marks an edge of
    a filled box (header shading, zebra stripe) rather than a drawn line."""
    segs = []
    for d in drawings:
        for it in d["items"]:
            if it[0] == "l":
                a, b = it[1], it[2]
                if abs(a.y - b.y) < 1.0:
                    segs.append(((a.y + b.y) / 2, min(a.x, b.x), max(a.x, b.x), False))
            elif it[0] == "re":
                r = it[1]
                if r.height <= _RULE_MAX_THICK:
                    segs.append(((r.y0 + r.y1) / 2, r.x0, r.x1, False))
                elif d.get("fill") is not None and r.height <= _FILL_MAX_HEIGHT:
                    # a shaded header row or zebra stripe: both edges bound a row
                    segs.append((r.y0, r.x0, r.x1, True))
                    segs.append((r.y1, r.x0, r.x1, True))
    segs.sort(key=lambda s: (round(s[0]), s[1]))
    rules: list[list] = []
    for y, x0, x1, shaded in segs:
        if rules and abs(rules[-1][0] - y) < 1.0 and x0 - rules[-1][2] <= _RULE_JOIN_GAP:
            rules[-1][2] = max(rules[-1][2], x1)
            rules[-1][3] = rules[-1][3] or shaded
        else:
            rules.append([y, x0, x1, shaded])
    return sorted(tuple(r) for r in rules if r[2] - r[1] >= _RULE_MIN_LEN)


def _rule_groups(rules, min_rules: int = _MIN_RULES):
    """Group rules sharing an x-extent. Returns [(rules, header_above)].

    header_above marks the IEEE/revtex style: the header line sits above a
    doubled rule with no rule over it, and each later rule is drawn above
    its row, so the last row hangs below the last rule.
    """
    groups: list[list] = []
    doubled: dict[int, bool] = {}
    for rule in rules:
        y, x0, x1 = rule[:3]
        for gi, g in enumerate(groups):
            if abs(g[0][1] - x0) <= _RULE_SAME_X and abs(g[0][2] - x1) <= _RULE_SAME_X:
                if y - g[-1][0] > _RULE_MERGE_Y:
                    g.append(tuple(rule))
                elif len(g) == 1:
                    doubled[gi] = True
                break
        else:
            groups.append([tuple(rule)])
    return [(g, doubled.get(gi, False)) for gi, g in enumerate(groups)
            if len(g) >= (min_rules - 1 if doubled.get(gi) else min_rules)]


def _text_lines(words):
    """Cluster words into text lines by y-centre: [(top, bottom, words)]."""
    lines: list[list] = []
    for w in sorted(words, key=lambda w: (w[1] + w[3]) / 2):
        yc = (w[1] + w[3]) / 2
        if lines and yc - lines[-1][3] < 2.5:
            lines[-1][2].append(w)
            lines[-1][0] = min(lines[-1][0], w[1]); lines[-1][1] = max(lines[-1][1], w[3])
            lines[-1][3] = yc
        else:
            lines.append([w[1], w[3], [w], yc])
    return [(a, b, ws) for a, b, ws, _ in lines]


def _column_starts(row_words: list[list]) -> list[float]:
    """Column boundaries for a block of rows.

    Union of two signals: (1) gaps in the union of word extents that no
    row covers; (2) x positions where a word starts after a visible gap in
    at least _COL_START_SUPPORT of the rows - this survives a cell that
    overruns into the next column, which closes the gap in signal 1.
    Returns the sorted x of each column's left boundary (first is -inf).
    """
    # Superscripts (reference marks) sit after their text and must not
    # define columns; they are still assigned to cells by position later.
    kept = []
    for ws in row_words:
        raised = _raised(ws)
        kept.append([w for w in ws if not any(w is r for r in raised)])
    row_words = [ws for ws in kept if ws] or row_words
    words = [w for ws in row_words for w in ws]
    # A narrow x range that no row covers is a column gap only when rows
    # disagree about what sits on either side of it (distinct word pairs
    # across it); identical repeated text, or a table of one or two rows,
    # leaves coincidental gaps between ordinary words. Those gaps must be
    # wide to count.
    heights = sorted(w[3] - w[1] for w in words)
    wide = max(_COL_GAP_MIN, _COL_GAP_EM * heights[len(heights) // 2])
    ivs = sorted((w[0], w[2]) for w in words)
    merged = [list(ivs[0])]
    for a, b in ivs[1:]:
        if a - merged[-1][1] < _COL_GAP_MIN:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    seps = set()
    for i in range(len(merged) - 1):
        g0, g1 = merged[i][1], merged[i + 1][0]
        # evidence: distinct rows (by their text next to the gap) that have
        # words on both sides of it on the same line
        rows_seen = set()
        for ws in row_words:
            near = [w for w in ws if merged[i][0] - 0.5 <= w[0] and w[2] <= merged[i + 1][1] + 0.5]
            straddles = False
            for _, _, lw in _text_lines(near):
                if any(w[2] <= g0 + 0.5 for w in lw) and any(w[0] >= g1 - 0.5 for w in lw):
                    straddles = True
            if straddles:
                rows_seen.add(" ".join(w[4] for w in sorted(near, key=lambda w: (round(w[1]), w[0]))))
        if g1 - g0 >= wide or len(rows_seen) >= _COL_GAP_PAIRS:
            seps.add((g0 + g1) / 2)

    starts: Counter[int] = Counter()
    for ws in row_words:
        seen = set()
        for _, _, lw in _text_lines(ws):          # compare words within a line
            lw = sorted(lw, key=lambda w: w[0])
            for i, w in enumerate(lw):
                gap_before = w[0] - lw[i - 1][2] if i else 1e9
                size = w[3] - w[1]
                # a visible gap, or text drawn over the previous word's tail
                # (an identifier overrunning into this column)
                if gap_before > 0.9 * size or gap_before < -_OVERPRINT:
                    k = round(w[0] / _COL_START_TOL)
                    if k not in seen:
                        seen.add(k); starts[k] += 1
    # A wide gap in the header (first) row starts a column when some data
    # row also starts a word there: in short tables with overrunning cells
    # the header is often the only row whose gaps are visible.
    # Rows whose text runs across the boundary must start a word right at it
    # (an overrunning identifier with the next column drawn over it);
    # otherwise the boundary would cut through ordinary text, as it does for
    # a centred column.
    header = sorted(row_words[0], key=lambda w: w[0]) if row_words else []
    for a, b in zip(header, header[1:]):
        x = b[0]
        if b[0] - a[2] < wide:
            continue
        body = row_words[1:]
        starts_here = [any(abs(w[0] - x) <= _COL_START_TOL for w in ws) for ws in body]
        crosses = [any(w[0] < x - _COL_START_TOL and w[2] > x + _COL_START_TOL for w in ws)
                   for ws in body]
        if any(starts_here) and all(s or not c for s, c in zip(starts_here, crosses)):
            k = round(x / _COL_START_TOL)
            starts[k] = max(starts[k], len(row_words))
    left = min(w[0] for w in words)
    need = max(2, _COL_START_SUPPORT * len(row_words))
    for k, n in starts.items():
        x = k * _COL_START_TOL
        if n >= need and x - left > 2 * _COL_START_TOL:
            if not any(abs(x - s) < 4 * _COL_START_TOL for s in seps):
                seps.add(x - _COL_START_TOL)
    return [float("-inf")] + sorted(seps)


def _raised(words: list) -> list:
    """Words that are superscripts: no larger than a word they overlap
    vertically and shifted up against it at both top and bottom. (Small
    code-font text sits on the line and is not raised.)"""
    if not words:
        return []
    return [w for w in words if len(w[4]) <= _MAX_MARK and any(
        b[5][0][3] > w[5][0][3] and min(b[3], w[3]) > max(b[1], w[1])
        and b[1] - w[1] > _RAISE_TOP and b[3] - w[3] > _RAISE for b in words)]


def _is_caption_band(lw: list, cell_left: float, band_height: float = 0.0) -> bool:
    """A band whose every line starts left of where cell text starts (cells
    are padded; captions and paragraphs are not): e.g. "Bounds (3)", or a
    paragraph plus the next table's caption - text between two tables that
    share the rules' width, not a row."""
    raised = _raised(lw)
    lw = [w for w in lw if not any(w is r for r in raised)]   # raised marks form their own "line"
    lines = [sorted(ws, key=lambda w: w[0]) for _, _, ws in _text_lines(lw)]
    if all(ws[0][0] < cell_left - _CAPTION_INDENT for ws in lines):
        return True                      # starts at the margin, left of padded cells
    # Or: a short run of prose (no column-sized gap) that does not start
    # where cell text starts - a caption indented differently from cells,
    # e.g. "Scenario 4 - Two Orders Resulting in a Trade".
    def prose(ws):
        return all(b[0] - a[2] < 1.5 * (a[3] - a[1]) for a, b in zip(ws, ws[1:]))
    if not all(prose(ws) for ws in lines):
        return False
    if len(lines) > _MAX_PROSE_ROW_LINES:
        return True                      # a section of running text, not a row
    if lines[0][0][0] < cell_left - _CAPTION_INDENT:
        return True                      # a legend or note block starting at the margin
    if len(lines) > 3:
        return False
    if all(abs(ws[0][0] - cell_left) > _CAPTION_INDENT for ws in lines):
        return True
    # A prose band mostly empty space (captions sit in the gap between two
    # tables); a data row is snug around its text.
    text_h = sum(max(w[3] for w in ws) - min(w[1] for w in ws) for ws in lines)
    return band_height > _CAPTION_SPACE * text_h


def _trim_trailing_prose(bw, top, bot, cell_left):
    """Cut text after a row that starts at the margin and runs on as prose
    (the paragraph after a table whose last rule is far below)."""
    lines = _text_lines(bw)
    cut = None
    for i in range(len(lines) - 1, 0, -1):
        ws = sorted(lines[i][2], key=lambda w: w[0])
        if ws[0][0] < cell_left - _CAPTION_INDENT and all(
                b[0] - a[2] < 1.5 * (a[3] - a[1]) for a, b in zip(ws, ws[1:])):
            cut = i
        else:
            break
    if cut is None:
        return bw, bot
    new_bot = lines[cut][0] - 0.5
    return [w for w in bw if (w[1] + w[3]) / 2 < new_bot], new_bot


def _rule_band_tables(page_num, words_all, group, header_above,
                      min_rows: int = 2) -> list[TableCandidate]:
    ys = [g[0] for g in group]
    x0 = min(g[1] for g in group) - 2
    x1 = max(g[2] for g in group) + 2
    if header_above:
        step = min(b - a for a, b in zip(ys, ys[1:])) if len(ys) > 1 else 14.0
        step = min(max(step, 11.0), 16.0)
        ys = [ys[0] - _HEADER_ABOVE] + ys + [ys[-1] + step]
    in_x = [w for w in words_all if w[0] >= x0 and w[2] <= x1]
    words = [w for w in in_x if ys[0] < (w[1] + w[3]) / 2 < ys[-1]]
    if not words:
        return []

    # One rule per row: many rules, or four starting with a padded shaded
    # header box (header top/bottom, then one rule per row). Highlight strips
    # around a single line of text are not padded and do not count.
    def padded_header():
        if len(group) != _PER_ROW_RULES - 1 or not all(len(r) > 3 and r[3] for r in group[:2]):
            return False
        hw = [w for w in words if group[0][0] < (w[1] + w[3]) / 2 < group[1][0]]
        text_h = max((w[3] for w in hw), default=0) - min((w[1] for w in hw), default=0)
        return bool(hw) and group[1][0] - group[0][0] >= _HEADER_PADDING * text_h
    per_row_rules = len(ys) >= _PER_ROW_RULES or padded_header()
    band_words = [(top, bot, [w for w in words if top < (w[1] + w[3]) / 2 < bot])
                  for top, bot in zip(ys, ys[1:])]
    # where cell text usually starts: the commonest left edge of the bands
    lefts = Counter(round(min(w[0] for w in bw)) for _, _, bw in band_words if bw)
    cell_left = lefts.most_common(1)[0][0] if lefts else x0
    segments: list[list[tuple[float, float]]] = [[]]
    for top, bot, bw in band_words:
        if not bw:
            continue
        bw, bot = _trim_trailing_prose(bw, top, bot, cell_left)
        if per_row_rules:
            if _is_caption_band(bw, cell_left, bot - top):
                if segments[-1]:
                    segments.append([])     # two tables share the rules' width
                continue                    # a caption is never a row
            segments[-1].append((top, bot))
        else:
            # one row per text line; superscript marks are not lines of their own
            raised = _raised(bw)
            plain = [w for w in bw if not any(w is r for r in raised)] or bw
            segments[-1].extend((a - 1, b + 1) for a, b, _ in _text_lines(plain))
    out = []
    for bands in segments:
        t = _bands_to_table(page_num, in_x, bands, x0, x1, header_above, min_rows,
                            per_line=not per_row_rules)
        if t is not None:
            out.append(t)
    return out


def _has_column_gap(ws) -> bool:
    """A line of the row has a column-sized gap, or text drawn over text."""
    for _, _, lw in _text_lines(ws):
        lw = sorted(lw, key=lambda w: w[0])
        for a, b in zip(lw, lw[1:]):
            gap = b[0] - a[2]
            if gap >= (a[3] - a[1]) or gap < -_OVERPRINT:
                return True
    return False


def _sparse_under_header(row_words) -> bool:
    """A header row with column gaps over short entries that start at its columns (a
    "Person | Affiliation | Strengths" table whose only row is "TBD"): a sparse table, not
    prose. Learned from the vision readers, which keep such small framed tables."""
    if len(row_words) < 2 or not row_words[0] or not _has_column_gap(row_words[0]):
        return False
    hdr = sorted(row_words[0], key=lambda w: w[0])
    starts = [hdr[0][0]] + [b[0] for a, b in zip(hdr, hdr[1:]) if b[0] - a[2] >= (a[3] - a[1])]
    if len(starts) < 2:
        return False
    for ws in row_words[1:]:
        if not ws or len(ws) > 4:
            return False
        for _, _, lw in _text_lines(ws):
            first = min(lw, key=lambda w: w[0])
            if not any(abs(first[0] - s) <= _COL_START_TOL for s in starts):
                return False
    return True


def _bands_to_table(page_num, in_x, bands, x0, x1, header_above,
                    min_rows: int = 2, per_line: bool = False) -> TableCandidate | None:
    def excluded(rule):
        if bands:
            current().record.exclude("rules", page_num, (x0, bands[0][0], x1, bands[-1][1]), rule, "paths")
        return None
    if len(bands) < min_rows:
        return excluded("too few rule bands")
    row_words = [[w for w in in_x if a <= (w[1] + w[3]) / 2 <= b] for a, b in bands]
    # Prose between rules (quotations, notes) has no column gaps at all.
    sparse = False
    if sum(1 for ws in row_words if _has_column_gap(ws)) < min_rows:
        if not _sparse_under_header(row_words):
            return excluded("no column gaps between rules (prose)")
        sparse = True
    seps = _column_starts(row_words)
    if len(seps) < 2:
        return excluded("one column start")
    top = bands[0][0]

    # A header line just above the first rule, aligned with the columns,
    # belongs to the table (tables whose top rule is under the header).
    if not header_above:
        above = [w for w in in_x if top - 18.0 < (w[1] + w[3]) / 2 < top]
        if above:
            col_of = lambda w: sum(1 for s in seps if w[0] >= s) - 1
            col_x: dict[int, float] = {}
            for w in (w for ws in row_words for w in ws):
                col_x[col_of(w)] = min(col_x.get(col_of(w), w[0]), w[0])
            aligned = {col_of(w) for w in above
                       if abs(w[0] - col_x.get(col_of(w), -1e9)) <= _COL_START_TOL}
            if len(aligned) >= 2:
                top = min(w[1] for w in above) - 1
                row_words.insert(0, above)

    rows = []
    for ws in row_words:
        cells: list[list] = [[] for _ in seps]
        for w in ws:
            cells[sum(1 for s in seps if w[0] >= s) - 1].append(w)
        rows.append([_chars_to_lines(_word_chars(cw), page_num) for cw in cells])
    rows = _drop_empty(rows)
    if per_line:
        rows = _join_wrapped_lines(rows)
    if len(rows) < min_rows or max(len(r) for r in rows) < 2:
        return excluded("too few rows or columns after cleaning")
    return TableCandidate("rules", rows, {page_num: (x0, top, x1, bands[-1][1])},
                          flags=["sparse-under-header"] if sparse else [])


_CODE_BODY = 0.8          # this share of monospace body text: a before/after code pair...
_CODE_STATEMENTS = 0.3    # ...when this share of its lines has a brace or semicolon


def _join_wrapped_lines(rows):
    """Rebuild booktabs rows from text lines (no rules between body rows).

    Without rules every text line came out as a row. Two cases put lines
    back together:
      - a code body (before/after listings): the whole body is one row, one
        listing per column;
      - a wrapped cell: a line continues the row above when every cell it
        has text in continues a cell that wrapped - the line's first word
        would not have fitted in the space left on the line above (how
        LaTeX p{} columns break) - and it leaves at least one cell empty.
        A line that fills every cell is a row of its own.
    """
    if len(rows) < 3:
        return rows
    ncol = max(len(r) for r in rows)
    rows = [r + [[] for _ in range(ncol - len(r))] for r in rows]
    body = [ln for r in rows[1:] for cell in r for ln in cell]
    chars = sum(len(s.text.strip()) for ln in body for s in ln.spans)
    mono = sum(len(s.text.strip()) for ln in body for s in ln.spans if s.monospace)
    # A before/after listing is statements, not names: many lines carry a
    # brace or a semicolon. A table of monospace identifiers (function |
    # return type) is all monospace too, but its lines are separate rows.
    stmt = sum(1 for ln in body if any(ch in ln.text for ch in "{};"))
    if (chars and mono >= _CODE_BODY * chars and ncol <= 3
            and stmt >= _CODE_STATEMENTS * len(body)):
        merged = [[ln for r in rows[1:] for ln in r[c]] for c in range(ncol)]
        return [rows[0], merged]
    right = [max((ln.bbox[2] for r in rows for ln in r[c]), default=0.0) for c in range(ncol)]

    def first_word_width(ln) -> float:
        text = ln.text.strip()
        word = text.split()[0] if text else ""
        return (ln.bbox[2] - ln.bbox[0]) * len(word) / max(len(text), 1)

    out = [rows[0]]
    last = rows[0]                       # the previous text line (not the merged row)
    for r in rows[1:]:
        filled = [c for c in range(ncol) if r[c]]
        cont = bool(filled) and len(filled) < ncol and all(
            last[c] and right[c] - last[c][-1].bbox[2] < first_word_width(r[c][0]) + 2.0
            for c in filled)
        if cont:
            for c in filled:
                out[-1][c] = out[-1][c] + r[c]
        else:
            out.append([list(cell) for cell in r])
        last = r
    return out


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def _overlaps(a, b) -> bool:
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def _column_ruled_tables(page_num, chars, drawings, taken) -> list[TableCandidate]:
    """Tables drawn with column rules only (LaTeX `|c|c|` with an \\hline under the
    header, no outer frame): vertical segments stacked row by row at the same x
    positions are the column dividers, each band of segments is a row, and a
    horizontal rule across the band gives the table's width. find_tables needs
    closed cells and misses them."""
    vs = []
    hs = []
    for d in drawings:
        for it in d["items"]:
            if it[0] == "l":
                a, b = it[1], it[2]
                if abs(a.x - b.x) < 1.0 and abs(a.y - b.y) >= 6.0:
                    vs.append((a.x, min(a.y, b.y), max(a.y, b.y)))
                elif abs(a.y - b.y) < 1.0 and abs(a.x - b.x) >= 20.0:
                    hs.append((a.y, min(a.x, b.x), max(a.x, b.x)))
            elif it[0] == "re":
                r = it[1]
                if r.width <= _RULE_MAX_THICK and r.height >= 6.0:
                    vs.append(((r.x0 + r.x1) / 2, r.y0, r.y1))
                elif r.height <= _RULE_MAX_THICK and r.width >= 20.0:
                    hs.append(((r.y0 + r.y1) / 2, r.x0, r.x1))
    # bands: segments sharing their top and bottom
    bands: list[list] = []
    for x, y0, y1 in sorted(vs, key=lambda v: (round(v[1]), v[0])):
        if bands and abs(bands[-1][0] - y0) <= 1.2 and abs(bands[-1][1] - y1) <= 1.2:
            bands[-1][2].append(x)
        else:
            bands.append([y0, y1, [x]])
    for b in bands:
        b[2] = sorted(b[2])
    # tables: consecutive bands with the same dividers, touching
    groups: list[list] = []
    for b in sorted(bands, key=lambda b: b[0]):
        g = groups[-1] if groups else None
        if (g and -1.5 <= b[0] - g[-1][1] <= 2.5 and len(b[2]) == len(g[-1][2])
                and all(abs(p - q) <= 1.5 for p, q in zip(b[2], g[-1][2]))):
            g.append(b)
        else:
            groups.append([b])
    out = []
    for g in groups:
        if len(g) < 2:
            continue
        top, bot, xs = g[0][0], g[-1][1], g[0][2]
        across = [h for h in hs if top - 1.5 <= h[0] <= bot + 1.5 and h[1] < xs[0] and h[2] > xs[-1]]
        if not across:
            continue                    # no rule gives the width: leave it to the other readers
        x0, x1 = min(h[1] for h in across), max(h[2] for h in across)
        box = (x0, top, x1, bot)
        if any(_overlaps(box, t) for t in taken):
            continue
        edges = [x0] + xs + [x1]
        rows = []
        ok = True
        for b in g:
            cell_chars = [_chars_in(chars, (a, b[0], c, b[1])) for a, c in zip(edges, edges[1:])]
            row = [_chars_to_lines(cc, page_num) for cc in cell_chars]
            # the rules must mark the rows and the columns: one text line per band
            # (a band over several lines is not a row), and no cell holding a
            # column-sized gap (columns separated by space, not by rules)
            if any(len([ln for ln in cell if ln.text.strip()]) > 1 for cell in row):
                ok = False
                break
            for cc in cell_chars:
                vis = sorted((c for c in cc if c[0].strip()), key=lambda c: c[1][0])
                if vis:
                    h = sorted(c[1][3] - c[1][1] for c in vis)[len(vis) // 2] or 8
                    if any(q[1][0] - p_[1][2] >= 1.5 * h for p_, q in zip(vis, vis[1:])):
                        ok = False
            if not ok:
                break
            rows.append(row)
        if not ok:
            current().record.exclude("grid", page_num, box, "column rules do not mark the rows or columns", "paths")
            continue
        rows = [r for r in rows if any(r)]
        if len(rows) < 2 or max(len(r) for r in rows) < 2:
            continue
        current().record.nominate("grid", page_num, box, "column rules (no frame)", "paths", len(xs))
        out.append(TableCandidate("grid", rows, {page_num: box}))
    return out


def extract_ruled_tables(page, page_num: int, drawings=None) -> list[TableCandidate]:
    """All tables on one page that ruling lines reveal."""
    if drawings is None:
        drawings = page.get_drawings()
    if not any(it[0] in ("l", "re") for d in drawings for it in d["items"]):
        return []                       # nothing drawn: no ruled table
    raw = _unrotate(_rawdict(page))
    chars = _page_chars(raw)
    words = _page_words(raw)
    tables = _grid_tables(page, page_num, chars, drawings)
    tables += _column_ruled_tables(page_num, chars, drawings, [t.bboxes[page_num] for t in tables])
    # Only plausible grids claim their area: find_tables can also build a
    # junk grid from section underlines and a real table's verticals, which
    # must not hide the real table from the rule-band reader.
    for t in tables:
        bad = _bad_flags(t)
        if bad:
            current().record.exclude("grid", page_num, t.bboxes[page_num],
                                       "grid failed checks: " + ", ".join(sorted(bad)), "paths")
            # a drop is never silent: the excluded reading goes on as a rejected
            # candidate, so a table-level mark is left where no kept table covers it
            t.flags = sorted(set(t.flags) | set(table_flags(t)))
            current().excluded_grids.append(t)
    tables = [t for t in tables if not _bad_flags(t)]
    grids = [t.bboxes[page_num] for t in tables]
    # Rules that are part of a grid already found belong to it, not to a
    # rule-band table of the same width further down the page.
    rules = [r for r in _horizontal_rules(drawings)
             if not any(g[1] - 2 <= r[0] <= g[3] + 2 and r[1] < g[2] and r[2] > g[0] for g in grids)]
    for group, header_above in _rule_groups(rules):
        bb = (min(r[1] for r in group), group[0][0] - (_HEADER_ABOVE if header_above else 0),
              max(r[2] for r in group), group[-1][0])
        if any(_overlaps(bb, g) for g in grids):
            continue
        current().record.nominate("rules", page_num, bb, "rule group", "paths", len(group))
        tables.extend(_rule_band_tables(page_num, words, group, header_above))
    # The top of a table continued from the previous page: two rules near the
    # top of the page around a row or two. Kept only if select_tables can
    # stitch it to the table ending the previous page.
    for group, header_above in _rule_groups(rules, min_rules=2):
        if len(group) != 2 or header_above or group[0][0] > _CONTINUATION_TOP * page.rect.height:
            continue
        for t in _rule_band_tables(page_num, words, group, False, min_rows=1):
            if not any(_overlaps(t.bboxes[page_num], o.bboxes[page_num]) for o in tables):
                t.flags.append("continuation-fragment")
                tables.append(t)
    _mark_icon_cells(page, page_num, tables)
    if tables:
        _log.debug("Page %d: %d ruled table(s)", page_num, len(tables))
    return tables


def page_hrules(page, drawings=None) -> list[tuple[float, float, float]]:
    """Drawn horizontal separators on the page: (y, x0, x1)."""
    out = []
    for d in (page.get_drawings() if drawings is None else drawings):
        for it in d["items"]:
            if it[0] == "l" and abs(it[1].y - it[2].y) <= 1:
                out.append((it[1].y, min(it[1].x, it[2].x), max(it[1].x, it[2].x)))
            elif it[0] == "re" and it[1].height <= 2:
                r = it[1]
                out.append(((r.y0 + r.y1) / 2, r.x0, r.x1))
    return out
