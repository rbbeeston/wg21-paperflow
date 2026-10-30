# Copyright (c) 2026 C++ Alliance, Inc. (https://cppalliance.org)
# Distributed under the Boost Software License, Version 1.0.
# https://www.boost.org/LICENSE_1_0.txt

"""Unit tests for new table detection passes added in PR #109."""

from types import SimpleNamespace

import pytest

from tomd.domain.elements import Confidence
from tomd.lib.pdf.types import Span, Line, Block, Section, SectionKind
from tomd.lib.pdf.table import (
    _block_column_positions,
    _build_rows_sequential,
    _build_rows_ybanded,
    _columns_count_match,
    _detect_horizontal_row_tables,
    _detect_side_by_side_tables,
    detect_tables,
    _block_horizontal_row,
    _block_on_one_column,
    _gap_asymmetry_reject,
    _grid_rows_left_behind,
    _is_column_aligned_orphan,
    _is_trailing_continuation,
    _pass1_region_incomplete,
    _try_orphan_lookahead,
    _try_split_row,
    _try_wrapped_partial_row,
    _try_cross_page_continuation,
    _filter_overlapping_mupdf_tables,
    _rot_midpoint,
    _rows_from_drawn_grid,
    _detect_mupdf_native_tables,
    _detect_banded_rotated_tables,
)
from tomd.lib.pdf.pipeline import (
    _column_of,
    _column_aware_sort,
    _detect_column_split,
    _detect_drawing_grids,
    _drop_leading_contents,
    _insert_table_sections,
)

# Page height of a 595x842 portrait page (P3100R6 geometry), shared by
# the drawing-grid tests and the rotation fixtures below.
_PAGE_H = 842.0


def _line(text: str, x0: float, y0: float, x1: float, y1: float) -> Line:
    """Create a Line with explicit bbox."""
    return Line(
        spans=[Span(text=text, font_size=10.0)],
        bbox=(x0, y0, x1, y1),
    )


def _block_from_lines(lines: list[Line]) -> Block:
    """Create a Block from pre-built lines."""
    x0 = min(l.bbox[0] for l in lines) if lines else 0.0
    y0 = min(l.bbox[1] for l in lines) if lines else 0.0
    x1 = max(l.bbox[2] for l in lines) if lines else 0.0
    y1 = max(l.bbox[3] for l in lines) if lines else 0.0
    return Block(lines=lines, bbox=(x0, y0, x1, y1), page_num=0)


class TestGapAsymmetryReject:
    """Tests for _gap_asymmetry_reject: filters false-positive table rows."""

    def test_fewer_than_3_lines_accepted(self):
        lines = [
            _line("A", 10, 100, 50, 110),
            _line("B", 100, 100, 150, 110),
        ]
        assert not _gap_asymmetry_reject(lines)

    def test_uniform_gaps_accepted(self):
        """Three cells with roughly equal spacing should pass."""
        lines = [
            _line("Col1", 10, 100, 60, 110),
            _line("Col2", 80, 100, 130, 110),
            _line("Col3", 150, 100, 200, 110),
        ]
        assert not _gap_asymmetry_reject(lines)

    def test_extreme_gap_asymmetry_rejected(self):
        """WG21 heading pattern: '4  General  [general]' with wildly uneven gaps."""
        lines = [
            _line("4", 72, 100, 82, 110),
            _line("General", 120, 100, 180, 110),
            _line("[general]", 400, 100, 470, 110),
        ]
        assert _gap_asymmetry_reject(lines)

    def test_moderate_gap_extreme_width_3cells_rejected(self):
        """Reference list pattern: tiny marker + long description.

        Gap between cell 1-2 = 5, gap between cell 2-3 = 20, ratio = 4.0 (> 3).
        Width of cell 1 = 23, cell 2 = 10, cell 3 = 380, ratio = 38 (> 10).
        """
        lines = [
            _line("(1.1)", 72, 100, 95, 110),
            _line("—", 100, 100, 110, 110),
            _line("IEC Electropedia: Very long description text", 130, 100, 510, 110),
        ]
        assert _gap_asymmetry_reject(lines)

    def test_4plus_cells_uniform_gaps_accepted(self):
        """4 cells with roughly uniform gaps should pass (real table)."""
        lines = [
            _line("A", 10, 100, 50, 110),
            _line("B", 70, 100, 110, 110),
            _line("C", 130, 100, 170, 110),
            _line("D", 190, 100, 230, 110),
        ]
        assert not _gap_asymmetry_reject(lines)

    def test_overlapping_gaps_not_counted(self):
        """When gaps are negative (overlapping), fewer than 2 positive gaps -> accept."""
        lines = [
            _line("A", 10, 100, 60, 110),
            _line("B", 50, 100, 110, 110),
            _line("C", 120, 100, 170, 110),
        ]
        assert not _gap_asymmetry_reject(lines)


def _bbox_block(lines: list[Line], monospace: bool = False) -> Block:
    """Build a Block whose bbox encloses its lines (optionally monospace)."""
    if monospace:
        for ln in lines:
            for sp in ln.spans:
                sp.monospace = True
    x0 = min(ln.bbox[0] for ln in lines)
    y0 = min(ln.bbox[1] for ln in lines)
    x1 = max(ln.bbox[2] for ln in lines)
    y1 = max(ln.bbox[3] for ln in lines)
    return Block(lines=lines, bbox=(x0, y0, x1, y1), page_num=0)


class TestWrappedPartialRow:
    """Tests for _try_wrapped_partial_row (Pass 1 Branch 3b).

    Models the P4182R1 Table A defect: a data row whose Heap and Hosted
    cells sit 41pt apart (below _COLUMN_GAP_THRESHOLD), so MuPDF groups
    them into one non-columnar block that splits the table without this
    branch.
    """

    # Table A header columns: Category, Coro, TLS, PMR, Heap, Hosted.
    REF_COLS = [66.7, 294.2, 339.1, 373.4, 438.8, 480.0]
    COLUMN_XS = frozenset(REF_COLS)

    def _established_table(self) -> list[Block]:
        """Header + one data row, ending at y1=472.2 (the Full RTOS anchor)."""
        header = _bbox_block([_line(t, x, 344.6, x + 20, 358.2)
                              for t, x in zip("ABCDEF", self.REF_COLS)])
        anchor = _bbox_block([
            _line("Full RTOS", 66.7, 458.6, 196.4, 472.2),
            _line("Yes", 294.2, 458.6, 307.1, 472.2),
            _line("Yes", 339.1, 458.6, 352.0, 472.2),
            _line("Hosted", 373.4, 458.6, 400.7, 472.2),
        ])
        return [header, anchor]

    def _right_fragment(self) -> Block:
        """Heap + Hosted cells, same y-band as the anchor, 41pt gap."""
        return _bbox_block([
            _line("Yes", 438.8, 458.6, 451.6, 472.2),
            _line("Partial to", 480.0, 458.6, 514.8, 472.2),
        ])

    def test_narrow_gap_right_fragment_absorbed(self):
        blocks = self._established_table() + [self._right_fragment()]
        result = _try_wrapped_partial_row(
            blocks, 2, self.REF_COLS, self.COLUMN_XS, blocks[:2])
        assert result is not None
        assert result.advance_to == 3
        assert result.multi_orphan is True
        assert id(blocks[2]) in result.absorbed_ids

    def test_left_margin_prose_rejected(self):
        """A wrapped paragraph at the label column (index 0) is not a row."""
        prose = _bbox_block([
            _line("Some prose that wraps onto", 66.7, 500.0, 300.0, 512.0),
            _line("a second physical line here", 66.7, 514.0, 300.0, 526.0),
        ])
        blocks = self._established_table() + [prose]
        assert _try_wrapped_partial_row(
            blocks, 2, self.REF_COLS, self.COLUMN_XS, blocks[:2]) is None

    def test_columnar_block_rejected(self):
        """A block whose gap exceeds the threshold is handled by Branches 1-3."""
        columnar = _bbox_block([
            _line("Yes", 294.2, 458.6, 307.1, 472.2),
            _line("Hosted", 373.4, 458.6, 400.7, 472.2),
        ])
        blocks = self._established_table() + [columnar]
        assert _try_wrapped_partial_row(
            blocks, 2, self.REF_COLS, self.COLUMN_XS, blocks[:2]) is None

    def test_monospace_fragment_rejected(self):
        frag = _bbox_block([
            _line("Yes", 438.8, 458.6, 451.6, 472.2),
            _line("code", 480.0, 458.6, 514.8, 472.2),
        ], monospace=True)
        blocks = self._established_table() + [frag]
        assert _try_wrapped_partial_row(
            blocks, 2, self.REF_COLS, self.COLUMN_XS, blocks[:2]) is None

    def test_unestablished_table_rejected(self):
        """Need header + a data row before absorbing a fragment."""
        blocks = self._established_table()[:1] + [self._right_fragment()]
        assert _try_wrapped_partial_row(
            blocks, 1, self.REF_COLS, self.COLUMN_XS, blocks[:1]) is None

    def test_far_y_gap_rejected(self):
        frag = _bbox_block([
            _line("Yes", 438.8, 600.0, 451.6, 612.0),
            _line("Partial to", 480.0, 600.0, 514.8, 612.0),
        ])
        blocks = self._established_table() + [frag]
        assert _try_wrapped_partial_row(
            blocks, 2, self.REF_COLS, self.COLUMN_XS, blocks[:2]) is None


class TestOrphanLookaheadMonospaceTwoColumn:
    """Tests for _try_orphan_lookahead (Pass 1 Branch 4) on a 2-column
    monospace table.

    Models P0957R8 p.28 (tomd page 27): a bordered 2x2 table of type-trait
    expressions set in a monospace font, whose cell (1, 2) wraps onto a
    second physical line ("HasNothrowDestructor"). MuPDF emits that wrapped
    tail as its own single-line block aligned to column 2. Branch 4a must
    take it (the next block is a full 2-column row) so the table keeps
    scanning; a former guard that returned None for any 2-column monospace
    table ended the scan there and the whole table fell back to a cpp fence.
    """

    REF_COLS = [100.0, 300.0]
    COLUMN_XS = frozenset(REF_COLS)

    def _header(self) -> Block:
        return _bbox_block([
            _line("HasNothrowMoveAssignment", 100.0, 100.0, 240.0, 112.0),
            _line("HasNothrowMoveConstructor &&", 300.0, 100.0, 470.0, 112.0),
        ], monospace=True)

    def _wrapped_tail(self) -> Block:
        return _bbox_block([
            _line("HasNothrowDestructor", 300.0, 114.0, 420.0, 126.0),
        ], monospace=True)

    def _second_row(self) -> Block:
        return _bbox_block([
            _line("HasMoveAssignment", 100.0, 130.0, 210.0, 142.0),
            _line("HasMoveConstructor && HasDestructor", 300.0, 130.0, 500.0, 142.0),
        ], monospace=True)

    def test_wrapped_monospace_tail_absorbed_before_full_row(self):
        blocks = [self._header(), self._wrapped_tail(), self._second_row()]
        result = _try_orphan_lookahead(
            blocks, 1, self.REF_COLS, self.COLUMN_XS, blocks[:1], set())
        assert result is not None
        assert result.advance_to == 2
        # Column-1 tails are marked partial regardless of font (see
        # _try_single_orphan), so the tail merges back into cell (1, 2).
        assert result.absorbed_ids == frozenset({id(blocks[1])})

    def test_tail_without_confirming_row_rejected(self):
        """The lookahead needs a following block; a lone tail is not a row."""
        blocks = [self._header(), self._wrapped_tail()]
        assert _try_orphan_lookahead(
            blocks, 1, self.REF_COLS, self.COLUMN_XS, blocks[:1], set()) is None

    def test_unaligned_monospace_line_rejected(self):
        """A monospace line off both columns is code, not a wrapped cell."""
        stray = _bbox_block([
            _line("return 0;", 180.0, 114.0, 240.0, 126.0),
        ], monospace=True)
        blocks = [self._header(), stray, self._second_row()]
        assert _try_orphan_lookahead(
            blocks, 1, self.REF_COLS, self.COLUMN_XS, blocks[:1], set()) is None


class _FakePage:
    """Stub page exposing get_drawings()/get_text() with synthetic items.

    `lines` become "l" items, `rects` become "re" items (filled
    rectangles, the border primitive of HTML-to-PDF engines).
    """

    def __init__(self, lines, text_lines=None, rects=None):
        self._lines = lines
        self._text_lines = text_lines or []
        self._rects = rects or []

    def get_drawings(self):
        drawings = [
            {"items": [("l", SimpleNamespace(x=x0, y=y0),
                        SimpleNamespace(x=x1, y=y1))]}
            for x0, y0, x1, y1 in self._lines
        ]
        drawings.extend(
            {"items": [("re", SimpleNamespace(
                x0=x0, y0=y0, x1=x1, y1=y1, width=x1 - x0, height=y1 - y0))]}
            for x0, y0, x1, y1 in self._rects
        )
        return drawings

    def get_text(self, kind, flags=0):
        return {
            "blocks": [{
                "type": 0,
                "lines": [{"bbox": bbox} for bbox in self._text_lines],
            }]
        }


def _grid_lines(x0, x1, ys):
    """Horizontal rules at each y plus full-height verticals at x0/x1."""
    lines = [(x0, y, x1, y) for y in ys]
    lines.append((x0, ys[0], x0, ys[-1]))
    lines.append((x1, ys[0], x1, ys[-1]))
    return lines


def _two_col_text(ys, left_x=200.0, right_x=300.0):
    """Two side-by-side text cells per row band (a real table)."""
    cells = []
    for y in ys:
        cells.append((left_x, y, left_x + 40, y + 11))
        cells.append((right_x, y, right_x + 90, y + 11))
    return cells


class TestDetectDrawingGrids:
    """Tests for _detect_drawing_grids: bordered grids find_tables missed."""

    PAGE_H = _PAGE_H

    def test_p3100r6_geometry_detected(self):
        """The real P3100R6 page-66 grid (8 h-rules, verticals) is found."""
        ys = [565.0, 578.9, 581.3, 595.2, 609.2, 623.1, 637.1, 637.5]
        text = _two_col_text([566.1, 583.0, 597.0, 610.9, 624.9])
        page = _FakePage(_grid_lines(190.0, 405.0, ys), text)
        grids = _detect_drawing_grids(page, self.PAGE_H, [])
        assert len(grids) == 1
        bbox = grids[0]["bbox"]
        assert bbox[0] == 190.0 and bbox[2] == 405.0
        # Synthetic entry carries the find_tables shape: the 8 rules
        # dedupe to 6 (578.9/581.3 and 637.1/637.5 merge), giving 5 rows
        # between two outer verticals, one cell per row.
        assert grids[0]["source"] == "drawing_grid"
        assert grids[0]["row_count"] == 5
        assert grids[0]["col_count"] == 1
        assert len(grids[0]["cells"]) == 5
        assert grids[0]["cells"][0][1] == 565.0 and grids[0]["cells"][-1][3] == 637.1

    def test_full_page_margin_rules_rejected(self):
        """Full-page-height rules (wording margins) must not become grids."""
        ys = [74.0, 190.0, 306.0, 422.0, 538.0, 654.0, 769.0]
        text = _two_col_text([100.0, 220.0, 340.0, 460.0, 580.0],
                             left_x=210.0, right_x=270.0)
        page = _FakePage(_grid_lines(205.0, 320.0, ys), text)
        grids = _detect_drawing_grids(page, self.PAGE_H, [])
        assert grids == []

    def test_too_few_horizontals_rejected(self):
        ys = [565.0, 595.0, 637.0]
        text = _two_col_text([570.0, 600.0])
        page = _FakePage(_grid_lines(190.0, 405.0, ys), text)
        assert _detect_drawing_grids(page, self.PAGE_H, []) == []

    def test_missing_vertical_borders_rejected(self):
        """Horizontal rules without side borders (e.g. hr separators)."""
        ys = [565.0, 580.0, 595.0, 610.0, 625.0]
        text = _two_col_text([567.0, 582.0, 597.0, 612.0])
        page = _FakePage([(190.0, y, 405.0, y) for y in ys], text)
        assert _detect_drawing_grids(page, self.PAGE_H, []) == []

    def test_already_covered_by_find_tables_skipped(self):
        ys = [565.0, 580.0, 595.0, 610.0, 625.0]
        text = _two_col_text([567.0, 582.0, 597.0, 612.0])
        page = _FakePage(_grid_lines(190.0, 405.0, ys), text)
        existing = [{"bbox": (185.0, 560.0, 410.0, 630.0)}]
        assert _detect_drawing_grids(page, self.PAGE_H, existing) == []

    def test_boxed_code_single_column_rejected(self):
        """Bordered wording/code boxes (one line per y-band) are not tables."""
        ys = [565.0, 580.0, 595.0, 610.0, 625.0]
        # One text line per band, varying indentation (code box pattern).
        text = [
            (200.0, 567.0, 380.0, 578.0),
            (215.0, 582.0, 390.0, 593.0),
            (215.0, 597.0, 350.0, 608.0),
            (200.0, 612.0, 360.0, 623.0),
        ]
        page = _FakePage(_grid_lines(190.0, 405.0, ys), text)
        assert _detect_drawing_grids(page, self.PAGE_H, []) == []

    def test_mostly_single_cell_bands_rejected(self):
        """A grid where most rows hold one cell is a box stack, not a table."""
        ys = [565.0, 580.0, 595.0, 610.0, 625.0, 640.0]
        text = [
            # 2 multi-cell bands...
            (200.0, 567.0, 240.0, 578.0), (300.0, 567.0, 390.0, 578.0),
            (200.0, 582.0, 240.0, 593.0), (300.0, 582.0, 390.0, 593.0),
            # ...but 3 single-cell bands dominate
            (200.0, 597.0, 390.0, 608.0),
            (200.0, 612.0, 390.0, 623.0),
            (200.0, 627.0, 390.0, 638.0),
        ]
        page = _FakePage(_grid_lines(190.0, 405.0, ys), text)
        assert _detect_drawing_grids(page, self.PAGE_H, []) == []


def _cell_edge_rects(row_ys, col_xs, thickness=0.6):
    """Borders as one thin filled rectangle per cell edge (P4016R0 style).

    Every interior rule is drawn twice (bottom of one cell, top of the
    next), every vertical once per row band.
    """
    rects = []
    for r in range(len(row_ys) - 1):
        y0, y1 = row_ys[r], row_ys[r + 1]
        for c in range(len(col_xs) - 1):
            x0, x1 = col_xs[c], col_xs[c + 1]
            rects.append((x0, y0, x1, y0 + thickness))
            rects.append((x0, y1, x1, y1 + thickness))
            rects.append((x0, y0, x0 + thickness, y1 + thickness))
            rects.append((x1, y0, x1 + thickness, y1 + thickness))
    return rects


class TestDrawingGridsFromRectangles:
    """P4016R0 draws every table border as a 0.6pt filled rectangle and
    never as a line item; find_tables() returns a full-page phantom on
    those pages. The fallback reads thin rectangles as rules, merges the
    per-cell edge pieces, and separates the table from the other
    full-width rules on the page by the vertical rules that bridge them.
    """

    PAGE_H = 842.0
    # B.1 (tomd page 30): 3 rows, 3 columns.
    ROW_YS = [738.4, 751.7, 764.4, 777.6]
    COL_XS = [57.0, 103.7, 202.3, 254.7]

    def _b1_text(self):
        cells = []
        for y in (740.5, 753.8, 766.5):
            cells.append((60.7, y, 100.0, y + 9.0))
            cells.append((107.4, y, 190.0, y + 9.0))
            cells.append((206.0, y, 250.0, y + 9.0))
        return cells

    def _b1_page(self, extra_rects=()):
        rects = _cell_edge_rects(self.ROW_YS, self.COL_XS)
        # Header cell fills: wide and 13pt tall, not rules.
        for c in range(3):
            rects.append((self.COL_XS[c], 738.4, self.COL_XS[c + 1], 751.7))
        # Page background box (what find_tables() turns into a phantom).
        rects.append((57.0, 57.0, 537.2, 779.4))
        rects.extend(extra_rects)
        return _FakePage([], self._b1_text(), rects=rects)

    def test_thin_rectangles_form_one_grid(self):
        grids = _detect_drawing_grids(self._b1_page(), self.PAGE_H, [])
        assert len(grids) == 1
        g = grids[0]
        assert g["source"] == "drawing_grid"
        assert (g["row_count"], g["col_count"]) == (3, 3)
        assert len(g["cells"]) == 9
        assert g["bbox"][1] == pytest.approx(738.7, abs=0.1)
        assert g["bbox"][3] == pytest.approx(777.9, abs=0.1)
        # Cell (row 1, col 1) is bounded by the drawn rules.
        x0, y0, x1, y1 = g["cells"][4]
        assert (x0, x1) == pytest.approx((104.0, 202.6), abs=0.1)
        assert (y0, y1) == pytest.approx((752.0, 765.0), abs=0.5)

    def test_separators_and_note_box_stay_out_of_the_grid(self):
        # A full-width section rule (no verticals) and a two-rule note
        # box with its own side borders share the 57-537 span with a
        # table; the chain split keeps only the table's rules.
        wide_rows = [400.0, 413.0, 426.0, 439.0]
        wide_cols = [57.0, 200.0, 537.0]
        rects = _cell_edge_rects(wide_rows, wide_cols)
        rects.append((57.0, 615.6, 537.2, 616.2))  # section separator
        rects.extend([(57.0, 57.0, 537.2, 57.6), (57.0, 136.6, 537.2, 137.1),
                      (57.0, 57.0, 57.6, 137.1), (536.7, 57.0, 537.2, 137.1)])
        text = []
        for y in (402.0, 415.0, 428.0):
            text.append((60.0, y, 150.0, y + 9.0))
            text.append((204.0, y, 400.0, y + 9.0))
        text.append((60.0, 70.0, 500.0, 79.0))  # note box prose
        page = _FakePage([], text, rects=rects)
        grids = _detect_drawing_grids(page, self.PAGE_H, [])
        assert len(grids) == 1
        assert grids[0]["bbox"][1] == pytest.approx(400.3, abs=0.1)
        assert grids[0]["bbox"][3] == pytest.approx(439.3, abs=0.1)
        assert grids[0]["row_count"] == 3

    def test_tall_centred_cells_counted_per_rule_band(self):
        # K.1 pattern: the Notes cell wraps to six lines while Platform
        # is one line. Per rule band both columns have text, so the row
        # is multi-cell even though five text-y levels hold one line.
        rows = [100.0, 200.0, 300.0]
        cols = [57.0, 300.0, 537.0]
        rects = _cell_edge_rects(rows, cols)
        text = []
        for band_top in (100.0, 200.0):
            text.append((60.0, band_top + 45.0, 200.0, band_top + 54.0))
            for k in range(6):
                y = band_top + 10.0 + k * 13.0
                text.append((304.0, y, 530.0, y + 9.0))
        page = _FakePage([], text, rects=rects)
        grids = _detect_drawing_grids(page, self.PAGE_H, [])
        assert len(grids) == 1
        assert (grids[0]["row_count"], grids[0]["col_count"]) == (2, 2)

    def test_phantom_free_coverage_skips_the_grid(self):
        # The caller hands over phantom-filtered find_tables() entries; a
        # tight region over the same table still counts as coverage.
        tight = [{"bbox": (57.2, 738.6, 254.9, 777.8)}]
        assert _detect_drawing_grids(self._b1_page(), self.PAGE_H, tight) == []


