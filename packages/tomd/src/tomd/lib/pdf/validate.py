#
# Copyright (c) 2026 Rob Beeston (rob@cppalliance.org)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
#

"""Round-trip self-verification of an extracted table against the page.

A table read by only one source has no second opinion. Instead of a second
extractor, put the extracted grid back onto the page and check that it is
consistent with where the words actually are:

  - every word in the table's area falls in exactly one cell's box
    (no cell boxes overlap, no word is outside every cell);
  - each cell's words, read in page order (top to bottom, left to right),
    spell the cell's text;
  - rows are stacked: a row's band does not overlap the next row's band;
  - columns are side by side: column bands keep their order and do not
    overlap, except a cell that is alone in its row (a title bar, a
    spanning header), which may cover several columns.

A table that passes is consistent with the page geometry. Whether that is
enough to trust it alone is measured per class before it is used (see
classify.gate_tables).
"""

import copy
import re

from .types import Section, Span

_TOL = 1.5             # points of slack for boxes that touch
_HIDDEN_GAP = 12.0     # a gap this wide (pt) inside a cell's line is a column gap
_GAP_RATIO = 1.6       # row spacing is at least this many times line leading
_ALNUM = re.compile(r"[^\W_]", re.UNICODE)


def _cell_boxes(sec: Section):
    """[[bbox or None]] per row and column, from the cell spans."""
    out = []
    for row in sec.columns:
        boxes = []
        for cell in row:
            bs = [s.bbox for s in cell if s.text.strip() and s.text != "\n"
                  and s.bbox and s.bbox[2] > s.bbox[0]]
            boxes.append((min(b[0] for b in bs), min(b[1] for b in bs),
                          max(b[2] for b in bs), max(b[3] for b in bs)) if bs else None)
        out.append(boxes)
    return out


def cell_text(cell) -> str:
    """A cell's text as tomd renders it: spans of a line joined as they are
    (they carry their own spaces: "has_degree<G>", "C++26"), lines joined
    with a space. Joining spans with spaces broke code into "has_degree < G >"
    and made correct tables fail the word-boundary check."""
    lines, cur = [], []
    for s in cell:
        if s.text == "\n":
            lines.append("".join(cur))
            cur = []
        else:
            cur.append(s.text)
    lines.append("".join(cur))
    return " ".join(l.strip() for l in lines if l.strip())


def _tokens(words: list[str]) -> list[str]:
    """Words, with a line-break hyphen joining its two halves."""
    out: list[str] = []
    for w in (w.strip() for w in words):
        if not w:
            continue
        if out and out[-1].endswith("-") and w[:1].isalpha():
            out[-1] = out[-1][:-1] + w        # "com-" "patibility" (or a kept compound)
        else:
            out.append(w)
    return [re.sub(r"-", "", t) for t in out]


def _line_ys(ws) -> list[float]:
    ys: list[float] = []
    for w in sorted(ws, key=lambda w: (w[1] + w[3]) / 2):
        y = (w[1] + w[3]) / 2
        if not ys or y - ys[-1] > _TOL * 2:
            ys.append(y)
    return ys


def _column_rights(sec) -> list[float]:
    """The right edge text reaches in each column, over all rows."""
    ncol = max(len(r) for r in sec.columns)
    out = []
    for c in range(ncol):
        xs = [s.bbox[2] for row in sec.columns if c < len(row) for s in row[c]
              if s.text.strip() and s.text != "\n" and s.bbox]
        out.append(max(xs) if xs else 0.0)
    return out


def _wraps(cell, right: float) -> bool:
    """Some line of the cell wrapped: the first word of the next line would
    not have fitted in the space left at the end of it (how text breaks)."""
    lines = []
    cur = []
    for s in cell:
        if s.text == "\n":
            if cur:
                lines.append(cur)
            cur = []
        elif s.text.strip() and s.bbox:
            cur.append(s)
    if cur:
        lines.append(cur)
    for a, b in zip(lines, lines[1:]):
        end = max(s.bbox[2] for s in a)
        first = b[0]
        text = first.text.strip()
        word = text.split()[0] if text else ""
        width = (first.bbox[2] - first.bbox[0]) * len(word) / max(len(text), 1)
        if right - end < width + 2.0:
            return True
    return False


def _code_row(row) -> bool:
    """The row's text is (nearly) all monospace: lines of code belong to one
    listing, so they are never split into rows (before/after tables)."""
    spans = [s for c in row for s in c if s.text.strip() and s.text != "\n"]
    chars = sum(len(s.text.strip()) for s in spans)
    return chars > 0 and sum(len(s.text.strip()) for s in spans if s.monospace) >= 0.8 * chars


