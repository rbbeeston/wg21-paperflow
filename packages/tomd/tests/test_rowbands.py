# Copyright (c) 2026 Rob Beeston (rob@cppalliance.org)
# Distributed under the Boost Software License, Version 1.0.
# https://www.boost.org/LICENSE_1_0.txt

"""Rows bounded by drawn rules (rowbands.py)."""
from tomd.lib.pdf.rowbands import merge_rule_bands
from tomd.lib.pdf.types import Line, Section, SectionKind, Span


def _sec(rows):
    cols = [[[Span(text=t, bbox=(x, y, x + 40, y + 10))] if t else [] for t, x in zip(r, (10, 100, 200))]
            for r, y in rows]
    lines = [Line(spans=[s for c in r for s in c], bbox=(10, y, 240, y + 10), page_num=3) for r, (_, y) in zip(cols, rows)]
    return Section(kind=SectionKind.TABLE, text="", lines=lines, columns=cols)


GRID = [(y, 0, 300) for y in (8, 25, 45, 85, 108)]       # border, header, records 25-45, 45-85, 85-108


def _texts(sec):
    return [[" ".join(s.text for s in c if s.text != "\n") for c in r] for r in sec.columns]


def test_continuation_row_joins_record_above():
    s = _sec([(["Key", "A", "B"], 10), (["US 1", "first", "x"], 30), (["US 2", "start", "y"], 50),
              (["", "more", ""], 65), (["US 3", "z", "w"], 95)])
    assert merge_rule_bands(s, GRID) == 1
    assert _texts(s)[2] == ["US 2", "start more", "y"]


def test_rule_between_rows_keeps_them_apart():
    s = _sec([(["Key", "A", "B"], 10), (["US 1", "first", "x"], 30), (["", "next", ""], 50),
              (["US 3", "z", "w"], 95)])
    assert merge_rule_bands(s, GRID) == 0


def test_no_grid_no_change():
    s = _sec([(["Key", "A", "B"], 10), (["US 2", "start", "y"], 50), (["", "more", ""], 65)])
    assert merge_rule_bands(s, [(5, 0, 300), (120, 0, 300)]) == 0


def test_full_row_with_blank_key_is_its_own_record():
    # grouped grid: the group name only on the first row; the next row is full, not a continuation
    s = _sec([(["Key", "A", "B"], 10), (["US 1", "first", "x"], 30), (["Group", "start", "y"], 50),
              (["", "next", "z"], 65), (["US 3", "z", "w"], 95)])
    assert merge_rule_bands(s, GRID) == 0