def _drawing_grid_entry(row_ys, col_xs, page_h=842.0, drawn=True):
    """A page_mupdf_tables entry in the shape _detect_drawing_grids emits."""
    cells = [(col_xs[c], row_ys[r], col_xs[c + 1], row_ys[r + 1])
             for r in range(len(row_ys) - 1) for c in range(len(col_xs) - 1)]
    entry = {
        "bbox": (col_xs[0], row_ys[0], col_xs[-1], row_ys[-1]),
        "row_count": len(row_ys) - 1,
        "col_count": len(col_xs) - 1,
        "cells": cells,
        "header_names": None,
        "extract": [],
        "rot": None,
        "max_cell_h": max(b - a for a, b in zip(row_ys, row_ys[1:])),
        "tbl_h": row_ys[-1] - row_ys[0],
        "page_coverage": (row_ys[-1] - row_ys[0]) / page_h,
    }
    if drawn:
        entry["source"] = "drawing_grid"
    return entry


class TestDrawingGridConsumers:
    """table.py treats a drawing-grid entry as verified geometry: Pass 1
    stands down for it only on a partial view, Pass 5 drops the
    find_tables()-specific guards (min size, label transposition).
    """

    ROW_YS = [100.0, 115.0, 130.0, 145.0, 160.0, 175.0]
    COL_XS = [57.0, 290.0, 537.0]

    def _rows(self, n, first_y=102.0, step=15.0):
        labels = ["Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta"]
        blocks = []
        for k in range(n):
            y = first_y + k * step
            blocks.append(_bbox_block([
                _line(labels[k], 60.0, y, 120.0, y + 9.0),
                _line(f"value {k}", 294.0, y, 380.0, y + 9.0)]))
        return blocks

    def test_pass1_keeps_a_complete_table_over_a_drawn_grid(self):
        blocks = self._rows(5)
        grid = {0: [_drawing_grid_entry(self.ROW_YS, self.COL_XS)]}
        tables, remaining = detect_tables(blocks, page_mupdf_tables=grid)
        assert len(tables) == 1 and remaining == []
        assert tables[0].table_source == "horizontal_rows"
        assert len(tables[0].columns) == 5

    def test_find_tables_region_with_five_rows_still_defers(self):
        # Control: the same region as a find_tables() guess keeps the
        # old rule (5+ rows overlapping Pass 1 -> Pass 5 assembles).
        blocks = self._rows(5)
        grid = {0: [_drawing_grid_entry(self.ROW_YS, self.COL_XS, drawn=False)]}
        tables, _ = detect_tables(blocks, page_mupdf_tables=grid)
        assert len(tables) == 1
        assert tables[0].table_source is None

    def test_pass1_defers_when_the_drawn_grid_holds_unclaimed_rows(self):
        # K.1 pattern: Pass 1 assembles some rows, the grid contains
        # more blocks it cannot take (a one-line row). Pass 5 builds the
        # whole grid, including the leftover.
        blocks = self._rows(5)
        y = 102.0 + 5 * 15.0
        blocks.append(_bbox_block([_line("Zeta", 60.0, y, 120.0, y + 9.0)]))
        row_ys = self.ROW_YS + [190.0]
        grid = {0: [_drawing_grid_entry(row_ys, self.COL_XS)]}
        tables, remaining = detect_tables(blocks, page_mupdf_tables=grid)
        assert len(tables) == 1 and remaining == []
        assert tables[0].table_source is None
        col0 = ["".join(s.text for s in row[0]).strip()
                for row in tables[0].columns]
        assert col0 == ["Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta"]

    def test_pass5_accepts_a_short_drawn_grid(self):
        # B.1 is 39pt tall; the find_tables() min-size guard would drop it.
        row_ys = [738.7, 752.0, 764.7, 777.9]
        col_xs = [57.3, 104.0, 202.6, 255.0]
        blocks = []
        for k, y in enumerate((740.5, 753.8, 766.5)):
            blocks.append(_bbox_block([
                _line(f"a{k}", 60.7, y, 100.0, y + 9.0),
                _line(f"b{k}", 107.4, y, 190.0, y + 9.0),
                _line(f"c{k}", 206.0, y, 250.0, y + 9.0)]))
        drawn = {0: [_drawing_grid_entry(row_ys, col_xs)]}
        tables, used = _detect_mupdf_native_tables(blocks, drawn)
        assert len(tables) == 1 and used == {0, 1, 2}
        assert len(tables[0].columns) == 3
        assert all(len(row) == 3 for row in tables[0].columns)
        guessed = {0: [_drawing_grid_entry(row_ys, col_xs, drawn=False)]}
        assert _detect_mupdf_native_tables(blocks, guessed) == ([], set())

    # F.1 pattern (P4016R0 page 38): the Rationale cell of the middle
    # row is three lines tall; MuPDF puts its first line into the block
    # of the row above and its last line into the block of the row
    # below. Grid rows 95-115 (header), 115-130, 130-190, 190-215.
    _F1_ROW_YS = [95.0, 115.0, 130.0, 190.0, 215.0]

    def _f1_blocks(self):
        return [
            _bbox_block([_line("Decision", 60.0, 100.0, 110.0, 109.0),
                         _line("Rationale", 294.0, 100.0, 350.0, 109.0)]),
            _bbox_block([_line("Topology", 60.0, 118.0, 110.0, 127.0),
                         _line("O(log N) depth", 294.0, 118.0, 380.0, 127.0),
                         _line("Algebraic clarity;", 294.0, 133.0, 400.0, 142.0)]),
            _bbox_block([_line("Init placement", 60.0, 155.0, 140.0, 164.0),
                         _line("compatible with the", 294.0, 148.0, 420.0, 157.0),
                         _line("reduce-family API", 294.0, 163.0, 400.0, 172.0)]),
            _bbox_block([_line("Split rule", 60.0, 198.0, 120.0, 207.0),
                         _line("([reduce]).", 294.0, 178.0, 360.0, 187.0),
                         _line("Unique grouping", 294.0, 198.0, 400.0, 207.0)]),
        ]

    @staticmethod
    def _cell_texts(section: Section) -> list[list[str]]:
        return [["".join(s.text for s in cell).strip() for cell in row]
                for row in section.columns]

    def test_pass1_recuts_rows_along_a_complete_drawn_grid(self):
        blocks = self._f1_blocks()
        grid = {0: [_drawing_grid_entry(self._F1_ROW_YS, self.COL_XS)]}
        tables, remaining = detect_tables(blocks, page_mupdf_tables=grid)
        assert len(tables) == 1 and remaining == []
        assert tables[0].table_source == "horizontal_rows"
        assert self._cell_texts(tables[0]) == [
            ["Decision", "Rationale"],
            ["Topology", "O(log N) depth"],
            ["Init placement",
             "Algebraic clarity;\ncompatible with the\nreduce-family API\n"
             "([reduce])."],
            ["Split rule", "Unique grouping"],
        ]

    def test_pass1_block_rows_without_the_grid_show_the_defect(self):
        # Control: by block, the tall cell's lines land in the rows above
        # and below (what the golden showed before the fix).
        blocks = self._f1_blocks()
        tables, _ = detect_tables(blocks)
        assert len(tables) == 1
        cells = self._cell_texts(tables[0])
        assert cells[1][1] == "O(log N) depth\nAlgebraic clarity;"
        assert cells[3][1] == "([reduce]).\nUnique grouping"

    def test_recut_keeps_pass1_rows_when_a_line_fits_no_cell(self):
        blocks = self._f1_blocks()
        # Grid that stops above the last row: "Split rule" fits no cell.
        grid = _drawing_grid_entry(self._F1_ROW_YS[:-1], self.COL_XS)
        assert _rows_from_drawn_grid(blocks, grid, 0, 2) is None
        tables, _ = detect_tables(blocks, page_mupdf_tables={0: [grid]})
        assert len(tables) == 1
        assert len(tables[0].columns) == 4  # Pass 1's own rows kept

    def test_recut_needs_the_full_cell_list(self):
        grid = _drawing_grid_entry(self._F1_ROW_YS, self.COL_XS)
        grid["cells"] = grid["cells"][:-1]
        assert _rows_from_drawn_grid(self._f1_blocks(), grid, 0, 2) is None
        grid = _drawing_grid_entry(self._F1_ROW_YS, self.COL_XS)
        grid["row_count"] = 1
        assert _rows_from_drawn_grid(self._f1_blocks(), grid, 0, 2) is None

    def test_recut_refuses_blocks_from_another_page(self):
        # A cross-page Pass 1 table: the grid's cells are page-0
        # coordinates, the page-1 block's lines would land in the top
        # rows. Pass 1 keeps its own rows instead.
        blocks = self._f1_blocks()
        blocks.append(Block(
            lines=[_line("Next page", 60.0, 100.0, 120.0, 109.0),
                   _line("continued", 294.0, 100.0, 350.0, 109.0)],
            bbox=(60.0, 100.0, 350.0, 109.0), page_num=1))
        grid = _drawing_grid_entry(self._F1_ROW_YS, self.COL_XS)
        assert _rows_from_drawn_grid(blocks, grid, 0, 2) is None

    def test_recut_refuses_a_grid_with_other_column_count(self):
        # Three drawn columns against Pass 1's two: merged cells or a
        # grid that is not this table. No re-cut.
        grid = _drawing_grid_entry(
            self._F1_ROW_YS, [57.0, 200.0, 290.0, 537.0])
        assert _rows_from_drawn_grid(self._f1_blocks(), grid, 0, 2) is None

    def test_recut_places_by_left_edge_and_sorts_lines_by_y(self):
        # Block order puts the lower fragment first; the cell text must
        # still read top to bottom. A line whose left edge starts in
        # column 0 but whose midpoint would fall into column 1 (long
        # merged-cell line) stays in column 0.
        blocks = [
            _bbox_block([_line("Decision", 60.0, 100.0, 110.0, 109.0),
                         _line("Rationale", 294.0, 100.0, 350.0, 109.0)]),
            _bbox_block([_line("Topology", 60.0, 118.0, 110.0, 127.0),
                         _line("second line", 294.0, 133.0, 400.0, 142.0)]),
            _bbox_block([_line("first line", 294.0, 118.0, 400.0, 127.0),
                         _line("A wide note across both columns",
                               60.0, 198.0, 500.0, 207.0)]),
        ]
        grid = _drawing_grid_entry([95.0, 115.0, 190.0, 215.0], self.COL_XS)
        recut = _rows_from_drawn_grid(blocks, grid, 0, 2)
        assert recut is not None
        rows, _ = recut
        texts = [["".join(s.text for s in c) for c in r] for r in rows]
        assert texts == [
            ["Decision", "Rationale"],
            ["Topology", "first line\nsecond line"],
            ["A wide note across both columns", ""],
        ]

    def test_recut_drops_drawn_rows_without_text(self):
        # An extra empty drawn row band (rule doubled) yields no row.
        rows_ys = self._F1_ROW_YS[:-1] + [212.0, 215.0]
        grid = _drawing_grid_entry(rows_ys, self.COL_XS)
        recut = _rows_from_drawn_grid(self._f1_blocks(), grid, 0, 2)
        assert recut is not None
        rows, all_lines = recut
        assert len(rows) == 4
        assert len(all_lines) == 11

    def test_pass5_never_transposes_a_drawn_two_column_grid(self):
        row_ys = [100.0, 160.0, 220.0, 280.0]
        col_xs = [57.0, 200.0, 537.0]
        blocks = []
        for k, y in enumerate((110.0, 170.0, 230.0)):
            blocks.append(_bbox_block([
                _line(["Before", "After", "Later"][k], 60.0, y, 120.0, y + 9.0),
                _line(f"description {k}", 204.0, y, 400.0, y + 9.0)]))
        drawn = {0: [_drawing_grid_entry(row_ys, col_xs)]}
        tables, _ = _detect_mupdf_native_tables(blocks, drawn)
        assert len(tables) == 1
        assert len(tables[0].columns) == 3
        assert all(len(row) == 2 for row in tables[0].columns)
        guessed = {0: [_drawing_grid_entry(row_ys, col_xs, drawn=False)]}
        tables, _ = _detect_mupdf_native_tables(blocks, guessed)
        assert len(tables) == 1
        assert len(tables[0].columns[0]) == 3  # labels became the header


# 90-degree rotation matrix of a 595x842 portrait page (P3100R6 appendix
# geometry): maps unrotated page space into reading space via
# (x, y) -> (842 - y, x).
_ROT90 = (0.0, 1.0, -1.0, 0.0, _PAGE_H, 0.0)


def _rotated_line(text: str, rx: float, ry: float) -> Line:
    """Line whose page-space bbox maps to reading-space center (rx, ry)."""
    x, y = ry, _PAGE_H - rx
    return Line(spans=[Span(text=text, font_size=10.0)],
                bbox=(x - 5, y - 5, x + 5, y + 5))


class TestRotMidpoint:
    def test_no_rotation_returns_plain_midpoint(self):
        assert _rot_midpoint((10.0, 20.0, 30.0, 40.0), None) == (20.0, 30.0)

    def test_rot90_maps_into_reading_space(self):
        # Page-space midpoint (100, 742) -> reading space (842-742, 100).
        assert _rot_midpoint((90.0, 732.0, 110.0, 752.0), _ROT90) == (
            100.0, 100.0)


class TestMupdfNativeRotatedPage:
    """Pass 5 on rotated pages: cell assignment uses reading space.

    Models the P3100R6 appendix (pages rotated 90 degrees): find_tables()
    reports table/cell bboxes in reading space while extract_mupdf block
    bboxes stay in unrotated page space.  Without the rot matrix every
    line lands in the wrong cell (or none).
    """

    # 3 columns: keeps the 2-column label-transpose heuristic out of play.
    EXPECTED = [
        ["Name", "Meaning", "Notes"],
        ["pre", "a precondition check", "evaluated on entry"],
        ["post", "a postcondition check", "evaluated on exit"],
    ]

    def _tbl_info(self, rot):
        # 3x3 grid in reading space: rows at y 50/120/190,
        # cols at x 50/200/400.
        cells = [
            (50.0, 50.0, 200.0, 120.0), (200.0, 50.0, 400.0, 120.0),
            (400.0, 50.0, 560.0, 120.0),
            (50.0, 120.0, 200.0, 190.0), (200.0, 120.0, 400.0, 190.0),
            (400.0, 120.0, 560.0, 190.0),
            (50.0, 190.0, 200.0, 260.0), (200.0, 190.0, 400.0, 260.0),
            (400.0, 190.0, 560.0, 260.0),
        ]
        return {
            "bbox": (50.0, 50.0, 560.0, 260.0),
            "row_count": 3, "col_count": 3,
            "cells": cells,
            "header_names": None,
            "extract": [list(r) for r in self.EXPECTED],
            "rot": rot,
        }

    def _blocks(self):
        # One block per cell, placed at reading-space cell centers but
        # carrying page-space bboxes (as extract_mupdf delivers them).
        col_x = (125.0, 300.0, 480.0)
        row_y = (85.0, 155.0, 225.0)
        blocks = []
        for ri, row in enumerate(self.EXPECTED):
            for ci, txt in enumerate(row):
                ln = _rotated_line(txt, col_x[ci], row_y[ri])
                blocks.append(Block(lines=[ln], bbox=ln.bbox, page_num=0))
        return blocks

    def test_rotated_cells_assigned_correctly(self):
        sections, used = _detect_mupdf_native_tables(
            self._blocks(), {0: [self._tbl_info(_ROT90)]})
        assert len(sections) == 1
        rows = [
            ["".join(s.text for s in cell) for cell in row]
            for row in sections[0].columns
        ]
        assert rows == self.EXPECTED

    def test_without_rot_matrix_assembly_degrades(self):
        """Control: same geometry minus the matrix must not pair correctly."""
        sections, used = _detect_mupdf_native_tables(
            self._blocks(), {0: [self._tbl_info(None)]})
        for sec in sections:
            rows = [
                ["".join(s.text for s in cell) for cell in row]
                for row in sec.columns
            ]
            assert rows != self.EXPECTED


def _banded_frag(row_ys, col_xs=(50.0, 200.0, 400.0, 560.0)):
    """A find_tables fragment dict in reading space.

    row_ys: list of (y_top, y_bot) per row; col_xs: column boundaries.
    """
    cells = []
    for (yt, yb) in row_ys:
        for k in range(len(col_xs) - 1):
            cells.append((col_xs[k], yt, col_xs[k + 1], yb))
    bbox = (col_xs[0], row_ys[0][0], col_xs[-1], row_ys[-1][1])
    return {
        "bbox": bbox,
        "row_count": len(row_ys), "col_count": len(col_xs) - 1,
        "cells": cells,
        "header_names": None,
        "extract": [],
        "rot": _ROT90,
    }


class TestBandedRotatedAssembly:
    """Banded assembly path: fragment stitching with band barriers.

    Models the P3100R6 appendix: a rotated page where find_tables()
    splits one logical table into fragments separated by category-band
    blocks.  1-row fragments are continuation rows; bands start a new
    section and stay unclaimed (rendered as prose headings).
    """

    HEADER = ["Name", "Meaning", "Notes"]
    ROW_PRE = ["pre", "a precondition", "on entry"]
    ROW_POST = ["post", "a postcondition", "on exit"]
    ROW_ASSERT = ["assert", "an assertion", "mid-body"]

    COL_CENTERS = (125.0, 300.0, 480.0)

    def _row_blocks(self, texts, ry):
        blocks = []
        for ci, txt in enumerate(texts):
            ln = _rotated_line(txt, self.COL_CENTERS[ci], ry)
            blocks.append(Block(lines=[ln], bbox=ln.bbox, page_num=0))
        return blocks

    def _band_block(self, text, ry):
        ln = _rotated_line(text, 100.0, ry)
        return Block(lines=[ln], bbox=ln.bbox, page_num=0)

    def _setup(self, frag2_rows):
        """Header frag / band / 1-row frag / band / 2-row frag."""
        frags = [
            _banded_frag([(50.0, 80.0)]),
            _banded_frag([(100.0, 160.0)]),
            _banded_frag([(180.0, 240.0), (240.0, 300.0)]),
        ]
        blocks = []
        blocks += self._row_blocks(self.HEADER, 65.0)
        band1 = self._band_block("I. Contracts", 90.0)
        blocks.append(band1)
        blocks += self._row_blocks(self.ROW_PRE, 130.0)
        band2 = self._band_block("II. Checks", 170.0)
        blocks.append(band2)
        row_ys = (210.0, 270.0)
        for texts, ry in zip(frag2_rows, row_ys):
            blocks += self._row_blocks(texts, ry)
        band_indices = {blocks.index(band1), blocks.index(band2)}
        return blocks, frags, band_indices

    @staticmethod
    def _texts(section):
        return [
            ["".join(s.text for s in cell) for cell in row]
            for row in section.columns
        ]

    def test_band_barriers_split_into_categories(self):
        blocks, frags, band_idx = self._setup(
            [self.ROW_POST, self.ROW_ASSERT])
        sections, used = _detect_mupdf_native_tables(blocks, {0: frags})
        assert len(sections) == 2
        assert all(s.table_source == "banded_grid" for s in sections)
        # Category I: canonical header + the 1-row fragment.
        assert self._texts(sections[0]) == [self.HEADER, self.ROW_PRE]
        # Category II: canonical header + both rows of fragment 2.
        assert self._texts(sections[1]) == [
            self.HEADER, self.ROW_POST, self.ROW_ASSERT]

    def test_band_blocks_stay_unclaimed(self):
        blocks, frags, band_idx = self._setup(
            [self.ROW_POST, self.ROW_ASSERT])
        sections, used = _detect_mupdf_native_tables(blocks, {0: frags})
        assert not (used & band_idx)

    def test_repeated_header_dropped(self):
        # Fragment 2 starts with a per-page header repeat that differs
        # from the canonical header in one cell (the P3100R6 typo case).
        blocks, frags, band_idx = self._setup(
            [["Nam", "Meaning", "Notes"], self.ROW_POST])
        sections, used = _detect_mupdf_native_tables(blocks, {0: frags})
        assert len(sections) == 2
        assert self._texts(sections[1]) == [self.HEADER, self.ROW_POST]

    def test_without_bands_does_not_fire(self):
        blocks, frags, band_idx = self._setup(
            [self.ROW_POST, self.ROW_ASSERT])
        blocks = [b for i, b in enumerate(blocks) if i not in band_idx]
        sections, used, consumed = _detect_banded_rotated_tables(
            blocks, {0: frags})
        assert consumed == set()
        assert sections == []

    def test_without_rot_does_not_fire(self):
        blocks, frags, band_idx = self._setup(
            [self.ROW_POST, self.ROW_ASSERT])
        frags = [{**f, "rot": None} for f in frags]
        sections, used, consumed = _detect_banded_rotated_tables(
            blocks, {0: frags})
        assert consumed == set()

    def test_band_hugging_fragment_edge_still_splits(self):
        """A band heading inside the claim margin of the next fragment
        must stay a band (review fix: band detection runs before block
        claiming, otherwise the heading is swallowed into a cell)."""
        blocks, frags, band_idx = self._setup(
            [self.ROW_POST, self.ROW_ASSERT])
        # Move band 2 from ry 170 to ry 179: 1pt above fragment 3's top
        # edge (180), well inside its 5pt claim margin.
        for i in band_idx:
            if blocks[i].text == "II. Checks":
                ln = _rotated_line("II. Checks", 100.0, 179.0)
                blocks[i] = Block(lines=[ln], bbox=ln.bbox, page_num=0)
        sections, used = _detect_mupdf_native_tables(blocks, {0: frags})
        assert len(sections) == 2
        assert self._texts(sections[1]) == [
            self.HEADER, self.ROW_POST, self.ROW_ASSERT]
        # The heading itself must not appear in any cell.
        all_cells = [c for s in sections for row in self._texts(s)
                     for c in row]
        assert "II. Checks" not in all_cells

    def test_two_column_header_repeat_requires_exact_match(self):
        """In a 2-column table a data row sharing one cell with the
        header is real data, not a header repeat (review fix: the
        1-mismatch tolerance applies only to 3+ column tables)."""
        two_cols = (50.0, 200.0, 400.0)
        frags = [
            _banded_frag([(50.0, 80.0)], col_xs=two_cols),
            _banded_frag([(100.0, 160.0)], col_xs=two_cols),
        ]
        header = ["Default", "Meaning"]
        data_row = ["Default", "checks enabled"]
        blocks = []
        for ci, txt in enumerate(header):
            ln = _rotated_line(txt, (125.0, 300.0)[ci], 65.0)
            blocks.append(Block(lines=[ln], bbox=ln.bbox, page_num=0))
        blocks.append(self._band_block("I. Modes", 90.0))
        for ci, txt in enumerate(data_row):
            ln = _rotated_line(txt, (125.0, 300.0)[ci], 130.0)
            blocks.append(Block(lines=[ln], bbox=ln.bbox, page_num=0))
        sections, used = _detect_mupdf_native_tables(blocks, {0: frags})
        assert len(sections) == 1
        assert self._texts(sections[0]) == [header, data_row]

    def test_distant_rotated_table_not_absorbed(self):
        """An independent rotated table on a far page is its own run and
        must not be stitched into the banded table (review fix)."""
        blocks, frags, band_idx = self._setup(
            [self.ROW_POST, self.ROW_ASSERT])

        # Independent 3x3 rotated table on page 20, different column
        # count irrelevant: distance alone must isolate it.
        other_rows = [
            ["Opt", "Type", "Doc"],
            ["-O2", "level", "speed"],
            ["-Og", "level", "debug"],
        ]
        cells = []
        row_ys = [(50.0, 120.0), (120.0, 190.0), (190.0, 260.0)]
        col_xs = (50.0, 200.0, 400.0, 560.0)
        for yt, yb in row_ys:
            for k in range(len(col_xs) - 1):
                cells.append((col_xs[k], yt, col_xs[k + 1], yb))
        tbl20 = {
            "bbox": (50.0, 50.0, 560.0, 260.0),
            "row_count": 3, "col_count": 3,
            "cells": cells,
            "header_names": None,
            "extract": [list(r) for r in other_rows],
            "rot": _ROT90,
        }
        for ri, row in enumerate(other_rows):
            for ci, txt in enumerate(row):
                ln = _rotated_line(txt, self.COL_CENTERS[ci],
                                   (85.0, 155.0, 225.0)[ri])
                blocks.append(Block(lines=[ln], bbox=ln.bbox, page_num=20))

        sections, used = _detect_mupdf_native_tables(
            blocks, {0: frags, 20: [tbl20]})
        banded = [s for s in sections if s.table_source == "banded_grid"]
        assert len(banded) == 2
        assert self._texts(banded[0]) == [self.HEADER, self.ROW_PRE]
        assert self._texts(banded[1]) == [
            self.HEADER, self.ROW_POST, self.ROW_ASSERT]
        # Page 20 keeps its own table, assembled by the main loop.
        others = [s for s in sections if s.page_num == 20]
        assert len(others) == 1
        assert self._texts(others[0]) == other_rows


