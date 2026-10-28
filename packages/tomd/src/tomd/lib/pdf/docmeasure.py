#
# Copyright (c) 2026 Rob Beeston (rob@cppalliance.org)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
#

"""Level 0: what ordinary prose looks like in this document.

Measured once per paper from the body text (lines of multi-line blocks with
several words): the prose measure (left and right text edges, robust
percentiles), whether the prose is justified (right edges pile up on the
measure), and the normal space between words per text height. Everything
below compares against it: a table's text is inset from the measure (cell
padding) and ends raggedly per column; its lines have bimodal word gaps
(one space inside cells, several between cells, recurring at the same x),
where prose has uniform gaps (one space, or uniformly stretched when
justified).
"""
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field


@dataclass
class DocMeasure:
    left: float = 0.0
    right: float = 0.0
    justified: float = 0.0               # share of prose lines ending on the right measure
    space: dict = field(default_factory=dict)   # text height (pt, rounded) -> normal word space
    known: bool = False

    def word_space(self, height: float) -> float:
        if not self.space:
            return 2.5
        h = round(height)
        if h in self.space:
            return self.space[h]
        near = min(self.space, key=lambda k: abs(k - h))
        return self.space[near] * height / max(near, 1)


def visual_lines(words):
    """Words (x0, y0, x1, y1, text, ...) sharing a baseline, left to right."""
    ws = sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    lines: list[list] = []
    for w in ws:
        if lines:
            ln = lines[-1]
            top, bot = min(x[1] for x in ln), max(x[3] for x in ln)
            if min(bot, w[3]) - max(top, w[1]) >= 0.5 * min(w[3] - w[1], bot - top):
                ln.append(w)
                continue
        lines.append([w])
    return [sorted(ln, key=lambda w: w[0]) for ln in lines]


def measure(page_words: list[list]) -> DocMeasure:
    """page_words: per page, fitz "words" tuples (x0, y0, x1, y1, text, block, line, n)."""
    xs0, xs1, gaps = [], [], defaultdict(list)

    def take(ln):
        if len(ln) < 6:
            return
        xs0.append(ln[0][0])
        xs1.append(ln[-1][2])
        h = round(statistics.median(w[3] - w[1] for w in ln))
        gaps[h].extend(b[0] - a[2] for a, b in zip(ln, ln[1:]) if b[0] > a[2])

    for words in page_words:
        blocks = defaultdict(lambda: defaultdict(list))
        for w in words:
            blocks[w[5]][w[6]].append(w)
        for lines in blocks.values():
            if len(lines) >= 3:
                for ln in lines.values():
                    take(sorted(ln, key=lambda w: w[0]))
    if len(xs0) < 20:
        # some generators put every line of a paragraph in a block of its own:
        # fall back to the page's visual lines (long lines only, so headings
        # and list labels stay out; the percentiles below absorb the rest)
        xs0, xs1, gaps = [], [], defaultdict(list)
        for words in page_words:
            for ln in visual_lines(words):
                take(ln)
    if len(xs0) < 20:
        return DocMeasure()
    xs0.sort()
    xs1.sort()
    left, right = xs0[len(xs0) // 10], xs1[-1 - len(xs1) // 10]
    return DocMeasure(left=left, right=right,
                      justified=sum(1 for x in xs1 if abs(x - right) <= 3) / len(xs1),
                      space={h: sorted(g)[len(g) // 4] for h, g in gaps.items() if len(g) >= 30},
                      known=True)


def gap_stats(line, m: DocMeasure) -> dict | None:
    """One visual line's word gaps in units of the document's normal space."""
    if len(line) < 2:
        return None
    h = statistics.median(w[3] - w[1] for w in line)
    sp = max(m.word_space(h), 0.8)
    g = [(b[0] - a[2]) / sp for a, b in zip(line, line[1:])]
    big, med = max(g), statistics.median(g)
    return {"max_gap": big, "bimodal": big >= 3 and min(g) <= 1.6,
            "uniform": len(g) >= 3 and big <= 1.8 * max(med, 0.3) and big < 3,
            "big_x": [(a[2] + b[0]) / 2 for a, b, x in zip(line, line[1:], g) if x >= 3]}


def area_word_features(words, m: DocMeasure) -> dict:
    """Word-gap and footprint features of the words in one area."""
    lines = [ln for ln in visual_lines(words) if len(ln) >= 2]
    if not lines or not m.known:
        return {"w_known": 0.0}
    st = [gap_stats(ln, m) for ln in lines]
    st = [s for s in st if s]
    if not st:
        return {"w_known": 0.0}
    xs = [x for s in st for x in s["big_x"]]
    recur = sum(1 for s in st if any(sum(1 for y in xs if abs(y - x) <= 4) >= 2 for x in s["big_x"]))
    ends = [ln[-1][2] for ln in lines]
    return {"w_known": 1.0,
            "w_max_gap": float(statistics.median(s["max_gap"] for s in st)),
            "w_bimodal_share": sum(s["bimodal"] for s in st) / len(st),
            "w_recurring_gap_share": recur / len(st),
            "w_uniform_share": sum(s["uniform"] for s in st) / len(st),
            "f_left_inset": min(w[0] for w in words) - m.left,
            "f_right_inset": m.right - max(w[2] for w in words),
            "f_ends_on_measure": sum(1 for e in ends if abs(e - m.right) <= 3) / len(ends),
            "f_justified_doc": m.justified}


def hyphenates(page_words: list[list]) -> bool:
    """Does the document break words with a hyphen at line ends? Evidence: a
    line ending in "word-" whose join with the next line's first word appears
    elsewhere in the document unhyphenated ("compari-" + "son", "comparison"
    seen elsewhere). Two or more such breaks: it hyphenates. None: a line-end
    hyphen is the word's own ("Use-" + "cases"). One: undecided, treated as
    hyphenating (the earlier behaviour). Measured on the keys: 4 to 223 such
    breaks in hyphenating papers (LaTeX, and Word with hyphenation on), 0 in
    papers that never hyphenate. The maker alone does not tell (Word can do
    either)."""
    lines = []
    for words in page_words:
        cur: dict = {}
        for w in words:
            cur.setdefault((w[5], w[6]), []).append(w)
        lines += [" ".join(w[4] for w in sorted(ln, key=lambda w: w[0])) for ln in cur.values()]
    seen = Counter(t.lower() for ln in lines for t in re.findall(r"[A-Za-z]+", ln))
    breaks = 0
    for a, b in zip(lines, lines[1:]):
        m, n = re.search(r"([A-Za-z]+)-$", a), re.match(r"([a-z]+)", b)
        if m and n and seen[(m.group(1) + n.group(1)).lower()] > 0:
            breaks += 1
            if breaks >= 2:
                return True
    return breaks != 0
