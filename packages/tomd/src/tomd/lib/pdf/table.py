"""Table detection, classification, and rendering strategy from MuPDF blocks.

Table Family (6 kinds, corpus-validated against 768 tables from 124 WG21 PDFs):

  CLEAN_MATRIX   Short-text cells (<15 words).  Pipe table.
                  Schedule grids, vote tallies, feature comparisons.
  PROSE_TABLE    Any cell >15 words.  Pipe table (HTML if cells have newlines).
                  Rationale tables, design-alternative comparisons.
  CODE_COMPARISON  "Tony Tables".  High monospace ratio, few cols/rows.  HTML
                  table with <pre> blocks.  Side-by-side before/after code.
  SPEC_TABLE     WG21 requirement tables.  3 columns, header matches
                  "expression|operation" + "return|type".  HTML table.
                  Concept requirement tables (io_awaitable, executor).
  KEY_VALUE      2-column tables with short field labels in col-0 (<=8 words)
                  and longer descriptive values in col-1 (>15 words).  Pipe
                  table.  Platform/compiler schema tables (Field | Value).
                  Single-orphan continuation blocks at col-1 x-position are
                  backward-merged into the previous row via partial_absorbed.
  FALSE_POSITIVE  >50% empty cells or ragged columns.  Skipped.

Detection passes (run in order, each consumes matched blocks):

  Pre-pass (atomized side-by-side): Pass 2's detector with
    atomized_only=True, run before Pass 1 so tables whose cells arrive as
    one block per wrapped line (Google Docs exports) are not taken line by
    line as Pass 1 rows.  Entry via an atomized header (line blocks over
    more x-positions than the seed has columns), a regular header row
    block over a shattered body (_body_is_atomized), or a header-grid
    seed (_header_grid_positions: 3+ cells on one baseline, first column
    narrower than _COLUMN_GAP_THRESHOLD, body lines on every column; the
    header's grid replaces the body clustering).  A recovered
    two-column header with at least one WG21 paper-id-plus-Section cell
    (the other cell may be a short header-like label) may adopt that
    grid when later prose inflates body x-clusters, and may accept a
    single atomized body row.  A citation header split across separate
    blocks (wrapped section number beside the other column) is a
    pre-pass seed when the reconstructed cells match that same family.
    A citation title over the value column followed by exactly three
    Yes/But/Actually row blocks (gap just under the 50pt column gate)
    is the same family.  Dense-table and mid-table-seed gates bound
    it; stacked tables on one page seed in turn.
    table_source="side_by_side_prepass".
  Pass 1 (inline-column): blocks with 2+ lines whose x-starts have gaps
    > _COLUMN_GAP_THRESHOLD.  A same-baseline header whose cells share one
    row, followed by one block of data rows (each row returns to column 0;
    the cells of a row are sibling lines), is its own detection family
    (table_source="multirow_body"; the semantic kind stays clean_matrix
    when the cells are short).  A two-column run of bare page numbers
    under a same-page Contents label is a contents list, not a table.
    A 2-column grid whose header cell is a WG21 document id is page
    furniture: Pass 1 and the side-by-side pass consume it and emit
    nothing.  Orphan absorption for wrapped cell first-lines
    (forward, col 0) and wrapped tails (backward, col 1+, any column count);
    a trailing continuation without a confirming row is absorbed in-loop
    (Branch 4c) so a following partial row still joins.  Fragment
    absorption reaches at most _PARTIAL_ROW_MAX_Y_GAP below the last row.
  Pass 2 (side-by-side blocks): each cell is a separate MuPDF block at a
    different x-position (Tony Tables with multi-line code cells).
  Pass 3 (horizontal-row): narrow poll/vote grids with small column gaps.
    A lone SF/F/N/A/SA header block with no row below it is an empty
    suggested poll and gets a synthesized empty body row.
  Pass 4 (column-aligned): borderless tables where MuPDF distributes columns
    across separate single-column blocks.  Span-level x-position clustering.
  Pass 4b (spec-label): WG21 requirement tables anchored by a "Table N - ..."
    caption.  Collects all blocks (including monospace expression cells) in
    the spatial region below the label.  Cross-page continuation supported.
  Pass 5 (MuPDF native): fallback using MuPDF find_tables() on remaining blocks.
  Post-passes (pass-agnostic): header cluster absorption (free blocks
    directly above a table whose lines sit on its columns become the header
    row, _collect_header_cluster); when that header cell is a bare integer,
    a second look prepends a `#` line sitting above it.  Separator-row
    removal drops a body row of dash-only cells (_drop_separator_rows).

Classification flow:
  detect_tables() -> _compute_table_signals() -> _classify_table()
  -> _STRATEGY_MAP -> emit.py rendering dispatch.

Optional Docling enrichment (ml_tables=True):
  Docling re-grids cells via ML, then _classify_and_annotate re-classifies.
  Can upgrade PROSE_TABLE to SPEC_TABLE when Docling provides the header row.
"""

import logging
import re
from bisect import bisect_right
from collections import Counter, defaultdict
from collections.abc import Set as AbstractSet
from dataclasses import replace
from enum import Enum
from typing import NamedTuple, Optional

from tomd.domain.elements import Confidence

from ..toc import MIN_TOC_RUN, is_toc_label
from .types import Block, Line, Span, Section, SectionKind, compute_bbox

_log = logging.getLogger(__name__)


_COLUMN_GAP_THRESHOLD = 50.0
_MIN_TABLE_ROWS = 2
_COLUMN_X_TOLERANCE = 10.0
_COLUMN_X_END_TOLERANCE = 1.0
_TABLE_Y_OVERLAP_MARGIN = 5.0

_COLUMN_X_BUCKET = 5.0    # bucket size for x-position clustering
_Y_BAND_HEIGHT   = 15.0   # bucket size for y-position clustering
_MIN_SHARED_YBANDS = 2    # x must co-occur with other columns in 2+ y-bands

# Partial-row absorption: a columnar block with fewer columns than the
# table header may be a row whose rightmost columns were split into
# separate blocks by MuPDF.  Accept it when all its x-positions are a
# subset of the table's reference columns and the y-gap is small.
_PARTIAL_ROW_MAX_Y_GAP = 25.0
# A data row packed into one block: sibling lines of the same row stay
# within this many points in y0 (Yes sits 0.4pt off the function line;
# the next row is ~13pt below). A larger jump starts the next row.
_MULTIROW_SAME_ROW_Y = 4.0
# Body line starts may sit right of a short header label (Comment -> G|U).
_MULTIROW_BODY_X_SUPPORT_TOL = 25.0
# Adjacent labels can be distinct columns even when the body column is empty.
_MULTIROW_ADJACENT_HEADER_GAP = 5.0
# Gap between adjacent spans that is a word space rather than kerning.
# "float" / "frexp" is a few points; "G" / "|" is under one.
_SPAN_WORD_GAP = 2.0
# A last column of bare page numbers is a table of contents
# ("1. Introduction" | "3"), not a data column.
_PAGE_NUMBER_CELL_RE = re.compile(r"\d{1,3}")

# Side-by-side table constants
_SBS_MAX_SCAN_GAP = 30.0  # max y-gap before stopping body scan
_SBS_MAX_SCAN_GAP_ALIGNED = 50.0  # larger tolerance for column-aligned blocks
_SBS_COL_ALIGN_TOL = 25.0  # max x-distance to count as column-aligned
_SBS_ROW_Y_BAND = 10.0    # max y-gap between col-0 blocks in the same row
_ATOMIZED_HDR_MAX_HEIGHT = 60.0  # max header region height for recovery
_ATOMIZED_HDR_MAX_LINE_GAP = 10.0  # y-gap ending the header block set
_ATOMIZED_HDR_MAX_CONSEC_SINGLE = 3  # stop after N consecutive 1-col rows
_ATOMIZED_PREPASS_MIN_ROWS = 5  # min body rows for the atomized-only pre-pass
# Dense shattered tables (Google-Docs exports: one block per wrapped line,
# every row populating all or all-but-one column) are accepted by the
# pre-pass at a lower row count, so Pass 1 cannot steal their fused
# col-0/col-1 blocks first. Both conditions must hold.
_ATOMIZED_PREPASS_MIN_ROWS_DENSE = 4
_ATOMIZED_PREPASS_DENSE_MIN_COLS = 3
# Two-column citation comparison box: at least one header cell begins
# with a WG21 paper id plus "Section", the body is one atomized quoted
# row. Does not lower the 4/5-row gates for any other atomized table.
_ATOMIZED_PREPASS_MIN_ROWS_CITATION = 1
# Header cell starts with P2300R10 Section / n5000r1 section, optional
# wrapped section number on the next line of the same column.
_WG21_CITATION_SECTION_HEADER_RE = re.compile(
    r"^[PN]\d{3,5}R\d+\s+Section\b",
    re.IGNORECASE,
)
# Non-citation sibling of a citation header cell: "Context", "The
# receiver concept". Longer prose in that slot is not a header.
_CITATION_HEADER_LABEL_MAX_WORDS = 4
# Citation title over the value column, then Yes / But / Actually as
# three two-line row blocks. Label-to-value gap is just under
# _COLUMN_GAP_THRESHOLD, so _block_column_positions misses them.
_YBA_LABELS = ("Yes", "But", "Actually")
_YBA_MAX_ROW_GAP = 25.0
_YBA_MAX_WRAP_GAP = 10.0
# One continuation of the Actually value. A second same-column line
# inside the wrap gap is the next sentence, not part of the cell.
_YBA_MAX_WRAPS = 1
# Mid-table seed guard: a genuine atomized header has prose or a heading
# (left margin) above it. A cell aligned to column 1+ within this many
# points above the seed means the seed is a data row of a table whose
# real header sits higher up or on the previous page.
_ATOMIZED_SEED_ABOVE_GAP = 40.0
# Atomized body under a regular header row block: the pre-pass claims it
# when at least this fraction of the grouped rows is built from 2+
# blocks and at least this fraction of the body blocks is single-line
# (one block per wrapped line). Pass 1 would take each such line as a
# row of its own.
_ATOMIZED_BODY_MIN_SINGLE_FRAC = 0.6
# Header-grid seed for the pre-pass: a header row block whose cells all
# sit on one baseline, over an atomized body that populates every one
# of its columns (p4047r0 prediction tables, "# | Prediction | Source |
# Date | Outcome"). Two cells on one baseline is a list item or a TOC
# entry as often as a table row; three is a grid.
_HEADER_GRID_MIN_CELLS = 3
# A table cell that is only a run of ASCII/en/em dashes, optionally with
# the markdown alignment colons: a rendered separator, not data (see
# _drop_separator_rows).
_SEPARATOR_CELL_RE = re.compile(r"^:?[-\u2013\u2014]+:?$")

# Guard: bare section number on line 0 of a 2-line block.
# Prevents misclassifying heading blocks (large bold number + right-aligned
# title) as tables. Kretz-style LaTeX papers (P3948, P3844, P4012) produce
# blocks where the section number sits at x=73 and the ALL-CAPS title at
# x=440+, a gap of ~370pt that far exceeds _COLUMN_GAP_THRESHOLD.
_BARE_HEADING_NUM_RE = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*|[A-Z]+|[IVXLCDM]+)\.?\s*$"
)
_SECTION_HEADING_RE = re.compile(
    r"^(?:[A-Z]\.\d+|\d+(?:\.\d+)*|Appendix\s)"
)
_HEADING_NUM_MAX_WORDS = 8

# WG21 stable name in brackets: [basic.memobj], [intro.object], etc.
# These appear as bold right-aligned text on WG21 section heading lines.
_STABLE_NAME_RE = re.compile(
    r"^\[[\w.]+\]$"
)

# Guard: C++ declaration lines with prefix keywords (constexpr, inline, template, etc.).
# When MuPDF splits an indented declaration (e.g. green 'constexpr' at x=55 and
# black 'float frexp(...);' at x=110), the large x-gap must not trigger table detection.
_CODE_DECL_PREFIX_RE = re.compile(
    r"^\s*(?:constexpr|consteval|constinit|inline|template\b|static|virtual|explicit|friend|"
    r"extern|typedef|using|export|namespace|#define|#include)\b"
)


# ---------------------------------------------------------------------------
# Table classification (integrated from table_analyzer.py)
# Thresholds corpus-validated against 768 tables from 124 WG21 PDFs.
# ---------------------------------------------------------------------------

class TableKind(Enum):
    """What kind of table this section represents."""
    CLEAN_MATRIX = "clean_matrix"
    INLINE_GRID = "inline_grid"
    PROSE_TABLE = "prose_table"
    CODE_COMPARISON = "code_comparison"
    SPEC_TABLE = "spec_table"
    KEY_VALUE = "key_value"
    BIBLIOGRAPHY = "bibliography"
    NB_BALLOT = "nb_ballot"
    FALSE_POSITIVE = "false_positive"


class TableStrategy(Enum):
    """How to render this table in markdown."""
    PIPE_TABLE = "pipe_table"
    CODE_BLOCKS = "code_blocks"
    HTML_TABLE = "html_table"
    SKIP = "skip"


_STRATEGY_MAP = {
    TableKind.CLEAN_MATRIX: TableStrategy.PIPE_TABLE,
    TableKind.PROSE_TABLE: TableStrategy.PIPE_TABLE,
    TableKind.CODE_COMPARISON: TableStrategy.HTML_TABLE,
    TableKind.SPEC_TABLE: TableStrategy.HTML_TABLE,
    TableKind.KEY_VALUE: TableStrategy.PIPE_TABLE,
    TableKind.BIBLIOGRAPHY: TableStrategy.PIPE_TABLE,
    TableKind.NB_BALLOT: TableStrategy.HTML_TABLE,
    TableKind.FALSE_POSITIVE: TableStrategy.SKIP,
}

_EMPTY_RATIO_THRESHOLD = 0.50
_MONO_RATIO_THRESHOLD = 0.70
_PROSE_WORD_THRESHOLD = 15
_KV_COL0_MAX_WORDS = 8

# Bibliography: col-0 cells are bracketed reference labels.
_BIBLIOGRAPHY_LABEL_RE = re.compile(r"^\[[\w\d.+\-]+\]$")
_BIBLIOGRAPHY_LABEL_RATIO = 0.60

# NB-Ballot: col-0 cells are national body comment IDs like [ES-047]
# or bare country codes like [SE], [FI]. Also matches the header "NB number".
_NB_BALLOT_ID_RE = re.compile(
    r"^\[(?:[A-Z]{2}(?:[-\s]\d{2,3})?)\]$|^NB\s+number$"
)


class _MatchResult(NamedTuple):
    """Result of a Pass 1 inner-loop decision branch."""
    advance_to: int
    new_ref_cols: Optional[list] = None
    absorbed_ids: frozenset = frozenset()
    multi_orphan: bool = False


def _render_table_text(rows: list[list[list]]) -> str:
    """Render table rows (list of cells, each cell a list of Spans) to pipe-delimited text."""
    return "\n".join(
        " | ".join(
            "".join(s.text for s in cell).strip()
            for cell in row
        )
        for row in rows
    )


def _header_dedup_start(
    prev_columns: list[list[list]],
    cur_rows: list[list[list]],
) -> int:
    """Return row index to start appending from cur_rows.

    If the first row of cur_rows textually matches the header (first
    row) of prev_columns, return 1 to skip the duplicate header.
    Otherwise return 0 (append all rows).
    """
    if cur_rows and prev_columns:
        hdr_prev = [
            "".join(s.text for s in cell).strip()
            for cell in prev_columns[0]
        ]
        hdr_cur = [
            "".join(s.text for s in cell).strip()
            for cell in cur_rows[0]
        ]
        if hdr_prev == hdr_cur:
            return 1
    return 0


def _find_column_xs(blocks: list[Block]) -> frozenset[float]:
    """Return x-start positions that are genuine table columns.

    Uses the shared-y-band approach: an x position qualifies only when it
    co-occurs in the same y-band with at least one other distinct x position,
    across at least _MIN_SHARED_YBANDS such y-bands. Body text at the left
    margin is alone in every y-band and therefore never qualifies.

    Y-bands are scoped per page so that two lines on different pages at the
    same absolute y coordinate are not treated as sharing a row.
    """
    yband_to_xs: dict[tuple[int, int], set[int]] = defaultdict(set)
    for block in blocks:
        for line in block.lines:
            if not line.spans or not line.text.strip():
                continue
            x_key = round(line.bbox[0] / _COLUMN_X_BUCKET)
            y_key = round(((line.bbox[1] + line.bbox[3]) / 2.0) / _Y_BAND_HEIGHT)
            yband_to_xs[(block.page_num, y_key)].add(x_key)

    shared_counts: Counter[int] = Counter()
    for xs in yband_to_xs.values():
        if len(xs) >= 2:
            for x_key in xs:
                shared_counts[x_key] += 1

    return frozenset(
        x_key * _COLUMN_X_BUCKET
        for x_key, count in shared_counts.items()
        if count >= _MIN_SHARED_YBANDS
    )


def _block_is_monospace(block: Block) -> bool:
    """True if most of the block's text spans are monospace.

    Used to prevent the single-header multi-orphan scan from absorbing
    code comparison blocks that belong to side-by-side tables.
    """
    text_spans = [s for ln in block.lines for s in ln.spans
                  if s.text.strip()]
    if not text_spans:
        return False
    return sum(1 for s in text_spans if s.monospace) >= len(text_spans) / 2


def _is_column_aligned_orphan(block: Block, column_xs: frozenset[float]) -> bool:
    """True if block is a single-line or multi-line block whose x0 aligns with a known column."""
    if not block.lines or not block.lines[0].spans:
        return False
    if block.lines[0].is_bold and _SECTION_HEADING_RE.match(block.lines[0].text.strip()):
        return False
    t = block.lines[0].text.strip()
    if t.endswith(":") or t.startswith("[Note:"):
        return False
    x0 = block.lines[0].bbox[0]
    min_col_x = min(column_xs) if column_xs else 0.0
    if len(block.lines) == 1:
        if x0 <= min_col_x + 40.0 and (block.lines[0].bbox[2] - x0) > 200.0:
            return False
        return any(abs(x0 - cx) <= _COLUMN_X_BUCKET for cx in column_xs)
    # Multi-line block: must be a narrow single-column cell with strictly aligned lines
    text_spans = [s for ln in block.lines for s in ln.spans if s.text.strip()]
    if len(block.lines) > 2 and all(s.monospace for s in text_spans):
        return False
    width = block.bbox[2] - block.bbox[0]
    if x0 <= min_col_x + 40.0:
        if width > 120.0 or len(block.lines) > 2:
            return False
    elif width > 150.0:
        return False
    for ln in block.lines[1:]:
        if abs(ln.bbox[0] - x0) > 2.0:
            return False
    return any(abs(x0 - cx) <= _COLUMN_X_BUCKET for cx in column_xs)


def _is_partial_row(block: Block, ref_cols: list[float],
                    prev_bottom: float, same_page: bool) -> bool:
    """True if block is a columnar row with fewer columns than ref_cols.

    Matches when ALL of the block's column x-positions align with a subset
    of the reference columns, the block is on the same page, and the
    vertical gap is within _PARTIAL_ROW_MAX_Y_GAP.
    """
    cols = _block_column_positions(block)
    if cols is None or len(cols) >= len(ref_cols):
        return False
    if not same_page:
        return False
    y_gap = block.bbox[1] - prev_bottom
    if y_gap > _PARTIAL_ROW_MAX_Y_GAP or y_gap < 0:
        return False
    for x in cols:
        if not any(abs(x - rx) < _COLUMN_X_TOLERANCE for rx in ref_cols):
            return False
    return True


def _is_trailing_continuation(block: Block, ref_cols: list[float],
                               prev_bottom: float, same_page: bool) -> bool:
    """True if block is a single-line block continuing a non-first column.

    Trailing continuations appear after the last full row when a cell's
    text wraps across multiple PDF lines delivered as separate blocks.
    The non-first-column guard distinguishes them from new paragraphs
    which start at the left margin (column 0).
    """
    if len(block.lines) != 1 or not block.lines[0].spans:
        return False
    if not same_page:
        return False
    # A vertically centred col-0 label reaches below the first line of a
    # taller col-1 cell, so the cell's tail can start slightly above the
    # row block's bottom (p4016r0 N.14 "Practicality", -2.8pt).
    y_gap = block.bbox[1] - prev_bottom
    if y_gap > _PARTIAL_ROW_MAX_Y_GAP or y_gap < -_TABLE_Y_OVERLAP_MARGIN:
        return False
    x0 = block.lines[0].bbox[0]
    return any(abs(x0 - ref_cols[ci]) <= _COLUMN_X_TOLERANCE
               for ci in range(1, len(ref_cols)))


def _block_column_positions(block: Block) -> list[float] | None:
    """Return the x-start positions of columns in a block, or None.

    A block is columnar if it has 2+ lines where every line after
    the first starts significantly to the right of the first line's
    x-start position.
    """
    if len(block.lines) < 2:
        return None

    # Guard: 2-line blocks where line 0 is a bold bare section number in a
    # heading-sized font are section headings, not table rows. The title text
    # on line 1 is right-aligned or centered, creating a large x-gap that
    # would otherwise trigger columnar detection.
    if len(block.lines) == 2:
        line0 = block.lines[0]
        line1 = block.lines[1]
        if (line0.is_bold
                and _BARE_HEADING_NUM_RE.match(line0.text.strip())
                and line0.font_size > line1.font_size
                and len(line1.text.split()) <= _HEADING_NUM_MAX_WORDS):
            return None

    # Guard: WG21 section headings where any line is a bold stable name
    # in brackets (e.g. "[basic.memobj]") far to the right.
    if any(ln.is_bold and _STABLE_NAME_RE.match(ln.text.strip()) for ln in block.lines):
        return None

    # Guard: C++ code declarations where line 0 is a keyword (e.g. 'constexpr', 'inline')
    # and subsequent lines are function/variable signatures or comments.
    if _CODE_DECL_PREFIX_RE.match(block.lines[0].text):
        last_text = block.lines[-1].text.strip()
        if (last_text.endswith((";", "{", "}", ")"))
                or "//" in last_text or "/*" in last_text):
            return None

    x_starts = []
    for line in block.lines:
        if not line.spans:
            return None
        x_starts.append(line.bbox[0])

    # Cluster x_starts by tolerance: lines proceed from left to right with possible wrapped lines
    clusters: list[list[float]] = []
    for x in x_starts:
        if not clusters:
            clusters.append([x])
        elif abs(x - clusters[-1][-1]) <= _COLUMN_X_TOLERANCE:
            clusters[-1].append(x)
        elif x > clusters[-1][-1]:
            clusters.append([x])
        else:
            return None

    if any(len(c) > 3 for c in clusters):
        return None

    unique_xs = [c[0] for c in clusters]
    if len(unique_xs) < 2:
        return None

    for i in range(1, len(unique_xs)):
        if unique_xs[i] - unique_xs[0] < _COLUMN_GAP_THRESHOLD:
            return None

    return unique_xs


def _header_grid_positions(block: Block) -> list[float] | None:
    """Column x-starts of a single-band header row block, or None.

    _block_column_positions rejects a header whose first column is
    narrower than _COLUMN_GAP_THRESHOLD (p4047r0 "#", 30pt before
    "Prediction"); that rule tells a columnar block from wrapped prose,
    where a wrapped line starts a little right of the first. A block
    whose lines all end on one baseline cannot be wrapped prose: MuPDF
    splits a line inside a block only at a horizontal gap, so every
    line is a cell of the same row. Three or more cells, each with
    text, x-starts increasing by more than _COLUMN_X_TOLERANCE.
    """
    if len(block.lines) < _HEADER_GRID_MIN_CELLS:
        return None
    if any(not ln.spans or not ln.text.strip() for ln in block.lines):
        return None
    bottoms = [ln.bbox[3] for ln in block.lines]
    if max(bottoms) - min(bottoms) > _TABLE_Y_OVERLAP_MARGIN:
        return None
    xs = [ln.bbox[0] for ln in block.lines]
    if any(b - a <= _COLUMN_X_TOLERANCE for a, b in zip(xs, xs[1:])):
        return None
    return xs


def _columns_match(
    cols_a: list[float],
    cols_b: list[float],
    *,
    block_a: Block | None = None,
    block_b: Block | None = None,
) -> bool:
    """Check if two column position lists represent the same table structure.

    When both *block_a* and *block_b* are provided, a secondary x-end
    check fires for right-aligned columns whose x-start varies with
    cell text length but whose x-end is fixed by the layout engine.
    """
    if len(cols_a) != len(cols_b):
        return False
    if block_a is not None and block_b is not None:
        ends_a = [ln.bbox[2] for ln in block_a.lines]
        ends_b = [ln.bbox[2] for ln in block_b.lines]
        for sa, sb, ea, eb in zip(cols_a, cols_b, ends_a, ends_b):
            start_ok = abs(sa - sb) < _COLUMN_X_TOLERANCE
            end_ok = abs(ea - eb) < _COLUMN_X_END_TOLERANCE
            if not (start_ok or end_ok):
                return False
        return True
    return all(abs(a - b) < _COLUMN_X_TOLERANCE for a, b in zip(cols_a, cols_b))


def _is_subset_columns(cols: list[float],
                       ref_cols: list[float]) -> bool:
    """True when *cols* is a strict subset of *ref_cols*.

    Every x-position in *cols* must match a distinct column in
    *ref_cols* within tolerance, and *cols* must have fewer columns.
    Used by the multi-orphan lookahead to confirm a table continues
    via a block that covers only some columns (e.g. col1+col2 of a
    3-column table).
    """
    if len(cols) >= len(ref_cols):
        return False
    return all(
        any(abs(px - rx) < _COLUMN_X_TOLERANCE for rx in ref_cols)
        for px in cols)


# Max y-gap between consecutive columnar blocks to consider them part of the
# same table when they share a column count but differ in x-positions (e.g.
# centered header row + left-aligned data rows).
_RELAXED_MATCH_MAX_Y_GAP = 40.0


def _columns_count_match(cols_a: list[float], cols_b: list[float],
                         block_a_bottom: float, block_b_top: float,
                         same_page: bool) -> bool:
    """Relaxed match: same column count, same page, close y-proximity.

    Handles PDF tables where header cells are centered differently from
    data cells.  The column count is identical but x-positions differ by
    more than _COLUMN_X_TOLERANCE.
    """
    if not same_page:
        return False
    if len(cols_a) != len(cols_b):
        return False
    if len(cols_a) < 2:
        return False
    # Reject blocks that vertically overlap: block_b starts above block_a's
    # bottom edge (within tolerance).  Same-row table halves from shattered
    # Google-Docs cells should not be glued as sequential rows.
    if block_b_top < block_a_bottom - _TABLE_Y_OVERLAP_MARGIN:
        return False
    if block_b_top - block_a_bottom > _RELAXED_MATCH_MAX_Y_GAP:
        return False
    return True


def _cluster_x_positions(x_vals: list[float],
                         gap: float = _COLUMN_GAP_THRESHOLD) -> list[float]:
    """Cluster nearby x values, return sorted representative per cluster."""
    if not x_vals:
        return []
    xs = sorted(set(round(x, 1) for x in x_vals))
    clusters: list[list[float]] = [[xs[0]]]
    for x in xs[1:]:
        if x - clusters[-1][-1] < gap:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    return [min(c) for c in clusters]


def _nearest_column(x: float, col_xs: list[float]) -> int:
    """Return index of nearest column in col_xs for position x."""
    return min(range(len(col_xs)), key=lambda ci: abs(x - col_xs[ci]))


def _column_by_start(x: float, col_xs: list[float]) -> int:
    """Column whose start ``x`` has reached, not the nearest center.

    A spaced word inside a cell can sit closer to the next column than
    to its own (P0957R8 swap table: ``(rhs`` at x=296 between columns
    at 185 and 365). Nearest-column then moves that word into the next
    cell. A line belongs to column i once its left edge is within
    ``_COLUMN_X_TOLERANCE`` of i's start, and stays there until the
    next start.
    """
    chosen = 0
    for i, cx in enumerate(col_xs):
        if x + _COLUMN_X_TOLERANCE >= cx:
            chosen = i
        else:
            break
    return chosen


def _column_for_body_line(
    x: float, col_xs: list[float], prev_x1: float | None,
) -> int:
    """Column for one body line of a side-by-side row.

    Spaced words of one cell stay with ``_column_by_start``. A line
    that begins more than ``_COLUMN_GAP_THRESHOLD`` past the previous
    line's right edge is the next column: P4012R0 puts
    ``// exposition only`` 81pt after the code line and 27pt before
    the column at x=421, which start-assignment would leave behind.
    """
    if prev_x1 is not None and x - prev_x1 > _COLUMN_GAP_THRESHOLD:
        return _nearest_column(x, col_xs)
    return _column_by_start(x, col_xs)


def _resplit_rows_on_ruled_grid(valid_rows, grids, num_cols):
    """Split an SBS row that crosses several ruled rows.

    P0957R8 5.4.2.1 packs three Name/Value rows into one cell because
    the next row's text starts a few points before the previous row's
    block ends, so the y-gap test never fires. find_tables() already
    has those rules. Only a grid with the same column count and at
    most four extra rows is used, so a full-page phantom does not
    re-cut a real table.
    """
    grid = None
    for tbl in grids:
        if tbl.get("rot") is not None or tbl.get("col_count") != num_cols:
            continue
        extra = tbl.get("row_count", 0) - len(valid_rows)
        if 0 < extra <= 4 and tbl.get("cells"):
            grid = tbl
            break
    if grid is None:
        return valid_rows
    cells = grid["cells"]
    n_rows = grid["row_count"]

    def grid_row(y):
        for i, cell in enumerate(cells):
            if cell and cell[1] <= y <= cell[3]:
                return i % n_rows
        return None

    out = []
    for row in valid_rows:
        groups = {}
        order = []
        for item in row:
            blk = item[1]
            y = (blk.bbox[1] + blk.bbox[3]) / 2.0
            ri = grid_row(y)
            if ri not in groups:
                groups[ri] = []
                order.append(ri)
            groups[ri].append(item)
        if len(groups) <= 1:
            out.append(row)
        else:
            out.extend(groups[ri] for ri in order)
    return out


_SBS_MUPDF_DEFER_MIN_ROWS = 5
_MUPDF_REGION_MARGIN = 4.0  # pt of slack when testing block containment

# page_mupdf_tables entries synthesized by the pipeline's drawing-grid
# fallback carry this source. Their cells are rule intersections of a
# validated bordered grid, so the guards written against find_tables()
# guesses (phantom height, min size, label transposition) stand down.
_DRAWING_GRID_SOURCE = "drawing_grid"


def _is_drawing_grid(tbl_info: dict) -> bool:
    return tbl_info.get("source") == _DRAWING_GRID_SOURCE


def _rows_from_drawn_grid(
    table_blocks: list[Block],
    grid: dict,
    page_num: int,
    num_cols: int,
) -> tuple[list[list[list]], list[Line]] | None:
    """Re-cut Pass 1's blocks into the cells of a drawn grid.

    Pass 1 assigns lines to rows by MuPDF block. When one cell is much
    taller than its neighbours (a seven-line Rationale beside one-line
    cells, P4016R0 F.1) MuPDF splits that cell's lines over the blocks
    of the adjacent rows, and Pass 1 writes them into the wrong rows.
    The drawn grid knows the row bands: a line's row is the band that
    holds its y-midpoint, its column the drawn column its left edge
    starts in (a line spanning merged columns stays in the leftmost,
    as Pass 1 would place it). Lines of one cell are joined by "\\n" in
    y order: a drawn cell's line break is a real break.

    Returns (rows, all_lines), or None when the grid does not describe
    these blocks and Pass 1 keeps its rows: a block from another page
    (the grid's cells are in `page_num` coordinates), a column count
    that differs from Pass 1's, a line outside every cell.
    """
    n_rows = grid.get("row_count", 0)
    n_cols = grid.get("col_count", 0)
    cells = grid.get("cells") or []
    if (n_rows < 2 or n_cols != num_cols
            or len(cells) != n_rows * n_cols):
        return None
    if any(blk.page_num != page_num for blk in table_blocks):
        return None
    # Cells are the row-major cartesian product of the rule positions
    # (pipeline._grid_from_rule_chain), so the boundaries are the first
    # row's x-edges and the first column's y-edges.
    col_xs = [cells[c][0] for c in range(n_cols)] + [cells[n_cols - 1][2]]
    row_ys = [cells[r * n_cols][1] for r in range(n_rows)] + [cells[-1][3]]
    margin = _MUPDF_REGION_MARGIN
    cell_lines: list[list[list[tuple[float, Line]]]] = [
        [[] for _ in range(n_cols)] for _ in range(n_rows)]
    all_lines: list[Line] = []
    for blk in table_blocks:
        for ln in blk.lines:
            all_lines.append(ln)
            lx = ln.bbox[0]
            my = (ln.bbox[1] + ln.bbox[3]) / 2.0
            if not (col_xs[0] - margin <= lx <= col_xs[-1] + margin
                    and row_ys[0] - margin <= my <= row_ys[-1] + margin):
                return None
            # bisect with the margin folded in: a left edge a hair left
            # of its rule (glyph side bearing) still lands right of it.
            ci = min(max(bisect_right(col_xs, lx + margin) - 1, 0), n_cols - 1)
            ri = min(max(bisect_right(row_ys, my) - 1, 0), n_rows - 1)
            cell_lines[ri][ci].append((ln.bbox[1], ln))
    rows: list[list[list]] = []
    for band in cell_lines:
        row: list[list] = []
        for entries in band:
            cell: list = []
            for _, ln in sorted(entries, key=lambda e: e[0]):
                if cell and ln.spans:
                    cell.append(Span(text="\n"))
                cell.extend(ln.spans)
            row.append(cell)
        if any(row):
            rows.append(row)
    if len(rows) < 2:
        return None
    return rows, all_lines


