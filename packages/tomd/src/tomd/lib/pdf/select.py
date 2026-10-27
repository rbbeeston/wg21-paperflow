#
# Copyright (c) 2026 Rob Beeston (rob@cppalliance.org)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
#

"""Table trust: a table is HIGH only when another kind of evidence agrees.

Every table reader proposes candidates (``TableCandidate``). A table read by
one reader alone, however plausible, is UNCERTAIN: measured on fresh WG21
papers, single-source tables carry most silent errors. A table whose cells
lose or repeat the text of its area (``conservation_error``), whose cell text
is read in an order the page contradicts, or whose text layer is damaged is
UNCERTAIN too. The reasons are kept in ``Section.metadata`` for the marks, the
prompts and the paper summary.

Today the only reader is ``table.detect_tables``, so ``trust_tables`` lowers
its tables without changing a cell. The other readers and the selection
between their readings join this module as they are ported.
"""

import logging
import re
from collections import Counter
from difflib import SequenceMatcher

from .types import Block, Confidence, Line, Section, SectionKind, TableCandidate

_log = logging.getLogger(__name__)

_CELL_AGREE = 0.85         # whitespace-free similarity for "same cell"
_SUBSET_SHARE = 0.5        # a partial reading must confirm at least this share of the rows
_NEIGHBOUR_PITCH = 1.6     # look this many row pitches above and below the table
_SEGMENT_GAP = 10.0        # spans further apart than this are separate cells
_AREA_MARGIN = 1.0         # a line centred this close outside a table's area counts as inside
_ORDER_SLACK = 1.0         # a later line starting this far left of an earlier one is out of order
_QUOTE_CHARS = 20          # characters of a line quoted in a note
_DAMAGED_SHOWN = 6         # damaged characters quoted in a note
# Phonetic extensions: not WG21 text; seen as math italics with the last hex digit dropped.
_DAMAGED_RANGE = (0x1D00, 0x1DBF)
_ALNUM = re.compile(r"[^\W_]", re.UNICODE)


def _key(s: str) -> str:
    return re.sub(r"\s+", "", s)


def _cells_agree(a: str, b: str) -> bool:
    ka, kb = _key(a), _key(b)
    if ka == kb:
        return True
    if not ka or not kb:
        return False
    return SequenceMatcher(None, ka, kb, autojunk=False).ratio() >= _CELL_AGREE


def candidates_agree(a: TableCandidate, b: TableCandidate) -> bool:
    """Same grid shape and every cell matching."""
    if a.shape != b.shape:
        return False
    ta, tb = a.text_rows(), b.text_rows()
    return all(_cells_agree(x, y)
               for ra, rb in zip(ta, tb) for x, y in zip(ra + [""] * (len(rb) - len(ra)),
                                                         rb + [""] * (len(ra) - len(rb))))


def _all_bold(row) -> bool:
    spans = [s for cell in row for ln in cell for s in ln.spans if s.text.strip()]
    return bool(spans) and all(s.bold for s in spans)


def partial_reading(primary: TableCandidate, other: TableCandidate) -> bool:
    """True when ``other`` is the text-position reading of part of a fully ruled
    table: same columns, and every one of its rows matches, cell for cell, a row
    of the ruled table in the same order. The text-position reader often stops
    early or starts late on ruled tables; a correct subset confirms the rows it
    saw rather than contradicting the rest."""
    if other.source != "tomd" or primary.source not in ("grid", "rules"):
        return False
    if other.shape[1] != primary.shape[1] or other.shape[0] > primary.shape[0]:
        return False
    rows = primary.text_rows()
    i = 0
    seen = set()
    for orow in other.text_rows():
        while i < len(rows) and not all(_cells_agree(x, y) for x, y in zip(orow, rows[i])):
            i += 1
        if i == len(rows):
            return False
        seen.add(i)
        i += 1
    # The rows the text reader did not see are unconfirmed: they must be the minority,
    # and none may look like another table's header (every cell bold): a ruled box
    # around two tables passed as one.
    if len(seen) < _SUBSET_SHARE * len(rows):
        return False
    return not any(r > 0 and r not in seen and _all_bold(primary.rows[r])
                   for r in range(len(rows)))


