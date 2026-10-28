#
# Copyright (c) 2026 Rob Beeston (rob@cppalliance.org)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
#

"""WG21 poll result tables.

WG21 papers and minutes record straw polls in a fixed shape: a header line
"SF F N A SA" (Strongly For, For, Neutral, Against, Strongly Against) with
the vote counts in the line below, one count under each header. Authors draw
it in many ways - ruled, unruled, inside a coloured box, tab-aligned - and
the other table sources miss most of them (too few rules, no tags), so this
source looks for the shape itself.

A poll is recognised when a text line consists of exactly the five header
tokens in order. Rows of numbers directly below whose numbers sit under the
header columns are its counts (up to _MAX_ROWS). A suggested poll with no
counts yet is emitted with an empty vote row when one is drawn under the
header, otherwise as a header-only table. A header followed by text on
the same line ("SF F N A SA: 4 5 1 0 0") is inline prose and is left alone.
"""

import logging
import re

from .pagecache import rawdict as _rawdict
from .ruled import _chars_to_lines, _page_words, _text_lines, _word_chars
from .select import VOTE_LABELS, vote_header
from .types import TableCandidate

_log = logging.getLogger(__name__)

_HEADER = ["SF", "F", "N", "A", "SA"]
def _label_cells(lw: list) -> list[list]:
    """Group a line's words into cells: words closer than a word gap join."""
    cells: list[list] = []
    for w in lw:
        if cells and w[0] - cells[-1][-1][2] < 0.6 * (w[3] - w[1]):
            cells[-1].append(w)
        else:
            cells.append([w])
    return cells
_ZERO_WIDTH = "​‌‍﻿"
_COUNT_RE = re.compile(r"^(\d{1,3}|[-–—]{1,2})$")   # "--" under SF and SA in a consent poll
_MAX_ROWS = 3
_ROW_GAP_RATIO = 2.5      # a count row starts within this many line heights
_EMPTY_ROW_RATIO = 3.0    # rules this close below the header bound an empty vote row


def _clean(text: str) -> str:
    return text.strip(_ZERO_WIDTH + " |")


def _row_cells(words, centers, half):
    """Assign words to the nearest header column; None if any does not fit."""
    cells: list[list] = [[] for _ in centers]
    for w in words:
        xc = (w[0] + w[2]) / 2
        k = min(range(len(centers)), key=lambda i: abs(centers[i] - xc))
        if abs(centers[k] - xc) > half:
            return None
        cells[k].append(w)
    return cells


def _strip_zero_width(lines):
    for ln in lines:
        for s in ln.spans:
            s.text = "".join(c for c in s.text if c not in _ZERO_WIDTH)
        ln.spans = [s for s in ln.spans if s.text]
    return [ln for ln in lines if ln.spans]


def _split_pipes(words):
    """Pipe-delimited polls ("SF|WF| N|WA|SA"): a word holding '|' is split at
    its '|' characters into words of their own (the pipes themselves dropped)."""
    out = []
    for w in words:
        if "|" not in w[4]:
            out.append(w)
            continue
        chars = w[5] if len(w) > 5 and isinstance(w[5], list) else None
        if not chars:
            # no character boxes (page words from fitz): place parts by their share of the text
            t, n_, pos = w[4], max(len(w[4]), 1), 0
            for prt in t.split("|"):
                if prt.strip():
                    out.append((w[0] + (w[2] - w[0]) * pos / n_, w[1], w[0] + (w[2] - w[0]) * (pos + len(prt)) / n_,
                                w[3], prt.strip()))
                pos += len(prt) + 1
            continue
        part: list = []
        for k, ch in enumerate(chars + [("|", None)]):
            if ch[0] == "|":
                if part:
                    bbs = [c[1] for c in part]
                    last = k == len(chars)
                    out.append((min(b[0] for b in bbs), min(b[1] for b in bbs), max(b[2] for b in bbs),
                                max(b[3] for b in bbs), "".join(c[0] for c in part), list(part),
                                w[6] if last and len(w) > 6 else False))
                part = []
            else:
                part.append(ch)
    return out