class TestColumnAwareSortRotated:
    """_column_aware_sort uses reading-space y on rotated pages."""

    def test_rotated_page_sorts_by_reading_order(self):
        # Reading order: heading (ry 30), table row (ry 100), footer
        # (ry 200).  In page space their y-order is inverted (the 90
        # degree rotation maps reading-y onto page-x).
        ln_heading = _rotated_line("Appendix", 100.0, 30.0)
        heading = Block(lines=[ln_heading], bbox=ln_heading.bbox, page_num=0)
        ln_row = _rotated_line("data", 100.0, 100.0)
        row = Block(lines=[ln_row], bbox=ln_row.bbox, page_num=0)
        ln_footer = _rotated_line("73", 100.0, 200.0)
        footer = Block(lines=[ln_footer], bbox=ln_footer.bbox, page_num=0)
        blocks = [footer, row, heading]
        _column_aware_sort(blocks, {0: 595.0}, {0: _ROT90})
        assert [b.text for b in blocks] == ["Appendix", "data", "73"]

    def test_without_rotation_map_behavior_unchanged(self):
        a = Block(lines=[_line("top", 10, 50, 100, 60)],
                  bbox=(10, 50, 100, 60), page_num=0)
        b = Block(lines=[_line("bottom", 10, 500, 100, 510)],
                  bbox=(10, 500, 100, 510), page_num=0)
        blocks = [b, a]
        _column_aware_sort(blocks, {0: 595.0})
        assert [blk.text for blk in blocks] == ["top", "bottom"]


# ---------------------------------------------------------------------------
# Cross-page table continuation (issue #304)
# ---------------------------------------------------------------------------

# Real geometry from P0957R8 "Table 3 - Sample compiler configurations", which
# runs off the bottom of page 12 and resumes at the top of page 13.
_P12_HEADER_XS = [63.0, 200.3, 343.7, 453.0]
_P12_ROW1_XS = [75.4, 224.5, 347.4, 452.2]
_P12_ROW2_XS = [94.4, 228.4, 351.2, 452.2]
_P13_CONT_XS = [81.7, 224.5, 347.4, 452.2]


def _row(page: int, y0: float, y1: float, xs: list[float]) -> Block:
    """A columnar block: one line per cell, starting at each x in xs."""
    lines = [
        Line(spans=[Span(text=f"c{i}", font_size=10.0)],
             bbox=(x, y0, x + 40.0, y1), page_num=page)
        for i, x in enumerate(xs)
    ]
    return Block(lines=lines, bbox=(xs[0], y0, xs[-1] + 40.0, y1),
                 page_num=page)


def _spacer(page: int, y0: float, y1: float) -> Block:
    """A whitespace-only block, as left behind by header/footer stripping."""
    line = Line(spans=[Span(text=" ", font_size=10.0)],
                bbox=(62.5, y0, 64.8, y1), page_num=page)
    return Block(lines=[line], bbox=(62.5, y0, 64.8, y1), page_num=page)


def _prose(page: int, y0: float, y1: float) -> Block:
    """A single-line block carrying real text."""
    line = Line(spans=[Span(text="Some prose.", font_size=10.0)],
                bbox=(62.5, y0, 400.0, y1), page_num=page)
    return Block(lines=[line], bbox=(62.5, y0, 400.0, y1), page_num=page)


class TestTryCrossPageContinuation:
    """Branch 6: a table runs off one page and resumes on the next."""

    def _table_blocks(self) -> list[Block]:
        return [
            _row(12, 714.0, 727.8, _P12_HEADER_XS),
            _row(12, 730.3, 743.7, _P12_ROW1_XS),
            _row(12, 745.9, 759.3, _P12_ROW2_XS),
        ]

    def test_continuation_row_across_blank_spacer(self):
        """The P0957R8 case: spacer on page 12, continuation on page 13."""
        table_blocks = self._table_blocks()
        blocks = [_spacer(12, 770.6, 793.1),
                  _row(13, 73.5, 86.9, _P13_CONT_XS)]
        result = _try_cross_page_continuation(
            blocks, 0, _P12_ROW2_XS, table_blocks)
        assert result is not None
        assert result.advance_to == 2
        assert result.new_ref_cols == _P13_CONT_XS

    def test_continuation_row_with_nothing_between(self):
        table_blocks = self._table_blocks()
        blocks = [_row(13, 73.5, 86.9, _P13_CONT_XS)]
        result = _try_cross_page_continuation(
            blocks, 0, _P12_ROW2_XS, table_blocks)
        assert result is not None
        assert result.advance_to == 1

    def test_real_block_between_ends_the_table(self):
        """Only whitespace may intervene; prose means the table stopped."""
        table_blocks = self._table_blocks()
        blocks = [_prose(12, 770.6, 785.0),
                  _row(13, 73.5, 86.9, _P13_CONT_XS)]
        assert _try_cross_page_continuation(
            blocks, 0, _P12_ROW2_XS, table_blocks) is None

    def test_page_gap_larger_than_one_rejected(self):
        table_blocks = self._table_blocks()
        blocks = [_row(14, 73.5, 86.9, _P13_CONT_XS)]
        assert _try_cross_page_continuation(
            blocks, 0, _P12_ROW2_XS, table_blocks) is None

    def test_candidate_below_top_band_rejected(self):
        """A table further down the next page is a different table."""
        table_blocks = self._table_blocks()
        blocks = [_row(13, 300.0, 313.4, _P13_CONT_XS)]
        assert _try_cross_page_continuation(
            blocks, 0, _P12_ROW2_XS, table_blocks) is None

    def test_table_not_at_page_bottom_rejected(self):
        """A table ending mid-page did not run out of room."""
        table_blocks = [
            _row(12, 300.0, 313.4, _P12_HEADER_XS),
            _row(12, 315.0, 328.4, _P12_ROW1_XS),
            _row(12, 330.0, 343.4, _P12_ROW2_XS),
        ]
        blocks = [_row(13, 73.5, 86.9, _P13_CONT_XS)]
        assert _try_cross_page_continuation(
            blocks, 0, _P12_ROW2_XS, table_blocks) is None

    def test_column_count_mismatch_rejected(self):
        table_blocks = self._table_blocks()
        blocks = [_row(13, 73.5, 86.9, [81.7, 224.5, 347.4])]
        assert _try_cross_page_continuation(
            blocks, 0, _P12_ROW2_XS, table_blocks) is None

    def test_column_drift_beyond_tolerance_rejected(self):
        """Same column count but a visibly different layout."""
        table_blocks = self._table_blocks()
        blocks = [_row(13, 73.5, 86.9, [200.0, 300.0, 400.0, 500.0])]
        assert _try_cross_page_continuation(
            blocks, 0, _P12_ROW2_XS, table_blocks) is None

    def test_unestablished_table_rejected(self):
        """A single row is not yet a table worth continuing."""
        table_blocks = [_row(12, 745.9, 759.3, _P12_ROW2_XS)]
        blocks = [_row(13, 73.5, 86.9, _P13_CONT_XS)]
        assert _try_cross_page_continuation(
            blocks, 0, _P12_ROW2_XS, table_blocks) is None

    def test_non_columnar_candidate_rejected(self):
        table_blocks = self._table_blocks()
        blocks = [_prose(13, 73.5, 86.9)]
        assert _try_cross_page_continuation(
            blocks, 0, _P12_ROW2_XS, table_blocks) is None

    def test_trailing_blanks_only_rejected(self):
        """Running off the end of the document is not a continuation."""
        table_blocks = self._table_blocks()
        blocks = [_spacer(12, 770.6, 793.1)]
        assert _try_cross_page_continuation(
            blocks, 0, _P12_ROW2_XS, table_blocks) is None


class TestFilterOverlappingMupdfTablesCrossPage:
    """A cross-page section must claim a y-range per page, not one union."""

    def _cross_page_section(self) -> Section:
        """Section whose lines span the bottom of page 12 and top of page 13."""
        return Section(
            kind=SectionKind.TABLE,
            text="",
            lines=[
                Line(spans=[Span(text="a")], bbox=(63.0, 714.0, 500.0, 727.8),
                     page_num=12),
                Line(spans=[Span(text="b")], bbox=(81.7, 73.5, 500.0, 86.9),
                     page_num=13),
            ],
            page_num=12,
        )

    def test_unrelated_table_on_same_page_survives(self):
        """A find_tables entry mid-page-12 does not overlap the bottom band."""
        page_tables = {12: [{"bbox": (60.0, 448.0, 520.0, 560.0)}]}
        kept = _filter_overlapping_mupdf_tables(
            page_tables, [self._cross_page_section()])
        assert kept == page_tables

    def test_overlapping_entry_on_each_touched_page_dropped(self):
        """Both the page-12 and the page-13 fragment suppress their own page."""
        page_tables = {
            12: [{"bbox": (60.0, 710.0, 520.0, 760.0)}],
            13: [{"bbox": (60.0, 70.0, 520.0, 90.0)}],
        }
        kept = _filter_overlapping_mupdf_tables(
            page_tables, [self._cross_page_section()])
        assert kept == {}


# --- N5040 attendance table (issue #360) ------------------------------------
#
# A two-column bordered table whose header cells are CENTERED while every
# body cell is left-aligned, running past the bottom of one page and
# continuing at the top of the next. Geometry mirrors the real paper:
# body names at x0=74, national bodies at x0=367, and the centered header
# cells at x0=203 / x0=404.

_ATT_NAME_X = 74.0
_ATT_BODY_X = 367.0
_ATT_HDR_NAME_X = 203.0
_ATT_HDR_BODY_X = 404.0


def _attendance_page(names, page_num, y0, *, header=False, blank_tail=0):
    """Build one page's worth of the attendance table as a single Block."""
    lines, y = [], y0
    if header:
        lines.append(_line("Name", _ATT_HDR_NAME_X, y, _ATT_HDR_NAME_X + 36, y + 13))
        lines.append(_line("National Body", _ATT_HDR_BODY_X, y,
                           _ATT_HDR_BODY_X + 78, y + 13))
        y += 17
    for name, body in names:
        lines.append(_line(name, _ATT_NAME_X, y, _ATT_NAME_X + 90, y + 13))
        lines.append(_line(body, _ATT_BODY_X, y, _ATT_BODY_X + 31, y + 13))
        y += 17
    for _ in range(blank_tail):
        lines.append(_line(" ", _ATT_NAME_X, y, _ATT_NAME_X + 3, y + 13))
        y += 17
    for ln in lines:
        ln.page_num = page_num
    x1 = _ATT_HDR_BODY_X + 78
    blk = Block(lines=lines, bbox=(_ATT_NAME_X, y0, x1, y), page_num=page_num)
    return blk, (_ATT_NAME_X, y0, x1, y)


class TestInlineGridAttendanceTable:
    """Issue #360: phantom column, page-break splits, blank trailing rows."""

    @staticmethod
    def _run(blocks, bboxes):
        from tomd.lib.pdf.table import _detect_inline_grid_tables
        mupdf = {}
        for blk, bbox in zip(blocks, bboxes):
            mupdf.setdefault(blk.page_num, []).append({"bbox": bbox})
        return _detect_inline_grid_tables(blocks, mupdf)

    def _two_pages(self, blank_tail=0):
        page_a = [(f"Name A{i}", "ANSI") for i in range(38)]
        page_b = [(f"Name B{i}", "BSI") for i in range(20)]
        blk_a, bb_a = _attendance_page(page_a, 0, 120.0, header=True)
        blk_b, bb_b = _attendance_page(page_b, 1, 120.0, blank_tail=blank_tail)
        return self._run([blk_a, blk_b], [bb_a, bb_b])

    def test_centered_header_does_not_create_a_phantom_column(self):
        sections, _ = self._two_pages()
        assert len(sections) == 1
        assert len(sections[0].columns[0]) == 2

    def test_header_row_holds_the_column_labels(self):
        sections, _ = self._two_pages()
        header = ["".join(s.text for s in cell).strip()
                  for cell in sections[0].columns[0]]
        assert header == ["Name", "National Body"]

    def test_page_break_does_not_start_a_second_table(self):
        sections, _ = self._two_pages()
        assert len(sections) == 1
        # 1 header + 38 + 20 attendees, nothing dropped or duplicated.
        assert len(sections[0].columns) == 59

    def test_continuation_rows_are_body_rows_not_headers(self):
        sections, _ = self._two_pages()
        first_continuation = [
            "".join(s.text for s in cell).strip()
            for cell in sections[0].columns[39]
        ]
        assert first_continuation == ["Name B0", "BSI"]

    def test_blank_source_lines_do_not_become_empty_rows(self):
        sections, _ = self._two_pages(blank_tail=2)
        rows = sections[0].columns
        assert len(rows) == 59
        for row in rows:
            assert any("".join(s.text for s in cell).strip() for cell in row)


class TestMergeCrossPageFragments:
    """The merge helper is shared by the inline-grid and MuPDF-native passes."""

    @staticmethod
    def _fragment(rows, page_num, y0, y1):
        lines = [_line(rows[0][0], 74.0, y0, 160.0, y0 + 13),
                 _line(rows[-1][0], 74.0, y1 - 13, 160.0, y1)]
        for ln in lines:
            ln.page_num = page_num
        columns = [[[Span(text=c)] for c in row] for row in rows]
        return Section(kind=SectionKind.TABLE, text="",
                       confidence=Confidence.HIGH, lines=lines,
                       page_num=page_num, columns=columns)

    def test_merges_fragments_across_a_page_break(self):
        from tomd.lib.pdf.table import _merge_cross_page_fragments
        a = self._fragment([["a1", "x"], ["a2", "y"]], 0, 120.0, 760.0)
        b = self._fragment([["b1", "z"], ["b2", "w"]], 1, 120.0, 300.0)
        merged = _merge_cross_page_fragments([a, b])
        assert len(merged) == 1
        assert len(merged[0].columns) == 4

    def test_leaves_fragments_with_different_column_counts_alone(self):
        from tomd.lib.pdf.table import _merge_cross_page_fragments
        a = self._fragment([["a1", "x"], ["a2", "y"]], 0, 120.0, 760.0)
        b = self._fragment([["b1", "z", "extra"]], 1, 120.0, 300.0)
        assert len(_merge_cross_page_fragments([a, b])) == 2

    def test_leaves_mid_page_neighbours_alone(self):
        from tomd.lib.pdf.table import _merge_cross_page_fragments
        a = self._fragment([["a1", "x"], ["a2", "y"]], 0, 120.0, 300.0)
        b = self._fragment([["b1", "z"]], 1, 400.0, 500.0)
        assert len(_merge_cross_page_fragments([a, b])) == 2


# ── _detect_column_split G1/G2 guard tests ──────────────────────────

def _split_block(x0: float, y0: float, x1: float, y1: float) -> Block:
    """Minimal block for column-split testing (bbox only)."""
    ln = _line("x", x0, y0, x1, y1)
    return Block(lines=[ln], bbox=(x0, y0, x1, y1), page_num=0)


class TestColumnSplitGuards:
    """_detect_column_split G1 (gutter-crossing) and G2 (row-alignment)."""

    @staticmethod
    def _page_width():
        return 612.0

    def test_genuine_two_column_p3977r0_p5_accepted(self):
        """p3977r0 page 5: genuine two-column text. G1=0.0, G2 low."""
        # Left column blocks at x0~72, right at x0~310; no crossing,
        # y0s do not align across columns.
        blocks = [
            _split_block(72, 100, 280, 112),
            _split_block(72, 120, 280, 132),
            _split_block(72, 140, 280, 152),
            _split_block(72, 160, 280, 172),
            _split_block(72, 180, 280, 192),
            _split_block(310, 105, 540, 117),
            _split_block(310, 125, 540, 137),
            _split_block(310, 145, 540, 157),
            _split_block(310, 165, 540, 177),
            _split_block(310, 185, 540, 197),
        ]
        result = _detect_column_split(blocks, self._page_width())
        assert result is not None, "genuine two-column must be accepted"

    def test_genuine_two_column_p0533r9_p4_accepted(self):
        """p0533r9 page 4: mixed page (two-column top, full-width below).
        Must keep today's two-column detection."""
        # Left column at x0~57, right at x0~310; no gutter crossing.
        # y0s do not align (left lines at 100,115,130; right at 103,118,133).
        blocks = [
            _split_block(57, 100, 280, 112),
            _split_block(57, 115, 280, 127),
            _split_block(57, 130, 280, 142),
            _split_block(310, 103, 540, 115),
            _split_block(310, 118, 540, 130),
            _split_block(310, 133, 540, 145),
        ]
        result = _detect_column_split(blocks, self._page_width())
        assert result is not None, "genuine two-column must be accepted"

    def test_p4096r0_p9_rejected_by_g2(self):
        """p4096r0 page 9: shattered table cells form row-aligned left/right
        blocks. G2 (row-alignment fraction >= 0.5) must reject."""
        # Simulated: left blocks at x0~67-171, right at x0~301.
        # y0s align between left and right (table rows).
        blocks = [
            _split_block(67, 300, 170, 315),   # left cell
            _split_block(301, 300, 434, 315),  # right cell, same y0
            _split_block(67, 340, 170, 355),
            _split_block(301, 340, 434, 355),
            _split_block(67, 380, 170, 395),
            _split_block(301, 380, 434, 395),
            _split_block(67, 420, 170, 435),
            _split_block(301, 420, 434, 435),
            _split_block(67, 460, 170, 475),
            _split_block(171, 460, 300, 475),  # extra left block
        ]
        result = _detect_column_split(blocks, self._page_width())
        assert result is None, "shattered table (G2) must be rejected"

    def test_p4096r0_p10_rejected_by_g1(self):
        """p4096r0 page 10: left blocks whose x1 crosses into the right
        column's x-range. G1 (gutter-crossing fraction > 0.15) must reject."""
        # Simulated: left blocks crossing into right zone (x1 > 301+tol).
        blocks = [
            _split_block(67, 100, 310, 115),   # x1=310 crosses right x0=301
            _split_block(67, 130, 310, 145),
            _split_block(67, 160, 310, 175),
            _split_block(67, 190, 310, 205),
            _split_block(67, 220, 310, 235),
            _split_block(301, 100, 434, 115),
            _split_block(301, 130, 434, 145),
            _split_block(301, 160, 434, 175),
        ]
        result = _detect_column_split(blocks, self._page_width())
        assert result is None, "gutter-crossing page (G1) must be rejected"


# ── _columns_count_match y-overlap guard tests ──────────────────────

class TestColumnsCountMatchOverlap:
    """_columns_count_match must reject same-row y-overlapping blocks."""

    def test_y_overlapping_pair_rejected(self):
        """Two blocks at the same y (table header halves) must not match."""
        cols = [67.0, 244.0]
        # block_a bottom = 200, block_b top = 190: b starts above a's bottom
        assert not _columns_count_match(cols, cols, 200.0, 190.0, True)

    def test_stacked_pair_with_small_gap_accepted(self):
        """Blocks stacked with a small y-gap (< 40) must be accepted."""
        cols = [67.0, 244.0]
        # block_a bottom = 200, block_b top = 215: gap = 15
        assert _columns_count_match(cols, cols, 200.0, 215.0, True)

    def test_stacked_pair_with_large_gap_rejected(self):
        """Blocks separated by > _RELAXED_MATCH_MAX_Y_GAP (40) rejected."""
        cols = [67.0, 244.0]
        # block_a bottom = 200, block_b top = 250: gap = 50 > 40
        assert not _columns_count_match(cols, cols, 200.0, 250.0, True)

    def test_different_page_rejected(self):
        """Cross-page pairs must always be rejected."""
        cols = [67.0, 244.0]
        assert not _columns_count_match(cols, cols, 200.0, 215.0, False)


# ── SBS atomized pre-pass: dense shattered tables (p4096r0 §5.4) ────

def _geo_block(page: int, *lines: tuple[str, float, float, float, float]
               ) -> Block:
    """Block with explicit line bboxes; block bbox is the union.

    Spans carry the line bbox too, as MuPDF spans do: the spanning-header
    post-pass reads column x-positions from the first row's spans."""
    lns = [Line(spans=[Span(text=t, font_size=10.0, bbox=(x0, y0, x1, y1))],
                bbox=(x0, y0, x1, y1))
           for t, x0, y0, x1, y1 in lines]
    return Block(
        lines=lns,
        bbox=(min(l.bbox[0] for l in lns), min(l.bbox[1] for l in lns),
              max(l.bbox[2] for l in lns), max(l.bbox[3] for l in lns)),
        page_num=page,
    )


def _cell_text(cell: list) -> str:
    return " ".join("".join(s.text for s in cell).split())