def _pass1_region_incomplete(
    region: tuple[float, float, float, float],
    page_num: int,
    table_blocks: list[Block],
    all_blocks: list[Block],
) -> bool:
    """True when `region` contains blocks Pass 1 did not claim.

    find_tables() sees the whole bordered table; Pass 1 assembles rows from
    block geometry and can miss one (P3290R4's enum.detection header shares a
    block with its first data row). When MuPDF's region covers a block Pass 1
    left behind, Pass 1 is working from a partial view and must stand down.
    """
    x0, y0, x1, y1 = region
    m = _MUPDF_REGION_MARGIN
    claimed = {id(b) for b in table_blocks}
    for blk in all_blocks:
        if blk.page_num != page_num or id(blk) in claimed:
            continue
        if (blk.bbox[0] >= x0 - m and blk.bbox[2] <= x1 + m
                and blk.bbox[1] >= y0 - m and blk.bbox[3] <= y1 + m):
            return True
    return False


def _seed_is_mid_table(
    blocks: list[Block],
    seed_idx: int,
    col_xs: list[float],
    used: set[int],
) -> bool:
    """True when the atomized-header seed is really a data-row fragment.

    Two signatures, either one disqualifies the seed:

    - A block sits to the left of the seed in the same y-band. A header
      row starts at column 0, so a seed with a left neighbour is the
      right-hand fragment of a data row (p4047r0: "2021 // Confirmed"
      beside "T1 // P2300 unlikely ...").
    - A column-1+ aligned block sits within _ATOMIZED_SEED_ABOVE_GAP above
      the seed: the wrapped cells of the previous row, or of a row
      continued from the previous page. Prose and headings above a genuine
      header start at the left margin and never trip this.

    Blocks already consumed by an earlier table in this scan are ignored
    so stacked tables still seed independently.
    """
    seed = blocks[seed_idx]
    sx0, sy0, _, sy1 = seed.bbox

    def _in_band(pb: Block) -> bool:
        return (pb.bbox[3] > sy0 + _TABLE_Y_OVERLAP_MARGIN
                and pb.bbox[1] < sy1 - _TABLE_Y_OVERLAP_MARGIN)

    # Left neighbour in the same band: look both ways, since y-mid
    # sorting can place a taller seed before a shorter left neighbour.
    for k in range(seed_idx + 1, len(blocks)):
        pb = blocks[k]
        if pb.page_num != seed.page_num or pb.bbox[1] >= sy1:
            break
        if (k not in used and _in_band(pb)
                and pb.bbox[0] < sx0 - _COLUMN_X_TOLERANCE):
            return True

    for k in range(seed_idx - 1, -1, -1):
        if k in used:
            continue
        pb = blocks[k]
        if pb.page_num != seed.page_num:
            break
        if _in_band(pb) and pb.bbox[0] < sx0 - _COLUMN_X_TOLERANCE:
            return True
        gap = sy0 - pb.bbox[3]
        if gap < 0:
            continue  # same band as the seed (a taller sibling header cell)
        if gap > _ATOMIZED_SEED_ABOVE_GAP:
            break
        ci = _nearest_column(pb.bbox[0], col_xs)
        if ci >= 1 and abs(pb.bbox[0] - col_xs[ci]) <= _COLUMN_X_TOLERANCE:
            return True
    return False


def _body_is_atomized(rows: list[list[tuple[int, Block]]]) -> bool:
    """True when the grouped body is shattered into one block per line.

    Row-block tables (Pass 1's family) group as one multi-line block per
    row; a shattered table groups as several mostly single-line blocks per
    row. Both conditions are required so a row-block table with a few
    fused right-hand fragments stays with Pass 1. "Most" rather than
    "all" rows, because the body scan may run on into a following
    table whose header block forms a one-block row.
    """
    if not rows:
        return False
    multi = sum(1 for row in rows if len(row) >= 2)
    if multi / len(rows) < _ATOMIZED_BODY_MIN_SINGLE_FRAC:
        return False
    body = [b for row in rows for _, b in row]
    single = sum(1 for b in body if len(b.lines) == 1)
    return single / len(body) >= _ATOMIZED_BODY_MIN_SINGLE_FRAC


def _sbs_cells_from_blocks(
    blocks: list[Block],
    indices: AbstractSet[int],
    col_xs: list[float],
) -> list[list]:
    """Assign each line of *indices* to the nearest column in *col_xs*.

    A fused block whose lines sit on more than one column is split per
    line; a stacked wrap in one column stays in that column. Used for
    atomized-header reconstruction and the citation-section header check.
    """
    cells: list[list] = [[] for _ in col_xs]
    for k in sorted(indices):
        blk_k = blocks[k]
        line_cols = [_nearest_column(ln.bbox[0], col_xs) for ln in blk_k.lines]
        multi_col = len(set(line_cols)) > 1
        blk_ci = _nearest_column(blk_k.bbox[0], col_xs)
        for ln, lc in zip(blk_k.lines, line_cols):
            ci = lc if multi_col else blk_ci
            if cells[ci]:
                cells[ci].append(Span(text="\n"))
            cells[ci].extend(ln.spans)
    return cells


def _cell_plain_text(cell: list) -> str:
    return " ".join("".join(s.text for s in cell).split())


def _header_is_citation_section(header_cells: list[list]) -> bool:
    """True for a two-column citation-comparison header.

    At least one cell begins with a WG21 paper id plus Section. A
    non-citation sibling must be nonempty, short, and header-like
    (not a quote, at most `_CITATION_HEADER_LABEL_MAX_WORDS`). Both
    cells may be citations. Citation plus long prose is rejected.
    """
    if len(header_cells) != 2:
        return False
    texts = [_cell_plain_text(cell) for cell in header_cells]
    if any(not t for t in texts):
        return False
    cites = [bool(_WG21_CITATION_SECTION_HEADER_RE.match(t)) for t in texts]
    if not any(cites):
        return False
    for text, is_cite in zip(texts, cites):
        if is_cite:
            continue
        if text[:1] in "\"'":
            return False
        if len(text.split()) > _CITATION_HEADER_LABEL_MAX_WORDS:
            return False
    return True


# A citation cell that already ends on one of these is closed. A later
# lowercase line is the next sentence, not a wrap of the quote.
_CITATION_CELL_CLOSED = frozenset(".?!\"'”’")


def _citation_open_cell_text(
    row: list[tuple[int, Block]],
    col: int,
    col_xs: list[float],
) -> str:
    """Plain text already placed in *col* of the open citation row."""
    parts: list[str] = []
    for _, blk in row:
        line_cols = [_nearest_column(ln.bbox[0], col_xs) for ln in blk.lines]
        multi_col = len(set(line_cols)) > 1
        blk_ci = _nearest_column(blk.bbox[0], col_xs)
        for ln, lc in zip(blk.lines, line_cols):
            if (lc if multi_col else blk_ci) == col:
                parts.append("".join(sp.text for sp in ln.spans))
    return " ".join(" ".join(parts).split())


def _citation_row_continuation(text: str, open_cell: str) -> bool:
    """True when *text* continues an unfinished citation quote.

    A later citation header, a quote, or a sentence-initial line ends
    the box. A lowercase tail stays only while *open_cell* does not
    already end the quote (``data-races`` after ``there are no``).
    Lowercase prose after a closed quote stays out.
    """
    if not text or not open_cell or _WG21_CITATION_SECTION_HEADER_RE.match(text):
        return False
    if open_cell[-1] in _CITATION_CELL_CLOSED:
        return False
    first = text[0]
    if first in "\"'“‘":
        return False
    return first.islower()


def _yba_line_text(line: Line) -> str:
    return " ".join(line.text.split())


def _citation_yes_but_actually_seed(
    blocks: list[Block],
    seed_idx: int,
    used: set[int],
) -> tuple[list[int], list[int], list[float]] | None:
    """Citation title over col-1, then Yes/But/Actually two-line rows.

    Each row block has two nonempty lines whose x-gap is just under
    `_COLUMN_GAP_THRESHOLD`, so `_block_column_positions` is None.
    Title must sit on the value column. At most `_YBA_MAX_WRAPS`
    same-column continuation after Actually joins that cell. An extra
    two-line row in the band, a missing/reordered label, or unstable
    x-positions reject the seed.
    """
    title = blocks[seed_idx]
    if not title.lines:
        return None
    title_text = _yba_line_text(title.lines[0])
    if not _WG21_CITATION_SECTION_HEADER_RE.match(title_text):
        return None
    page = title.page_num
    row_idxs: list[int] = []
    prev_y1 = title.bbox[3]
    k = seed_idx + 1
    for label in _YBA_LABELS:
        if k >= len(blocks) or k in used:
            return None
        blk = blocks[k]
        if blk.page_num != page:
            return None
        if blk.bbox[1] - prev_y1 > _YBA_MAX_ROW_GAP:
            return None
        if len(blk.lines) != 2:
            return None
        texts = [_yba_line_text(ln) for ln in blk.lines]
        if texts[0] != label or not texts[1]:
            return None
        row_idxs.append(k)
        prev_y1 = blk.bbox[3]
        k += 1
    col0s = [blocks[r].lines[0].bbox[0] for r in row_idxs]
    col1s = [blocks[r].lines[1].bbox[0] for r in row_idxs]
    if max(col0s) - min(col0s) > _COLUMN_X_TOLERANCE:
        return None
    if max(col1s) - min(col1s) > _COLUMN_X_TOLERANCE:
        return None
    col_xs = [sum(col0s) / 3.0, sum(col1s) / 3.0]
    if col_xs[1] - col_xs[0] <= _COLUMN_X_TOLERANCE:
        return None
    if abs(title.bbox[0] - col_xs[1]) > _COLUMN_X_TOLERANCE:
        return None
    wraps: list[int] = []
    while (k < len(blocks) and k not in used
           and len(wraps) < _YBA_MAX_WRAPS):
        blk = blocks[k]
        if blk.page_num != page:
            break
        if blk.bbox[1] - prev_y1 > _YBA_MAX_WRAP_GAP:
            break
        if len(blk.lines) != 1:
            break
        if abs(blk.lines[0].bbox[0] - col_xs[1]) > _COLUMN_X_TOLERANCE:
            break
        wraps.append(k)
        prev_y1 = blk.bbox[3]
        k += 1
    if k < len(blocks) and k not in used:
        extra = blocks[k]
        if (extra.page_num == page
                and extra.bbox[1] - prev_y1 <= _YBA_MAX_ROW_GAP
                and len(extra.lines) == 2
                and extra.lines[0].text.strip()
                and extra.lines[1].text.strip()):
            return None
    return row_idxs, wraps, col_xs


def _emit_citation_yba_table(
    blocks: list[Block],
    seed_idx: int,
    row_idxs: list[int],
    wraps: list[int],
) -> tuple[Section, set[int]]:
    """Build the 4x2 Yes/But/Actually table (empty col-0 over the title)."""
    title = blocks[seed_idx]
    header_cells: list[list] = [[], list(title.lines[0].spans)]
    all_lines = list(title.lines)
    all_rows: list[list[list]] = [header_cells]
    consumed = {seed_idx, *row_idxs, *wraps}
    last = len(row_idxs) - 1
    for ri, ridx in enumerate(row_idxs):
        blk = blocks[ridx]
        c0 = list(blk.lines[0].spans)
        c1 = list(blk.lines[1].spans)
        all_lines.extend(blk.lines)
        if ri == last:
            for widx in wraps:
                wblk = blocks[widx]
                if c1:
                    c1.append(Span(text="\n"))
                c1.extend(wblk.lines[0].spans)
                all_lines.extend(wblk.lines)
        all_rows.append([c0, c1])
    kind_val, strategy_val, all_rows = _classify_and_annotate(all_rows)
    return Section(
        kind=SectionKind.TABLE,
        text=_render_table_text(all_rows),
        confidence=Confidence.HIGH,
        lines=all_lines,
        page_num=title.page_num,
        columns=all_rows,
        table_kind=kind_val,
        table_strategy=strategy_val,
        table_source="side_by_side_prepass",
    ), consumed


def _collect_atomized_header_blocks(
    blocks: list[Block],
    seed_idx: int,
    *,
    end: int | None = None,
    used: AbstractSet[int] | None = None,
) -> set[int]:
    """Consecutive same-page blocks in the atomized header band."""
    seed = blocks[seed_idx]
    page = seed.page_num
    hdr_y0 = seed.bbox[1]
    collected = {seed_idx}
    max_y1 = seed.bbox[3]
    stop = len(blocks) if end is None else end
    for k in range(seed_idx + 1, stop):
        if used is not None and k in used:
            break
        nb = blocks[k]
        if nb.page_num != page:
            break
        if nb.bbox[1] - hdr_y0 > _ATOMIZED_HDR_MAX_HEIGHT:
            break
        if nb.bbox[1] - max_y1 > _ATOMIZED_HDR_MAX_LINE_GAP:
            break
        collected.add(k)
        max_y1 = max(max_y1, nb.bbox[3])
    return collected


def _citation_split_header_seed(
    blocks: list[Block],
    seed_idx: int,
    used: set[int],
) -> tuple[set[int], list[float]] | None:
    """Pre-pass seed when the citation header is split across blocks.

    `_block_column_positions` is None for a one-line `P... Section`
    cell. Gather the height/gap cluster, require exactly two x-columns,
    and accept only when the reconstructed cells are a citation-
    comparison header. A stacked section number in column 0 joins
    that cell.
    """
    collected = _collect_atomized_header_blocks(
        blocks, seed_idx, used=used)
    ext_xs = _cluster_x_positions(
        [ln.bbox[0] for k in sorted(collected)
         for ln in blocks[k].lines])
    if len(ext_xs) != 2:
        return None
    if _seed_is_mid_table(blocks, seed_idx, ext_xs, used):
        return None
    recovered = _sbs_cells_from_blocks(blocks, collected, ext_xs)
    if not _header_is_citation_section(recovered):
        return None
    return collected, ext_xs


def _detect_side_by_side_tables(
    blocks: list[Block],
    *,
    atomized_only: bool = False,
    page_mupdf_tables: dict[int, list[dict]] | None = None,
) -> tuple[list[Section], set[int]]:
    """Detect tables where each cell is a separate side-by-side block.

    When *atomized_only* is True, only tables whose headers required
    atomized-header recovery are emitted; regular side-by-side tables
    are skipped so that Pass 1 (horizontal rows) gets first dibs.

    When *page_mupdf_tables* is provided, candidate table regions that
    overlap a MuPDF ``find_tables()`` bbox with >= ``_SBS_MUPDF_DEFER_MIN_ROWS``
    rows are skipped so MuPDF Native (Pass 5) can handle them intact.

    The row grouping walks the body candidates top-down and relies on
    y order, which the pipeline's reading-order sort delivers on every
    page it did not split into two text columns; on a split page the
    same sort also puts the page into detect_tables' two_column_pages
    (one decision, `_column_aware_sort`), so no re-sort happens here.

    Returns (table_sections, used_block_indices).
    """
    table_sections: list[Section] = []
    used: set[int] = set()
    i = 0

    while i < len(blocks):
        if i in used:
            i += 1
            continue
        cols = _block_column_positions(blocks[i])
        split_hdr: set[int] | None = None
        # Pre-pass only: a single-baseline header row whose first column
        # is too narrow for _block_column_positions. Its grid replaces
        # the body clustering below (a 30pt column falls into its
        # neighbour's _COLUMN_GAP_THRESHOLD cluster) once the body is
        # seen to populate every header column.
        header_grid: list[float] | None = None
        if cols is None and atomized_only:
            header_grid = _header_grid_positions(blocks[i])
            cols = header_grid
        if cols is None or len(cols) < 2:
            # cols is None is ordinary prose (no column gaps), not a seed;
            # only a block that had positions but too few is worth a line.
            # Exception: atomized-only citation header split across
            # separate blocks (wrapped section number beside the other
            # column). Generic split headers stay rejected.
            if atomized_only:
                # Yes/But/Actually before the split-header seed: a Yes
                # row inside _ATOMIZED_HDR_MAX_LINE_GAP would otherwise
                # join the title cluster and the box would emit as 3
                # rows instead of 4x2.
                if (yba := _citation_yes_but_actually_seed(
                        blocks, i, used)) is not None:
                    row_idxs, wraps, _col_xs = yba
                    sec, consumed = _emit_citation_yba_table(
                        blocks, i, row_idxs, wraps)
                    table_sections.append(sec)
                    used.update(consumed)
                    _log.debug(
                        "SBS citation Yes/But/Actually: seed %d on page %d, "
                        "4x2", i, blocks[i].page_num)
                    nxt = max(consumed) + 1
                    i = i + 1 if nxt <= i else nxt
                    continue
                split = _citation_split_header_seed(blocks, i, used)
                if split is not None:
                    split_hdr, cols = split
                    _log.debug(
                        "SBS citation split header: seed %d on page %d, "
                        "%d header blocks, 2 cols",
                        i, blocks[i].page_num, len(split_hdr))
            if split_hdr is None:
                if cols is not None:
                    _log.debug("SBS reject: seed %d has %d column(s) (need 2+), page %d",
                                i, len(cols), blocks[i].page_num)
                i += 1
                continue

        header = blocks[i]
        page = header.page_num
        if split_hdr is not None:
            h_bottom = max(blocks[k].bbox[3] for k in split_hdr)
            scan_from = max(split_hdr) + 1
        else:
            h_bottom = header.bbox[3]
            scan_from = i + 1

        # Gather body candidates: same page, below header
        body_candidates: list[tuple[int, Block]] = []
        j = scan_from
        while j < len(blocks):
            b = blocks[j]
            if b.page_num != page:
                break
            if j in (split_hdr or ()):
                j += 1
                continue
            if b.bbox[1] >= h_bottom - _TABLE_Y_OVERLAP_MARGIN:
                body_candidates.append((j, b))
            j += 1

        if not body_candidates:
            _log.debug("SBS reject: seed %d on page %d has no body candidates",
                        i, page)
            i += 1
            continue

        # Determine column structure from body block x-positions
        body_xs = [b.bbox[0] for _, b in body_candidates]
        col_xs = _cluster_x_positions(body_xs)

        if len(col_xs) < 2:
            _log.debug("SBS reject: seed %d on page %d, body has %d x-cluster(s) (need 2+)",
                        i, page, len(col_xs))
            i += 1
            continue

        if header_grid is not None:
            # The seed's own signature (three cells on one baseline) is
            # shared by a wide data row; the mid-table guard tells them
            # apart by what stands above. The body must then put at
            # least one line on every header column.
            if _seed_is_mid_table(blocks, i, header_grid, used):
                _log.debug("SBS reject: header-grid seed %d on page %d is mid-table",
                            i, page)
                i += 1
                continue
            body_line_xs = [ln.bbox[0] for _, b in body_candidates for ln in b.lines]
            unpopulated = [
                hx for hx in header_grid
                if not any(abs(lx - hx) <= _COLUMN_X_TOLERANCE for lx in body_line_xs)]
            if unpopulated:
                _log.debug("SBS reject: header-grid seed %d on page %d, no body line "
                            "on header column(s) at x=%s", i, page,
                            ["%.0f" % hx for hx in unpopulated])
                i += 1
                continue
            _log.debug("SBS header-grid seed %d on page %d: %d header cols over "
                       "%d body cluster(s)", i, page, len(header_grid), len(col_xs))
            col_xs = list(header_grid)
        # Header grid: a regular header row block whose lines sit on more
        # columns than the body's block x0s cluster into. A narrow column
        # (p4098r1 "Year", 39pt before "Evidence") is never a block x0
        # when the exporter fuses it into its left neighbour's block, and
        # two columns closer than _COLUMN_GAP_THRESHOLD fall into one
        # cluster. _block_column_positions clusters the header's lines
        # at _COLUMN_X_TOLERANCE, so the header knows the grid. Adopt it
        # when the body agrees: every body cluster is a header column and
        # every header column has at least one body line on it. Mirror of
        # the atomized-header recovery below, which repairs the opposite
        # imbalance (body wider than the header block).
        if len(cols) > len(col_xs):
            body_line_xs = [ln.bbox[0] for _, b in body_candidates for ln in b.lines]
            clusters_on_header = all(
                any(abs(cx - hx) <= _COLUMN_X_TOLERANCE for hx in cols)
                for cx in col_xs)
            header_cols_populated = all(
                any(abs(lx - hx) <= _COLUMN_X_TOLERANCE for lx in body_line_xs)
                for hx in cols)
            if clusters_on_header and header_cols_populated:
                _log.debug("SBS header grid: seed %d on page %d, %d header "
                           "cols over %d body cluster(s)",
                           i, page, len(cols), len(col_xs))
                col_xs = list(cols)

        # Cross-page extension: when the table reaches very close to
        # the page bottom, extend body_candidates to include column-
        # aligned blocks from the top of the next page.  Guards:
        #  - Table bottom must be within ~90pt of the page edge (700+).
        #  - Continuation blocks must start near the page top (y < 160).
        #  - At least 2 distinct columns must be represented.
        #  - Stop at numbered headings or misaligned blocks.
        _SBS_PAGE_BOTTOM_THRESH = 660.0
        _SBS_CROSS_PAGE_COL_TOLERANCE = 30.0
        _SBS_CROSS_PAGE_Y_MAX = 160.0
        last_body_y1 = max(b.bbox[3] for _, b in body_candidates)
        if last_body_y1 > _SBS_PAGE_BOTTOM_THRESH and len(col_xs) >= 2:
            next_page = page + 1
            cross_candidates: list[tuple[int, Block]] = []
            cross_cols_seen: set[int] = set()
            for k in range(j, len(blocks)):
                nb = blocks[k]
                if nb.page_num > next_page:
                    break
                if nb.page_num != next_page:
                    continue
                if nb.bbox[1] > _SBS_CROSS_PAGE_Y_MAX:
                    break
                nb_text = "".join(
                    s.text for ln in nb.lines for s in ln.spans).strip()
                if not nb_text:
                    continue
                if (_SPEC_HEADING_NUM_RE.match(nb_text)
                        or _SPEC_TABLE_LABEL_RE.match(nb_text)):
                    break
                nearest = _nearest_column(nb.bbox[0], col_xs)
                dist = abs(nb.bbox[0] - col_xs[nearest])
                if dist > _SBS_CROSS_PAGE_COL_TOLERANCE:
                    if cross_candidates:
                        break
                    continue
                cross_candidates.append((k, nb))
                cross_cols_seen.add(nearest)
            if len(cross_cols_seen) >= 2:
                body_candidates.extend(cross_candidates)
                _log.debug(
                    "Side-by-side cross-page: extended to page %d "
                    "(%d total body candidates, %d cols)",
                    next_page, len(body_candidates),
                    len(cross_cols_seen))

        # Guard: body suggests more columns than the header declares.
        # A non-table block (caption, label) sitting at a third x-position
        # inflates col_xs. Reject so Pass 4 (MuPDF native) handles it.
        #
        # Exception: atomized headers where each column heading is a
        # separate Block. Collect all blocks in the header region and
        # cluster their x-positions; if the cluster matches col_xs the
        # table is accepted with a multi-block header.
        #
        # Exception: a recovered two-column header whose cells both
        # begin with a WG21 paper id plus "Section". Later prose may
        # inflate body clusters; adopt the two header columns when
        # body lines populate both. Do not use the general header-grid
        # rule (that rule requires every body cluster to sit on a
        # header column, which the inflating prose fails).
        atomized_hdr: set[int] | None = None
        citation_header = False
        if split_hdr is not None:
            atomized_hdr = split_hdr
            citation_header = True
            if len(col_xs) > len(cols):
                body_line_xs = [
                    ln.bbox[0]
                    for idx, b in body_candidates
                    if idx not in split_hdr
                    for ln in b.lines
                ]
                if all(
                    any(abs(lx - hx) <= _COLUMN_X_TOLERANCE
                        for lx in body_line_xs)
                    for hx in cols
                ):
                    _log.debug("SBS citation header grid: seed %d on page %d, "
                               "%d header cols over %d body cluster(s)",
                               i, page, len(cols), len(col_xs))
                    col_xs = list(cols)
                else:
                    _log.debug("SBS reject: seed %d on page %d, split citation "
                               "header body does not populate both columns",
                               i, page)
                    i += 1
                    continue
        elif len(col_xs) > len(cols):
            if _seed_is_mid_table(blocks, i, col_xs, used):
                _log.debug("SBS reject: seed %d on page %d is mid-table (already consumed)",
                            i, page)
                i += 1
                continue
            hdr_block_set = _collect_atomized_header_blocks(
                blocks, i, end=j)
            # Cluster line x0s, not block x0s: a fused two-line header
            # block ("P2300R10[8] (2026)" / "Coroutine executor") holds
            # two column headings but only one block x0.
            ext_xs = _cluster_x_positions(
                [ln.bbox[0] for k in sorted(hdr_block_set)
                 for ln in blocks[k].lines])
            if len(ext_xs) >= len(col_xs):
                atomized_hdr = hdr_block_set
                _log.debug("Atomized header recovery: %d blocks, "
                           "%d cols on page %d, seed %r",
                           len(hdr_block_set), len(ext_xs), page,
                           header.text[:40])
            else:
                recovered = _sbs_cells_from_blocks(
                    blocks, hdr_block_set, ext_xs)
                body_line_xs = [
                    ln.bbox[0]
                    for idx, b in body_candidates
                    if idx not in hdr_block_set
                    for ln in b.lines
                ]
                if (len(ext_xs) == 2
                        and _header_is_citation_section(recovered)
                        and all(
                            any(abs(lx - hx) <= _COLUMN_X_TOLERANCE
                                for lx in body_line_xs)
                            for hx in ext_xs)):
                    _log.debug("SBS citation header grid: seed %d on page %d, "
                               "%d header cols over %d body cluster(s)",
                               i, page, len(ext_xs), len(col_xs))
                    col_xs = list(ext_xs)
                    atomized_hdr = hdr_block_set
                    citation_header = True
                else:
                    _log.debug("SBS reject: seed %d on page %d, atomized header recovery "
                                "failed (ext_xs %d < col_xs %d)",
                                i, page, len(ext_xs), len(col_xs))
                    i += 1
                    continue
        elif len(cols) == 2:
            citation_header = _header_is_citation_section(
                _sbs_cells_from_blocks(blocks, {i}, cols))
        # A regular header row block is not skipped here in the pre-pass:
        # the body may still be shattered (p4094r0 §Assertion table). The
        # decision is taken after row grouping, see _body_is_atomized.

        # When we recovered an atomized header, exclude header blocks
        # from body_candidates and reset h_bottom.
        if atomized_hdr is not None:
            effective_h_bottom = max(
                blocks[k].bbox[3] for k in atomized_hdr)
            body_candidates = [
                (idx, b) for idx, b in body_candidates
                if idx not in atomized_hdr
                and b.bbox[1] >= effective_h_bottom - _TABLE_Y_OVERLAP_MARGIN
            ]
            if not body_candidates:
                _log.debug("SBS reject: seed %d on page %d, no body candidates "
                            "after atomized header exclusion", i, page)
                i += 1
                continue
            h_bottom = effective_h_bottom

        # Fix ordering: _column_aware_sort may place non-col-0 blocks
        # before the col-0 block that starts the same row (marginally
        # lower y, or an exact y tie kept in extraction order).  Walk
        # each col-0 block back over every consecutive preceding
        # non-col-0 block within the band so the row starts at col 0.
        # p4096r0 page 11: two cells at y0 478.58 precede "Generic
        # composition" at y0 478.58.
        _SBS_COL0_SWAP_BAND = 10.0
        body_sorted = list(body_candidates)
        for si in range(1, len(body_sorted)):
            _, b_c0 = body_sorted[si]
            if _nearest_column(b_c0.bbox[0], col_xs) != 0:
                continue
            k = si
            while k > 0:
                _, b_prev = body_sorted[k - 1]
                if (_nearest_column(b_prev.bbox[0], col_xs) != 0
                        and b_prev.page_num == b_c0.page_num
                        and abs(b_c0.bbox[1] - b_prev.bbox[1])
                                < _SBS_COL0_SWAP_BAND):
                    k -= 1
                else:
                    break
            if k < si:
                body_sorted.insert(k, body_sorted.pop(si))

        # Group candidates into rows.
        # A new row starts when a col-0 block appears and the
        # whitespace gap (y0 of new block minus y1 of last col-0
        # block) exceeds _SBS_ROW_Y_BAND.  Atomized single-line
        # blocks within the band belong to the same logical row.
        # A page boundary always forces a new row.
        rows: list[list[tuple[int, Block]]] = []
        current_row: list[tuple[int, Block]] = []
        has_col0 = False
        last_col0_y1 = h_bottom
        last_col0_page = -1
        last_bottom = h_bottom

        for idx, blk in body_sorted:
            col = _nearest_column(blk.bbox[0], col_xs)

            # Stop at a numbered section heading (e.g. "5.2 The Symmetry
            # Test") sitting in col-0: the heading is prose, not a cell.
            if col == 0:
                blk_text = "".join(
                    s.text for ln in blk.lines for s in ln.spans).strip()
                if (_SPEC_HEADING_NUM_RE.match(blk_text)
                        and len(blk_text.split()) <= _HEADING_NUM_MAX_WORDS):
                    if current_row:
                        rows.append(current_row)
                    break

            # Stop when a line spills clearly into the next column:
            # a line starting in column c whose x1 extends past the
            # next column's x-position (plus tolerance) is prose that
            # spans multiple table columns, not a valid cell.  Wide
            # table cells that end just before the column boundary pass.
            spills = False
            for ln in blk.lines:
                lc = _nearest_column(ln.bbox[0], col_xs)
                if lc + 1 < len(col_xs):
                    if ln.bbox[2] > col_xs[lc + 1] + _COLUMN_X_TOLERANCE:
                        spills = True
                        break
            if spills:
                if current_row:
                    rows.append(current_row)
                break

            gap = blk.bbox[1] - last_bottom
            if gap > _SBS_MAX_SCAN_GAP:
                col_dist = abs(blk.bbox[0] - col_xs[col])
                if col_dist > _SBS_COL_ALIGN_TOL or gap > _SBS_MAX_SCAN_GAP_ALIGNED:
                    if current_row:
                        rows.append(current_row)
                    break
            # A citation box is one atomized body row. Past the row
            # band, keep only a lowercase tail of an unfinished quote.
            # A sentence-initial line, a closed quote, or the next
            # citation header ends the box and stays a later seed.
            if (citation_header and has_col0
                    and blk.bbox[1] - last_col0_y1 > _SBS_ROW_Y_BAND):
                tail = "".join(
                    s.text for ln in blk.lines for s in ln.spans).strip()
                open_cell = _citation_open_cell_text(current_row, col, col_xs)
                if col == 0 or not _citation_row_continuation(tail, open_cell):
                    if current_row:
                        rows.append(current_row)
                    break
            if col == 0:
                new_page = blk.page_num != last_col0_page and last_col0_page >= 0
                gap_exceeds = blk.bbox[1] - last_col0_y1 > _SBS_ROW_Y_BAND
                if has_col0 and (new_page or gap_exceeds):
                    rows.append(current_row)
                    current_row = [(idx, blk)]
                    has_col0 = True
                else:
                    current_row.append((idx, blk))
                    has_col0 = True
                last_col0_y1 = blk.bbox[3]
                last_col0_page = blk.page_num
            else:
                current_row.append((idx, blk))
            last_bottom = max(last_bottom, blk.bbox[3])

        if current_row and current_row not in rows:
            rows.append(current_row)

        # Validate: each row must span 2+ columns.  Check line-level
        # x-positions (not just block x0) because single-block rows can
        # contain multiple internal columns (Phase 15 per-line logic).
        valid_rows: list[list[tuple[int, Block]]] = []
        valid_row_col_counts: list[int] = []
        consec_single = 0
        scanned_rows: list[tuple[list[tuple[int, Block]], bool]] = []
        for row in rows:
            row_cols: set[int] = set()
            for _, b in row:
                for ln in b.lines:
                    row_cols.add(_nearest_column(ln.bbox[0], col_xs))
            if len(row_cols) >= 2:
                valid_rows.append(row)
                valid_row_col_counts.append(len(row_cols))
                scanned_rows.append((row, True))
                consec_single = 0
            else:
                if atomized_hdr is not None:
                    scanned_rows.append((row, False))
                    consec_single += 1
                    if consec_single >= _ATOMIZED_HDR_MAX_CONSEC_SINGLE:
                        break
                else:
                    break

        # Build consumed_rows: include all rows up to and including the
        # last valid row.  Skipped single-column rows BETWEEN valid rows
        # are internal sub-headers and must be consumed.  Skipped rows
        # AFTER the last valid row are post-table prose and must NOT be
        # consumed.
        last_valid_idx = -1
        for si in range(len(scanned_rows) - 1, -1, -1):
            if scanned_rows[si][1]:
                last_valid_idx = si
                break
        consumed_rows: list[list[tuple[int, Block]]] = [
            row for ri, (row, _) in enumerate(scanned_rows)
            if ri <= last_valid_idx
        ]

        min_rows = _MIN_TABLE_ROWS
        if atomized_only:
            # Regular header over a body of row blocks: Pass 1 territory.
            if atomized_hdr is None and not _body_is_atomized(valid_rows):
                _log.debug("SBS reject: prepass seed %d on page %d, not atomized "
                            "(regular header, body not atomized)", i, page)
                i += 1
                continue
            # The row minimum keeps the pre-pass off Pass 1's row-block
            # tables. A header-grid seed is not one Pass 1 could take:
            # its first column is narrower than Pass 1's gap and its
            # body is shattered, so _MIN_TABLE_ROWS stands (p4047r0
            # Implementation Maturity has two rows).
            if header_grid is None:
                dense = (
                    len(col_xs) >= _ATOMIZED_PREPASS_DENSE_MIN_COLS
                    and bool(valid_row_col_counts)
                    and all(n >= len(col_xs) - 1 for n in valid_row_col_counts)
                )
                min_rows = max(
                    min_rows,
                    _ATOMIZED_PREPASS_MIN_ROWS_DENSE if dense
                    else _ATOMIZED_PREPASS_MIN_ROWS)
            if (citation_header
                    and len(col_xs) == 2
                    and len(valid_rows) == 1
                    and _body_is_atomized(valid_rows)):
                min_rows = _ATOMIZED_PREPASS_MIN_ROWS_CITATION
        if len(valid_rows) < min_rows:
            _log.debug("SBS reject: seed %d on page %d, too few valid rows "
                        "(%d < %d)", i, page, len(valid_rows), min_rows)
            i += 1
            continue

        num_cols = len(col_xs)
        if page_mupdf_tables:
            valid_rows = _resplit_rows_on_ruled_grid(
                valid_rows, page_mupdf_tables.get(page, []), num_cols)

        # Build header row.
        if atomized_hdr is not None:
            header_cells = _sbs_cells_from_blocks(
                blocks, atomized_hdr, col_xs)
            all_lines = [ln for k in sorted(atomized_hdr)
                         for ln in blocks[k].lines]
        else:
            header_cells = []
            for ln in header.lines[:num_cols]:
                header_cells.append(list(ln.spans))
            while len(header_cells) < num_cols:
                header_cells.append([])
            all_lines = list(header.lines)

        all_rows_data: list[list[list]] = [header_cells]

        for row in valid_rows:
            col_spans: dict[int, list] = defaultdict(list)
            for _, blk in row:
                line_cols: list[int] = []
                prev_x1: float | None = None
                for ln in blk.lines:
                    line_cols.append(
                        _column_for_body_line(ln.bbox[0], col_xs, prev_x1))
                    prev_x1 = ln.bbox[2]
                multi_col = len(set(line_cols)) > 1
                blk_ci = _nearest_column(blk.bbox[0], col_xs)
                for ln, lc in zip(blk.lines, line_cols):
                    ci = lc if multi_col else blk_ci
                    if col_spans[ci] and ln.spans:
                        col_spans[ci].append(Span(text="\n"))
                    col_spans[ci].extend(ln.spans)
                    all_lines.append(ln)
            table_row = [col_spans.get(ci, []) for ci in range(num_cols)]
            all_rows_data.append(table_row)

        # MuPDF-overlap guard: if the body blocks overlap a substantial
        # MuPDF find_tables() region, defer to MuPDF Native (Pass 5) which
        # handles bordered tables with proper row/cell extraction.
        # Skip deferral for predominantly monospace tables (code
        # comparisons) where SBS/Pass 1 produces better results.
        if page_mupdf_tables:
            sbs_mono = 0
            sbs_total = 0
            for ln in all_lines:
                for sp in ln.spans:
                    if sp.text.strip():
                        sbs_total += 1
                        if sp.monospace:
                            sbs_mono += 1
            sbs_mono_ratio = sbs_mono / sbs_total if sbs_total else 0
            if sbs_mono_ratio < _MONO_RATIO_THRESHOLD:
                body_block_set = {idx for row in consumed_rows for idx, _ in row}
                body_y0 = min(blocks[idx].bbox[1] for idx in body_block_set
                              if idx < len(blocks))
                body_y1 = max(blocks[idx].bbox[3] for idx in body_block_set
                              if idx < len(blocks))
                body_x0 = min(blocks[idx].bbox[0] for idx in body_block_set
                              if idx < len(blocks))
                body_x1 = max(blocks[idx].bbox[2] for idx in body_block_set
                              if idx < len(blocks))
                deferred = False
                for tbl in page_mupdf_tables.get(page, []):
                    tb = tbl["bbox"]
                    rot = tbl.get("rot")
                    # Rotated entries are mostly 1-row band fragments,
                    # so the min-rows gate must not apply to them: any
                    # overlap defers to the rotation-aware Pass 5.
                    if (rot is None
                            and tbl.get("row_count", 0)
                            < _SBS_MUPDF_DEFER_MIN_ROWS):
                        continue
                    # find_tables bboxes live in reading space; map the
                    # body bbox there on rotated pages (see _rot_midpoint).
                    bx0, by0, bx1, by1 = _rot_bbox(
                        (body_x0, body_y0, body_x1, body_y1), rot)
                    overlap_x = max(0, min(bx1, tb[2]) - max(bx0, tb[0]))
                    overlap_y = max(0, min(by1, tb[3]) - max(by0, tb[1]))
                    if overlap_x > 0 and overlap_y > 0:
                        body_area = max((bx1 - bx0) * (by1 - by0), 1)
                        overlap_ratio = (overlap_x * overlap_y) / body_area
                        if rot is not None or overlap_ratio > 0.30:
                            _log.debug(
                                "SBS deferred to MuPDF Native: page %d, "
                                "overlap=%.0f%%, MuPDF rows=%d",
                                page, overlap_ratio * 100,
                                tbl.get("row_count", 0))
                            deferred = True
                            break
                if deferred:
                    i = j
                    continue

        kind_val, strategy_val, all_rows_data = _classify_and_annotate(
            all_rows_data)

        # Bibliography: not a real table, skip so prose pipeline handles it.
        if kind_val == TableKind.BIBLIOGRAPHY.value:
            _log.debug("SBS bibliography bypass: page %d", page)
            i = j
            continue

        if _is_labeled_contents_table(all_rows_data, blocks, page):
            _log.debug("SBS contents bypass: page %d", page)
            i = j
            continue

        if _is_running_header_grid(all_rows_data):
            # Consume the blocks without emitting a table. Returning
            # them to prose turns the same furniture into headings on
            # page-slice goldens (P4012R0).
            _log.debug("SBS running-header bypass: page %d", page)
            used.add(i)
            if atomized_hdr is not None:
                used.update(atomized_hdr)
            for row in consumed_rows:
                for idx, _ in row:
                    used.add(idx)
            i = j
            continue

        text = _render_table_text(all_rows_data)

        table_sections.append(Section(
            kind=SectionKind.TABLE,
            text=text,
            confidence=Confidence.HIGH,
            lines=all_lines,
            page_num=page,
            columns=all_rows_data,
            table_kind=kind_val,
            table_strategy=strategy_val,
            table_source=("side_by_side_prepass" if atomized_only
                          else "side_by_side"),
        ))
        _log.debug("Side-by-side table: %d rows x %d cols on page %d",
                    len(all_rows_data), num_cols, page)

        used.add(i)
        if atomized_hdr is not None:
            used.update(atomized_hdr)
        for row in consumed_rows:
            for idx, _ in row:
                used.add(idx)

        # Stacked pre-pass tables (p4047r0 prediction tables, P4178
        # citation boxes) seed one after the other. j is the page end:
        # jumping there skips the next header. Resume after the last
        # consumed header or body block on this page. Cross-page
        # continuation indices stay in used but do not skip remaining
        # same-page seeds. A regular side-by-side table keeps i = j.
        if atomized_only:
            consumed = {i}
            if atomized_hdr is not None:
                consumed.update(atomized_hdr)
            consumed.update(idx for row in consumed_rows for idx, _ in row)
            same_page = [
                idx for idx in consumed
                if 0 <= idx < len(blocks)
                and blocks[idx].page_num == page
            ]
            nxt = (max(same_page) if same_page else i) + 1
            i = i + 1 if nxt <= i else nxt
        else:
            i = j

    return table_sections, used


