# Copyright (c) 2026 Rob Beeston (rob@cppalliance.org)
# Distributed under the Boost Software License, Version 1.0.
# https://www.boost.org/LICENSE_1_0.txt

"""Pipe-table cells: wrapped lines, line-end hyphens and characters that would break the table."""

import pytest

from tomd.lib.pdf.emit import _render_table_cell
from tomd.lib.pdf.runctx import run_scope
from tomd.lib.pdf.types import Span


def _s(text, **kw):
    return Span(text=text, **kw)


@pytest.mark.parametrize("cell", [
    [_s("a"), _s("\n\n"), _s("b"), _s(" \n"), _s("c")],
    [_s("Bit-precise integers \nSlides for P3666R1")],
    [_s("Allow "), _s("  \n  "), _s("incomplete types")],
])
def test_a_cell_never_holds_a_literal_newline(cell):
    assert "\n" not in _render_table_cell(cell)


def test_wrapped_lines_join_with_br():
    assert _render_table_cell([_s("sockets"), _s("\n"), _s("TLS")]) == "sockets<br>TLS"


def test_pipe_angle_and_asterisk_cannot_break_the_cell():
    assert _render_table_cell([_s("a | b <c> *d*")]) == "a \\| b \\<c> \\*d\\*"


def test_line_end_hyphen_decided_by_the_paper():
    with run_scope() as ctx:
        ctx.lexicon.update({"character": 3})
        assert _render_table_cell([_s("char-"), _s("\n"), _s("acter encoding")]) == "character encoding"
        assert _render_table_cell([_s("non-"), _s("\n"), _s("enforced")]) == "non-enforced"
