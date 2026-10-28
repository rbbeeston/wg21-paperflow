#
# Copyright (c) 2026 Rob Beeston (rob@cppalliance.org)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
#

"""The AI step's pure pieces: what to ask about a flagged table, and how an answer is used.

tomd never calls a model. The agent that asks (open question 7: in paperflow's
pipeline framework, `pipeline.run_agent` with RepairAnswer as its output type,
retries and usage limits) lives outside run_pipeline; the step is off unless
that caller runs it. tomd gives the agent:

  repair_request(sec, words)  the instructions and the table area's words, by
                              index; None when the table is not asked about
  apply_repair(sec, answer, words)
                              the answer's arrangement checked and, when it holds,
                              put in place of the table's cells

An answer can only arrange the given words (indices): it cannot add, change or
drop text. It is rejected when an index is unknown or used twice, a word is left
out, the rows are ragged, the layout check against the page fails, or it adds a
column of bare line numbers to code. A repaired table stays flagged (L4); the
first reading is kept in the metadata and the evidence record.
"""
from dataclasses import dataclass, replace

from .runctx import current
from .types import Confidence, Section, Span
from .validate import verify_layout

# A table area holding more words than this is not asked about.
MAX_WORDS = 1500
# Words on one text line: centres closer than this (pt) are joined with a space.
_SAME_LINE = 3.0

INSTRUCTIONS = (
    "The image shows one table from a WG21 paper. Below it is every word of the PDF's "
    "text layer inside the table's area, one per line as: index, x0, y0, x1, y1, text "
    "(page coordinates, y grows downwards).\n\n"
    "Arrange the words into the table's rows and cells, as a reader of the image would. "
    "Return rows top to bottom; each row is a list of cells left to right; each cell is "
    "the list of word indices in reading order (an empty list for an empty cell). Every "
    "row has the same number of cells. Use every index exactly once. You may only "
    "arrange the given words: never add, change or drop text. Conventions: the header "
    "row is the first row; several entries stacked in one drawn cell are separate rows; "
    "a cell whose text wraps is one cell; a cell spanning several columns goes in its "
    "first column with empty cells after it."
)


@dataclass(frozen=True)
class RepairAnswer:
    """A model's arrangement: rows of cells of word indices (no text can be added)."""
    rows: list[list[list[int]]]


def repair_request(sec: Section, words: list) -> dict | None:
    """What to ask about a flagged table: the instructions and its area's words,
    by index. None for a trusted table, or an area with no words or too many."""
    if sec.confidence == Confidence.HIGH or not words or len(words) > MAX_WORDS:
        return None
    lines = [f"{i}, {w[0]:.0f}, {w[1]:.0f}, {w[2]:.0f}, {w[3]:.0f}, {w[4]}" for i, w in enumerate(words)]
    return {"instructions": INSTRUCTIONS, "words": "\n".join(lines), "word_count": len(words)}


def build_columns(rows, words):
    """Cells of spans from word indices, or (None, reason) if the answer is unusable:
    an index out of range, used twice, or a word left out."""
    used = [i for row in rows for cell in row for i in cell]
    if any(not isinstance(i, int) or i < 0 or i >= len(words) for i in used):
        return None, "unknown-word"
    if len(used) != len(set(used)):
        return None, "word-used-twice"
    if len(used) != len(words):
        return None, "word-left-out"
    if not rows or len({len(r) for r in rows}) != 1:
        return None, "ragged"
    columns = []
    for row in rows:
        out_row = []
        for cell in row:
            spans: list = []
            prev = None
            for w in (words[i] for i in cell):
                if prev is not None:
                    same_line = abs((w[1] + w[3]) / 2 - (prev[1] + prev[3]) / 2) <= _SAME_LINE
                    spans.append(Span(text=" ") if same_line else Span(text="\n"))
                spans.append(Span(text=w[4], bbox=tuple(w[:4])))
                prev = w
            out_row.append(spans)
        columns.append(out_row)
    return columns, ""


def code_guard(first, repaired) -> str:
    """A repair may not add a column of bare line numbers to code. Returns the
    failed check or "" (measured on fresh10's cached answers in tomd-tables: it
    turned the two breaks repair caused in side-by-side code into no change)."""
    def ints(cols, j):
        vals = [" ".join(s.text for s in r[j] if s.text != "\n").strip() for r in cols if j < len(r)]
        vals = [v for v in vals if v]
        return len(vals) >= 3 and all(v.isdigit() for v in vals)
    ncol_f = max((len(r) for r in first), default=0)
    ncol_r = max((len(r) for r in repaired), default=0)
    if ncol_r > ncol_f and any(ints(repaired, j) for j in range(ncol_r)) \
            and not any(ints(first, j) for j in range(ncol_f)):
        return "line-numbers-added"
    return ""


def apply_repair(sec: Section, answer: RepairAnswer, words: list, model: str = "") -> str:
    """Check the answer and, when it holds, put its arrangement in place of the
    table's cells. Returns "verified" or "rejected:<why>"; the table stays flagged."""
    columns, why = build_columns(answer.rows, words)
    if columns is None:
        sec.metadata["llm_repair"] = {"model": model, "result": "rejected:" + why}
        return "rejected:" + why
    failed = verify_layout(replace(sec, columns=columns, metadata=dict(sec.metadata)), words) \
        or code_guard(sec.columns or [], columns)
    if failed:
        sec.metadata["llm_repair"] = {"model": model, "result": "rejected:" + failed}
        return "rejected:" + failed
    first, first_source = sec.text, sec.metadata.get("table_source")
    sec.columns = columns
    sec.text = "\n".join(" | ".join("".join(s.text for s in c) for c in r) for r in columns)
    sec.metadata["llm_repair"] = {"model": model, "result": "verified", "first_reading": first,
                                  "first_source": first_source}
    sec.metadata["table_source"] = "llm-structure"
    sec.metadata.pop("likely", None)          # the fit was for the first reading
    reasons = sec.metadata.setdefault("uncertain_reasons", [])
    if "llm-repaired" not in reasons:
        reasons.append("llm-repaired")
    sec.confidence = Confidence.UNCERTAIN
    current().record.feature("llm", sec.page_num, (0, 0, 0, 0), "first-reading", "record", first)
    return "verified"