# ---------------------------------------------------------------------------
# Inline-grid tables: a single block whose lines alternate between N fixed
# x-positions, forming an implicit grid.  MuPDF delivers bordered tables
# with short cells as one block where e.g. lines 0,2,4 are at x=105 and
# lines 1,3,5 are at x=184.  Each pair at the same y-level is one row.
# ---------------------------------------------------------------------------
_INLINE_GRID_MIN_LINES = 4        # at least 2 rows x 2 cols
_INLINE_GRID_COL_GAP = 30.0       # min x-gap to count as distinct column
_INLINE_GRID_Y_BAND = 5.0         # max y-difference for same-row lines
_INLINE_GRID_VALID_ROW_RATIO = 0.75  # fraction of rows that must span 2+ cols
_INLINE_GRID_MIN_ROWS = 2
_INLINE_GRID_MIN_COL_ROWS = 2     # lines needed before an x-cluster is a column


def _detect_inline_grid_tables(
    blocks: list[Block],
    page_mupdf_tables: dict[int, list[dict]] | None = None,
) -> tuple[list[Section], set[int]]:
    """Detect tables encoded as alternating-x lines in a single block.

    Pattern: one MuPDF block contains 2*N or more lines that cycle through
    K distinct x-positions (K >= 2).  Lines at the same y-level belong to
    the same table row.  Only fires when MuPDF find_tables() independently
    confirms a table at the same location (bordered table confirmation).

    Returns (table_sections, used_block_indices).
    """
    table_sections: list[Section] = []
    used: set[int] = set()

    # Pre-build set of (page, y_mid) ranges from MuPDF tables for fast
    # lookup.  Entries carrying a rotation matrix are excluded: the
    # x/y clustering below operates in page space, which is transposed
    # on rotated pages; Pass 5 handles those rotation-aware.
    mupdf_ranges: list[tuple[int, float, float, float, float]] = []
    for pg, tbls in (page_mupdf_tables or {}).items():
        for tbl in tbls:
            if tbl.get("rot") is not None:
                continue
            bbox = tbl["bbox"]
            mupdf_ranges.append((pg, bbox[0], bbox[1], bbox[2], bbox[3]))

    for bi, block in enumerate(blocks):
        if len(block.lines) < _INLINE_GRID_MIN_LINES:
            continue

        # Gate: block must overlap a MuPDF-detected table region.
        # This ensures we only catch bordered tables, not code listings
        # or prose blocks with indented lines.
        bmid_y = (block.bbox[1] + block.bbox[3]) / 2.0
        bmid_x = (block.bbox[0] + block.bbox[2]) / 2.0
        margin = 10.0
        has_mupdf = False
        for pg, mx0, my0, mx1, my1 in mupdf_ranges:
            if (block.page_num == pg
                    and mx0 - margin <= bmid_x <= mx1 + margin
                    and my0 - margin <= bmid_y <= my1 + margin):
                has_mupdf = True
                break
        if not has_mupdf:
            continue

        # Blank lines are layout padding, not table rows: they would end up
        # as all-empty rows and their x0 could invent a column.
        ink_lines = [ln for ln in block.lines
                     if any(sp.text.strip() for sp in ln.spans)]
        if len(ink_lines) < _INLINE_GRID_MIN_LINES:
            continue

        # Cluster line x0 positions into columns.
        x_positions: list[float] = [ln.bbox[0] for ln in ink_lines]
        col_xs = _cluster_x_positions(x_positions)
        if len(col_xs) < 2:
            continue

        # Verify the gap between the two nearest columns is large enough.
        sorted_xs = sorted(col_xs)
        min_gap = min(sorted_xs[i + 1] - sorted_xs[i]
                      for i in range(len(sorted_xs) - 1))
        if min_gap < _INLINE_GRID_COL_GAP:
            continue

        # Group lines into rows by y-position.
        rows: list[list[Line]] = []
        for ln in ink_lines:
            placed = False
            for row in rows:
                if abs(ln.bbox[1] - row[0].bbox[1]) <= _INLINE_GRID_Y_BAND:
                    row.append(ln)
                    placed = True
                    break
            if not placed:
                rows.append([ln])

        if len(rows) < _INLINE_GRID_MIN_ROWS:
            continue

        # Drop x-clusters that too few rows reach. A centered header cell
        # sits at its own x, well clear of the left-aligned body beneath it,
        # and would otherwise become a phantom column that shifts every body
        # cell one place along. Reassigning it to the nearest surviving
        # column puts it back over the cells it labels.
        if len(col_xs) > 2:
            occupancy = Counter(
                _nearest_column(ln.bbox[0], col_xs)
                for row in rows for ln in row
            )
            kept = [x for ci, x in enumerate(col_xs)
                    if occupancy[ci] >= _INLINE_GRID_MIN_COL_ROWS]
            if len(kept) >= 2:
                col_xs = kept

        # Each row must span 2+ columns.
        num_cols = len(col_xs)
        valid_rows = 0
        for row in rows:
            row_col_set = set()
            for ln in row:
                ci = _nearest_column(ln.bbox[0], col_xs)
                row_col_set.add(ci)
            if len(row_col_set) >= 2:
                valid_rows += 1

        if valid_rows < _INLINE_GRID_MIN_ROWS:
            continue

        # Strict guard: at least 75% of rows must be multi-column.
        if valid_rows < len(rows) * _INLINE_GRID_VALID_ROW_RATIO:
            continue

        # Build cell data: rows x cols.
        all_rows_data: list[list[list]] = []
        all_lines: list[Line] = []
        for row_lines in rows:
            cell_spans: dict[int, list] = defaultdict(list)
            for ln in row_lines:
                ci = _nearest_column(ln.bbox[0], col_xs)
                if cell_spans[ci] and ln.spans:
                    cell_spans[ci].append(Span(text="\n"))
                cell_spans[ci].extend(ln.spans)
                all_lines.append(ln)
            table_row = [cell_spans.get(ci, []) for ci in range(num_cols)]
            all_rows_data.append(table_row)

        text = _render_table_text(all_rows_data)

        strategy = TableStrategy.PIPE_TABLE
        for row in all_rows_data:
            for cell_spans in row:
                if any("\n" in s.text for s in cell_spans):
                    strategy = TableStrategy.HTML_TABLE
                    break
            if strategy == TableStrategy.HTML_TABLE:
                break

        table_sections.append(Section(
            kind=SectionKind.TABLE,
            text=text,
            confidence=Confidence.HIGH,
            lines=all_lines,
            page_num=block.page_num,
            columns=all_rows_data,
            table_kind=TableKind.INLINE_GRID.value,
            table_strategy=strategy.value,
        ))
        used.add(bi)
        _log.debug("Inline-grid table: %d rows x %d cols on page %d",
                    len(all_rows_data), num_cols, block.page_num)

    return _merge_cross_page_fragments(table_sections), used


_MUPDF_TABLE_MIN_BBOX_SIZE = 50.0  # minimum width AND height for a real table

# Phantom-table guard for find_tables(). When the table bbox covers
# most of the page AND a single cell occupies a disproportionate
# fraction of the table height, find_tables() has likely merged a
# real (small) table with surrounding prose/headings into one
# full-page "table". The block-based detector handles the real
# table; the phantom must be rejected.
_MUPDF_TABLE_MAX_PAGE_COVERAGE = 0.80
_MUPDF_TABLE_MAX_CELL_FRACTION = 0.40

# Cross-page merge thresholds.  Used by the MuPDF-native per-page
# pre-classify absorb and by _merge_cross_page_fragments below.
_CROSS_PAGE_BOTTOM_Y = 600.0
_CROSS_PAGE_TOP_Y = 200.0
_CROSS_PAGE_MAX_GAP = 2


def _merge_cross_page_fragments(
    table_sections: list[Section],
) -> list[Section]:
    """Merge consecutive table sections that straddle a page break.

    A table running past the bottom of a page is detected once per page, so
    the fragments arrive as separate sections and every continuation row
    would render as a fresh pipe table with its first attendee promoted to a
    header.  Merge by appending continuation rows (skipping any repeated
    header) to the first fragment and dropping the rest.

    Guards (all must hold):
      - Same column count (structural identity).
      - First fragment ends near page bottom (y > _CROSS_PAGE_BOTTOM_Y).
      - Second fragment starts near page top (y < _CROSS_PAGE_TOP_Y).
      - Pages within _CROSS_PAGE_MAX_GAP (allows blank separator pages).

    table_kind is intentionally NOT checked: the same logical table gets
    different kinds per page because _classify_and_annotate runs
    independently per fragment.  Column count is the structural signal.

    Iterates until stable so A+B+C+D collapses in one pass sequence.
    """
    if len(table_sections) < 2:
        return table_sections

    changed = True
    while changed:
        changed = False
        merged_indices: set[int] = set()
        for si in range(len(table_sections) - 1):
            if si in merged_indices:
                continue
            sec_a = table_sections[si]
            sec_b = table_sections[si + 1]
            # Banded sections are deliberately split at category bands;
            # never re-merge them.  Their line bboxes are in unrotated
            # page space, so the y-guards below would be meaningless.
            if (sec_a.table_source == "banded_grid"
                    or sec_b.table_source == "banded_grid"):
                continue
            if not (sec_a.columns and sec_b.columns):
                continue
            if len(sec_a.columns[0]) != len(sec_b.columns[0]):
                continue
            # Use max page from lines for adjacency (page_num stays at
            # the first fragment's page after a merge).
            a_last_page = sec_a.page_num
            if sec_a.lines:
                pages_in_a = {
                    ln.page_num for ln in sec_a.lines
                    if hasattr(ln, 'page_num') and ln.page_num is not None
                }
                if pages_in_a:
                    a_last_page = max(pages_in_a)
            page_gap = sec_b.page_num - a_last_page
            if page_gap < 1 or page_gap > _CROSS_PAGE_MAX_GAP:
                continue
            a_max_y = max((ln.bbox[3] for ln in sec_a.lines), default=0)
            b_min_y = min((ln.bbox[1] for ln in sec_b.lines), default=999)
            if not (a_max_y > _CROSS_PAGE_BOTTOM_Y
                    and b_min_y < _CROSS_PAGE_TOP_Y):
                continue
            start = _header_dedup_start(sec_a.columns, sec_b.columns)
            sec_a.columns.extend(sec_b.columns[start:])
            sec_a.lines.extend(sec_b.lines)
            sec_a.text = _render_table_text(sec_a.columns)
            merged_indices.add(si + 1)
            changed = True
            _log.debug(
                "Cross-page merge: page %d + %d (cols=%d), now %d rows",
                sec_a.page_num, sec_b.page_num,
                len(sec_a.columns[0]), len(sec_a.columns))
        if merged_indices:
            table_sections = [
                s for i, s in enumerate(table_sections)
                if i not in merged_indices
            ]

    return table_sections


# Vertical rules of two find_tables() grids count as the same cut when
# every x differs by at most this much. P0957R8's Name/Value grid is
# 48.6 / 283.6 / 546.7 on one page and 48.5 / 283.6 / 546.8 on the next.
_RULED_GRID_X_TOLERANCE = 1.0


def _ruled_grid_xs(tbl: dict) -> list[float] | None:
    """Sorted unique vertical-rule x positions of a find_tables() grid."""
    xs: list[float] = []
    for cell in tbl.get("cells") or []:
        if not cell:
            continue
        xs.append(cell[0])
        xs.append(cell[2])
    if len(xs) < 4:
        return None
    xs.sort()
    rules = [xs[0]]
    for x in xs[1:]:
        if x - rules[-1] > _RULED_GRID_X_TOLERANCE:
            rules.append(x)
    return rules if len(rules) >= 3 else None


def _rules_match(left: list[float], right: list[float]) -> bool:
    if len(left) != len(right):
        return False
    return all(
        abs(a - b) <= _RULED_GRID_X_TOLERANCE for a, b in zip(left, right)
    )


def _section_y_span(section: Section, page: int) -> tuple[float, float] | None:
    tops = [
        ln.bbox[1] for ln in section.lines
        if getattr(ln, "page_num", page) == page
    ]
    bots = [
        ln.bbox[3] for ln in section.lines
        if getattr(ln, "page_num", page) == page
    ]
    if not tops:
        return None
    return min(tops), max(bots)


def _grid_for_section(
    section: Section, page: int, grids: dict[int, list[dict]],
) -> dict | None:
    span = _section_y_span(section, page)
    if span is None:
        return None
    y0, y1 = span
    for tbl in grids.get(page, []):
        if tbl.get("rot") is not None:
            continue
        tb = tbl.get("bbox")
        rules = _ruled_grid_xs(tbl)
        if tb is None or rules is None:
            continue
        if y1 < tb[1] or y0 > tb[3]:
            continue
        if tbl.get("col_count") != len(section.columns[0]):
            continue
        return tbl
    return None


def _prose_between(
    blocks: list[Block], page_a: int, y_after: float,
    page_b: int, y_before: float,
) -> bool:
    """True when a heading, caption or prose block sits between the fragments."""
    for blk in blocks:
        text = blk.text.strip()
        if not text or text.isdigit():
            continue
        if blk.page_num == page_a and blk.bbox[1] > y_after + 2.0:
            return True
        if blk.page_num == page_b and blk.bbox[3] < y_before - 2.0:
            return True
    return False


def _join_ruled_grid_continuations(
    table_sections: list[Section],
    grids: dict[int, list[dict]],
    blocks: list[Block],
) -> list[Section]:
    """Append a page-top fragment onto the table it continues.

    Both fragments must sit on ruled grids with the same vertical rules,
    the first grid must end in the bottom band and the second must start
    in the top band, and no prose may lie between them. A borderless
    paper (P4098R1 has no find_tables() grid) never joins.
    """
    if len(table_sections) < 2 or not grids:
        return table_sections
    drop: set[int] = set()
    for i, sec_a in enumerate(table_sections):
        if i in drop or not sec_a.columns or not sec_a.lines:
            continue
        pages_a = {
            ln.page_num for ln in sec_a.lines
            if getattr(ln, "page_num", None) is not None
        }
        page_a = max(pages_a) if pages_a else sec_a.page_num
        span_a = _section_y_span(sec_a, page_a)
        if span_a is None or span_a[1] <= _CROSS_PAGE_BOTTOM_Y:
            continue
        grid_a = _grid_for_section(sec_a, page_a, grids)
        if grid_a is None or grid_a["bbox"][3] <= _CROSS_PAGE_BOTTOM_Y:
            continue
        rules_a = _ruled_grid_xs(grid_a)
        if rules_a is None:
            continue
        for j, sec_b in enumerate(table_sections):
            if j == i or j in drop or not sec_b.columns or not sec_b.lines:
                continue
            if len(sec_a.columns[0]) != len(sec_b.columns[0]):
                continue
            if sec_b.page_num != page_a + 1:
                continue
            span_b = _section_y_span(sec_b, sec_b.page_num)
            if span_b is None or span_b[0] >= _CROSS_PAGE_TOP_Y:
                continue
            grid_b = _grid_for_section(sec_b, sec_b.page_num, grids)
            if grid_b is None or grid_b["bbox"][1] >= _CROSS_PAGE_TOP_Y:
                continue
            rules_b = _ruled_grid_xs(grid_b)
            if rules_b is None or not _rules_match(rules_a, rules_b):
                continue
            if _prose_between(blocks, page_a, span_a[1], sec_b.page_num, span_b[0]):
                continue
            start = _header_dedup_start(sec_a.columns, sec_b.columns)
            sec_a.columns.extend(sec_b.columns[start:])
            sec_a.lines.extend(sec_b.lines)
            sec_a.text = _render_table_text(sec_a.columns)
            drop.add(j)
            _log.debug(
                "Ruled-grid continuation: page %d + %d, now %d rows",
                page_a, sec_b.page_num, len(sec_a.columns))
            break
    if not drop:
        return table_sections
    return [s for i, s in enumerate(table_sections) if i not in drop]


_LABEL_MAX_WORDS = 3  # column-0 cells with more words are not labels


def _maybe_transpose_label_table(
    rows: list[list[list]],
) -> list[list[list]]:
    """Transpose a table whose first column contains short row labels.

    Detects tables where column 0 has short non-monospace labels
    (e.g. "Before", "After") at certain rows, with remaining rows
    holding data or continuation content. Transposes so the labels
    become column headers, and all content from each label group
    merges into one data cell per label.

    Handles both simple (2-row) and multi-row (4+ row) tables
    uniformly. Continuation rows between labels have their content
    from all columns merged into the preceding label's data cell.
    """
    if len(rows) < 2 or len(rows[0]) < 2:
        return rows

    num_cols = len(rows[0])
    if num_cols != 2:
        return rows

    # Scan column 0 for short non-monospace labels.
    labels: list[str] = []
    label_indices: list[int] = []
    for ri, row in enumerate(rows):
        cell0_text = "".join(s.text for s in row[0]).strip()
        if not cell0_text:
            continue
        words = cell0_text.split()
        is_mono = any(s.monospace for s in row[0] if s.text.strip())
        if len(words) <= _LABEL_MAX_WORDS and not is_mono:
            labels.append(cell0_text)
            label_indices.append(ri)

    if len(labels) < 2:
        return rows

    # Build transposed table: labels become column headers.
    new_num_cols = len(labels)
    header_row: list[list] = [list(rows[ri][0]) for ri in label_indices]

    # For each label, collect ALL content from its group rows
    # (label row through next label - 1) across all columns,
    # excluding the label text in column 0 of the label row.
    data_cells: list[list] = [[] for _ in range(new_num_cols)]
    for li, start_ri in enumerate(label_indices):
        end_ri = (label_indices[li + 1]
                  if li + 1 < len(label_indices) else len(rows))
        for ri in range(start_ri, end_ri):
            for ci in range(num_cols):
                # Skip the label cell itself (col 0 of the label row).
                if ri == start_ri and ci == 0:
                    continue
                cell_spans = rows[ri][ci]
                if cell_spans:
                    if data_cells[li]:
                        data_cells[li].append(Span(text="\n"))
                    data_cells[li].extend(cell_spans)

    return [header_row, data_cells]


def _rot_midpoint(
    bbox: tuple[float, float, float, float],
    rot: Optional[tuple[float, ...]],
) -> tuple[float, float]:
    """Midpoint of bbox, mapped through a rotation matrix if given.

    On rotated pages find_tables() reports geometry in reading
    (display) space while extract_mupdf blocks stay in unrotated page
    space. ``rot`` is the page rotation matrix (a, b, c, d, e, f) that
    maps page space into reading space; ``None`` means no rotation.
    """
    x = (bbox[0] + bbox[2]) / 2.0
    y = (bbox[1] + bbox[3]) / 2.0
    if rot is None:
        return x, y
    a, b, c, d, e, f = rot
    return a * x + c * y + e, b * x + d * y + f


def _rot_bbox(
    bbox: tuple[float, float, float, float],
    rot: Optional[tuple[float, ...]],
) -> tuple[float, float, float, float]:
    """Bbox mapped through a rotation matrix (normalized), see _rot_midpoint."""
    if rot is None:
        return bbox
    a, b, c, d, e, f = rot
    x0 = a * bbox[0] + c * bbox[1] + e
    y0 = b * bbox[0] + d * bbox[1] + f
    x1 = a * bbox[2] + c * bbox[3] + e
    y1 = b * bbox[2] + d * bbox[3] + f
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


# Banded rotated-table assembly (Pass 5 pre-step).  Geometry tolerances
# match the main Pass 5 loop; the band gap tolerance allows a band block
# to touch the adjacent fragment edges.  Rotated pages further apart
# than the page gap belong to independent tables and are never stitched.
_BANDED_CLUSTER_TOL = 10.0
_BANDED_MARGIN = 5.0
_BANDED_BAND_GAP_TOL = 2.0
_BANDED_MAX_PAGE_GAP = 2


def _norm_row_texts(row: list[list]) -> tuple[str, ...]:
    """Whitespace-normalized text per cell, for row comparisons."""
    return tuple(
        " ".join("".join(s.text for s in cell).split())
        for cell in row
    )


def _banded_header_match(row: list[list], header_norm: tuple[str, ...]) -> bool:
    """True when row repeats the canonical header (pre-normalized).

    Per-page header repeats may differ in a single cell (e.g. the
    P3100R6 appendix header has a typo on its first page only).  The
    tolerance is restricted to 3+ column tables: in a 2-column table a
    data row sharing one cell with the header is most likely real data,
    and dropping it would be silent data loss.
    """
    a = _norm_row_texts(row)
    if len(a) != len(header_norm):
        return False
    mismatches = sum(1 for x, y in zip(a, header_norm) if x != y)
    allowed = 1 if len(header_norm) >= 3 else 0
    return mismatches <= allowed


def _assemble_rotated_fragment(
    tbl_info: dict,
    blocks: list[Block],
    rot: tuple[float, ...],
    exclude: AbstractSet[int],
) -> tuple[list[list[list]], list, set[int]]:
    """Assemble one find_tables() fragment on a rotated page.

    Clusters the fragment's cell bboxes into a grid (same thresholds as
    the main Pass 5 loop) and assigns block lines to cells via
    reading-space midpoints.  Block indices in *exclude* (band heading
    candidates) are never claimed.  Returns (rows, lines,
    block_indices); rows that are completely empty are dropped.
    """
    page_num = tbl_info["page_num"]
    bbox = tbl_info["bbox"]
    valid_cells = [c for c in tbl_info["cells"] if c is not None]
    if not valid_cells:
        return [], [], set()

    y_tops = sorted(set(round(c[1], 1) for c in valid_cells))
    y_clusters: list[float] = []
    for yt in y_tops:
        if not y_clusters or abs(yt - y_clusters[-1]) > _BANDED_CLUSTER_TOL:
            y_clusters.append(yt)
        else:
            y_clusters[-1] = (y_clusters[-1] + yt) / 2.0
    x_mids = sorted(set(round((c[0] + c[2]) / 2.0, 1) for c in valid_cells))
    x_clusters: list[float] = []
    for xm in x_mids:
        if not x_clusters or abs(xm - x_clusters[-1]) > _BANDED_CLUSTER_TOL:
            x_clusters.append(xm)
        else:
            x_clusters[-1] = (x_clusters[-1] + xm) / 2.0

    nrows, ncols = len(y_clusters), len(x_clusters)
    cell_grid: list[list[tuple | None]] = [
        [None] * ncols for _ in range(nrows)
    ]
    for c in valid_cells:
        ri = min(range(nrows), key=lambda r: abs(c[1] - y_clusters[r]))
        ci = min(range(ncols),
                 key=lambda k: abs((c[0] + c[2]) / 2.0 - x_clusters[k]))
        cell_grid[ri][ci] = c

    rows_data: list[list[list]] = [
        [[] for _ in range(ncols)] for _ in range(nrows)
    ]
    lines = []
    block_indices: set[int] = set()
    m = _BANDED_MARGIN
    for idx, blk in enumerate(blocks):
        if blk.page_num != page_num or idx in exclude:
            continue
        bmx, bmy = _rot_midpoint(blk.bbox, rot)
        if not (bbox[0] - m <= bmx <= bbox[2] + m
                and bbox[1] - m <= bmy <= bbox[3] + m):
            continue
        block_indices.add(idx)
        for ln in blk.lines:
            lmx, lmy = _rot_midpoint(ln.bbox, rot)
            best_r, best_c = -1, -1
            best_score = float("inf")
            for ri in range(nrows):
                for ci in range(ncols):
                    cb = cell_grid[ri][ci]
                    if cb is None:
                        continue
                    if (cb[0] - m <= lmx <= cb[2] + m
                            and cb[1] - m <= lmy <= cb[3] + m):
                        cw = max(cb[2] - cb[0], 1.0)
                        ch = max(cb[3] - cb[1], 1.0)
                        score = (abs(lmx - (cb[0] + cb[2]) / 2.0) / cw
                                 + abs(lmy - (cb[1] + cb[3]) / 2.0) / ch)
                        if score < best_score:
                            best_score = score
                            best_r, best_c = ri, ci
            if best_r >= 0:
                cell = rows_data[best_r][best_c]
                if cell and ln.spans:
                    cell.append(Span(text="\n"))
                cell.extend(ln.spans)
            lines.append(ln)

    rows = [r for r in rows_data if any(cell for cell in r)]
    return rows, lines, block_indices