def _gap_threshold(columns) -> float | None:
    """This table's own boundary between line leading and row spacing: the
    largest relative jump in the sorted gaps between consecutive visual
    lines of the body, or None (abstain) when the gaps form one cluster."""
    lines = sorted({(round(min(s.bbox[1] for s in ln), 1), round(max(s.bbox[3] for s in ln), 1))
                    for row in columns[1:] for cell in row for ln in _lines_of(cell)
                    if all(s.bbox for s in ln)})
    merged: list = []
    for top, bot in lines:                      # one entry per visual line
        if merged and top < merged[-1][1] - 1.0:
            merged[-1] = (min(merged[-1][0], top), max(merged[-1][1], bot))
        else:
            merged.append((top, bot))
    gaps = sorted(b[0] - a[1] for a, b in zip(merged, merged[1:]))
    if len(gaps) < 2:
        return None
    best = None
    for a, b in zip(gaps, gaps[1:]):
        ratio = b / max(a, 0.5)
        if ratio >= _GAP_RATIO and (best is None or ratio > best[0]):
            best = (ratio, (a + b) / 2)
    return best[1] if best else None


def _row_baselines(row):
    """[(y, top, {column: line index})] for the visual lines of one row, top down."""
    starts: list[list] = []
    for c, cell in enumerate(row):
        for i, ln in enumerate(_lines_of(cell)):
            y = _yc(ln)
            hit = next((b for b in starts if abs(b[0] - y) <= _TOL * 1.5), None)
            top = min(s.bbox[1] for s in ln)
            if hit:
                hit[2][c] = i
                hit[1] = min(hit[1], top)
            else:
                starts.append([y, top, {c: i}])
    return sorted(starts, key=lambda b: b[0])


def _inside(w, b) -> bool:
    xc, yc = (w[0] + w[2]) / 2, (w[1] + w[3]) / 2
    return b[0] - _TOL <= xc <= b[2] + _TOL and b[1] - _TOL <= yc <= b[3] + _TOL


