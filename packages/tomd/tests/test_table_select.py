# Copyright (c) 2026 Rob Beeston (rob@cppalliance.org)
# Distributed under the Boost Software License, Version 1.0.
# https://www.boost.org/LICENSE_1_0.txt

"""Tests for multi-source table selection (lib.pdf.table) and table output."""

import pytest

from conftest import make_span
from tomd.lib.pdf.types import Block, Line, Section, SectionKind, Confidence, TableCandidate
from tomd.lib.pdf import select
from tomd.lib.pdf.select import (
    table_flags, candidates_agree, select_tables, stitch_pages,
    remove_table_regions,
)


@pytest.fixture(autouse=True)
def _agreement_trusts(monkeypatch):
    """These tests check the agreement logic itself: trust is not withheld for the
    checks still to be ported (select.WITHHOLD_TRUST_UNTIL_VERIFIED, port step 9)."""
    monkeypatch.setattr(select, "WITHHOLD_TRUST_UNTIL_VERIFIED", False)


def _line(text, x, y, page=0, mono=False):
    return Line(spans=[make_span(text, monospace=mono, bbox=(x, y, x + 6 * len(text), y + 10))],
                bbox=(x, y, x + 6 * len(text), y + 10), page_num=page)


def _cand(source, rows, page=0, x0=50, y0=100, row_h=20, col_w=150):
    """A candidate whose cells are laid out on a regular grid."""
    cells = [[[_line(t, x0 + c * col_w, y0 + r * row_h, page)] if t else []
              for c, t in enumerate(row)] for r, row in enumerate(rows)]
    bbox = (x0, y0, x0 + col_w * max(len(r) for r in rows), y0 + row_h * len(rows))
    return TableCandidate(source, cells, {page: bbox})


_GOOD = [["Name", "Value"], ["alpha", "1"], ["beta", "2"]]


class TestTableFlags:
    def _flags(self, rows):
        return table_flags(_cand("tomd", rows))

    def test_clean_table_has_no_flags(self):
        assert self._flags(_GOOD) == []

    def test_bullet_list(self):
        assert "bullet-list" in self._flags([["●", "first item"], ["●", "second item"]])

    def test_code_comment_column(self):
        rows = [["Fun fun;", "// exposition only"], ["Rcvr& rcvr;", "// exposition only"]]
        assert "code-comment-column" in self._flags(rows)

    def test_reference_list_including_glued_label(self):
        rows = [["[N2529]", "Lambda expressions"], ["http://x/n2529.pdf[N2550]", "Revision 4"]]
        assert "reference-list" in self._flags(rows)

    def test_capture_syntax_is_not_a_reference_list(self):
        rows = [["", "() const", "() mutable"], ["[x]", "a", "b"], ["[mutable x]", "c", "d"]]
        assert "reference-list" not in self._flags(rows)

    def test_two_row_toc(self):
        assert "toc-like" in self._flags([["Acknowledgments", "4"], ["References", "5"]])

    def test_single_cell_rows(self):
        rows = [["POLL:", "Modify the paper by adding"], ["a feature test macro and", ""],
                ["send it to LWG.", ""]]
        assert "single-cell-rows" in self._flags(rows)

    def test_constant_first_column(self):
        rows = [["constexpr", f"int f{i}();"] for i in range(5)]
        assert "constant-first-column" in self._flags(rows)

    def test_split_code(self):
        rows = [["A", "F::minimum_copyability =="], ["constraint_level::trivial B", "x &&"],
                ["C", "y"]]
        assert "split-code" in self._flags(rows)


class TestAgreement:
    def test_same_cells_agree(self):
        assert candidates_agree(_cand("tags", _GOOD), _cand("rules", _GOOD))

    def test_whitespace_differences_agree(self):
        other = [["Name", "Value"], ["al pha", "1"], ["beta", "2"]]
        assert candidates_agree(_cand("tags", _GOOD), _cand("rules", other))

    def test_shape_difference_disagrees(self):
        assert not candidates_agree(_cand("tags", _GOOD), _cand("rules", _GOOD[:2]))