def _assemble_banded_run(
    run_pages: list[int],
    blocks: list[Block],
    page_mupdf_tables: dict[int, list[dict]],
) -> tuple[list[Section], set[int], set[int]]:
    """Banded assembly over one contiguous run of rotated pages.

    Returns (sections, used_block_indices, consumed_entry_ids).  When
    the run has no category band, everything is left to the main Pass 5
    loop and all three results are empty.
    """
    # Stream of (page, reading_y, kind, payload) items in reading order.
    stream: list[tuple] = []
    n_bands = 0
    run_entry_ids: set[int] = set()
    for pg in run_pages:
        entries = [e for e in page_mupdf_tables[pg]
                   if e.get("rot") is not None]
        run_entry_ids |= {id(e) for e in entries}
        rot = entries[0]["rot"]
        frags = sorted(entries, key=lambda e: e["bbox"][1])

        # Identify band candidates before fragments claim blocks: the
        # claim margin is wider than the band gap tolerance, so a band
        # heading hugging a fragment edge would otherwise be swallowed
        # into a table cell.
        x_lo = min(e["bbox"][0] for e in frags)
        x_hi = max(e["bbox"][2] for e in frags)
        band_candidates: dict[int, float] = {}
        for idx, blk in enumerate(blocks):
            if blk.page_num != pg or len(blk.lines) != 1:
                continue
            bmx, bmy = _rot_midpoint(blk.bbox, rot)
            if not (x_lo - _BANDED_MARGIN <= bmx <= x_hi + _BANDED_MARGIN):
                continue
            for k in range(len(frags) - 1):
                if (frags[k]["bbox"][3] - _BANDED_BAND_GAP_TOL <= bmy
                        <= frags[k + 1]["bbox"][1] + _BANDED_BAND_GAP_TOL):
                    band_candidates[idx] = bmy
                    break

        page_items: list[tuple] = []
        for e in frags:
            rows, lines, bidx = _assemble_rotated_fragment(
                {**e, "page_num": pg}, blocks, rot,
                exclude=band_candidates.keys())
            if not rows:
                continue
            page_items.append(
                (pg, e["bbox"][1], "frag", (rows, lines, bidx, id(e))))

        if not page_items:
            continue

        for bmy in band_candidates.values():
            page_items.append((pg, bmy, "band", None))
            n_bands += 1
        page_items.sort(key=lambda it: it[1])
        stream.extend(page_items)

    if n_bands == 0:
        return [], set(), set()

    # Walk the stream: bands open a new category; fragments append
    # their rows to the current category.  The first assembled row of
    # the run is the canonical header; rows that repeat it are dropped
    # (interior dedup).  Fragments whose column count differs from the
    # header belong to a different table and stay with the main loop.
    header: list[list] | None = None
    header_norm: tuple[str, ...] | None = None
    categories: list[dict] = []
    current: dict | None = None
    used: set[int] = set()
    skipped_entry_ids: set[int] = set()
    for pg, _y, kind, payload in stream:
        if kind == "band":
            current = {"page_num": pg, "rows": [], "lines": []}
            categories.append(current)
            continue
        rows, lines, bidx, entry_id = payload
        if header is not None and rows and len(rows[0]) != len(header):
            skipped_entry_ids.add(entry_id)
            continue
        if current is None:
            # Pre-band area: holds the canonical header fragment (and
            # any intro rows, which get their own unlabeled section).
            current = {"page_num": pg, "rows": [], "lines": []}
            categories.append(current)
        used |= bidx
        current["lines"].extend(lines)
        for row in rows:
            if header is None:
                header = row
                header_norm = _norm_row_texts(header)
                continue
            if _banded_header_match(row, header_norm):
                continue
            current["rows"].append(row)

    # Classify once over all data rows: every category is a slice of
    # the same logical table, so kind/strategy must be uniform.  The
    # row transformation step (code-row merging) is re-applied per
    # category because the classifier's merged rows cross category
    # boundaries.
    all_rows = [r for cat in categories for r in cat["rows"]]
    if not all_rows:
        return [], set(), set()
    kind_val, strategy_val, _ = _classify_and_annotate(all_rows)

    sections: list[Section] = []
    for cat in categories:
        if not cat["rows"]:
            continue
        cat_rows = cat["rows"]
        if kind_val == TableKind.CODE_COMPARISON.value:
            cat_rows = _merge_code_rows(cat_rows)
        # Copy the header per section: downstream enrichment mutates
        # section columns in place, and a shared row object would leak
        # edits across sibling categories.
        columns = [[list(cell) for cell in header]] + cat_rows
        sections.append(Section(
            kind=SectionKind.TABLE,
            text=_render_table_text(columns),
            confidence=Confidence.HIGH,
            lines=cat["lines"],
            page_num=cat["page_num"],
            columns=columns,
            table_kind=kind_val,
            table_strategy=strategy_val,
            table_source="banded_grid",
        ))
        _log.debug(
            "Banded rotated table: %d rows x %d cols starting page %d (%s)",
            len(columns), len(columns[0]), cat["page_num"], kind_val)

    return sections, used, run_entry_ids - skipped_entry_ids


def _detect_banded_rotated_tables(
    blocks: list[Block],
    page_mupdf_tables: dict[int, list[dict]],
) -> tuple[list[Section], set[int], set[int]]:
    """Stitch find_tables() fragments on rotated pages into category tables.

    Category bands (unclaimed single-line blocks sitting between two
    fragments, within the table x-range) act as merge barriers: each
    band starts a new table section, and fragments between bands are
    stitched together, across pages when a category spans several
    pages.  1-row fragments are continuation rows here, not noise.
    The band blocks themselves stay unclaimed so the prose pipeline
    renders them as headings.

    Rotated pages are grouped into contiguous runs (max gap
    _BANDED_MAX_PAGE_GAP); each run is assembled independently so an
    unrelated rotated table elsewhere in the document is never stitched
    into this one.  Runs without a band are left to the main Pass 5
    loop (today's behavior).

    Returns (sections, used_block_indices, consumed_entry_ids); the
    main loop skips exactly the entries whose id() is in the consumed
    set.
    """
    rot_pages = sorted(
        pg for pg, entries in page_mupdf_tables.items()
        if any(e.get("rot") is not None for e in entries)
    )
    if not rot_pages:
        return [], set(), set()

    runs: list[list[int]] = [[rot_pages[0]]]
    for pg in rot_pages[1:]:
        if pg - runs[-1][-1] <= _BANDED_MAX_PAGE_GAP:
            runs[-1].append(pg)
        else:
            runs.append([pg])

    sections: list[Section] = []
    used: set[int] = set()
    consumed: set[int] = set()
    for run_pages in runs:
        r_sections, r_used, r_consumed = _assemble_banded_run(
            run_pages, blocks, page_mupdf_tables)
        sections.extend(r_sections)
        used |= r_used
        consumed |= r_consumed
    return sections, used, consumed


def _detect_mupdf_native_tables(
    blocks: list[Block],
    page_mupdf_tables: dict[int, list[dict]],
) -> tuple[list[Section], set[int]]:
    """Detect tables using MuPDF's native find_tables() results.

    Maps pre-collected find_tables() data (cell bboxes) back to the
    existing Block/Line/Span objects so that classification and
    rendering can use monospace and font information.

    Returns (table_sections, used_block_indices).
    """
    table_sections: list[Section] = []
    used: set[int] = set()

    if not page_mupdf_tables:
        return table_sections, used

    # Pre-step: banded assembly for rotated pages.  Entries it consumed
    # are skipped by the main loop below; entries it left alone (runs
    # without bands, column-count mismatches) fall through.
    banded_sections, banded_used, banded_consumed = (
        _detect_banded_rotated_tables(blocks, page_mupdf_tables))
    table_sections.extend(banded_sections)
    used |= banded_used

    for page_num in sorted(page_mupdf_tables):
        for tbl_info in page_mupdf_tables[page_num]:
            if id(tbl_info) in banded_consumed:
                continue
            bbox = tbl_info["bbox"]
            row_count = tbl_info["row_count"]
            col_count = tbl_info["col_count"]
            cells = tbl_info["cells"]
            # Rotation matrix for rotated pages (synthetic entries and
            # tests may omit the key).
            rot = tbl_info.get("rot")

            if row_count < 2 or col_count < 1:
                continue
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
            # A drawn grid validated its own geometry; a 3-row table of
            # 13pt rows is 39pt tall and real (P4016R0 B.1).
            drawn = _is_drawing_grid(tbl_info)
            if not drawn and (w < _MUPDF_TABLE_MIN_BBOX_SIZE
                              or h < _MUPDF_TABLE_MIN_BBOX_SIZE):
                continue

            # Phantom-table guard: reject find_tables() results that
            # span most of the page with a disproportionately tall cell.
            valid_cells_for_guard = [c for c in cells if c is not None]
            if valid_cells_for_guard:
                page_height = 842.0  # A4 default; US Letter is 792
                page_coverage = h / page_height
                max_cell_h = max((c[3] - c[1]) for c in valid_cells_for_guard)
                max_cell_frac = max_cell_h / h if h > 0 else 0
                if (page_coverage > _MUPDF_TABLE_MAX_PAGE_COVERAGE
                        and max_cell_frac > _MUPDF_TABLE_MAX_CELL_FRACTION):
                    _log.debug(
                        "Rejected phantom find_tables() on page %d: "
                        "page_coverage=%.0f%%, max_cell_fraction=%.0f%%",
                        page_num, page_coverage * 100, max_cell_frac * 100)
                    continue

            # Build cell grid by clustering cell bboxes by y-position
            # (rows) and x-position (columns). find_tables() may return
            # cells in column-major order for some table layouts, so
            # relying on ri*col_count+ci is unreliable. Instead, group
            # cells spatially.
            valid_cells = [c for c in cells if c is not None]
            if len(valid_cells) < 2:
                continue

            # Cluster y-top positions into rows. Using y_top (c[1])
            # instead of y_mid avoids misclassification of merged cells
            # that span multiple logical rows (their tall y_mid drifts
            # into a separate cluster from the smaller sibling cells).
            y_tops = sorted(set(
                round(c[1], 1) for c in valid_cells))
            y_clusters: list[float] = []
            for yt in y_tops:
                if not y_clusters or abs(yt - y_clusters[-1]) > 10.0:
                    y_clusters.append(yt)
                else:
                    y_clusters[-1] = (y_clusters[-1] + yt) / 2.0

            # Cluster x-midpoints into columns.
            x_mids = sorted(set(
                round((c[0] + c[2]) / 2.0, 1) for c in valid_cells))
            x_clusters: list[float] = []
            for xm in x_mids:
                if not x_clusters or abs(xm - x_clusters[-1]) > 10.0:
                    x_clusters.append(xm)
                else:
                    x_clusters[-1] = (x_clusters[-1] + xm) / 2.0

            actual_rows = len(y_clusters)
            actual_cols = len(x_clusters)
            if actual_rows < 2 or actual_cols < 1:
                continue

            # Assign each cell to (row_idx, col_idx) by closest cluster.
            # Use y_top for row assignment (matches y_top clustering).
            cell_grid: list[list[tuple[float, float, float, float] | None]] = [
                [None] * actual_cols for _ in range(actual_rows)
            ]
            for c in valid_cells:
                cy = c[1]  # y_top
                cx = (c[0] + c[2]) / 2.0
                ri = min(range(actual_rows),
                         key=lambda r: abs(cy - y_clusters[r]))
                ci = min(range(actual_cols),
                         key=lambda c_: abs(cx - x_clusters[c_]))
                cell_grid[ri][ci] = c

            row_count = actual_rows
            col_count = actual_cols

            # Collect blocks that fall within the table bbox (with margin).
            margin = 5.0
            table_block_indices: list[int] = []
            for idx, blk in enumerate(blocks):
                if idx in used:
                    continue
                if blk.page_num != page_num:
                    continue
                bmid_x, bmid_y = _rot_midpoint(blk.bbox, rot)
                if (bbox[0] - margin <= bmid_x <= bbox[2] + margin
                        and bbox[1] - margin <= bmid_y <= bbox[3] + margin):
                    table_block_indices.append(idx)

            if not table_block_indices:
                continue

            # Map each line from collected blocks into the cell grid.
            all_rows_data: list[list[list]] = [
                [[] for _ in range(col_count)] for _ in range(row_count)
            ]
            all_lines = []

            caption_outside: list[int] = []
            for idx in table_block_indices:
                blk = blocks[idx]
                placed_lines: list[tuple[int, int, Line]] = []
                for ln in blk.lines:
                    lmid_x, lmid_y = _rot_midpoint(ln.bbox, rot)

                    best_r, best_c = -1, -1
                    best_score = float("inf")
                    for ri in range(row_count):
                        for ci in range(col_count):
                            cb = cell_grid[ri][ci]
                            if cb is None:
                                continue
                            if (cb[0] - margin <= lmid_x <= cb[2] + margin
                                    and cb[1] - margin <= lmid_y <= cb[3] + margin):
                                cw = max(cb[2] - cb[0], 1.0)
                                ch = max(cb[3] - cb[1], 1.0)
                                nx = abs(lmid_x - (cb[0] + cb[2]) / 2.0) / cw
                                ny = abs(lmid_y - (cb[1] + cb[3]) / 2.0) / ch
                                score = nx + ny
                                if score < best_score:
                                    best_score = score
                                    best_r, best_c = ri, ci

                    if best_r >= 0:
                        placed_lines.append((best_r, best_c, ln))
                # A "Table N - ..." caption whose block midpoint falls
                # inside the grid margin (P0957R8 Table 2 sits 8pt into
                # the find_tables bbox) must stay prose. Placing it in
                # the nearest cell drops it: the emitted rows come from
                # the grid, and the block is marked used.
                if _SPEC_TABLE_LABEL_RE.match(blk.text.strip()):
                    caption_outside.append(idx)
                    continue
                for best_r, best_c, ln in placed_lines:
                    cell = all_rows_data[best_r][best_c]
                    if cell and ln.spans:
                        cell.append(Span(text="\n"))
                    cell.extend(ln.spans)
                    all_lines.append(ln)
                if not placed_lines:
                    all_lines.extend(blk.lines)
            if caption_outside:
                table_block_indices = [
                    idx for idx in table_block_indices
                    if idx not in caption_outside
                ]

            # Cross-page continuation: when the table bbox extends
            # close to the page bottom, absorb code blocks from the
            # top of the next page that fall within the table's
            # x-range. Only monospace blocks qualify; stop at the
            # first non-monospace block (heading, caption, body text).
            _PAGE_BOTTOM_THRESH = 650.0
            next_page = page_num + 1
            if bbox[3] > _PAGE_BOTTOM_THRESH and col_count >= 2:
                cont_row: list[list] = [[] for _ in range(col_count)]
                table_mid = (bbox[0] + bbox[2]) / 2.0
                for idx, blk in enumerate(blocks):
                    if idx in used:
                        continue
                    if blk.page_num != next_page:
                        continue
                    if blk.bbox[1] > 200.0:
                        break
                    if not all(ln.is_monospace for ln in blk.lines):
                        break
                    bmid_x = (blk.bbox[0] + blk.bbox[2]) / 2.0
                    if bbox[0] - margin <= bmid_x <= bbox[2] + margin:
                        for ln in blk.lines:
                            lmid_x = (ln.bbox[0] + ln.bbox[2]) / 2.0
                            best_c = (0 if lmid_x < table_mid
                                      else col_count - 1)
                            cell = cont_row[best_c]
                            if cell and ln.spans:
                                cell.append(Span(text="\n"))
                            cell.extend(ln.spans)
                            all_lines.append(ln)
                        table_block_indices.append(idx)
                        used.add(idx)
                if any(cell for cell in cont_row):
                    all_rows_data.append(cont_row)

            # Drop rows that are completely empty.
            non_empty_rows = [
                r for r in all_rows_data
                if any(cell for cell in r)
            ]
            if len(non_empty_rows) < 2:
                continue

            # Transpose comparison tables: when column 0 contains only
            # short labels (e.g. "Before", "After") and column 1+ has
            # longer content, restructure so the labels become column
            # headers and corresponding data fills the columns below.
            # Never for a drawn grid: its rows are the drawn rows.
            if not drawn:
                non_empty_rows = _maybe_transpose_label_table(non_empty_rows)

            text = _render_table_text(non_empty_rows)

            # Exclude a short header row from classification signals
            # so non-monospace labels don't dilute mono_ratio.
            classify_rows = non_empty_rows
            header_excluded = False
            if (len(non_empty_rows) > 1
                    and all(len(cell) <= 1 for cell in non_empty_rows[0])
                    and sum(len("".join(s.text for s in cell).split())
                            for cell in non_empty_rows[0]) <= col_count):
                classify_rows = non_empty_rows[1:]
                header_excluded = True

            kind_val, strategy_val, classify_rows = (
                _classify_and_annotate(classify_rows))

            # Cross-page absorption: before rejecting a table as
            # false_positive or bibliography, check if it continues
            # the immediately preceding table section.  Small tail
            # fragments (e.g. 2 data rows + footer junk) often get
            # misclassified because the signal-to-noise ratio is low,
            # but structurally they belong to the previous table.
            # Use the MuPDF-native col count (tbl_info) because
            # spatial clustering may inflate actual_cols.
            mupdf_col_count = tbl_info["col_count"]
            if (table_sections
                    and (kind_val == TableKind.FALSE_POSITIVE.value
                         or kind_val == TableKind.BIBLIOGRAPHY.value)):
                prev = table_sections[-1]
                prev_cols = (len(prev.columns[0])
                             if prev.columns else 0)
                prev_last_page = prev.page_num
                if prev.lines:
                    ppages = {ln.page_num for ln in prev.lines
                              if hasattr(ln, 'page_num') and ln.page_num is not None}
                    if ppages:
                        prev_last_page = max(ppages)
                page_gap = page_num - prev_last_page
                if (prev_cols == mupdf_col_count
                        and 1 <= page_gap <= 2):
                    prev_max_y = max(
                        (ln.bbox[3] for ln in prev.lines), default=0)
                    cur_min_y = min(
                        (ln.bbox[1] for ln in all_lines), default=999)
                    if (prev_max_y > _CROSS_PAGE_BOTTOM_Y
                            and cur_min_y < _CROSS_PAGE_TOP_Y):
                        # Build rows from MuPDF-native extract data
                        # (correct column count) instead of the
                        # spatially-clustered non_empty_rows which may
                        # have inflated column count.
                        extract = tbl_info["extract"]
                        native_rows: list[list[list]] = []
                        for raw_row in extract:
                            cells = [
                                [Span(text=(c or ""))]
                                for c in raw_row
                            ]
                            filled = sum(
                                1 for c in raw_row
                                if c and c.strip()
                            )
                            if filled >= 2:
                                native_rows.append(cells)
                        if not native_rows:
                            continue
                        start = _header_dedup_start(
                            prev.columns, native_rows)
                        prev.columns.extend(native_rows[start:])
                        prev.lines.extend(all_lines)
                        prev.text = _render_table_text(prev.columns)
                        used.update(table_block_indices)
                        _log.debug(
                            "Cross-page absorb (pre-classify): "
                            "page %d into page %d table, now %d rows",
                            page_num, prev.page_num,
                            len(prev.columns))
                        continue

            # Bibliography: not a real table, skip so prose pipeline handles it.
            # Do NOT mark blocks as used so they stay in remaining.
            if kind_val == TableKind.BIBLIOGRAPHY.value:
                _log.debug("MuPDF native bibliography bypass: page %d",
                            page_num)
                continue

            # False positive: classification rejected the table.
            # Do NOT mark blocks as used so they stay in remaining
            # for the prose pipeline.
            if kind_val == TableKind.FALSE_POSITIVE.value:
                _log.debug(
                    "MuPDF native table: %d rows x %d cols on page %d "
                    "(false_positive, skipped)",
                    len(non_empty_rows), col_count, page_num)
                continue

            used.update(table_block_indices)

            if header_excluded:
                non_empty_rows = [non_empty_rows[0]] + classify_rows
            else:
                non_empty_rows = classify_rows

            table_sections.append(Section(
                kind=SectionKind.TABLE,
                text=text,
                confidence=Confidence.HIGH,
                lines=all_lines,
                page_num=page_num,
                columns=non_empty_rows,
                table_kind=kind_val,
                table_strategy=strategy_val,
            ))
            _log.debug(
                "MuPDF native table: %d rows x %d cols on page %d (%s)",
                len(non_empty_rows), col_count, page_num, kind_val,
            )

    table_sections = _merge_cross_page_fragments(table_sections)

    return table_sections, used


_HORIZONTAL_ROW_Y_TOLERANCE = 3.0
_HORIZONTAL_ROW_Y_TOLERANCE_WIDE = 12.0
_HORIZONTAL_ROW_WIDE_X_SPREAD = 150.0
_HORIZONTAL_ROW_MIN_CELLS = 3
# Gap-asymmetry guard: reject blocks where the ratio of largest to
# smallest inter-cell gap exceeds this threshold.  Real table rows
# have roughly uniform spacing (ratio 1-3); WG21 section headings
# like "4  General  [general]" have extreme asymmetry (ratio 5-13)
# because the stable name sits far to the right.
_HORIZONTAL_ROW_MAX_GAP_RATIO = 4.0

# Spanning-header absorption: when a valid run is found, the
# immediately preceding block may be a multi-column header with
# fewer columns (e.g. 2-col header over 3-col data table).
_SPANNING_HEADER_X_TOLERANCE = 40.0
_SPANNING_HEADER_Y_GAP_MAX = 30.0
_SPANNING_HEADER_MIN_COLS = 2
# A header label wrapped onto stacked lines in one column ("Feed" /
# "Rate" / "(msg/s)") is short; a prose paragraph at column 0 is not.
# Stacked lines longer than this end the cluster as non-header.
_SPANNING_HEADER_STACKED_MAX_LEN = 30

# Trailing horizontal-row split: blocks where MuPDF merged a table
# header into the preceding paragraph (happens when data cells are
# empty, e.g. P4012R0 §2.2 "Suggested Polls").
_TRAILING_HR_MIN_CELLS = 3
_TRAILING_HR_MAX_CELL_LEN = 4
_TRAILING_HR_Y_GAP = 8.0
_TRAILING_HR_MIN_BANDS = 2  # header + at least one data row

# Empty vote grid: a horizontal-row block whose cells are all WG21 poll
# vocabulary and that has no data row below it is a suggested (not yet
# taken) poll, e.g. P3978R0 §2.1. Pass 3 accepts it as a header-only
# table with an empty body row, the shape Pass 3a emits for P4012R0 §2.2.
_VOTE_HEADER_CELLS = frozenset({"SF", "F", "N", "A", "SA"})


def _is_lone_vote_header(
    blocks: list[Block],
    idx: int,
    used: set[int],
) -> bool:
    """True when blocks[idx] is a poll header row with no data row under it.

    Every line text must be a member of _VOTE_HEADER_CELLS, and no unused
    horizontal-row block on the same page may start within
    _PARTIAL_ROW_MAX_Y_GAP below the header's bottom edge: a number row
    that close belongs to the same table and is taken by the normal
    two-block run, not by this header-only path.
    """
    block = blocks[idx]
    if len(block.lines) < _HORIZONTAL_ROW_MIN_CELLS:
        return False
    if not all(ln.text.strip() in _VOTE_HEADER_CELLS for ln in block.lines):
        return False
    bottom = block.bbox[3]
    for k, other in enumerate(blocks):
        if k == idx or k in used or other.page_num != block.page_num:
            continue
        gap = other.bbox[1] - bottom
        if 0 <= gap <= _PARTIAL_ROW_MAX_Y_GAP and _block_horizontal_row(other):
            return False
    return True


def _block_horizontal_row(block: Block) -> list[float] | None:
    """Detect a block whose lines sit side-by-side at the same y-level.

    Returns x-start positions when the block has 3+ lines sharing
    the same y-band (within _HORIZONTAL_ROW_Y_TOLERANCE). This
    catches narrow poll/vote tables where column gaps are too small
    for _block_column_positions.

    When the strict tolerance fails, a relaxed check fires: if the
    lines span a wide horizontal range (>150pt) and the y-spread is
    within _HORIZONTAL_ROW_Y_TOLERANCE_WIDE, the block still qualifies.
    MuPDF sometimes reports slightly different y-positions for cells
    in the same visual row (observed 8pt spread on P4003R1 §9.4).
    """
    if len(block.lines) < _HORIZONTAL_ROW_MIN_CELLS:
        return None
    y_centers = [(ln.bbox[1] + ln.bbox[3]) / 2 for ln in block.lines]
    if max(y_centers) - min(y_centers) <= _HORIZONTAL_ROW_Y_TOLERANCE:
        cols = [ln.bbox[0] for ln in block.lines]
        if _gap_asymmetry_reject(block.lines):
            return None
        return cols

    # Relaxed: non-overlapping x-ranges (true side-by-side cells)
    # with moderate y jitter.  MuPDF sometimes reports slightly
    # different y-positions for cells in the same visual row
    # (observed 8pt spread on P4003R1 §9.4).  Only fires when
    # each line occupies a distinct horizontal lane: sorted by x0,
    # each line's x0 must exceed the previous line's x2 (right edge).
    y_spread = max(y_centers) - min(y_centers)
    if y_spread <= _HORIZONTAL_ROW_Y_TOLERANCE_WIDE:
        by_x = sorted(block.lines, key=lambda ln: ln.bbox[0])
        non_overlapping = True
        for k in range(len(by_x) - 1):
            if by_x[k + 1].bbox[0] < by_x[k].bbox[2]:
                non_overlapping = False
                break
        if non_overlapping:
            if _gap_asymmetry_reject(by_x):
                return None
            return [ln.bbox[0] for ln in by_x]

    return None


def _gap_asymmetry_reject(lines: list) -> bool:
    """Reject blocks with extreme gap asymmetry between cells.

    Two independent guards, either triggers rejection:

    1. Pure gap asymmetry: gap_ratio > _HORIZONTAL_ROW_MAX_GAP_RATIO.
       Real table rows have roughly uniform spacing (ratio 1-3); WG21
       section headings like "4  General  [general]" reach 5-13.

    2. Combined gap + width asymmetry: gap_ratio > 3 AND the widest
       cell is >10x the narrowest.  Catches reference-list patterns
       like "(1.1) — IEC Electropedia: ..." where a tiny marker sits
       next to a long description (width ratio 27, gap ratio 3.6).
       Real tables with extreme width ratios have uniform gaps (≤1.4)
       and vice versa; the combination is unique to list-marker blocks.
    """
    if len(lines) < 3:
        return False
    by_x = sorted(lines, key=lambda ln: ln.bbox[0])
    gaps: list[float] = []
    for k in range(len(by_x) - 1):
        gap = by_x[k + 1].bbox[0] - by_x[k].bbox[2]
        gaps.append(gap)
    positive = [g for g in gaps if g > 0]
    if len(positive) < 2:
        return False
    gap_ratio = max(positive) / min(positive)

    # Guard 1: pure gap asymmetry
    if gap_ratio > _HORIZONTAL_ROW_MAX_GAP_RATIO:
        return True

    # Guard 2: moderate gap asymmetry + extreme cell-width asymmetry,
    # restricted to exactly 3 cells.  The pattern is reference-list
    # markers "(1.1) — Long description..." which always decompose
    # into exactly 3 lines.  4+ cell rows are real tables even when
    # one cell is tiny (e.g. a "-" score column).
    _GAP_MODERATE = 3.0
    _WIDTH_EXTREME = 10.0
    if len(by_x) == 3 and gap_ratio > _GAP_MODERATE:
        widths = [ln.bbox[2] - ln.bbox[0] for ln in by_x]
        pos_w = [w for w in widths if w > 0]
        if len(pos_w) >= 2:
            width_ratio = max(pos_w) / min(pos_w)
            if width_ratio > _WIDTH_EXTREME:
                return True

    return False


def _collect_header_cluster(
    remaining: list[Block],
    absorbed: set[int],
    page_num: int,
    table_top: float,
    col_xs: list[float],
) -> tuple[list[int], list[list[Span]]] | None:
    """Gather the remaining blocks that form a shattered header above a table.

    Walks upward from *table_top*: the first block must end within
    _SPANNING_HEADER_Y_GAP_MAX, every further block within
    _ATOMIZED_HDR_MAX_LINE_GAP of the cluster's current top (a larger gap
    is the whitespace before a title or prose, which ends the header).
    Whitespace-only blocks (header/footer stripping leaves them behind)
    are skipped without joining or moving the top. A block joins only
    when every non-empty line sits on a table column and none spills
    past the next column (prose spanning columns), and only when the
    cluster stays well-formed with it: lines stacked in one column are a
    wrapped label and join into one cell, top to bottom, but only when
    each is short (prose at column 0 is long); two lines at the same
    height in one column are not a header. The first block that fails
    ends the cluster; what was gathered below it stands.

    Returns (indices into *remaining*, header row) or None when fewer than
    _SPANNING_HEADER_MIN_COLS columns are covered.
    """
    ncols = len(col_xs)
    cands = sorted(
        (bi for bi, b in enumerate(remaining)
         if bi not in absorbed and b.page_num == page_num
         and b.bbox[3] <= table_top),
        key=lambda bi: -remaining[bi].bbox[3])
    chosen: list[int] = []
    per_col: dict[int, list[tuple[float, float, Line]]] = {}  # (y_mid, x0, line)
    region_top = table_top
    max_gap = _SPANNING_HEADER_Y_GAP_MAX
    for bi in cands:
        blk = remaining[bi]
        if region_top - blk.bbox[3] > max_gap:
            break
        lines = [ln for ln in blk.lines if ln.spans and ln.text.strip()]
        if not lines:
            continue
        # None once a line of this block falls outside the column grid.
        blk_tagged: list[tuple[int, tuple[float, float, Line]]] | None = []
        for ln in lines:
            x0 = ln.bbox[0]
            ci = min(range(ncols), key=lambda c: abs(x0 - col_xs[c]))
            if abs(x0 - col_xs[ci]) >= _SPANNING_HEADER_X_TOLERANCE:
                blk_tagged = None
                break
            if (ci + 1 < ncols
                    and ln.bbox[2] > col_xs[ci + 1] + _COLUMN_X_TOLERANCE):
                blk_tagged = None
                break
            blk_tagged.append((ci, ((ln.bbox[1] + ln.bbox[3]) / 2, x0, ln)))
        if blk_tagged is None:
            break
        trial = {ci: list(ls) for ci, ls in per_col.items()}
        for ci, t in blk_tagged:
            trial.setdefault(ci, []).append(t)
        if not _header_cluster_well_formed(trial):
            break
        per_col = trial
        chosen.append(bi)
        region_top = min(region_top, blk.bbox[1])
        max_gap = _ATOMIZED_HDR_MAX_LINE_GAP

    if len(per_col) < _SPANNING_HEADER_MIN_COLS:
        return None
    header_row: list[list[Span]] = [[] for _ in range(ncols)]
    for ci, lines in per_col.items():
        for t in sorted(lines, key=lambda t: (t[0], t[1])):
            if header_row[ci]:
                header_row[ci].append(Span(text=" "))
            header_row[ci].extend(t[2].spans)
    return chosen, header_row


_PAPER_ID_CELL_RE = re.compile(r"^[PND]\d{3,5}R\d+$")
_SECTION_NUM_CELL_RE = re.compile(r"^\d+(?:\.\d+)*$")
# "4.1 exploration" is a section heading whose words were cut into
# columns. A packed function table does not start that way (P0533R9).
_SECTION_HEADING_CELL_RE = re.compile(r"^\d+\.\d+\b")
_HASH_HEADER_CELL = "#"


def _row_cell_text(cell: list) -> str:
    """Visible text of one table cell, with bold markers stripped."""
    return "".join(s.text for s in cell).replace("*", "").strip()


def _is_running_header_grid(rows: list) -> bool:
    """A 2-column grid whose header cell is a WG21 document number.

    Running headers (`P3978R3` beside `3 Motivation`) plus the section
    number and small-caps title look like a table to Pass 1 and Pass 2.
    Real tables do not put the document id in column 0.
    """
    if len(rows) < 2 or len(rows[0]) != 2:
        return False
    if not _PAPER_ID_CELL_RE.match(_row_cell_text(rows[0][0])):
        return False
    for row in rows[1:]:
        if len(row) < 2:
            return False
        c0 = _row_cell_text(row[0])
        if not _SECTION_NUM_CELL_RE.match(c0):
            return False
    return True


def _header_cluster_well_formed(
    per_col: dict[int, list[tuple[float, float, Line]]],
) -> bool:
    """Per-column constraints of a header cluster (see
    _collect_header_cluster): no two lines on one baseline, and stacked
    lines all short."""
    for lines in per_col.values():
        if len(lines) < 2:
            continue
        ordered = sorted(lines, key=lambda t: (t[0], t[1]))
        for a, b in zip(ordered, ordered[1:]):
            if b[0] - a[0] <= _HORIZONTAL_ROW_Y_TOLERANCE:
                return False
        if any(len(t[2].text.strip()) > _SPANNING_HEADER_STACKED_MAX_LEN
               for t in ordered):
            return False
    return True