def verify_layout(sec: Section, words: list) -> str:
    """"" when the grid is consistent with the page, else what failed.

    `words` are the page's words (fitz "words" tuples) in the table's area.
    """
    if not sec.columns or len(sec.columns) < 2:
        return "too-small"
    if len({ln.page_num for ln in sec.lines}) > 1:
        return "multi-page"
    boxes = _cell_boxes(sec)
    flat = [(r, c, b) for r, row in enumerate(boxes) for c, b in enumerate(row) if b]
    if not flat:
        return "no-geometry"
    # 1. every word in exactly one cell
    owner: dict = {}
    for i, w in enumerate(words):
        hits = [(r, c) for r, c, b in flat if _inside(w, b)]
        if len(hits) > 1:
            return "overlapping-cells"
        if not hits:
            return "word-outside-cells"
        owner.setdefault(hits[0], []).append(w)
    # 2. each cell's words, in page order, are its words: same letters in
    #    the same order, and the same word boundaries (a line-break hyphen
    #    may join two page words)
    for r, c, _ in flat:
        text = cell_text(sec.columns[r][c])
        ws = sorted(owner.get((r, c), []), key=lambda w: (round((w[1] + w[3]) / 2 / 3), w[0]))
        if _ALNUM.findall(" ".join(w[4] for w in ws)) != _ALNUM.findall(text):
            return "cell-order"
        if _tokens([w[4] for w in ws]) != _tokens(text.split()):
            return "word-boundaries"
    # 2b. several cells of a row, each several lines on shared baselines:
    #     those are rows the reader merged, not wrapped cells
    # rows merged inside one row: a later baseline where most columns start
    # an item (line correspondence) AND the space above it is row spacing
    # (this table's gap clusters). Both votes, or no flag.
    gap = _gap_threshold(sec.columns)
    used = {c for (r, c) in owner if r > 0}
    need = max(2, (len(used) + 1) // 2)
    for r, row in enumerate(sec.columns):
        if r == 0 or _code_row(row):
            continue
        bases = _row_baselines(row)
        for prev, cur in zip(bases, bases[1:]):
            if len(cur[2]) < need or gap is None:
                continue
            prev_bot = max(s.bbox[3] for c, i in prev[2].items() for s in _lines_of(row[c])[i])
            if cur[1] - prev_bot > gap:
                return "stacked-rows"
    # 2c. a column whose cells have a wide gap at the same x in several
    #     rows holds two columns
    for c in range(max(len(r) for r in sec.columns)):
        spans = [sp for row in sec.columns if c < len(row) for sp in row[c] if sp.text.strip()]
        if spans and sum(len(sp.text) for sp in spans if sp.monospace) >= 0.6 * sum(len(sp.text) for sp in spans):
            continue                       # code: wide gaps align comments, they are not columns
        gaps = []
        for r in range(len(sec.columns)):
            ws = owner.get((r, c), [])
            for y in _line_ys(ws):
                lw = sorted((w for w in ws if abs((w[1] + w[3]) / 2 - y) <= _TOL), key=lambda w: w[0])
                for a, b in zip(lw, lw[1:]):
                    if b[0] - a[2] >= max(_HIDDEN_GAP, 1.5 * (a[3] - a[1])):
                        gaps.append((r, (a[2] + b[0]) / 2))
        for r, x in gaps:
            # in two rows, or in the header (one label per column)
            if r == 0 or len({r2 for r2, x2 in gaps if abs(x2 - x) <= 4.0}) >= 2:
                return "hidden-column"
    # 3. rows stacked
    bands = []
    for row in boxes:
        bs = [b for b in row if b]
        if bs:
            bands.append((min(b[1] for b in bs), max(b[3] for b in bs)))
    for (a0, a1), (b0, b1) in zip(bands, bands[1:]):
        if b0 < a1 - _TOL:
            return "rows-overlap"
    # 4. columns side by side (cells alone in their row may span)
    ncol = max(len(r) for r in boxes)
    cols = []
    for c in range(ncol):
        bs = [row[c] for row in boxes if c < len(row) and row[c]
              and sum(1 for b in row if b) > 1]
        cols.append((min(b[0] for b in bs), max(b[2] for b in bs)) if bs else None)
    present = [cb for cb in cols if cb]
    for (a0, a1), (b0, b1) in zip(present, present[1:]):
        if b0 < a1 - _TOL:
            return "columns-overlap"
    return ""


# ------------------------------------------------------------- escalation
#
# A failed verification says what is wrong; each reason maps to a small set
# of targeted re-reads at the smallest level that can fix it. A re-read is
# kept only if it passes the same verification; otherwise the table stays
# as it was, flagged.

def _lines_of(cell):
    """A cell's spans split into lines (the "\n" spans separate them)."""
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


def _yc(line) -> float:
    return sum((s.bbox[1] + s.bbox[3]) / 2 for s in line) / len(line)


def _join_lines(lines, nl):
    out = []
    for i, ln in enumerate(lines):
        if i:
            out.append(nl)
        out.extend(ln)
    return out


def _with_columns(sec, columns):
    new = copy.copy(sec)
    new.metadata = dict(sec.metadata)
    new.columns = columns
    new.text = "\n".join(" | ".join("".join(s.text for s in c if s.text != "\n") for c in r)
                         for r in columns)
    return new


def _newline_span(sec):
    for row in sec.columns:
        for cell in row:
            for s in cell:
                if s.text == "\n":
                    return s
    return Span(text="\n")


def split_stacked_rows(sec, words):
    """Rows whose cells hold several entries on shared baselines become one
    row per baseline (the drawn cell grouped several entries)."""
    nl = _newline_span(sec)
    out, changed = [], False
    for row in sec.columns:
        lines = [_lines_of(c) for c in row]
        multi = [ls for ls in lines if len(ls) >= 2]
        right = _column_rights(sec)
        if len(multi) < 2 or _code_row(row) or any(_wraps(row[c], right[c]) for c in range(len(row))):
            out.append(row)              # wrapped cells and code listings are one row
            continue
        base = [_yc(ln) for ln in max(multi, key=len)]
        groups = [[[] for _ in row] for _ in base]
        for c, ls in enumerate(lines):
            for ln in ls:
                k = min(range(len(base)), key=lambda i: abs(base[i] - _yc(ln)))
                groups[k][c].append(ln)
        out += [[_join_lines(cell, nl) for cell in g] for g in groups if any(g)]
        changed = True
    return _with_columns(sec, out) if changed else None


def resegment_rows(sec, words):
    """Rebuild row boundaries where both votes agree: a new row where most
    columns start an item AND the gap above is row spacing; a continuation
    where neither holds; otherwise the boundary stays as it was. Code is
    never re-segmented (its lines belong to one listing)."""
    if any(_code_row(r) for r in sec.columns[1:]):
        return None
    gap = _gap_threshold(sec.columns)
    if gap is None:
        return None
    ncol = max(len(r) for r in sec.columns)
    used = {c for row in sec.columns[1:] for c, cell in enumerate(row) if _lines_of(cell)}
    need = max(2, (len(used) + 1) // 2)
    nl = _newline_span(sec)
    out: list = []
    prev_bot = None
    for r, row in enumerate(sec.columns[1:], start=1):
        bases = _row_baselines(row)
        for k, (y, top, idx) in enumerate(bases):
            lines = {c: _lines_of(row[c])[i] for c, i in idx.items()}
            many = len(idx) >= need
            spaced = prev_bot is None or top - prev_bot > gap
            if k == 0:
                start = not (out and not many and not spaced)      # merge only if both say continuation
            else:
                start = many and spaced                            # split only if both say new row
            if start or not out:
                out.append([[] for _ in range(ncol)])
            for c, ln in lines.items():
                out[-1][c].append(ln)
            prev_bot = max(s.bbox[3] for ln in lines.values() for s in ln)
    body = [[_join_lines(cell, nl) for cell in r] for r in out]
    if len(body) == len(sec.columns) - 1:
        return None
    header = list(sec.columns[0]) + [[] for _ in range(ncol - len(sec.columns[0]))]
    return _with_columns(sec, [header] + body)


_NUM_CELL = re.compile(r"^[\d\s.,:%+\-–—/×()<>=~]+$")


def _kind(text: str, mono: bool) -> str:
    """Coarse content type of a cell: numeric, code, label (short) or prose."""
    t = text.strip()
    if not t:
        return "empty"
    if _NUM_CELL.match(t):
        return "numeric"
    if mono:
        return "code"
    return "prose" if len(t.split()) >= 5 else "label"


def _contrasts(cells, sec) -> bool:
    """The candidate header (word tuples per column) breaks the content
    pattern of its columns: per column, its kind differs from the body's
    dominant kind, or it is bold over a non-bold body. Most filled columns
    must vote yes; a header is a description of what is under it."""
    votes = total = 0
    for c, ws in enumerate(cells):
        if not ws:
            continue
        body = [r[c] for r in sec.columns if c < len(r) and any(s.text.strip() for s in r[c])]
        if not body:
            continue
        kinds = [_kind(cell_text(b), all(s.monospace for s in b if s.text.strip())) for b in body]
        # ties broken in a fixed order: iterating a set of strings follows the per-process hash
        # seed, so the same PDF could convert differently between runs (2026-10-23, p2688r1)
        dominant = max(sorted(set(kinds)), key=kinds.count)
        head = _kind(" ".join(w[4] for w in ws), False)
        bold_body = all(s.bold for b in body for s in b if s.text.strip())
        total += 1
        votes += head != dominant or (head == "label" and dominant == "label" and not bold_body and
                                      any(len(cell_text(b).split()) > 2 for b in body) and
                                      len(" ".join(w[4] for w in ws).split()) <= 3)
    return total >= 2 and votes >= (total + 1) // 2 + (1 if total == 2 else 0)


def add_header_above(sec, words):
    """The line just above the table, aligned with its columns, is its header
    (the region started below it). `words` must include the line above."""
    above = sec.metadata.get("_above_words") or []
    if not above:
        return None
    y = max((w[1] + w[3]) / 2 for w in above)
    line = sorted((w for w in above if abs((w[1] + w[3]) / 2 - y) <= _TOL), key=lambda w: w[0])
    text = " ".join(w[4] for w in line)
    if not line or re.match(r"^(Table|Figure|Listing)\s+\d", text):
        return None                              # a caption, not a header
    if len(text.split()) >= 8:
        return None                              # a sentence: headers are labels
    gaps = [b[0] - a[2] for a, b in zip(line, line[1:])]
    if len(gaps) >= 3 and max(gaps) <= 1.8 * sorted(gaps)[len(gaps) // 2]:
        return None                              # uniform word gaps: a (justified) prose line
    first = [[(s.bbox[0], s.bbox[1], s.bbox[2], s.bbox[3], s.text) for s in c if s.text.strip()]
             for c in sec.columns[0]]
    if _contrasts(first, _with_columns(sec, sec.columns[1:])):
        return None                              # the table already has a header row
    bands = []
    for c in range(max(len(r) for r in sec.columns)):
        xs = [s.bbox for r in sec.columns if c < len(r) for s in r[c] if s.text.strip() and s.text != "\n"]
        bands.append((min(b[0] for b in xs), max(b[2] for b in xs)) if xs else None)
    cells: list[list] = [[] for _ in bands]
    for w in line:
        xc = (w[0] + w[2]) / 2
        hit = [c for c, b in enumerate(bands) if b and b[0] - 6 <= xc <= b[1] + 6]
        if len(hit) != 1:
            return None                          # does not line up with one column
        cells[hit[0]].append(w)
    if sum(1 for c in cells if c) < 2:
        return None
    if not _contrasts(cells, sec):
        return None                              # reads like the rows below: not a header
    header = []
    for c in cells:
        spans = []
        for i, w in enumerate(c):
            if i:
                spans.append(Span(text=" "))
            spans.append(Span(text=w[4], bbox=tuple(w[:4])))
        header.append(spans)
    new = _with_columns(sec, [header] + list(sec.columns))
    new.metadata["_words_with_header"] = list(words) + line
    return new


def split_hidden_column(sec, words):
    """A column whose cells have a wide gap at the same x is two columns:
    split every cell of it at that x (spans left and right of the gap)."""
    ncol = max(len(r) for r in sec.columns)
    for c in range(ncol):
        xs = []
        for row in sec.columns:
            if c >= len(row):
                continue
            for ln in _lines_of(row[c]):
                ln = sorted(ln, key=lambda s: s.bbox[0])
                for a, b in zip(ln, ln[1:]):
                    if b.bbox[0] - a.bbox[2] >= _HIDDEN_GAP:
                        xs.append((a.bbox[2] + b.bbox[0]) / 2)
        for x in xs:
            if sum(1 for y in xs if abs(y - x) <= 4.0) >= 2:
                nl = _newline_span(sec)
                out = []
                for row in sec.columns:
                    row = list(row) + [[] for _ in range(ncol - len(row))]
                    left, right = [], []
                    for ln in _lines_of(row[c]):
                        lft = [s for s in ln if (s.bbox[0] + s.bbox[2]) / 2 < x]
                        rgt = [s for s in ln if (s.bbox[0] + s.bbox[2]) / 2 >= x]
                        if lft:
                            left.append(lft)
                        if rgt:
                            right.append(rgt)
                    out.append(row[:c] + [_join_lines(left, nl), _join_lines(right, nl)] + row[c + 1:])
                return _with_columns(sec, out)
    return None


def switch_reader(sec, words):
    """Another source's reading of the same region, the first that verifies.

    The content builder reads rows and columns from word positions, the same
    information the verifier checks, so it passes by construction: it may
    replace a reading that also came from words (tomd, the rule-band reader's
    columns), never one whose rows and columns come from drawn paths or the
    structure tree (grid, tags) - that would be one witness checking itself."""
    primary = sec.metadata.get("table_source")
    shape = (len(sec.columns), max((len(r) for r in sec.columns), default=0))
    for source, columns in sec.metadata.get("alternatives", []):
        if source == "content" and primary in ("grid", "tags"):
            continue
        if source == "content" and (len(columns), max((len(r) for r in columns), default=0)) == shape:
            continue                  # same grid, other cell text: the content builder is not the better witness
                                      # of text (a cell-order failure is often the verifier's own false alarm)
        alt = _with_columns(sec, columns)
        alt.metadata["table_source"] = source
        if not verify_layout(alt, words):
            return alt
    return None


_MOVES = {
    "stacked-rows": [resegment_rows, split_stacked_rows],
    "hidden-column": [split_hidden_column],
    "overlapping-cells": [switch_reader],
    "word-outside-cells": [switch_reader],
    "cell-order": [switch_reader],
    "rows-overlap": [switch_reader],
    "columns-overlap": [switch_reader],
    "header-above": [add_header_above],
}


def escalate(sec, words, reason: str, depth: int = 2):
    """(re-read section, moves) that passes verification, or (None, [])."""
    for move in _MOVES.get(reason, []):
        new = move(sec, words)
        if new is None:
            continue
        again = verify_layout(new, new.metadata.get("_words_with_header") or words)
        if not again:
            return new, [move.__name__]
        if depth > 1 and again != reason:          # fixed one thing, try the next
            deeper, moves = escalate(new, words, again, depth - 1)
            if deeper is not None:
                return deeper, [move.__name__] + moves
    return None, []


def verify_pieces(sec, words_on) -> str:
    """A table stitched across pages: each piece against its own page's
    words (words_on(page, bbox)), then the whole by its parts. "" when every
    piece verifies, else "page N: what failed"."""
    pieces = sec.metadata.get("pieces")
    boxes = sec.metadata.get("page_bboxes") or {}
    if not pieces:
        return "multi-page"
    for page, a, b in pieces:
        sub = _with_columns(sec, sec.columns[a:b])
        sub.lines = [ln for ln in sec.lines if ln.page_num == page]
        reason = verify_layout(sub, words_on(page, boxes.get(page))) if b - a >= 2 else ""
        if reason:
            return f"page {page + 1}: {reason}"
    return ""
