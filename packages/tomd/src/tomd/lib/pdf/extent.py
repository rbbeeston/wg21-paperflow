#
# Copyright (c) 2026 Rob Beeston (rob@cppalliance.org)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
#

"""The extent step: where each reader's table stops, and the rows just outside it.

Runs after every reader, before selection, with the pages at hand.

Stop reason (evidence): for every candidate, at its top and bottom, the
reader's own extent rule and what lies just beyond (page edge, a drawn rule,
the gap to the next text, that text). Readers do not record why they stop;
this is the one place that does.

Rows just outside a reading (user, from the cut-short diagnosis: "Alignment
of text over the columns is a common reason"; background colour; rules that
keep separating the columns; a header placed under its columns):
  alignment   a short label row directly above (or below) the body whose
              pieces each start at, or are centred over, a body column, and
              that covers at least two columns
  dividers    the body's vertical column dividers continue through the row
              (the row is inside the drawn table even above its first
              horizontal rule)
  shading     a filled band spanning the table's width directly above or
              below the body holds the row (a header or title band)
Dividers and shading are drawn paths - the same information type as rules -
so they set extent; they are not an independent witness. A row above becomes
the first row; a label row below the body (short labels, unlike the body's
cells) is the table's header, placed first and marked as found under the
columns. Tagged and poll readings are left alone (the tag tree and the poll
vocabulary state their own extent).
"""

import logging
import re

from .content import _cell_lines, page_text, visual_lines
from .runctx import current
from .types import TableCandidate

_log = logging.getLogger(__name__)

_SKIP = ("tags", "tags-malformed", "poll")
_CAPTION = re.compile(r"^\s*(table|tab\.|figure|fig\.|listing|algorithm|example)\s*"
                      r"(([\dIVX]+([.\-][\dA-Za-z]+)*)\b|[—–:-])", re.I)
# a bracketed stable name or table label ([support.types], [tab:...]): the standard's headings and captions
_STABLE = re.compile(r"^\[(tab:[a-z][\w.:\-]*|[a-z][\w\-]*(\.[\w\-]+)+)\]$")
_VERB = re.compile(r"\b(is|are|was|were|be|been|has|have|shows?|lists?|gives?|returns?|describes?|compares?|"
                   r"summari[sz]es?|contains?|provides?|presents?|illustrates?|depicts?)\b", re.I)


def _reads_as_caption(pcs, text, x0, x1):
    """a caption separates and never joins (user): it never attaches as a header row -
    'Table N' / 'Figure N' (or Tab., Fig., Listing; a number or a dash), one piece spanning
    most of the table, sentence-like text (a verb, a full stop, eight words in one piece),
    or a bracketed stable name / table label"""
    if _CAPTION.match(text):
        return "caption label"
    if len(pcs) == 1 and pcs[0][-1][2] - pcs[0][0][0] >= 0.6 * (x1 - x0):
        return "one piece spanning the table"
    if text.rstrip().endswith(".") or any(len(p) >= 8 for p in pcs) or _VERB.search(text):
        return "sentence-like"
    if any(_STABLE.match(" ".join(w[4] for w in p).strip()) for p in pcs):
        return "stable name or table label"
    return None
_HEADING = re.compile(r"^\s*(\d+(\.\d+)*|[A-Z](\.\d+)*|[IVX]+\.)\s+\S")
_MAX_LINES = 3
_ALIGN_TOL = 4.0

EXTENT_RULE = {
    "rules": "rule bands", "grid": "cell boxes", "codepair": "code boxes",
    "content": "the region handed to the builder", "records": "the record run",
    "tomd": "the text section", "tags": "the Table element", "poll": "the vote rows",
}