class TestSelectTables:
    def _tomd_section(self, rows):
        c = _cand("tomd", rows)
        return Section(kind=SectionKind.TABLE, text="", page_num=0,
                       lines=[ln for r in c.rows for cell in r for ln in cell],
                       columns=[[[s for ln in cell for s in ln.spans] for cell in r] for r in c.rows])

    def test_agreeing_sources_are_high(self):
        out = select_tables([self._tomd_section(_GOOD)], [_cand("rules", _GOOD)], [], [])
        assert len(out) == 1 and out[0].confidence == Confidence.HIGH

    def test_single_source_is_uncertain(self):
        out = select_tables([], [_cand("grid", _GOOD)], [], [])
        assert out[0].confidence == Confidence.UNCERTAIN
        assert "Only one table source" in out[0].metadata["table_note"]

    def test_lost_text_is_uncertain(self):
        # a page line inside the table area that no cell holds
        lost = Block(lines=[_line("delta", 52, 141)], page_num=0)
        cells = Block(lines=[ln for r in _cand("grid", _GOOD).rows for c in r for ln in c],
                      page_num=0)
        out = select_tables([self._tomd_section(_GOOD)], [_cand("rules", _GOOD)], [],
                            [cells, lost])
        assert out[0].confidence == Confidence.UNCERTAIN
        assert "conservation" in out[0].metadata["table_note"]

    def test_conserved_text_stays_high(self):
        cells = Block(lines=[ln for r in _cand("grid", _GOOD).rows for c in r for ln in c],
                      page_num=0)
        out = select_tables([self._tomd_section(_GOOD)], [_cand("rules", _GOOD)], [], [cells])
        assert out[0].confidence == Confidence.HIGH

    def test_disagreement_is_uncertain_with_all_versions(self):
        bad = [["Name", "Value"], ["alpha", "1"], ["gamma", "7"]]
        out = select_tables([self._tomd_section(bad)], [_cand("rules", _GOOD)], [], [])
        assert out[0].confidence == Confidence.UNCERTAIN
        sources = [s for s, _ in out[0].metadata["table_versions"]]
        assert sources == ["rules", "tomd"]

    def test_tags_win_over_ruling_lines(self, monkeypatch):
        other = [["Name", "Value"], ["alpha", "1"], ["gamma", "3"]]
        out = select_tables([], [_cand("grid", other)], [_cand("tags", _GOOD)], [])
        assert out[0].metadata["table_source"] == "tags"


    def test_malformed_tags_rank_below_grid(self):
        tags = _cand("tags", [["Name", "Value"], ["alpha", "1"], ["gamma", "3"]])
        tags.flags.append("tags-malformed")
        out = select_tables([], [_cand("grid", _GOOD)], [tags], [])
        assert out[0].metadata["table_source"] == "grid"


class TestStitchPages:
    def test_continued_table_is_joined_and_repeated_header_dropped(self):
        a = _cand("grid", _GOOD, page=0, y0=600)
        b = _cand("grid", [["Name", "Value"], ["gamma", "3"]], page=1, y0=60)
        out = stitch_pages([a, b], [])
        assert len(out) == 1
        assert out[0].text_rows() == _GOOD + [["gamma", "3"]]
        assert out[0].pages == [0, 1]

    def test_caption_between_parts_prevents_join(self):
        a = _cand("grid", _GOOD, page=0, y0=600)
        b = _cand("grid", [["Name", "Value"], ["gamma", "3"]], page=1, y0=60)
        caption = Block(lines=[_line("Table 2 - Something", 50, 700, page=0)], page_num=0)
        assert len(stitch_pages([a, b], [caption])) == 2


def test_remove_table_regions_keeps_text_outside():
    table = select_tables([], [_cand("grid", _GOOD)], [], [])
    inside = _line("alpha", 52, 121)
    outside = _line("A paragraph below the table", 50, 300)
    blocks = [Block(lines=[inside, outside], page_num=0)]
    out = remove_table_regions(blocks, table)
    assert [ln.text for b in out for ln in b.lines] == ["A paragraph below the table"]


def test_text_in_table_region_but_not_in_table_is_kept():
    """Words inside a table's area that no cell captured stay as text."""
    table = select_tables([], [_cand("grid", _GOOD)], [], [])
    stray = _line("Weak Consensus", 210, 121)
    captured = _line("alpha", 52, 121)
    out = remove_table_regions([Block(lines=[captured, stray], page_num=0)], table)
    assert [ln.text for b in out for ln in b.lines] == ["Weak Consensus"]


class TestPartialReading:
    _ROWS = [["Name", "Kind"], ["alpha", "fast"], ["beta", "slow"], ["gamma", "slow"]]

    def _tomd_section(self, rows):
        return TestSelectTables()._tomd_section(rows)

    def test_tomd_subset_of_ruled_table_is_high(self):
        out = select_tables([self._tomd_section(self._ROWS[1:3])],
                            [_cand("rules", self._ROWS)], [], [])
        assert out[0].confidence == Confidence.HIGH

    def test_tomd_subset_with_wrong_cell_stays_uncertain(self):
        wrong = [["alpha", "fast"], ["beta", "quick"]]
        out = select_tables([self._tomd_section(wrong)], [_cand("rules", self._ROWS)], [], [])
        assert out[0].confidence == Confidence.UNCERTAIN

    def test_subset_rule_only_applies_to_ruled_tables(self):
        out = select_tables([self._tomd_section(self._ROWS[1:3])], [],
                            [_cand("tags", self._ROWS)], [])
        assert out[0].confidence == Confidence.UNCERTAIN


