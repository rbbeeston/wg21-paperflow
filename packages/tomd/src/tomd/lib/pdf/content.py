#
# Copyright (c) 2026 Rob Beeston (rob@cppalliance.org)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
#

"""One content-first row/column builder for every table class.

The layout class only locates the region; inside it, rows and columns come
from the words themselves, top down:

  lines    words sharing a baseline (vertical overlap) form a visual line
  pieces   words in a line closer than a word gap form a piece (a phrase)
  columns  gutters: x ranges that (almost) no piece crosses, over all lines;
           columns are the spans between gutters that hold pieces. A piece
           crossing a gutter in at most _SPAN_LINES lines is a spanning cell
           (a header over several columns), not evidence against the gutter.
  rows     a line starts a new row when the vertical gap above it is a row
           gap (the region's own natural break between line leading and row
           spacing), or - when gaps do not separate rows (LaTeX booktabs,
           p{} wraps with row spacing equal to leading) - when it has text in
           the key column (the leftmost column filled in most rows) and the
           line above was not a lone wrap of that column. A line that fills
           only some columns, continuing cells from above, joins the row
           above (wrap continuation).
  cells    the pieces of each row and column, joined in reading order.

Every decision is recorded (`trace`) so a specialist's evidence can be
compared against it: drawn rules, box edges and tags confirm or contradict
this grid; they do not build it.
"""
import logging
import re
from collections import Counter

from .pagecache import _dedup_words
from .types import Line, Span, TableCandidate

_log = logging.getLogger(__name__)

_WORD_GAP = 0.6        # a gap below this many line heights stays inside a piece
_MIN_GUTTER = 4.0      # points: narrower white space is word spacing, not a column
_SPAN_LINES = 1        # a gutter may be crossed by this many lines (spanning cells)
_GAP_RATIO = 1.5       # row gap: at least this many times the typical leading
_KEY_FILL = 0.5
_ROW_VOTES = int(__import__('os').environ.get('TOMD_ROW_VOTES', '99'))   # record-only by default: measured, the votes split one-box programs (3 votes: inert)
# a code unit's opening: declaration keyword(s) and the declared name, or a
# function signature head (return type and name)
_DECL = re.compile(r"^\s*(template\s*<[^>]*>\s*)?((enum|struct|class|union|namespace|concept|using)\s+(class\s+)?[A-Za-z_]\w*"
                   r"|[A-Za-z_][\w:<>,*& ]*?\s+[*&]?[A-Za-z_]\w*\s*\()")        # key column: filled in at least this share of rows


def visual_lines(words):
    """words: (x0, y0, x1, y1, text) -> lines of words sorted left to right."""
    ws = sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    lines: list[list] = []
    for w in ws:
        h = w[3] - w[1]
        if lines:
            ln = lines[-1]
            top, bot = min(x[1] for x in ln), max(x[3] for x in ln)
            if min(bot, w[3]) - max(top, w[1]) >= 0.5 * min(h, bot - top):
                ln.append(w)
                continue
        lines.append([w])
    return [sorted(ln, key=lambda w: w[0]) for ln in lines]


def pieces_of(line):
    h = max(w[3] - w[1] for w in line)
    out: list[list] = []
    for w in line:
        if out and w[0] - out[-1][-1][2] < _WORD_GAP * h:
            out[-1].append(w)
        else:
            out.append([w])
    return [(min(w[0] for w in p), max(w[2] for w in p), p) for p in out]