def _p4096_page11_blocks(*, drop_rows: set[str] = frozenset(),
                         ragged: bool = False,
                         cells_before_col0: float | None = None,
                         ) -> list[Block]:
    """p4096r0 page_num 11 (§5.4 Summary) as MuPDF delivers it.

    Header: fused "Criterion // P2464R0[1]" block, "(2021)", fused
    "P2300R10[8] (2026) // Coroutine executor" block. Every body row:
    fused col-0/col-1 block, "has none" continuation, col-2 and col-3
    single-line blocks. *drop_rows* removes whole rows by criterion;
    *ragged* drops the col-2 and col-3 blocks of two rows so those rows
    span only 2 of 4 columns. *cells_before_col0* reproduces the real
    extraction order of the "Generic composition" row: its col-2 and
    col-3 blocks start that many points above the col-0 block (0.0 is
    the exact tie on the page) and precede it in the list.
    """
    P = 11
    GC = "Generic composition"
    blocks = [
        _geo_block(P, ("5.4 Summary", 56.7, 282.1, 116.9, 297.8)),
        _geo_block(P, ("Criterion", 66.7, 316.2, 112.0, 329.8),
                   ("P2464R0[1]", 171.5, 319.1, 214.8, 332.7)),
        _geo_block(P, ("P2300R10[8] (2026)", 244.4, 316.2, 340.0, 332.7),
                   ("Coroutine executor", 433.6, 319.1, 510.3, 332.7)),
        _geo_block(P, ("(2021)", 171.5, 337.6, 196.8, 351.2)),
    ]
    rows = [
        ("Error channel", 366.1, "set_error exists; does not handle",
         "Not needed; result",
         [("compound I/O results without information", 384.6),
          ("loss (P2430R0[11])", 400.2)],
         [("delivered to", 384.6), ("continuation on resume", 403.1)]),
        ("Lifecycle", 431.6, "Structured lifecycle exists; task converts",
         "Ownership contract:",
         [("routine errors to exceptions (P3552R3[14])", 447.2)],
         [("resume or destroy", 450.1)]),
        ("Generic composition", 478.6,
         "Sender algorithms exist; deployed for GPU",
         "co_await replaces state",
         [("dispatch, thread pools, infrastructure", 497.1)],
         [("machines", 497.1)]),
        ("Deployed networking", 525.6, "None published", "New.", [], []),
    ]
    for ri, (crit, y0, c2, c3, c2_more, c3_more) in enumerate(rows):
        if crit in drop_rows:
            continue
        blocks.append(_geo_block(
            P, (crit, 66.7, y0, 160.0, y0 + 13.6),
            ('execute(F&&)' if crit != "Deployed networking"
             else '"I don\'t', 171.5, y0, 220.7, y0 + 13.6)))
        blocks.append(_geo_block(
            P, ("has none" if crit != "Deployed networking" else 'know"',
                171.5, y0 + 18.5, 206.7, y0 + 32.1)))
        if ragged and ri in (1, 2):
            continue
        dy = cells_before_col0 if (
            cells_before_col0 is not None and crit == GC) else 0.0
        blocks.append(_geo_block(P, (c2, 244.4, y0 - dy, 400.0, y0 + 13.6)))
        for t, yy in c2_more:
            blocks.append(_geo_block(P, (t, 244.4, yy, 408.4, yy + 13.6)))
        blocks.append(_geo_block(P, (c3, 433.6, y0 - dy, 520.0, y0 + 13.6)))
        for t, yy in c3_more:
            blocks.append(_geo_block(P, (t, 433.6, yy, 525.6, yy + 13.6)))
    blocks.append(_geo_block(
        P, ("The question that P2464R0[1] asked in 2021 - whether",
            56.7, 578.7, 536.8, 595.2)))
    blocks.sort(key=lambda b: ((b.bbox[1] + b.bbox[3]) / 2, b.bbox[0]))
    if cells_before_col0 is not None and GC not in drop_rows:
        # Real order: the two right-hand cells come out ahead of col 0.
        gc = next(i for i, b in enumerate(blocks)
                  if b.lines[0].text == GC)
        y0 = blocks[gc].bbox[1]
        pre = [i for i, b in enumerate(blocks)
               if b.bbox[0] >= 244.0
               and abs(b.bbox[1] - (y0 - cells_before_col0)) < 0.01]
        assert len(pre) == 2
        moved = [blocks[i] for i in pre]
        for i in sorted(pre, reverse=True):
            del blocks[i]
        gc = next(i for i, b in enumerate(blocks)
                  if b.lines[0].text == GC)
        blocks[gc:gc] = moved
    return blocks


class TestAtomizedPrepassDenseGate:
    """The pre-scanner claims dense 4-row shattered tables before Pass 1."""

    def test_p4096_page11_prepass_claims_dense_four_row_table(self):
        sections, used = _detect_side_by_side_tables(
            _p4096_page11_blocks(), atomized_only=True)
        assert len(sections) == 1
        sec = sections[0]
        assert sec.page_num == 11
        assert sec.table_source == "side_by_side_prepass"
        assert len(sec.columns) == 5
        assert all(len(row) == 4 for row in sec.columns)
        assert [_cell_text(c) for c in sec.columns[0]] == [
            "Criterion", "P2464R0[1] (2021)", "P2300R10[8] (2026)",
            "Coroutine executor"]
        assert [_cell_text(row[0]) for row in sec.columns[1:]] == [
            "Error channel", "Lifecycle", "Generic composition",
            "Deployed networking"]
        assert _cell_text(sec.columns[4][1]) == '"I don\'t know"'

    def test_line_level_header_acceptance_sees_fused_heading_pair(self):
        """Fused 'P2300R10[8] (2026) // Coroutine executor' block holds
        two column headings; clustering block x0s would find only 3."""
        sections, _ = _detect_side_by_side_tables(
            _p4096_page11_blocks(), atomized_only=True)
        hdr = [_cell_text(c) for c in sections[0].columns[0]]
        assert hdr[2] == "P2300R10[8] (2026)"
        assert hdr[3] == "Coroutine executor"

    def test_ragged_four_row_table_stays_below_general_gate(self):
        """Two rows spanning only 2 of 4 columns: not dense, gate stays 5."""
        sections, _ = _detect_side_by_side_tables(
            _p4096_page11_blocks(ragged=True), atomized_only=True)
        assert sections == []

    def test_three_row_dense_table_rejected(self):
        sections, _ = _detect_side_by_side_tables(
            _p4096_page11_blocks(drop_rows={"Deployed networking"}),
            atomized_only=True)
        assert sections == []

    def test_pass2_regular_source_is_side_by_side(self):
        """Same blocks without the pre-pass flag: Pass 2 claims them and
        labels the source accordingly."""
        sections, _ = _detect_side_by_side_tables(_p4096_page11_blocks())
        assert len(sections) == 1
        assert sections[0].table_source == "side_by_side"

    def test_pass1_source_is_horizontal_rows(self):
        blocks = [
            _geo_block(0, ("Property", 67, 100, 120, 113),
                       ("Coroutine executor", 186, 100, 280, 113),
                       ("Sender model", 304, 100, 400, 113)),
            _geo_block(0, ("Age", 67, 120, 90, 133),
                       ("New in 2026.", 186, 120, 280, 133),
                       ("Five years old.", 304, 120, 400, 133)),
            _geo_block(0, ("Deployments", 67, 140, 130, 153),
                       ("Capy, Corosio.", 186, 140, 280, 153),
                       ("Facebook, NVIDIA.", 304, 140, 400, 153)),
        ]
        sections, _ = detect_tables(blocks)
        assert len(sections) == 1
        assert sections[0].table_source == "horizontal_rows"


def _three_col_row(page: int, y0: float, texts: tuple[str, str, str]) -> Block:
    return _geo_block(
        page, (texts[0], 67, y0, 150, y0 + 13),
        (texts[1], 186, y0, 280, y0 + 13),
        (texts[2], 304, y0, 400, y0 + 13))


def _two_stacked_tables(gap: float, *, fragment: str) -> list[Block]:
    """Two 3-row Pass 1 tables (p4125r1 benchmark layout) separated by a
    block that starts *gap* points below the first table's last row.

    *fragment* selects what sits in the gap: ``"orphan"`` is a single-line
    block at column 0 (a scenario heading), ``"subset"`` a two-line block
    covering columns 1 and 2 only (a shorter header of the next table).
    """
    rows_a = [_three_col_row(0, y, (f"a{k}", "1", "2"))
              for k, y in enumerate((100, 120, 140))]
    fy = 153 + gap
    if fragment == "orphan":
        mid = [_geo_block(0, ("Scenario 2 - Filled Book", 67, fy, 250, fy + 13))]
    else:
        mid = [_geo_block(0, ("Count", 186, fy, 230, fy + 13),
                          ("Rate", 304, fy, 340, fy + 13))]
    by0 = fy + 20
    rows_b = [_three_col_row(0, y, (f"b{k}", "3", "4"))
              for k, y in enumerate((by0, by0 + 20, by0 + 40))]
    return rows_a + mid + rows_b


def _p4125_page20_blocks() -> list[Block]:
    """p4125r1 page_num 20 as detect_tables receives it: two benchmark
    tables (Empty Book, Filled Book), each a shattered 7-block header
    over five 10-cell row blocks, with scenario titles between."""
    P = 20
    cols = [56.7, 114.0, 170.8, 214.6, 262.8, 306.6, 350.4, 394.2, 438.0, 498.3]
    cols_b = [49.5, 110.0, 166.8, 210.6, 263.1, 306.9, 350.7, 394.5, 438.3, 502.1]
    labels = ["Count", "Min", "Max", "Mean", "P50", "P95", "P99", "Avg Rate"]

    def header(cx, y):
        h = 13.6
        return [
            _geo_block(P, ("Feed" if cx is cols else "Feed Rate", cx[0], y, cx[0] + 30, y + h)),
            _geo_block(P, *[(t, cx[k + 1], y, cx[k + 1] + 35, y + h)
                            for k, t in enumerate(labels)]),
            _geo_block(P, ("Avg Rate", cx[9], y, cx[9] + 35, y + h)),
            *([_geo_block(P, ("Rate", cx[0], y + 18.5, cx[0] + 18, y + 18.5 + h))]
              if cx is cols else []),
            _geo_block(P, ("(events/s)", cx[8], y + 18.5, cx[8] + 40, y + 18.5 + h)),
            _geo_block(P, ("(orders/s)", cx[9], y + 18.5, cx[9] + 40, y + 18.5 + h)),
            _geo_block(P, ("(msg/s)", cx[0], y + 37.0 if cx is cols else y + 18.5,
                           cx[0] + 31, (y + 37.0 if cx is cols else y + 18.5) + h)),
        ]

    def rows(cx, y0):
        out = []
        for r, first in enumerate(("1,000", "10,000", "100,000", "200,000", "∞")):
            y = y0 + r * 28.5
            cells = [first, "10,000"] + [f"+{r}.{k}%" for k in range(8)]
            out.append(_geo_block(P, *[(t, cx[k], y, cx[k] + 30, y + 13.6)
                                       for k, t in enumerate(cells)]))
        return out

    blocks = [
        _geo_block(P, ("Scenario 2 - Enter IOC, No Execution", 56.7, 56.0, 207.3, 70.3)),
        _geo_block(P, ("Empty Book", 56.7, 94.5, 104.3, 108.1)),
        *header(cols, 129.8),
        *rows(cols, 195.3),
        _geo_block(P, ("Scenario 2 - Enter IOC, No Execution", 56.7, 362.6, 207.3, 376.9)),
        _geo_block(P, ("Filled Book", 56.7, 401.1, 100.7, 414.7)),
        *header(cols_b, 436.4),
        *rows(cols_b, 483.4),
        _geo_block(P, ("Scenario 3 - Order Amends, Quantity Only", 56.7, 650.6, 230.8, 664.9)),
    ]
    blocks.sort(key=lambda b: ((b.bbox[1] + b.bbox[3]) / 2, b.bbox[0]))
    return blocks


def _p4094_page8_blocks() -> list[Block]:
    """p4094r0 page_num 8 (Assertion / Source / Evidence): a regular
    three-line header row block over a shattered body. Source+Evidence of
    each row are one fused two-line block; every wrapped line of the
    Assertion and Evidence cells is its own single-line block."""
    P = 8
    H = 13.6
    c0, c1, c2 = 66.7, 183.6, 281.9

    def row(y, assertion_lines, source, evidence_lines):
        out = [_geo_block(P, (source, c1, y - 2.8, 260.0, y - 2.8 + H),
                          (evidence_lines[0], c2, y - 2.8, 522.9, y - 2.8 + H))]
        for k, t in enumerate(assertion_lines):
            yy = y + k * 18.5
            out.append(_geo_block(P, (t, c0, yy, c0 + 90.0, yy + H)))
        for k, t in enumerate(evidence_lines[1:], start=1):
            yy = y + k * 18.5
            out.append(_geo_block(P, (t, c2, yy, c2 + 230.0, yy + H)))
        return out

    blocks = [
        _geo_block(P, ("Assertion", c0, 68.3, 110.0, 81.9),
                   ("Source", c1, 68.3, 220.0, 81.9),
                   ("Evidence", c2, 68.3, 317.3, 81.9)),
        *row(96.8, ['"we want to be able to', "have a single thread pool",
                    "object that can be used", "for all of the above use",
                    'cases"'],
             "P0285R0[14] (2016)",
             ["(none found in the published record)",
              "that mix networking and parallel algorithm",
              "same pool. No deployment data showing friction",
              "pools."]),
        *row(199.3, ['"each facility\'s unique', "interface necessitates an",
                     "entirely different", 'implementation" (the N',
                     "x M argument)"],
             "P0761R2[13] (2018)",
             ["One hypothetical code snippet.",
              "a parallel_for with an if/else chain over",
              "thread pool. This is the only code-level",
              "published record for any unification rationale",
              "authored by the proposal authors, not drawn",
              "codebase. No measurement from a real standard",
              "implementation."]),
        *row(338.8, ['"the view of SG1 was', "that a single executor",
                     "abstraction was", 'preferred"'],
             "P1791R0[12] (2019)",
             ["(none found in the published record)",
              'poll "Start with Chris Mysen\'s proposal?"',
              "(SF:9/WF:5/N:4/WA:0/SA:2). No rationale for",
              "abstraction is preferred over multiple.",
              "would be lost."]),
        *row(441.3, ['"Proposals mostly', "converged, but some",
                     'differences remain"'],
             "N4199[11] (2014)",
             ["(none found in the published record)",
              "differences (begin-work/end-work brackets,",
              "executors, three spawn variants) but no",
              "these differences are reconcilable or fundamental."]),
        *row(525.3, ['"serves the use cases of', "those independent",
                     "proposals with a single", 'consistent programming',
                     'model"'],
             "P0443R0[1] (2016)",
             ["(none found in the published record)",
              "demonstrating that the unified model serves",
              "No experiment comparing unified and domain-specific",
              "approaches."]),
        _geo_block(P, ("The published record was searched systematically.",
                       c0, 640.0, 520.0, 653.6)),
    ]
    blocks.sort(key=lambda b: ((b.bbox[1] + b.bbox[3]) / 2, b.bbox[0]))
    return blocks


class TestSbsCol0BandReorder:
    """Cells that precede their row's col-0 block in extraction order
    (exact y tie or marginally lower y) are pulled behind it, so the
    row groups on the col-0 block instead of gluing to the row above."""

    @pytest.mark.parametrize("pre_dy", [0.0, 2.8])
    def test_generic_composition_row_owns_its_cells(self, pre_dy):
        sections, _ = _detect_side_by_side_tables(
            _p4096_page11_blocks(cells_before_col0=pre_dy),
            atomized_only=True)
        assert len(sections) == 1
        sec = sections[0]
        assert sec.table_source == "side_by_side_prepass"
        rows = {_cell_text(r[0]): r for r in sec.columns[1:]}
        assert list(rows) == ["Error channel", "Lifecycle",
                              "Generic composition", "Deployed networking"]
        assert _cell_text(rows["Lifecycle"][2]) == (
            "Structured lifecycle exists; task converts routine errors to "
            "exceptions (P3552R3[14])")
        assert _cell_text(rows["Generic composition"][2]) == (
            "Sender algorithms exist; deployed for GPU dispatch, thread "
            "pools, infrastructure")
        assert _cell_text(rows["Generic composition"][3]) == (
            "co_await replaces state machines")
        assert _cell_text(rows["Deployed networking"][1]) == '"I don\'t know"'


def _p4096_page10_blocks() -> list[Block]:
    """p4096r0 page_num 10 (§5.2): two Pass 1 row-block tables.

    Age table: every row is one 3-line block; wrapped col-2 tails are
    single-line orphan blocks at the col-2 x. noexcept table: rows are
    3-line or 2-line (col 0 + col 1) blocks with col-1 and col-2 tails as
    orphans; the last row is followed by a numbered heading."""
    P = 10
    H = 13.62
    c0, c1, c2 = 66.7, 171.3, 304.1
    n1, n2 = 171.3, 373.9

    def row3(y0, t0, t1, t2, xs=(c0, c1, c2), x1s=(160.0, 290.0, 530.0)):
        return _geo_block(P, (t0, xs[0], y0, x1s[0], y0 + H),
                          (t1, xs[1], y0, x1s[1], y0 + H),
                          (t2, xs[2], y0, x1s[2], y0 + H))

    def one(y0, text, x, x1=530.0):
        return _geo_block(P, (text, x, y0, x1, y0 + H))

    return [
        one(56.0, "Ecosystem-scale validation:", 56.7, 200.0),
        row3(91.96, "Property", "Coroutine executor",
             "P2300R10[8] for networking"),
        row3(120.46, "Age", "P4003R0[4] (2026). New.",
             "P2464R0[1] redirected the committee toward P2300R10[8]"),
        one(141.83, "in 2021. Five years.", c2),
        row3(167.46, "Deployments", "Capy[6], Corosio[7].",
             "P2470R0[15]: Facebook, NVIDIA, Bloomberg - GPU"),
        one(188.83, "dispatch, thread pools, infrastructure.", c2),
        row3(217.33, "Networking deployments", "New.",
             "None published. Boost.Asio and Boost.Beast - the"),
        one(235.83, "deployed networking that the committee set aside - used",
            c2),
        one(254.33, "the continuation model.", c2),
        one(291.84, "The noexcept context. Both models must answer the same",
            56.7),
        one(310.34, "condition:", 56.7, 110.0),
        row3(346.30, "Property", "Coroutine executor",
             "execution::task (P3552R3[14])", xs=(c0, n1, n2),
             x1s=(160.0, 360.0, 530.0)),
        _geo_block(P, ("What throws", c0, 377.66, 130.0, 391.28),
                   ("post(coroutine_handle<>) throws", n1, 377.66, 360.0,
                    391.28)),
        one(377.66, "AS-EXCEPT-PTR converts routine", n2),
        one(396.16, "std::system_error on scheduling failure.", n1, 360.0),
        one(396.16, "error_code to exception_ptr.", n2),
        row3(424.66, "Trigger condition", "Scheduling failure on an I/O",
             "ECONNRESET, ETIMEDOUT, EWOULDBLOCK -", xs=(c0, n1, n2),
             x1s=(160.0, 360.0, 530.0)),
        one(443.16, "routine I/O outcomes.", n2),
        _geo_block(P, ("In a noexcept context", c0, 471.66, 165.0, 485.28),
                   ("std::terminate on catastrophic", n1, 471.66, 360.0,
                    485.28)),
        one(471.66, "std::terminate on routine I/O", n2),
        one(490.16, "condition.", n1, 230.0),
        one(544.82, "5.3 The Outcome", 56.7, 150.0),
        one(566.56, "The analysis was procedurally correct on every step.",
            56.7),
    ]


class TestPass1ContinuationOrphans:
    """A col-1+ orphan under an N-column row-block table is the wrapped
    tail of the previous row, merged backward into that cell."""

    def _age_table(self):
        sections, _ = detect_tables(_p4096_page10_blocks())
        by_hdr = {_cell_text(s.columns[0][2]): s for s in sections}
        return by_hdr["P2300R10[8] for networking"]

    def test_age_table_tails_merge_backward(self):
        sec = self._age_table()
        assert sec.table_source == "horizontal_rows"
        assert len(sec.columns) == 4
        assert [_cell_text(r[0]) for r in sec.columns] == [
            "Property", "Age", "Deployments", "Networking deployments"]
        assert _cell_text(sec.columns[1][2]).endswith(
            "toward P2300R10[8] in 2021. Five years.")
        assert _cell_text(sec.columns[2][2]).endswith(
            "GPU dispatch, thread pools, infrastructure.")
        assert _cell_text(sec.columns[3][2]).endswith(
            "the continuation model.")


class TestPass1ResumeAfterTrailingContinuation:
    """A col-1+ orphan with no following full row (Branch 4a/4b fail) is
    a trailing continuation; absorbing it inside the loop lets the scan
    reach the partial row that follows (p4096r0 §5.2 noexcept row 3)."""

    def _noexcept_table(self, blocks):
        sections, remaining = detect_tables(blocks)
        by_hdr = {_cell_text(s.columns[0][2]): s for s in sections}
        return by_hdr["execution::task (P3552R3[14])"], remaining

    def test_third_row_complete_and_heading_stays_out(self):
        blocks = _p4096_page10_blocks()
        sec, remaining = self._noexcept_table(blocks)
        assert sec.table_source == "horizontal_rows"
        assert [_cell_text(r[0]) for r in sec.columns] == [
            "Property", "What throws", "Trigger condition",
            "In a noexcept context"]
        assert _cell_text(sec.columns[1][1]) == (
            "post(coroutine_handle<>) throws std::system_error on "
            "scheduling failure.")
        assert _cell_text(sec.columns[1][2]) == (
            "AS-EXCEPT-PTR converts routine error_code to exception_ptr.")
        assert _cell_text(sec.columns[2][2]) == (
            "ECONNRESET, ETIMEDOUT, EWOULDBLOCK - routine I/O outcomes.")
        assert _cell_text(sec.columns[3][1]) == (
            "std::terminate on catastrophic condition.")
        assert _cell_text(sec.columns[3][2]) == (
            "std::terminate on routine I/O")
        assert any(b.lines[0].text == "5.3 The Outcome" for b in remaining)

    def test_prose_after_trailing_orphan_still_ends_table(self):
        blocks = [
            _three_col_row(0, 100, ("Property", "A", "B")),
            _three_col_row(0, 120, ("r1", "x", "y")),
            _three_col_row(0, 140, ("r2", "x", "y")),
            _three_col_row(0, 160, ("r3", "x", "wrapped")),
            _geo_block(0, ("tail of wrapped", 304, 178, 400, 191)),
            _geo_block(0, ("A paragraph that starts at the margin and runs on.",
                           56.7, 205, 540, 218)),
        ]
        sections, remaining = detect_tables(blocks)
        assert len(sections) == 1
        assert _cell_text(sections[0].columns[3][2]) == "wrapped tail of wrapped"
        assert len(remaining) == 1


class TestSeparatorRowDrop:
    """A body row of dash-only cells is a rendered markdown separator
    (p1068r11 poll tables), not data."""

    def test_all_dash_row_dropped_single_dash_cell_kept(self):
        blocks = [
            _three_col_row(0, 100, ("SF", "F", "N")),
            _three_col_row(0, 120, ("-", "-", "\u2014")),
            _three_col_row(0, 140, ("0", "-", "3")),
            _three_col_row(0, 160, ("1", "2", "3")),
            _three_col_row(0, 180, ("4", "5", "6")),
        ]
        sections, _ = detect_tables(blocks)
        assert len(sections) == 1
        rows = [[_cell_text(c) for c in r] for r in sections[0].columns]
        assert rows == [["SF", "F", "N"], ["0", "-", "3"],
                        ["1", "2", "3"], ["4", "5", "6"]]
        assert "| - | - |" not in sections[0].text


class TestAtomizedBodyPrepass:
    """The pre-scanner routes a regular-header table with a shattered body
    to the side-by-side family before Pass 1 can take each line as a row."""

    def test_p4094_page8_prepass_claims_shattered_body(self):
        sections, used = _detect_side_by_side_tables(
            _p4094_page8_blocks(), atomized_only=True)
        assert len(sections) == 1
        sec = sections[0]
        assert sec.table_source == "side_by_side_prepass"
        assert len(sec.columns) == 6
        assert [_cell_text(c) for c in sec.columns[0]] == [
            "Assertion", "Source", "Evidence"]
        assert [_cell_text(r[0]) for r in sec.columns[1:]] == [
            '"we want to be able to have a single thread pool object that '
            'can be used for all of the above use cases"',
            '"each facility\'s unique interface necessitates an entirely '
            'different implementation" (the N x M argument)',
            '"the view of SG1 was that a single executor abstraction was '
            'preferred"',
            '"Proposals mostly converged, but some differences remain"',
            '"serves the use cases of those independent proposals with a '
            'single consistent programming model"']
        assert _cell_text(sec.columns[1][1]) == "P0285R0[14] (2016)"
        assert _cell_text(sec.columns[1][2]).startswith(
            "(none found in the published record) that mix networking")
        assert _cell_text(sec.columns[5][2]).endswith("approaches.")

    def test_end_to_end_page8_is_one_table(self):
        sections, remaining = detect_tables(_p4094_page8_blocks())
        assert [len(s.columns) for s in sections] == [6]
        assert sections[0].table_source == "side_by_side_prepass"
        assert len(remaining) == 1

    def test_row_block_table_stays_with_pass1(self):
        """Every row one multi-line block: not atomized, the pre-pass
        leaves it to Pass 1 even at 5+ rows."""
        blocks = [_three_col_row(0, 100 + 20 * k, (f"r{k}", "x", "y"))
                  for k in range(6)]
        sections, _ = _detect_side_by_side_tables(blocks, atomized_only=True)
        assert sections == []
        sections, _ = detect_tables(blocks)
        assert len(sections) == 1
        assert sections[0].table_source == "horizontal_rows"


