# Copyright (c) 2026 C++ Alliance, Inc. (https://cppalliance.org)
# Distributed under the Boost Software License, Version 1.0.
# https://www.boost.org/LICENSE_1_0.txt

"""Family pins for one PDF golden.

One module per paper. A new golden adds a module here and a stem file.
It does not edit test_pdf_golden.py.
"""

from pathlib import Path

import pytest

from tomd.lib.pdf import run_pipeline
from tomd.lib.pdf.types import SectionKind

_GOLDEN = Path(__file__).resolve().parent.parent / "fixtures" / "golden"

# Family pins for P4047R0 (#377): the seven prediction tables (tomd pages
# 2-5, printed 3-6; Timeline, Safety and Correctness, Customization
# Mechanism, Universality and Scope, Domain Viability, Networking,
# Implementation Maturity) are header-grid seeds of the side-by-side
# pre-scanner. The Scorecard (page 6) is Pass 1 with its header cluster
# absorbed; the Conclusion (page 6) is Pass 1 at header plus three rows,
# its fourth row leaks as prose (pinned as is, tracked separately).
_P4047R0_TABLE_PINS = {
    (2, 6, 5, "prose_table", "side_by_side_prepass"),
    (3, 6, 5, "clean_matrix", "side_by_side_prepass"),
    (3, 4, 5, "prose_table", "side_by_side_prepass"),
    (4, 7, 5, "clean_matrix", "side_by_side_prepass"),
    (4, 4, 5, "clean_matrix", "side_by_side_prepass"),
    (5, 4, 5, "prose_table", "side_by_side_prepass"),
    (5, 3, 5, "clean_matrix", "side_by_side_prepass"),
    (6, 9, 6, "clean_matrix", "horizontal_rows"),
    # the Conclusion's fifth row ("Implementation maturity concerns") is read
    # since port step 6; the old 4-row shape dropped it
    (6, 5, 2, "clean_matrix", None),
}
_P4047R0_PREDICTION_HEADER = ["#", "Prediction", "Source", "Date", "Outcome"]


def _header_cells(section) -> list[str]:
    """Header row cell texts, runs of whitespace collapsed."""
    return [" ".join("".join(sp.text for sp in cell).split())
            for cell in section.columns[0]]


def test_p4047r0_table_family_pins():
    """#377 focused guard: the seven prediction tables are pre-scanner
    header-grid tables with the PDF's five columns and their header row
    intact; the Scorecard and the Conclusion keep their Pass 1 shape.
    Independent of the full golden so a re-bless can never silently hand
    a prediction table back to Pass 1's 2-column shards.
    """
    pdf_path = _GOLDEN / "sources" / "p4047r0.pdf"
    if not pdf_path.is_file():
        pytest.skip(f"missing PDF fixture: {pdf_path}")
    sections = run_pipeline(pdf_path).sections
    tables = [s for s in sections if s.kind == SectionKind.TABLE]
    got = {
        (s.page_num, len(s.columns), len(s.columns[0]),
         s.table_kind, s.table_source)
        for s in tables
    }
    assert got == _P4047R0_TABLE_PINS
    prediction = [s for s in tables if s.table_source == "side_by_side_prepass"]
    assert len(prediction) == 7
    for s in prediction:
        assert _header_cells(s) == _P4047R0_PREDICTION_HEADER, s.page_num