def gutters(lines_pieces, x_lo, x_hi):
    """x intervals crossed by at most _SPAN_LINES lines' pieces."""
    step = 1.0
    n = int((x_hi - x_lo) / step) + 1
    cross = [0] * n
    for ps in lines_pieces:
        seen = [False] * n
        for a, b, _ in ps:
            for i in range(max(0, int((a - x_lo) / step)), min(n, int((b - x_lo) / step) + 1)):
                seen[i] = True
        for i in range(n):
            cross[i] += seen[i]
    limit = _SPAN_LINES if len(lines_pieces) > 3 * _SPAN_LINES else 0
    out, start = [], None
    for i in range(n):
        free = cross[i] <= limit
        if free and start is None:
            start = i
        if (not free or i == n - 1) and start is not None:
            end = i if not free else i + 1
            if (end - start) * step >= _MIN_GUTTER and start > 0 and end < n:
                out.append((x_lo + start * step, x_lo + end * step))
            start = None
    return out


SPECIALISTS = {"code_rows": True, "separators": True}


_LABEL_LINE = re.compile(r"^\s*(//|/\*)[^;{}()]*:?\s*(\*/)?\s*$")


def _per_unit_relation(i, cl, prev_cl, code_cols, hrules, bots, tops) -> bool:
    """Something in the table relates to the unit starting on line i on its own:
    a non-code column starts an entry there (notes, status, an explanation per
    unit), every code column carries an aligned comment-only label there (a
    sub-header), or a drawn rule lies at the boundary."""
    if any(c not in code_cols and c not in prev_cl for c in cl):
        return True
    labels = [c for c in code_cols if c in cl]
    if len(labels) >= 2 and all(_LABEL_LINE.match(" ".join(w[4] for w in cl[c])) for c in labels):
        return True
    return any(bots[i - 1] - 1 <= y <= tops[i] + 1 for y in hrules)


