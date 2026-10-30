#
# Copyright (c) 2026 Rob Beeston (rob@cppalliance.org)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
#

"""Side-by-side code comparisons, found from geometry and confirmed by content.

  observation  two blocks of monospace lines on one page whose vertical
               extents overlap (by half the shorter one) with a gutter
               between them - whatever draws them: boxes, shading, rules or
               white space only;
  hypothesis   the two blocks do roughly the same thing: they share much of
               their code (whitespace-free character trigrams, since text
               layers often drop spaces in code), and the right one is not
               a column of comments beside the left one;
  validation   short labels aligned above both blocks become the header row;
               pairs stacked down the page with the same column starts are
               rows of one table.
Measured on the truth sets (cmp_measure.py) before use. A pair is a table
candidate like any other ("codepair"); it renders with the code-comparison
convention.
"""

import dataclasses
import logging
import re
from collections import defaultdict

from .runctx import current
from .types import Block, Line, TableCandidate

_log = logging.getLogger(__name__)

_MONO_SHARE = 0.8          # a monospace piece: this share of its characters
_PIECE_GAP = 12.0          # a wider gap inside a pdf line separates two pieces
_JOIN_GAP = 1.8            # lines join a block across gaps below this many line heights
_OVERLAP = 0.5             # vertical overlap, share of the shorter block
_SAME_CODE = 0.3           # trigram overlap coefficient: "doing the same thing"
_COMMENTS = 0.7            # a right block this share comments is an annotation column
_LABEL_REACH = 30.0        # a label sits at most this far above its block
_LABEL_WORDS = 8
_STACK_TOL = 6.0           # stacked pairs: column starts this close are the same column
_COMMENT = ("//", "/*", "#", "--")
_CODE_MARK = re.compile(r"[;{}()<>\[\]=]|::|->")
_CODE_LINES = 0.3          # a code block: this share of its lines carry code punctuation
_FURNITURE_PAGES = 3       # the same pair text on this many pages is page furniture
_ROW_TEXT = 0.5            # this share of left lines with plain text on their row, between or right of the code: rows


def _pieces(line: Line) -> list[Line]:
    spans = sorted((s for s in line.spans if s.text.strip()), key=lambda s: s.bbox[0])
    out: list[list] = []
    for s in spans:
        if out and s.bbox[0] - out[-1][-1].bbox[2] <= _PIECE_GAP:
            out[-1].append(s)
        else:
            out.append([s])
    return [Line(spans=p, page_num=line.page_num,
                 bbox=(min(s.bbox[0] for s in p), min(s.bbox[1] for s in p),
                       max(s.bbox[2] for s in p), max(s.bbox[3] for s in p))) for p in out]


def _mono(line: Line) -> bool:
    chars = sum(len(s.text.strip()) for s in line.spans)
    mono = sum(len(s.text.strip()) for s in line.spans if s.monospace)
    return chars > 0 and mono >= _MONO_SHARE * chars


def _ruled_between(a: Line, b: Line, rules) -> bool:
    """A drawn horizontal rule separates the two lines where they overlap."""
    top, bot = min(a.bbox[3], b.bbox[3]), max(a.bbox[1], b.bbox[1])
    x0, x1 = max(a.bbox[0], b.bbox[0]), min(a.bbox[2], b.bbox[2])
    return any(top - 1 <= y <= bot + 1 and rx0 <= x0 + 2 and rx1 >= x1 - 2 for y, rx0, rx1 in rules)