class _Page:
    def __init__(self, page):
        self.page = page
        self.words, self.rotated = page_text(page)
        self.vrules, self.hrules, self.fills = [], [], []
        for d in page.get_drawings():
            fill = d.get("fill")
            for it in d["items"]:
                if it[0] == "l":
                    a, b = it[1], it[2]
                    if abs(a.x - b.x) < 1.5 and abs(a.y - b.y) > 3:
                        self.vrules.append((a.x, min(a.y, b.y), max(a.y, b.y)))
                    elif abs(a.y - b.y) < 1.5 and abs(a.x - b.x) > 10:
                        self.hrules.append((a.y, min(a.x, b.x), max(a.x, b.x)))
                elif it[0] == "re":
                    r = it[1]
                    if r.width < 2.5 and r.height > 3:
                        self.vrules.append(((r.x0 + r.x1) / 2, r.y0, r.y1))
                    elif r.height < 2.5 and r.width > 10:
                        self.hrules.append(((r.y0 + r.y1) / 2, r.x0, r.x1))
                    else:
                        if d.get("color") is not None and r.width > 4 and r.height > 4:
                            self.vrules += [(r.x0, r.y0, r.y1), (r.x1, r.y0, r.y1)]
                            self.hrules += [(r.y0, r.x0, r.x1), (r.y1, r.x0, r.x1)]
                        if (fill and d.get("fill_opacity", 1) > 0 and not all(c > 0.97 for c in fill)
                                and r.width > 4 and r.height > 4):
                            self.fills.append((r.x0, r.y0, r.x1, r.y1))
        self.fills = _merge_fills(self.fills)
        self.page_box = (page.rect.x0, page.rect.y0, page.rect.x1, page.rect.y1)


def _merge_fills(fills):
    """a box drawn as one strip per line is one box: strips with the same left and
    right edges that touch vertically are merged"""
    out = []
    for f in sorted(fills, key=lambda f: (round(f[0]), round(f[2]), f[1])):
        if out and abs(out[-1][0] - f[0]) <= 1 and abs(out[-1][2] - f[2]) <= 1 and f[1] <= out[-1][3] + 1:
            o = out[-1]
            out[-1] = (min(o[0], f[0]), o[1], max(o[2], f[2]), max(o[3], f[3]))
        else:
            out.append(f)
    return out


def _lines_of(words):
    out = []
    for w in sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0])):
        h = w[3] - w[1]
        if out and abs((out[-1][0][1] + out[-1][0][3]) / 2 - (w[1] + w[3]) / 2) < 0.5 * h:
            out[-1].append(w)
        else:
            out.append([w])
    return [sorted(ln, key=lambda w: w[0]) for ln in out]