def candidate_from_section(sec: Section) -> TableCandidate:
    """Wrap a ``detect_tables`` section (cells are span lists) as a candidate."""
    rows = []
    for row in sec.columns:
        cells = []
        for spans in row:
            if spans:
                bbs = [s.bbox for s in spans]
                cells.append([Line(spans=list(spans), page_num=sec.page_num,
                                   bbox=(min(b[0] for b in bbs), min(b[1] for b in bbs),
                                         max(b[2] for b in bbs), max(b[3] for b in bbs)))])
            else:
                cells.append([])
        rows.append(cells)
    bboxes: dict[int, tuple] = {}
    for ln in sec.lines:
        b = bboxes.get(ln.page_num, ln.bbox)
        bboxes[ln.page_num] = (min(b[0], ln.bbox[0]), min(b[1], ln.bbox[1]),
                               max(b[2], ln.bbox[2]), max(b[3], ln.bbox[3]))
    return TableCandidate("tomd", rows, bboxes)


def conservation_error(cand: TableCandidate, blocks: list[Block]) -> str:
    """Check that the text in the table's area went into its cells exactly once.

    The area is where the cells' own lines sit on each page. Every letter and
    digit of the page lines centred in that area must appear in the cells as
    often as on the page: a deficit is text the table lost (a dropped row,
    an overprinted word), a surplus is text it duplicated. Compared as
    character counts, so line breaks, hyphenation and spacing do not matter.
    Returns "" when conserved, else a note for the prompt.
    """
    area: dict[int, list[float]] = {}
    for row in cand.rows:
        for cell in row:
            for ln in cell:
                b = area.get(ln.page_num)
                area[ln.page_num] = (list(ln.bbox) if b is None else
                                     [min(b[0], ln.bbox[0]), min(b[1], ln.bbox[1]),
                                      max(b[2], ln.bbox[2]), max(b[3], ln.bbox[3])])
    if not area:
        return ""
    page_chars: Counter[str] = Counter()
    for blk in blocks:
        r = area.get(blk.page_num)
        if r is None:
            continue
        for ln in blk.lines:
            xc, yc = (ln.bbox[0] + ln.bbox[2]) / 2, (ln.bbox[1] + ln.bbox[3]) / 2
            if (r[0] - _AREA_MARGIN <= xc <= r[2] + _AREA_MARGIN
                    and r[1] - _AREA_MARGIN <= yc <= r[3] + _AREA_MARGIN):
                page_chars.update(_ALNUM.findall(ln.text))
    if not page_chars:
        return ""                     # the area's lines are not in the block stream
    cell_chars = Counter(_ALNUM.findall(" ".join(" ".join(r) for r in cand.text_rows())))
    lost = sum((page_chars - cell_chars).values())
    extra = sum((cell_chars - page_chars).values())
    if lost or extra:
        return (f"Text conservation failed: {lost} characters on the page are not in "
                f"any cell and {extra} appear in cells more often than on the page.")
    if _aligned_neighbour_row(cand, blocks):
        return ("A row of text just above or below the table is split into the "
                "table's columns: it may be a header or row the table lost.")
    return ""