class TestPossibleTables:
    """lib.pdf.flag: table-like text left after selection is marked, not changed."""

    def _rows(self, rows, y0=100, x0=50, col_w=120, page=0):
        return Block(lines=[_line(t, x0 + c * col_w, y0 + r * 14, page)
                            for r, row in enumerate(rows) for c, t in enumerate(row)],
                     page_num=page)


def test_lost_header_row_above_agreeing_sources_is_uncertain():
    # both sources start at "alpha"; the header sits one row above, split
    # into the table's columns, so it was lost by both
    body = [["alpha", "fast"], ["beta", "slow"], ["gamma", "slow"]]
    tomd = TestSelectTables()._tomd_section(body)
    header = Block(lines=[_line("Name", 50, 80), _line("Value", 200, 80)], page_num=0)
    cells = Block(lines=[ln for r in _cand("grid", body).rows for c in r for ln in c], page_num=0)
    out = select_tables([tomd], [_cand("rules", body)], [], [header, cells])
    assert out[0].confidence == Confidence.UNCERTAIN
    assert "lost" in out[0].metadata["table_note"]
    caption = Block(lines=[_line("Table 1 - Values", 50, 80)], page_num=0)
    out = select_tables([tomd], [_cand("rules", body)], [], [caption, cells])
    assert out[0].confidence == Confidence.HIGH


class TestBooktabsRows:
    """lib.pdf.ruled._join_wrapped_lines: booktabs rows from text lines."""

    def _rows(self, lines, mono=False, col_x=(50, 200), col_w=(120, 300)):
        # lines: list of rows of cell texts; a cell's line ends at its text width
        rows = []
        for i, r in enumerate(lines):
            row = []
            for c, t in enumerate(r):
                row.append([_line(t, col_x[c], 100 + 12 * i, mono=mono)] if t else [])
            rows.append(row)
        return rows

    def test_wrapped_cell_joins_the_row_above(self):
        from tomd.lib.pdf.ruled import _join_wrapped_lines
        long = "x" * 50                       # fills column 2 to its right edge
        rows = self._rows([["Paper", "Description"], ["P1", long], ["", "continued"],
                           ["P2", "short"]])
        out = _join_wrapped_lines(rows)
        assert [[" ".join(l.text for l in c) for c in r] for r in out] == [
            ["Paper", "Description"], ["P1", long + " continued"], ["P2", "short"]]

    def test_short_line_does_not_swallow_the_next_row(self):
        from tomd.lib.pdf.ruled import _join_wrapped_lines
        rows = self._rows([["Paper", "Description"], ["P1", "short"], ["", "next entry"],
                           ["P2", "x" * 50]])
        assert len(_join_wrapped_lines(rows)) == 4

    def test_monospace_identifier_table_keeps_its_rows(self):
        from tomd.lib.pdf.ruled import _join_wrapped_lines
        rows = self._rows([["Alias", "Meaning"], ["vertex_t<G>", "vertex"],
                           ["edge_t<G>", "edge"], ["graph_t", "graph"]], mono=True)
        assert len(_join_wrapped_lines(rows)) == 4

    def test_code_body_is_one_row(self):
        from tomd.lib.pdf.ruled import _join_wrapped_lines
        rows = self._rows([["Before", "After"], ["int a;", "auto a = 0;"], ["f(a);", "f(a);"]],
                          mono=True)
        out = _join_wrapped_lines(rows)
        assert len(out) == 2 and [l.text for l in out[1][0]] == ["int a;", "f(a);"]


class TestClassCheck:


    def test_poll_with_text_is_not_trusted(self):
        from tomd.lib.pdf.select import class_check
        assert class_check(_cand("poll", [["SF", "F", "N", "A", "SA"],
                                          ["1", "2", "3", "4", "many"]])) == ""


class TestVerifyLayout:
    """lib.pdf.validate.verify_layout: the grid put back onto the page."""

    def _sec(self, rows):
        return select_tables([], [_cand("grid", rows)], [], [])[0]

    def _words(self, sec):
        # the page's words where the cells say they are
        out = []
        for row in sec.columns:
            for cell in row:
                for s in cell:
                    if s.text.strip() and s.text != "\n":
                        out.append((*s.bbox, s.text.strip(), 0, 0, 0))
        return out


class TestGutter:
    def _rows(self, rows, page=2):
        return Block(lines=[_line(t, 50 + 160 * c, 100 + 14 * r, page)
                            for r, row in enumerate(rows) for c, t in enumerate(row) if t],
                     page_num=page)


