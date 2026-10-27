# Copyright (c) 2026 Rob Beeston (rob@cppalliance.org)
# Distributed under the Boost Software License, Version 1.0.
# https://www.boost.org/LICENSE_1_0.txt

"""Table trust: one reader is never enough for HIGH; conservation, order and damage checks."""

from pathlib import Path

import pytest

from tomd.lib.pdf import run_pipeline
from tomd.lib.pdf.select import (
    candidate_from_section,
    candidates_agree,
    conservation_error,
    partial_reading,
    trust_tables,
)
from tomd.lib.pdf.types import Block, Confidence, Line, Section, SectionKind, Span, TableCandidate

_GOLDEN = Path(__file__).resolve().parent / "fixtures" / "golden"


def _span(text, x0, y0, x1=None, bold=False):
    return Span(text=text, bbox=(x0, y0, x1 if x1 is not None else x0 + 6 * len(text), y0 + 10), bold=bold)


def _table(cells, page=0, x0=100.0, y0=100.0, col_w=120.0, row_h=14.0):
    """A TABLE section whose cells are single spans laid out on a grid."""
    columns, lines = [], []
    for r, row in enumerate(cells):
        out_row = []
        for c, text in enumerate(row):
            sp = _span(text, x0 + c * col_w, y0 + r * row_h) if text else None
            out_row.append([sp] if sp else [])
        columns.append(out_row)
        spans = [cell[0] for cell in out_row if cell]
        lines.append(Line(spans=spans, page_num=page,
                          bbox=(min(s.bbox[0] for s in spans), min(s.bbox[1] for s in spans),
                                max(s.bbox[2] for s in spans), max(s.bbox[3] for s in spans))))
    sec = Section(kind=SectionKind.TABLE, text="", columns=columns, lines=lines, page_num=page)
    return sec, Block(lines=lines, page_num=page)


def test_candidate_from_section_keeps_cells_and_area():
    sec, _ = _table([["a", "b"], ["c", ""]])
    cand = candidate_from_section(sec)
    assert cand.source == "tomd" and cand.text_rows() == [["a", "b"], ["c", ""]]
    assert cand.pages == [0] and cand.shape == (2, 2)


def test_conserved_table_has_no_error():
    sec, blk = _table([["Name", "Value"], ["alpha", "1"], ["beta", "2"]])
    assert conservation_error(candidate_from_section(sec), [blk]) == ""


def test_lost_text_is_a_conservation_error():
    sec, blk = _table([["Name", "Value"], ["alpha", "1"], ["beta", "2"]])
    sec.columns[2][0] = []            # the table dropped "beta", the page still has it
    msg = conservation_error(candidate_from_section(sec), [blk])
    assert msg.startswith("Text conservation failed: 4 characters")


def test_agreement_is_cell_for_cell():
    a = candidate_from_section(_table([["x", "y"], ["1", "2"]])[0])
    b = candidate_from_section(_table([["x", "y"], ["1", "2"]])[0])
    c = candidate_from_section(_table([["x", "y"], ["1", "3"]])[0])
    assert candidates_agree(a, b) and not candidates_agree(a, c)


def test_partial_reading_needs_a_ruled_primary():
    full = candidate_from_section(_table([["h1", "h2"], ["a", "b"], ["c", "d"]])[0])
    part = candidate_from_section(_table([["h1", "h2"], ["a", "b"]])[0])
    assert not partial_reading(full, part)
    full.source = "rules"
    assert partial_reading(full, part)


def test_single_source_table_is_uncertain_with_reasons():
    sec, blk = _table([["Name", "Value"], ["alpha", "1"]])
    trust_tables([sec], [blk])
    assert sec.confidence == Confidence.UNCERTAIN
    assert sec.metadata["table_agreement"] == "none"
    assert sec.metadata["uncertain_reasons"] == ["single-source"]
    assert sec.columns[1][0][0].text == "alpha"        # no cell changes


def test_damaged_text_layer_is_a_reason():
    sec, blk = _table([["Name", "ᴀx"], ["alpha", "1"]])
    trust_tables([sec], [blk])
    assert "damaged" in sec.metadata["uncertain_reasons"]


def test_no_table_from_one_reader_is_trusted():
    pdf = _GOLDEN / "p4012r0-page-6.pdf"
    if not pdf.is_file():
        pytest.skip(f"missing PDF fixture: {pdf.name}")
    tables = [s for s in run_pipeline(pdf).sections if s.kind == SectionKind.TABLE]
    assert tables, "fixture should hold a table"
    for sec in tables:
        assert sec.confidence == Confidence.UNCERTAIN
        assert "single-source" in sec.metadata["uncertain_reasons"]