def _p4098_page4_blocks(*, column_first: bool = False,
                        year_column: bool = True) -> list[Block]:
    """p4098r1 page_num 4 (section 2.3, Claim / Source / Year / Evidence)
    as MuPDF delivers it: a regular four-line header block, then per row
    one fused Source + Year + first-Evidence-line block, every wrapped
    Claim line and Evidence continuation its own single-line block.

    The Year column (x 330.3) is 39.4pt before Evidence (x 369.7), closer
    than _COLUMN_GAP_THRESHOLD, and never a block x0. *column_first*
    returns the order _column_aware_sort produces when it takes the page
    for two text columns: heading, header and every Claim block first,
    the right-hand blocks after them. *year_column=False* drops the Year
    line from the fused blocks (no body line on the header's third
    column), the negative case for the header-grid adoption.
    """
    P = 4
    H = 13.6
    c0, c1, c2, c3 = 66.7, 261.0, 330.3, 369.7

    def fused(y, source, year, evidence, ev_x1):
        # The bracketed reference is a superscript: the Source line's box
        # starts 2.8pt above the row (PDF: 118.5 vs 121.3) and ends on the
        # row's bottom edge like every other line (134.9).
        lines = [(source, c1, y - 2.8, 309.3, y + H)]
        if year_column:
            lines.append((year, c2, y, 349.2, y + H))
        lines.append((evidence, c3, y, ev_x1, y + H))
        return _geo_block(P, *lines)

    def single(text, x0, y, x1):
        return _geo_block(P, (text, x0, y, x1, y + H))

    heading = _geo_block(P, ("2.3 Networking Dependency (2018-2021)",
                             56.7, 55.9, 244.2, 71.6))
    header = _geo_block(P, ("Claim", c0, 92.8, 89.2, 106.4),
                        ("Source", c1, 92.8, 288.2, 106.4),
                        ("Year", c2, 92.8, 348.2, 106.4),
                        ("Evidence", c3, 92.8, 405.1, 106.4))
    claims = [
        single('"SG1 has decided that the Networking TS', c0, 121.3, 224.6),
        single("should not be merged into the C++ working", c0, 139.8, 234.1),
        single('paper before executors go in."', c0, 158.3, 184.1),
        single('"How blocked is networking on the executors', c0, 186.8, 240.9),
        single('wording process?"', c0, 205.3, 138.0),
        single('"we should not standardize the Networking', c0, 252.3, 234.1),
        single("TS as it's currently designed. The problem is", c0, 270.8, 235.1),
        single('the use of a P0443 executor."', c0, 289.3, 179.0),
        single('"Stop spending energy on standardizing the', c0, 317.8, 236.4),
        single('Networking TS for C++23."', c0, 336.3, 168.5),
    ]
    right = [
        fused(121.3, "P1256R0 [16]", "2018",
              "Published decision. The coupling is a", 510.6),
        single("fact.", c3, 139.8, 386.2),
        fused(186.8, "P2130R0 [17]", "2020",
              "Pablo Halpern's question in the Prague", 519.8),
        single("minutes. No published answer", c3, 205.3, 487.0),
        single("quantifying the degree of blockage.", c3, 223.8, 507.1),
        fused(252.3, "P2464R0 [18]", "2021",
              "The analysis is under the work framing.", 520.8),
        single("No analysis under the continuation", c3, 270.8, 504.2),
        single("framing (P4096R0 [5] Section 2).", c3, 286.5, 492.3),
        fused(317.8, "P2464R0 [18]", "2021",
              "Published recommendation. The", 494.7),
        single("committee acted on it.", c3, 336.3, 455.7),
    ]
    if column_first:
        return [heading, header, *claims, *right]
    body = sorted(claims + right,
                  key=lambda b: (b.bbox[1] + b.bbox[3]) / 2)
    return [heading, header, *body]


class TestHeaderGridPrepass:
    """A regular header row block knows more columns than the body's block
    x0s cluster into (a narrow column fused into its neighbour's block);
    the pre-scanner adopts the header's grid when the body sits on it.
    Body order is the pipeline's business (TestColumnSplitOnTablePage)."""

    _HEADER = ["Claim", "Source", "Year", "Evidence"]

    def test_p4098_page4_header_grid_gives_four_columns(self):
        sections, used = _detect_side_by_side_tables(
            _p4098_page4_blocks(), atomized_only=True)
        assert len(sections) == 1
        sec = sections[0]
        assert sec.table_source == "side_by_side_prepass"
        assert len(sec.columns) == 5
        assert [_cell_text(c) for c in sec.columns[0]] == self._HEADER
        assert [_cell_text(r[2]) for r in sec.columns[1:]] == [
            "2018", "2020", "2021", "2021"]
        assert _cell_text(sec.columns[1][0]) == (
            '"SG1 has decided that the Networking TS should not be merged '
            'into the C++ working paper before executors go in."')
        assert _cell_text(sec.columns[1][3]) == (
            "Published decision. The coupling is a fact.")
        assert _cell_text(sec.columns[2][3]) == (
            "Pablo Halpern's question in the Prague minutes. No published "
            "answer quantifying the degree of blockage.")
        assert _cell_text(sec.columns[4][3]) == (
            "Published recommendation. The committee acted on it.")
        assert len(used) == 21  # header + 20 body blocks

    def test_header_grid_needs_a_body_line_on_every_header_column(self):
        """Without any body line on the header's Year column the header
        grid is not adopted: the body's three clusters stand (the shape
        before this fix, header cells cut to the cluster count)."""
        sections, _ = _detect_side_by_side_tables(
            _p4098_page4_blocks(year_column=False), atomized_only=True)
        assert len(sections) == 1
        assert [_cell_text(c) for c in sections[0].columns[0]] == [
            "Claim", "Source", "Year"]

    def test_end_to_end_page4_is_one_table(self):
        sections, remaining = detect_tables(_p4098_page4_blocks())
        assert [len(s.columns) for s in sections] == [5]
        assert len(sections[0].columns[0]) == 4
        assert sections[0].table_source == "side_by_side_prepass"
        assert [b.lines[0].spans[0].text for b in remaining] == [
            "2.3 Networking Dependency (2018-2021)"]


def _citation_comparison_blocks(
    *,
    left_header: tuple[str, ...],
    right_header: str,
    left_body: tuple[str, ...],
    right_body: tuple[str, ...],
    atomized_body: bool = True,
    populate_right: bool = True,
    inflate_xs: tuple[float, ...] = (180.0, 480.0),
    y_hdr: float = 100.0,
    page: int = 0,
) -> list[Block]:
    """Two-column citation comparison box plus later x-cluster inflators.

    Seed is a regular two-line header block (left first line + right).
    Extra *left_header* lines are stacked blocks in column 0, as when
    the section number wraps off `P... Section` (#427 printed p.7).
    The quoted body is either one block per wrapped line or one
    multi-line row block (T1 / Pass 1). Inflators at other x-positions
    reproduce later prose/boxes that push body x-clusters above 2.
    """
    P = page
    H = 13.0
    c0, c1 = 70.0, 300.0
    blocks = [
        _geo_block(P, (left_header[0], c0, y_hdr, c0 + 140.0, y_hdr + H),
                   (right_header, c1, y_hdr, c1 + 150.0, y_hdr + H)),
    ]
    y_next = y_hdr + H + 1.0
    for extra in left_header[1:]:
        blocks.append(_geo_block(
            P, (extra, c0, y_next, c0 + 40.0, y_next + H)))
        y_next += H + 1.0
    y_body = y_next + 14.0
    if atomized_body:
        for k, left in enumerate(left_body):
            yy = y_body + k * (H + 4.0)
            blocks.append(_geo_block(
                P, (left, c0, yy, c0 + 120.0, yy + H)))
            if populate_right:
                blocks.append(_geo_block(
                    P, (right_body[k], c1, yy, c1 + 120.0, yy + H)))
        y_last = y_body + (len(left_body) - 1) * (H + 4.0) + H
    else:
        lines = [
            (left_body[0], c0, y_body, c0 + 120.0, y_body + H),
            (right_body[0], c1, y_body, c1 + 120.0, y_body + H),
        ]
        blocks.append(_geo_block(P, *lines))
        y_last = y_body + H
    for n, x in enumerate(inflate_xs):
        yy = y_last + 60.0 + n * 20.0
        blocks.append(_geo_block(
            P, (f"Later boxed note {n + 1}.", x, yy, x + 80.0, yy + H)))
    blocks.sort(key=lambda b: ((b.bbox[1] + b.bbox[3]) / 2, b.bbox[0]))
    return blocks


def _stacked_citation_comparison_blocks() -> list[Block]:
    """Two citation boxes on one page, full-width heading between them.

    The heading spills both columns so the first scan stops; the
    pre-scanner must resume after the first box instead of jumping to
    the page end (i = j).
    """
    first = _citation_comparison_blocks(
        left_header=("P2300R10 Section 4.16",),
        right_header="P2300R10 Section 4.15",
        left_body=('"it is sensible to pass', "both the error channel"),
        right_body=('"In other cases, the', "partial success is kept"),
        inflate_xs=(),
        y_hdr=100.0,
    )
    heading = _geo_block(
        0, ("Dismiss, Then Adopt", 56.7, 200.0, 420.0, 214.0))
    second = _citation_comparison_blocks(
        left_header=("P2300R10 Section 4.17",),
        right_header="N5000R1 Section 2.1",
        left_body=('"Many senders can be', "made awaitable"),
        right_body=('"Only some senders can', "be made awaitable"),
        inflate_xs=(180.0, 480.0),
        y_hdr=230.0,
    )
    blocks = first + [heading] + second
    blocks.sort(key=lambda b: ((b.bbox[1] + b.bbox[3]) / 2, b.bbox[0]))
    return blocks


def _abutting_citation_boxes(n: int, gap: float = 30.0) -> list[Block]:
    """N citation boxes on one page, *gap* pt apart, no heading between.

    The next header sits inside the aligned scan gap and outside the
    row band, so a scan that keeps walking treats it as body.
    """
    blocks: list[Block] = []
    y = 100.0
    for k in range(n):
        blocks.extend(_citation_comparison_blocks(
            left_header=(f"P2300R10 Section 4.{16 + k}",),
            right_header=f"N5000R1 Section {k + 1}.1",
            left_body=('"left quote line', f"continues {k}"),
            right_body=('"right quote line', f"continues {k}"),
            inflate_xs=(),
            y_hdr=y,
        ))
        # Header height 13, pad 1, body offset 14, two lines pitched 17,
        # last line height 13: bottom is y + 58.
        y = y + 58.0 + gap
    blocks.sort(key=lambda b: ((b.bbox[1] + b.bbox[3]) / 2, b.bbox[0]))
    return blocks


def _ordinary_atomized_five_row(y_hdr: float, tag: str) -> list[Block]:
    """Non-citation 2-col atomized table with five body rows (min_rows=5)."""
    H = 13.0
    c0, c1 = 70.0, 300.0
    blocks = [
        _geo_block(0, (f"Left {tag}", c0, y_hdr, c0 + 80.0, y_hdr + H),
                   (f"Right {tag}", c1, y_hdr, c1 + 80.0, y_hdr + H)),
    ]
    for r in range(5):
        # Pitch > _SBS_ROW_Y_BAND so each pair is its own body row.
        yy = y_hdr + 24.0 + r * 28.0
        blocks.append(_geo_block(
            0, (f"{tag} a{r}", c0, yy, c0 + 80.0, yy + H)))
        blocks.append(_geo_block(
            0, (f"{tag} b{r}", c1, yy, c1 + 80.0, yy + H)))
    return blocks


def _stacked_ordinary_atomized_tables() -> list[Block]:
    """Two ordinary atomized tables plus a full-width heading.

    Current scan jumps to page end after the first claim (i = j), so
    the pre-pass emits only the first table.
    """
    first = _ordinary_atomized_five_row(100.0, "one")
    heading = _geo_block(
        0, ("A full width heading between tables", 56.7, 320.0, 500.0, 334.0))
    second = _ordinary_atomized_five_row(350.0, "two")
    blocks = first + [heading] + second
    blocks.sort(key=lambda b: ((b.bbox[1] + b.bbox[3]) / 2, b.bbox[0]))
    return blocks


def _two_line_citation_blocks(**kwargs) -> list[Block]:
    """Regular two-line 2-col citation header, wrapped atomized body."""
    return _citation_comparison_blocks(
        left_header=("P2300R10 Section 1.2",),
        right_header="P2300R10 Section 4.16",
        left_body=('"senders are not a', "good model for this"),
        right_body=('"coroutines are not a', "good model either"),
        **kwargs)


def _wrapped_citation_header_blocks(**kwargs) -> list[Block]:
    """Atomized header: left `P... Section` + stacked `4.8`, right citation."""
    return _citation_comparison_blocks(
        left_header=("P2300R10 Section", "4.8"),
        right_header="P2300R10 Section 4.7",
        left_body=('"first yes then no', "is not a protocol"),
        right_body=('"stop token is the', "cancellation model"),
        **kwargs)


def _split_citation_header_blocks(
    *,
    column_first: bool = True,
    inflate_xs: tuple[float, ...] = (400.0,),
) -> list[Block]:
    """Printed p.7 4.8/4.7 box: three separate header blocks.

    Left `P2300R10 Section` and stacked `4.8` at x=66.7, right
    `P2300R10 Section 4.7` at x=169.3. Each header cell is its own
    single-line block, so `_block_column_positions` is None. Body gap
    after `4.8` is > `_ATOMIZED_HDR_MAX_LINE_GAP` (real: 14.9pt).
    *column_first* matches MuPDF extraction order (left column, then
    right). The y-mid sort is the other legal reading order.
    """
    P = 0
    H = 13.6
    c0, c1 = 66.7, 169.3
    y_hdr, y_wrap, y_body = 247.2, 265.7, 294.2
    header = [
        _geo_block(P, ("P2300R10 Section", c0, y_hdr, c0 + 80.0, y_hdr + H)),
        _geo_block(P, ("4.8", c0, y_wrap, c0 + 20.0, y_wrap + H)),
        _geo_block(P, ("P2300R10 Section 4.7", c1, y_hdr, c1 + 140.0, y_hdr + H)),
    ]
    if not column_first:
        header = sorted(header, key=lambda b: ((b.bbox[1] + b.bbox[3]) / 2,
                                               b.bbox[0]))
    y_wrap2 = 312.7
    body = [
        _geo_block(P, ('"Senders are', c0, y_body, c0 + 80.0, y_body + H)),
        _geo_block(P, ('forkable"', c0, y_wrap2, c0 + 50.0, y_wrap2 + H)),
        _geo_block(P, (
            '"A single-shot sender can only be connected once."',
            c1, y_body, c1 + 200.0, y_body + H)),
    ]
    heading = _geo_block(
        P, ("4. Example Code", 56.7, 423.5, 160.0, 441.2))
    blocks = header + body + [heading]
    y_last = y_wrap2 + H
    for n, x in enumerate(inflate_xs):
        yy = y_last + 60.0 + n * 20.0
        blocks.append(_geo_block(
            P, (f"Later boxed note {n + 1}.", x, yy, x + 80.0, yy + H)))
    return blocks


def _split_header_pair(
    left: str,
    right: str,
    *,
    wrap: str | None = None,
    x0: float = 66.7,
    x1: float = 169.3,
    extra_col: tuple[str, float] | None = None,
    populate_right: bool = True,
) -> list[Block]:
    """Two (or three) separate header blocks plus one atomized body row."""
    P = 0
    H = 13.6
    y_hdr, y_wrap, y_body = 247.2, 265.7, 294.2
    blocks = [
        _geo_block(P, (left, x0, y_hdr, x0 + 80.0, y_hdr + H)),
        _geo_block(P, (right, x1, y_hdr, x1 + 140.0, y_hdr + H)),
    ]
    if wrap is not None:
        blocks.append(_geo_block(
            P, (wrap, x0, y_wrap, x0 + 20.0, y_wrap + H)))
    if extra_col is not None:
        text, x2 = extra_col
        blocks.append(_geo_block(
            P, (text, x2, y_hdr, x2 + 80.0, y_hdr + H)))
        blocks.append(_geo_block(
            P, ('"third quote"', x2, y_body, x2 + 80.0, y_body + H)))
    blocks.append(_geo_block(
        P, ('"left quote"', x0, y_body, x0 + 80.0, y_body + H)))
    if populate_right:
        blocks.append(_geo_block(
            P, ('"right quote"', x1, y_body, x1 + 80.0, y_body + H)))
    return blocks


class TestCitationSectionHeaderPrepass:
    """Two-column WG21 citation-section headers over one atomized quoted
    row (#427 comparison boxes). Later prose inflates body x-clusters;
    the pre-scanner adopts the recovered two-column grid only for this
    family, and only then accepts min_rows=1. T1-shaped one-block bodies
    stay with Pass 1."""

    def test_two_line_citation_header_one_atomized_row(self):
        sections, used = _detect_side_by_side_tables(
            _two_line_citation_blocks(), atomized_only=True)
        assert len(sections) == 1
        sec = sections[0]
        assert sec.table_source == "side_by_side_prepass"
        assert len(sec.columns) == 2
        assert all(len(row) == 2 for row in sec.columns)
        assert [_cell_text(c) for c in sec.columns[0]] == [
            "P2300R10 Section 1.2", "P2300R10 Section 4.16"]
        assert [_cell_text(c) for c in sec.columns[1]] == [
            '"senders are not a good model for this',
            '"coroutines are not a good model either']
        assert len(used) == 5  # header + 4 body line blocks; inflators out

    def test_wrapped_citation_header_stacked_section_number(self):
        sections, _ = _detect_side_by_side_tables(
            _wrapped_citation_header_blocks(), atomized_only=True)
        assert len(sections) == 1
        sec = sections[0]
        assert sec.table_source == "side_by_side_prepass"
        assert [_cell_text(c) for c in sec.columns[0]] == [
            "P2300R10 Section 4.8", "P2300R10 Section 4.7"]
        assert [_cell_text(c) for c in sec.columns[1]] == [
            '"first yes then no is not a protocol',
            '"stop token is the cancellation model']

    def test_end_to_end_citation_headers_are_2x2_prepass(self):
        for blocks in (_two_line_citation_blocks(),
                       _wrapped_citation_header_blocks()):
            sections, remaining = detect_tables(blocks)
            assert len(sections) == 1
            sec = sections[0]
            assert sec.table_source == "side_by_side_prepass"
            assert len(sec.columns) == 2
            assert all(len(row) == 2 for row in sec.columns)
            assert [b.lines[0].spans[0].text for b in remaining] == [
                "Later boxed note 1.", "Later boxed note 2."]

    def test_split_citation_header_three_separate_blocks(self):
        """#427 printed p.7: three one-line header blocks, not a fused seed."""
        for column_first in (True, False):
            blocks = _split_citation_header_blocks(column_first=column_first)
            assert all(
                _block_column_positions(b) is None
                for b in blocks[:3])
            sections, used = _detect_side_by_side_tables(
                blocks, atomized_only=True)
            assert len(sections) == 1
            sec = sections[0]
            assert sec.table_source == "side_by_side_prepass"
            assert len(sec.columns) == 2
            assert all(len(row) == 2 for row in sec.columns)
            assert [_cell_text(c) for c in sec.columns[0]] == [
                "P2300R10 Section 4.8", "P2300R10 Section 4.7"]
            assert [_cell_text(c) for c in sec.columns[1]] == [
                '"Senders are forkable"',
                '"A single-shot sender can only be connected once."']
            heading = next(
                b for b in blocks
                if b.lines[0].spans[0].text == "4. Example Code")
            assert blocks.index(heading) not in used
            # Pass 2 must not use this seed; the pre-pass owns it.
            assert _detect_side_by_side_tables(blocks) == ([], set())

    def test_end_to_end_split_citation_header_is_2x2_prepass(self):
        blocks = _split_citation_header_blocks()
        sections, remaining = detect_tables(blocks)
        assert len(sections) == 1
        sec = sections[0]
        assert sec.table_source == "side_by_side_prepass"
        assert len(sec.columns) == 2
        assert all(len(row) == 2 for row in sec.columns)
        assert [_cell_text(c) for c in sec.columns[0]] == [
            "P2300R10 Section 4.8", "P2300R10 Section 4.7"]
        assert [b.lines[0].spans[0].text for b in remaining] == [
            "4. Example Code", "Later boxed note 1."]

    def test_ordinary_split_headers_rejected(self):
        blocks = _split_header_pair("Before", "After")
        assert _detect_side_by_side_tables(
            blocks, atomized_only=True)[0] == []

    def test_one_column_citation_split_rejected(self):
        blocks = _split_header_pair(
            "P2300R10 Section", "orphan",
            wrap="4.8", populate_right=False)
        # Drop the non-citation right header so the cluster is 1-col.
        blocks = [b for b in blocks
                  if b.lines[0].spans[0].text != "orphan"]
        assert _detect_side_by_side_tables(
            blocks, atomized_only=True)[0] == []

    def test_three_column_citation_split_rejected(self):
        blocks = _split_header_pair(
            "P2300R10 Section 1.0",
            "P2300R10 Section 2.0",
            extra_col=("P2300R10 Section 3.0", 360.0))
        assert _detect_side_by_side_tables(
            blocks, atomized_only=True)[0] == []

    def test_non_citation_two_col_split_cluster_rejected(self):
        blocks = _split_header_pair("Claim", "Source")
        assert _detect_side_by_side_tables(
            blocks, atomized_only=True)[0] == []

    def test_non_citation_headers_same_geometry_rejected(self):
        blocks = _citation_comparison_blocks(
            left_header=("Before",),
            right_header="After",
            left_body=('"senders are not a', "good model for this"),
            right_body=('"coroutines are not a', "good model either"),
        )
        sections, _ = _detect_side_by_side_tables(
            blocks, atomized_only=True)
        assert sections == []

    def test_citation_header_one_block_body_stays_with_pass1(self):
        """T1 geometry: citation header over one multi-line row block.
        Not atomized; the pre-pass must not steal it at min_rows=1."""
        blocks = _two_line_citation_blocks(atomized_body=False)
        sections, _ = _detect_side_by_side_tables(
            blocks, atomized_only=True)
        assert sections == []
        sections, remaining = detect_tables(blocks)
        assert len(sections) == 1
        assert sections[0].table_source == "horizontal_rows"
        assert len(sections[0].columns) == 2
        assert [_cell_text(c) for c in sections[0].columns[0]] == [
            "P2300R10 Section 1.2", "P2300R10 Section 4.16"]
        assert [_cell_text(c) for c in sections[0].columns[1]] == [
            '"senders are not a', '"coroutines are not a']
        assert [b.lines[0].spans[0].text for b in remaining] == [
            "Later boxed note 1.", "Later boxed note 2."]

    def test_body_populating_only_one_header_column_rejected(self):
        blocks = _two_line_citation_blocks(populate_right=False)
        sections, _ = _detect_side_by_side_tables(
            blocks, atomized_only=True)
        assert sections == []

    def test_stacked_citation_boxes_both_claimed(self):
        """Two citation boxes separated by full-width prose: both 2x2,
        heading unconsumed. Resume is citation-prepass only."""
        blocks = _stacked_citation_comparison_blocks()
        sections, used = _detect_side_by_side_tables(
            blocks, atomized_only=True)
        assert len(sections) == 2
        assert all(s.table_source == "side_by_side_prepass" for s in sections)
        assert all(len(s.columns) == 2 and all(len(r) == 2 for r in s.columns)
                   for s in sections)
        assert [_cell_text(c) for c in sections[0].columns[0]] == [
            "P2300R10 Section 4.16", "P2300R10 Section 4.15"]
        assert [_cell_text(c) for c in sections[1].columns[0]] == [
            "P2300R10 Section 4.17", "N5000R1 Section 2.1"]
        heading = next(b for b in blocks
                       if b.lines[0].spans[0].text == "Dismiss, Then Adopt")
        assert blocks.index(heading) not in used
        sections_e2e, remaining = detect_tables(blocks)
        assert len(sections_e2e) == 2
        assert [b.lines[0].spans[0].text for b in remaining] == [
            "Dismiss, Then Adopt",
            "Later boxed note 1.",
            "Later boxed note 2.",
        ]

    def test_value_column_line_after_the_row_stays_out(self):
        """A same-column sentence 30pt under the quote is not a wrap.

        30pt is inside the aligned scan gap (50pt) and outside the row
        band (10pt). The line must stay prose.
        """
        blocks = _two_line_citation_blocks(inflate_xs=())
        last_y1 = max(b.bbox[3] for b in blocks)
        y = last_y1 + 30.0
        prose = _geo_block(
            0, ("A later sentence on the value column.",
                300.0, y, 480.0, y + 13.0))
        blocks.append(prose)
        blocks.sort(key=lambda b: ((b.bbox[1] + b.bbox[3]) / 2, b.bbox[0]))
        sections, used = _detect_side_by_side_tables(
            blocks, atomized_only=True)
        assert len(sections) == 1
        assert len(sections[0].columns) == 2
        body = " ".join(_cell_text(c) for row in sections[0].columns for c in row)
        assert "later sentence" not in body
        assert blocks.index(prose) not in used

    def test_lowercase_quote_tail_stays_in_the_cell(self):
        """P4178 Section 1.2/4.9.3: ``data-races`` continues the quote.

        The tail sits past the row band and inside the aligned scan
        gap. A sentence-initial line at the same gap does not.
        """
        blocks = _two_line_citation_blocks(inflate_xs=())
        last_y1 = max(b.bbox[3] for b in blocks)
        y = last_y1 + 30.0
        tail = _geo_block(0, ("data-races", 300.0, y, 380.0, y + 13.0))
        blocks.append(tail)
        blocks.sort(key=lambda b: ((b.bbox[1] + b.bbox[3]) / 2, b.bbox[0]))
        sections, used = _detect_side_by_side_tables(
            blocks, atomized_only=True)
        assert len(sections) == 1
        right = _cell_text(sections[0].columns[1][1])
        assert right.endswith("data-races")
        assert blocks.index(tail) in used

    def test_lowercase_prose_after_closed_quote_stays_out(self):
        """A lowercase sentence after a finished quote is not a wrap."""
        blocks = _citation_comparison_blocks(
            left_header=("P2300R10 Section 1.2",),
            right_header="P2300R10 Section 4.16",
            left_body=('"left quote', 'ends here."'),
            right_body=('"right quote', 'ends here."'),
            inflate_xs=(),
        )
        last_y1 = max(b.bbox[3] for b in blocks)
        y = last_y1 + 30.0
        prose = _geo_block(
            0, ("this is a later prose sentence.",
                300.0, y, 480.0, y + 13.0))
        blocks.append(prose)
        blocks.sort(key=lambda b: ((b.bbox[1] + b.bbox[3]) / 2, b.bbox[0]))
        sections, used = _detect_side_by_side_tables(
            blocks, atomized_only=True)
        assert len(sections) == 1
        right = _cell_text(sections[0].columns[1][1])
        assert right.endswith('ends here."')
        assert "later prose" not in right
        assert blocks.index(prose) not in used

    def test_abutting_citation_boxes_stay_separate(self):
        """Two and three boxes 30pt apart, no spilling heading.

        Each box is its own 2x2. A later citation header is not a body
        row of the first box.
        """
        for n in (2, 3):
            blocks = _abutting_citation_boxes(n)
            sections, _used = _detect_side_by_side_tables(
                blocks, atomized_only=True)
            assert len(sections) == n
            assert all(len(s.columns) == 2 for s in sections)
            headers = [_cell_text(s.columns[0][0]) for s in sections]
            assert headers == [f"P2300R10 Section 4.{16 + k}" for k in range(n)]
            for sec in sections:
                flat = " ".join(
                    _cell_text(c) for row in sec.columns for c in row)
                assert flat.count("P2300R10 Section") == 1
                assert flat.count("N5000R1 Section") == 1

    def test_stacked_ordinary_atomized_tables_both_claimed(self):
        """Pre-pass resumes after a claimed table, so a second ordinary
        atomized table on the same page is claimed too. The heading
        between them stays prose."""
        blocks = _stacked_ordinary_atomized_tables()
        sections, used = _detect_side_by_side_tables(
            blocks, atomized_only=True)
        assert len(sections) == 2
        assert all(s.table_source == "side_by_side_prepass" for s in sections)
        assert [_cell_text(c) for c in sections[0].columns[0]] == [
            "Left one", "Right one"]
        assert [_cell_text(c) for c in sections[1].columns[0]] == [
            "Left two", "Right two"]
        heading = next(
            b for b in blocks
            if b.lines[0].spans[0].text.startswith("A full width heading"))
        assert blocks.index(heading) not in used

    def test_mixed_citation_and_short_label_header(self):
        """#427: one citation cell plus a short context label, 2x2."""
        for right in ("The receiver concept", "Context"):
            blocks = _citation_comparison_blocks(
                left_header=("P2300R10 Section 1.9.3",),
                right_header=right,
                left_body=('"The lack of a standard', "callback shape"),
                right_body=("set_value, set_error", "with cancellation"),
            )
            sections, _ = _detect_side_by_side_tables(
                blocks, atomized_only=True)
            assert len(sections) == 1
            sec = sections[0]
            assert sec.table_source == "side_by_side_prepass"
            assert len(sec.columns) == 2
            assert all(len(row) == 2 for row in sec.columns)
            assert [_cell_text(c) for c in sec.columns[0]] == [
                "P2300R10 Section 1.9.3", right]

    def test_end_to_end_mixed_citation_label_is_2x2_prepass(self):
        blocks = _citation_comparison_blocks(
            left_header=("P2300R10 Section 4.9.4",),
            right_header="Context",
            left_body=('"these concerns are still', "being investigated"),
            right_body=("This is R10, the revision", "that became C++26."),
        )
        sections, remaining = detect_tables(blocks)
        assert len(sections) == 1
        assert sections[0].table_source == "side_by_side_prepass"
        assert [_cell_text(c) for c in sections[0].columns[0]] == [
            "P2300R10 Section 4.9.4", "Context"]
        assert [b.lines[0].spans[0].text for b in remaining] == [
            "Later boxed note 1.", "Later boxed note 2."]

    def test_long_non_citation_sibling_rejected(self):
        blocks = _citation_comparison_blocks(
            left_header=("P2300R10 Section 1.2",),
            right_header=(
                "This long prose sentence is not a short header label"),
            left_body=('"senders are not a', "good model for this"),
            right_body=('"coroutines are not a', "good model either"),
        )
        assert _detect_side_by_side_tables(
            blocks, atomized_only=True)[0] == []