def _header_prefix(lw):
    """The leading words that are a poll header, when the rest of the line is an
    annotation set apart from it - "(21 present)" after a gap, or a raised
    footnote mark on the last label. None when there is no such header."""
    labels = [_clean(w[4]) for w in lw]
    h = sorted(w[3] - w[1] for w in lw)[len(lw) // 2] or 8
    for k in range(len(lw) - 1, 2, -1):
        if not vote_header(labels[:k]):
            continue
        rest = lw[k:]
        if VOTE_LABELS.get(labels[k].lower()) is not None:
            continue                    # the header does not stop before a vote label
        if len(rest) == 1 and re.fullmatch(r"\d{1,2}", labels[k]) and rest[0][0] - lw[k - 1][2] <= 1.2 * h:
            return lw                   # a footnote mark after the last label stays with it ("SA 3")
        gap = rest[0][0] - lw[k - 1][2]
        raised = all((w[3] - w[1]) < 0.85 * h and w[3] < lw[k - 1][3] - 0.15 * h for w in rest)
        if gap >= 0.9 * h or raised or _clean(rest[0][4]).startswith("("):
            return lw[:k]
    return None


def _baseline_lines(words):
    """Lines by shared baseline. A note set between two lines (an outcome
    centred beside a poll's header and counts) stays a line of its own instead
    of chaining the header and the counts into one line."""
    if not words:
        return []
    hs = sorted(w[3] - w[1] for w in words)
    tol = max(1.5, 0.25 * hs[len(hs) // 2])
    out = []
    for w in sorted(words, key=lambda w: w[3]):
        if out and abs(out[-1][2][-1][3] - w[3]) <= tol:
            out[-1][2].append(w)
            out[-1][0] = min(out[-1][0], w[1])
            out[-1][1] = max(out[-1][1], w[3])
        else:
            out.append([w[1], w[3], [w]])
    return [(a, b, ws) for a, b, ws in out]


def extract_poll_tables(page, page_num: int, words_hint=None) -> list[TableCandidate]:
    """Poll result tables on one page. `words_hint` (the page's words, already
    extracted) lets a page with no vote label skip the character extraction."""
    if words_hint is not None and not any(VOTE_LABELS.get(_clean(w[4]).lower()) == -1 for w in _split_pipes(words_hint)):
        return []
    raw = _rawdict(page)
    words = [w for w in _split_pipes(_page_words(raw)) if _clean(w[4])]
    if not any(VOTE_LABELS.get(_clean(w[4]).lower()) == -1 for w in words):
        return []
    lines = _baseline_lines(words)
    out = []
    for i, (top, bot, lw) in enumerate(lines):
        lw = sorted(lw, key=lambda w: w[0])
        # one label per word ("SF F N A SA", however tightly set), else
        # words grouped into multi-word labels ("Strongly Favor ...")
        head = [[w] for w in lw]
        if not vote_header([_clean(w[4]) for w in lw]):
            head = _label_cells(lw)
            if not vote_header([" ".join(_clean(w[4]) for w in c) for c in head]):
                pre = _header_prefix(lw)
                if pre is None:
                    continue
                if pre is lw:                   # header plus a footnote mark on its last label
                    head = [[w] for w in lw[:-2]] + [[lw[-2], lw[-1]]]
                    lw = lw[:-1]
                else:
                    head = [[w] for w in pre]   # an annotation after the header is not part of the poll
                    lw = pre
        centers = [(c[0][0] + c[-1][2]) / 2 for c in head]
        half = min(b - a for a, b in zip(centers, centers[1:])) / 2
        height = bot - top
        # a raised footnote mark right after the last label belongs to it ("SA 3")
        last = head[-1][-1]
        marks = [w for _, _, l2 in lines for w in l2
                 if w not in lw and w[1] < bot and w[3] > top and len(_clean(w[4])) <= 2
                 and 0 <= w[0] - last[2] <= 1.2 * height and _clean(w[4]).isdigit()]
        if marks:
            head[-1] = head[-1] + marks[:1]
        rows = [head]
        last_bot = bot
        right = max(w[2] for w in lw) + half
        for top2, bot2, lw2 in lines[i + 1:i + 1 + _MAX_ROWS + 2]:
            if len(rows) > _MAX_ROWS:
                break
            # a line wholly right of the header's columns (an outcome note) or a
            # footnote mark taken into the header is skipped, not a row
            if all(w[0] > right for w in lw2) or all(any(w is m for m in marks) for w in lw2):
                continue
            if top2 - last_bot > _ROW_GAP_RATIO * height:
                break
            # words wholly right of the header's columns are an annotation
            # beside the poll (an outcome note), not counts
            lw2 = [w for w in lw2 if w[0] <= right]
            if not lw2 or not all(_COUNT_RE.match(_clean(w[4])) for w in lw2):
                break
            cells = _row_cells(lw2, centers, half)
            if cells is None:
                break
            rows.append(cells)
            last_bot = bot2
        table_rows = [[_strip_zero_width(_chars_to_lines(_word_chars(c), page_num)) for c in row]
                      for row in rows]
        if len(rows) == 1:
            # a suggested poll (no counts yet) still has its vote row, blank -
            # drawn or not (convention: every poll is a header and a vote row)
            table_rows.append([[] for _ in head])
        x0 = min(w[0] for w in lw) - 2
        x1 = max(w[2] for w in lw) + 2
        cand = TableCandidate("poll", table_rows, {page_num: (x0, top - 1, x1, last_bot + 1)})
        if len(rows) == 1:
            cand.flags.append("blank-row-inferred")       # by convention, not seen: no evidence
        out.append(cand)
    if out:
        _log.debug("Page %d: %d poll table(s)", page_num, len(out))
    return out