def _blocks(lines: list[Line], rules=()) -> list[list[Line]]:
    parent = list(range(len(lines)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i, a in enumerate(lines):
        h = max(a.bbox[3] - a.bbox[1], 1.0)
        for j in range(i + 1, len(lines)):
            b = lines[j]
            if b.bbox[1] - a.bbox[3] > _JOIN_GAP * h:
                break                                 # sorted by top: nothing further joins
            if min(a.bbox[2], b.bbox[2]) > max(a.bbox[0], b.bbox[0]) and not _ruled_between(a, b, rules):
                parent[find(i)] = find(j)
    groups: dict = defaultdict(list)
    for i, ln in enumerate(lines):
        groups[find(i)].append(ln)
    return [sorted(g, key=lambda l: (l.bbox[1], l.bbox[0])) for g in groups.values()]


def _spaced(line: Line) -> Line:
    """A copy of the line with a space where the PDF leaves a word-sized gap
    between two runs and encodes no space ("int" "f(int" "x)" -> "int f(int x)")."""
    out = []
    for sp in line.spans:
        if out:
            prev = out[-1]
            gap = sp.bbox[0] - prev.bbox[2]
            if (gap >= 0.25 * max(sp.font_size or prev.font_size, 1.0) and prev.text[-1:].strip()
                    and sp.text[:1].strip()):
                out.append(dataclasses.replace(prev, text=" ", bbox=(prev.bbox[2], prev.bbox[1], sp.bbox[0], prev.bbox[3])))
        out.append(sp)
    return dataclasses.replace(line, spans=out)


def _box(block: list[Line]) -> tuple[float, float, float, float]:
    return (min(l.bbox[0] for l in block), min(l.bbox[1] for l in block),
            max(l.bbox[2] for l in block), max(l.bbox[3] for l in block))


def _grams(block: list[Line]) -> set[str]:
    t = re.sub(r"\s+", "", "".join(l.text for l in block))
    return {t[i:i + 3] for i in range(len(t) - 2)}


def same_code(left: list[Line], right: list[Line]) -> float:
    """Share of the smaller block's trigrams that the other block has too."""
    a, b = _grams(left), _grams(right)
    return len(a & b) / max(min(len(a), len(b)), 1)


def _comment_share(block: list[Line]) -> float:
    return sum(l.text.strip().startswith(_COMMENT) for l in block) / max(len(block), 1)


def _code_like(block: list[Line]) -> bool:
    """Code, not prose set in a monospace font."""
    return sum(bool(_CODE_MARK.search(l.text)) for l in block) >= _CODE_LINES * len(block)


def _row_text_share(left: list[Line], right: list[Line], rest: list[Line]) -> float:
    """Share of the left block's lines that have plain (non-code) text on the same row
    between the two blocks or right of the right one ("cw<1> + 1 | -> | 2 | the thing it
    holds"): a mapping table whose rows hold code, not two listings side by side."""
    lb, rb = _box(left), _box(right)
    def on_row(ln, other):
        h = ln.bbox[3] - ln.bbox[1]
        return abs((ln.bbox[1] + ln.bbox[3]) / 2 - (other.bbox[1] + other.bbox[3]) / 2) <= h / 2
    beside = [r for r in rest if not r.text.strip().isdigit()        # line numbers belong to listings
              and lb[1] - 2 <= (r.bbox[1] + r.bbox[3]) / 2 <= max(lb[3], rb[3]) + 2
              and (lb[2] <= r.bbox[0] and r.bbox[2] <= rb[0] or r.bbox[0] >= rb[2])]
    hits = sum(1 for ln in left if any(on_row(ln, r) for r in beside))
    return hits / len(left) if left else 0.0


def _label(block: list[Line], others: list[Line]) -> Line | None:
    x0, y0, x1, _ = _box(block)
    near = [l for l in others if y0 - _LABEL_REACH <= l.bbox[3] <= y0 + 1
            and l.bbox[0] < x1 and l.bbox[2] > x0 and len(l.text.split()) <= _LABEL_WORDS]
    return max(near, key=lambda l: l.bbox[3]) if near else None


def find_code_pairs(blocks: list[Block], rules_for=None) -> list[TableCandidate]:
    """Code-comparison candidates on every page. rules_for(page) gives the
    page's drawn horizontal rules (y, x0, x1): a rule between two lines
    separates them (rows of a ruled comparison are not one block)."""
    by_page: dict = defaultdict(list)
    for b in blocks:
        for ln in b.lines:
            by_page[ln.page_num].extend(_pieces(ln))
    out: list[TableCandidate] = []
    for page, pieces in sorted(by_page.items()):
        mono = sorted((p for p in pieces if _mono(p)), key=lambda l: (l.bbox[1], l.bbox[0]))
        rest = [p for p in pieces if not _mono(p)]
        rules = rules_for(page) if (rules_for and mono) else []
        code_blocks = [b for b in _blocks(mono, rules) if len(b) >= 2]
        pairs = []
        weak = []                     # pairs whose sides share too little code on their own
        for i, a in enumerate(code_blocks):
            for b in code_blocks[i + 1:]:
                left, right = (a, b) if _box(a)[0] <= _box(b)[0] else (b, a)
                lb, rb = _box(left), _box(right)
                if lb[2] > rb[0]:
                    continue                          # no gutter between them
                overlap = min(lb[3], rb[3]) - max(lb[1], rb[1])
                if overlap < _OVERLAP * min(lb[3] - lb[1], rb[3] - rb[1]):
                    continue
                box = (lb[0], min(lb[1], rb[1]), rb[2], max(lb[3], rb[3]))
                rec = current().record
                if _comment_share(right) >= _COMMENTS:
                    rec.exclude("codepair", page, box, "code with a comment column", "words")
                    continue                          # code with its comments beside it
                if _row_text_share(left, right, rest) >= _ROW_TEXT:
                    rec.exclude("codepair", page, box, "rows continue with text beside the code (a wider table)", "words")
                    continue                          # two code columns of a wider table
                if not (_code_like(left) and _code_like(right)):
                    rec.exclude("codepair", page, box, "monospace prose, not code", "words")
                    continue                          # monospace prose (a form, a template)
                score = same_code(left, right)
                rec.feature("codepair", page, box, "same-code", "meaning", round(score, 3))
                if score >= _SAME_CODE:
                    pairs.append((left, right, score))
                else:
                    rec.exclude("codepair", page, box, "blocks do not share their code", "meaning", round(score, 3))
                    weak.append((left, right, score))
        # one block pairs once: keep its best partner
        pairs.sort(key=lambda p: -p[2])
        used: set[int] = set()
        kept = []
        for left, right, score in pairs:
            if id(left) in used or id(right) in used:
                continue
            used |= {id(left), id(right)}
            kept.append((left, right, score))
        # a weak pair stacked directly on a kept pair (the same column starts, nothing
        # between) is a row of the same comparison: the layout is the evidence
        for w in weak:
            if id(w[0]) in used or id(w[1]) in used:
                continue
            for k in kept:
                same_cols = (abs(_box(w[0])[0] - _box(k[0])[0]) <= _STACK_TOL
                             and abs(_box(w[1])[0] - _box(k[1])[0]) <= _STACK_TOL)
                top, bot = sorted((w, k), key=lambda p: _box(p[0])[1])
                gap_lo = max(_box(top[0])[3], _box(top[1])[3])
                gap_hi = min(_box(bot[0])[1], _box(bot[1])[1])
                between = any(gap_lo + 1 < (l.bbox[1] + l.bbox[3]) / 2 < gap_hi - 1 and
                              l.bbox[0] < _box(w[1])[2] and l.bbox[2] > _box(w[0])[0] for l in rest)
                if same_cols and 0 <= gap_hi - gap_lo <= 60 and not between:
                    current().record.feature("codepair", page, _box(w[0]), "stacked on a kept pair", "words", 1.0)
                    kept.append(w)
                    used |= {id(w[0]), id(w[1])}
                    break
        kept.sort(key=lambda p: _box(p[0])[1])

        def labels(pair):
            """The pair's own label lines: aligned across the sides ("// P2935R0:" |
            "// This paper:"). Labels are header material, never a code unit."""
            lab_l, lab_r = _label(pair[0], rest), _label(pair[1], rest)
            if lab_l is not None and lab_r is not None and lab_l is not lab_r \
                    and abs(lab_l.bbox[1] - lab_r.bbox[1]) <= 3:
                return [[lab_l], [lab_r]]
            return None

        def prose_between(last, p, labs):
            """Text between two stacked pairs (other than the pair's labels): a
            heading, caption or prose between them makes two tables."""
            top, bot = max(_box(last[0])[3], _box(last[1])[3]), min(_box(p[0])[1], _box(p[1])[1])
            x0, x1 = _box(p[0])[0], _box(p[1])[2]
            skip = {id(c[0]) for c in (labs or [])}
            return any(top + 1 < (l.bbox[1] + l.bbox[3]) / 2 < bot - 1 and l.bbox[0] < x1 and l.bbox[2] > x0
                       and id(l) not in skip for l in rest)

        # stacked pairs with the same column starts are rows of one table; text
        # between them splits the table; a recurring label pair inside a table
        # starts a row group (a sub-header row, then its code row)
        tables: list[list] = []
        for p in kept:
            labs = labels(p)
            if tables:
                last = tables[-1][-1][1]
                if (abs(_box(p[0])[0] - _box(last[0])[0]) <= _STACK_TOL
                        and abs(_box(p[1])[0] - _box(last[1])[0]) <= _STACK_TOL
                        and not prose_between(last, p, labs)):
                    tables[-1].append((labs, p))
                    continue
            tables.append([(labs, p)])
        for group in tables:
            cells = []
            for i, (labs, (left, right, _)) in enumerate(group):
                if labs:
                    cells.append(labs)
                cells.append([left, right])
            rows = [p for _, p in group]
            header = cells[:1] if group[0][0] else []
            lines = [ln for r in cells for c in r for ln in c]
            bbox = (min(l.bbox[0] for l in lines), min(l.bbox[1] for l in lines),
                    max(l.bbox[2] for l in lines), max(l.bbox[3] for l in lines))
            cells = [[[_spaced(ln) for ln in c] for c in r] for r in cells]
            cand = TableCandidate("codepair", cells, {page: bbox})
            cand.flags = ["same-code=%.2f" % min(s for _, _, s in rows)] + (["labelled"] if header else [])
            out.append(cand)
    # page furniture: the same pair text recurring page after page
    key = lambda c: re.sub(r"\s+", "", " ".join(c.text_rows()[-1]))[:200]
    seen = defaultdict(set)
    for c in out:
        seen[key(c)].add(c.pages[0])
    for c in out:
        if len(seen[key(c)]) >= _FURNITURE_PAGES:
            current().record.exclude("codepair", c.pages[0], c.bboxes[c.pages[0]],
                                       "page furniture (same pair on 3+ pages)", "document")
    out = [c for c in out if len(seen[key(c)]) < _FURNITURE_PAGES]
    if out:
        _log.debug("%d code-comparison candidate(s)", len(out))
    return out
