# Copyright (c) 2026 C++ Alliance, Inc. (https://cppalliance.org)
# Distributed under the Boost Software License, Version 1.0.
# https://www.boost.org/LICENSE_1_0.txt

"""Family pins for P3290R4. One module per paper.

A new golden adds a module here and a stem file. It does not edit test_pdf_golden.py.
"""

from pathlib import Path

import pytest

from tomd.lib.pdf import run_pipeline
from tomd.lib.pdf.types import SectionKind

_GOLDEN = Path(__file__).resolve().parent.parent / "fixtures" / "golden"

# Family pins for P3290R4 (#426): five poll grids (header + one numeric
# row, tomd pages 2, 2, 3, 6, 11) and the two `Name | Meaning` enum
# tables of [support.contract.enums] (page 15). All seven are MuPDF-native
# grids (no table_source). The bibliography (pages 18 and 19) must not
# appear here at all: the pin test asserts no TABLE section past page 17.
# A sorted tuple, not a set: two polls share (2, 2, 5).
_P3290R4_TABLE_PINS = (
    (2, 2, 5, "clean_matrix", None),
    (2, 2, 5, "clean_matrix", None),
    (3, 2, 5, "clean_matrix", None),
    (6, 2, 5, "clean_matrix", None),
    (11, 2, 5, "clean_matrix", None),
    # page-16 hyphen left for the cell renderer (port step 12): kind reads key_value
    (15, 4, 2, "key_value", None),
    (15, 6, 2, "clean_matrix", None),
)
_P3290R4_BIBLIOGRAPHY_LABELS = (
    "[N5032]", "[P2264R7]", "[P2900R14]", "[P3191R0]", "[P3290R0]", "[P3311R0]")


def test_p3290r4_bibliography_is_prose_and_table_family_pins():
    """#426 focused guard: the bibliography is never a table again, and the
    seven real tables (five polls, two enum tables) keep their shape. Each
    bibliography entry is one paragraph that starts with its label; no pipe
    row anywhere in the paper carries a bibliography label.
    """
    pdf_path = _GOLDEN / "sources" / "p3290r4.pdf"
    if not pdf_path.is_file():
        pytest.skip(f"missing PDF fixture: {pdf_path}")
    result = run_pipeline(pdf_path)
    tables = [s for s in result.sections if s.kind == SectionKind.TABLE]
    # table_source may be None or str; the key keeps a regression (one poll
    # claimed by a pass, its twin native) an assertion failure, not a TypeError.
    got = sorted(
        ((s.page_num, len(s.columns), len(s.columns[0]),
          s.table_kind, s.table_source) for s in tables),
        key=lambda t: (t[0], t[1], t[2], t[3], t[4] or ""),
    )
    assert tuple(got) == _P3290R4_TABLE_PINS
    assert all(s.page_num <= 17 for s in tables), [s.page_num for s in tables]
    lines = result.md.splitlines()
    for label in _P3290R4_BIBLIOGRAPHY_LABELS:
        entries = [ln for ln in lines if ln.startswith(label + " ")]
        assert len(entries) == 1, (label, entries)
        assert not any(ln.startswith("|") and label in ln for ln in lines), label