def build(words, hrules=(), specialists=None):
    """-> (rows of cell strings, trace).

    hrules: y positions of drawn horizontal separators that cross most of the
    region (a specialist's evidence at the row level: a drawn line between
    two text lines separates rows; no line is not evidence of anything)."""
    sp = dict(SPECIALISTS, **(specialists or {}))
    trace = {"specialists": {}}
    lines = visual_lines(words)
    if len(lines) < 2:
        return [], {"abstain": "fewer than two lines"}
    lp = [pieces_of(ln) for ln in lines]
    x_lo = min(w[0] for w in words) - 1
    x_hi = max(w[2] for w in words) + 1
    # gutters from single words, not phrases: a narrow column ("." | "Period")
    # must not be merged away. Wider than the region's own word spacing.
    spaces = sorted(b[0] - a[2] for ln in lines for a, b in zip(ln, ln[1:]) if b[0] > a[2])
    lh = sorted(max(w[3] for w in ln) - min(w[1] for w in ln) for ln in lines)[len(lines) // 2]
    # word spacing from the tight gaps only: in a numeric table most gaps
    # between neighbouring words are column gaps
    word_space = min(spaces[len(spaces) // 4] if spaces else 2.5, 0.5 * lh)
    gs = [g for g in gutters([[(w[0], w[2], [w]) for w in ln] for ln in lines], x_lo, x_hi)
          if g[1] - g[0] >= max(_MIN_GUTTER, 1.6 * word_space)]
    bounds = [x_lo] + [(a + b) / 2 for a, b in gs] + [x_hi]
    ncol = len(bounds) - 1
    trace["gutters"] = [(round(a), round(b)) for a, b in gs]
    if ncol < 2:
        return [], {**trace, "abstain": "one column"}

    def col_of(x0, x1):
        xc = (x0 + x1) / 2
        for c in range(ncol):
            if bounds[c] <= xc < bounds[c + 1]:
                return c
        return ncol - 1
    grid_lines = []
    for ps in lp:
        cells: dict = {}
        for a, b, p in ps:
            cells.setdefault(col_of(a, b), []).extend(p)
        grid_lines.append(cells)
    tops = [min(w[1] for w in ln) for ln in lines]
    bots = [max(w[3] for w in ln) for ln in lines]
    gaps = [tops[i] - bots[i - 1] for i in range(1, len(lines))]
    heights = sorted(b - t for t, b in zip(tops, bots))
    h = heights[len(heights) // 2]
    leading = sorted(gaps)[len(gaps) // 4] if gaps else 0.0     # the tight end: line leading
    # the region's own natural break: the largest jump in the sorted gaps
    sg = sorted(gaps)
    jumps = [(b - a, (a + b) / 2) for a, b in zip(sg, sg[1:]) if b - a >= 1.5 and b >= a * 1.3 + 0.5]
    row_gap = max(jumps)[1] if jumps else max(leading * _GAP_RATIO, leading + 0.35 * h)
    code = sp["code_rows"] and len(words[0]) > 5 and sum(w[5] for w in words) >= 0.6 * len(words)
    if code:
        row_gap = max(row_gap, leading + 1.5 * h)     # a blank line inside code is not a row gap
    gap_votes = [g > row_gap for g in gaps]
    # gaps separate rows only when row gaps recur: a single wide gap is the
    # space under a header rule (booktabs), not the row pattern
    gaps_separate = sum(gap_votes) >= max(2, 0.2 * len(gaps)) and not all(gap_votes)
    fill = Counter(c for cl in grid_lines for c in cl)
    key = min((c for c in range(ncol) if fill[c] >= 2), default=0)   # leftmost column used on 2+ lines
    trace.update({"ncol": ncol, "key": key, "leading": round(leading, 1), "row_gap": round(row_gap, 1),
                  "gaps_separate": gaps_separate})
    # specialist at the row level: code cells. In code, every line has text
    # in the key column, so key-column starts say nothing; only row gaps do.
    trace["code"] = code
    # code columns: mostly monospace text (the others hold notes, labels, status)
    code_cols = {c for c in range(ncol)
                 if sum(w[5] for cl in grid_lines for w in cl.get(c, []) if len(w) > 5)
                 >= 0.6 * max(sum(len(cl.get(c, [])) for cl in grid_lines), 1)}
    # each column's extent over the whole table (for the per-column wrap test)
    col_left = {c: min((min(w[0] for w in cl[c]) for cl in grid_lines if c in cl), default=0.0) for c in range(ncol)}
    col_right = {c: max((max(w[2] for w in cl[c]) for cl in grid_lines if c in cl), default=0.0) for c in range(ncol)}
    # content's own row starts first
    content_new = [True]
    unit_votes: list = [None]
    base = {c: min((min(w[0] for w in cl[c]) for cl in grid_lines if c in cl), default=0.0) for c in range(ncol)}
    balance = {c: 0 for c in range(ncol)}
    opened = {c: False for c in range(ncol)}      # a block opened (and must close) since the row began

    def _bal(text: str) -> int:
        return sum(text.count(o) - text.count(k) for o, k in ("{}", "()", "[]"))

    def _decl(text: str) -> str:
        """The declared name or signature head a unit opens with ("enum Color", "void f")."""
        m = _DECL.match(text)
        return m.group(0).replace(" ", "") if m else ""
    for i in range(1, len(grid_lines)):
        cl = grid_lines[i]
        prev_cl = grid_lines[i - 1]
        for c, ws in prev_cl.items():
            balance[c] += _bal(" ".join(w[4] for w in ws))
            opened[c] = opened[c] or balance[c] > 0 or "{" in " ".join(w[4] for w in ws)
        if code and sp["code_rows"]:
            # the code-pair specialist: three votes for a row boundary
            both = [c for c in range(ncol) if c in cl]
            at_base = [c for c in both if min(w[0] for w in cl[c]) <= base[c] + 2]
            # a complete unit: a block opened and closed back to the base indentation
            complete = (len(both) >= 2 and all(balance[c] == 0 and opened[c] for c in both)
                        and len(at_base) == len(both))
            names = [_decl(" ".join(w[4] for w in cl[c])) for c in both]
            same_name = len(names) >= 2 and names[0] != "" and all(n == names[0] for n in names)
            aligned = len(at_base) >= 2 and len(at_base) == len(both)
            votes = complete + same_name + aligned
            # the votes find candidate boundaries; a unit becomes its own row only when
            # something relates to it individually (user: a third column explaining each
            # unit, a label per unit, a rule) - otherwise each side is one block, one row
            relation = _per_unit_relation(i, cl, prev_cl, code_cols, hrules, bots, tops)
            new = gap_votes[i - 1] or (votes >= _ROW_VOTES and relation)
            if votes == 1 and aligned:
                unit_votes.append("flag: tops aligned but unit incomplete or names differ")
            elif votes >= _ROW_VOTES and not relation and not gap_votes[i - 1]:
                unit_votes.append("candidate boundary: no per-unit relation")
            else:
                unit_votes.append(votes if new else None)
        elif gap_votes[i - 1]:
            new = True
        elif gaps_separate or code:
            new = False
        else:
            prev = grid_lines[i - 1]
            lone_key_wrap = set(prev) == {key}
            new = key in cl and not (lone_key_wrap and len(cl) == 1)
            # rows not drawn (few rules for the lines): where rules separate the rows, they decide
            if not new and len(cl) >= 2 and len(hrules) < 0.3 * len(lines):
                # per column, a line continues a cell only when that column's line above ran
                # to the column's right edge (wrapping); a short or empty line above means a
                # new item. Two or more columns starting items: a new row (user, blank pattern)
                starts = [c for c in cl if c not in prev
                          or max(w[2] for w in prev[c]) < col_right[c] - 0.15 * max(col_right[c] - col_left[c], 1)]
                new = len(starts) >= 2
        content_new.append(new)
        if new:
            balance = {c: 0 for c in range(ncol)}
            opened = {c: False for c in range(ncol)}
    if code and sp["code_rows"]:
        trace["specialists"]["code_rows"] = {"row_votes": [v for v in unit_votes if v is not None]}
    # specialist (row level): drawn separators confirm, add or contradict
    ruled = [False] + [any(bots[i - 1] - 1 <= y <= tops[i] + 1 for y in hrules) for i in range(1, len(lines))]
    final_new = list(content_new)
    if sp["separators"] and hrules:
        added = [i for i in range(1, len(lines)) if ruled[i] and not content_new[i]]
        starts_c = [i for i in range(1, len(lines)) if content_new[i]]
        confirmed = [i for i in starts_c if ruled[i]]
        every_row = len(starts_c) >= 2 and len(confirmed) >= 0.6 * len(starts_c) and len(confirmed) >= 2
        removed = [i for i in starts_c if every_row and not ruled[i]]
        for i in added:
            final_new[i] = True
        for i in removed:
            final_new[i] = False
        trace["specialists"]["separators"] = {"confirmed": len(confirmed), "added": added, "removed": removed,
                                              "rules_every_row": every_row}
    rows: list[dict] = [dict(grid_lines[0])]
    starts = [0]
    for i in range(1, len(grid_lines)):
        cl = grid_lines[i]
        new = final_new[i]
        if new:
            rows.append(dict(cl))
            starts.append(i)
        else:
            for c, ws in cl.items():
                rows[-1].setdefault(c, []).extend(ws)
    trace["row_starts"] = starts
    out = []
    for r in rows:
        # reading order inside a cell: its own visual lines (raised references
        # and superscripts stay on their line), left to right
        out.append([visual_lines(r.get(c, [])) for c in range(ncol)])
    # drop columns empty in every row (a gutter split inside white space)
    keep = [c for c in range(ncol) if any(r[c] for r in out)]
    return [[r[c] for c in keep] for r in out], trace


def build_text(words, hrules=(), specialists=None):
    """Rows of cell strings (for measurement)."""
    rows, trace = build(words, hrules, specialists)
    return [[" ".join(w[4] for ln in cell for w in ln) for cell in r] for r in rows], trace


_MONO_FONTS = ("mono", "courier", "code", "cmtt", "consol", "menlo", "lmmono")


def page_words(page) -> list[tuple]:
    """(x0, y0, x1, y1, text, monospace) for every horizontal word on the page."""
    return page_text(page)[0]


def page_text(page) -> tuple[list[tuple], list[tuple]]:
    """Horizontal words (x0, y0, x1, y1, text, monospace), and rotated lines
    (x0, y0, x1, y1, text) - labels set at 90 degrees, as table headers often
    are. Rotated text is kept out of line, row and column building."""
    spans, rotated = [], []
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            horizontal = abs(ln["dir"][0] - 1) <= 0.01
            if not horizontal:
                text = "".join(sp["text"] for sp in ln["spans"]).strip()
                if text:
                    rotated.append(tuple(ln["bbox"]) + (text,))
            for sp in ln["spans"]:
                spans.append((sp["bbox"], bool(sp["flags"] & 8) or any(k in sp["font"].lower() for k in _MONO_FONTS),
                              horizontal))

    def look(w):
        xc, yc = (w[0] + w[2]) / 2, (w[1] + w[3]) / 2
        hits = [(m, h) for bb, m, h in spans if bb[0] <= xc <= bb[2] and bb[1] <= yc <= bb[3]]
        return any(m for m, _ in hits), (not hits or any(h for _, h in hits))
    words = []
    for w in _dedup_words(page.get_text("words")):
        mono, horizontal = look(w)
        if horizontal:
            words.append(tuple(w[:5]) + (mono,))
    return words, rotated


def _rotated_header(rows, rotated):
    """Rotated labels define the columns (columns level): one label per
    column, marks aligned under them. Columns: a key column left of the
    labels, one per label, and one for anything right of the last label;
    every row's words are re-assigned by x, and the labels become a header
    row placed by height among the rows."""
    labels = sorted(rotated, key=lambda r: (r[0] + r[2]) / 2)
    if len(labels) < 3 or not rows:
        return rows, None
    xs = [(r[0] + r[2]) / 2 for r in labels]
    step = min(b - a for a, b in zip(xs, xs[1:])) if len(xs) > 1 else 10.0
    edges = [xs[0] - step / 2] + [(a + b) / 2 for a, b in zip(xs, xs[1:])] + [xs[-1] + step / 2]
    ncol = len(labels) + 2

    def col(x):
        if x < edges[0]:
            return 0
        for i in range(len(labels)):
            if edges[i] <= x < edges[i + 1]:
                return i + 1
        return ncol - 1
    out = []
    for r in rows:
        cells: list[list] = [[] for _ in range(ncol)]
        for cell in r:
            for ln in cell:
                for w in ln:
                    cells[col((w[0] + w[2]) / 2)].append(w)
        out.append([visual_lines(c) for c in cells])
    head = [[] for _ in range(ncol)]
    for i, (x0, y0, x1, y1, text) in enumerate(labels):
        head[i + 1] = [[(x0, y0, x1, y1, text, False)]]
    bottom = max(r[3] for r in labels)
    at = next((i for i, r in enumerate(out)
               if min((w[1] for cell in r for ln in cell for w in ln), default=1e9) > bottom), len(out))
    above = out[:at]
    if above:
        # everything above the rotated labels is one header row (a row label
        # like "Group" is centred across both header lines)
        merged = [[w for r in above for ln in r[c] for w in ln] for c in range(ncol)]
        # a group label over several sub-columns goes to the first column of
        # its span; spans end halfway to the next group label
        groups = sorted((c, w) for c in range(1, len(labels) + 1) for w in merged[c])
        if groups:
            mids = [((a[1][0] + a[1][2]) / 2 + (b[1][0] + b[1][2]) / 2) / 2 for a, b in zip(groups, groups[1:])]
            starts = [1] + [next((c for c in range(1, len(labels) + 1) if xs[c - 1] >= m), len(labels)) for m in mids]
            for c in range(1, len(labels) + 1):
                merged[c] = []
            for (_, w), c in zip(groups, starts):
                merged[c].append(w)
            # a label column outside every group's span is a header cell over
            # both header rows: its label goes to the top row (span convention)
            width = (starts[1] - starts[0]) if len(starts) > 1 else len(labels)
            covered = {c for st in starts for c in range(st, st + width)}
            for i in range(len(labels)):
                if i + 1 not in covered:
                    merged[i + 1] = head[i + 1][0][:] if head[i + 1] else []
                    head[i + 1] = []
        above = [[visual_lines(c) for c in merged]]
    out = above + [head] + out[at:]
    at = len(above)
    keep = [c for c in range(ncol) if any(r[c] for r in out)]
    return [[r[c] for c in keep] for r in out], at


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


def _region_rules(rules, words):
    x0, x1 = min(w[0] for w in words), max(w[2] for w in words)
    y0, y1 = min(w[1] for w in words) - 4, max(w[3] for w in words) + 4
    return [y for y, a, b in rules if y0 <= y <= y1 and a <= x0 + 0.5 * (x1 - x0) and b - a >= 0.6 * (x1 - x0)]


def _cell_lines(cell, page_num) -> list[Line]:
    out = []
    for ln in cell:
        # one span per run of words in the same face: a code identifier set in several
        # words renders as one code span, not one per word
        spans = []
        for i, w in enumerate(ln):
            mono = w[5] if len(w) > 5 else False
            if spans and spans[-1].monospace == mono:
                last = spans[-1]
                spans[-1] = Span(text=last.text + " " + w[4], monospace=mono,
                                 bbox=(min(last.bbox[0], w[0]), min(last.bbox[1], w[1]),
                                       max(last.bbox[2], w[2]), max(last.bbox[3], w[3])))
                continue
            if i:
                spans.append(Span(text=" ", monospace=False))
            spans.append(Span(text=w[4], bbox=tuple(w[:4]), monospace=mono))
        out.append(Line(spans=spans, page_num=page_num,
                        bbox=(min(w[0] for w in ln), min(w[1] for w in ln),
                              max(w[2] for w in ln), max(w[3] for w in ln))))
    return out


def content_candidates(pages, regions, specialists=None, rules_by_page=None) -> list[TableCandidate]:
    """For every located region (page, bbox) - from any reader, kept or not -
    the content-first grid of the words inside it."""
    cache: dict = {}
    out: list[TableCandidate] = []
    seen = set()
    for page_num, bbox in regions:
        key = (page_num, tuple(round(v) for v in bbox))
        if key in seen:
            continue
        seen.add(key)
        if page_num not in cache:
            words_page, rotated_page = page_text(pages[page_num])
            rules = (rules_by_page or {}).get(page_num)
            cache[page_num] = (words_page, rules if rules is not None else page_hrules(pages[page_num]),
                               rotated_page)
        words_all, rules, rotated_all = cache[page_num]
        x0, y0, x1, y1 = bbox
        # a word that starts inside the region belongs to it, even when it runs past the
        # region's right edge (code overflowing its cell or frame)
        words = [w for w in words_all if w[0] >= x0 - 2 and w[0] < x1 - 1 and w[1] >= y0 - 2 and w[3] <= y1 + 2]
        if len(words) < 2:
            continue
        rows, trace = build(words, _region_rules(rules, words), specialists)
        rot = [r for r in rotated_all if r[0] >= x0 - 2 and r[2] <= x1 + 2 and r[1] >= y0 - 40 and r[3] <= y1 + 2]
        if rows and rot:
            rows, at = _rotated_header(rows, rot)
            if at is not None:
                trace["specialists"]["rotated_header"] = {"row": at, "labels": len(rot)}
        if len(rows) < 2 or max(len(r) for r in rows) < 2:
            continue
        cells = [[_cell_lines(c, page_num) for c in r] for r in rows]
        cand = TableCandidate("content", cells, {page_num: bbox})
        cand.trace = trace
        cand.region = key
        out.append(cand)
    return out