def _absorb_hash_header_above_number(
    ts: Section,
    remaining: list[Block],
    absorbed: set[int],
) -> None:
    """Pull `# | Paper | Abstraction` onto a table whose header is row 1.

    The numbered body row sits inside the first absorption gap. The real
    header is one line further up, past the tightened 10pt cluster gap
    (P4100R0 and P4100R1 section 7.1). A second look from the new top
    reaches it. Only a header cell that is exactly `#` is prepended, so
    a numbered row that is the real header stays put.
    """
    if not ts.columns or not ts.columns[0] or not ts.lines:
        return
    if not _row_cell_text(ts.columns[0][0]).isdigit():
        return
    ts_y_top = min(ln.bbox[1] for ln in ts.lines)
    col_xs: list[float] = []
    for cell in ts.columns[0]:
        xs = [sp.bbox[0] for sp in cell
              if hasattr(sp, "bbox") and sp.bbox and any(sp.bbox)]
        col_xs.append(min(xs) if xs else 999.0)
    if any(x >= 999 for x in col_xs):
        return
    cluster = _collect_header_cluster(
        remaining, absorbed, ts.page_num, ts_y_top, col_xs)
    if cluster is None:
        return
    cluster_idxs, header_row = cluster
    if _row_cell_text(header_row[0]) != _HASH_HEADER_CELL:
        return
    if len(header_row) != len(ts.columns[0]):
        return
    for bi in cluster_idxs:
        for ln in remaining[bi].lines:
            ts.lines.insert(0, ln)
    ts.columns.insert(0, header_row)
    ts.text = _render_table_text(ts.columns)
    absorbed.update(cluster_idxs)
    _log.debug(
        "Hash header absorbed above numbered row: page %d", ts.page_num)


def _line_y_center(line: Line) -> float:
    return (line.bbox[1] + line.bbox[3]) / 2


def _is_cell_band(band: list[Line]) -> bool:
    """True when `band` looks like one row of short, side-by-side cells."""
    if len(band) < _TRAILING_HR_MIN_CELLS:
        return False
    if not all(len(ln.text.strip()) <= _TRAILING_HR_MAX_CELL_LEN
               for ln in band):
        return False
    by_x = sorted(band, key=lambda ln: ln.bbox[0])
    return not any(by_x[k + 1].bbox[0] < by_x[k].bbox[2]
                   for k in range(len(by_x) - 1))


def _trailing_cell_bands(
    lines: list[Line],
) -> tuple[list[list[Line]], int]:
    """Maximal run of trailing y-bands that all look like table rows.

    Walks backwards grouping lines into y-bands and stops at the first band
    that fails the cell guards or disagrees on cell count: a header and its
    data rows describe the same columns, so a differing count means the run
    has reached unrelated content.

    Returns (bands in document order, index where the run starts).
    """
    bands: list[list[Line]] = []
    idx = len(lines)
    while idx > 0:
        y_c = _line_y_center(lines[idx - 1])
        start = idx
        while (start > 0
               and abs(_line_y_center(lines[start - 1]) - y_c)
               <= _HORIZONTAL_ROW_Y_TOLERANCE):
            start -= 1
        band = lines[start:idx]
        if not _is_cell_band(band):
            break
        if bands and len(band) != len(bands[-1]):
            break
        bands.append(band)
        idx = start
    bands.reverse()
    return bands, idx


def _split_trailing_horizontal_rows(
    blocks: list[Block],
) -> tuple[list[Section], list[Block]]:
    """Split blocks where trailing lines form merged table rows.

    MuPDF merges table cells into the preceding paragraph block. Two shapes
    occur: a header row alone when the data cells are empty (P4012R0 §2.2),
    and a header row plus its data rows when both are populated (P3290R4's
    poll boxes, issue #368). Peeling only the last band mistakes the data row
    for the header, so peel every trailing band that qualifies.

    Bands must be (a) on one y-band each, (b) very short text, (c) separated
    by a y-gap from the paragraph text, and (d) non-overlapping in x. Creates
    a TABLE section and returns the shortened paragraph block.
    """
    table_sections: list[Section] = []
    result_blocks: list[Block] = []

    for block in blocks:
        if len(block.lines) < _TRAILING_HR_MIN_CELLS + 1:
            result_blocks.append(block)
            continue

        bands, start = _trailing_cell_bands(block.lines)

        # A lone band is only a merged header when it trails paragraph text.
        # A block that is entirely one row belongs to the horizontal-row pass.
        if len(bands) < _TRAILING_HR_MIN_BANDS and start == 0:
            bands = []
        # Merged rows sit visibly below the paragraph they were folded into.
        if bands and start > 0:
            prev_c = _line_y_center(block.lines[start - 1])
            first_c = min(_line_y_center(ln) for ln in bands[0])
            if first_c - prev_c < _TRAILING_HR_Y_GAP:
                bands = []

        if not bands:
            result_blocks.append(block)
            continue

        para_lines = block.lines[:start]
        if para_lines:
            result_blocks.append(Block(
                lines=para_lines,
                bbox=(block.bbox[0], block.bbox[1],
                      block.bbox[2], para_lines[-1].bbox[3]),
                page_num=block.page_num,
            ))

        rows: list[list[list]] = [
            [list(ln.spans) for ln in band] for band in bands]
        if len(rows) < _TRAILING_HR_MIN_BANDS:
            # Header whose data cells are empty: synthesize the body row so
            # the table does not render as a bare header.
            rows.append([[] for _ in bands[0]])
            text = " | ".join(ln.text.strip() for ln in bands[0])
        else:
            text = _render_table_text(rows)

        kind_val, strategy_val, _ = _classify_and_annotate(rows)

        table_sections.append(Section(
            kind=SectionKind.TABLE,
            text=text,
            confidence=Confidence.MEDIUM,
            lines=[ln for band in bands for ln in band],
            page_num=block.page_num,
            columns=rows,
            table_kind=kind_val,
            table_strategy=strategy_val,
        ))
        _log.debug(
            "Trailing horizontal-row split: page %d, %d band(s) x %d cells",
            block.page_num, len(bands), len(bands[0]))

    return table_sections, result_blocks


def _block_sits_on_columns(block: Block, cols: list[float]) -> bool:
    """True when `block` is one row on exactly the x-starts in `cols`."""
    if len(block.lines) != len(cols):
        return False
    y_centers = [(ln.bbox[1] + ln.bbox[3]) / 2 for ln in block.lines]
    if max(y_centers) - min(y_centers) > _HORIZONTAL_ROW_Y_TOLERANCE_WIDE:
        return False
    xs = sorted(ln.bbox[0] for ln in block.lines)
    return all(abs(x - c) <= _COLUMN_X_TOLERANCE
               for x, c in zip(xs, sorted(cols)))


def _grid_rows_left_behind(
    run_blocks: list[Block],
    cols: list[float],
    all_blocks: list[Block],
    page_mupdf_tables: dict[int, list[dict]] | None,
) -> list[Block]:
    """Rows of the run's bordered grid that the run did not claim.

    Pass 1's "partial view" rule, narrowed to Pass 3's family: an upright
    find_tables() region overlaps the run, reports more rows than the run
    has, and still contains unclaimed blocks that are themselves rows on
    the run's columns (same cell count, same x-starts, one y-band). Such a
    block failed _gap_asymmetry_reject (uneven cell texts inside a grid),
    so it belongs to the table. Instead of standing down and relying on a
    later pass to take the grid (which may never happen: Pass 4 can claim
    a subset and the overlap filter then hides the region from Pass 5),
    Pass 3 completes its own run with these rows.

    Only rows chained to the run within _PARTIAL_ROW_MAX_Y_GAP are
    returned, so two complete stacked grids sharing columns inside one
    over-reaching box stay two tables. A rows=0 box spanning a page of
    poll grids (p1068r11) fails the row-count test, and prose inside such
    a box never sits on the columns.
    """
    if not page_mupdf_tables or not run_blocks:
        return []
    page_num = run_blocks[0].page_num
    rx0 = min(b.bbox[0] for b in run_blocks)
    ry0 = min(b.bbox[1] for b in run_blocks)
    rx1 = max(b.bbox[2] for b in run_blocks)
    ry1 = max(b.bbox[3] for b in run_blocks)
    claimed = {id(b) for b in run_blocks}
    m = _MUPDF_REGION_MARGIN
    for tbl in page_mupdf_tables.get(page_num, []):
        if tbl.get("rot") is not None:
            continue
        if tbl.get("row_count", 0) <= len(run_blocks):
            continue
        tx0, ty0, tx1, ty1 = tbl["bbox"]
        if min(rx1, tx1) <= max(rx0, tx0) or min(ry1, ty1) <= max(ry0, ty0):
            continue
        candidates = [
            blk for blk in all_blocks
            if blk.page_num == page_num and id(blk) not in claimed
            and blk.bbox[0] >= tx0 - m and blk.bbox[2] <= tx1 + m
            and blk.bbox[1] >= ty0 - m and blk.bbox[3] <= ty1 + m
            and _block_sits_on_columns(blk, cols)]
        if not candidates:
            continue
        # Chain outward from the run: a candidate joins when it sits
        # within one fragment gap above or below the rows taken so far.
        taken: list[Block] = []
        lo, hi = ry0, ry1
        grew = True
        while grew:
            grew = False
            for blk in candidates:
                if any(blk is t for t in taken):
                    continue
                gap = max(blk.bbox[1] - hi, lo - blk.bbox[3], 0.0)
                if gap <= _PARTIAL_ROW_MAX_Y_GAP:
                    taken.append(blk)
                    lo, hi = min(lo, blk.bbox[1]), max(hi, blk.bbox[3])
                    grew = True
        if taken:
            return taken
    return []


def _detect_horizontal_row_tables(
    blocks: list[Block],
    rotated_pages: frozenset[int],
    page_mupdf_tables: dict[int, list[dict]] | None = None,
) -> tuple[list[Section], set[int]]:
    """Detect tables formed by consecutive horizontal-row blocks.

    Two or more adjacent blocks on the same page, each with 3+ lines
    at identical y-level and matching cell count, form a table.

    A single block whose cells are all poll vocabulary (SF, F, N, A, SA)
    with no horizontal-row block directly below it is an empty suggested
    poll (_is_lone_vote_header, P3978R0 §2.1); it forms a table on its
    own with a synthesized empty body row. Without this, Pass 4 fuses
    consecutive poll headers and their captions into one table.

    *rotated_pages* are skipped: the y-level geometry assumes upright
    text and produces garbage rows there; Pass 5 handles those pages
    rotation-aware.

    A run that is a partial view of a find_tables() grid is completed
    with the grid's other rows (see _grid_rows_left_behind): rows whose
    cell texts are uneven fail _gap_asymmetry_reject and would otherwise
    be left out (p4016r0 D.3 header and "Evaluation Order" row, N.6 last
    row). Completed rows are ordered by y, so a recovered header lands
    on top.
    """
    table_sections: list[Section] = []
    used: set[int] = set()
    i = 0

    while i < len(blocks):
        if blocks[i].page_num in rotated_pages or i in used:
            i += 1
            continue
        cols = _block_horizontal_row(blocks[i])
        if cols is None:
            i += 1
            continue

        run = [i]
        continuation_blocks: set[int] = set()
        ncols = len(cols)
        j = i + 1
        while j < len(blocks):
            nxt_cols = _block_horizontal_row(blocks[j])
            if (nxt_cols is not None
                    and len(nxt_cols) == ncols
                    and blocks[j].page_num == blocks[i].page_num):
                run.append(j)
                j += 1
            elif (blocks[j].page_num == blocks[i].page_num
                  and len(blocks[j].lines) == 1
                  and blocks[j].lines[0].text.strip()):
                # Single-line block that is a wrapped parenthetical
                # from the previous row's cell (e.g. "(kqueue)"
                # continuing "macOS" above).  Only absorb when the
                # text starts with '(' and x-aligns with a column.
                txt = blocks[j].lines[0].text.strip()
                if txt.startswith("("):
                    ln_x = blocks[j].lines[0].bbox[0]
                    col_dist = min(abs(ln_x - c) for c in cols)
                    if col_dist < 20.0:
                        run.append(j)
                        continuation_blocks.add(j)
                        j += 1
                        continue
                break
            else:
                break

        lone_vote_header = (
            len(run) < _MIN_TABLE_ROWS
            and _is_lone_vote_header(blocks, i, used)
        )
        if len(run) >= _MIN_TABLE_ROWS or lone_vote_header:
            left_behind = (
                [] if lone_vote_header
                else _grid_rows_left_behind(
                    [blocks[idx] for idx in run], cols, blocks,
                    page_mupdf_tables)
            )
            if left_behind:
                idx_of = {id(b): k for k, b in enumerate(blocks)}
                run.extend(idx_of[id(b)] for b in left_behind)
                run.sort(key=lambda k: blocks[k].bbox[1])
                _log.debug(
                    "Pass 3 completed run from find_tables grid: page %d, "
                    "+%d row(s), %d total",
                    blocks[i].page_num, len(left_behind), len(run))
            rows: list[list[list]] = []
            all_lines = []
            for idx in run:
                blk = blocks[idx]

                if idx in continuation_blocks:
                    # Merge this single-line block into the
                    # previous row's nearest column cell.
                    if rows:
                        ln = blk.lines[0]
                        all_lines.append(ln)
                        best_col = min(
                            range(ncols),
                            key=lambda ci: abs(ln.bbox[0] - cols[ci]),
                        )
                        prev = rows[-1]
                        if prev[best_col]:
                            prev[best_col].append(Span(text=" "))
                        prev[best_col].extend(ln.spans)
                    continue

                row = []
                for ln in blk.lines[:ncols]:
                    row.append(list(ln.spans))
                    all_lines.append(ln)
                while len(row) < ncols:
                    row.append([])
                # Merge extra lines (beyond ncols) into nearest cell.
                for ln in blk.lines[ncols:]:
                    all_lines.append(ln)
                    ln_x = ln.bbox[0]
                    best_col = min(
                        range(ncols),
                        key=lambda ci: abs(ln_x - cols[ci]),
                    )
                    if row[best_col]:
                        row[best_col].append(Span(text=" "))
                    row[best_col].extend(ln.spans)
                rows.append(row)

            if lone_vote_header:
                # Header whose data cells are empty: synthesize the body
                # row so the table does not render as a bare header
                # (same shape as _split_trailing_horizontal_rows).
                rows.append([[] for _ in range(ncols)])

            kind_val, strategy_val, rows = _classify_and_annotate(rows)
            text = _render_table_text(rows)

            table_sections.append(Section(
                kind=SectionKind.TABLE,
                text=text,
                confidence=Confidence.HIGH,
                lines=all_lines,
                page_num=blocks[run[0]].page_num,
                columns=rows,
                table_kind=kind_val,
                table_strategy=strategy_val,
            ))
            _log.debug(
                "Horizontal-row table: %d rows x %d cols on page %d",
                len(rows), ncols, blocks[run[0]].page_num,
            )
            used.update(run)
            i = j
        else:
            i += 1

    return table_sections, used


# ---------------------------------------------------------------------------
# Classification helpers (integrated from table_analyzer.py)
# ---------------------------------------------------------------------------

def _compute_table_signals(rows: list[list[list]]) -> dict:
    """Compute classification signals from table rows (list of cell-span-lists)."""
    if not rows:
        return {"empty": True}

    total_cells = 0
    empty_cells = 0
    monospace_cells = 0
    max_word_count = 0
    col_counts = []
    total_cell_length = 0
    total_spans = 0

    for row in rows:
        col_counts.append(len(row))
        for cell_spans in row:
            total_cells += 1
            total_spans += len(cell_spans)
            cell_text = "".join(s.text for s in cell_spans).strip()
            if not cell_text:
                empty_cells += 1
                continue

            total_cell_length += len(cell_text)
            words = cell_text.split()
            if len(words) > max_word_count:
                max_word_count = len(words)

            text_spans = [s for s in cell_spans if s.text.strip()]
            if text_spans and all(s.monospace for s in text_spans):
                monospace_cells += 1

    non_empty = total_cells - empty_cells
    num_cols = max(col_counts) if col_counts else 0

    # Per-column word count for key-value classification.
    col0_max_words = 0
    for row in rows:
        if row and row[0]:
            text = "".join(s.text for s in row[0]).strip()
            wc = len(text.split()) if text else 0
            if wc > col0_max_words:
                col0_max_words = wc

    # WG21 spec table header detection: 3-column tables whose header row
    # matches the "expression | return type | assertion/note" pattern
    # (or close variants like "operation | type | semantics").
    header_matches_spec = False
    if num_cols == 3 and rows:
        hdr = [
            "".join(s.text for s in cell).lower().strip()
            for cell in rows[0]
        ]
        if len(hdr) == 3:
            col0_spec = any(k in hdr[0] for k in ("expression", "operation"))
            col1_spec = any(k in hdr[1] for k in ("return", "type"))
            header_matches_spec = col0_spec and col1_spec

    # Bibliography signal: fraction of col-0 cells matching [Label] pattern.
    # Multi-ID cells (newline-separated) count as a match when every line
    # individually matches the bracket pattern.
    col0_bracket_count = 0
    col0_non_empty = 0
    for row in rows:
        if row and row[0]:
            text = "".join(s.text for s in row[0]).strip()
            if text:
                col0_non_empty += 1
                sub_lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
                if sub_lines and all(
                    _BIBLIOGRAPHY_LABEL_RE.match(sl) for sl in sub_lines
                ):
                    col0_bracket_count += 1
    col0_bracket_ratio = (col0_bracket_count / col0_non_empty
                          if col0_non_empty else 0.0)

    # NB-ballot signal: fraction of col-0 cells matching [CC-NNN] pattern.
    col0_ballot_count = 0
    for row in rows:
        if row and row[0]:
            text = "".join(s.text for s in row[0]).strip()
            if text and _NB_BALLOT_ID_RE.match(text):
                col0_ballot_count += 1
    col0_ballot_ratio = (col0_ballot_count / col0_non_empty
                         if col0_non_empty else 0.0)

    return {
        "empty": False,
        "empty_ratio": empty_cells / total_cells if total_cells > 0 else 0,
        "mono_ratio": monospace_cells / non_empty if non_empty > 0 else 0,
        "max_word_count": max_word_count,
        "col_count_consistent": len(set(col_counts)) <= 2,
        "num_cols": num_cols,
        "num_rows": len(rows),
        "avg_cell_length": total_cell_length / non_empty if non_empty > 0 else 0,
        "avg_spans_per_cell": total_spans / total_cells if total_cells > 0 else 0,
        "col0_max_words": col0_max_words,
        "header_matches_spec": header_matches_spec,
        "col0_bracket_ratio": col0_bracket_ratio,
        "col0_ballot_ratio": col0_ballot_ratio,
    }


def _classify_table(signals: dict) -> TableKind:
    """Classify a table based on its computed signals."""
    if signals.get("empty"):
        return TableKind.FALSE_POSITIVE

    if signals["empty_ratio"] > _EMPTY_RATIO_THRESHOLD:
        return TableKind.FALSE_POSITIVE

    if not signals["col_count_consistent"]:
        return TableKind.FALSE_POSITIVE

    # Tony Tables: few rows, many spans per cell (multi-line code packed
    # into each cell by MuPDF).
    if (signals["mono_ratio"] >= _MONO_RATIO_THRESHOLD
            and signals.get("num_cols", 0) <= 3
            and signals.get("num_rows", 0) <= 5
            and signals.get("avg_spans_per_cell", 0) > 10):
        return TableKind.CODE_COMPARISON

    # Per-line code tables: many rows where each cell is a single code
    # line (e.g. side-by-side struct definitions).  Distinguished from
    # code-declaration tables by high mono_ratio combined with very low
    # avg_spans_per_cell (each cell = one code token/line, not a
    # labelled signature with mixed fonts).
    if (signals["mono_ratio"] >= 0.85
            and signals.get("num_cols", 0) <= 3
            and signals.get("avg_spans_per_cell", 0) <= 3
            and signals.get("num_rows", 0) >= 4):
        return TableKind.CODE_COMPARISON

    # WG21 spec tables: 3-column requirement tables with known header
    # pattern (expression/return type/assertion).  Checked before the
    # prose-word fallback so they get html_table rendering regardless
    # of cell length.
    if signals.get("header_matches_spec"):
        return TableKind.SPEC_TABLE

    # NB-ballot tables: >= 50% of col-0 cells are national body comment IDs
    # like [ES-047], [FI-071], [SE]. Checked before bibliography because
    # short country-code labels also match the bibliography bracket regex.
    if (signals.get("col0_ballot_ratio", 0) >= 0.50
            and signals.get("num_rows", 0) >= 3):
        return TableKind.NB_BALLOT

    # Bibliography tables: >= 60% of col-0 cells are bracketed references
    # like [CodeQL], [P2900R14], [Das16]. Checked before KEY_VALUE because
    # 2-column bibliographies also match the key-value pattern.
    if (signals.get("col0_bracket_ratio", 0) >= _BIBLIOGRAPHY_LABEL_RATIO
            and signals.get("num_rows", 0) >= 2):
        return TableKind.BIBLIOGRAPHY

    # Key-value tables: exactly 2 columns where col-0 holds short field
    # labels and col-1 holds longer descriptive values.
    if (signals.get("num_cols") == 2
            and signals.get("col0_max_words", 99) <= _KV_COL0_MAX_WORDS
            and signals["max_word_count"] > _PROSE_WORD_THRESHOLD):
        return TableKind.KEY_VALUE

    if signals["max_word_count"] > _PROSE_WORD_THRESHOLD:
        return TableKind.PROSE_TABLE

    return TableKind.CLEAN_MATRIX


def _merge_code_rows(rows: list[list[list]]) -> list[list[list]]:
    """Merge consecutive per-line code rows into multi-line cells.

    When Pass 2 detects a side-by-side code table, MuPDF may deliver
    each code line as a separate block, producing many single-line rows.
    This merges them into one data row with newline-joined cells so the
    HTML renderer produces proper ``<pre>`` blocks.

    Only merges rows where every non-empty cell is monospace and
    contains no existing newlines (already multi-line cells stay as-is).
    The first row (header) is never merged into.
    """
    if len(rows) <= 2:
        return rows

    def _is_single_line_code_row(row: list[list]) -> bool:
        """True if every non-empty cell is monospace with no newlines."""
        for cell_spans in row:
            text = "".join(s.text for s in cell_spans).strip()
            if not text:
                continue
            text_spans = [s for s in cell_spans if s.text.strip()]
            if not text_spans or not all(s.monospace for s in text_spans):
                return False
            if any("\n" in s.text for s in cell_spans):
                return False
        return True

    def _is_code_accumulator(row: list[list]) -> bool:
        """True if every non-empty cell is all-monospace (may have newlines)."""
        for cell_spans in row:
            text = "".join(s.text for s in cell_spans).strip()
            if not text:
                continue
            text_spans = [s for s in cell_spans if s.text.strip()]
            if not text_spans or not all(s.monospace for s in text_spans):
                return False
        return True

    merged: list[list[list]] = [rows[0]]
    for row in rows[1:]:
        if (_is_single_line_code_row(row)
                and len(merged) >= 2
                and _is_code_accumulator(merged[-1])):
            target = merged[-1]
            for ci in range(len(row)):
                if ci >= len(target):
                    break
                if row[ci]:
                    if target[ci]:
                        target[ci].append(Span(text="\n"))
                    target[ci].extend(row[ci])
        else:
            merged.append(row)
    return merged


def _has_multiline_code_cell(rows: list[list[list]]) -> bool:
    """True when some cell holds monospace text broken across lines.

    A pipe cell cannot contain a line break, but not every break needs one.
    In code the break is semantic and must survive, so the table has to
    render as HTML. In prose it is only where the PDF soft-wrapped the cell,
    and flattening back to one line loses nothing. Monospace is what tells
    the two apart.
    """
    for row in rows:
        for cell_spans in row:
            if not any("\n" in s.text for s in cell_spans):
                continue
            ink = [s for s in cell_spans if s.text.strip()]
            if ink and all(s.monospace for s in ink):
                return True
    return False


def _classify_and_annotate(
    rows: list[list[list]],
) -> tuple[str, str, list[list[list]]]:
    """Classify rows, optionally merge, return (kind, strategy, rows)."""
    signals = _compute_table_signals(rows)
    kind = _classify_table(signals)
    strategy = _STRATEGY_MAP[kind]

    if kind == TableKind.CODE_COMPARISON:
        rows = _merge_code_rows(rows)

    # Pipe tables cannot represent multi-line cell content. Force HTML
    # rendering when a break is load-bearing; soft-wrapped prose is
    # flattened by the emitter instead.
    if strategy == TableStrategy.PIPE_TABLE and _has_multiline_code_cell(rows):
        strategy = TableStrategy.HTML_TABLE

    return kind.value, strategy.value, rows


def _detect_header_block(blocks: list[Block], table_start_idx: int,
                         ref_cols: list[float], num_cols: int
                         ) -> list[list] | None:
    """Check block preceding a table for column headers (e.g. Before | After).

    Returns a header row (list of cell-span-lists) if found, None otherwise.
    """
    if table_start_idx == 0:
        return None

    prev_blk = blocks[table_start_idx - 1]
    first_table_blk = blocks[table_start_idx]

    # Must be same page and close vertically
    if prev_blk.page_num != first_table_blk.page_num:
        return None
    y_gap = first_table_blk.lines[0].bbox[1] - prev_blk.lines[-1].bbox[3]
    if y_gap > 30.0 or y_gap < 0:
        return None

    # Must have same number of lines as columns (one label per column)
    if len(prev_blk.lines) != num_cols:
        return None

    # Check x-positions match the table columns
    for li, line in enumerate(prev_blk.lines):
        if abs(line.bbox[0] - ref_cols[li]) > _COLUMN_X_TOLERANCE * 2:
            return None

    # Must be non-monospace short text (headers, not code)
    for line in prev_blk.lines:
        text = "".join(s.text for s in line.spans).strip()
        if len(text) > 30:
            return None
        if any(s.monospace for s in line.spans if s.text.strip()):
            return None

    # Build header row
    header_row = []
    for line in prev_blk.lines:
        header_row.append(list(line.spans))
    while len(header_row) < num_cols:
        header_row.append([])
    return header_row


# ---------------------------------------------------------------------------
# Pass 3: geometric column grouping (borderless tables)
# ---------------------------------------------------------------------------

# Minimum distinct x-columns in a y-band for it to count as a table row.
# Set to 4 to avoid false positives from numbered lists (2-3 columns)
# and function signature blocks (3 columns).
_GEO_MIN_COLS_PER_BAND = 4

# Maximum distinct x-columns allowed.  Code blocks produce 20+ span
# x-positions per line; real borderless tables have 3-8 columns.
_GEO_MAX_COLS = 8

# Minimum number of multi-column y-bands to form a table region.
_GEO_MIN_TABLE_BANDS = 3

# Maximum gap (in y-bands) between two multi-column bands before the
# run is considered broken.  A band is _Y_BAND_HEIGHT (15pt), so a gap
# of 8 bands ≈ 120pt, accommodating multi-line cells whose wrapped
# lines only populate 1-2 columns instead of all 4.
_GEO_MAX_BAND_GAP = 8

# Maximum fraction of monospace spans in a candidate region.
# Code blocks are predominantly monospace; tables are not.
_GEO_MAX_MONO_RATIO = 0.50