def _pieces(line):
    h = sorted(w[3] - w[1] for w in line)[len(line) // 2] or 8
    out = [[line[0]]]
    for a, b in zip(line, line[1:]):
        if b[0] - a[2] > 0.9 * h:
            out.append([b])
        else:
            out[-1].append(b)
    return out


def _columns(cand, pg, pd=None):
    """each column's x-range: its text, widened to a filled box that holds the column's text
    (code boxes: a label is centred over the box, not over the code)"""
    cols = []
    for c in range(cand.shape[1]):
        xs = [ln.bbox for row in cand.rows if c < len(row) for ln in row[c]
              if ln.page_num == pg and ln.text.strip()]
        if not xs:
            cols.append(None)
            continue
        a, b = min(v[0] for v in xs), max(v[2] for v in xs)
        if pd is not None:
            boxes = [f for f in pd.fills if f[0] <= a + 1 and f[2] >= b - 1 and f[2] - f[0] <= 1.6 * (b - a) + 60
                     and any(f[1] <= v[1] + 1 and v[3] <= f[3] + 1 for v in xs)]
            if boxes:
                f = min(boxes, key=lambda f: f[2] - f[0])
                a, b = f[0], f[2]
        cols.append((a, b))
    # a column box must not reach into its neighbour
    for i in range(len(cols) - 1):
        if cols[i] and cols[i + 1] and cols[i][1] > cols[i + 1][0]:
            return _columns(cand, pg) if pd is not None else cols
    return cols


def _aligned(piece, cols):
    """the columns a piece sits over (start at a column, or centred over one
    or a group of columns), or None"""
    x0, x1 = piece[0][0], piece[-1][2]
    xc = (x0 + x1) / 2
    live = [(i, c) for i, c in enumerate(cols) if c]
    for i, (a, b) in live:
        if abs(x0 - a) <= _ALIGN_TOL:
            return [i]
        if a - 2 <= xc <= b + 2 and abs(xc - (a + b) / 2) <= max(6.0, 0.25 * (b - a)) and x1 - x0 <= (b - a) + 24:
            return [i]
    # a group label centred over several columns it spans
    under = [i for i, (a, b) in live if a < x1 and b > x0]
    if len(under) >= 2:
        a, b = cols[under[0]][0], cols[under[-1]][1]
        if abs(xc - (a + b) / 2) <= max(8.0, 0.15 * (b - a)):
            return under
    return None


def _kind(text):
    t = text.strip()
    if re.fullmatch(r"[-+−]?[\d.,%]+[a-zA-Z%]{0,3}", t):
        return "num"
    if re.search(r"[{};=<>]|::|->|\w\(", t):
        return "code"
    return "word"


def _full_line(pd, line):
    """every page word on the line's height (a prose line runs past the table)"""
    y = (line[0][1] + line[0][3]) / 2
    h = line[0][3] - line[0][1]
    return [w for w in pd.words if abs((w[1] + w[3]) / 2 - y) < 0.5 * h]


def _dividers_through(pd, bbox, cols, y_lo, y_hi):
    """interior vertical dividers of the body that also cover the band y_lo..y_hi"""
    live = [c for c in cols if c]
    gaps = [(a[1] - 2, b[0] + 2) for a, b in zip(live, live[1:])]
    if not gaps:
        return False
    # every column gap of the body holds a divider that also crosses the band
    return all(any(lo <= v[0] <= hi and v[1] <= y_lo + 1 and v[2] >= y_hi - 1 for v in pd.vrules)
               for lo, hi in gaps)


def _band(pd, bbox, y_lo, y_hi):
    x0, _, x1, _ = bbox
    return any(f[0] <= x0 + 0.1 * (x1 - x0) and f[2] >= x1 - 0.1 * (x1 - x0) and f[1] <= y_lo + 1 and f[3] >= y_hi - 1
               for f in pd.fills)


def _band_next_to(pd, bbox, lt, lb, edge, side, h):
    """a filled band spanning the table's width holds the line and touches the body (a rule may sit between)"""
    x0, _, x1, _ = bbox
    for f in pd.fills:
        if not (f[0] <= x0 + 0.1 * (x1 - x0) and f[2] >= x1 - 0.1 * (x1 - x0) and f[1] <= lt + 1 and f[3] >= lb - 1):
            continue
        # a header or title band holds just its label line, not a shaded block of text
        if f[3] - f[1] > 3.2 * h or any(f[1] <= (w[1] + w[3]) / 2 <= f[3] and not (lt - 1 <= w[1] and w[3] <= lb + 1)
                                        and f[0] <= w[0] <= f[2] for w in pd.words):
            continue
        if (side == "above" and edge - f[3] <= 1.2 * h) or (side == "below" and f[1] - edge <= 1.2 * h):
            return True
    return False


def _beyond(pd, bbox, side):
    x0, y0, x1, y1 = bbox
    if side == "above":
        ws = [w for w in pd.words if w[3] <= y0 + 0.5 and w[2] >= x0 and w[0] <= x1]
        nxt = max(ws, key=lambda w: w[3]) if ws else None
        gap = (y0 - nxt[3]) if nxt else None
        rule = any(y <= y0 + 1 and (nxt is None or y >= nxt[3] - 1) and a <= x0 + 10 and b >= x1 - 10 for y, a, b in pd.hrules)
    else:
        ws = [w for w in pd.words if w[1] >= y1 - 0.5 and w[2] >= x0 and w[0] <= x1]
        nxt = min(ws, key=lambda w: w[1]) if ws else None
        gap = (nxt[1] - y1) if nxt else None
        rule = any(y >= y1 - 1 and (nxt is None or y <= nxt[1] + 1) and a <= x0 + 10 and b >= x1 - 10 for y, a, b in pd.hrules)
    text = ""
    if nxt:
        text = " ".join(w[4] for w in _full_line(pd, [nxt]))[:60]
    return {"gap": round(gap, 1) if gap is not None else None, "page_edge": nxt is None, "rule": rule, "next": text}


def _rows_span(cand, pg):
    """top and bottom of the rows actually read on the page (the reader's box may be larger)"""
    ys = [ln.bbox for row in cand.rows for cell in row for ln in cell if ln.page_num == pg and ln.text.strip()]
    return (min(b[1] for b in ys), max(b[3] for b in ys)) if ys else None


def _rotated_pieces(pd, bbox, lt, lb, h):
    """rotated labels standing on the line (column labels set at 90 degrees above a grid)"""
    x0, _, x1, _ = bbox
    # a label's anchor is where its baseline starts (bottom left, for text rising to the right)
    return [[(r[0], r[3] - h, r[0] + h, r[3], r[4], False)] for r in pd.rotated
            if x0 - 4 <= r[0] <= x1 + 4 and lt - 1.5 * h <= r[3] <= lb + 1.5 * h]


def _block(pd, cand, pg, side, h, others):
    """the label lines just outside the rows read (nearest first), with the evidence that holds each"""
    bbox = cand.bboxes[pg]
    x0, y0, x1, y1 = bbox
    cols = _columns(cand, pg, pd)
    span = _rows_span(cand, pg)
    if span is None:
        return [], cols
    top, bot = span
    reach = (_MAX_LINES + 1) * 1.6 * h + 3 * h
    if side == "above":
        ws = [w for w in pd.words if w[3] <= top + 1 and w[1] >= top - reach and w[2] >= x0 - 12 and w[0] <= x1 + 12]
        lines = sorted(_lines_of(ws), key=lambda ln: -ln[0][3])
    else:
        ws = [w for w in pd.words if w[1] >= bot - 1 and w[3] <= bot + reach and w[2] >= x0 - 12 and w[0] <= x1 + 12]
        lines = sorted(_lines_of(ws), key=lambda ln: ln[0][1])
    out = []
    edge = top if side == "above" else bot
    rules_crossed = 0
    left0 = cols[0][0] if cols and cols[0] else x0
    nrows = sum(1 for row in cand.rows if any(ln.page_num == pg for cell in row for ln in cell))
    inner_rules = sum(1 for y, a, b in pd.hrules if top + 1 < y < bot - 1 and a <= left0 + 6 and b >= x1 - 0.2 * (x1 - x0))
    rule_per_row = nrows >= 2 and inner_rules >= max(1, nrows - 2)    # rules between the body's rows: crossing one is usual
    def stop(why, ln):
        _log.debug("extent stop %s p%d %s %s: %s | %s", cand.source, pg, side,
                   [round(v) for v in bbox], why, " ".join(w[4] for w in ln)[:60])
    for ln in lines[:_MAX_LINES]:
        lt, lb = min(w[1] for w in ln), max(w[3] for w in ln)
        gap = (edge - lb) if side == "above" else (lt - edge)
        band = _band_next_to(pd, bbox, lt, lb, edge, side, h)
        lim = (3.5 * h + 2) if band else (2.2 * h + 2 if not out else 1.2 * h + 1)
        if gap > lim:
            stop(f"gap {gap:.1f} > {lim:.1f}", ln)
            break
        if any(o[0] - 2 <= w[0] and w[2] <= o[2] + 2 and o[1] - 2 <= w[1] and w[3] <= o[3] + 2
               for o in others for w in ln):
            stop("inside another table", ln)
            break
        full = _full_line(pd, ln)
        cols_ = cols
        wide = [w for w in full if w[0] < x0 - 12 or w[2] > x1 + 12]
        if wide:
            # a prose line runs past the table - unless the line is the table's own labels,
            # each over a column, running a little past the body's text
            al0 = [_aligned(p, cols_) for p in _pieces(sorted(full, key=lambda w: w[0]))]
            if not (all(a is not None for a in al0) and len({i for a in al0 for i in a}) >= 2
                    and all(w[0] >= x0 - 60 and w[2] <= x1 + 60 for w in full)):
                stop("prose", ln)
                break
            ln = sorted(full, key=lambda w: w[0])
            lt, lb = min(w[1] for w in ln), max(w[3] for w in ln)
        text = " ".join(w[4] for w in ln)
        cap = _reads_as_caption(_pieces(ln), text, x0, x1)
        if cap:
            stop("reads as a caption: " + cap, ln)
            break
        if _HEADING.match(text) or (lb - lt) > 1.35 * h:
            stop("caption, heading or larger type", ln)
            break
        ys = (min(lt, edge), max(lb, edge))
        # a rule across the table (a group rule under some columns only does not close it)
        left = cols[0][0] if cols and cols[0] else x0
        crossed = any(ys[0] + 0.5 < y < ys[1] - 0.5 and a <= left + 6 and b >= x1 - 0.2 * (x1 - x0)
                      for y, a, b in pd.hrules)
        dividers = _dividers_through(pd, bbox, cols, lt, lb)
        pcs = _pieces(ln)
        rot = _rotated_pieces(pd, bbox, lt, lb, h) if side == "above" else []
        al = [_aligned(p, cols) for p in pcs + rot]
        live_n = sum(1 for c in cols if c)
        covered = {i for a in al if a for i in a}
        # alignment alone: labels over at least half the columns, not a sentence end, not code
        # (a single label spanning the table is a title or caption unless something drawn holds it)
        aligned = (len(pcs) + len(rot) >= 2 and all(a is not None for a in al) and len(covered) >= max(2, (live_n + 1) // 2)
                   and not text.rstrip().endswith((".", ":", ";"))
                   and not any(_kind(" ".join(w[4] for w in p_)) == "code" for p_ in pcs))
        short = all(len(p) <= 8 for p in pcs) and not (text.rstrip().endswith(".") and len(ln) > 4)
        if not short:
            stop("not short labels", ln)
            break
        if crossed:
            rules_crossed += 1
            # a header rule between label and body is usual; more than one rule, or a rule
            # with nothing aligned or drawn through it, closes the table
            if (rules_crossed > 1 and not rule_per_row) or not (aligned or dividers or band):
                stop("rule between", ln)
                break
        why = [k for k, v in (("alignment", aligned), ("dividers", dividers), ("shading", band)) if v]
        if not why:
            stop(f"not aligned {al}", ln)
            break
        if not aligned and any(w[0] < x0 - 4 or w[2] > x1 + 4 for w in ln):
            stop("outside the columns", ln)
            break
        out.append((ln + [w for p in rot for w in p], why + (["ruled-off"] if crossed else [])))
        edge = lt if side == "above" else lb
    return out, cols


def _row_from(lines, cols, pg):
    live = [i for i, c in enumerate(cols) if c]
    cells: list[list] = [[] for _ in cols]
    for ln in lines:
        hor = [w for w in ln if w[3] - w[1] <= 1.6 * (w[2] - w[0]) or len(w[4]) <= 1]
        rot = [w for w in ln if w not in hor]
        pieces = []
        for p in _pieces(sorted(hor, key=lambda w: w[0])):
            a = _aligned(p, cols)
            over = [i for i in live if cols[i][0] - 2 < p[-1][2] and p[0][0] < cols[i][1] + 2]
            if a is not None and len(a) == 1 and len(over) > 1:
                pieces += [[w] for w in p]          # a piece running across a column boundary: by word
            else:
                pieces.append(p)
        for p in pieces + [[w] for w in rot]:
            a = _aligned(p, cols)
            if a is None:
                xc = (p[0][0] + p[-1][2]) / 2
                a = [min(live, key=lambda i: abs((cols[i][0] + cols[i][1]) / 2 - xc))]
            cells[a[0]] += p
    return [_cell_lines(visual_lines(c), pg) if c else [] for c in cells]


def _overlaps(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    return ix * iy > 0.3 * min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))


def _row_height(cand, pg):
    hs = sorted(ln.bbox[3] - ln.bbox[1] for row in cand.rows for cell in row for ln in cell
                if ln.page_num == pg and ln.text.strip())
    return hs[len(hs) // 2] if hs else 10.0


def extend(cands: list[TableCandidate], pages: dict) -> None:
    rec = current().record
    cache: dict = {}

    def pdata(pg):
        if pg not in cache:
            cache[pg] = _Page(pages[pg])
        return cache[pg]
    for cand in cands:
        if not cand.rows or not cand.bboxes:
            continue
        for side, pg in (("above", cand.pages[0]), ("below", cand.pages[-1])):
            if pg not in pages:
                continue
            pd = pdata(pg)
            rec.feature(cand.source, pg, cand.bboxes[pg], "stop " + ("top" if side == "above" else "bottom"), "record",
                        {"rule": EXTENT_RULE.get(cand.source, cand.source), **_beyond(pd, cand.bboxes[pg], side)})
            if cand.source in _SKIP or cand.shape[1] < 2 or getattr(cand, "pieces", None):
                continue
            h = _row_height(cand, pg)
            others = [o.bboxes[pg] for o in cands if o is not cand and pg in o.bboxes
                      and not _overlaps(o.bboxes[pg], cand.bboxes[pg])]
            block, cols = _block(pd, cand, pg, side, h, others)
            if not block or sum(1 for c in cols if c) < 2:
                continue
            lines = [ln for ln, _ in block]
            why = sorted({k for _, w in block for k in w} - {"ruled-off"})
            if side == "below":
                # only a label row: short labels unlike the body's cells
                kinds = {_kind(" ".join(w[4] for w in p)) for ln in lines for p in _pieces(ln)}
                body = {_kind(c) for r in cand.text_rows()[-3:] for c in r if c}
                drawn = "dividers" in why or "shading" in why
                if not drawn and (kinds - {"word"} or "word" in body and "code" not in body
                                  or any(len(p) > 4 for ln in lines for p in _pieces(ln)) or len(lines) > 1):
                    continue
            # lines a rule separates are rows of their own; lines without one are one wrapped row
            groups: list[list] = []
            for k, (ln, w_) in enumerate(block):
                if k == 0 or "ruled-off" in w_:
                    groups.append([ln])
                else:
                    groups[-1].append(ln)
            if side == "above":
                groups.reverse()
            new_rows = [_row_from(sorted(g, key=lambda ln: ln[0][1]), cols, pg) for g in groups]
            new_rows = [r for r in new_rows if any(r)]
            if not new_rows:
                continue
            row = new_rows[0]
            x0, y0, x1, y1 = cand.bboxes[pg]
            ys = [w[1] for ln in lines for w in ln] + [w[3] for ln in lines for w in ln]
            if side == "above":
                cand.rows[0:0] = new_rows
                cand.bboxes[pg] = (x0, min(ys), x1, y1)
                cand.flags.append("extent:row-above")
            elif "dividers" in why or "shading" in why:
                cand.rows.extend(new_rows)               # inside the drawn table: body rows
                cand.bboxes[pg] = (x0, y0, x1, max(ys))
                cand.flags.append("extent:row-below")
            else:
                cand.rows[0:0] = new_rows                # a label row under the columns: the header
                cand.bboxes[pg] = (x0, y0, x1, max(ys))
                cand.flags.append("extent:header-below")
            rec.feature(cand.source, pg, cand.bboxes[pg], "row " + side + " attached", "paths" if "alignment" not in why else "words",
                        {"why": why, "rows": len(new_rows),
                         "text": " | ".join(" ".join(ln.text for ln in c) for c in row)[:80]})
