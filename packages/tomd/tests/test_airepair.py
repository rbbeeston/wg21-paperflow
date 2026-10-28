# Copyright (c) 2026 Rob Beeston (rob@cppalliance.org)
# Distributed under the Boost Software License, Version 1.0.
# https://www.boost.org/LICENSE_1_0.txt

"""The AI step's pure pieces: the request, and how an answer is checked and used."""

from tomd.lib.pdf.airepair import RepairAnswer, apply_repair, build_columns, code_guard, repair_request
from tomd.lib.pdf.types import Confidence, Line, Section, SectionKind, Span

# four words of a 2x2 table: (x0, y0, x1, y1, text)
_WORDS = [(10, 10, 30, 20, "Name"), (60, 10, 90, 20, "Value"),
          (10, 30, 30, 40, "alpha"), (60, 30, 70, 40, "1")]


def _table(conf=Confidence.UNCERTAIN):
    cols = [[[Span("Name", bbox=_WORDS[0][:4])], [Span("Value", bbox=_WORDS[1][:4])]],
            [[Span("alpha 1", bbox=(10, 30, 70, 40))], []]]
    lines = [Line(spans=[Span(w[4], bbox=w[:4])], bbox=w[:4], page_num=0) for w in _WORDS]
    return Section(kind=SectionKind.TABLE, text="Name | Value\nalpha 1 |", confidence=conf,
                   page_num=0, columns=cols, lines=lines)


def test_request_lists_words_by_index_and_skips_trusted_tables():
    req = repair_request(_table(), _WORDS)
    assert req["word_count"] == 4 and req["words"].splitlines()[0] == "0, 10, 10, 30, 20, Name"
    assert repair_request(_table(Confidence.HIGH), _WORDS) is None
    assert repair_request(_table(), []) is None


def test_an_answer_can_only_arrange_the_given_words():
    assert build_columns([[[0], [1]], [[2], [9]]], _WORDS) == (None, "unknown-word")
    assert build_columns([[[0], [1]], [[2], [2]]], _WORDS) == (None, "word-used-twice")
    assert build_columns([[[0], [1]], [[2], []]], _WORDS) == (None, "word-left-out")
    assert build_columns([[[0], [1]], [[2, 3]]], _WORDS) == (None, "ragged")


def test_rejected_answer_leaves_the_table_unchanged():
    sec = _table()
    before = sec.columns
    assert apply_repair(sec, RepairAnswer([[[0], [1]], [[2], [2]]]), _WORDS) == "rejected:word-used-twice"
    assert sec.columns is before and sec.confidence == Confidence.UNCERTAIN


def test_code_guard_refuses_an_added_line_number_column():
    code = [[[Span("int a;")]], [[Span("int b;")]], [[Span("int c;")]]]
    numbered = [[[Span("1")], [Span("int a;")]], [[Span("2")], [Span("int b;")]], [[Span("3")], [Span("int c;")]]]
    assert code_guard(code, numbered) == "line-numbers-added"
    assert code_guard(numbered, numbered) == ""