def _yba_row(page: int, y: float, label: str, value: str,
             *, c0: float = 66.7, c1: float = 116.4, h: float = 13.6
             ) -> Block:
    """One Yes/But/Actually row: two lines, gap 49.7pt (under 50)."""
    return _geo_block(
        page,
        (label, c0, y, c0 + 20.0, y + h),
        (value, c1, y, c1 + 200.0, y + h),
    )


def _yba_table_blocks(
    *,
    page: int = 0,
    y_title: float = 119.3,
    section: str = "4.14",
    values: tuple[str, str, str] = (
        '"it is sensible to pass both channels"',
        '"partial success is more of a partial failure."',
        '"sending the error through the value channel"',
    ),
    wrap: str | None = None,
    commentary: str | None = "The section may be exploring a genuine tension.",
    title: str | None = None,
    labels: tuple[str, str, str] = ("Yes", "But", "Actually"),
    extra_row: tuple[str, str] | None = None,
    value_xs: tuple[float, float, float] | None = None,
    drop_last: bool = False,
    title_gap: float = 14.9,
) -> list[Block]:
    """Printed pp.3-4 Yes/But/Actually box: citation title over col-1."""
    H = 13.6
    c0, c1 = 66.7, 116.4
    title_text = title if title is not None else f"P2300R10 Section {section}"
    blocks = [_geo_block(
        page, (title_text, c1, y_title, c1 + 90.0, y_title + H))]
    y = y_title + H + title_gap
    n_rows = 2 if drop_last else 3
    xs = value_xs or (c1, c1, c1)
    for i, label in enumerate(labels[:n_rows]):
        blocks.append(_yba_row(
            page, y, label, values[i], c0=c0, c1=xs[i], h=H))
        y += H + 14.9
    if wrap is not None:
        blocks.append(_geo_block(
            page, (wrap, c1, y - 10.0, c1 + 80.0, y - 10.0 + H)))
        y += 8.0
    if extra_row is not None:
        blocks.append(_yba_row(page, y, extra_row[0], extra_row[1]))
        y += H + 14.9
    if commentary is not None:
        blocks.append(_geo_block(
            page, (commentary, 56.7, y + 20.0, 520.0, y + 20.0 + H)))
    return blocks


def _stacked_yba_tables() -> list[Block]:
    """Four Yes/But/Actually boxes on one page, commentary between."""
    blocks: list[Block] = []
    y = 80.0
    for n, sec in enumerate(("4.14", "4.16", "4.15", "4.17")):
        chunk = _yba_table_blocks(
            y_title=y,
            section=sec,
            values=(
                f'"yes quote {sec}"',
                f'"but quote {sec}"',
                f'"actually quote {sec}"',
            ),
            commentary=f"Commentary after {sec}.",
            wrap='"tail wrap."' if sec == "4.16" else None,
        )
        blocks.extend(chunk)
        y += 160.0
    return blocks


class TestCitationYesButActuallyPrepass:
    """Citation title over the value column plus Yes/But/Actually rows
    (#427 printed pp.3-4). Gap 49.7pt misses `_block_column_positions`."""

    def test_real_shape_is_4x2_prepass(self):
        blocks = _yba_table_blocks()
        assert _block_column_positions(blocks[1]) is None
        sections, used = _detect_side_by_side_tables(
            blocks, atomized_only=True)
        assert len(sections) == 1
        sec = sections[0]
        assert sec.table_source == "side_by_side_prepass"
        assert len(sec.columns) == 4
        assert all(len(row) == 2 for row in sec.columns)
        assert [_cell_text(c) for c in sec.columns[0]] == [
            "", "P2300R10 Section 4.14"]
        assert [_cell_text(r[0]) for r in sec.columns[1:]] == [
            "Yes", "But", "Actually"]
        comment = next(
            b for b in blocks
            if b.lines[0].spans[0].text.startswith("The section may"))
        assert blocks.index(comment) not in used
        assert _detect_side_by_side_tables(blocks) == ([], set())

    def test_end_to_end_yba_is_4x2_prepass(self):
        blocks = _yba_table_blocks(wrap='"than coroutines."')
        sections, remaining = detect_tables(blocks)
        assert len(sections) == 1
        sec = sections[0]
        assert sec.table_source == "side_by_side_prepass"
        assert len(sec.columns) == 4
        assert _cell_text(sec.columns[3][1]).endswith('than coroutines."')
        assert [b.lines[0].spans[0].text for b in remaining] == [
            "The section may be exploring a genuine tension."]

    def test_stacked_four_yba_all_claimed(self):
        blocks = _stacked_yba_tables()
        sections, used = _detect_side_by_side_tables(
            blocks, atomized_only=True)
        assert len(sections) == 4
        assert all(s.table_source == "side_by_side_prepass" for s in sections)
        assert all(len(s.columns) == 4 for s in sections)
        headers = [_cell_text(s.columns[0][1]) for s in sections]
        assert headers == [
            "P2300R10 Section 4.14",
            "P2300R10 Section 4.16",
            "P2300R10 Section 4.15",
            "P2300R10 Section 4.17",
        ]
        comments = [
            b.lines[0].spans[0].text for b in blocks
            if b.lines[0].spans[0].text.startswith("Commentary after")]
        assert len(comments) == 4
        for b in blocks:
            if b.lines[0].spans[0].text.startswith("Commentary after"):
                assert blocks.index(b) not in used
        sections_e2e, remaining = detect_tables(blocks)
        assert len(sections_e2e) == 4
        assert all(
            t.startswith("Commentary after")
            for t in (b.lines[0].spans[0].text for b in remaining))

    def test_wrong_labels_rejected(self):
        blocks = _yba_table_blocks(labels=("Yeah", "But", "Actually"))
        assert _detect_side_by_side_tables(
            blocks, atomized_only=True)[0] == []

    def test_reordered_labels_rejected(self):
        blocks = _yba_table_blocks(labels=("But", "Yes", "Actually"))
        assert _detect_side_by_side_tables(
            blocks, atomized_only=True)[0] == []

    def test_missing_row_rejected(self):
        blocks = _yba_table_blocks(drop_last=True)
        assert _detect_side_by_side_tables(
            blocks, atomized_only=True)[0] == []

    def test_extra_row_rejected(self):
        blocks = _yba_table_blocks(extra_row=("Maybe", '"a fourth row"'))
        assert _detect_side_by_side_tables(
            blocks, atomized_only=True)[0] == []

    def test_title_gap_inside_header_band_stays_4x2(self):
        """Yes 8pt under the title is still a row, not part of the header.

        8pt is inside _ATOMIZED_HDR_MAX_LINE_GAP, so the split-header
        seed would absorb the Yes row if it ran first.
        """
        blocks = _yba_table_blocks(title_gap=8.0)
        sections, _used = _detect_side_by_side_tables(
            blocks, atomized_only=True)
        assert len(sections) == 1
        sec = sections[0]
        assert sec.table_source == "side_by_side_prepass"
        assert len(sec.columns) == 4
        assert [_cell_text(c) for c in sec.columns[0]] == [
            "", "P2300R10 Section 4.14"]
        assert [_cell_text(r[0]) for r in sec.columns[1:]] == [
            "Yes", "But", "Actually"]

    def test_second_actually_line_stays_out(self):
        """One Actually continuation joins. The next sentence does not."""
        blocks = _yba_table_blocks(
            wrap='"than coroutines."', commentary=None)
        wrap_blk = next(
            b for b in blocks
            if "than coroutines" in b.lines[0].spans[0].text)
        x0, _y0, _x1, y1 = wrap_blk.bbox
        sentence = _geo_block(
            0, ("This is the next sentence.",
                x0, y1 + 8.0, x0 + 160.0, y1 + 8.0 + 13.6))
        blocks = [*blocks, sentence]
        sections, used = _detect_side_by_side_tables(
            blocks, atomized_only=True)
        assert len(sections) == 1
        actually = _cell_text(sections[0].columns[3][1])
        assert actually.endswith('than coroutines."')
        assert "next sentence" not in actually
        assert blocks.index(sentence) not in used

    def test_non_citation_title_rejected(self):
        blocks = _yba_table_blocks(title="Introduction")
        assert _detect_side_by_side_tables(
            blocks, atomized_only=True)[0] == []

    def test_unstable_columns_rejected(self):
        blocks = _yba_table_blocks(value_xs=(116.4, 116.4, 220.0))
        assert _detect_side_by_side_tables(
            blocks, atomized_only=True)[0] == []

    def test_t1_one_block_body_still_pass1(self):
        """T1 stays with Pass 1 after the mixed-header generalization."""
        blocks = _two_line_citation_blocks(atomized_body=False)
        sections, _ = _detect_side_by_side_tables(
            blocks, atomized_only=True)
        assert sections == []
        sections, _ = detect_tables(blocks)
        assert len(sections) == 1
        assert sections[0].table_source == "horizontal_rows"


class TestColumnSplitOnTablePage:
    """p4098r1 p.4: a table page with one wide Claim column beside three
    narrow ones must not pass for two text columns. Two things went wrong
    in the pipeline: G2 compared block y0s, and the fused Source blocks
    carry a superscript that lifts their y0 2.8pt above the Claim line
    (4/10 aligned, below the 0.5 reject); and two_column_pages was computed
    on the raw blocks, where the centred page number fills the gutter, so
    the classification and the sort disagreed. Real geometry from the PDF
    (page 4, 0-based), footer as MuPDF delivers it."""

    _WIDTH = 612.0

    @staticmethod
    def _footer() -> Block:
        return _geo_block(4, ("5", 295.7, 794.8, 299.5, 804.7))

    def test_stripped_page_is_not_two_column(self):
        blocks = _p4098_page4_blocks()
        assert _detect_column_split(blocks, self._WIDTH) is None

    def test_raw_page_with_footer_is_not_two_column(self):
        """Regression pin for the raw-block state, not for this fix: with
        the centred footer the largest x-mid gap moves left of the Claim
        column and the x0 check already returns None. It documents why the
        old raw-block classification and the sort disagreed."""
        blocks = [*_p4098_page4_blocks(), self._footer()]
        assert _detect_column_split(blocks, self._WIDTH) is None

    def test_bottom_edge_is_what_rejects_the_split(self):
        """The fixture models the superscript as a taller first line (top
        lifted, bottom on the row). Lowering those four bottoms by the same
        2.8pt, so that neither y0 nor bottom edge lines up, brings the
        pre-fix state back: G2 counts 4/10 and the page splits."""
        blocks = _p4098_page4_blocks()
        fused = [b for b in blocks if b.bbox[0] > 200 and len(b.lines) == 3]
        assert len(fused) == 4
        for b in fused:
            ln = b.lines[0]
            assert ln.bbox[1] < b.lines[1].bbox[1]  # superscript lifts y0
            assert abs(ln.bbox[3] - b.lines[1].bbox[3]) < 1e-6  # same bottom
            x0, y0, x1, y1 = ln.bbox
            ln.bbox = (x0, y0, x1, y1 - 2.8)
        assert _detect_column_split(blocks, self._WIDTH) is not None

    def test_sort_returns_split_pages_and_keeps_y_order_here(self):
        blocks = _p4098_page4_blocks(column_first=True)
        split_pages = _column_aware_sort(blocks, {4: self._WIDTH})
        assert split_pages == frozenset()
        ys = [(b.bbox[1] + b.bbox[3]) / 2 for b in blocks]
        assert ys == sorted(ys)

    def test_sort_returns_genuine_two_column_page(self):
        left = [_split_block(72, y, 280, y + 12) for y in (100, 120, 140, 160, 180)]
        right = [_split_block(310, y, 540, y + 12) for y in (105, 125, 145, 165, 185)]
        blocks = [*right, *left]
        assert _column_aware_sort(blocks, {0: self._WIDTH}) == frozenset({0})
        assert [b.bbox[0] for b in blocks] == [72] * 5 + [310] * 5

    def test_end_to_end_column_first_input_is_not_repaired(self):
        """detect_tables no longer re-sorts: a column-first page reaching
        it means the pipeline classified the page as two-column, and the
        pre-pass must stand down there (a left heading beside a right
        paragraph has exactly this geometry)."""
        sections, _ = _detect_side_by_side_tables(
            _p4098_page4_blocks(column_first=True), atomized_only=True)
        assert sections == []


class TestPass1FragmentAbsorptionGap:
    """Branch 3 and 4 absorb table fragments only within the same y-gap
    that Branch 3b and 5 already require. Beyond it the table ends, so
    two stacked tables never chain through the heading between them."""

    def test_orphan_beyond_gap_ends_table(self):
        """A column-0 title 40pt below the last row opens the next table;
        one column covered is no header, so it stays prose."""
        sections, remaining = detect_tables(
            _two_stacked_tables(40.0, fragment="orphan"))
        assert [len(s.columns) for s in sections] == [3, 3]
        assert [_cell_text(s.columns[0][0]) for s in sections] == ["a0", "b0"]
        assert [_cell_text(s.columns[-1][0]) for s in sections] == ["a2", "b2"]
        assert len(remaining) == 1

    def test_subset_beyond_gap_becomes_next_tables_header(self):
        """A two-column header block 40pt below table A belongs to table B:
        Pass 1 no longer chains it into A, the spanning-header post-pass
        prepends it to B."""
        sections, remaining = detect_tables(
            _two_stacked_tables(40.0, fragment="subset"))
        assert [len(s.columns) for s in sections] == [3, 4]
        assert [_cell_text(c) for c in sections[1].columns[0]] == [
            "", "Count", "Rate"]
        assert _cell_text(sections[1].columns[1][0]) == "b0"
        assert remaining == []

    def test_p4125r1_page20_two_headed_tables(self):
        """Real p4125r1 page 20 geometry: two 5x10 tables, each under a
        header shattered into seven blocks. The shattered headers become
        header rows; the scenario title and 'Empty Book' stay prose."""
        sections, remaining = detect_tables(_p4125_page20_blocks())
        assert [len(s.columns) for s in sections] == [6, 6]
        hdr = [_cell_text(c) for c in sections[0].columns[0]]
        assert hdr == ["Feed Rate (msg/s)", "Count", "Min", "Max", "Mean",
                       "P50", "P95", "P99", "Avg Rate (events/s)",
                       "Avg Rate (orders/s)"]
        assert _cell_text(sections[0].columns[1][0]) == "1,000"
        assert _cell_text(sections[1].columns[0][0]) == "Feed Rate (msg/s)"
        assert [" ".join(l.text.strip() for l in b.lines) for b in remaining] == [
            "Scenario 2 - Enter IOC, No Execution", "Empty Book",
            "Scenario 2 - Enter IOC, No Execution", "Filled Book",
            "Scenario 3 - Order Amends, Quantity Only"]

    def test_prose_above_table_is_not_a_header(self):
        """A paragraph at column 0 plus one aligned fragment must not be
        folded into a header row: stacked lines in one column are header
        labels only when short."""
        blocks = [
            _geo_block(0, ("This paragraph explains the benchmark setup in",
                           67, 100, 400, 113),
                       ("some detail and continues for a second line here.",
                        67, 115, 400, 128)),
            _geo_block(0, ("Count", 186, 115, 230, 128)),
        ]
        blocks += [_three_col_row(0, y, (f"a{k}", "1", "2"))
                   for k, y in enumerate((140, 160, 180))]
        sections, remaining = detect_tables(blocks)
        assert len(sections) == 1
        assert len(sections[0].columns) == 3
        assert len(remaining) == 2

    def test_prose_directly_above_header_ends_cluster_not_header(self):
        """A long column-0 sentence 6pt above a two-cell header block
        must not cost the table its header: the cluster ends at the
        sentence and keeps the block below it."""
        blocks = [
            _geo_block(0, ("This sentence introduces the table that follows"
                           " and spans the full width of the page.",
                           67, 100, 400, 113)),
            _geo_block(0, ("Count", 186, 119, 230, 132),
                       ("Rate", 304, 119, 350, 132)),
        ]
        blocks += [_three_col_row(0, y, (f"a{k}", "1", "2"))
                   for k, y in enumerate((140, 160, 180))]
        sections, remaining = detect_tables(blocks)
        assert len(sections) == 1
        assert [_cell_text(c) for c in sections[0].columns[0]] == [
            "", "Count", "Rate"]
        assert len(remaining) == 1
        assert remaining[0].lines[0].text.startswith("This sentence")

    def test_single_spanning_line_is_not_a_header_cell(self):
        """One aligned fragment plus a page-wide sentence at column 0 (a
        single line, so the stacked-length guard never sees it) yields no
        header: the sentence spills past the next column."""
        blocks = [
            _geo_block(0, ("Count", 186, 100, 230, 113)),
            _geo_block(0, ("The following table lists the measured values"
                           " for every scenario in the benchmark run.",
                           67, 119, 540, 132)),
        ]
        blocks += [_three_col_row(0, y, (f"a{k}", "1", "2"))
                   for k, y in enumerate((140, 160, 180))]
        sections, remaining = detect_tables(blocks)
        assert len(sections) == 1
        assert len(sections[0].columns) == 3
        assert len(remaining) == 2

    def test_whitespace_spacer_between_header_and_table_is_skipped(self):
        blocks = [
            _geo_block(0, ("Count", 186, 100, 230, 113),
                       ("Rate", 304, 100, 350, 113)),
            _geo_block(0, ("   ", 67, 118, 70, 130)),
        ]
        blocks += [_three_col_row(0, y, (f"a{k}", "1", "2"))
                   for k, y in enumerate((140, 160, 180))]
        sections, remaining = detect_tables(blocks)
        assert [_cell_text(c) for c in sections[0].columns[0]] == [
            "", "Count", "Rate"]
        assert len(remaining) == 1 and not remaining[0].lines[0].text.strip()

    @pytest.mark.parametrize("fragment", ["orphan", "subset"])
    def test_fragment_within_gap_still_absorbed(self, fragment):
        sections, remaining = detect_tables(
            _two_stacked_tables(7.0, fragment=fragment))
        assert len(sections) == 1
        assert remaining == []
        joined = " ".join(_cell_text(c) for r in sections[0].columns for c in r)
        assert "b2" in joined and ("Scenario 2" in joined or "Count" in joined)