def _detect_column_aligned_tables(
    blocks: list[Block],
    *,
    two_column_pages: frozenset[int] = frozenset(),
    rotated_pages: frozenset[int],
) -> tuple[list[Section], set[int]]:
    """Detect borderless tables via span-level x-position clustering.

    Implements the "Pass 3 (geometric column grouping)" described in the
    module docstring.  Works on blocks where each row is a separate
    single-line block with spans at multiple x-positions.

    Algorithm:
    1. For each page, bucket every non-empty span into (page, y_band)
       groups and collect distinct x-position buckets per y-band.
    2. Find y-bands with 3+ distinct x-columns (multi-column signal).
    3. Find contiguous runs of such y-bands (allowing small gaps for
       multi-line cells).
    4. For each run: collect the union of column x-positions, assign
       spans to columns, merge visual lines into logical table rows
       (a new row starts when the leftmost column has content).
    5. Classify and emit Section(kind=TABLE).

    Returns (table_sections, used_block_indices).
    """
    table_sections: list[Section] = []
    used: set[int] = set()

    # Index blocks by page.
    page_blocks: dict[int, list[tuple[int, Block]]] = defaultdict(list)
    for idx, blk in enumerate(blocks):
        page_blocks[blk.page_num].append((idx, blk))

    for page_num in sorted(page_blocks):
        idx_blocks = page_blocks[page_num]

        # Skip pages with two-column paper layout, and rotated pages:
        # the y-band/x-bucket geometry below assumes upright text and
        # produces garbage there; Pass 5 handles those rotation-aware.
        if page_num in two_column_pages:
            continue
        if page_num in rotated_pages:
            continue

        # Collect span x-positions per y-band.
        yband_xs: dict[int, set[int]] = defaultdict(set)
        yband_spans: dict[int, list[Span]] = defaultdict(list)
        yband_block_indices: dict[int, set[int]] = defaultdict(set)

        for idx, blk in idx_blocks:
            for line in blk.lines:
                if not line.spans or not line.text.strip():
                    continue
                # Use LINE-level x-position (line.bbox[0]), not
                # span-level.  Prose with inline code has all lines
                # at x=left-margin; real column tables have separate
                # blocks at distinct x-positions.
                x_key = round(line.bbox[0] / _COLUMN_X_BUCKET)
                y_key = round(
                    ((line.bbox[1] + line.bbox[3]) / 2.0)
                    / _Y_BAND_HEIGHT
                )
                yband_xs[y_key].add(x_key)
                yband_spans[y_key].extend(line.spans)
                yband_block_indices[y_key].add(idx)

        # Skip pages with two-column paper layout.
        if page_num in two_column_pages:
            continue

        # Find y-bands with enough distinct columns.
        multi_col_bands = sorted(
            yk for yk, xs in yband_xs.items()
            if len(xs) >= _GEO_MIN_COLS_PER_BAND
        )
        if len(multi_col_bands) < _GEO_MIN_TABLE_BANDS:
            continue

        # Find contiguous runs of multi-column bands.
        runs: list[list[int]] = []
        current_run = [multi_col_bands[0]]
        for i in range(1, len(multi_col_bands)):
            gap = multi_col_bands[i] - multi_col_bands[i - 1]
            if gap <= _GEO_MAX_BAND_GAP:
                current_run.append(multi_col_bands[i])
            else:
                if len(current_run) >= _GEO_MIN_TABLE_BANDS:
                    runs.append(current_run)
                current_run = [multi_col_bands[i]]
        if len(current_run) >= _GEO_MIN_TABLE_BANDS:
            runs.append(current_run)

        for run in runs:
            # Find column x-positions that recur across multiple
            # y-bands.  Font-change fragments (ligatures, bold/italic
            # transitions) produce noise x-positions that appear in
            # only 1 band; real columns repeat across many bands.
            x_band_counts: Counter[int] = Counter()
            for yk in run:
                for xk in yband_xs[yk]:
                    x_band_counts[xk] += 1
            stable_x_keys = {
                xk for xk, cnt in x_band_counts.items()
                if cnt >= _MIN_SHARED_YBANDS
            }
            raw_positions = sorted(x_key * _COLUMN_X_BUCKET
                                   for x_key in stable_x_keys)
            if len(raw_positions) < _GEO_MIN_COLS_PER_BAND:
                continue

            # Merge columns that are too close together.  Inline
            # code and font changes produce clusters of x-positions
            # within a single logical column.
            # Use a tighter merge threshold than _COLUMN_GAP_THRESHOLD
            # (50pt) because real table columns can be as close as 30pt
            # (e.g. row-number column at x=65, text column at x=95).
            _GEO_MERGE_THRESHOLD = 25.0
            col_positions = [raw_positions[0]]
            for xp in raw_positions[1:]:
                if xp - col_positions[-1] < _GEO_MERGE_THRESHOLD:
                    pass  # absorbed into previous column
                else:
                    col_positions.append(xp)
            # After merging, require at least 3 distinct columns.
            # The pre-merge check already required 4+ raw columns
            # per y-band; the merge step collapses close neighbors.
            if len(col_positions) < 3:
                continue
            if len(col_positions) > _GEO_MAX_COLS:
                continue

            # Monospace guard: skip regions dominated by code.
            region_spans = []
            for yk in run:
                region_spans.extend(yband_spans[yk])
            if region_spans:
                mono_count = sum(1 for s in region_spans if s.monospace)
                if mono_count / len(region_spans) > _GEO_MAX_MONO_RATIO:
                    continue

            # Also include intermediate y-bands (those with fewer
            # columns that fall between multi-column bands, e.g.
            # continuation lines of multi-line cells).
            y_min_band = run[0]
            y_max_band = run[-1]

            # Extend the range to capture trailing continuation lines
            # (multi-line cells whose last line falls just below
            # y_max_band and has fewer than _GEO_MIN_COLS_PER_BAND
            # distinct columns).
            col_x_set = {round(cp / _COLUMN_X_BUCKET) for cp in col_positions}
            for candidate_yk in sorted(yband_spans):
                if candidate_yk <= y_max_band:
                    continue
                if candidate_yk > y_max_band + _GEO_MAX_BAND_GAP:
                    break
                cand_xs = yband_xs.get(candidate_yk, set())
                if cand_xs and cand_xs <= col_x_set:
                    y_max_band = candidate_yk
                else:
                    break

            all_ybands = sorted(
                yk for yk in yband_spans
                if y_min_band <= yk <= y_max_band
            )

            # Filter out the page-number band (typically a lone centered
            # span at the very bottom of the page).
            filtered_ybands = []
            for yk in all_ybands:
                spans = yband_spans[yk]
                texts = [s.text.strip() for s in spans if s.text.strip()]
                if len(texts) == 1 and texts[0].isdigit() and len(texts[0]) <= 3:
                    continue
                filtered_ybands.append(yk)
            all_ybands = filtered_ybands

            if not all_ybands:
                continue

            # Assign spans to columns.
            def _assign_col(span_x: float) -> int:
                best = 0
                best_d = abs(span_x - col_positions[0])
                for ci, cx in enumerate(col_positions):
                    d = abs(span_x - cx)
                    if d < best_d:
                        best_d = d
                        best = ci
                return best

            # Build visual rows: group lines by y-band, assign to
            # columns based on their line.bbox[0].  All spans within
            # a line go into the same column cell.  Track which MuPDF
            # block indices contribute to each visual row so that
            # multi-line cells (lines from the same block spanning
            # multiple y-bands) can be detected during row-merge.
            num_cols = len(col_positions)
            visual_rows: list[tuple[int, list[list[Span]]]] = []
            _vrow_blk_ids: list[set[int]] = []

            for yk in all_ybands:
                cells: list[list[Span]] = [[] for _ in range(num_cols)]
                blk_ids: set[int] = set()
                # Re-collect lines for this y-band (not just spans).
                for idx, blk in idx_blocks:
                    for line in blk.lines:
                        if not line.spans or not line.text.strip():
                            continue
                        line_yk = round(
                            ((line.bbox[1] + line.bbox[3]) / 2.0)
                            / _Y_BAND_HEIGHT
                        )
                        if line_yk != yk:
                            continue
                        ci = _assign_col(line.bbox[0])
                        cells[ci].extend(line.spans)
                        blk_ids.add(idx)
                visual_rows.append((yk, cells))
                _vrow_blk_ids.append(blk_ids)

            # Merge visual rows into logical rows.  A new logical row
            # starts when the leftmost column (col 0) has non-empty
            # content, indicating a new table entry.  A col-0 value
            # that looks like a wrapped continuation of the previous
            # cell (starts with '(' or ',') is merged instead of
            # starting a new row — fixes P4003R1 §9.4 where "(kqueue)"
            # wraps from the previous cell's "macOS" line.
            #
            # Block-sharing continuation: when two consecutive visual
            # rows share a contributing MuPDF block, the lines come
            # from the same multi-line cell and must be merged even
            # if col 0 has content (P1000R7 wrapped prose table).
            logical_rows: list[list[list[Span]]] = []
            current_logical: list[list[Span]] | None = None

            for vi, (_, cells) in enumerate(visual_rows):
                col0_text = "".join(s.text for s in cells[0]).strip()
                shares_block = (
                    vi > 0
                    and current_logical is not None
                    and bool(_vrow_blk_ids[vi] & _vrow_blk_ids[vi - 1])
                )
                is_continuation = (
                    shares_block
                    or (col0_text
                        and current_logical is not None
                        and col0_text[0] in "(,;")
                )
                if col0_text and not is_continuation:
                    if current_logical is not None:
                        logical_rows.append(current_logical)
                    current_logical = [list(c) for c in cells]
                else:
                    if current_logical is None:
                        current_logical = [list(c) for c in cells]
                    else:
                        for ci in range(num_cols):
                            if cells[ci]:
                                if current_logical[ci] and any(
                                    s.text.strip()
                                    for s in current_logical[ci]
                                ):
                                    current_logical[ci].append(
                                        Span(text="\n"))
                                current_logical[ci].extend(cells[ci])
            if current_logical is not None:
                logical_rows.append(current_logical)

            # Header-split guard: the row-merge heuristic (new row when
            # col 0 is non-empty) can absorb data lines into the header
            # when the first data line starts on a y-band where col 0 is
            # still empty.  Detect this by checking for \n Span
            # separators in logical_rows[0]: if the text before the
            # first \n is a short label (<=5 words) in most cells, split
            # row 0 into a clean header and a spillover data fragment.
            if logical_rows:
                row0 = logical_rows[0]
                cells_with_nl = 0
                short_pre_nl = 0
                for cell_spans in row0:
                    nl_idx = next(
                        (i for i, s in enumerate(cell_spans)
                         if s.text == "\n"), None)
                    if nl_idx is not None:
                        cells_with_nl += 1
                        pre_text = "".join(
                            s.text for s in cell_spans[:nl_idx]).strip()
                        if len(pre_text.split()) <= _COLALIGN_HEADER_MAX_WORDS:
                            short_pre_nl += 1

                if cells_with_nl >= 2 and short_pre_nl == cells_with_nl:
                    header_row: list[list[Span]] = []
                    spill_row: list[list[Span]] = []
                    for cell_spans in row0:
                        nl_idx = next(
                            (i for i, s in enumerate(cell_spans)
                             if s.text == "\n"), None)
                        if nl_idx is not None:
                            header_row.append(list(cell_spans[:nl_idx]))
                            spill_row.append(list(cell_spans[nl_idx + 1:]))
                        else:
                            header_row.append(list(cell_spans))
                            spill_row.append([])

                    logical_rows[0] = header_row
                    # Merge spillover into row 1 if it exists; otherwise
                    # insert as a new row.
                    if len(logical_rows) > 1:
                        for ci in range(num_cols):
                            if spill_row[ci]:
                                if logical_rows[1][ci] and any(
                                    s.text.strip()
                                    for s in logical_rows[1][ci]
                                ):
                                    logical_rows[1][ci] = (
                                        spill_row[ci]
                                        + [Span(text="\n")]
                                        + logical_rows[1][ci]
                                    )
                                else:
                                    logical_rows[1][ci] = spill_row[ci]
                    else:
                        has_content = any(
                            any(s.text.strip() for s in c)
                            for c in spill_row
                        )
                        if has_content:
                            logical_rows.insert(1, spill_row)

            if len(logical_rows) < _MIN_TABLE_ROWS:
                continue

            # Cross-column merge guard: if the table columns span
            # both left (<280pt) and right (>320pt) halves AND the
            # majority of cells are empty, this is likely two
            # separate page columns merged into one table.
            _MERGE_LEFT = 280.0
            _MERGE_RIGHT = 320.0
            has_left_col = any(x < _MERGE_LEFT for x in col_positions)
            has_right_col = any(x > _MERGE_RIGHT for x in col_positions)
            if has_left_col and has_right_col:
                total_cells = sum(
                    len(row) for row in logical_rows)
                empty_cells = sum(
                    1 for row in logical_rows
                    for cell in row
                    if not "".join(s.text for s in cell).strip()
                )
                if total_cells > 0 and empty_cells / total_cells > 0.15:
                    continue

            # Bullet/dash list guard: if column 0 is predominantly
            # bullet markers, this is a list, not a table.
            _BULLET_CHARS = frozenset("-\u2022\u2013\u2014")
            col0_texts = [
                "".join(s.text for s in row[0]).strip()
                for row in logical_rows
            ]
            bullet_count = sum(
                1 for t in col0_texts
                if t and all(ch in _BULLET_CHARS for ch in t)
            )
            if len(col0_texts) > 0 and bullet_count / len(col0_texts) > 0.5:
                continue

            # Classify the table.
            kind_val, strategy_val, logical_rows = _classify_and_annotate(
                logical_rows)
            if kind_val == "false_positive":
                continue

            # Collect consumed blocks and lines.
            consumed_indices: set[int] = set()
            for yk in all_ybands:
                consumed_indices |= yband_block_indices.get(yk, set())
            used |= consumed_indices

            all_lines = []
            for ci in consumed_indices:
                blk = blocks[ci]
                all_lines.extend(blk.lines)
            all_lines.sort(key=lambda ln: (ln.bbox[1], ln.bbox[0]))

            text = _render_table_text(logical_rows)

            table_sections.append(Section(
                kind=SectionKind.TABLE,
                text=text,
                confidence=Confidence.HIGH,
                lines=all_lines,
                page_num=page_num,
                columns=logical_rows,
                table_kind=kind_val,
                table_strategy=strategy_val,
                table_source="column_aligned",
            ))
            _log.info(
                "Column-aligned table on page %d: %d rows x %d cols "
                "[kind=%s, strategy=%s]",
                page_num, len(logical_rows), num_cols,
                kind_val, strategy_val)

    # Cross-page continuation: when consecutive tables on adjacent
    # pages share the same column count and the second table's header
    # row is textually identical, strip the duplicate header from the
    # continuation so the emit phase can render them as one visual
    # table.  We do NOT merge Sections (that breaks page-based
    # y-position sorting); we just remove the repeated header row.
    if len(table_sections) >= 2:
        for i in range(len(table_sections) - 1):
            t1 = table_sections[i]
            t2 = table_sections[i + 1]
            if (t2.page_num - t1.page_num) not in (0, 1):
                continue
            if not t1.columns or not t2.columns:
                continue
            if len(t1.columns[0]) != len(t2.columns[0]):
                continue
            h1 = tuple(
                "".join(s.text for s in cell).strip()
                for cell in t1.columns[0])
            h2 = tuple(
                "".join(s.text for s in cell).strip()
                for cell in t2.columns[0])
            if h1 == h2 and len(t2.columns) > 1:
                t2.columns = t2.columns[1:]
                t2.table_continuation = True
                t2.text = _render_table_text(t2.columns)
                _log.info(
                    "Stripped duplicate header from column-aligned "
                    "table continuation on page %d",
                    t2.page_num)

    return table_sections, used


# ---------------------------------------------------------------------------
# Pass 4b: label-anchored spec table detection
# ---------------------------------------------------------------------------
# WG21 spec tables carry a "Table N - XYZ requirements" caption above the
# grid.  MuPDF distributes each column's cells into separate Block objects
# at distinct x-positions, so existing heuristic passes (which look for
# multi-column lines *within* a single block) often miss them.  The phantom
# guard in Pass 5 then rejects the MuPDF-native fallback because the tables
# span most of the page.
#
# This pass uses the label as an anchor, collects ALL blocks (including
# monospace) in the spatial region below the label until the next heading
# or table label, clusters them by x-position to recover columns, and
# merges visual lines into logical rows.
#
# Crucially, monospace blocks inside the table region are NOT skipped:
# the "expression" column of spec tables contains code identifiers like
# `a.await_suspend(h, env)`.  Standalone code blocks (concept definitions,
# struct declarations) sit above the table label and are never touched.
# ---------------------------------------------------------------------------

_SPEC_TABLE_LABEL_RE = re.compile(r"^Table\s+(\d+)\s*[\u2014\u2013\-]")

# Y-coordinate below which blocks are page footers (page numbers).
# A4 = 842pt, US Letter = 792pt.  790 catches both.
_SPEC_TABLE_FOOTER_Y = 790.0

# Minimum gap between x-position buckets to count as separate columns.
_SPEC_TABLE_X_MERGE = 25.0

# Bucket size for x-position clustering.
_SPEC_TABLE_X_BUCKET = 10.0

# y-band height for row grouping.
_SPEC_TABLE_Y_BAND = 15.0

# Section-number pattern for heading detection (stop boundary).
_SPEC_HEADING_NUM_RE = re.compile(r"^\d+(?:\.\d+)*\s")

_SPEC_HEADING_SUBSECTION_RE = re.compile(r"^\d+\.\d+")

_DATA_MARKERS_RE = re.compile(
    r"^(Returns|Effects|Preconditions|Postconditions|"
    r"Synchronization|Shall|Same|Requires|Remarks)\b",
    re.IGNORECASE)

_SPEC_COL_NAMES_RE = re.compile(
    r"\b(expression|return\s+type|assertion|pre/post|"
    r"preconditions?|postconditions?|requirements?)\b",
    re.IGNORECASE)

_COL_HEADER_RE = re.compile(
    r"^(expression|return\s+type|assertion|conditions|"
    r"pre/post-conditions|assertion/note\s+pre/post-?)$",
    re.IGNORECASE,
)

_COLALIGN_HEADER_MAX_WORDS = 5
_SPEC_HEADER_MAX_WORDS = 4


def _is_spec_heading_block(block: Block) -> bool:
    """True if *block* looks like a section heading (stop boundary).

    Detects numbered headings (e.g. "11.3.2 Concept io_runnable")
    that delimit where a table region ends.  Accepts both bold
    headings at any size > 10 and non-bold subsection headings
    (font_size >= 10.5 with dotted numbering like ``11.3.3``),
    because P4003R1 renders some subsection headings without bold.
    """
    if not block.lines:
        return False
    first = block.lines[0]
    text = first.text.strip()
    if not _SPEC_HEADING_NUM_RE.match(text):
        return False
    if first.is_bold and first.font_size > 10:
        return True
    if first.font_size >= 10.5 and _SPEC_HEADING_SUBSECTION_RE.match(text):
        return True
    return False