def _aligned_neighbour_row(cand: TableCandidate, blocks: list[Block]) -> bool:
    """A text row just outside the table whose pieces fall in 2+ of its columns.

    Two readers can lose the same row (a header drawn outside the tagged table,
    a row above the first rule), and then they agree on a wrong table. A
    caption is one piece; a lost row splits at the column gaps.
    """
    cols: dict[int, list[float]] = {}
    tops: list[float] = []
    for row in cand.rows:
        ys = [ln.bbox[1] for cell in row for ln in cell]
        if ys:
            tops.append(min(ys))
        for c, cell in enumerate(row):
            for ln in cell:
                b = cols.get(c)
                cols[c] = ([ln.bbox[0], ln.bbox[2]] if b is None else
                           [min(b[0], ln.bbox[0]), max(b[1], ln.bbox[2])])
    if len(cols) < 2 or len(tops) < 2 or len(cand.pages) != 1:
        return False
    page = cand.pages[0]
    tops.sort()
    pitch = sorted(b - a for a, b in zip(tops, tops[1:]))[(len(tops) - 1) // 2]
    x0 = min(v[0] for v in cols.values())
    x1 = max(v[1] for v in cols.values())
    y0 = min(ln.bbox[1] for r in cand.rows for cell in r for ln in cell)
    y1 = max(ln.bbox[3] for r in cand.rows for cell in r for ln in cell)
    bands = ((y0 - _NEIGHBOUR_PITCH * pitch, y0 - 0.5), (y1 + 0.5, y1 + _NEIGHBOUR_PITCH * pitch))
    for lo, hi in bands:
        spans = sorted((s for blk in blocks if blk.page_num == page for ln in blk.lines
                        for s in ln.spans if s.text.strip()
                        and lo <= (s.bbox[1] + s.bbox[3]) / 2 <= hi
                        and x0 - 2 <= (s.bbox[0] + s.bbox[2]) / 2 <= x1 + 2),
                       key=lambda s: s.bbox[0])
        segs: list[list[float]] = []
        for sp in spans:
            if segs and sp.bbox[0] - segs[-1][1] < _SEGMENT_GAP:
                segs[-1][1] = max(segs[-1][1], sp.bbox[2])
            else:
                segs.append([sp.bbox[0], sp.bbox[2]])
        if len(segs) < 2:
            continue
        hit = {c for a, b in segs for c, (ca, cb) in cols.items()
               if a < cb - 1 and b > ca + 1}
        if len(hit) >= 2 and all(any(a < cb - 1 and b > ca + 1 for ca, cb in cols.values())
                                 for a, b in segs):
            return True
    return False


def _order_contradiction(cand: TableCandidate) -> str:
    """A cell whose lines are read in an order the page contradicts: a line read
    after another shares its baseline band (each centre inside the other's height)
    but starts left of where the earlier one ends - one printed line read as two,
    its end first (an arrow set larger than its line, read before the text it
    follows)."""
    for row in cand.rows:
        for cell in row:
            ls = [ln for ln in cell if ln.text.strip()]
            for a, b in zip(ls, ls[1:]):
                if a.page_num != b.page_num:
                    continue
                ca, cb = (a.bbox[1] + a.bbox[3]) / 2, (b.bbox[1] + b.bbox[3]) / 2
                if (b.bbox[1] <= ca <= b.bbox[3] and a.bbox[1] <= cb <= a.bbox[3]
                        and b.bbox[0] < a.bbox[0] - _ORDER_SLACK):
                    return (f"'{a.text.strip()[:_QUOTE_CHARS]}' is read before "
                            f"'{b.text.strip()[:_QUOTE_CHARS]}' but sits to its right")
    return ""


def _damaged_text(cand: TableCandidate) -> str:
    """Characters showing that the PDF's own text layer is wrong."""
    bad = sorted({ch for row in cand.text_rows() for cell in row for ch in cell
                  if _DAMAGED_RANGE[0] <= ord(ch) <= _DAMAGED_RANGE[1]})
    return " ".join(bad[:_DAMAGED_SHOWN])


def trust_tables(table_sections: list[Section], blocks: list[Block]) -> None:
    """Set each table's confidence from the evidence, in place; no cell changes.

    ``blocks`` are the page blocks before any reader consumed them (the text the
    conservation check counts). With one reader no second kind of evidence can
    agree, so every table is UNCERTAIN ("single-source"), plus the reasons its
    own checks find. Each table's metadata gains ``table_agreement``,
    ``uncertain_reasons`` and ``table_note``.
    """
    for sec in table_sections:
        if sec.kind != SectionKind.TABLE:
            continue
        cand = candidate_from_section(sec)
        reasons = ["single-source"]
        notes = ["Only one table source produced this table."]
        lost = conservation_error(cand, blocks)
        if lost:
            reasons.append("conservation")
            notes.append(lost)
        disorder = _order_contradiction(cand)
        if disorder:
            reasons.append("glyph-order")
            notes.append(f"Text in a cell is read in an order its page positions contradict ({disorder}); "
                         "check the cell against the page.")
        damaged = _damaged_text(cand)
        if damaged:
            reasons.append("damaged")
            notes.append(
                "The PDF's text layer is damaged in this table (characters such as "
                f"{damaged} are wrong in the file itself, e.g. math italics written "
                "without their last hex digit). Read the symbols from the page image.")
        sec.confidence = Confidence.UNCERTAIN
        sec.metadata["table_agreement"] = "none"
        sec.metadata["uncertain_reasons"] = reasons
        sec.metadata["table_note"] = " ".join(notes)
        _log.debug("Table p%d %s: uncertain (%s)", sec.page_num, sec.table_source, ", ".join(reasons))