class TestTableBugFixes:
    """Regression tests for table parsing bugs (issue #369)."""

    def test_block_column_positions_clusters_wrapped_lines(self):
        # Block with 3 columns where column 1 and column 2 have wrapped lines
        lines = [
            _line("Col0", 60.0, 100.0, 100.0, 110.0),
            _line("Col1 line 1", 150.0, 100.0, 200.0, 110.0),
            _line("Col1 line 2", 150.0, 112.0, 200.0, 122.0),
            _line("Col2 line 1", 300.0, 100.0, 400.0, 110.0),
            _line("Col2 line 2", 300.0, 112.0, 400.0, 122.0),
        ]
        blk = _block_from_lines(lines)
        cols = _block_column_positions(blk)
        assert cols is not None
        assert len(cols) == 3
        assert cols[0] == 60.0
        assert cols[1] == 150.0
        assert cols[2] == 300.0

    def test_block_column_positions_wrapped_col0(self):
        # Col 0 has wrapped lines
        lines = [
            _line("Deterministic ST (L=16,", 60.7, 100.0, 150.0, 110.0),
            _line("8-block unroll)", 60.7, 112.0, 140.0, 122.0),
            _line("26.5 GB/s", 280.0, 100.0, 320.0, 110.0),
            _line("+391%", 420.0, 100.0, 460.0, 110.0),
        ]
        blk = _block_from_lines(lines)
        cols = _block_column_positions(blk)
        assert cols is not None
        assert len(cols) == 3

    def test_build_rows_sequential_assigns_by_x_coordinate(self):
        # Row with multiline cell in col 1
        lines = [
            _line("Facility A", 60.0, 100.0, 120.0, 110.0),
            _line("Canonical expression", 150.0, 100.0, 250.0, 110.0),
            _line("(§4)", 150.0, 112.0, 180.0, 122.0),
            _line("Fixed", 300.0, 100.0, 350.0, 110.0),
        ]
        blk = _block_from_lines(lines)
        ref_cols = [60.0, 150.0, 300.0]
        rows, all_lines = _build_rows_sequential([blk], ref_cols, 3, set())
        assert len(rows) == 1
        row = rows[0]
        assert "".join(s.text for s in row[0]).strip() == "Facility A"
        assert "Canonical expression" in "".join(s.text for s in row[1])
        assert "(§4)" in "".join(s.text for s in row[1])
        assert "".join(s.text for s in row[2]).strip() == "Fixed"

    def test_complete_pass1_not_deferred_to_mupdf(self):
        # 5 blocks covering the region exactly
        lines_header = [_line("Property", 60.0, 100.0, 100.0, 110.0)]
        lines_r1 = [_line("Section", 60.0, 120.0, 100.0, 130.0)]
        lines_r2 = [_line("Grouping", 60.0, 140.0, 100.0, 150.0)]
        lines_r3 = [_line("Complexity", 60.0, 160.0, 100.0, 170.0)]
        lines_r4 = [_line("Order", 60.0, 180.0, 100.0, 190.0)]
        table_blocks = [
            _block_from_lines(lines_header),
            _block_from_lines(lines_r1),
            _block_from_lines(lines_r2),
            _block_from_lines(lines_r3),
            _block_from_lines(lines_r4),
        ]
        all_blocks = list(table_blocks)
        region = (55.0, 95.0, 360.0, 195.0)
        # All blocks in region are claimed -> complete
        assert not _pass1_region_incomplete(region, 0, table_blocks, all_blocks)

        # An extra block exists in the region that Pass 1 did not claim -> incomplete
        orphan_block = _block_from_lines([_line("Missed note", 70.0, 150.0, 150.0, 160.0)])
        all_blocks_with_extra = all_blocks + [orphan_block]
        assert _pass1_region_incomplete(region, 0, table_blocks, all_blocks_with_extra)

    def test_is_column_aligned_orphan_multiline_narrow_col0(self):
        # Multiline block at col 0 (x0=60.7, x1=98.0) width=37.3 <= 200
        lines = [
            _line("PyTorch /", 60.7, 225.8, 90.9, 233.2),
            _line("TensorFlow", 60.7, 235.0, 98.0, 242.4),
        ]
        blk = _block_from_lines(lines)
        col_xs = frozenset({60.7, 134.9, 209.0, 397.0})
        assert _is_column_aligned_orphan(blk, col_xs)

    def test_build_rows_ybanded_vertically_staggered_cells(self):
        # Header block (all 4 cols)
        header_lines = [
            _line("Library", 60.7, 150.2, 86.4, 157.7),
            _line("Feature", 134.9, 150.2, 162.1, 157.7),
            _line("Mechanism", 209.0, 150.2, 302.0, 157.7),
            _line("Scope", 397.0, 150.2, 450.1, 157.7),
        ]
        b_hdr = _block_from_lines(header_lines)

        # Row 1: Col 1 starts at y=163.0 (4 lines), Col 0 starts at y=176.8, Cols 2-3 at y=172.2
        b_col1 = _block_from_lines([
            _line("Conditional", 134.9, 163.0, 171.9, 170.3),
            _line("Numerical", 134.9, 172.2, 168.7, 179.6),
            _line("Reproducibility", 134.9, 181.4, 184.2, 188.8),
            _line("(CNR)", 134.9, 190.6, 155.0, 198.0),
        ])
        b_col0 = _block_from_lines([
            _line("Intel oneMKL", 60.7, 176.8, 104.7, 184.2),
        ])
        b_col23 = _block_from_lines([
            _line("Constrains execution paths", 209.0, 176.8, 367.0, 184.2),
            _line("Reproducibility across specified CPU", 397.0, 172.2, 516.0, 179.6),
            _line("configurations", 397.0, 181.4, 443.3, 188.8),
        ])

        ref_cols = [60.7, 134.9, 209.0, 397.0]
        tbl_blocks = [b_hdr, b_col1, b_col0, b_col23]
        rows, all_lines = _build_rows_ybanded(tbl_blocks, ref_cols, 4)

        assert len(rows) == 2
        # Header row
        assert "".join(s.text for s in rows[0][0]).strip() == "Library"
        assert "".join(s.text for s in rows[0][1]).strip() == "Feature"
        assert "".join(s.text for s in rows[0][2]).strip() == "Mechanism"
        assert "".join(s.text for s in rows[0][3]).strip() == "Scope"
        # Data row 1
        assert "".join(s.text for s in rows[1][0]).strip() == "Intel oneMKL"
        assert "Conditional" in "".join(s.text for s in rows[1][1])
        assert "Constrains execution paths" in "".join(s.text for s in rows[1][2])
        assert "Reproducibility across specified CPU" in "".join(s.text for s in rows[1][3])


def _grid_row(page: int, y0: float, cells: list[tuple[str, float, float]]) -> Block:
    """One row of a bordered grid: (text, x0, x1) per cell, 7.4pt tall."""
    y1 = y0 + 7.4
    lines = [
        Line(spans=[Span(text=text, font_size=8.0)],
             bbox=(x0, y0, x1, y1), page_num=page)
        for text, x0, x1 in cells
    ]
    return Block(lines=lines,
                 bbox=(cells[0][1], y0, max(c[2] for c in cells), y1),
                 page_num=page)


class TestPass3CompletesGridRun:
    """Pass 3 completes a run that is a partial view of a find_tables()
    grid (p4016r0 D.3 and N.6): rows whose cell texts are uneven fail
    _gap_asymmetry_reject, but they sit on the run's columns inside the
    bordered region MuPDF reports, so they are rows of the same table.
    Pass 3 takes them itself, ordered by y, instead of emitting the rows
    it happened to accept (header as a heading, last row as prose).
    """

    _PAGE = 34
    _COLS = [60.7, 123.2, 248.9]
    _REGION = {34: [
        {"bbox": (57.2, 708.6, 352.4, 773.3), "row_count": 5, "col_count": 3,
         "cells": []}]}

    def _d3_blocks(self) -> list[Block]:
        # p4016r0 tomd page 34 geometry. "Property" (gaps 31.8 / 6.8pt),
        # "Standard Section" (6.8 / 48.4) and "Evaluation Order" (7.1 /
        # 78.9) fail the asymmetry gate; "Grouping" and "Complexity" pass
        # it and form Pass 3's run.
        return [
            _grid_row(self._PAGE, 711.7, [
                ("Property", 60.7, 91.4),
                ("Sequential (accumulate/fold_left)", 123.2, 242.1),
                ("Parallel (reduce)", 248.9, 308.7)]),
            _grid_row(self._PAGE, 725.1, [
                ("Standard Section", 60.7, 116.4),
                ("[accumulate] / [alg.fold]", 123.2, 200.5),
                ("[reduce]", 248.9, 276.0)]),
            _grid_row(self._PAGE, 737.7, [
                ("Grouping", 60.7, 90.9),
                ("Mandated: Left-to-right", 123.2, 199.1),
                ("Generalized Sum (Unspecified)", 248.9, 349.0)]),
            _grid_row(self._PAGE, 750.4, [
                ("Complexity", 60.7, 96.9),
                ("O(N) operations", 123.2, 175.0),
                ("O(N) operations", 248.9, 300.7)]),
            _grid_row(self._PAGE, 763.7, [
                ("Evaluation Order", 60.7, 116.1),
                ("Fully specified", 123.2, 170.0),
                ("Not specified", 248.9, 291.4)]),
        ]

    @staticmethod
    def _col0(section: Section) -> list[str]:
        return ["".join(s.text for s in row[0]).strip()
                for row in section.columns]

    def test_fixture_is_faithful(self):
        blocks = self._d3_blocks()
        assert _block_horizontal_row(blocks[0]) is None
        assert _block_horizontal_row(blocks[1]) is None
        assert _block_horizontal_row(blocks[2]) is not None
        assert _block_horizontal_row(blocks[3]) is not None
        assert _block_horizontal_row(blocks[4]) is None

    def test_left_behind_rows_are_found(self):
        blocks = self._d3_blocks()
        run = [blocks[2], blocks[3]]
        got = _grid_rows_left_behind(run, self._COLS, blocks, self._REGION)
        assert [b.lines[0].spans[0].text for b in got] == [
            "Property", "Standard Section", "Evaluation Order"]

    def test_run_is_completed_in_y_order(self):
        blocks = self._d3_blocks()
        tables, used = _detect_horizontal_row_tables(
            blocks, rotated_pages=frozenset(),
            page_mupdf_tables=self._REGION)
        assert len(tables) == 1
        assert used == {0, 1, 2, 3, 4}
        assert self._col0(tables[0]) == [
            "Property", "Standard Section", "Grouping", "Complexity",
            "Evaluation Order"]
        assert all(len(row) == 3 for row in tables[0].columns)

    def test_without_mupdf_region_pass3_keeps_its_partial_run(self):
        blocks = self._d3_blocks()
        tables, used = _detect_horizontal_row_tables(
            blocks, rotated_pages=frozenset())
        assert len(tables) == 1
        assert used == {2, 3}
        assert self._col0(tables[0]) == ["Grouping", "Complexity"]

    def test_region_reporting_no_more_rows_than_run_is_ignored(self):
        # A rows=0 box spanning stacked poll grids (p1068r11 page 7) is
        # not a view of any one run; Pass 3 keeps its own rows only.
        blocks = self._d3_blocks()
        region = {34: [{"bbox": (57.2, 708.6, 352.4, 773.3), "row_count": 0,
                        "col_count": 0, "cells": []}]}
        tables, used = _detect_horizontal_row_tables(
            blocks, rotated_pages=frozenset(), page_mupdf_tables=region)
        assert len(tables) == 1
        assert used == {2, 3}

    def test_block_off_the_columns_inside_region_does_not_qualify(self):
        # A 3-line block inside the box whose x-starts are not the run's
        # columns (a wrapped prose paragraph MuPDF split into lines at
        # the left margin) is not a row of the grid.
        blocks = self._d3_blocks()
        stray = Block(
            lines=[
                Line(spans=[Span(text=f"prose {k}", font_size=8.0)],
                     bbox=(57.5, 763.7, 340.0, 771.1), page_num=34)
                for k in range(3)],
            bbox=(57.5, 763.7, 340.0, 771.1), page_num=34)
        run = [blocks[2], blocks[3]]
        got = _grid_rows_left_behind(
            run, self._COLS, run + [stray], self._REGION)
        assert got == []

    def test_rows_beyond_the_fragment_gap_stay_out(self):
        # Two complete grids sharing columns inside one over-reaching box:
        # the far grid's rows are not chained to this run.
        blocks = self._d3_blocks()
        far = _grid_row(34, 763.7 + 60.0, [
            ("Far", 60.7, 80.0), ("x", 123.2, 130.0), ("y", 248.9, 260.0)])
        region = {34: [{"bbox": (57.2, 708.6, 352.4, 840.0), "row_count": 6,
                        "col_count": 3, "cells": []}]}
        run = [blocks[2], blocks[3]]
        got = _grid_rows_left_behind(
            run, self._COLS, blocks + [far], region)
        assert far not in got
        assert len(got) == 3


def _p4016_page54_blocks() -> list[Block]:
    """p4016r0 page_num 54 (N.14 Summary) as MuPDF delivers it.

    Header and three body rows are fused two-column blocks. The
    "Determinism" row arrives as a col-0 label block plus a separate
    three-line cell block on column 1 that overlaps the label in y
    (label is vertically centred). The "Practicality" cell wraps onto a
    trailing block whose top (431.6) is 2.8pt above the row block's
    bottom (434.4). Prose above and below stays out of the table.
    """
    return [
        _geo_block(54, ("The multi-threaded stack ordered state merge "
                        "algorithm achieves:", 57.0, 321.6, 329.6, 331.0)),
        _geo_block(54, ("Property", 60.7, 342.8, 91.4, 350.2),
                   ("Guarantee", 288.4, 342.8, 325.6, 350.2)),
        _geo_block(54, ("Determinism", 60.7, 365.2, 106.9, 372.7)),
        _geo_block(54, ("Expression-identical to the single-threaded canonical "
                        "expression for any T", 288.4, 356.1, 527.0, 363.5),
                   ("under the specified partition/merge scheme; bitwise "
                    "identity additionally", 288.4, 365.3, 523.0, 372.7),
                   ("requires a matching floating-point evaluation model (§6)",
                    288.4, 374.5, 469.7, 381.9)),
        _geo_block(54, ("Correctness", 60.7, 391.8, 103.2, 399.2),
                   ("Equivalent to the canonical pairwise tree (argument "
                    "outlined in Appendix", 288.4, 387.2, 525.2, 394.6),
                   ("N)", 288.4, 396.4, 296.4, 403.8)),
        _geo_block(54, ("Efficiency", 60.7, 409.6, 95.5, 417.1),
                   ("O(N) work, O(N/T + T log N) span",
                    288.4, 409.7, 398.4, 417.1)),
        _geo_block(54, ("Practicality", 60.7, 426.9, 101.5, 434.4),
                   ("Demonstrated competitive with, and in some configurations "
                    "faster than,", 288.4, 422.4, 522.2, 429.8)),
        _geo_block(54, ("std::reduce with SIMD on the tested platforms/harness",
                        288.4, 431.6, 467.4, 439.0)),
        _geo_block(54, ("The key insights enabling this approach are:",
                        57.0, 449.6, 239.3, 459.0)),
    ]


class TestPass1SplitRow:
    """Branch 4d: a row delivered as a col-0 label block beside a cell
    block on one non-first column (p4016r0 N.14 "Determinism"), and the
    trailing-continuation tolerance for a wrapped cell whose tail starts
    slightly above the row bottom ("Practicality")."""

    _COLS = [60.7, 288.4]

    def test_block_on_one_column(self):
        blocks = _p4016_page54_blocks()
        assert _block_on_one_column(blocks[3], self._COLS) == 1  # cell block
        assert _block_on_one_column(blocks[2], self._COLS) == 0  # label
        assert _block_on_one_column(blocks[4], self._COLS) is None  # 2-col row
        off = _geo_block(54, ("x", 150.0, 356.1, 200.0, 363.5))
        assert _block_on_one_column(off, self._COLS) is None

    def test_split_row_label_first(self):
        blocks = _p4016_page54_blocks()
        got = _try_split_row(blocks, 2, self._COLS, [blocks[1]])
        assert got is not None
        assert got.advance_to == 4
        assert got.absorbed_ids == frozenset({id(blocks[3])})

    def test_split_row_cell_first(self):
        blocks = _p4016_page54_blocks()
        blocks[2], blocks[3] = blocks[3], blocks[2]
        got = _try_split_row(blocks, 2, self._COLS, [blocks[1]])
        assert got is not None
        assert got.advance_to == 4
        assert got.absorbed_ids == frozenset({id(blocks[2])})

    def test_split_row_rejects_disjoint_y_bands(self):
        blocks = _p4016_page54_blocks()
        # Label moved below the cell block: two different rows, not one.
        blocks[2] = _geo_block(54, ("Determinism", 60.7, 385.0, 106.9, 392.5))
        assert _try_split_row(blocks, 2, self._COLS, [blocks[1]]) is None

    def test_split_row_rejects_col0_cell(self):
        blocks = _p4016_page54_blocks()
        # A multi-line block on column 0 beside a label is prose, not a cell.
        blocks[3] = _geo_block(54, ("a", 60.7, 356.1, 200.0, 363.5),
                               ("b", 60.7, 365.3, 200.0, 372.7))
        assert _try_split_row(blocks, 2, self._COLS, [blocks[1]]) is None

    def test_split_row_rejects_single_line_cell(self):
        # p4007r0 §7: "set_error on" beside "Partial results destroyed",
        # both single-line. A fragment; claiming it hides the
        # find_tables() grid from Pass 5.
        blocks = _p4016_page54_blocks()
        blocks[3] = _geo_block(54, ("Partial results destroyed",
                                    288.4, 365.2, 420.0, 372.7))
        assert _try_split_row(blocks, 2, self._COLS, [blocks[1]]) is None

    def test_split_row_rejects_wider_table(self):
        # p4098r1 §2.6: four columns; a label plus one cell block is not
        # a row.
        blocks = _p4016_page54_blocks()
        cols = [60.7, 200.0, 288.4, 400.0]
        assert _try_split_row(blocks, 2, cols, [blocks[1]]) is None

    def test_split_row_rejects_label_below_cell_band(self):
        # Label overlaps the cell's last line only: two rows, not one
        # centred label.
        blocks = _p4016_page54_blocks()
        blocks[2] = _geo_block(54, ("Determinism", 60.7, 378.0, 106.9, 385.5))
        assert _try_split_row(blocks, 2, self._COLS, [blocks[1]]) is None

    def test_split_row_rejects_other_page(self):
        blocks = _p4016_page54_blocks()
        blocks[3].page_num = 55
        assert _try_split_row(blocks, 2, self._COLS, [blocks[1]]) is None

    def test_trailing_continuation_tolerates_small_negative_gap(self):
        blocks = _p4016_page54_blocks()
        tail, row = blocks[7], blocks[6]
        assert tail.bbox[1] - row.bbox[3] == pytest.approx(-2.8)
        assert _is_trailing_continuation(tail, self._COLS, row.bbox[3], True)

    def test_trailing_continuation_rejects_large_overlap(self):
        blocks = _p4016_page54_blocks()
        tail, row = blocks[7], blocks[6]
        assert not _is_trailing_continuation(
            tail, self._COLS, row.bbox[3] + 10.0, True)

    def test_n14_summary_is_one_table(self):
        blocks = _p4016_page54_blocks()
        sections, remaining = detect_tables(blocks)
        assert len(sections) == 1
        sec = sections[0]
        assert sec.table_source == "horizontal_rows"
        assert len(sec.columns) == 5  # rows
        assert all(len(r) == 2 for r in sec.columns)
        assert [_cell_text(r[0]) for r in sec.columns] == [
            "Property", "Determinism", "Correctness", "Efficiency",
            "Practicality"]
        assert _cell_text(sec.columns[1][1]).startswith(
            "Expression-identical to the single-threaded")
        assert _cell_text(sec.columns[1][1]).endswith(
            "evaluation model (§6)")
        assert _cell_text(sec.columns[4][1]) == (
            "Demonstrated competitive with, and in some configurations "
            "faster than, std::reduce with SIMD on the tested "
            "platforms/harness")
        assert [b.lines[0].text for b in remaining] == [
            "The multi-threaded stack ordered state merge algorithm achieves:",
            "The key insights enabling this approach are:"]

    def test_n14_summary_cell_block_first(self):
        # MuPDF may deliver the cell block before its label; the label
        # must still own the row (otherwise the partial-marked cell
        # merges backward into the header row).
        blocks = _p4016_page54_blocks()
        blocks[2], blocks[3] = blocks[3], blocks[2]
        sections, _ = detect_tables(blocks)
        assert len(sections) == 1
        sec = sections[0]
        assert [_cell_text(r[0]) for r in sec.columns] == [
            "Property", "Determinism", "Correctness", "Efficiency",
            "Practicality"]
        assert _cell_text(sec.columns[0][1]) == "Guarantee"
        assert _cell_text(sec.columns[1][1]).startswith(
            "Expression-identical to the single-threaded")

    def test_split_row_stands_down_on_two_column_pages(self):
        # A left-column heading beside a right-column paragraph has the
        # same geometry; Pass 1 must not build a row out of it there.
        blocks = _p4016_page54_blocks()
        sections, _ = detect_tables(blocks, two_column_pages=frozenset({54}))
        assert not any(
            _cell_text(r[0]) == "Determinism"
            for s in sections for r in s.columns)


def _vote_header(page: int, y0: float) -> Block:
    """A one-block SF/F/N/A/SA poll header, P3978R0 tomd page 1 geometry."""
    return _grid_row(page, y0, [
        ("SF", 79.7, 91.4), ("F", 103.5, 109.6), ("N", 121.7, 129.7),
        ("A", 141.7, 148.7), ("SA", 160.7, 173.3)])


def _caption(page: int, y0: float, text: str) -> Block:
    return Block(
        lines=[Line(spans=[Span(text=text, font_size=10.0)],
                    bbox=(73.7, y0, 216.1, y0 + 10.6), page_num=page)],
        bbox=(73.7, y0, 216.1, y0 + 10.6), page_num=page)