def _detect_spec_tables_by_label(
    blocks: list[Block],
) -> tuple[list[Section], set[int]]:
    """Detect WG21 spec tables anchored by 'Table N - ...' caption blocks.

    Algorithm:
      1. Scan blocks for label pattern ``Table <N> - <description>``.
      2. For each label, define the collection region: same page, from
         label y to the next heading, next table label, or page footer.
      3. Extend into the next page when the first blocks there are not
         headings and have x-positions matching table columns (cross-page
         continuation).
      4. Cluster collected blocks by x-position to identify columns.
      5. Group by y-band, assign to columns, merge into logical rows.
      6. Classify and emit as SPEC_TABLE Section.

    Returns (table_sections, used_block_indices).
    """
    table_sections: list[Section] = []
    used: set[int] = set()

    # Build (global_index, block) list and locate label blocks.
    labels: list[tuple[int, int, Block]] = []  # (global_idx, table_num, block)
    for i, blk in enumerate(blocks):
        m = _SPEC_TABLE_LABEL_RE.match(blk.text.strip())
        if m:
            labels.append((i, int(m.group(1)), blk))

    if not labels:
        return table_sections, used

    for label_gi, table_num, label_blk in labels:
        label_page = label_blk.page_num
        label_y = label_blk.bbox[1]

        # Determine y-end boundary on the label's page: stop at the next
        # heading, next table label, or numbered note, whichever comes
        # first.
        y_end = _SPEC_TABLE_FOOTER_Y
        for j in range(label_gi + 1, len(blocks)):
            b = blocks[j]
            if b.page_num != label_page:
                break
            by = b.bbox[1]
            if by >= _SPEC_TABLE_FOOTER_Y:
                continue
            if by < label_y - 5:
                continue
            txt = b.text.strip()
            if _SPEC_TABLE_LABEL_RE.match(txt):
                y_end = by - 5
                break
            if _is_spec_heading_block(b):
                y_end = by - 5
                break
            if re.match(r"^\d+\s*\[", txt):
                y_end = by - 5
                break
            if (re.match(r"^\d+\s", txt)
                    and b.bbox[2] - b.bbox[0] > 300):
                y_end = by - 5
                break

        # Collect all blocks in the region [label_y, y_end) on label_page,
        # skipping page footers.  MuPDF may return blocks out of
        # y-order (e.g. a code listing at y=170 after the label at
        # y=715), so explicitly skip blocks above the label.
        collected: list[tuple[int, Block]] = []
        next_page_start = -1  # index where next page begins

        for j in range(label_gi, len(blocks)):
            b = blocks[j]
            if b.page_num == label_page:
                if b.bbox[1] >= _SPEC_TABLE_FOOTER_Y:
                    continue
                if b.bbox[1] >= y_end and j != label_gi:
                    break
                if b.bbox[1] < label_y - 5 and j != label_gi:
                    continue
                collected.append((j, b))
            elif b.page_num > label_page:
                next_page_start = j
                break

        # Cross-page extension: spec tables often span 2-3 pages.
        # Continue collecting on subsequent pages until a heading,
        # a numbered paragraph (e.g. "3 [ Note: ..."), or a block
        # whose x-position is far from any table column is hit.
        # Note: len(collected) >= 1 (not 2) because a table label
        # can sit at the bottom of a page with the entire body on
        # the next page (e.g. Table 3 in P4003R1 at pg 55 y=715).
        if next_page_start > 0 and len(collected) >= 1:
            # Compute column x-buckets from same-page blocks for
            # matching cross-page content.  When the label sits alone
            # at the bottom of a page (no same-page data blocks), we
            # accept all blocks on the next page until we accumulate
            # enough column positions to discriminate.
            same_page_xs: set[int] = set()
            for _, cb in collected[1:]:  # skip label itself
                for ln in cb.lines:
                    same_page_xs.add(round(ln.bbox[0] / _SPEC_TABLE_X_BUCKET))
            # _join_cross_page may have merged header lines from the
            # next page into the label block.  Seed column positions
            # from those merged lines so the collection loop knows
            # all three column x-positions before it starts.
            lbl_blk_0 = collected[0][1]
            for ln in lbl_blk_0.lines:
                if ln.page_num != label_page:
                    same_page_xs.add(
                        round(ln.bbox[0] / _SPEC_TABLE_X_BUCKET))

            current_page = label_page + 1
            seen_stop = False
            for j in range(next_page_start, len(blocks)):
                b = blocks[j]
                if b.page_num != current_page:
                    if b.page_num == current_page + 1:
                        current_page = b.page_num
                        seen_stop = False
                    else:
                        break
                if b.bbox[1] >= _SPEC_TABLE_FOOTER_Y:
                    continue
                if _is_spec_heading_block(b):
                    if b.bbox[0] > 250:
                        continue
                    break
                if _SPEC_TABLE_LABEL_RE.match(b.text.strip()):
                    break
                text = b.text.strip()
                first_line = b.lines[0].text.strip() if b.lines else text
                is_page_num_prefix = (
                    first_line.isdigit() and len(first_line) <= 3
                )
                # Numbered note/paragraph at the left margin signals
                # end of table.  MuPDF may deliver blocks out of
                # y-order: table-column blocks (x > 250) can follow
                # stop blocks in the list even though they are above
                # them on the page.  Set a flag and skip left-margin
                # blocks, but keep collecting right-column blocks
                # that belong to the table.
                is_stop_pattern = (
                    re.match(r"^\d+\s*\[", text)
                    or (not is_page_num_prefix
                        and re.match(r"^\d+\s", text)
                        and b.bbox[2] - b.bbox[0] > 300)
                )
                if is_stop_pattern:
                    seen_stop = True
                    continue
                bx = round(b.bbox[0] / _SPEC_TABLE_X_BUCKET)
                bootstrapping = len(same_page_xs) < 2
                in_column = (bootstrapping
                             or bx in same_page_xs
                             or b.bbox[0] > 250)
                if in_column:
                    collected.append((j, b))
                    for ln in b.lines:
                        same_page_xs.add(
                            round(ln.bbox[0] / _SPEC_TABLE_X_BUCKET))
                elif seen_stop:
                    # After a stop pattern, skip non-column blocks
                    # but keep scanning: MuPDF may deliver column
                    # blocks later in the list (out of y-order).
                    continue
                else:
                    break

        # Salvage pass: MuPDF sometimes delivers table-column blocks
        # after headings or notes in the block list even though they
        # are visually above them on the page.  Scan remaining blocks
        # on collected pages and pick up any that sit in a known
        # column x-position and below the header/footer threshold.
        collected_idxs = {gi for gi, _ in collected}
        if collected:
            collected_pages = {cb.page_num for _, cb in collected}
            max_page = max(collected_pages)
            salvaged: list[tuple[int, Block]] = []
            for j in range(next_page_start, len(blocks)):
                b = blocks[j]
                if b.page_num not in collected_pages:
                    if b.page_num > max_page:
                        break
                    continue
                if j in collected_idxs:
                    continue
                if b.bbox[1] >= _SPEC_TABLE_FOOTER_Y:
                    continue
                bx = round(b.bbox[0] / _SPEC_TABLE_X_BUCKET)
                if bx in same_page_xs or b.bbox[0] > 250:
                    salvaged.append((j, b))
            if salvaged:
                collected.extend(salvaged)

        # _join_cross_page may have merged the column-header block from
        # the next page into the label block (e.g. Table 3 label at the
        # bottom of page 55 + header row at top of page 56).  Detect
        # this by checking for lines whose page_num differs from the
        # label page, split them out, and fix the label block so the
        # header text does not leak as prose.
        if collected:
            lbl_gi, lbl_blk = collected[0]
            merged_lines = [
                ln for ln in lbl_blk.lines if ln.page_num != label_page
            ]
            if merged_lines:
                label_only = [
                    ln for ln in lbl_blk.lines if ln.page_num == label_page
                ]
                cleaned = replace(lbl_blk, lines=label_only)
                blocks[lbl_gi] = cleaned
                collected[0] = (lbl_gi, cleaned)
                synth_bbox = (
                    min(ln.bbox[0] for ln in merged_lines),
                    min(ln.bbox[1] for ln in merged_lines),
                    max(ln.bbox[2] for ln in merged_lines),
                    max(ln.bbox[3] for ln in merged_lines),
                )
                synth = replace(
                    lbl_blk,
                    lines=merged_lines,
                    page_num=merged_lines[0].page_num,
                    bbox=synth_bbox,
                )
                collected.insert(1, (-1, synth))

        if len(collected) < 3:
            # Need at least label + header + one data row
            continue

        _log.debug(
            "Spec table label 'Table %d' on page %d: "
            "collected %d blocks (y=[%.0f, %.0f])",
            table_num, label_page, len(collected),
            label_y,
            max(cb.bbox[3] for _, cb in collected))

        # ----- Spatial clustering: identify column x-positions -----
        # Collect all line x-positions (excluding the label block itself)
        # and cluster them.
        x_counts: Counter[int] = Counter()
        for ci, (gi, cb) in enumerate(collected):
            if ci == 0:
                continue  # skip label
            for ln in cb.lines:
                if ln.text.strip():
                    x_counts[round(ln.bbox[0] / _SPEC_TABLE_X_BUCKET)] += 1

        if not x_counts:
            continue

        # Keep x-positions that appear in at least 2 lines (noise filter).
        stable_xs = sorted(
            xk * _SPEC_TABLE_X_BUCKET
            for xk, cnt in x_counts.items()
            if cnt >= 2
        )
        if len(stable_xs) < 2:
            # Fallback: use all observed positions
            stable_xs = sorted(
                xk * _SPEC_TABLE_X_BUCKET for xk in x_counts)

        # Merge close positions into logical columns.
        col_positions: list[float] = [stable_xs[0]]
        for xp in stable_xs[1:]:
            if xp - col_positions[-1] >= _SPEC_TABLE_X_MERGE:
                col_positions.append(xp)

        if len(col_positions) < 2:
            continue

        num_cols = len(col_positions)

        def assign_col(x: float) -> int:
            """Map an x-coordinate to the nearest column index."""
            best = 0
            best_d = abs(x - col_positions[0])
            for ci, cx in enumerate(col_positions):
                d = abs(x - cx)
                if d < best_d:
                    best_d = d
                    best = ci
            return best

        # ----- Build visual rows by y-band -----
        # Each y-band groups lines at similar vertical positions.
        # Lines are assigned to columns by their x-position.
        yband_cells: dict[int, list[list[Span]]] = {}  # yk -> cells[num_cols]

        for ci, (gi, cb) in enumerate(collected):
            if ci == 0:
                continue  # skip label
            for ln in cb.lines:
                if not ln.text.strip():
                    continue
                # Page-scoped y-band key: lines on different pages
                # never share a y-band, even if their y-coordinates
                # happen to be similar.
                yk = ln.page_num * 1000 + round(
                    ((ln.bbox[1] + ln.bbox[3]) / 2.0)
                    / _SPEC_TABLE_Y_BAND
                )
                if yk not in yband_cells:
                    yband_cells[yk] = [[] for _ in range(num_cols)]
                col_idx = assign_col(ln.bbox[0])
                yband_cells[yk][col_idx].extend(ln.spans)

        if not yband_cells:
            continue

        sorted_ybands = sorted(yband_cells)
        yband_index = {yk: i for i, yk in enumerate(sorted_ybands)}

        # ----- Remove repeated headers (cross-page) -----
        # PDFs repeat table headers at the top of each new page.
        # The first y-band with col-0 content is the real header.
        # Any later y-band whose col-0 text matches the header's
        # col-0 text is a repeat and is dropped, along with the
        # immediately following continuation y-band (e.g. the
        # "conditions" line wrapping from "assertion/note pre/post-").
        first_col0_yk = None
        header_col0_text = ""
        for yk in sorted_ybands:
            col0_t = "".join(
                s.text for s in yband_cells[yk][0]
            ).strip().lower()
            if col0_t:
                first_col0_yk = yk
                header_col0_text = col0_t
                break

        if header_col0_text:
            drop_yks: set[int] = set()
            for yk in sorted_ybands:
                if yk == first_col0_yk:
                    continue
                col0_t = "".join(
                    s.text for s in yband_cells[yk][0]
                ).strip().lower()
                if col0_t == header_col0_text:
                    drop_yks.add(yk)
                    # Also drop the next y-band if it is a header
                    # continuation (col 0 empty, short text in
                    # last column only).
                    idx_in_sorted = yband_index[yk]
                    if idx_in_sorted + 1 < len(sorted_ybands):
                        nxt = sorted_ybands[idx_in_sorted + 1]
                        nxt_col0 = "".join(
                            s.text for s in yband_cells[nxt][0]
                        ).strip()
                        if not nxt_col0:
                            nxt_all = "".join(
                                s.text
                                for c in yband_cells[nxt]
                                for s in c
                            ).strip()
                            if len(nxt_all.split()) <= 3:
                                drop_yks.add(nxt)

            if drop_yks:
                sorted_ybands = [
                    yk for yk in sorted_ybands if yk not in drop_yks
                ]
                _log.debug(
                    "Spec table: dropped %d repeated-header y-bands",
                    len(drop_yks))

        # ----- Merge visual rows into logical rows -----
        # A new logical row starts when column 0 (expression) has
        # content.  Continuation y-bands (col 0 empty) append to
        # the current row -- UNLESS a later y-band on the SAME page
        # has col-0 content: in that case, the continuation belongs
        # to the upcoming row (assertion text that starts above the
        # vertically-centred expression name in the PDF).
        #
        # Cross-page continuations (no col-0 on the same page ahead)
        # are still appended to the current row as before.
        logical_rows: list[list[list[Span]]] = []
        current_row: list[list[Span]] | None = None

        # Pre-compute next col-0 y-band for each position.
        _next_col0: dict[int, int | None] = {}
        _last_c0: int | None = None
        for yk in reversed(sorted_ybands):
            c0t = "".join(s.text for s in yband_cells[yk][0]).strip()
            if c0t:
                _last_c0 = yk
            _next_col0[yk] = _last_c0

        deferred: list[list[list[Span]]] = []

        def _append_continuation(
            row: list[list[Span]], cells: list[list[Span]]
        ) -> None:
            for ci in range(num_cols):
                if cells[ci]:
                    if row[ci] and any(
                        s.text.strip() for s in row[ci]
                    ):
                        row[ci].append(Span(text="\n"))
                    row[ci].extend(cells[ci])

        last_col0_page: int | None = None
        in_deferred_zone = False
        prev_y_max: float | None = None

        for yk in sorted_ybands:
            cells = yband_cells[yk]
            col0_text = "".join(s.text for s in cells[0]).strip()
            current_page = yk // 1000

            # Compute actual y-extent from span bboxes.
            y_min_cur: float | None = None
            y_max_cur: float | None = None
            for cell in cells:
                for s in cell:
                    if s.text.strip() and s.bbox != (0, 0, 0, 0):
                        if y_min_cur is None or s.bbox[1] < y_min_cur:
                            y_min_cur = s.bbox[1]
                        if y_max_cur is None or s.bbox[3] > y_max_cur:
                            y_max_cur = s.bbox[3]

            if col0_text:
                in_deferred_zone = False
                last_col0_page = current_page
                if current_row is not None:
                    logical_rows.append(current_row)
                # Prepend deferred continuation cells (assertion
                # text that sits above the expression name on the
                # same page) BEFORE the col-0 y-band's own cells.
                if deferred:
                    current_row = [[] for _ in range(num_cols)]
                    for d_cells in deferred:
                        _append_continuation(current_row, d_cells)
                    _append_continuation(current_row, cells)
                    deferred.clear()
                else:
                    current_row = [list(c) for c in cells]
            elif current_row is None:
                current_row = [list(c) for c in cells]
            else:
                # Detect row boundaries via y-gap analysis.
                # Within a table cell, consecutive lines are spaced
                # ~7-9 px apart.  Between cells (row boundaries),
                # the gap is ~18-19 px.  _SPEC_TABLE_Y_BAND (~15)
                # cleanly separates the two regimes.
                if not in_deferred_zone:
                    if current_page != last_col0_page:
                        nxt = _next_col0.get(yk)
                        if (nxt is not None and nxt != yk
                                and (nxt // 1000) == current_page):
                            in_deferred_zone = True
                    elif (prev_y_max is not None
                          and y_min_cur is not None
                          and y_min_cur - prev_y_max
                              > _SPEC_TABLE_Y_BAND):
                        nxt = _next_col0.get(yk)
                        if (nxt is not None and nxt != yk
                                and (nxt // 1000) == current_page):
                            in_deferred_zone = True

                if in_deferred_zone:
                    deferred.append([list(c) for c in cells])
                else:
                    _append_continuation(current_row, cells)

            if y_max_cur is not None:
                prev_y_max = y_max_cur

        if current_row is not None:
            logical_rows.append(current_row)

        # ----- Header-split guard -----
        # The col-0 merge absorbs all y-bands (including multi-line
        # data content in the assertion column) into the header row
        # until the first expression entry.  Split row 0 into a clean
        # header and a data spillover fragment.
        #
        # Strategy: for each cell in row 0, walk the \n-separated
        # segments.  Header label segments are short (<=5 words).
        # The split point is the FIRST segment that looks like data:
        # long (>5 words) or starts with a known data marker like
        # "Returns:", "Effects:", "Preconditions:".
        def _find_header_split(cell_spans: list[Span]) -> int | None:
            """Return span index where header ends and data begins."""
            nl_indices = [
                i for i, s in enumerate(cell_spans) if s.text == "\n"
            ]
            if not nl_indices:
                return None
            # Walk each \n and check if the post-\n text is data.
            for nl_idx in nl_indices:
                post_text = "".join(
                    s.text for s in cell_spans[nl_idx + 1:]
                ).strip()
                if not post_text:
                    continue
                first_segment = post_text.split("\n")[0].strip()
                if (len(first_segment.split()) > _SPEC_HEADER_MAX_WORDS
                        or _DATA_MARKERS_RE.match(first_segment)):
                    return nl_idx
            return None

        if logical_rows:
            row0 = logical_rows[0]
            # Find the best split point across all cells.
            split_indices: list[int | None] = [
                _find_header_split(cell) for cell in row0
            ]
            has_split = any(si is not None for si in split_indices)

            if has_split:
                header_row: list[list[Span]] = []
                spill_row: list[list[Span]] = []
                for ci, cell_spans in enumerate(row0):
                    si = split_indices[ci]
                    if si is not None:
                        header_row.append(list(cell_spans[:si]))
                        spill_row.append(list(cell_spans[si + 1:]))
                    else:
                        header_row.append(list(cell_spans))
                        spill_row.append([])

                logical_rows[0] = header_row
                has_spill = any(
                    any(s.text.strip() for s in c) for c in spill_row
                )
                if has_spill:
                    if len(logical_rows) > 1:
                        for ci in range(num_cols):
                            if spill_row[ci]:
                                if logical_rows[1][ci] and any(
                                    s.text.strip()
                                    for s in logical_rows[1][ci]
                                ):
                                    logical_rows[1][ci] = (
                                        spill_row[ci]
                                        + [Span(text="\n")]
                                        + logical_rows[1][ci]
                                    )
                                else:
                                    logical_rows[1][ci] = spill_row[ci]
                    else:
                        logical_rows.insert(1, spill_row)

        if len(logical_rows) < 2:
            continue

        # Cell density guard: a genuine multi-column table has content
        # in most cells.  A table label followed by prose paragraphs
        # produces rows where only column 0 is populated and the rest
        # are empty.  Require that at least 40% of cells are non-empty
        # (excluding the header row, which always has all cells filled).
        total_cells = 0
        non_empty_cells = 0
        for row in logical_rows:
            for cell in row:
                total_cells += 1
                if "".join(s.text for s in cell).strip():
                    non_empty_cells += 1
        cell_density = non_empty_cells / total_cells if total_cells else 0
        if cell_density < 0.40:
            _log.debug(
                "Spec table 'Table %d' rejected: cell density %.0f%% "
                "(%d/%d) below threshold",
                table_num, cell_density * 100,
                non_empty_cells, total_cells)
            continue

        # Header row check: the first logical row (header) should have
        # content in at least 2 columns.  If the header is incomplete,
        # this is likely not a real table.
        header_filled = sum(
            1 for cell in logical_rows[0]
            if "".join(s.text for s in cell).strip()
        )
        if header_filled < 2:
            _log.debug(
                "Spec table 'Table %d' rejected: header has only %d "
                "filled cells (need >= 2)", table_num, header_filled)
            continue

        # WG21 spec-header guard: the header row must contain at least
        # one column name characteristic of WG21 requirement tables.
        # This prevents the pass from consuming general "Table N"
        # labels in non-spec papers (e.g. side-by-side code figures).
        
        header_text = " ".join(
            "".join(s.text for s in cell).strip()
            for cell in logical_rows[0]
        )
        if not _SPEC_COL_NAMES_RE.search(header_text):
            _log.debug(
                "Spec table 'Table %d' rejected: header '%s' lacks "
                "WG21 spec column names", table_num,
                header_text[:80])
            continue

        # ----- Classify and emit -----
        kind_val, strategy_val, logical_rows = _classify_and_annotate(
            logical_rows)
        # Override: these are known spec tables regardless of signal heuristics.
        if kind_val == "false_positive":
            kind_val = TableKind.SPEC_TABLE.value
            strategy_val = TableStrategy.HTML_TABLE.value

        # Collect consumed block indices and lines.  The label block
        # (first in collected) is NOT consumed: it stays in remaining
        # blocks so the structure phase emits it as a paragraph caption
        # above the table HTML.
        consumed_indices: set[int] = set()
        all_lines = []
        for ci_idx, (gi, cb) in enumerate(collected):
            if ci_idx == 0:
                continue  # skip label block
            consumed_indices.add(gi)
            all_lines.extend(cb.lines)
        all_lines.sort(key=lambda ln: (ln.page_num, ln.bbox[1], ln.bbox[0]))

        # Consume stray column-header blocks that appear BEFORE the
        # label in MuPDF reading order (e.g. "expression", "return
        # type", "assertion/note pre/post-conditions" as separate
        # blocks above the Table label).  Without this, they leak
        # as plain-text paragraphs in the output.
        
        for j in range(label_gi - 1, max(label_gi - 6, -1), -1):
            if j < 0:
                break
            bk = blocks[j]
            if bk.page_num != label_page:
                break
            if _COL_HEADER_RE.match(bk.text.strip()):
                consumed_indices.add(j)

        used |= consumed_indices

        text = _render_table_text(logical_rows)

        table_sections.append(Section(
            kind=SectionKind.TABLE,
            text=text,
            confidence=Confidence.HIGH,
            lines=all_lines,
            page_num=label_page,
            columns=logical_rows,
            table_kind=kind_val,
            table_strategy=strategy_val,
            table_source="spec_label",
        ))
        _log.info(
            "Spec table 'Table %d' on page %d: %d rows x %d cols "
            "[kind=%s, strategy=%s, source=spec_label]",
            table_num, label_page, len(logical_rows), num_cols,
            kind_val, strategy_val)

    # Cross-page continuation header dedup: when a table spans pages,
    # MuPDF repeats the header row on each page.  If consecutive
    # spec-label sections share the same header text AND are on
    # adjacent pages (gap <= 1), strip the duplicate from the
    # continuation.  Tables separated by 2+ pages are independent.
    if len(table_sections) >= 2:
        for i in range(len(table_sections) - 1):
            t1 = table_sections[i]
            t2 = table_sections[i + 1]
            if not t1.columns or not t2.columns:
                continue
            if abs(t2.page_num - t1.page_num) > 1:
                continue
            if len(t1.columns[0]) != len(t2.columns[0]):
                continue
            h1 = tuple(
                "".join(s.text for s in cell).strip()
                for cell in t1.columns[0])
            h2 = tuple(
                "".join(s.text for s in cell).strip()
                for cell in t2.columns[0])
            if h1 == h2 and len(t2.columns) > 1:
                t2.columns = t2.columns[1:]
                t2.table_continuation = True
                t2.text = _render_table_text(t2.columns)
                _log.info(
                    "Stripped duplicate header from spec table "
                    "continuation on page %d", t2.page_num)

    return table_sections, used


def _filter_phantom_mupdf_tables(
    page_mupdf_tables: dict[int, list[dict]],
) -> dict[int, list[dict]]:
    """Remove find_tables entries that swallowed most of a page and contain huge cells."""
    if not page_mupdf_tables:
        return page_mupdf_tables
    filtered: dict[int, list[dict]] = {}
    for pg, tbls in page_mupdf_tables.items():
        kept = []
        for t in tbls:
            cov = t.get("page_coverage", 0.0)
            max_ch = t.get("max_cell_h", 0.0)
            tbl_h = t.get("tbl_h", 0.0)
            if cov > 0.80 and (max_ch > 150.0 or (tbl_h > 0 and max_ch / tbl_h > 0.20)):
                continue
            kept.append(t)
        if kept:
            filtered[pg] = kept
    return filtered


def _filter_overlapping_mupdf_tables(
    page_mupdf_tables: dict[int, list[dict]],
    existing_sections: list[Section],
) -> dict[int, list[dict]]:
    """Remove find_tables entries that overlap with already-detected tables."""
    if not existing_sections:
        return page_mupdf_tables

    existing_ranges: list[tuple[int, float, float]] = []
    for sec in existing_sections:
        if not sec.lines:
            continue
        # Group by the line's own page. A cross-page table's lines mix
        # bottom-of-page-N and top-of-page-N+1 y-coordinates, so a single
        # min/max would claim nearly the whole page and suppress unrelated
        # find_tables entries on it.
        per_page: dict[int, tuple[float, float]] = {}
        for ln in sec.lines:
            y0, y1 = per_page.get(ln.page_num, (ln.bbox[1], ln.bbox[3]))
            per_page[ln.page_num] = (min(y0, ln.bbox[1]),
                                     max(y1, ln.bbox[3]))
        for pg, (y_min, y_max) in per_page.items():
            existing_ranges.append((pg, y_min, y_max))

    result: dict[int, list[dict]] = {}
    for pg, tables in page_mupdf_tables.items():
        kept = []
        for tbl in tables:
            bbox = tbl["bbox"]
            overlaps = False
            for epg, ey0, ey1 in existing_ranges:
                if pg != epg:
                    continue
                overlap = min(bbox[3], ey1) - max(bbox[1], ey0)
                if overlap > 0:
                    overlaps = True
                    break
            if not overlaps:
                kept.append(tbl)
        if kept:
            result[pg] = kept
    return result


# ---------------------------------------------------------------------------
# Pass 1 inner-loop decision helpers (extracted for testability).
# Each function evaluates one decision branch and returns a _MatchResult
# or None (= this branch does not apply).
# ---------------------------------------------------------------------------


def _try_strict_match(
    blocks: list[Block],
    j: int,
    ref_cols: list[float],
) -> Optional[_MatchResult]:
    """Branch 1: next block's columns match ref_cols exactly."""
    next_cols = _block_column_positions(blocks[j])
    if next_cols is not None and _columns_match(ref_cols, next_cols):
        return _MatchResult(advance_to=j + 1)
    return None


def _try_relaxed_match(
    blocks: list[Block],
    j: int,
    ref_cols: list[float],
    table_blocks: list[Block],
) -> Optional[_MatchResult]:
    """Branch 2: same column count, close proximity. Adopts new positions."""
    next_cols = _block_column_positions(blocks[j])
    if (next_cols is not None
            and _columns_count_match(
                ref_cols, next_cols,
                table_blocks[-1].bbox[3], blocks[j].bbox[1],
                blocks[j].page_num == table_blocks[-1].page_num)):
        return _MatchResult(advance_to=j + 1, new_ref_cols=next_cols)
    return None


def _within_fragment_gap(block: Block, table_blocks: list[Block]) -> bool:
    """True when *block* starts close enough below the table's last block
    to be a fragment of its current row or the next one.

    Branches 3 and 4 claim "this block is a piece of the table being
    built". Beyond _PARTIAL_ROW_MAX_Y_GAP of whitespace that claim cannot
    hold: a column-aligned heading or a shorter header block sitting
    there opens the *next* table, and absorbing it chains two stacked
    tables into one (p4125r1 benchmark pages). A negative gap is a
    same-band right-hand fragment and passes.
    """
    return block.bbox[1] - table_blocks[-1].bbox[3] <= _PARTIAL_ROW_MAX_Y_GAP


def _try_subset_columns_absorb(
    blocks: list[Block],
    j: int,
    ref_cols: list[float],
    table_blocks: list[Block],
) -> Optional[_MatchResult]:
    """Branch 3: fewer columns, all align to ref_cols. Marks as partial."""
    next_cols = _block_column_positions(blocks[j])
    if (next_cols is not None
            and _is_subset_columns(next_cols, ref_cols)
            and not _block_is_monospace(blocks[j])
            and not _block_is_monospace(table_blocks[0])
            and blocks[j].page_num == table_blocks[-1].page_num
            and _within_fragment_gap(blocks[j], table_blocks)):
        return _MatchResult(
            advance_to=j + 1,
            absorbed_ids=frozenset({id(blocks[j])}),
            multi_orphan=True,
        )
    return None


def _try_wrapped_partial_row(
    blocks: list[Block],
    j: int,
    ref_cols: list[float],
    column_xs: frozenset[float],
    table_blocks: list[Block],
) -> Optional[_MatchResult]:
    """Branch 3b: multi-line fragment of a wrapped row in non-first columns.

    When two adjacent value columns sit closer than _COLUMN_GAP_THRESHOLD,
    MuPDF groups them into one block whose lines fall short of the gap, so
    _block_column_positions rejects it as non-columnar and Branches 1-3 all
    miss it.  Left unhandled, a single wrapped data row breaks the table in
    two and orphans its right-hand cells into prose.

    Recognize it as a partial row via the geometric column signal: every
    non-empty line must align (within _COLUMN_X_TOLERANCE) to a known
    column in both column_xs and ref_cols, none of them the left-margin
    label column (index 0, which would be prose), and the covered columns
    must be a strict subset of ref_cols.  The block must sit on the same
    page within _PARTIAL_ROW_MAX_Y_GAP of the previous row (a same-band
    right-hand fragment has a small negative gap, hence the abs()).
    """
    block = blocks[j]
    if len(table_blocks) < 2 or len(block.lines) < 2:
        return None
    if block.page_num != table_blocks[-1].page_num:
        return None
    if _block_column_positions(block) is not None:
        return None
    if _block_is_monospace(block) or _block_is_monospace(table_blocks[0]):
        return None
    if abs(block.bbox[1] - table_blocks[-1].bbox[3]) > _PARTIAL_ROW_MAX_Y_GAP:
        return None

    covered: set[int] = set()
    for line in block.lines:
        if not line.spans or not line.text.strip():
            continue
        x0 = line.bbox[0]
        # Both signals are required, not redundant: column_xs is a column
        # that recurs across 2+ rows, a stricter check than ref_cols (the
        # single seed block's positions).
        if not any(abs(x0 - cx) <= _COLUMN_X_TOLERANCE for cx in column_xs):
            return None
        ci = min(range(len(ref_cols)), key=lambda c: abs(x0 - ref_cols[c]))
        if ci == 0 or abs(x0 - ref_cols[ci]) > _COLUMN_X_TOLERANCE:
            return None
        covered.add(ci)

    if not 0 < len(covered) < len(ref_cols):
        return None
    return _MatchResult(
        advance_to=j + 1,
        absorbed_ids=frozenset({id(block)}),
        multi_orphan=True,
    )


def _try_single_orphan(
    blocks: list[Block],
    j: int,
    ref_cols: list[float],
    column_xs: frozenset[float],
) -> Optional[_MatchResult]:
    """Sub-branch 4a: orphan at j, next block (j+1) is a full column match.

    Precondition: j + 1 < len(blocks) (caller must verify).
    """
    peek_cols = _block_column_positions(blocks[j + 1])
    if not (peek_cols is not None
            and blocks[j + 1].page_num == blocks[j].page_num
            and _columns_match(ref_cols, peek_cols)):
        return None
    # An orphan aligned to column 1+ is the wrapped tail of the previous
    # row's cell (top-aligned cells put a row's first line on the col-0
    # line, so it cannot be the next row's first line). Marking it
    # partial routes it through the from_partial path of
    # _build_rows_sequential, which maps it by nearest column and merges
    # it backward. Without the mark the line lands in column 0 as a row
    # of its own and Pass B glues it forward (p4096r0 §5.2 "Age" row).
    # The font does not matter: a monospace tail is still a cell tail
    # (p0957r8 p.28 `HasNothrowDestructor`, p4016r0 p.27 header
    # `Proposed canonical_reduce`); the column position is the signal.
    absorbed = set()
    if blocks[j].lines:
        orphan_x0 = blocks[j].lines[0].bbox[0]
        orphan_spans = [
            s for s in blocks[j].lines[0].spans
            if s.text.strip()]
        if (orphan_spans
                and any(abs(orphan_x0 - ref_cols[ci])
                        <= _COLUMN_X_TOLERANCE
                        for ci in range(1, len(ref_cols)))):
            absorbed.add(id(blocks[j]))
    return _MatchResult(
        advance_to=j + 1,
        absorbed_ids=frozenset(absorbed),
    )


def _scan_for_confirmer(
    blocks: list[Block],
    j: int,
    ref_cols: list[float],
    column_xs: frozenset[float],
) -> tuple[int, int, bool]:
    """Scan ahead past orphans/subsets to find a full-column confirmer.

    Returns (scan_pos, absorbed_end, found_full).
    """
    table_page = blocks[j].page_num
    max_scan = 3 * len(ref_cols)
    scan = j
    absorbed_end = j
    found_full = False
    while (scan < len(blocks)
           and blocks[scan].page_num == table_page
           and scan - j < max_scan):
        if _is_column_aligned_orphan(blocks[scan], column_xs):
            scan += 1
            continue
        sc = _block_column_positions(blocks[scan])
        if sc is not None and _columns_match(ref_cols, sc):
            absorbed_end = scan
            found_full = True
            break
        if sc is not None and _is_subset_columns(sc, ref_cols):
            scan += 1
            continue
        break
    return scan, absorbed_end, found_full


def _check_collective_coverage(
    blocks: list[Block],
    j: int,
    scan: int,
    ref_cols: list[float],
    column_xs: frozenset[float],
    table_blocks: list[Block],
    partial_absorbed: set[int],
) -> Optional[_MatchResult]:
    """Fix B: check if orphan blocks collectively cover all header columns.

    Extends scan past max_scan limit since borderless tables have each
    cell as a separate block.  Returns _MatchResult if coverage passes.
    """
    if len(ref_cols) < 3 or scan <= j:
        return None

    table_page = blocks[j].page_num
    while (scan < len(blocks)
           and blocks[scan].page_num == table_page
           and (_is_column_aligned_orphan(blocks[scan], column_xs)
                or (_block_column_positions(blocks[scan]) is not None
                    and _is_subset_columns(_block_column_positions(blocks[scan]), ref_cols)))):
        scan += 1

    col_ybands: dict[int, set[int]] = {}
    orphan_ybs: set[int] = set()
    for k in range(j, scan):
        b = blocks[k]
        for oln in b.lines:
            if not oln.spans or not oln.text.strip():
                continue
            x0 = oln.bbox[0]
            best_ci = min(
                range(len(ref_cols)),
                key=lambda ci: abs(x0 - ref_cols[ci]))
            if abs(x0 - ref_cols[best_ci]) <= _COLUMN_X_TOLERANCE:
                ym = (oln.bbox[1] + oln.bbox[3]) / 2.0
                yk = round(ym / _Y_BAND_HEIGHT)
                col_ybands.setdefault(best_ci, set()).add(yk)
                orphan_ybs.add(yk)

    # Include columns from subset blocks already absorbed.
    for tb in table_blocks:
        if id(tb) not in partial_absorbed:
            continue
        tb_cp = _block_column_positions(tb)
        if tb_cp is None or not _is_subset_columns(tb_cp, ref_cols):
            continue
        for tln in tb.lines:
            if not tln.spans or not tln.text.strip():
                continue
            tx0 = tln.bbox[0]
            tci = min(
                range(len(ref_cols)),
                key=lambda ci: abs(tx0 - ref_cols[ci]))
            if abs(tx0 - ref_cols[tci]) <= _COLUMN_X_TOLERANCE:
                tym = (tln.bbox[1] + tln.bbox[3]) / 2.0
                yk = round(tym / _Y_BAND_HEIGHT)
                col_ybands.setdefault(tci, set()).add(yk)
                orphan_ybs.add(yk)

    mc_bands = sum(
        1 for yk in orphan_ybs
        if sum(1 for ci, ybs in col_ybands.items() if yk in ybs) >= 2)

    if len(col_ybands) >= len(ref_cols) and mc_bands >= 1:
        absorbed_ids = frozenset(id(blocks[k]) for k in range(j, scan))
        return _MatchResult(
            advance_to=scan,
            absorbed_ids=absorbed_ids,
            multi_orphan=True,
        )
    return None


def _try_orphan_lookahead(
    blocks: list[Block],
    j: int,
    ref_cols: list[float],
    column_xs: frozenset[float],
    table_blocks: list[Block],
    partial_absorbed: set[int],
) -> Optional[_MatchResult]:
    """Branch 4: single-line block aligned to a column, lookahead to confirm."""
    eff_col_xs = frozenset(column_xs | set(ref_cols))
    if not (_is_column_aligned_orphan(blocks[j], eff_col_xs)
            and j + 1 < len(blocks)
            and blocks[j].page_num == table_blocks[-1].page_num
            and _within_fragment_gap(blocks[j], table_blocks)):
        return None

    # 4a: Single-orphan case
    result = _try_single_orphan(blocks, j, ref_cols, eff_col_xs)
    if result is not None:
        return result

    # 4b: Multi-step lookahead
    peek_cols = _block_column_positions(blocks[j + 1])
    if not (len(table_blocks) >= 1
            and ((peek_cols is not None
                  and blocks[j + 1].page_num == blocks[j].page_num
                  and _is_subset_columns(peek_cols, ref_cols))
                 or (_is_column_aligned_orphan(blocks[j + 1], eff_col_xs)
                     and blocks[j + 1].page_num == blocks[j].page_num))
            and (len(table_blocks) >= 2
                 or not _block_is_monospace(blocks[j]))):
        return None

    scan, absorbed_end, found_full = _scan_for_confirmer(
        blocks, j, ref_cols, eff_col_xs)

    if found_full:
        absorbed_ids = frozenset(id(blocks[k]) for k in range(j, absorbed_end))
        return _MatchResult(
            advance_to=absorbed_end,
            absorbed_ids=absorbed_ids,
            multi_orphan=True,
        )

    # Fix B: Collective orphan coverage
    return _check_collective_coverage(
        blocks, j, scan, ref_cols, eff_col_xs,
        table_blocks, partial_absorbed)


def _block_on_one_column(block: Block, ref_cols: list[float]) -> Optional[int]:
    """Index of the reference column every line of `block` starts on, or None."""
    if not block.lines:
        return None
    ci = _nearest_column(block.lines[0].bbox[0], ref_cols)
    if any(abs(ln.bbox[0] - ref_cols[ci]) > _COLUMN_X_TOLERANCE
           for ln in block.lines):
        return None
    return ci


def _try_split_row(
    blocks: list[Block],
    j: int,
    ref_cols: list[float],
    table_blocks: list[Block],
) -> Optional[_MatchResult]:
    """Branch 4d: one row delivered as two blocks, label and cell.

    In a two-column table, a single-line block on column 0 beside a
    multi-line block whose lines all start on column 1, with the label
    vertically inside the cell's band (the label is centred on the
    taller cell), is one row (p4016r0 N.14 "Determinism" beside its
    three-line guarantee). Neither block is columnar on its own and the
    cell block is too wide for the orphan branches. The label block owns
    the row; the cell block is returned in ``absorbed_ids`` so the
    from_partial path of _build_rows_sequential merges it into that row
    by nearest column. The caller appends the label block first.

    The guards (two columns, multi-line cell, label inside the cell's
    band) are load-bearing: with single-line cells or wider tables the
    pair is a fragment, and a Pass 1 claim on a fragment hides the
    find_tables() grid from Pass 5 (p4007r0 §7, p4098r1 §2.6, p2583r0
    §6 all shattered when the guards were missing).

    Precondition: j + 1 < len(blocks).
    """
    if len(ref_cols) != 2:
        return None
    a, b = blocks[j], blocks[j + 1]
    if a.page_num != b.page_num or a.page_num != table_blocks[-1].page_num:
        return None
    if not _within_fragment_gap(a, table_blocks):
        return None
    for label, cell in ((a, b), (b, a)):
        if len(label.lines) != 1 or not label.lines[0].text.strip():
            continue
        if len(cell.lines) < 2 or not any(ln.text.strip() for ln in cell.lines):
            continue
        if abs(label.lines[0].bbox[0] - ref_cols[0]) > _COLUMN_X_TOLERANCE:
            continue
        if _block_on_one_column(cell, ref_cols) != 1:
            continue
        if (cell.bbox[1] > label.bbox[1] + _TABLE_Y_OVERLAP_MARGIN
                or cell.bbox[3] < label.bbox[3] - _TABLE_Y_OVERLAP_MARGIN):
            continue  # label not inside the cell's row band
        return _MatchResult(
            advance_to=j + 2,
            absorbed_ids=frozenset({id(cell)}),
        )
    return None


def _try_partial_row(
    blocks: list[Block],
    j: int,
    ref_cols: list[float],
    column_xs: frozenset[float],
    table_blocks: list[Block],
) -> Optional[_MatchResult]:
    """Branch 5: fewer columns but all x-positions match known columns."""
    if not (len(table_blocks) >= 2
            and _is_partial_row(blocks[j], ref_cols,
                                table_blocks[-1].bbox[3],
                                blocks[j].page_num
                                == table_blocks[-1].page_num)):
        return None

    # Absorb trailing orphans after the partial row.
    end = j + 1
    absorbed = set()
    while (end < len(blocks)
           and _is_column_aligned_orphan(blocks[end], column_xs)
           and blocks[end].page_num == table_blocks[-1].page_num):
        absorbed.add(id(blocks[end]))
        end += 1
    return _MatchResult(
        advance_to=end,
        absorbed_ids=frozenset(absorbed),
    )


# Per-column alignment tolerance for a cross-page continuation row. Wider
# than _COLUMN_X_TOLERANCE because centered cells re-centre on the new page
# against different text widths, but far tighter than the column pitch, so
# an unrelated table with the same column count still fails to match.
_CROSS_PAGE_COL_X_TOLERANCE = 30.0


def _try_cross_page_continuation(
    blocks: list[Block],
    j: int,
    ref_cols: list[float],
    table_blocks: list[Block],
) -> Optional[_MatchResult]:
    """Branch 6: the table runs off one page and resumes on the next.

    Fires only when the table is already established, its last row sits in
    the bottom band of its page, and the candidate is a columnar block with
    the same column count in the top band of the very next page. Only
    whitespace-only spacer blocks (left behind by header/footer stripping)
    may sit between the two; any real block ends the table as before.

    Reuses the page-band constants of the MuPDF-native pass: "bottom of a
    page" and "top of a page" mean the same thing in both.
    """
    if len(table_blocks) < _MIN_TABLE_ROWS:
        return None
    last = table_blocks[-1]
    if last.bbox[3] < _CROSS_PAGE_BOTTOM_Y:
        return None

    k = j
    while k < len(blocks) and not blocks[k].text.strip():
        k += 1
    if k >= len(blocks):
        return None

    cand = blocks[k]
    if (cand.page_num != last.page_num + 1
            or cand.bbox[1] > _CROSS_PAGE_TOP_Y):
        return None

    cand_cols = _block_column_positions(cand)
    if cand_cols is None or len(cand_cols) != len(ref_cols):
        return None
    if any(abs(a - b) > _CROSS_PAGE_COL_X_TOLERANCE
           for a, b in zip(ref_cols, cand_cols)):
        return None

    return _MatchResult(advance_to=k + 1, new_ref_cols=cand_cols)


def _build_rows_ybanded(
    table_blocks: list[Block],
    ref_cols: list[float],
    num_cols: int,
) -> tuple[list[list[list]], list[Line]]:
    """Build rows using y-band grouping for multi-orphan tables.

    Returns (rows, all_lines).
    """
    all_lines: list[Line] = []
    tagged: list[tuple[float, int, Line]] = []
    for blk in table_blocks:
        for line in blk.lines:
            all_lines.append(line)
            y_mid = (line.bbox[1] + line.bbox[3]) / 2
            best_col = min(
                range(num_cols),
                key=lambda ci: abs(line.bbox[0] - ref_cols[ci]),
            )
            tagged.append((y_mid, best_col, line))
    tagged.sort(key=lambda t: t[0])

    # Adaptive band gap from sorted y-midpoints.
    y_mids = sorted({t[0] for t in tagged})
    gaps = [y_mids[i + 1] - y_mids[i] for i in range(len(y_mids) - 1)]
    real_gaps = sorted({g for g in gaps if g > 1.0})
    if len(real_gaps) >= 3:
        max_jump = 0.0
        split_idx = 0
        for gi in range(len(real_gaps) - 1):
            jump = real_gaps[gi + 1] - real_gaps[gi]
            if jump > max_jump:
                max_jump = jump
                split_idx = gi
        band_gap = (real_gaps[split_idx] + real_gaps[split_idx + 1]) / 2
    elif len(real_gaps) >= 2:
        band_gap = (real_gaps[0] + real_gaps[1]) / 2
    else:
        band_gap = _SPEC_TABLE_Y_BAND

    bands: list[list[tuple[int, Line]]] = [[]]
    prev_y = tagged[0][0] if tagged else 0.0
    for y_mid, col_idx, line in tagged:
        if bands[-1] and y_mid - prev_y > band_gap:
            bands.append([])
        bands[-1].append((col_idx, line))
        prev_y = y_mid

    rows: list[list[list]] = []
    for band in bands:
        row: list[list] = [[] for _ in range(num_cols)]
        for col_idx, line in band:
            if row[col_idx] and line.spans:
                row[col_idx].append(Span(text=" "))
            row[col_idx].extend(line.spans)
        rows.append(row)

    # Multi-line cell merge: bands with col-0 filled are "row anchors";
    # bands with col-0 empty are continuations merged by y-distance.
    if len(rows) > 1 and len(bands) > 1:
        band_ymids = [
            sum(ln.bbox[1] for _, ln in band) / len(band)
            if band else 0.0
            for band in bands]
        anchor_idxs = []
        non_anchor_idxs = []
        for ri, row in enumerate(rows):
            col0_text = "".join(s.text for s in row[0]).strip()
            if col0_text:
                anchor_idxs.append(ri)
            else:
                any_other = any(
                    "".join(s.text for s in row[ci]).strip()
                    for ci in range(1, num_cols))
                if any_other:
                    non_anchor_idxs.append(ri)
                else:
                    anchor_idxs.append(ri)
        if non_anchor_idxs and anchor_idxs:
            merge_map: dict[int, int] = {}
            for ni in non_anchor_idxs:
                ny = band_ymids[ni]
                non_empty_cols = {
                    ci for ci in range(1, num_cols) if rows[ni][ci]
                }
                candidates = [
                    ai for ai in anchor_idxs
                    if (ai > 0 or not all(rows[0][ci] for ci in range(num_cols)))
                ]
                if not candidates:
                    candidates = anchor_idxs
                empty_col_candidates = [
                    ai for ai in candidates
                    if all(not rows[ai][ci] for ci in non_empty_cols)
                ]
                pool = empty_col_candidates if empty_col_candidates else candidates
                best_ai = min(pool, key=lambda ai: abs(band_ymids[ai] - ny))
                merge_map[ni] = best_ai
            merged_rows: dict[int, list[list]] = {}
            for ri, row in enumerate(rows):
                target_ri = merge_map.get(ri, ri)
                if target_ri not in merged_rows:
                    merged_rows[target_ri] = [
                        list(cell) for cell in rows[target_ri]]
                if ri != target_ri:
                    target = merged_rows[target_ri]
                    prepend = (band_ymids[ri] < band_ymids[target_ri])
                    for ci in range(num_cols):
                        ct = "".join(s.text for s in row[ci]).strip()
                        if ct:
                            if prepend:
                                ins = list(row[ci])
                                if target[ci]:
                                    ins.append(Span(text=" "))
                                ins.extend(target[ci])
                                target[ci] = ins
                            else:
                                if target[ci]:
                                    target[ci].append(Span(text=" "))
                                target[ci].extend(row[ci])
            rows = [merged_rows[ai] for ai in sorted(merged_rows.keys())]

    return rows, all_lines


def _build_rows_sequential(
    table_blocks: list[Block],
    ref_cols: list[float],
    num_cols: int,
    partial_absorbed: set[int],
) -> tuple[list[list[list]], list[Line]]:
    """Build rows using sequential block-to-row mapping.

    Returns (rows, all_lines).
    """
    all_lines: list[Line] = []
    rows: list[list[list]] = []
    continuation_row_indices: set[int] = set()

    for blk in table_blocks:
        from_partial = id(blk) in partial_absorbed
        blk_cols = _block_column_positions(blk)
        target_cols = blk_cols if (blk_cols is not None and len(blk_cols) == num_cols) else ref_cols

        if from_partial:
            row: list[list] = [[] for _ in range(num_cols)]
            for line in blk.lines:
                all_lines.append(line)
                best_col = min(
                    range(num_cols),
                    key=lambda ci: abs(line.bbox[0] - ref_cols[ci]),
                )
                if row[best_col] and line.spans:
                    row[best_col].append(Span(text=" "))
                row[best_col].extend(line.spans)
            continuation_row_indices.add(len(rows))
        else:
            row = [[] for _ in range(num_cols)]
            for line in blk.lines:
                all_lines.append(line)
                line_x = line.bbox[0]
                best_col = min(
                    range(num_cols),
                    key=lambda ci: abs(line_x - target_cols[ci]),
                )
                if row[best_col] and line.spans:
                    row[best_col].append(Span(text="\n"))
                row[best_col].extend(line.spans)
        rows.append(row)

    if continuation_row_indices:
        tmp: list[list[list]] = []
        for ri, row in enumerate(rows):
            if ri in continuation_row_indices and tmp:
                target = tmp[-1]
                for ci in range(num_cols):
                    if not row[ci]:
                        continue
                    if target[ci]:
                        target[ci].append(Span(text=" "))
                    target[ci].extend(row[ci])
            else:
                tmp.append(row)
        rows = tmp

    return rows, all_lines


def _drop_separator_rows(ts: Section) -> None:
    """Remove body rows whose every cell is a run of dashes.

    Markdown-authored papers rendered to PDF carry the ``|---|---|``
    separator as a table row of "-" cells (p1068r11 poll tables). Once
    the header cluster above the drawn table is absorbed, that row is
    a body row holding no data. The table's line list keeps the dash
    lines so they stay excluded from prose."""
    body = ts.columns[1:]
    kept = [
        row for row in body
        if not (row and all(
            _SEPARATOR_CELL_RE.match("".join(s.text for s in c).strip())
            for c in row))]
    if len(kept) != len(body):
        ts.columns[1:] = kept
        ts.text = _render_table_text(ts.columns)


def _same_baseline_header_columns(
    block: Block, body: Block,
) -> list[float] | None:
    """Span x-starts of a one-row header, or None.

    ``_block_column_positions`` sees only line starts, so ``Pass`` and
    ``Comment`` on one line collapse into a single column. A header is
    one visual row when every ink line ends on the same baseline. Span
    starts more than ``_COLUMN_X_TOLERANCE`` apart are cells. At least
    one gap must still clear ``_COLUMN_GAP_THRESHOLD``, so a slightly
    indented wrap is not a header.
    """
    ink = [ln for ln in block.lines if ln.text.strip()]
    if len(ink) < 2:
        return None
    if _CODE_DECL_PREFIX_RE.match(ink[0].text):
        return None
    bottoms = [ln.bbox[3] for ln in ink]
    if max(bottoms) - min(bottoms) > _TABLE_Y_OVERLAP_MARGIN:
        return None
    header_spans = sorted(
        (sp.bbox[0], line_idx, sp.bbox[2])
        for line_idx, ln in enumerate(ink)
        for sp in ln.spans
        if sp.text.strip()
    )
    if len(header_spans) < 2:
        return None
    clusters: list[list[tuple[float, int, float]]] = [[header_spans[0]]]
    for item in header_spans[1:]:
        if item[0] - clusters[-1][-1][0] <= _COLUMN_X_TOLERANCE:
            clusters[-1].append(item)
        else:
            clusters.append([item])
    representatives = [cluster[0] for cluster in clusters]
    cols = [item[0] for item in representatives]
    if len(cols) < 2:
        return None
    if max(b - a for a, b in zip(cols, cols[1:])) < _COLUMN_GAP_THRESHOLD:
        return None
    # A style change can split one header cell into several spans whose
    # starts look like extra columns. Keep only candidates independently
    # supported by body line starts; assign each line to its nearest
    # candidate so one body column cannot validate two header fragments.
    support = [0] * len(cols)
    for line in body.lines:
        if not line.text.strip():
            continue
        nearest = min(range(len(cols)), key=lambda idx: abs(line.bbox[0] - cols[idx]))
        if abs(line.bbox[0] - cols[nearest]) <= _MULTIROW_BODY_X_SUPPORT_TOL:
            support[nearest] += 1
    kept: list[float] = []
    for idx, (col, count) in enumerate(zip(cols, support)):
        adjacent_empty_header = (
            idx > 0
            and representatives[idx][1] == representatives[idx - 1][1]
            and _SPAN_WORD_GAP
                < representatives[idx][0] - representatives[idx - 1][2]
                <= _MULTIROW_ADJACENT_HEADER_GAP
        )
        if count >= 1 or adjacent_empty_header:
            kept.append(col)
    cols = kept
    if len(cols) < 2:
        return None
    return cols


def _column_at_or_before(x: float, cols: list[float]) -> int:
    """Rightmost column whose start is at or just left of ``x``.

    Nearest-column assignment pulls the tail of a long left cell
    (``iptr)`` at x=468) into the Pass column 28pt away. A span belongs
    to the last column that has already started.
    """
    chosen = 0
    for i, col in enumerate(cols):
        if col <= x + _COLUMN_X_TOLERANCE:
            chosen = i
        else:
            break
    return chosen


def _append_cell_span(cell: list, sp: Span) -> None:
    if cell and sp.bbox[0] - cell[-1].bbox[2] > _SPAN_WORD_GAP:
        cell.append(Span(text=" "))
    cell.append(sp)


def _row_from_lines(lines: list[Line], cols: list[float]) -> list[list]:
    row: list[list] = [[] for _ in cols]
    for ln in lines:
        for sp in ln.spans:
            if not sp.text.strip():
                continue
            _append_cell_span(row[_column_at_or_before(sp.bbox[0], cols)], sp)
    return row


class _MultirowBodyResult(NamedTuple):
    rows: list[list[list]]
    used_lines: list[Line]
    trailing_lines: list[Line]


def _unpack_multirow_body(
    block: Block, cols: list[float],
) -> _MultirowBodyResult | None:
    """Rows of a body block whose cells are sibling lines, or None.

    ``_block_column_positions`` returns None as soon as a line's x goes
    back to column 0, which is every data row after the first. Group
    lines that share a baseline, assign spans to ``cols``, and accept
    the block only when several of those rows actually use a later column.
    """
    ink = [ln for ln in block.lines if ln.text.strip()]
    if len(ink) < 2:
        return None
    if abs(block.bbox[0] - cols[0]) > _COLUMN_X_TOLERANCE:
        return None
    ink.sort(key=lambda ln: (ln.bbox[1], ln.bbox[0]))
    bands: list[list[Line]] = [[ink[0]]]
    for ln in ink[1:]:
        if ln.bbox[1] - bands[-1][0].bbox[1] > _MULTIROW_SAME_ROW_Y:
            bands.append([ln])
        else:
            bands[-1].append(ln)
    if len(bands) < _MIN_TABLE_ROWS:
        return None
    rows: list[list[list]] = []
    used_lines: list[Line] = []
    trailing_lines: list[Line] = []
    used_other = 0
    for band_idx, band in enumerate(bands):
        row = _row_from_lines(band, cols)
        if not any(sp.text.strip() for sp in row[0]):
            return None
        has_other = any(row[ci] for ci in range(1, len(cols)))
        if not has_other:
            if used_other < _MIN_TABLE_ROWS:
                return None
            trailing_lines = [
                ln for rest in bands[band_idx:] for ln in rest
            ]
            break
        used_other += 1
        rows.append(row)
        used_lines.extend(band)
    if used_other < _MIN_TABLE_ROWS:
        return None
    return _MultirowBodyResult(rows, used_lines, trailing_lines)


def _last_column_is_page_numbers(rows: list[list[list]]) -> bool:
    """True when the last column is only bare page numbers."""
    cells: list[str] = []
    for row in rows:
        if not row:
            continue
        text = "".join(sp.text for sp in row[-1]).strip()
        if text:
            cells.append(text)
    if len(cells) < _MIN_TABLE_ROWS:
        return False
    return all(_PAGE_NUMBER_CELL_RE.fullmatch(cell) for cell in cells)


def _same_page_contents_label(blocks: list[Block], page_num: int) -> bool:
    for block in blocks:
        if block.page_num != page_num:
            continue
        if any(is_toc_label(ln.text) for ln in block.lines):
            return True
    return False


def _is_labeled_contents_table(
    rows: list[list[list]], blocks: list[Block], page_num: int,
) -> bool:
    """A Contents list with no dot leaders still has two aligned columns.

    The right column is a bare page number. That is not a data table
    when a Contents label is on the same page and the run is long enough
    to be a contents list. A numeric column without that label stays a
    table.
    """
    if not rows or len(rows[0]) != 2 or len(rows) < MIN_TOC_RUN:
        return False
    if not _last_column_is_page_numbers(rows):
        return False
    return _same_page_contents_label(blocks, page_num)


def detect_tables(
    blocks: list[Block],
    *,
    page_mupdf_tables: dict[int, list[dict]] | None = None,
    two_column_pages: frozenset[int] = frozenset(),
) -> tuple[list[Section], list[Block]]:
    """Detect table regions from MuPDF block structure.

    Returns (table_sections, remaining_blocks).
    Table sections have kind=TABLE with high confidence.
    Remaining blocks are the non-table blocks for normal processing.
    """
    column_xs = _find_column_xs(blocks)  # geometric second signal

    filtered_mupdf_tables = _filter_phantom_mupdf_tables(page_mupdf_tables or {})

    # Pages whose find_tables() results carry a rotation matrix: the
    # upright-geometry passes (1, 3, 4) stand down there and Pass 5
    # handles those pages rotation-aware.
    rotated_pages = frozenset(
        pg for pg, tbls in filtered_mupdf_tables.items()
        if any(t.get("rot") is not None for t in tbls)
    )

    table_sections: list[Section] = []

    # Pass 0: label-anchored spec tables ("Table N - XYZ requirements").
    # Runs FIRST because the label regex is highly distinctive (near-zero
    # false positives) and later passes (especially side-by-side in Pass 2)
    # consume the scattered table-cell blocks before this pass can see them.
    spec_tables, spec_used = _detect_spec_tables_by_label(blocks)
    if spec_tables:
        table_sections.extend(spec_tables)
    # Remove consumed blocks; renumber for subsequent passes.
    remaining_after_spec: list[Block] = [
        b for idx, b in enumerate(blocks) if idx not in spec_used
    ]

    blocks = remaining_after_spec  # Post-spec-label blocks

    # Pre-pass: atomized-header side-by-side tables only.  Must run
    # before Pass 1 (horizontal rows) because Pass 1 consumes single-
    # block columnar rows as independent mini-tables, stealing body
    # blocks that belong to the larger atomized-header table.
    sbs_pre_tables, sbs_pre_used = _detect_side_by_side_tables(
        blocks, atomized_only=True,
        page_mupdf_tables=filtered_mupdf_tables)
    if sbs_pre_tables:
        table_sections.extend(sbs_pre_tables)
        blocks = [b for idx, b in enumerate(blocks)
                  if idx not in sbs_pre_used]

    # Pass 1: horizontal-row tables
    remaining: list[Block] = []
    i = 0

    while i < len(blocks):
        cols = _block_column_positions(blocks[i])
        if cols is None:
            remaining.append(blocks[i])
            i += 1
            continue

        span_cols = (
            _same_baseline_header_columns(blocks[i], blocks[i + 1])
            if i + 1 < len(blocks) else None
        )
        if (span_cols is not None
                and len(span_cols) >= len(cols)
                and i + 1 < len(blocks)
                and blocks[i].page_num not in rotated_pages
                and blocks[i + 1].page_num == blocks[i].page_num
                and blocks[i + 1].bbox[1] - blocks[i].bbox[3]
                    >= -_TABLE_Y_OVERLAP_MARGIN
                and blocks[i + 1].bbox[1] - blocks[i].bbox[3]
                    <= _PARTIAL_ROW_MAX_Y_GAP):
            body_result = _unpack_multirow_body(blocks[i + 1], span_cols)
            if body_result is not None:
                body_rows = body_result.rows
                rows = [
                    _row_from_lines(blocks[i].lines, span_cols),
                    *body_rows,
                ]
                header0 = "".join(sp.text for sp in rows[0][0]).strip()
                # A contents list whose last column is only page numbers is
                # refused below. A section heading cut into columns
                # ("4.1 exploration | of | potential") is refused here.
                if (_SECTION_HEADING_CELL_RE.match(header0)
                        or _last_column_is_page_numbers(rows)
                        or _is_labeled_contents_table(
                            rows, blocks, blocks[i].page_num)):
                    body_result = None
                else:
                    kind_val, strategy_val, rows = _classify_and_annotate(rows)
                    if kind_val not in (
                            TableKind.FALSE_POSITIVE.value,
                            TableKind.BIBLIOGRAPHY.value):
                        all_lines = [
                            *blocks[i].lines,
                            *body_result.used_lines,
                        ]
                        if body_result.trailing_lines:
                            remaining.append(Block(
                                lines=body_result.trailing_lines,
                                bbox=compute_bbox([
                                    ln.bbox for ln
                                    in body_result.trailing_lines
                                ]),
                                page_num=blocks[i + 1].page_num,
                            ))
                        table_sections.append(Section(
                            kind=SectionKind.TABLE,
                            text=_render_table_text(rows),
                            confidence=Confidence.HIGH,
                            lines=all_lines,
                            page_num=blocks[i].page_num,
                            columns=rows,
                            table_kind=kind_val,
                            table_strategy=strategy_val,
                            table_source="multirow_body",
                        ))
                        _log.debug(
                            "Table detected: %d rows x %d cols on page %d "
                            "(multirow body)",
                            len(rows), len(span_cols), blocks[i].page_num)
                        i += 2
                        continue

        table_blocks = [blocks[i]]
        # Track the "reference" column positions used for strict matching.
        # When a relaxed (column-count) match fires, adopt the new block's
        # positions as reference so subsequent data rows can strict-match
        # against each other.
        ref_cols = cols
        partial_absorbed: set[int] = set()  # id(block) for partial-row path
        multi_orphan_used = False
        j = i + 1
        while j < len(blocks):
            # Branch 1: strict column match
            result = _try_strict_match(blocks, j, ref_cols)
            if result is not None:
                table_blocks.append(blocks[j])
                j = result.advance_to
                continue

            # Branch 2: relaxed match (same count, close proximity)
            result = _try_relaxed_match(blocks, j, ref_cols, table_blocks)
            if result is not None:
                table_blocks.append(blocks[j])
                # The relaxed match always carries new columns; the `or`
                # only tells the type checker so (new_ref_cols is Optional).
                ref_cols = result.new_ref_cols or ref_cols
                j = result.advance_to
                continue

            # Branch 3: subset columns (partial absorption)
            result = _try_subset_columns_absorb(
                blocks, j, ref_cols, table_blocks)
            if result is not None:
                table_blocks.append(blocks[j])
                partial_absorbed.update(result.absorbed_ids)
                multi_orphan_used = True
                j = result.advance_to
                continue

            # Branch 3b: wrapped partial-row fragment (narrow-gap cells that
            # _block_column_positions rejects, but aligned to known columns)
            result = _try_wrapped_partial_row(
                blocks, j, ref_cols, column_xs, table_blocks)
            if result is not None:
                table_blocks.append(blocks[j])
                partial_absorbed.update(result.absorbed_ids)
                multi_orphan_used = True
                j = result.advance_to
                continue

            # Branch 4: orphan lookahead (single/multi-step)
            result = _try_orphan_lookahead(
                blocks, j, ref_cols, column_xs,
                table_blocks, partial_absorbed)
            if result is not None:
                for k in range(j, result.advance_to):
                    table_blocks.append(blocks[k])
                partial_absorbed.update(result.absorbed_ids)
                if result.multi_orphan:
                    multi_orphan_used = True
                j = result.advance_to
                continue

            # Branch 4d: split row, label block beside its cell block.
            # The label owns the row and comes first; the cell block is
            # partial-marked and merges into it. Not on two-column pages:
            # there a left-column heading beside a right-column paragraph
            # has exactly this geometry.
            if (j + 1 < len(blocks)
                    and blocks[j].page_num not in two_column_pages):
                result = _try_split_row(blocks, j, ref_cols, table_blocks)
                if result is not None:
                    if id(blocks[j]) in result.absorbed_ids:
                        table_blocks.extend((blocks[j + 1], blocks[j]))
                    else:
                        table_blocks.extend((blocks[j], blocks[j + 1]))
                    partial_absorbed.update(result.absorbed_ids)
                    j = result.advance_to
                    continue

            # Branch 4c: trailing continuation.  A single-line block at
            # column 1+ directly under the last row whose lookahead found
            # no full row (the next row is itself partial, or the table
            # ends here).  Absorbing it in the loop keeps the scan alive
            # so Branch 5 can still take a following partial row
            # (p4096r0 §5.2 noexcept row 3).  Guard: only tables that are
            # already established, to avoid grabbing code-comparison
            # content.
            if (len(table_blocks) >= _MIN_TABLE_ROWS
                    and _is_trailing_continuation(
                        blocks[j], ref_cols, table_blocks[-1].bbox[3],
                        blocks[j].page_num == table_blocks[-1].page_num)):
                partial_absorbed.add(id(blocks[j]))
                table_blocks.append(blocks[j])
                j += 1
                continue

            # Branch 4 failure falls through here. Today this is safe because
            # _is_column_aligned_orphan and _is_partial_row are mutually exclusive
            # (orphan blocks are single-line; partial row rejects single-line).
            # Branch 5: partial row
            result = _try_partial_row(
                blocks, j, ref_cols, column_xs, table_blocks)
            if result is not None:
                table_blocks.append(blocks[j])
                for k in range(j + 1, result.advance_to):
                    table_blocks.append(blocks[k])
                partial_absorbed.update(result.absorbed_ids)
                j = result.advance_to
                continue

            # Branch 6: the table resumes at the top of the next page.
            # Tried last so it can only rescue a table the same-page
            # branches have already given up on. Only the continuation
            # row joins the table; the whitespace-only spacers it skipped
            # carry no text.
            result = _try_cross_page_continuation(
                blocks, j, ref_cols, table_blocks)
            if result is not None:
                table_blocks.append(blocks[result.advance_to - 1])
                ref_cols = result.new_ref_cols or ref_cols  # always set; typing only
                j = result.advance_to
                continue

            # No branch matched: end table
            _log.debug("Pass 1: no branch matched for block %d on page %d, ending table scan",
                        j, blocks[j].page_num)
            break

        if len(table_blocks) >= _MIN_TABLE_ROWS:
            num_cols = len(ref_cols)
            rows: list[list[list]] = []
            all_lines = []

            # Header detection: check block before table for column headers
            header_row = _detect_header_block(blocks, i, ref_cols, num_cols)
            if header_row is not None:
                rows.append(header_row)

            # When multi-orphan lookahead absorbed blocks, MuPDF
            # delivers column fragments in non-y-sorted order.
            # Use y-band grouping to reconstruct logical rows
            # instead of sequential block-to-row mapping.
            if multi_orphan_used:
                ybanded_rows, all_lines = _build_rows_ybanded(
                    table_blocks, ref_cols, num_cols)
                rows.extend(ybanded_rows)
            else:
                seq_rows, all_lines = _build_rows_sequential(
                    table_blocks, ref_cols, num_cols, partial_absorbed)
                rows.extend(seq_rows)

            # Pass B: merge forward-orphans (single populated first
            # cell) into the following row.  This handles wrapped cell
            # first lines absorbed by the existing orphan-lookahead.
            merged: list[list[list]] = []
            k = 0
            while k < len(rows):
                row = rows[k]
                if (k + 1 < len(rows)
                        and bool(row[0])
                        and all(not cell for cell in row[1:])
                        and bool(rows[k + 1][0])):
                    sep = [Span(text="\n")]
                    merged.append(
                        [row[0] + sep + rows[k + 1][0]]
                        + rows[k + 1][1:])
                    k += 2
                else:
                    merged.append(row)
                    k += 1
            rows = merged

            # Dedup repeated headers from cross-page tables.
            # PDFs that span multiple pages often repeat the
            # header row at the top of each continuation page.
            if len(rows) >= 3:
                hdr_text = tuple(
                    "".join(s.text for s in cell).strip()
                    for cell in rows[0])
                deduped: list[list[list]] = [rows[0]]
                for row in rows[1:]:
                    row_text = tuple(
                        "".join(s.text for s in cell).strip()
                        for cell in row)
                    if row_text != hdr_text:
                        deduped.append(row)
                rows = deduped

            # MuPDF-overlap guard (Pass 1): if the table blocks overlap a
            # substantial MuPDF find_tables() region, defer to Pass 5.
            # Skip deferral for predominantly monospace tables (code
            # comparisons) where Pass 1 produces better results.
            p1_page = table_blocks[0].page_num
            p1_deferred = False
            p1_grid: dict | None = None  # drawn grid that re-cuts the rows
            if filtered_mupdf_tables:
                mono_spans = 0
                total_spans = 0
                for blk in table_blocks:
                    for ln in blk.lines:
                        for sp in ln.spans:
                            if sp.text.strip():
                                total_spans += 1
                                if sp.monospace:
                                    mono_spans += 1
                p1_mono_ratio = mono_spans / total_spans if total_spans else 0
                page_tbls = filtered_mupdf_tables.get(p1_page, [])
                # Rotated pages: Pass 1 column geometry operates in page
                # space where the rotated table layout is meaningless, so
                # the mono-ratio escape hatch must not keep its result.
                if (p1_mono_ratio < _MONO_RATIO_THRESHOLD
                        or p1_page in rotated_pages):
                    # Use only blocks on p1_page for bounding box.
                    # Cross-page tables mix y-coordinates from
                    # different pages, inflating p1_h and defeating
                    # the phantom guard.
                    same_pg = [b for b in table_blocks
                               if b.page_num == p1_page]
                    p1_y0 = min(b.bbox[1] for b in same_pg)
                    p1_y1 = max(b.bbox[3] for b in same_pg)
                    p1_x0 = min(b.bbox[0] for b in same_pg)
                    p1_x1 = max(b.bbox[2] for b in same_pg)
                    for tbl in page_tbls:
                        tb = tbl["bbox"]
                        rot = tbl.get("rot")
                        # find_tables bboxes live in reading space; map
                        # the Pass 1 bbox there on rotated pages.
                        rx0, ry0, rx1, ry1 = _rot_bbox(
                            (p1_x0, p1_y0, p1_x1, p1_y1), rot)
                        ov_x = max(0, min(rx1, tb[2]) - max(rx0, tb[0]))
                        ov_y = max(0, min(ry1, tb[3]) - max(ry0, tb[1]))
                        if rot is not None:
                            # Rotated page: any overlap defers to Pass 5,
                            # which is rotation-aware. The min-rows and
                            # phantom guards are calibrated for upright
                            # pages and would keep Pass 1's garbage here.
                            if ov_x > 0 and ov_y > 0:
                                _log.debug(
                                    "Pass 1 deferred to MuPDF Native "
                                    "(rotated page %d)", p1_page)
                                p1_deferred = True
                                break
                            continue
                        if _is_drawing_grid(tbl):
                            # A drawn grid is verified geometry, not a
                            # find_tables() guess: it never merges prose
                            # into the table, so the 5-row rule and the
                            # phantom height guard below do not apply.
                            # Pass 1 stands down only when the grid holds
                            # blocks it did not claim (P4016R0 K.1: 2 of
                            # 9 rows). A complete Pass 1 table keeps the
                            # blocks but re-cuts its rows along the drawn
                            # cells: Pass 1 assigns lines to rows by
                            # MuPDF block, and a cell taller than its
                            # neighbours arrives split over the adjacent
                            # rows' blocks (P4016R0 F.1 Rationale).
                            # Standing down instead is not an option:
                            # Pass 2 (column-aligned) claims the blocks
                            # before Pass 5 sees the grid.
                            if not _pass1_region_incomplete(
                                    tb, p1_page, table_blocks, blocks):
                                if (ov_x > 0 and ov_y > 0
                                        and p1_grid is None):
                                    p1_area = max(
                                        (rx1 - rx0) * (ry1 - ry0), 1)
                                    if (ov_x * ov_y) / p1_area > 0.30:
                                        p1_grid = tbl
                                continue
                        else:
                            if (tbl.get("row_count", 0)
                                    < _SBS_MUPDF_DEFER_MIN_ROWS
                                    and not _pass1_region_incomplete(
                                        tb, p1_page, table_blocks, blocks)):
                                continue
                            # Phantom guard: if MuPDF's table is much
                            # taller than what Pass 1 detected, MuPDF has
                            # merged prose with the real table. Keep the
                            # Pass 1 detection.
                            mupdf_h = tb[3] - tb[1]
                            p1_h = max(ry1 - ry0, 1.0)
                            if mupdf_h > p1_h * 3.0:
                                continue
                        if ov_x > 0 and ov_y > 0:
                            p1_area = max(
                                (rx1 - rx0) * (ry1 - ry0), 1)
                            if (ov_x * ov_y) / p1_area > 0.30:
                                _log.debug(
                                    "Pass 1 deferred to MuPDF Native: "
                                    "page %d, MuPDF rows=%d",
                                    p1_page, tbl.get("row_count", 0))
                                p1_deferred = True
                                break
            if p1_deferred:
                for blk in table_blocks:
                    remaining.append(blk)
                i = j
                continue

            if p1_grid is not None:
                recut = _rows_from_drawn_grid(
                    table_blocks, p1_grid, p1_page, num_cols)
                if recut is not None:
                    rows, all_lines = recut
                    # The header block above the grid is not in
                    # table_blocks; keep it in front as before.
                    if header_row is not None:
                        rows.insert(0, header_row)
                    _log.debug(
                        "Pass 1 rows re-cut along drawn grid: page %d, "
                        "%d rows x %d cols",
                        p1_page, len(rows), p1_grid.get("col_count", 0))

            kind_val, strategy_val, rows = _classify_and_annotate(rows)

            # Contents with no dot leaders: title and page number align
            # like a two-column row. Give the blocks back to the prose
            # path so the contents label can still strip them.
            if _is_labeled_contents_table(rows, blocks, p1_page):
                _log.debug(
                    "Pass 1 contents bypass: %d blocks on page %d",
                    len(table_blocks), p1_page)
                for blk in table_blocks:
                    remaining.append(blk)
                i = j
                continue

            # Bibliography: not a real table, return blocks to prose pipeline.
            if kind_val == TableKind.BIBLIOGRAPHY.value:
                _log.debug("Pass 1 bibliography bypass: %d blocks on page %d",
                            len(table_blocks), p1_page)
                for blk in table_blocks:
                    remaining.append(blk)
                i = j
                continue

            if _is_running_header_grid(rows):
                # Consume without emitting. See the side-by-side bypass.
                _log.debug(
                    "Pass 1 running-header bypass: %d blocks on page %d",
                    len(table_blocks), p1_page)
                i = j
                continue

            text = _render_table_text(rows)

            table_sections.append(Section(
                kind=SectionKind.TABLE,
                text=text,
                confidence=Confidence.HIGH,
                lines=all_lines,
                page_num=p1_page,
                columns=rows,
                table_kind=kind_val,
                table_strategy=strategy_val,
                table_source="horizontal_rows",
            ))
            _log.debug("Table detected: %d rows x %d cols on page %d",
                        len(rows), num_cols, p1_page)
            i = j
        else:
            _log.debug("Pass 1 reject: seed %d on page %d, too few table blocks "
                        "(%d < %d)", i, blocks[i].page_num,
                        len(table_blocks), _MIN_TABLE_ROWS)
            remaining.append(blocks[i])
            i += 1

    # Pass 2: side-by-side block tables (non-atomized) on remaining blocks
    sbs_tables, sbs_used = _detect_side_by_side_tables(
        remaining, page_mupdf_tables=filtered_mupdf_tables)
    if sbs_tables:
        table_sections.extend(sbs_tables)
        remaining = [b for idx, b in enumerate(remaining)
                     if idx not in sbs_used]

    # Cross-page continuation for side-by-side tables: when tables on
    # adjacent pages share identical headers, strip the duplicate header
    # so the emit phase folds them into one visual table.  Operates on
    # all side-by-side tables (pre-pass + regular pass) sorted by page.
    sbs_all = [s for s in table_sections
               if s.table_kind == "clean_matrix"
               and s.table_strategy == "html_table"]
    sbs_all.sort(key=lambda s: s.page_num)
    for k in range(len(sbs_all) - 1):
        t1 = sbs_all[k]
        t2 = sbs_all[k + 1]
        if (t2.page_num - t1.page_num) not in (0, 1):
            continue
        if not t1.columns or not t2.columns:
            continue
        if len(t1.columns[0]) != len(t2.columns[0]):
            continue
        h1 = tuple(
            "".join(s.text for s in cell).strip()
            for cell in t1.columns[0])
        h2 = tuple(
            "".join(s.text for s in cell).strip()
            for cell in t2.columns[0])
        if h1 == h2 and len(t2.columns) > 1:
            t2.columns = t2.columns[1:]
            t2.table_continuation = True
            t2.text = _render_table_text(t2.columns)
            _log.info(
                "Stripped duplicate header from side-by-side "
                "table continuation on page %d", t2.page_num)

    # Pass 2b: inline-grid tables (alternating-x lines in one block).
    # Runs before MuPDF native (Pass 5) which would mishandle them
    # via _maybe_transpose_label_table.  Requires MuPDF confirmation
    # to avoid false positives on code listings and prose.
    ig_tables, ig_used = _detect_inline_grid_tables(
        remaining, page_mupdf_tables=filtered_mupdf_tables)
    if ig_tables:
        table_sections.extend(ig_tables)
        remaining = [b for idx, b in enumerate(remaining)
                     if idx not in ig_used]

    # Pass 3a: split blocks with trailing horizontal-row headers
    # (MuPDF merges table headers into paragraph blocks when cells
    # are empty, e.g. P4012R0 §2.2 "Suggested Polls").
    thr_tables, remaining = _split_trailing_horizontal_rows(remaining)
    if thr_tables:
        table_sections.extend(thr_tables)

    # Pass 3: narrow horizontal-row tables (e.g. vote/poll grids)
    hr_tables, hr_used = _detect_horizontal_row_tables(
        remaining, rotated_pages=rotated_pages,
        page_mupdf_tables=filtered_mupdf_tables)
    if hr_tables:
        table_sections.extend(hr_tables)
        remaining = [b for idx, b in enumerate(remaining)
                     if idx not in hr_used]

    # Pass 4: geometric column grouping (borderless tables)
    geo_tables, geo_used = _detect_column_aligned_tables(
        remaining, two_column_pages=two_column_pages,
        rotated_pages=rotated_pages)
    if geo_tables:
        table_sections.extend(geo_tables)
        remaining = [b for idx, b in enumerate(remaining)
                     if idx not in geo_used]

    # Pass 5: MuPDF native find_tables() on remaining blocks.
    # Runs last so it only catches tables missed by all heuristic passes.
    remaining_mupdf_tables = _filter_overlapping_mupdf_tables(
        filtered_mupdf_tables, table_sections)
    mupdf_tables, mupdf_used = _detect_mupdf_native_tables(
        remaining, remaining_mupdf_tables)
    if mupdf_tables:
        table_sections.extend(mupdf_tables)
        remaining = [b for idx, b in enumerate(remaining)
                     if idx not in mupdf_used]

    table_sections = _join_ruled_grid_continuations(
        table_sections, filtered_mupdf_tables, remaining)

    # Post-pass: spanning-header absorption.  After all passes,
    # check whether any remaining block sits directly above a
    # detected TABLE section and looks like a multi-column header
    # with fewer columns (e.g. "status quo | Section 6.3" above a
    # 3-col data table).  Pass-agnostic: works regardless of
    # which pass produced the table.
    absorbed: set[int] = set()
    for ts in table_sections:
        if not ts.columns or len(ts.columns) < 2:
            continue
        # Banded sections live on rotated pages where the page-space
        # y-geometry below is meaningless; they carry their own header.
        if ts.table_source == "banded_grid":
            continue
        ncols = len(ts.columns[0])
        ts_y_top = min(ln.bbox[1] for ln in ts.lines) if ts.lines else 0
        # Get column x-positions from the first data row's spans.
        first_row = ts.columns[0]
        col_xs: list[float] = []
        for cell in first_row:
            xs = [sp.bbox[0] for sp in cell
                  if hasattr(sp, "bbox") and any(sp.bbox)]
            col_xs.append(min(xs) if xs else 999.0)
        if all(x >= 999 for x in col_xs):
            continue

        cluster = _collect_header_cluster(
            remaining, absorbed, ts.page_num, ts_y_top, col_xs)
        if cluster is None:
            continue
        cluster_idxs, header_row = cluster
        # Absorb: prepend header row to table.
        for bi in cluster_idxs:
            for ln in remaining[bi].lines:
                ts.lines.insert(0, ln)
        ts.columns.insert(0, header_row)
        ts.text = _render_table_text(ts.columns)
        absorbed.update(cluster_idxs)
        _log.debug(
            "Spanning header absorbed: page %d, %d block(s) covering "
            "%d of %d cols",
            ts.page_num, len(cluster_idxs),
            sum(1 for c in header_row if c), ncols)

        _absorb_hash_header_above_number(ts, remaining, absorbed)

    if absorbed:
        remaining = [b for bi, b in enumerate(remaining)
                     if bi not in absorbed]

    for ts in table_sections:
        _drop_separator_rows(ts)

    if table_sections:
        kinds = {}
        for sec in table_sections:
            kinds[sec.table_kind] = kinds.get(sec.table_kind, 0) + 1
        _log.info("Table classification: %s", dict(sorted(kinds.items())))

    return table_sections, remaining


def exclude_table_regions(blocks: list[Block],
                          table_sections: list[Section]) -> list[Block]:
    """Remove blocks or lines whose vertical midpoint falls within a detected table region.

    For multi-page tables, builds per-page y-ranges from individual
    lines so that content on continuation pages is also excluded.
    """
    if not table_sections:
        return blocks

    # Build per-table (page_num, y_min, y_max) ranges.  Each table
    # section gets its own range(s) so disjoint tables on the same
    # page do not merge into one mega-range that swallows prose between
    # them (which would skew compare_extractions similarity scores).
    table_ranges: list[tuple[int, float, float]] = []
    for sec in table_sections:
        if not sec.lines:
            continue
        sec_ranges: dict[int, tuple[float, float]] = {}
        for ln in sec.lines:
            pg = ln.page_num
            if pg in sec_ranges:
                old_min, old_max = sec_ranges[pg]
                sec_ranges[pg] = (
                    min(old_min, ln.bbox[1]),
                    max(old_max, ln.bbox[3]),
                )
            else:
                sec_ranges[pg] = (ln.bbox[1], ln.bbox[3])
        table_ranges.extend(
            (pg, y_min, y_max)
            for pg, (y_min, y_max) in sec_ranges.items()
        )

    result = []
    for block in blocks:
        if not block.lines:
            by = (block.bbox[1] + block.bbox[3]) / 2.0
            in_table = False
            for pg, y_min, y_max in table_ranges:
                if (block.page_num == pg
                        and y_min - _TABLE_Y_OVERLAP_MARGIN <= by
                        <= y_max + _TABLE_Y_OVERLAP_MARGIN):
                    in_table = True
                    break
            if not in_table:
                result.append(block)
            continue

        kept_lines = []
        for ln in block.lines:
            ly = (ln.bbox[1] + ln.bbox[3]) / 2.0
            in_table = False
            for pg, y_min, y_max in table_ranges:
                if (ln.page_num == pg
                        and y_min - _TABLE_Y_OVERLAP_MARGIN <= ly
                        <= y_max + _TABLE_Y_OVERLAP_MARGIN):
                    in_table = True
                    break
            if not in_table:
                kept_lines.append(ln)

        if kept_lines:
            if len(kept_lines) == len(block.lines):
                result.append(block)
            else:
                result.append(Block(
                    lines=kept_lines,
                    bbox=compute_bbox([ln.bbox for ln in kept_lines]),
                    page_num=block.page_num,
                ))
    return result