class TestPass3EmptyVoteGrid:
    """A suggested poll is a lone SF/F/N/A/SA header block with empty
    cells below it (P3978R0 §2.1, #422). Pass 3 used to need two blocks
    per run, so three such headers and their captions fell to Pass 4,
    which fused them into one table. A lone vote header now forms a
    2-row table with a synthesized empty body row, the shape Pass 3a
    emits for P4012R0 §2.2.
    """

    _PAGE = 1

    def _p3978_blocks(self) -> list[Block]:
        return [
            _caption(self._PAGE, 207.9, "Poll: Adopt P3978R0 for C++26"),
            _vote_header(self._PAGE, 224.7),
            _caption(self._PAGE, 269.3, "Poll: Adopt P3978R0 for C++29"),
            _vote_header(self._PAGE, 286.2),
            _caption(self._PAGE, 330.8,
                     "Poll: Adopt P3978R0 for C++29 and apply as a DR"),
            _vote_header(self._PAGE, 347.7),
        ]

    def test_fixture_is_faithful(self):
        blocks = self._p3978_blocks()
        assert _block_horizontal_row(blocks[1]) is not None
        assert _block_horizontal_row(blocks[0]) is None

    def test_each_header_is_its_own_table(self):
        blocks = self._p3978_blocks()
        tables, used = _detect_horizontal_row_tables(
            blocks, rotated_pages=frozenset())
        assert len(tables) == 3
        assert used == {1, 3, 5}
        for t in tables:
            assert len(t.columns) == 2
            assert [_cell_text(c) for c in t.columns[0]] == [
                "SF", "F", "N", "A", "SA"]
            assert [_cell_text(c) for c in t.columns[1]] == [""] * 5
            assert t.table_kind == "clean_matrix"

    def test_captions_stay_prose_through_detect_tables(self):
        blocks = self._p3978_blocks()
        sections, remaining = detect_tables(blocks)
        tables = [s for s in sections if s.kind == SectionKind.TABLE]
        assert len(tables) == 3
        assert [b.lines[0].text for b in remaining] == [
            "Poll: Adopt P3978R0 for C++26",
            "Poll: Adopt P3978R0 for C++29",
            "Poll: Adopt P3978R0 for C++29 and apply as a DR"]

    def test_header_with_number_row_below_is_one_filled_table(self):
        # The taken-poll shape (p2728r11, p3290r4): the number row sits
        # 12pt under the header and joins the run; no empty row appears.
        header = _vote_header(self._PAGE, 224.7)
        numbers = _grid_row(self._PAGE, 236.7, [
            ("8", 82.0, 88.0), ("3", 104.0, 110.0), ("1", 123.0, 129.0),
            ("0", 142.0, 148.0), ("0", 164.0, 170.0)])
        tables, used = _detect_horizontal_row_tables(
            [header, numbers], rotated_pages=frozenset())
        assert len(tables) == 1
        assert used == {0, 1}
        assert [_cell_text(c) for c in tables[0].columns[1]] == [
            "8", "3", "1", "0", "0"]

    def test_lone_dash_row_is_not_a_vote_header(self):
        # p1068r11's rendered separator row has the geometry but not the
        # vocabulary; it must not become a header-only table.
        dashes = _grid_row(self._PAGE, 224.7, [
            ("-", 82.0, 88.0), ("-", 104.0, 110.0), ("-", 123.0, 129.0),
            ("-", 142.0, 148.0), ("-", 164.0, 170.0)])
        tables, used = _detect_horizontal_row_tables(
            [dashes], rotated_pages=frozenset())
        assert tables == [] and used == set()

    def test_lone_non_vote_row_is_not_claimed(self):
        row = _grid_row(self._PAGE, 224.7, [
            ("Name", 79.7, 100.0), ("Type", 121.7, 140.0),
            ("Note", 160.7, 180.0)])
        tables, used = _detect_horizontal_row_tables(
            [row], rotated_pages=frozenset())
        assert tables == [] and used == set()


def _cell_line(text: str, x0: float, x1: float, y0: float, y1: float) -> Line:
    return Line(
        spans=[Span(text=text, font_size=10.0, bbox=(x0, y0, x1, y1))],
        bbox=(x0, y0, x1, y1),
    )


def _spans_line(parts: list[tuple[str, float, float]], y0: float, y1: float) -> Line:
    spans = [
        Span(text=text, font_size=10.0, bbox=(x0, y0, x1, y1))
        for text, x0, x1 in parts
    ]
    return Line(
        spans=spans,
        bbox=(parts[0][1], y0, parts[-1][2], y1),
    )


class TestMultiRowBodyBlock:
    """One header row plus one block of data rows (P0533R9 Tables II-V).

    MuPDF puts every data row in a single block. Each row is sibling
    lines that return to column 0, so _block_column_positions gives up
    and Pass 1 used to keep only the header.
    """

    def _header(self) -> Block:
        lines = [
            _cell_line("Function", 322.3, 370.0, 221.8, 230.8),
            _spans_line(
                [("Pass", 495.8, 515.0), ("Comment", 517.6, 556.8)],
                221.8, 230.8),
        ]
        return _block_from_lines(lines)

    def _body(self) -> Block:
        lines = [
            _spans_line(
                [("float", 322.3, 345.8), ("frexp(float", 350.6, 402.3),
                 ("value,", 407.0, 435.3), ("int*", 440.0, 458.8),
                 ("exp)", 463.5, 482.4)],
                237.4, 246.4),
            _cell_line("Yes", 497.8, 516.0, 237.0, 246.0),
            _cell_line("w", 533.9, 542.0, 237.0, 246.0),
            _spans_line(
                [("int", 322.3, 339.0), ("ilogb(float", 341.1, 395.0),
                 ("arg)", 397.6, 420.0)],
                250.6, 259.6),
            _cell_line("Yes", 497.8, 516.0, 250.2, 259.2),
            _cell_line("G", 533.6, 541.0, 250.2, 259.2),
            _spans_line(
                [("float", 322.3, 345.8), ("modf(float", 350.6, 397.6),
                 ("value,", 402.3, 430.6), ("float*", 435.3, 463.5),
                 ("iptr)", 468.2, 490.0), ("Yes", 497.8, 516.0)],
                289.8, 299.2),
        ]
        return _block_from_lines(lines)

    def test_header_and_body_become_one_clean_matrix(self):
        tables, remaining = detect_tables([self._header(), self._body()])
        assert len(tables) == 1
        table = tables[0]
        assert table.table_kind == "clean_matrix"
        assert table.table_source == "multirow_body"
        assert table.table_strategy == "pipe_table"
        cells = [
            ["".join(sp.text for sp in cell).strip() for cell in row]
            for row in table.columns
        ]
        assert cells[0] == ["Function", "Pass", "Comment"]
        assert cells[1] == [
            "float frexp(float value, int* exp)", "Yes", "w"]
        assert cells[2][1:] == ["Yes", "G"]
        assert cells[3] == [
            "float modf(float value, float* iptr)", "Yes", ""]
        assert "iptr)" in cells[3][0]
        assert "Yes" not in cells[3][0]
        assert remaining == []

    def test_styled_header_fragments_do_not_create_a_column(self):
        header = _block_from_lines([
            _spans_line(
                [("Func", 322.3, 340.0), ("tion", 350.6, 370.0)],
                221.8, 230.8),
            _spans_line(
                [("Pass", 495.8, 515.0), ("Comment", 517.6, 556.8)],
                221.8, 230.8),
        ])
        tables, _remaining = detect_tables([header, self._body()])
        assert len(tables) == 1
        assert len(tables[0].columns[0]) == 3
        text = "".join(sp.text for sp in tables[0].columns[0][0])
        assert text.replace(" ", "") == "Function"

    def test_contiguous_styled_header_fragments_are_one_cell(self):
        header = _block_from_lines([
            _spans_line(
                [("Func", 322.3, 340.0), ("tion", 340.0, 370.0)],
                221.8, 230.8),
            _spans_line(
                [("Pass", 495.8, 515.0), ("Comment", 517.6, 556.8)],
                221.8, 230.8),
        ])
        tables, _remaining = detect_tables([header, self._body()])
        assert len(tables) == 1
        assert len(tables[0].columns[0]) == 3
        assert "".join(
            sp.text for sp in tables[0].columns[0][0]
        ) == "Function"

    def test_rotated_page_defers_the_multirow_family(self):
        fragment = _banded_frag([(50.0, 60.0), (60.0, 70.0)])
        tables, _remaining = detect_tables(
            [self._header(), self._body()],
            page_mupdf_tables={0: [fragment]},
        )
        assert all(table.table_source != "multirow_body" for table in tables)

    def test_prose_under_a_wide_header_is_not_a_table(self):
        header = self._header()
        prose = _block_from_lines([
            _cell_line(text, 322.3, 520.0, 240.0 + i * 14, 250.0 + i * 14)
            for i, text in enumerate(
                ("The functions listed below", "close on the rationals",
                 "and do not set a flag"))
        ])
        tables, _remaining = detect_tables([header, prose])
        assert tables == []

    def test_body_starting_far_above_header_is_not_claimed(self):
        header = self._header()
        body = self._body()
        shift = -200.0
        for line in body.lines:
            line.bbox = (
                line.bbox[0], line.bbox[1] + shift,
                line.bbox[2], line.bbox[3] + shift)
            for span in line.spans:
                span.bbox = (
                    span.bbox[0], span.bbox[1] + shift,
                    span.bbox[2], span.bbox[3] + shift)
        body.bbox = (
            body.bbox[0], body.bbox[1] + shift,
            body.bbox[2], body.bbox[3] + shift)
        tables, _remaining = detect_tables([header, body])
        assert tables == []

    def test_trailing_prose_in_body_block_stays_prose(self):
        body = self._body()
        prose = _cell_line(
            "Following discussion continues here.",
            322.3, 520.0, 310.0, 320.0)
        body.lines.append(prose)
        body.bbox = (
            body.bbox[0], body.bbox[1],
            max(body.bbox[2], prose.bbox[2]), prose.bbox[3])
        tables, remaining = detect_tables([self._header(), body])
        assert len(tables) == 1
        assert len(tables[0].columns) == 4
        assert len(remaining) == 1
        assert remaining[0].text == "Following discussion continues here."
        assert all(
            "Following discussion" not in line.text
            for line in tables[0].lines
        )

    def test_contents_page_numbers_are_not_a_table(self):
        header = _block_from_lines([
            _cell_line("1. Introduction", 72, 180, 356, 366),
            _cell_line("3", 533.9, 545, 356, 366),
        ])
        body_lines = []
        for title, page, y in (
            ("2. History/Changes from Previous Release", "3", 379),
            ("2020-08-28 [D1122R3] after virtual LWG meeting", "3", 392),
            ("2020-08-25 [D1122R3] preparation for virtual LWG meeting", "4", 405),
        ):
            body_lines.append(_cell_line(title, 72, 400, y, y + 9))
            body_lines.append(_cell_line(page, 533.9, 545, y, y + 9))
        tables, remaining = detect_tables([header, _block_from_lines(body_lines)])
        assert tables == []
        assert len(remaining) == 2

    def _page_number_rows(self) -> list[Block]:
        rows = []
        entries = (
            ("I. Revision History", "1", 80),
            ("II. Introduction", "1", 100),
            ("III. Motivation & Scope", "1", 120),
            ("IV. State of the Art", "3", 140),
        )
        for title, page, y in entries:
            rows.append(_block_from_lines([
                _cell_line(title, 54, 220, y, y + 10),
                _cell_line(page, 400, 420, y, y + 10),
            ]))
        return rows

    def test_labeled_contents_without_dot_leaders_is_not_a_table(self):
        contents = _block_from_lines([
            _cell_line("CONTENTS", 54, 130, 40, 52),
        ])
        tables, remaining = detect_tables([contents, *self._page_number_rows()])
        assert tables == []
        assert len(remaining) == 5

    def test_page_numbers_without_contents_label_stay_a_table(self):
        tables, remaining = detect_tables(self._page_number_rows())
        assert len(tables) == 1
        assert tables[0].table_source == "horizontal_rows"
        assert len(tables[0].columns) == 4
        assert remaining == []

    def test_contents_prefix_is_removed_from_paragraph_lines(self):
        lines = []
        y = 10.0
        for text in (
            "CONTENTS",
            "I. Revision History", "1",
            "II. Introduction", "1",
            "III. Motivation", "1",
            "R1 Includes discussion",
        ):
            lines.append(Line(
                spans=[Span(text=text, font_size=10.0, bbox=(54, y, 220, y + 10))],
                bbox=(54, y, 220, y + 10),
                page_num=0,
            ))
            y += 14
        sec = Section(
            kind=SectionKind.HEADING,
            text="\n".join(ln.text for ln in lines),
            heading_level=3,
            lines=lines,
            page_num=0,
            mupdf_text="\n".join(ln.text for ln in lines),
            spatial_text=(
                "CONTENTS R6 interleaved\n"
                "I. Revision History 1\n"
                "other spatial evidence\n"
                "II. Introduction 1\n"
                "III. Motivation 1\n"
                "stale spatial source"
            ),
            columns=[[[Span(text="stale")]]],
            indent_level=2,
            table_kind="clean_matrix",
            table_strategy="pipe_table",
            table_source="horizontal_rows",
            table_continuation=True,
        )
        _drop_leading_contents(sec)
        assert [ln.text for ln in sec.lines] == ["R1 Includes discussion"]
        assert sec.text == "R1 Includes discussion"
        assert sec.mupdf_text == "R1 Includes discussion"
        assert "CONTENTS" not in sec.spatial_text
        assert "Revision History" not in sec.spatial_text
        assert "other spatial evidence" in sec.spatial_text
        assert "stale spatial source" in sec.spatial_text
        assert sec.spatial_text != sec.text
        assert sec.kind == SectionKind.PARAGRAPH
        assert sec.heading_level == 0
        assert sec.columns == []
        assert sec.indent_level == 0
        assert sec.table_kind is None
        assert sec.table_strategy is None
        assert sec.table_source is None
        assert not sec.table_continuation


def _placed(text, x0, y0, x1, y1, page=4, kind=SectionKind.PARAGRAPH):
    line = Line(
        spans=[Span(text=text, font_size=10.0)],
        bbox=(x0, y0, x1, y1),
        page_num=page,
    )
    return Section(kind=kind, text=text, lines=[line], page_num=page)


class TestTwoColumnTableInsert:
    """A table goes back where the column sort put its blocks.

    Raw y would put a right-column table (small y) ahead of the whole
    left column. The split keeps each column together.
    """

    def test_right_column_table_stays_after_the_left_column(self):
        sections = [
            _placed("REFERENCES", 54, 55, 160, 64),
            _placed("body of the references", 54, 80, 250, 160),
            _placed("proposed wording", 54, 539, 250, 700),
            _placed("TABLE V caption", 317, 235, 520, 255),
        ]
        table = _placed(
            "Function", 322, 54, 540, 64, kind=SectionKind.TABLE)
        _insert_table_sections(sections, [table], {}, {4: 300.0})
        assert [s.text for s in sections] == [
            "REFERENCES",
            "body of the references",
            "proposed wording",
            "Function",
            "TABLE V caption",
        ]

    def test_left_column_table_stays_inside_its_column(self):
        sections = [
            _placed("REFERENCES", 54, 55, 160, 64),
            _placed("caption IV", 54, 470, 250, 490),
            _placed("right column prose", 317, 54, 520, 80),
        ]
        table = _placed("ceil", 56, 184, 280, 194, kind=SectionKind.TABLE)
        _insert_table_sections(sections, [table], {}, {4: 300.0})
        assert [s.text for s in sections] == [
            "REFERENCES",
            "ceil",
            "caption IV",
            "right column prose",
        ]

    def test_narrow_header_word_stays_in_the_right_column(self):
        # Page 4's split is 362, inside the right column. The header
        # word "Function" is only x=322-358; the row reaches Comment.
        sections = [
            _placed("REFERENCES", 140, 55, 213, 64),
            _placed("TABLE V caption", 317, 235, 540, 255),
        ]
        table = _placed(
            "Function", 322, 54, 358, 64, kind=SectionKind.TABLE)
        table.lines.append(Line(
            spans=[Span(text="Comment", font_size=10.0)],
            bbox=(517, 54, 560, 64),
            page_num=4,
        ))
        _insert_table_sections(sections, [table], {}, {4: 362.5})
        assert [s.text for s in sections] == [
            "REFERENCES",
            "Function",
            "TABLE V caption",
        ]

    def test_cross_page_tail_does_not_choose_the_column(self):
        section = _placed("left-column start", 54, 100, 250, 120)
        section.lines.append(Line(
            spans=[Span(text="right-column continuation", font_size=10.0)],
            bbox=(400, 50, 560, 70),
            page_num=5,
        ))
        assert _column_of(section, 300.0, None) == 0

    def test_single_column_still_inserts_by_y(self):
        sections = [
            _placed("above", 54, 40, 400, 50, page=1),
            _placed("below", 54, 200, 400, 220, page=1),
        ]
        table = _placed(
            "grid", 54, 100, 400, 110, page=1, kind=SectionKind.TABLE)
        _insert_table_sections(sections, [table], {}, {})
        assert [s.text for s in sections] == ["above", "grid", "below"]


def _multirow(text, x0, y0, x1, y1, page=4):
    sec = _placed(text, x0, y0, x1, y1, page=page, kind=SectionKind.TABLE)
    sec.table_source = "multirow_body"
    return sec


class TestSideBySideMultirowOrder:
    """Overlapping multirow tables read left, then right, then continue."""

    def _column_major(self):
        return [
            _placed("REFERENCES", 54, 55, 160, 64),
            _multirow("ceil", 56, 184, 280, 450),
            _placed("TABLE IV caption", 54, 460, 250, 480),
            _placed("VIII. PROPOSED WORDING", 54, 514, 250, 530),
            _multirow("fpclassify", 322, 54, 540, 224),
            _placed("TABLE V caption", 317, 235, 520, 255),
        ]

    def test_overlapping_pair_reads_left_then_right(self):
        sections = self._column_major()
        _insert_table_sections(sections, [], {}, {4: 300.0})
        assert [s.text for s in sections] == [
            "REFERENCES",
            "ceil",
            "TABLE IV caption",
            "fpclassify",
            "TABLE V caption",
            "VIII. PROPOSED WORDING",
        ]

    def test_non_overlapping_right_table_stays_after_the_left_column(self):
        sections = [
            _multirow("ceil", 56, 184, 280, 300),
            _placed("VIII. PROPOSED WORDING", 54, 320, 250, 340),
            _multirow("later", 322, 420, 540, 500),
        ]
        _insert_table_sections(sections, [], {}, {4: 300.0})
        assert [s.text for s in sections] == [
            "ceil",
            "VIII. PROPOSED WORDING",
            "later",
        ]

    def test_other_family_is_not_hoisted(self):
        sections = self._column_major()
        sections[4].table_source = "horizontal_rows"
        _insert_table_sections(sections, [], {}, {4: 300.0})
        assert [s.text for s in sections][3] == "VIII. PROPOSED WORDING"

    def test_single_column_does_not_hoist(self):
        sections = []
        _insert_table_sections(sections, [
            _multirow("fpclassify", 322, 54, 540, 224),
            _multirow("ceil", 56, 184, 280, 450),
        ], {}, {})
        assert [s.text for s in sections] == ["fpclassify", "ceil"]

    def test_rotated_page_does_not_hoist(self):
        sections = self._column_major()
        _insert_table_sections(sections, [], {4: _ROT90}, {4: 300.0})
        assert [s.text for s in sections][3] == "VIII. PROPOSED WORDING"

    def test_text_above_the_right_table_blocks_the_hoist(self):
        sections = [
            _multirow("ceil", 56, 200, 280, 400),
            _placed("TABLE IV caption", 54, 410, 250, 430),
            _placed("VIII. PROPOSED WORDING", 54, 450, 250, 470),
            _placed("right prologue", 317, 50, 520, 80),
            _multirow("fpclassify", 322, 220, 540, 320),
            _placed("TABLE V caption", 317, 330, 520, 350),
        ]
        _insert_table_sections(sections, [], {}, {4: 300.0})
        assert [s.text for s in sections] == [
            "ceil",
            "TABLE IV caption",
            "VIII. PROPOSED WORDING",
            "right prologue",
            "fpclassify",
            "TABLE V caption",
        ]

    def test_plain_paragraph_below_table_is_not_its_caption(self):
        sections = [
            _multirow("ceil", 56, 200, 280, 400),
            _placed("TABLE IV caption", 54, 410, 250, 430),
            _placed("VIII. PROPOSED WORDING", 54, 450, 250, 470),
            _multirow("fpclassify", 322, 220, 540, 320),
            _placed("ordinary paragraph", 317, 330, 520, 350),
        ]
        _insert_table_sections(sections, [], {}, {4: 300.0})
        assert [s.text for s in sections] == [
            "ceil",
            "TABLE IV caption",
            "fpclassify",
            "VIII. PROPOSED WORDING",
            "ordinary paragraph",
        ]


class TestRunningHeaderGrid:
    """A document-id column is page furniture, not a table (P3978R3)."""

    def test_paper_id_beside_section_titles_is_not_a_table(self):
        blocks = [
            _geo_block(0, ("P3978R3", 40, 100, 90, 112),
                       ("3 Motivation", 200, 100, 320, 112)),
            _geo_block(0, ("3.2", 40, 120, 70, 132),
                       ("status quo examples", 200, 120, 340, 132)),
        ]
        tables, remaining = detect_tables(blocks)
        assert tables == []
        assert remaining == []

    def test_two_column_comparison_with_real_header_stays(self):
        blocks = [
            _geo_block(0, ("Library", 40, 100, 100, 112),
                       ("Status", 200, 100, 260, 112)),
            _geo_block(0, ("Capy", 40, 120, 80, 132),
                       ("Published", 200, 120, 280, 132)),
            _geo_block(0, ("Corosio", 40, 140, 90, 152),
                       ("Published", 200, 140, 280, 152)),
        ]
        tables, _ = detect_tables(blocks)
        assert len(tables) == 1
        assert _cell_text(tables[0].columns[0][0]) == "Library"

    def test_a_later_paper_id_is_not_furniture(self):
        blocks = [
            _geo_block(0, ("P3978R3", 40, 100, 100, 112),
                       ("3 Motivation", 200, 100, 320, 112)),
            _geo_block(0, ("P1234R0", 40, 120, 100, 132),
                       ("Other paper", 200, 120, 320, 132)),
        ]
        tables, remaining = detect_tables(blocks)
        assert tables or remaining


class TestHashHeaderAboveNumberedRow:
    """`# | Paper | Abstraction` joins above row 1 (P4100R0 section 7.1)."""

    def _numbered_rows(self):
        rows = [
            _geo_block(0, ("#", 66, 80, 74, 92),
                       ("Paper", 94, 80, 130, 92),
                       ("Abstraction", 196, 80, 260, 92)),
        ]
        labels = [
            ("1", "IoAwaitable Protocol", "Coroutine execution protocol"),
            ("2", "Coroutine Task", "task and launch functions"),
            ("3", "Executor Utilities", "strand and any_executor"),
            ("4", "Buffer Ranges", "scatter and gather"),
            ("5", "Stream Concepts", "async byte IO"),
        ]
        y = 110
        for a, b, c in labels:
            rows.append(_geo_block(
                0, (a, 66, y, 74, y + 12),
                (b, 94, y, 160, y + 12),
                (c, 196, y, 360, y + 12)))
            y += 20
        return rows

    def test_hash_line_becomes_the_header(self):
        tables, _ = detect_tables(self._numbered_rows())
        assert len(tables) == 1
        assert _cell_text(tables[0].columns[0][0]) == "#"
        assert _cell_text(tables[0].columns[0][1]) == "Paper"
        assert _cell_text(tables[0].columns[1][0]) == "1"

    def test_numbered_header_without_hash_line_stays(self):
        rows = self._numbered_rows()[1:]
        tables, _ = detect_tables(rows)
        assert len(tables) == 1
        assert _cell_text(tables[0].columns[0][0]) == "1"
