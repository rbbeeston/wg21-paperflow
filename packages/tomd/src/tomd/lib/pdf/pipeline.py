"""PDF to Markdown converter - pipeline entry point."""

import fitz
import functools
import logging
import re
from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from pathlib import Path

from .cleanup import (
    get_edge_items,
    detect_repeating,
    strip_repeating,
    cleanup_text,
    find_hidden_regions,
    strip_hidden_blocks,
)
from .extract import extract_mupdf, extract_spatial, collect_links, attach_links
from .images import (
    ExtractedImage,
    VectorUncertaintyStats,
    _CAPTION_LABEL_RE,
    _CAPTION_SEARCH_RADIUS_BELOW_PT,
    _VectorExtractionStats,
    extract_page_images,
    finalize_extraction,
)
from .vector_images import extract_page_vector_images
from .glyphs import (
    GlyphPassStats,
    collect_glyph_candidates,
    collect_text_emoji_bboxes,
    drop_glyphs_in_code_and_tables,
    filter_coincident,
    inject_glyph_spans,
)
from .mono import propagate_monospace
from .figures import detect_figure_regions
from .wording import classify_wording, collect_line_drawings
from .spans import normalize_spans
from .structure import (
    compare_extractions,
    drop_leaked_toc_entries,
    structure_body,
    _is_known_section,
    _TITLE_PID_PREFIX_RE,
)
from ..metadata_yaml.extract import (
    apply_pdf_metadata_fallbacks as _apply_pdf_metadata_fallbacks,
    enrich_pdf_reply_to as _enrich_pdf_reply_to,
    extract_metadata as _extract_metadata_yaml,
)
from .table import (
    detect_tables, exclude_table_regions, _rot_bbox, _rot_midpoint,
    _filter_phantom_mupdf_tables, _cluster_x_positions, TableStrategy,
)
from .wg21 import extract_metadata_from_blocks
from .emit import emit_markdown, emit_prompts, renumber_uncertain_markers, _escape_italic_text
from .types import (
    Confidence,
    KNOWN_SECTIONS,
    Section,
    SectionKind,
    SkipReason,
    is_readable,
)
from .. import DOC_NUM_RE
from ..shared import override_revision_from_filename
from ..toc import find_toc_indices, has_dot_leader, is_toc_label
from ..metadata_yaml.strip import (
    strip_metadata_headings as _strip_metadata_headings_new,
    strip_pre_heading_fragments as _strip_pre_heading_fragments,
    strip_pre_content_paragraphs as _strip_pre_content_paragraphs,
)
from ..body.abstract import dedup_abstract as _dedup_abstract_new
from ..body.abstract import (
    promote_abstract_from_uncertain as _promote_abstract_from_uncertain,
)
from ..body.abstract import (
    reorder_abstract_in_uncertain as _reorder_abstract_in_uncertain,
)
from ..body.abstract import (
    rescue_stranded_abstract_body as _rescue_stranded_abstract_body,
)
from ..body.abstract import (
    strip_metadata_from_uncertain as _strip_metadata_from_uncertain,
)

from .docling_backend import (
    docling_available as _docling_available,
    extract_docling_tables as _extract_docling_tables,
    enrich_tables_with_docling as _enrich_tables_with_docling,
    absorb_cross_page_spec_rows as _absorb_cross_page_spec_rows,
    discover_tables_with_docling as _discover_tables_with_docling,
)
from ._fitz_lock import _FITZ_LOCK
from .runctx import current, run_scope
from .select import remove_table_regions, select_tables
from .tagged import extract_tagged_tables
from .ruled import extract_ruled_tables, page_hrules
from .rowbands import merge_rule_bands
from .levels import assign as assign_level
from .summary import build as build_summary, generator as pdf_generator, header_comment, prompt_elements

__all__ = ["run_pipeline", "PipelineResult", "ExtractedImage"]

_log = logging.getLogger(__name__)

_STANDALONE_PAGE_RE = re.compile(r"^\d{1,4}$")
_SECTION_NUM_START_RE = re.compile(r"^(?:\d+(?:\.\d+)*|[IVXLCDM]+)(?:\s|$)")
_TOC_X_TOLERANCE = 5.0
_TOC_BODY_PROTECT_MIN_WORDS = 10
_NUMBERED_LINE_RE = re.compile(r"^\s*\d+[\.\)]\s+\S")
_BARE_PAGE_NUM_RE = re.compile(r"^\s*\d{1,3}\s*$")
_LABEL_TOC_MIN_NUMBERED_LINES = 3
_CONTENTS_ENTRY_MAX_CHARS = 80
_TABLE_CAPTION_RE = re.compile(
    r"^\s*Table\s+(?:\d+|[IVXLCDM]+)\b", re.IGNORECASE)


def _leading_contents(
    lines: list[str],
) -> tuple[int, list[tuple[str, str]]] | None:
    """Cut index and title/page entries of a leading Contents list.

    Page numbers sit on their own lines. The cut keeps whatever body was
    joined onto the same section.
    """
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i >= len(lines) or not is_toc_label(lines[i].strip()):
        return None
    i += 1
    pages = 0
    entries: list[tuple[str, str]] = []
    while i < len(lines):
        while i < len(lines) and not lines[i].strip():
            i += 1
        if i >= len(lines):
            break
        title = lines[i].strip()
        k = i + 1
        while k < len(lines) and not lines[k].strip():
            k += 1
        if (k >= len(lines) or not title
                or len(title) > _CONTENTS_ENTRY_MAX_CHARS
                or not _BARE_PAGE_NUM_RE.match(lines[k].strip())):
            break
        pages += 1
        entries.append((title, lines[k].strip()))
        i = k + 1
    if pages < _LABEL_TOC_MIN_NUMBERED_LINES:
        return None
    return i, entries


def _strip_contents_entries(
    text: str, entries: list[tuple[str, str]],
) -> str:
    """Remove one Contents label and its known entries from an extraction.

    Spatial extraction interleaves the other column between TOC entries,
    so the list is not a contiguous prefix there. Exact title/page pairs
    can still be removed without replacing the independent extraction.
    """
    text = re.sub(r"(?im)^\s*contents\b[ \t]*", "", text, count=1)
    for title, page in entries:
        pattern = rf"(?i){re.escape(title)}\s+{re.escape(page)}(?=\s|$)"
        text = re.sub(pattern, "", text, count=1)
    return text.lstrip("\n")


def _drop_leading_contents(sec) -> None:
    """Remove a leading Contents list from both the text and the lines.

    Paragraphs render ``sec.lines``. Updating only ``sec.text`` would leave
    the list on the page. Uncertain-region prompts read ``mupdf_text`` and
    ``spatial_text``; leaving either raw extraction untouched would let the
    reconciliation model put the removed list back.
    """
    parsed = _leading_contents(sec.text.split("\n"))
    if parsed is None:
        return
    text_cut, entries = parsed
    trimmed_lines = False
    if sec.lines:
        lines_parsed = _leading_contents([ln.text for ln in sec.lines])
        if lines_parsed is not None:
            line_cut, _ = lines_parsed
            sec.lines = sec.lines[line_cut:]
            sec.text = "\n".join(ln.text for ln in sec.lines)
            trimmed_lines = True
    if not trimmed_lines:
        sec.text = "\n".join(sec.text.split("\n")[text_cut:]).lstrip("\n")
        # The section's line order did not expose a contiguous title/page
        # run (two-column extraction can interleave it). Render the clean
        # text instead of the stale lines.
        sec.lines = []
    for attr in ("mupdf_text", "spatial_text"):
        raw = getattr(sec, attr, "")
        if not raw:
            continue
        setattr(sec, attr, _strip_contents_entries(raw, entries))
    if sec.kind is not SectionKind.UNCERTAIN:
        sec.kind = SectionKind.PARAGRAPH
    sec.heading_level = 0
    sec.columns = []
    sec.indent_level = 0
    sec.table_kind = None
    sec.table_strategy = None
    sec.table_source = None
    sec.table_continuation = False
_TOC_LABEL_MAX_WORDS = 4

# Two-column detection: minimum gap (points) between the right edge of left-
# column blocks and the left edge of right-column blocks to declare two
# columns.  Typical column gutters are 15-30pt; single-column text with
# indented code can have 10pt shifts.  20pt sits comfortably between.
_COLUMN_GAP_MIN = 20.0

# Minimum fraction of total blocks that the smaller "column" must have to
# accept a two-column split.  Right-aligned decorative labels (e.g.
# "ABSTRACT", "CONTENTS") create a tiny cluster of 2-3 blocks that triggers
# a false column split against 20+ body blocks on the other side.
_COLUMN_MIN_FRACTION = 0.20

# Guard G1 – gutter-crossing fraction.  Among left-side blocks whose
# y-midpoint lies within the right column's vertical span, the fraction
# whose x1 extends past the right column's left edge (plus tolerance)
# must not exceed this threshold.  Shattered table pages have cells
# that straddle the "gutter" while genuine two-column pages do not.
_COLUMN_CROSSING_MAX_FRAC = 0.15
_COLUMN_CROSSING_X_TOL = 5.0  # pt of slack for the crossing check

# Guard G2 – row-alignment fraction.  When right-side blocks have a
# left-side counterpart within this y-tolerance, the page is likely a
# table (cells align into rows), not two text columns.
_COLUMN_ROW_ALIGN_TOL = 1.5     # pt: y0-proximity to count as row-aligned
_COLUMN_ROW_ALIGN_MAX_FRAC = 0.5  # reject when fraction >= this


def _toc_structural_hints(sections) -> list[bool]:
    """Mark sections that structurally resemble TOC entries.

    A section qualifies when its second non-empty text line is a bare page
    number AND its x coordinate clusters with other such candidates (the
    right-aligned page-number column). Used as a fallback for headingless
    wording papers where find_toc_indices would otherwise get an empty
    headings set.
    """
    candidates: list[tuple[int, float | None]] = []
    for i, sec in enumerate(sections):
        lines = [ln.strip() for ln in sec.text.split("\n") if ln.strip()]
        if len(lines) >= 2 and _STANDALONE_PAGE_RE.match(lines[1]):
            x = None
            non_empty = [ln for ln in sec.lines if ln.text.strip()]
            if len(non_empty) >= 2 and non_empty[1].spans:
                x = non_empty[1].spans[0].bbox[0]
            candidates.append((i, x))

    if not candidates:
        return [False] * len(sections)

    xs = sorted(x for _, x in candidates if x is not None)
    med_x = xs[len(xs) // 2] if xs else None

    result = [False] * len(sections)
    for i, x in candidates:
        if med_x is None:
            if x is None:
                result[i] = True
        elif x is None or abs(x - med_x) <= _TOC_X_TOLERANCE:
            result[i] = True
    return result


# ─── Drawing-grid detection ────────────────────────────────────────────
# MuPDF find_tables() misses some bordered tables (small ones, and any
# table on a page where it swallowed the page background box instead).
# This fallback detects rectangular grids from vector drawing rules and
# injects them as synthetic find_tables() entries, so Pass 2b (inline
# grid), the Pass 1 region checks and Pass 5 (MuPDF Native) see them.

_DRAWING_GRID_SPAN_TOL = 5.0  # grouping tolerance for horizontal lines
_DRAWING_GRID_AXIS_TOL = 1.0  # max skew for an axis-aligned line
# HTML-to-PDF engines draw borders as thin filled rectangles, one per
# cell edge, never as "l" items (P4016R0: every rule is a 0.6pt "re").
# A rectangle no thicker than this is read as a rule along its long axis.
_DRAWING_GRID_RULE_MAX_THICKNESS = 1.5
_DRAWING_GRID_MIN_HORIZONTALS = 5  # 5+ h-rule segments on the page
_DRAWING_GRID_MIN_WIDTH = 50.0  # reject tiny decorative boxes
_DRAWING_GRID_VERT_TOL = 3.0  # tolerance for matching vertical borders
_DRAWING_GRID_Y_DEDUP = 3.0  # merge near-identical y-values
_DRAWING_GRID_MIN_UNIQUE_ROWS = 3  # deduped rules: header + 2 data rows minimum
_DRAWING_GRID_MAX_HEIGHT_RATIO = 0.7  # reject grids taller than 70% of page
_DRAWING_GRID_CELL_X_TOL = 4.0  # x-start clustering into cells per rule band
_DRAWING_GRID_MIN_MULTI_BANDS = 2  # bands that must hold 2+ cells side by side
_DRAWING_GRID_MIN_MULTI_BAND_FRACTION = 0.5  # multi-cell bands >= half of all bands
_DRAWING_GRID_COVER_FRAC = 0.5  # find_tables overlap that counts as covered


def _page_text_line_bboxes(page) -> list[tuple[float, float, float, float]]:
    """Bboxes of all text lines on *page*, for the grid multi-cell check."""
    try:
        data = page.get_text("dict", flags=0)
    except Exception:
        # Firewall around MuPDF: a malformed page must not abort the
        # whole conversion, it just loses the drawing-grid fallback.
        return []
    return [
        tuple(line["bbox"])
        for blk in data.get("blocks", [])
        if blk.get("type") == 0
        for line in blk.get("lines", [])
    ]


def _detect_drawing_grids(
    page,
    page_height: float,
    existing_tables: list[dict],
) -> list[dict]:
    """Detect bordered table grids from page drawings that find_tables missed.

    Rules come from "l" items and from thin "re" items (cell-edge
    rectangles drawn by HTML-to-PDF engines). Collinear horizontal
    segments at one y are merged first, so per-cell edge pieces form
    one rule spanning the table. *existing_tables* must already be
    phantom-filtered: a full-page find_tables() phantom would otherwise
    "cover" every grid on the page.

    Returns a list of synthetic table entries in find_tables() shape
    (bbox, row/col counts, cell bboxes from the rule intersections,
    ``source="drawing_grid"``) for injection into page_mupdf_tables.
    """
    try:
        drawings = page.get_drawings()
    except Exception:
        # Firewall around MuPDF, same rationale as _page_text_line_bboxes.
        return []

    h_lines: list[tuple[float, float, float]] = []
    v_lines: list[tuple[float, float, float]] = []  # (x, y0, y1)

    for d in drawings:
        for item in d["items"]:
            if item[0] == "l":
                p1, p2 = item[1], item[2]
                if abs(p1.y - p2.y) < _DRAWING_GRID_AXIS_TOL:
                    h_lines.append((min(p1.x, p2.x), max(p1.x, p2.x), p1.y))
                elif abs(p1.x - p2.x) < _DRAWING_GRID_AXIS_TOL:
                    v_lines.append((p1.x, min(p1.y, p2.y), max(p1.y, p2.y)))
            elif item[0] == "re":
                r = item[1]
                if r.height <= _DRAWING_GRID_RULE_MAX_THICKNESS < r.width:
                    h_lines.append((r.x0, r.x1, (r.y0 + r.y1) / 2.0))
                elif r.width <= _DRAWING_GRID_RULE_MAX_THICKNESS < r.height:
                    v_lines.append(((r.x0 + r.x1) / 2.0, r.y0, r.y1))

    if len(h_lines) < _DRAWING_GRID_MIN_HORIZONTALS:
        return []

    h_lines = _merge_collinear_rules(h_lines)

    # Bucket h-lines by rounded span. Bucketing has hard edges (lines
    # straddling a bucket boundary split into two groups), but distance
    # clustering was tried and rejected: it merges vertically stacked
    # sibling tables with near-identical spans into one grid.
    h_by_span: dict[tuple[float, float], list[tuple[float, float, float]]] = defaultdict(list)
    for hx0, hx1, hy in h_lines:
        key = (
            round(hx0 / _DRAWING_GRID_SPAN_TOL) * _DRAWING_GRID_SPAN_TOL,
            round(hx1 / _DRAWING_GRID_SPAN_TOL) * _DRAWING_GRID_SPAN_TOL,
        )
        h_by_span[key].append((hx0, hx1, hy))

    results: list[dict] = []
    text_lines = _page_text_line_bboxes(page)
    for rules in h_by_span.values():
        x0 = min(r[0] for r in rules)
        x1 = max(r[1] for r in rules)
        if (x1 - x0) < _DRAWING_GRID_MIN_WIDTH:
            continue

        # Deduplicate y-values to count actual rows
        unique_ys: list[float] = []
        for y in sorted(r[2] for r in rules):
            if not unique_ys or abs(y - unique_ys[-1]) > _DRAWING_GRID_Y_DEDUP:
                unique_ys.append(y)

        span_verts = [v for v in v_lines
                      if x0 - _DRAWING_GRID_VERT_TOL <= v[0] <= x1 + _DRAWING_GRID_VERT_TOL]
        # One span bucket can hold several stacked things of the same
        # width: section separators, a two-rule note box, the table.
        # Only rules joined by a vertical rule belong to one grid.
        for chain in _split_rules_by_verticals(unique_ys, span_verts):
            grid = _grid_from_rule_chain(
                chain, x0, x1, page_height, span_verts, existing_tables,
                text_lines)
            if grid is not None:
                results.append(grid)

    return results


def _split_rules_by_verticals(
    ys: list[float],
    verts: list[tuple[float, float, float]],
) -> list[list[float]]:
    """Split sorted rule y-values into runs bridged by a vertical rule.

    Two consecutive rules belong to the same grid when some vertical
    segment spans from the upper to the lower one (a cell edge). A rule
    with no bridge on either side is a separator, not a table row.
    """
    chains: list[list[float]] = []
    for y in ys:
        if chains:
            prev = chains[-1][-1]
            bridged = any(vy0 <= prev + _DRAWING_GRID_Y_DEDUP
                          and vy1 >= y - _DRAWING_GRID_Y_DEDUP
                          for _, vy0, vy1 in verts)
            if bridged:
                chains[-1].append(y)
                continue
        chains.append([y])
    return chains


def _grid_from_rule_chain(
    unique_ys: list[float],
    x0: float,
    x1: float,
    page_height: float,
    span_verts: list[tuple[float, float, float]],
    existing_tables: list[dict],
    text_lines: list[tuple[float, float, float, float]],
) -> dict | None:
    """Validate one chain of rules as a table grid; None when it is not."""
    if len(unique_ys) < _DRAWING_GRID_MIN_UNIQUE_ROWS:
        return None
    y_min, y_max = unique_ys[0], unique_ys[-1]
    grid_height = y_max - y_min
    if grid_height > page_height * _DRAWING_GRID_MAX_HEIGHT_RATIO:
        return None

    # Require vertical borders on both sides within the grid's y-range.
    in_range = [v for v in span_verts
                if v[1] <= y_max - _DRAWING_GRID_Y_DEDUP
                and v[2] >= y_min + _DRAWING_GRID_Y_DEDUP]
    left_verts = any(abs(v[0] - x0) < _DRAWING_GRID_VERT_TOL for v in in_range)
    right_verts = any(abs(v[0] - x1) < _DRAWING_GRID_VERT_TOL for v in in_range)
    if not left_verts or not right_verts:
        return None

    grid_bbox = (x0, y_min, x1, y_max)

    # Multi-cell check: bordered wording/code boxes also produce
    # stacked horizontal rules, but their text sits at one x per
    # row. A real table has 2+ side-by-side cells in most rows.
    # Rows are the bands between consecutive rules, not text
    # y-clusters: a tall vertically centred cell puts its lines at
    # y-levels where the short neighbour cells have none, and
    # text-y bands would read those as single-cell rows (P4016R0
    # F.1 Rationale, K.1 Notes).
    band_xs: list[list[float]] = [[] for _ in unique_ys[1:]]
    for lx0, ly0, lx1, ly1 in text_lines:
        ymid = (ly0 + ly1) / 2.0
        xmid = (lx0 + lx1) / 2.0
        if not (y_min <= ymid <= y_max and x0 <= xmid <= x1):
            continue
        bi = bisect_right(unique_ys, ymid) - 1
        if 0 <= bi < len(band_xs):
            band_xs[bi].append(lx0)
    band_cells = [
        len(_cluster_x_positions(xs, _DRAWING_GRID_CELL_X_TOL))
        for xs in band_xs if xs]
    multi_bands = sum(1 for c in band_cells if c >= 2)
    if multi_bands < _DRAWING_GRID_MIN_MULTI_BANDS:
        return None
    if multi_bands < len(band_cells) * _DRAWING_GRID_MIN_MULTI_BAND_FRACTION:
        return None  # mostly single-cell rows: a box, not a table

    # Skip if already covered by find_tables
    already_covered = any(
        _bbox_overlap_fraction(grid_bbox, ft["bbox"]) > _DRAWING_GRID_COVER_FRAC
        for ft in existing_tables
    )
    if already_covered:
        return None

    # Vertical rules inside the grid, deduped, outer borders included.
    col_xs: list[float] = []
    for vx in sorted(v[0] for v in in_range):
        if not col_xs or abs(vx - col_xs[-1]) > _DRAWING_GRID_VERT_TOL:
            col_xs.append(vx)

    # The entry is what find_tables() should have returned: cells are
    # the rule intersections, so Pass 5 (MuPDF Native) maps text lines
    # into them exactly like a native result, and the Pass 1 region
    # checks see real row counts. "extract" stays empty (no MuPDF text
    # for synthesized cells); Pass 5 assembles from cells, only its
    # cross-page absorb branch reads extract and skips an empty one.
    n_rows = len(unique_ys) - 1
    n_cols = len(col_xs) - 1
    cells = [
        (col_xs[c], unique_ys[r], col_xs[c + 1], unique_ys[r + 1])
        for r in range(n_rows) for c in range(n_cols)
    ]
    max_cell_h = max(unique_ys[r + 1] - unique_ys[r] for r in range(n_rows))
    return {
        "bbox": grid_bbox,
        "row_count": n_rows,
        "col_count": n_cols,
        "cells": cells,
        "header_names": None,
        "extract": [],
        "rot": None,
        "max_cell_h": max_cell_h,
        "tbl_h": grid_height,
        "page_coverage": grid_height / page_height if page_height else 0.0,
        "source": "drawing_grid",
    }


def _merge_collinear_rules(
    h_lines: list[tuple[float, float, float]],
) -> list[tuple[float, float, float]]:
    """Merge horizontal segments that share a y and touch or overlap in x.

    Cell-edge rectangles give one segment per cell; a rule drawn twice
    (bottom of one cell, top of the next) gives duplicates. Both collapse
    into one (x0, x1, y) per rule so span bucketing sees the table width.
    """
    merged: list[tuple[float, float, float]] = []
    for hx0, hx1, hy in sorted(h_lines, key=lambda t: (t[2], t[0])):
        if merged:
            mx0, mx1, my = merged[-1]
            if abs(hy - my) <= _DRAWING_GRID_Y_DEDUP and hx0 <= mx1 + _DRAWING_GRID_SPAN_TOL:
                merged[-1] = (mx0, max(mx1, hx1), my)
                continue
        merged.append((hx0, hx1, hy))
    return merged


def _first_line_bottom(block) -> float:
    """Bottom edge of a block's topmost line (the block bbox for a block
    without lines). Superscripts raise a line's top, not its bottom. The
    minimum over the lines, not ``lines[0]``: MuPDF's line order is the
    content stream's, usually top-down but not a contract."""
    return min(ln.bbox[3] for ln in block.lines) if block.lines else block.bbox[3]


def _detect_column_split(blocks: list, page_width: float) -> float | None:
    """Find the x-coordinate that separates two text columns on a page.

    Returns the split point (midpoint of the inter-column gap) when two
    distinct column clusters exist, or None for single-column pages.
    Blocks whose x-midpoint falls left of the split are column 0 (left);
    those right of it are column 1 (right).
    """
    if len(blocks) < 2:
        return None
    x_mids = sorted((b.bbox[0] + b.bbox[2]) / 2 for b in blocks)
    # Find the largest gap between consecutive x-midpoints.
    best_gap = 0.0
    best_split = 0.0
    for i in range(len(x_mids) - 1):
        gap = x_mids[i + 1] - x_mids[i]
        if gap > best_gap:
            best_gap = gap
            best_split = (x_mids[i] + x_mids[i + 1]) / 2
    if best_gap < _COLUMN_GAP_MIN:
        return None
    # Sanity: both sides of the split must have blocks, and the split
    # should be roughly in the middle third of the page.
    left_count = sum(1 for x in x_mids if x < best_split)
    right_count = len(x_mids) - left_count
    if left_count < 2 or right_count < 2:
        return None
    if min(left_count, right_count) / (left_count + right_count) < _COLUMN_MIN_FRACTION:
        return None
    if best_split < page_width * 0.25 or best_split > page_width * 0.75:
        return None
    # Validate with left-edge (x0) clustering: in genuine two-column
    # layouts the right column's left edges sit near the page center,
    # not near the left margin.  Short single-column lines produce low
    # x-midpoints but keep their x0 near the left margin, so an x0
    # check rejects those false positives.
    left_x0s = [b.bbox[0] for b in blocks if (b.bbox[0] + b.bbox[2]) / 2 < best_split]
    right_x0s = [b.bbox[0] for b in blocks if (b.bbox[0] + b.bbox[2]) / 2 >= best_split]
    if left_x0s and right_x0s:
        max_left_x0 = max(left_x0s)
        min_right_x0 = min(right_x0s)
        if min_right_x0 - max_left_x0 < _COLUMN_GAP_MIN:
            return None

    # --- Guard G1: gutter-crossing fraction (interleaved blocks only) ---
    # Among left-side blocks vertically interleaved with the right column,
    # count those whose x1 extends past the right column's left edge.
    # Table pages have cells that straddle the split; genuine columns do not.
    right_blocks = [b for b in blocks
                    if (b.bbox[0] + b.bbox[2]) / 2 >= best_split]
    left_blocks = [b for b in blocks
                   if (b.bbox[0] + b.bbox[2]) / 2 < best_split]
    if right_blocks and left_blocks:
        right_y0 = min(b.bbox[1] for b in right_blocks)
        right_y1 = max(b.bbox[3] for b in right_blocks)
        min_right_x0_val = min(b.bbox[0] for b in right_blocks)
        interleaved = [b for b in left_blocks
                       if (b.bbox[1] + b.bbox[3]) / 2 >= right_y0
                       and (b.bbox[1] + b.bbox[3]) / 2 <= right_y1]
        if interleaved:
            crossing = sum(
                1 for b in interleaved
                if b.bbox[2] > min_right_x0_val + _COLUMN_CROSSING_X_TOL)
            frac = crossing / len(interleaved)
            if frac > _COLUMN_CROSSING_MAX_FRAC:
                return None

    # --- Guard G2: row-alignment fraction ---
    # When most right-side blocks have a left-side block starting at the
    # same y0 (within tolerance), the page is a row-aligned table, not
    # two independent text columns. The bottom edge of the first line is
    # checked as well: a superscript (p4098r1 "P1256R0 [16]") lifts a
    # block's y0 by a few points above its row neighbours while the
    # baseline, and with it the bottom edge, stays on the row. On the
    # p4098r1 p.4 PDF, y0 alone counted 4/10 right blocks aligned; with
    # the bottom edge 9/10 (the unit-test fixture is a subset: 8/10).
    if right_blocks and left_blocks:
        left_y0s = [b.bbox[1] for b in left_blocks]
        left_bottoms = [_first_line_bottom(b) for b in left_blocks]
        aligned = 0
        for rb in right_blocks:
            ry0 = rb.bbox[1]
            r_bottom = _first_line_bottom(rb)
            if (any(abs(ry0 - ly0) <= _COLUMN_ROW_ALIGN_TOL
                    for ly0 in left_y0s)
                    or any(abs(r_bottom - lb) <= _COLUMN_ROW_ALIGN_TOL
                           for lb in left_bottoms)):
                aligned += 1
        frac = aligned / len(right_blocks)
        if frac >= _COLUMN_ROW_ALIGN_MAX_FRAC:
            return None

    return best_split


def _region_bbox(lines: list) -> tuple[float, float, float, float]:
    """Union of line boxes. A header word is narrower than its row."""
    return (
        min(ln.bbox[0] for ln in lines),
        min(ln.bbox[1] for ln in lines),
        max(ln.bbox[2] for ln in lines),
        max(ln.bbox[3] for ln in lines),
    )


def _section_region_bbox(sec) -> tuple[float, float, float, float]:
    """Region on ``sec.page_num``; cross-page tails do not choose a column."""
    same_page = [ln for ln in sec.lines if ln.page_num == sec.page_num]
    return _region_bbox(same_page or sec.lines)


def _column_reading_key(
    bbox: tuple[float, float, float, float],
    split: float | None,
    rot: tuple | None,
    x_bbox: tuple[float, float, float, float] | None = None,
) -> tuple[int, float]:
    """(column, y0) in the order ``_column_aware_sort`` emits.

    With no split, or on a rotated page, the column is 0 and the key
    is the y comparison table insertion already used. A two-column
    split puts the whole left column before the right one, so a table
    at the top of the right column stays after the left column instead
    of jumping ahead of it because its page-space y is smaller.
    ``x_bbox`` is the region used for the column (the block the sort
    saw). The first line alone can sit left of the split: on P0533R9
    page 4 the split is 362 and the word Function is only x=322-358.
    """
    y = _rot_bbox(bbox, rot)[1]
    if split is None or rot is not None:
        return (0, y)
    box = x_bbox or bbox
    x_mid = (box[0] + box[2]) / 2
    return (0 if x_mid < split else 1, y)


def _insert_table_sections(
    sections: list,
    table_sections: list,
    page_rotations: dict[int, tuple],
    column_splits: dict[int, float],
) -> None:
    """Place each table back into the section list at its reading position."""
    for ts in table_sections:
        inserted = False
        data_on_label_page = ts.lines and ts.lines[0].page_num == ts.page_num
        ts_rot = page_rotations.get(ts.page_num)
        ts_split = column_splits.get(ts.page_num)
        ts_key = (
            _column_reading_key(
                ts.lines[0].bbox, ts_split, ts_rot,
                x_bbox=_section_region_bbox(ts))
            if ts.lines else None
        )
        for i, sec in enumerate(sections):
            if sec.page_num > ts.page_num:
                sections.insert(i, ts)
                inserted = True
                break
            if (
                data_on_label_page
                and ts_key is not None
                and sec.page_num == ts.page_num
                and sec.lines
                and _column_reading_key(
                    sec.lines[0].bbox, ts_split, ts_rot,
                    x_bbox=_section_region_bbox(sec))
                    > ts_key
            ):
                sections.insert(i, ts)
                inserted = True
                break
        if not inserted:
            sections.append(ts)
    _hoist_overlapping_multirow_pairs(
        sections, page_rotations, column_splits)


# A caption sits just under its table. The P0533 captions are about 11pt
# below the grid; a later heading is much further down.
_SIDE_BY_SIDE_CAPTION_GAP = 30.0
# Same band as structure._COLUMN_VOVERLAP_MIN: tables beside each other.
_TABLE_COLUMN_OVERLAP_MIN = 3.0


def _vertical_overlap(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> float:
    return min(a[3], b[3]) - max(a[1], b[1])


def _column_of(sec, split: float, rot: tuple | None) -> int | None:
    if not sec.lines:
        return None
    box = _section_region_bbox(sec)
    return _column_reading_key(sec.lines[0].bbox, split, rot, x_bbox=box)[0]


def _caption_after(
    sections: list, table_index: int, split: float, rot: tuple | None,
) -> int | None:
    """The paragraph immediately under a table, in the same column."""
    table = sections[table_index]
    nxt = table_index + 1
    if nxt >= len(sections):
        return None
    cap = sections[nxt]
    if (cap.kind == SectionKind.TABLE or not cap.lines
            or cap.page_num != table.page_num or not table.lines):
        return None
    if not _TABLE_CAPTION_RE.match(cap.text):
        return None
    table_box = _section_region_bbox(table)
    cap_box = _section_region_bbox(cap)
    if _column_of(cap, split, rot) != _column_of(table, split, rot):
        return None
    # A caption starts under the grid. A paragraph that overlaps the
    # table is body text, not the caption.
    gap = cap_box[1] - table_box[3]
    if gap < 0 or gap > _SIDE_BY_SIDE_CAPTION_GAP:
        return None
    return nxt


def _hoist_overlapping_multirow_pairs(
    sections: list,
    page_rotations: dict[int, tuple],
    column_splits: dict[int, float],
) -> None:
    """Read a side-by-side multirow pair left, then right, then continue.

    Column-major order finishes the left column, so the heading under the
    left table lands before the table beside it. When the two tables are
    the multirow_body family and their boxes overlap vertically, the right
    table and the caption under it move to just after the left table and
    its caption.
    """
    i = 0
    while i < len(sections):
        left = sections[i]
        split = column_splits.get(left.page_num)
        rot = page_rotations.get(left.page_num)
        if (left.table_source != "multirow_body" or not left.lines
                or split is None or rot is not None
                or _column_of(left, split, rot) != 0):
            i += 1
            continue
        left_box = _section_region_bbox(left)
        right_at = None
        for j in range(i + 1, len(sections)):
            other = sections[j]
            if other.page_num != left.page_num:
                break
            if other.table_source != "multirow_body" or not other.lines:
                continue
            if _column_of(other, split, rot) != 1:
                continue
            other_box = _section_region_bbox(other)
            if _vertical_overlap(left_box, other_box) >= _TABLE_COLUMN_OVERLAP_MIN:
                right_at = j
                break
        if right_at is None:
            i += 1
            continue
        left_cap = _caption_after(sections, i, split, rot)
        insert_at = i + 1
        if left_cap is not None and left_cap < right_at:
            insert_at = left_cap + 1
        # Right-column text above this table is already in front of it.
        # Hoisting would place the table before that text.
        if any(_column_of(sections[k], split, rot) == 1
               for k in range(insert_at, right_at)):
            i += 1
            continue
        right_cap = _caption_after(sections, right_at, split, rot)
        move = [right_at]
        if right_cap is not None:
            move.append(right_cap)
        moved = [sections[k] for k in move]
        for k in reversed(move):
            del sections[k]
        insert_at = i + 1
        if left_cap is not None and left_cap < right_at:
            insert_at = left_cap + 1
        for offset, sec in enumerate(moved):
            sections.insert(insert_at + offset, sec)
        i = insert_at + len(moved)


def _column_aware_sort(
    blocks: list,
    page_widths: dict[int, float],
    page_rotations: dict[int, tuple] | None = None,
    splits_out: dict[int, float] | None = None,
) -> frozenset[int]:
    """Sort blocks by reading order: page, then column (if two-column), then y.

    For two-column pages the left column is emitted entirely before the
    right column, preserving within-column y-order.  Single-column pages
    fall back to simple y-midpoint sorting (the P3625R1 fix).

    Rotated pages (page_rotations maps page -> rotation matrix) sort by
    the reading-space y-midpoint: block bboxes stay in unrotated page
    space, where the raw y-order does not match visual reading order.

    Returns the pages that were sorted column-first. This is the one
    definition of "two-column page" downstream: detect_tables receives
    exactly the set this sort acted on, so a page can never arrive in
    column order while being treated as single-column, or the reverse
    (p4098r1 p.4/5 did, when the set was computed on the raw blocks
    where the centred page number still filled the gutter).
    """
    page_blocks: dict[int, list] = {}
    for b in blocks:
        page_blocks.setdefault(b.page_num, []).append(b)

    rotations = page_rotations or {}
    splits: dict[int, float | None] = {}
    for pg, pblocks in page_blocks.items():
        if pg in rotations:
            # Column detection works on page-space x, which is
            # meaningless on rotated pages; sort_key short-circuits
            # before reading splits for these pages.
            continue
        pw = page_widths.get(pg, 612.0)
        splits[pg] = _detect_column_split(pblocks, pw)

    def sort_key(b):
        pg = b.page_num
        rot = rotations.get(pg)
        if rot is not None:
            _, ry = _rot_midpoint(b.bbox, rot)
            return (pg, 0, ry)
        y_mid = (b.bbox[1] + b.bbox[3]) / 2
        split = splits.get(pg)
        if split is not None:
            x_mid = (b.bbox[0] + b.bbox[2]) / 2
            col = 0 if x_mid < split else 1
            return (pg, col, y_mid)
        return (pg, 0, y_mid)

    blocks.sort(key=sort_key)
    found = frozenset(pg for pg, split in splits.items() if split is not None)
    if splits_out is not None:
        splits_out.clear()
        for pg in found:
            split = splits[pg]
            if split is not None:
                splits_out[pg] = split
    return found


def _get_page0_text_colors(page) -> dict[float, float]:
    """Map y-positions to text lightness using texttrace space-color proxy.

    Type 3 fonts report black for all glyphs. Space characters (type=0)
    leak the true graphics-state fill color. Returns {rounded_y: lightness}
    where lightness is 0.0 (black) to 1.0 (white).
    """
    colors: dict[float, float] = {}
    for span in page.get_texttrace():
        if span.get("type") != 0:
            continue
        color = span.get("color")
        if color is None:
            continue
        chars = span.get("chars", [])
        if not chars:
            continue
        y = round(chars[0][2][1])
        if isinstance(color, (tuple, list)) and len(color) >= 3:
            lightness = sum(color[:3]) / 3.0
        elif isinstance(color, (int, float)):
            lightness = float(color)
        else:
            continue
        colors[y] = lightness
    return colors


_SLIDE_DECK_MAX_WIDTH = 600
_SLIDE_DECK_LANDSCAPE_FRACTION = 0.8
_STANDARDS_DRAFT_MIN_PAGES = 200


def _is_slide_deck(doc) -> bool:
    """Detect presentation / slide-deck PDFs from page geometry.

    Two rules, either is sufficient:

    1. At least :data:`_SLIDE_DECK_LANDSCAPE_FRACTION` of pages are
       landscape AND narrower than :data:`_SLIDE_DECK_MAX_WIDTH`. This
       catches classic Beamer / Keynote 4:3 decks where the small
       page width is itself diagnostic (a portrait title page is
       fine).
    2. Every page in the document is landscape. This catches modern
       widescreen decks (720x405, 960x540, 1024x768, 1280x720,
       1920x1080) that exceed the width cap of rule 1. Strict
       all-landscape avoids false positives on mixed-orientation
       technical documents (e.g. N5028 - 105/114 landscape A4 pages,
       but the 9 portrait pages keep it out of the deck bucket).
    """
    if doc.page_count == 0:
        return False
    # Rule 1: small-width landscape dominant.
    small_landscape_count = 0
    all_landscape = True
    for pg_num in range(doc.page_count):
        r = doc[pg_num].rect
        if r.width <= r.height:
            all_landscape = False
        elif r.width < _SLIDE_DECK_MAX_WIDTH:
            small_landscape_count += 1
    if small_landscape_count / doc.page_count >= _SLIDE_DECK_LANDSCAPE_FRACTION:
        return True
    # Rule 2: every page is landscape (any width).
    return all_landscape


def _is_standards_draft(doc) -> bool:
    """Detect standards drafts by page count (>= 200 pages)."""
    return doc.page_count >= _STANDARDS_DRAFT_MIN_PAGES


def _make_image_section(img: ExtractedImage) -> Section:
    """Build a :class:`SectionKind.IMAGE` Section from one extraction record.

    Section.text and the per-path text fields are intentionally empty
    (plan N4): an image has no text content, and Section.text drives
    consumers like ``qa.compute_metrics`` whose word counts would be
    inflated by alt text. The canonical alt-text source is
    ``image_ref.suggested_alt``, read by the emit step.

    Confidence keys off ``img.source``: raster XObjects carry HIGH
    (the bytes are unambiguously a figure), vector clusters carry
    MEDIUM (the heuristic that grouped path operators into a figure
    is single-signal and uncertain - see the vector-extraction plan
    section 1.2).
    """
    confidence = Confidence.MEDIUM if img.source == "vector" else Confidence.HIGH
    return Section(
        kind=SectionKind.IMAGE,
        text="",
        confidence=confidence,
        page_num=img.page - 1,  # Section.page_num is 0-based
        image_ref=img,
    )


# Threshold for the structural-overlap filter (see
# :func:`_filter_vector_images_against_structural`). A vector
# ExtractedImage whose bbox overlaps a TABLE or CODE section by at
# least this fraction of the image area is treated as a duplicate of
# the structural representation and dropped. 0.5 is conservative
# enough that a real figure with a stray code line at one edge stays
# kept, while catching the calibrated false-positive cases:
#
# - P4003R1 page 8 comparison table (4 per-column vector PNGs
#   each ~100% overlapping the detected TABLE bbox).
# - P4003R1 pages 67 and 69 code-block backgrounds (vector PNGs
#   ~100% overlapping the CODE section the text path produces).
_STRUCTURAL_OVERLAP_THRESHOLD = 0.5

# Cross-page structural dedup: a vector image at the very top of a page
# is treated as a possible overflow continuation of a table from the
# prior page. Two guards work together:
#
# 1. The image's y0 must be within _NEAR_PAGE_TOP_PT of the page top --
#    the confirmed cases all have y0 = 57 pt; 75 pt gives safe margin.
# 2. The prior-page section's y1 must reach _CROSS_PAGE_STRUCTURAL_BOTTOM_MIN_PT
#    -- only structural sections that actually extend to the bottom of the
#    prior page can overflow. Applies to both TABLE and CODE sections.
#    All confirmed cases have table y1 ≈ 759 pt; 650 pt is safe for both
#    US Letter (792 pt) and A4 (842 pt) page heights.
_NEAR_PAGE_TOP_PT = 75.0
_CROSS_PAGE_STRUCTURAL_BOTTOM_MIN_PT = 650.0

# Thresholds for the vector-image dedup filter (see
# :func:`_filter_overlapping_vector_images`). A small vector image
# whose bbox overlaps a larger vector image's bbox by at least this
# fraction of the small image's area AND whose area is at most
# :data:`_OVERLAPPING_VECTOR_AREA_RATIO` of the larger image's area
# is treated as a detail crop of content already in the larger
# image and dropped. Calibrated against P4003R1 page 13's fig13-2
# (87x90pt small image, 40% inside fig13-1 at 481x256pt, area
# ratio 6.3% - clearly a redundant detail crop).
#
# The area-ratio guard prevents two genuinely adjacent figures of
# similar size (e.g. side-by-side panels) from being deduped just
# because their bboxes happen to overlap.
_OVERLAPPING_VECTOR_THRESHOLD = 0.30
_OVERLAPPING_VECTOR_AREA_RATIO = 0.20

# Threshold for the text-inside-vector dedup filter (see
# :func:`_filter_sections_inside_vector_images`). A non-structural
# section whose bbox is at least this fraction inside a surviving
# vector image's bbox is treated as duplicate content (the same
# text is already rasterised into the PNG) and dropped from the
# section list. TABLE, CODE, and IMAGE sections are never filtered
# - they are structural representations that stay regardless.
_SECTION_INSIDE_VECTOR_THRESHOLD = 0.5

# Threshold for the section-level CODE / TABLE drop inside the
# unextended vector cluster bbox. When a section's bbox is at least
# this fraction inside a vector's ``im.bbox`` (UNEXTENDED, no caption
# band), the whole section is dropped. The 0.5 vs 0.8 split is
# deliberate: the per-line filter uses the lower threshold because a
# line that is half inside a cluster is most likely the cluster's own
# baked-in label; a structural CODE / TABLE block that genuinely
# belongs to body content rarely overlaps a figure by more than 50%
# without being a real duplicate. Calibrated against P3127R1 page 6's
# set-description ``cpp`` block (overlap fraction 1.0 against the
# cluster bbox).
_STRUCTURAL_INSIDE_VECTOR_THRESHOLD = 0.8

# Possible-table marks (L5): content a reader proposed as a table that is not
# emitted as one. The reason travels in Section.metadata["possible_table"].
# Recorded for a rotated page the drawn-rule readers skip.
_ROTATED_NOT_READ = "rotated page: not read by the drawn-rule readers"
_MARK_DOT_LEADER = "a table with dot leaders, demoted as contents"
_MARK_FALSE_POSITIVE = "a table the classifier judged not a table, kept as text"
# Removed-content entries: examples shown per entry, and their length.
_DISCARD_EXAMPLES = 3
_DISCARD_DETAIL_CHARS = 120

# Depth of the caption band below a vector cluster, used for the
# section-level caption-shaped drop and sub-caption capture (NOT for
# rasterisation, NOT for the per-line PARAGRAPH filter, NOT for the
# CODE/TABLE drop above). Defined by reference to
# ``_CAPTION_SEARCH_RADIUS_BELOW_PT`` so the body-drop predicate covers
# everything the alt-text attribution predicate can attribute. A
# shallower band would let ``_caption_for`` mark a caption as alt-text
# while the body-drop refused to fire, duplicating the caption as both
# alt-text and body. A future change that wants the constants to
# diverge must also change ``_line_in_caption_band`` (and
# ``_caption_for``) in the same commit.
_FIGURE_CAPTION_BAND_BELOW_PT = _CAPTION_SEARCH_RADIUS_BELOW_PT

# Sub-caption line shape: ``(a) text...`` / ``(b) text...``. The
# captured letter is used for stable alphabetical ordering of the
# rendered sub-caption paragraphs. Only matches a single lowercase
# letter, matching the WG21 convention; uppercase letters would
# misfire on body prose like ``(A) test case`` and are intentionally
# excluded.
_SUB_CAPTION_RE = re.compile(r"^\s*\(([a-z])\)\s+(.+)$")


def _line_in_caption_band(
    line_bbox: tuple[float, float, float, float],
    im_bbox: tuple[float, float, float, float],
) -> bool:
    """Return True if ``line_bbox.y0`` lies in the caption band of ``im_bbox``.

    The band runs from ``im_bbox.y1`` (exclusive lower edge of the
    image) to ``im_bbox.y1 + _FIGURE_CAPTION_BAND_BELOW_PT`` and is
    **y-only**, with no horizontal gate. This is identical to the
    predicate :func:`images._caption_for` uses to attribute alt-text
    to an image; both use the same numeric depth
    (``_FIGURE_CAPTION_BAND_BELOW_PT == _CAPTION_SEARCH_RADIUS_BELOW_PT``)
    and the same y-only shape so the body-drop and alt-text attribution
    always fire on the same set of caption lines.

    **Predicate-equality invariant**: this helper drives the
    **overall-caption section drop** (the ``_CAPTION_LABEL_RE`` path),
    which must fire on exactly the same set of lines
    :func:`images._caption_for` attributes - otherwise a caption can
    become both alt-text AND a leaked body paragraph. Any refactor
    that adds a horizontal multi-column gate must add it to BOTH
    this helper and :func:`images._caption_for` in the same commit.

    The sub-caption capture path uses the wider
    :func:`_line_in_caption_region` (cluster bbox + band) so that a
    sub-caption between stacked sub-figures (P3127R1 Figure 1's
    ``(a)`` caption is the canonical case) is captured + re-emitted
    as italic alongside the below-cluster ``(b)``. Sub-captions are
    never alt-text'd by ``_caption_for``, so the wider predicate
    does not reopen any duplication invariant.

    The boundary semantics match :func:`images._caption_for` exactly:
    ``im_y1 <= line.y0 <= im_y1 + radius`` (inclusive on both ends).
    """
    return im_bbox[3] <= line_bbox[1] <= im_bbox[3] + _FIGURE_CAPTION_BAND_BELOW_PT


def _line_in_caption_region(
    line_bbox: tuple[float, float, float, float],
    im_bbox: tuple[float, float, float, float],
) -> bool:
    """Sub-caption containment: cluster bbox UNION caption band below.

    Wider than :func:`_line_in_caption_band`: this returns True when
    ``line_bbox.y0`` is anywhere in
    ``[im_bbox.y0, im_bbox.y1 + _FIGURE_CAPTION_BAND_BELOW_PT]``,
    covering both "between stacked sub-figures, inside the cluster"
    and "below the cluster, in the caption band".

    Why a separate predicate: WG21 multi-sub-figure layouts (P3127R1
    Figure 1 is the canonical case) place one sub-caption between
    the sub-figures (PDF y inside the cluster bbox) and another
    below both sub-figures (in the caption band). For visual
    symmetry, both should be captured and re-emitted as italic
    paragraphs after the IMAGE; the alternative is asymmetric
    markdown where ``(a)`` lives inside the PNG and ``(b)`` lives
    in italic text.

    This helper is used **only** by the vector branch of the
    sub-caption capture path (via :func:`_sub_caption_owns`). The
    overall-caption drop (the ``_CAPTION_LABEL_RE`` path) must stay
    on :func:`_line_in_caption_band` so it remains predicate-equal to
    :func:`images._caption_for`.
    """
    return im_bbox[1] <= line_bbox[1] <= im_bbox[3] + _FIGURE_CAPTION_BAND_BELOW_PT


def _sub_caption_owns(
    line_bbox: tuple[float, float, float, float],
    im: ExtractedImage,
) -> bool:
    """Does image ``im`` own the sub-caption line at ``line_bbox``?

    The owning predicate depends on the image source:

    - **Vector** clusters use the wider :func:`_line_in_caption_region`
      (cluster interior UNION band below). A stacked-sub-figure layout
      (P3127R1 Figure 1) places one sub-caption *between* the
      sub-figures, inside the cluster bbox, so the interior must be in
      scope to capture it.
    - **Raster** images use the narrow :func:`_line_in_caption_band`
      (band below only). A raster bbox is a resource-dictionary
      rectangle that can be hundreds of points tall, and each raster is
      its own :class:`ExtractedImage` - there is never an interior
      sub-caption to rescue, only the band-below caption. Using the
      wide region for raster would capture any ``(a)``-shaped body
      paragraph anywhere in the raster's vertical span and relocate it
      as italic text after the image; ``(a)``/``(b)`` enumerations are
      common in WG21 prose, so the interior must stay out of scope.
    """
    if im.source == "vector":
        return _line_in_caption_region(line_bbox, im.bbox)
    return _line_in_caption_band(line_bbox, im.bbox)


def _normalize_caption(text: str) -> str:
    """Normalize a caption string for equality comparison.

    Used by the overall-caption section drop to gate the drop on
    ``_normalize_caption(sec.text) == _normalize_caption(im.suggested_alt)``.
    The gate is the content-loss guard: it skips the drop when the
    body paragraph carries text that the alt-text does not (the
    merged-continuation case where the structure pass joined a
    caption line with subsequent prose).

    Conservative by design. Only normalizes whitespace:

    - All whitespace runs (including NBSP U+00A0 and newlines injected
      by the structure pass's wrap-join) collapse to a single space.
      ``str.split()`` without arguments treats U+00A0 as whitespace,
      so no explicit NBSP replacement is needed.
    - Leading and trailing whitespace are stripped.

    Explicitly does NOT lowercase, strip punctuation, normalize
    quotes/dashes, or strip the ``Figure N:`` prefix. A trailing
    period that the body carries but the alt-text omits is a real
    difference; the equality fails and the drop is skipped. Missing
    a leak is preferable to losing content.
    """
    return " ".join(text.split())


def _section_bbox(
    sec: Section,
) -> tuple[float, float, float, float] | None:
    """Return the union bbox of a section's lines, or None if it has none."""
    if not sec.lines:
        return None
    bbox = sec.lines[0].bbox
    for line in sec.lines[1:]:
        bbox = (
            min(bbox[0], line.bbox[0]),
            min(bbox[1], line.bbox[1]),
            max(bbox[2], line.bbox[2]),
            max(bbox[3], line.bbox[3]),
        )
    return bbox


def _bbox_overlap_fraction(
    image_bbox: tuple[float, float, float, float],
    section_bbox: tuple[float, float, float, float],
) -> float:
    """Intersection area divided by the *first* argument's area.

    The math is symmetric: ``intersection / area(first_arg)``. Both
    inverted call patterns are used in this module:

    - ``_bbox_overlap_fraction(image_bbox, section_bbox)`` -
      "fraction of the *image* inside the section." Used by the
      structural-overlap filter
      (``_filter_vector_images_against_structural``) to drop a vector
      whose drawing region is mostly covered by a TABLE or CODE
      section.
    - ``_bbox_overlap_fraction(section_bbox, image_bbox)`` - "fraction
      of the *section* inside the image." Used by the structural
      CODE / TABLE drop inside
      ``_filter_sections_inside_vector_images`` and by the per-line
      filter.

    Returns 0.0 when the first argument has non-positive area.
    """
    ix0, iy0, ix1, iy1 = image_bbox
    sx0, sy0, sx1, sy1 = section_bbox
    overlap_w = max(0.0, min(ix1, sx1) - max(ix0, sx0))
    overlap_h = max(0.0, min(iy1, sy1) - max(iy0, sy0))
    image_area = (ix1 - ix0) * (iy1 - iy0)
    if image_area <= 0:
        return 0.0
    return (overlap_w * overlap_h) / image_area


def _filter_vector_images_against_structural(
    images: list[ExtractedImage],
    sections: list[Section],
    *,
    threshold: float = _STRUCTURAL_OVERLAP_THRESHOLD,
) -> tuple[list[ExtractedImage], list[Section], int]:
    """Drop vector ExtractedImage records (and their IMAGE sections)
    that overlap a TABLE or CODE section by more than ``threshold``.

    A vector PNG that lands on top of a structural section (TABLE or
    CODE) duplicates content the markdown already renders structurally
    (as a markdown table or fenced code block). Removing the vector
    duplicate keeps the output clean and resolves the calibrated
    false-positive classes documented in:

    - bug-p4003r1-pg8-table-extraction.md (per-column vector PNGs of
      a comparison table).
    - improvements.md section 4.7 (vector PNGs duplicating code-block
      content on P4003R1 pages 67 and 69).
    - P2583R2 figs 6-1, 21-1, 21-2, 21-3 and P4007R0 fig 24-1 (table
      overflow to the top of the next page; see cross-page check below).

    When a vector image is near the top of its page
    (``y0 <= _NEAR_PAGE_TOP_PT``), the filter also checks TABLE and CODE
    sections from the prior page whose bottom edge reaches
    ``_CROSS_PAGE_STRUCTURAL_BOTTOM_MIN_PT``. These are overflow
    continuations of a structural section, not independent figures: a
    table that spans most of page N-1 renders its tail at the very top
    of page N as a vector cluster with the same x-range and near-zero y.

    Raster images are not filtered; an embedded raster image that
    overlaps a code block or table is presumed intentional (annotated
    diagram, embedded screenshot).

    Returns ``(filtered_images, filtered_sections, dropped_count)``.
    The dropped count is used to adjust the per-paper vector
    uncertainty marker's ``kept`` value so its disclosure matches the
    actual markdown content.
    """
    # Per-page body x-range from non-table, non-image content. Used to
    # inflate TABLE bboxes for the overlap test: table Section bboxes are
    # the union of cell-text bboxes, which are tight to glyphs and ignore
    # column padding. A vector cluster sitting in a table's column-padding
    # whitespace (canonical case: P4003R1 page 72 right column, vector at
    # x=326-538 vs table text x_end=409) would otherwise overlap below
    # the 0.5 threshold and survive. Stretching to the body x-range
    # restores the full visual column extent.
    body_x_by_page: dict[int, tuple[float, float]] = {}
    for sec in sections:
        if sec.kind in (SectionKind.TABLE, SectionKind.IMAGE):
            continue
        page = sec.page_num + 1
        for line in sec.lines:
            bx0, bx1 = line.bbox[0], line.bbox[2]
            prev = body_x_by_page.get(page)
            if prev is None:
                body_x_by_page[page] = (bx0, bx1)
            else:
                body_x_by_page[page] = (min(prev[0], bx0), max(prev[1], bx1))

    structural_bboxes_by_page: dict[int, list[tuple[float, float, float, float]]] = {}
    for sec in sections:
        if sec.kind not in (SectionKind.TABLE, SectionKind.CODE):
            continue
        bbox = _section_bbox(sec)
        if bbox is None:
            continue
        # ExtractedImage.page is 1-based; Section.page_num is 0-based.
        page = sec.page_num + 1
        if sec.kind == SectionKind.TABLE:
            body_x = body_x_by_page.get(page)
            if body_x is not None:
                bbox = (
                    min(bbox[0], body_x[0]),
                    bbox[1],
                    max(bbox[2], body_x[1]),
                    bbox[3],
                )
        structural_bboxes_by_page.setdefault(page, []).append(bbox)

    if not structural_bboxes_by_page:
        return images, sections, 0

    dropped_ids: set[int] = set()
    kept_images: list[ExtractedImage] = []
    for im in images:
        if im.source != "vector":
            kept_images.append(im)
            continue
        page_bboxes = structural_bboxes_by_page.get(im.page, ())
        if im.bbox[1] <= _NEAR_PAGE_TOP_PT:
            prior_bboxes = [
                b
                for b in structural_bboxes_by_page.get(im.page - 1, ())
                if b[3] >= _CROSS_PAGE_STRUCTURAL_BOTTOM_MIN_PT
            ]
            page_bboxes = (*page_bboxes, *prior_bboxes)
        if any(_bbox_overlap_fraction(im.bbox, b) >= threshold for b in page_bboxes):
            dropped_ids.add(id(im))
            continue
        kept_images.append(im)

    if not dropped_ids:
        return images, sections, 0

    kept_sections = [
        s
        for s in sections
        if not (
            s.kind == SectionKind.IMAGE
            and s.image_ref is not None
            and id(s.image_ref) in dropped_ids
        )
    ]
    return kept_images, kept_sections, len(dropped_ids)


def _filter_overlapping_vector_images(
    images: list[ExtractedImage],
    sections: list[Section],
    *,
    overlap_threshold: float = _OVERLAPPING_VECTOR_THRESHOLD,
    area_ratio: float = _OVERLAPPING_VECTOR_AREA_RATIO,
) -> tuple[list[ExtractedImage], list[Section], int]:
    """Drop vector images that are detail crops of larger vector images.

    A vector image A is treated as a redundant detail crop of a
    larger vector image B when:

    - A and B are on the same page,
    - A's bbox overlaps B's bbox by at least ``overlap_threshold``
      of A's area, AND
    - A's area is at most ``area_ratio`` of B's area (i.e. A is
      MUCH smaller than B - the area-ratio guard distinguishes a
      detail crop from a genuinely adjacent similar-sized figure).

    Resolves the calibrated false-positive case where a small
    cluster ends up adjacent to a much larger merged figure on the
    same page and shows duplicate content (P4003R1 page 13's
    fig13-2 "run_async legend" box overlapping fig13-1 main diagram
    at ~40% of fig13-2's area, area ratio 6.3%).

    The corresponding IMAGE section in ``sections`` (placed by
    :func:`_insert_image_sections`) is also removed so the markdown
    doesn't reference a dropped image.

    Returns ``(filtered_images, filtered_sections, dropped_count)``.
    """
    # Group vector images by page; sort each page's list by area
    # descending so we test smaller-vs-larger pairs.
    vectors_by_page: dict[int, list[int]] = {}
    for i, im in enumerate(images):
        if im.source != "vector":
            continue
        vectors_by_page.setdefault(im.page, []).append(i)

    def _area(im: ExtractedImage) -> float:
        return (im.bbox[2] - im.bbox[0]) * (im.bbox[3] - im.bbox[1])

    dropped_ids: set[int] = set()
    for page_indices in vectors_by_page.values():
        # Sort descending by area so the largest is considered first.
        sorted_idx = sorted(
            page_indices,
            key=lambda i: _area(images[i]),
            reverse=True,
        )
        # Larger images are "potential containers"; smaller images may
        # be detail crops. Compare each smaller against each kept
        # larger one. ``kept_local`` is the surviving subset on this
        # page that smaller images get tested against.
        kept_local: list[int] = []
        for i in sorted_idx:
            im = images[i]
            im_area = _area(im)
            is_dup = False
            for j in kept_local:
                larger = images[j]
                larger_area = _area(larger)
                if im_area > area_ratio * larger_area:
                    # Not "much smaller" than larger - keep both.
                    continue
                if _bbox_overlap_fraction(im.bbox, larger.bbox) >= overlap_threshold:
                    is_dup = True
                    break
            if is_dup:
                dropped_ids.add(id(im))
            else:
                kept_local.append(i)

    if not dropped_ids:
        return images, sections, 0

    kept_images = [im for im in images if id(im) not in dropped_ids]
    kept_sections = [
        s
        for s in sections
        if not (
            s.kind == SectionKind.IMAGE
            and s.image_ref is not None
            and id(s.image_ref) in dropped_ids
        )
    ]
    return kept_images, kept_sections, len(dropped_ids)


def _filter_sections_inside_vector_images(
    images: list[ExtractedImage],
    sections: list[Section],
    *,
    threshold: float = _SECTION_INSIDE_VECTOR_THRESHOLD,
    structural_threshold: float = _STRUCTURAL_INSIDE_VECTOR_THRESHOLD,
) -> tuple[list[Section], dict[int, list[tuple[str, str]]]]:
    """Drop text duplicated by a surviving image; capture sub-captions.

    The image already shows the line's text content as rasterised
    pixels (a label rendered inside a diagram is baked into the PNG
    by ``page.get_pixmap``; a raster figure's caption is attributed
    as alt-text by :func:`images._caption_for`), so re-emitting the
    same line as body markdown produces visible duplication. The
    filter handles four cases, split across two image scopes:

    **Vector-only behaviours** (raster bboxes are resource-dictionary
    rectangles, not claims of region ownership over overlapping body
    text, so they would risk dropping unrelated columns or
    watermark-backdropped content):

    1. **CODE / TABLE sections wholly inside a vector** (Fix A):
       when a section's bbox is at least ``structural_threshold``
       inside the *unextended* ``im.bbox``, the whole section is
       dropped. Calibrated against P3127R1 page 6's set-description
       ``cpp`` block (entirely inside the cluster). The check uses
       ``im.bbox`` (not the extended caption band) so a real CODE
       listing immediately below a figure - the figure-then-example
       pattern common in WG21 papers - is not dropped.
    4. **Other PARAGRAPH sections**: per-line filter against the
       *unextended* ``im.bbox`` only. A line whose bbox is at least
       ``threshold`` inside any vector's drawing region is dropped;
       the section is rebuilt from surviving lines (or removed
       entirely when no lines survive). Body lines that fall in the
       caption band but outside the unextended cluster bbox are
       KEPT - the band is reserved for the caption-shaped section
       drops below.

    **Caption-related behaviours** (raster AND vector; HTML images
    skipped via the ``(0,0,0,0)`` bbox sentinel):

    2. **Sub-caption sections** (``(a) ... / (b) ...``): when a
       PARAGRAPH section's first line matches ``_SUB_CAPTION_RE`` AND
       ``_line_in_caption_region(first_line.bbox, im.bbox)`` is True
       for some image, the section is captured against the owning
       image (upper-image wins by the y0-sorted iteration order) and
       dropped. Captures are returned in the second tuple element
       so the caller can rebuild the affected
       :class:`ExtractedImage` records via ``dataclasses.replace``
       and insert italicised PARAGRAPH sections immediately after
       the IMAGE section.
    3. **Overall-caption sections** (``Figure N: ...``): when a
       PARAGRAPH *or* HEADING section's first line matches
       ``_CAPTION_LABEL_RE`` AND ``_line_in_caption_band(...)`` is
       True for some image AND ``_normalize_caption(sec.text)`` equals
       ``_normalize_caption(im.suggested_alt)`` for the SAME image,
       the whole section is dropped. The equality gate is the
       content-loss guard: ``_caption_for`` captures only the first
       text line, so a multi-line wrapped caption or a caption joined
       with trailing prose by the structure pass produces a body
       paragraph longer than the alt-text - the gate then skips the
       drop, the duplicate survives as body text, and no content is
       lost. HEADING is included because WG21 figure captions are
       sometimes bold or distinct-font and trip the heading
       heuristic.

    IMAGE sections are always kept verbatim.

    **Predicate semantics for the overall-caption drop**. Originally
    the body-drop fired on EXACTLY the set of caption lines
    :func:`images._caption_for` attributes (set equality between the
    body-drop predicate and the alt-text predicate). With the
    equality gate the relationship weakens to a **subset**: the
    body-drop fires on a subset of the lines ``_caption_for``
    attributes (specifically, those whose body paragraph still
       equals the alt-text). The direction is safe - the body-drop is
       strictly more conservative; a caption can never be both
       attributed as alt-text AND retained in the body - but a future
       refactor that adds a horizontal multi-column gate must add it to
       BOTH ``_line_in_caption_band`` and ``images._caption_for`` in
       the same commit. Emit keys on ``caption_body_dropped`` (#408),
       which extends the invariant to the markdown surface: when the
       body caption section reaches this filter, the caption appears
       either in the kept body or as the italic paragraph, never both.
       (A caption whose body section was already stripped upstream of
       this filter leaves no markdown trace - the sidecar file and
       ``suggested_alt`` still carry it.)

    Returns ``(filtered_sections, captures_by_image_id,
    dropped_caption_ids)``. The captures dict maps ``id(image)`` to a
    list of ``(letter, full_section_text)`` tuples; the caller is
    responsible for threading these into the matching
    :class:`ExtractedImage` records (and into each IMAGE section's
    ``image_ref``). The third element holds the ``id(image)`` of every
    image whose overall body caption was dropped by the equality gate;
    the caller threads it into ``ExtractedImage.caption_body_dropped``
    so emit re-emits the caption as an italic paragraph exactly when
    the body copy is actually gone (#408).
    """
    # Index images twice. ``vector_images_by_page`` powers Fix A
    # (CODE/TABLE drop inside the cluster) and the per-line filter -
    # both rely on the fact that a vector cluster's bbox is derived
    # from the drawing operations that compose the figure, so any
    # text inside that bbox is the figure's own content.
    # ``caption_eligible_by_page`` powers the caption-shaped drops
    # and sub-caption capture - both fire on the y-only caption band
    # below an image, which works identically for raster and vector
    # because ``_caption_for`` attributes captions for both. Raster
    # images participate only in caption-related cleanup; their bbox
    # is just a resource-dictionary rectangle and does not claim
    # region ownership over overlapping body text (a raster bbox can
    # cover unrelated columns or a watermark backdrop), so Fix A and
    # the per-line filter remain vector-only.
    #
    # Sort by ``(page, im.bbox.y0, im.bbox.x0)`` so that when two
    # images' caption bands overlap, the upper one (smaller ``y0``)
    # wins attribution. HTML images carry the sentinel
    # ``(0, 0, 0, 0)`` bbox and would false-fire the y-only band
    # predicate, so they are skipped at indexing time.
    vector_images_by_page: dict[int, list[ExtractedImage]] = {}
    caption_eligible_by_page: dict[int, list[ExtractedImage]] = {}
    for im in images:
        if im.bbox == (0.0, 0.0, 0.0, 0.0):
            continue
        caption_eligible_by_page.setdefault(im.page, []).append(im)
        if im.source == "vector":
            vector_images_by_page.setdefault(im.page, []).append(im)
    for page in caption_eligible_by_page:
        caption_eligible_by_page[page].sort(
            key=lambda im: (im.bbox[1], im.bbox[0]),
        )
    for page in vector_images_by_page:
        vector_images_by_page[page].sort(
            key=lambda im: (im.bbox[1], im.bbox[0]),
        )

    if not caption_eligible_by_page:
        return sections, {}, set()

    captures_by_id: dict[int, list[tuple[str, str]]] = {}
    dropped_caption_ids: set[int] = set()
    kept: list[Section] = []

    for sec in sections:
        # IMAGE always kept.
        if sec.kind == SectionKind.IMAGE:
            kept.append(sec)
            continue

        page = sec.page_num + 1
        page_vectors = vector_images_by_page.get(page, ())
        page_caption_eligible = caption_eligible_by_page.get(page, ())
        if not page_vectors and not page_caption_eligible:
            kept.append(sec)
            continue

        # 1. CODE / TABLE: drop if mostly inside the unextended
        #    cluster bbox. Lineless sections (``_section_bbox``
        #    returns None) are kept verbatim - we never crash on a
        #    section with no geometry.
        if sec.kind in (SectionKind.CODE, SectionKind.TABLE):
            sec_bbox = _section_bbox(sec)
            if sec_bbox is None:
                kept.append(sec)
                continue
            mostly_inside = any(
                _bbox_overlap_fraction(sec_bbox, im.bbox) >= structural_threshold
                for im in page_vectors
            )
            if mostly_inside:
                # recorded, never silent: the paper summary lists removed content
                current().record.exclude(
                    "vector-images", sec.page_num, sec_bbox,
                    f"{sec.kind.value} inside an extracted vector figure", "paths")
                current().discards.append((
                    "vector figure", f"a {sec.kind.value} section on page {sec.page_num + 1} lies "
                    "inside an extracted vector figure", sec.text[:_DISCARD_DETAIL_CHARS]))
                continue
            kept.append(sec)
            continue

        # 2/3. Caption-shaped section drops. Apply to PARAGRAPH,
        #     HEADING, and LIST; the regex is the content signal, the
        #     y-only band match is the geometry signal. LIST is included
        #     because the structure pass classifies "(a) text" lines as
        #     list items, which is the canonical sub-caption shape.
        #     Skipped for sections with no lines (no first-line bbox to test).
        if sec.kind in (SectionKind.PARAGRAPH, SectionKind.HEADING, SectionKind.LIST) and sec.lines:
            first_text = sec.lines[0].text.strip()
            first_bbox = sec.lines[0].bbox

            # 2. Sub-caption: capture + drop. Walks raster and
            #    vector together via ``page_caption_eligible`` -
            #    sub-captions sit in the caption band of any image,
            #    raster or vector, and the attribution is the upper
            #    image (smaller ``y0``) by the sort order built at
            #    indexing time. The owning predicate is source-aware
            #    (``_sub_caption_owns``): vector clusters use the wide
            #    cluster-interior-plus-band region so a sub-caption
            #    between stacked sub-figures (P3127R1 Figure 1's
            #    "(a)") is captured, while raster images use the
            #    narrow band-below-only region so an ``(a)``-shaped
            #    body paragraph inside a tall raster bbox is not
            #    relocated.
            sub_match = _SUB_CAPTION_RE.match(first_text)
            if (sub_match and first_bbox != (0, 0, 0, 0)
                    and (sec.kind is not SectionKind.LIST or len(sec.lines) == 1)):
                letter = sub_match.group(1)
                owner = next(
                    (im for im in page_caption_eligible
                     if _sub_caption_owns(first_bbox, im)),
                    None,
                )
                if owner is not None:
                    captures_by_id.setdefault(id(owner), []).append(
                        (letter, sec.text),
                    )
                    continue

            # 3. Overall caption: drop only when an image's caption
            #    band fires AND its ``suggested_alt`` matches the
            #    section text after whitespace normalization. The
            #    equality gate is the content-loss guard: when the
            #    structure pass merged the caption line with trailing
            #    prose into one paragraph, the body carries text the
            #    alt-text does not, and dropping the section would
            #    lose that prose. ``_caption_for`` captures only the
            #    first text line, so this case is real and surfaces
            #    in the corpus (P3100R4/R5/R6, P3064R3 Fig 5).
            if (_CAPTION_LABEL_RE.match(first_text)
                    and first_bbox != (0, 0, 0, 0)):
                sec_norm = _normalize_caption(sec.text)
                matched_im = next(
                    (im for im in page_caption_eligible
                     if _line_in_caption_band(first_bbox, im.bbox)
                     and _normalize_caption(im.suggested_alt) == sec_norm),
                    None,
                )
                if matched_im is not None:
                    # Record the drop so emit can re-emit the caption
                    # as an italic paragraph exactly when the body copy
                    # is actually gone (#408).
                    dropped_caption_ids.add(id(matched_im))
                    continue

        # 4. PARAGRAPH / UNCERTAIN: per-line filter against unextended bbox.
        # UNCERTAIN is included because dual-path disagreement on a region
        # inside a vector cluster (e.g. P3127R1 page 6's set-description
        # block) produces an UNCERTAIN section whose lines are still
        # geometrically inside the cluster and must be filtered.
        if sec.kind not in (SectionKind.PARAGRAPH, SectionKind.UNCERTAIN):
            kept.append(sec)
            continue
        if not sec.lines:
            kept.append(sec)
            continue

        page_bboxes = [im.bbox for im in page_vectors]
        kept_lines = []
        for line in sec.lines:
            line_bbox = line.bbox
            if line_bbox == (0, 0, 0, 0):
                kept_lines.append(line)
                continue
            if any(
                _bbox_overlap_fraction(line_bbox, ib) >= threshold for ib in page_bboxes
            ):
                continue
            kept_lines.append(line)

        if len(kept_lines) == len(sec.lines):
            kept.append(sec)
            continue
        if not kept_lines:
            continue  # all lines dropped
        new_text = "\n".join(line.text for line in kept_lines)
        kept.append(replace(sec, lines=kept_lines, text=new_text))

    return kept, captures_by_id, dropped_caption_ids


def _insert_image_sections(
    sections: list[Section],
    images: list[ExtractedImage],
) -> list[Section]:
    """Insert IMAGE sections into a sorted section list at the right y-position.

    Mirrors the table-insertion logic: walk the existing sections by
    ``(page_num, first_line.bbox[1])`` and slot each IMAGE in just
    before the first section that comes after it. Appends if the
    image is at end-of-document.
    """
    out = list(sections)
    for img in images:
        img_sec = _make_image_section(img)
        inserted = False
        for i, sec in enumerate(out):
            if sec.page_num > img_sec.page_num:
                out.insert(i, img_sec)
                inserted = True
                break
            if (
                sec.page_num == img_sec.page_num
                and sec.lines
                and sec.lines[0].bbox[1] > img.bbox[1]
            ):
                out.insert(i, img_sec)
                inserted = True
                break
        if not inserted:
            out.append(img_sec)
    return out


@dataclass
class PipelineResult:
    """Full output of the PDF conversion pipeline, used for QA scoring.

    Image fields:

    - ``images``: up to ``_MAX_IMAGES_PER_PAPER`` :class:`ExtractedImage`
      records, sorted by ``(page, bbox.y0, bbox.x0)``. The CLI consumes
      this list to persist bytes via ``backend.write_paper_image``.
      Always empty when ``skipped`` is True - early-exit paths discard
      any partial extraction state to avoid orphan PNGs on disk without
      a referencing markdown.
    - ``source_image_count``: unique-xref total for the source,
      regardless of the cap. Drives the CLI's "kept M of N" line.
    - ``images_truncated``: True iff ``source_image_count`` exceeded
      the cap and the emit step appended the truncation HTML comment.
    """

    md: str = ""
    prompts: list[str] | None = None
    sections: list[Section] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    page_count: int = 0
    nesting_corrections: int = 0
    readable: bool = True
    skipped: bool = False
    skip_reason: SkipReason | None = None
    images: list[ExtractedImage] = field(default_factory=list)
    source_image_count: int = 0
    images_truncated: bool = False
    vector_uncertainty: VectorUncertaintyStats | None = None
    glyph_stats: GlyphPassStats | None = None
    # Table readers and checks that raised during the run (runctx.RunContext.reader_error):
    # recorded instead of failing the paper, never swallowed silently.
    reader_errors: list[dict] = field(default_factory=list)
    # Content removed on purpose: (what, why, an example). Never silent.
    discards: list[tuple[str, str, str]] = field(default_factory=list)
    # The paper summary (summary.build); None for a skipped paper.
    summary: dict | None = None

    @classmethod
    def for_skip(
        cls,
        reason: SkipReason,
        *,
        page_count: int = 0,
        prompts: list[str] | None = None,
        readable: bool = True,
    ) -> "PipelineResult":
        """Construct a complete skip result.

        Single source of truth for exit-condition fields on early-exit
        paths; bypasses partial-build mutation. Named ``for_skip`` (not
        ``skipped``) to avoid shadowing the ``skipped`` dataclass field.
        """
        return cls(
            md="",
            prompts=prompts,
            page_count=page_count,
            readable=readable,
            skipped=True,
            skip_reason=reason,
            images=[],
        )


def _enforce_skip_contract(result: PipelineResult) -> PipelineResult:
    """Validate skip invariants before returning from :func:`run_pipeline`."""
    empty_md = not result.md.strip()
    if empty_md or not result.readable:
        if not result.skipped:
            _log.error(
                "PipelineResult skip contract violated: skipped=False "
                "readable=%s md_empty=%s",
                result.readable,
                empty_md,
            )
            raise AssertionError(
                "PipelineResult must set skipped=True when markdown is empty "
                "or readable is False"
            )
        if not isinstance(result.skip_reason, SkipReason):
            _log.error(
                "PipelineResult skip contract violated: invalid skip_reason=%r",
                result.skip_reason,
            )
            raise AssertionError(
                f"PipelineResult skip_reason must be a SkipReason member, "
                f"got {result.skip_reason!r}"
            )
    if result.skipped:
        if result.skip_reason is None:
            _log.error("PipelineResult skip contract violated: missing skip_reason")
            raise AssertionError(
                "PipelineResult skip_reason must be set when skipped=True"
            )
        if result.images:
            _log.error(
                "PipelineResult skip contract violated: skipped with %d images",
                len(result.images),
            )
            raise AssertionError(
                "PipelineResult images must be empty when skipped=True"
            )
        if result.md.strip():
            _log.error(
                "PipelineResult skip contract violated: skipped with non-empty md"
            )
            raise AssertionError("PipelineResult md must be empty when skipped=True")
    return result


def _parse_pdf_info_date(raw: str) -> str:
    """Parse a PDF info-dict date (``D:YYYYMMDDHHmmSS...``) into ``YYYY-MM-DD``."""
    if not raw:
        return ""
    raw = raw.strip()
    if raw.startswith("D:"):
        raw = raw[2:]
    if len(raw) >= 8 and raw[:8].isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    return ""


def _insert_after_front_matter(md: str, line: str) -> str:
    """Insert one line after the YAML front matter (at the top when there is
    none), and point the uncertainty markers at their text again."""
    if md.startswith("---\n") and "\n---\n" in md[4:]:
        end = md.index("\n---\n", 4) + len("\n---\n")
        md = md[:end] + "\n" + line + "\n" + md[end:]
    else:
        md = line + "\n\n" + md
    return renumber_uncertain_markers(md)


def _in_run_scope(fn):
    """Run ``fn`` inside a fresh run context (``runctx.run_scope``): everything the
    table readers record belongs to this call only, also when papers convert on
    several threads. Reader errors recorded during the run are returned on
    ``PipelineResult.reader_errors``."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs) -> PipelineResult:
        with run_scope() as ctx:
            result = fn(*args, **kwargs)
            result.reader_errors = list(ctx.record.errors)
            result.discards = list(ctx.discards)
        return result
    return wrapper


@_in_run_scope
def run_pipeline(
    path: Path,
    *,
    ml_tables: bool = False,
    visualize: bool = False,
    extract_vector: bool = False,
    whiteout_text: bool = False,
) -> PipelineResult:
    """Run the full PDF conversion pipeline, returning all intermediate data.

    ``extract_vector`` opts in to vector-figure extraction (v2.0 default
    off; see :mod:`tomd.lib.pdf.vector_images` for the heuristic and
    :mod:`packages.tomd.improvements` for the layout-aware successor).
    When False, the per-page driver is not called and per-page candidate
    lists carry only the raster path's output - byte-identical to the
    pre-v2 behaviour.

    ``whiteout_text`` is forwarded to the vector driver and has no
    effect when ``extract_vector`` is False.
    labels inside vector figures render as pixels alongside body text.
    """
    path = Path(path)
    result = PipelineResult()
    doc = None
    vector_stats = _VectorExtractionStats() if extract_vector else None
    with _FITZ_LOCK:  # see _fitz_lock.py for why this lock is required
        try:
            doc = fitz.open(str(path))
            page_count = doc.page_count
            if page_count == 0:
                return _enforce_skip_contract(
                    PipelineResult.for_skip(SkipReason.EMPTY_PDF, page_count=0)
                )

            if _is_slide_deck(doc):
                _log.info("Detected slide deck (%d pages), skipping conversion",
                           page_count)
                return _enforce_skip_contract(PipelineResult.for_skip(
                    SkipReason.SLIDE_DECK,
                    page_count=page_count,
                    prompts=["# tomd - Slide Deck Detected\n\n"
                        "This PDF appears to be a presentation / slide deck. "
                        "tomd does not convert slide decks to Markdown.\n"],
                ))

            if _is_standards_draft(doc):
                _log.info("Detected standards draft (%d pages), skipping conversion",
                           page_count)
                return _enforce_skip_contract(PipelineResult.for_skip(
                    SkipReason.STANDARDS_DRAFT,
                    page_count=page_count,
                    prompts=["# tomd - Standards Draft Detected\n\n"
                        f"This PDF has {page_count} pages and appears to be "
                        "a standards draft. tomd is designed for technical papers.\n"],
                ))

            result.page_count = page_count

            all_mupdf_blocks = []
            all_spatial_blocks = []
            all_edge_items = []
            page_widths: dict[int, float] = {}
            # Rotated pages: pg -> rotation matrix (page space -> reading
            # space).  Used for reading-order sorting and table insertion.
            page_rotations: dict[int, tuple] = {}
            per_page_image_candidates: list = []
            # Sub-threshold raster glyphs (font-replacement emoji) and the
            # text-layer emoji bboxes used to skip coincident positions.
            # Both gathered while the doc is open; injected after the
            # readability gate so unreadable PDFs discard glyph state too.
            glyph_candidates: list = []
            text_emoji_by_page: dict[int, list] = {}
            page_height = 0.0

            for pg_num in range(result.page_count):
                page = doc[pg_num]
                page_widths[pg_num] = page.rect.width
                if page.rotation:
                    page_rotations[pg_num] = tuple(page.rotation_matrix)
                page_height = max(page_height, page.rect.height)

                mupdf_blocks = extract_mupdf(page, pg_num)
                spatial_blocks = extract_spatial(page, pg_num)

                edge_items = (
                    get_edge_items(mupdf_blocks, pg_num)
                    + get_edge_items(spatial_blocks, pg_num)
                )
                all_edge_items.append(edge_items)

                links = collect_links(page)
                attach_links(mupdf_blocks, links)
                attach_links(spatial_blocks, links)

                raster_candidates = extract_page_images(page, spatial_blocks)
                if extract_vector:
                    vector_candidates, page_vector_stats = extract_page_vector_images(
                        page, spatial_blocks, whiteout_text=whiteout_text,
                    )
                    vector_stats = _VectorExtractionStats.combine(
                        vector_stats, page_vector_stats,
                    )
                    per_page_image_candidates.append(
                        raster_candidates + vector_candidates
                    )
                else:
                    per_page_image_candidates.append(raster_candidates)

                page_glyphs = collect_glyph_candidates(page)
                if page_glyphs:
                    glyph_candidates.extend(page_glyphs)
                    # Only pages carrying glyphs need the coincidence check,
                    # so the rawdict emoji scan is scoped to them.
                    text_emoji_by_page[pg_num + 1] = collect_text_emoji_bboxes(page)

                all_mupdf_blocks.extend(mupdf_blocks)
                all_spatial_blocks.extend(spatial_blocks)

            font_counts: Counter[str] = Counter()
            for b in all_mupdf_blocks:
                for ln in b.lines:
                    for s in ln.spans:
                        if s.text.strip():
                            font_counts[s.font_name.lower()] += len(s.text)
            body_fonts = {f for f, _ in font_counts.most_common(5)}

            all_hidden: dict[int, set[tuple[float, float, float, float]]] = {}
            for pg_num in range(result.page_count):
                page = doc[pg_num]
                pg_hidden = find_hidden_regions(page, body_fonts)
                if pg_hidden:
                    all_hidden[pg_num] = pg_hidden

            page0_colors = _get_page0_text_colors(doc[0]) if result.page_count > 0 else {}

            page_drawings: dict[int, list] = {}
            page_mupdf_tables: dict[int, list[dict]] = {}
            ruled_tables: list = []
            page_rules: dict[int, list] = {}         # drawn horizontal rules per page
            all_figure_regions = []
            for pg_num in range(result.page_count):
                page = doc[pg_num]
                drawings = collect_line_drawings(page)
                if drawings:
                    page_drawings[pg_num] = drawings

                raw_drawings = page.get_drawings()
                page_figures = detect_figure_regions(
                    raw_drawings, pg_num, page.rect.width)
                all_figure_regions.extend(page_figures)

                # Table readers from the drawn lines: grids ruled both ways,
                # column-rule tables, and tables bounded by horizontal rules
                # (booktabs, shaded bands). They read the page upright; a
                # rotated page is not read by them yet (recorded).
                if pg_num in page_rotations:
                    current().record.exclude("rules", pg_num, tuple(page.rect), _ROTATED_NOT_READ, "paths")
                else:
                    try:
                        page_rules[pg_num] = page_hrules(page, raw_drawings)
                        ruled_tables.extend(extract_ruled_tables(page, pg_num, raw_drawings))
                    except Exception as exc:  # a failing table reader must not fail the paper: recorded
                        current().reader_error("ruled", pg_num, exc)

                # Intentional: runs unconditionally (independent of ml_tables).
                # Three table-detection passes rely on the MuPDF signal:
                # SBS deferral (Pass 0/2), inline-grid overlap (Pass 2b),
                # and MuPDF Native (Pass 5).  Cost accepted across the
                # 382-paper corpus.  Gate behind a flag if profiling shows
                # this dominates conversion time on large documents.
                try:
                    ft = page.find_tables()
                    if ft.tables:
                        # On rotated pages find_tables() reports bboxes in
                        # reading (display) space while extract_mupdf blocks
                        # stay in unrotated page space. Pass the rotation
                        # matrix so Pass 5 can map block/line midpoints into
                        # reading space before cell assignment.
                        rot = page_rotations.get(pg_num)
                        page_mupdf_tables[pg_num] = []
                        for t in ft.tables:
                            cell_heights = [c[3] - c[1] for c in t.cells if c] if t.cells else []
                            max_ch = max(cell_heights) if cell_heights else 0.0
                            tbl_h = t.bbox[3] - t.bbox[1]
                            page_cov = tbl_h / page.rect.height if page.rect.height else 0.0
                            page_mupdf_tables[pg_num].append({
                                "bbox": tuple(t.bbox),
                                "row_count": t.row_count,
                                "col_count": t.col_count,
                                "cells": [tuple(c) if c else None for c in t.cells],
                                "header_names": t.header.names if t.header else None,
                                "extract": t.extract(),
                                "rot": rot,
                                "max_cell_h": max_ch,
                                "tbl_h": tbl_h,
                                "page_coverage": page_cov,
                            })
                except Exception:
                    _log.debug("find_tables() failed on page %d", pg_num,
                               exc_info=True)

                # Fallback: detect bordered grids from drawing lines that
                # find_tables() missed and inject as synthetic entries.
                # Skipped on rotated pages: the h/v line classification works
                # in page space and Pass 2b consuming such an entry would
                # build a transposed table; Pass 5 owns rotated pages.
                if pg_num in page_rotations:
                    continue
                # A full-page phantom (find_tables() swallowing the page
                # background box) must not count as coverage, or every
                # real grid on that page is dropped (P4016R0 p.30/38/44).
                real_tables = _filter_phantom_mupdf_tables(
                    {pg_num: page_mupdf_tables.get(pg_num, [])}).get(pg_num, [])
                drawing_grids = _detect_drawing_grids(
                    page, page.rect.height, real_tables,
                )
                if drawing_grids:
                    _log.debug("Drawing-grid fallback found %d grid(s) on page %d",
                               len(drawing_grids), pg_num)
                    page_mupdf_tables.setdefault(pg_num, []).extend(drawing_grids)

            if all_figure_regions:
                _log.info("Detected %d figure region(s)", len(all_figure_regions))

            # Table reader: the PDF's accessibility tags (structure tree), the
            # author's own table markup, for tagged PDFs.
            try:
                tagged_tables = extract_tagged_tables(doc)
            except Exception as exc:  # a failing table reader must not fail the paper: recorded
                current().reader_error("tagged", None, exc)
                tagged_tables = []

            pdf_info_date = _parse_pdf_info_date(doc.metadata.get("creationDate", ""))
            pdf_info_title = (doc.metadata.get("title") or "").strip()
            doc_metadata = dict(doc.metadata)
        finally:
            if doc is not None:
                doc.close()

    if all_hidden:
        total_hidden = sum(len(v) for v in all_hidden.values())
        _log.info(
            "Stripping text hidden by %d covered regions on %d pages",
            total_hidden,
            len(all_hidden),
        )
        current().discards.append(("hidden", f"text under {total_hidden} covered region(s) "
                                   f"on {len(all_hidden)} page(s) removed", ""))
        all_mupdf_blocks = strip_hidden_blocks(all_mupdf_blocks, all_hidden)
        all_spatial_blocks = strip_hidden_blocks(all_spatial_blocks, all_hidden)

    mupdf_text = "\n".join(b.text for b in all_mupdf_blocks)
    if not is_readable(mupdf_text):
        _log.warning("Extracted text is not readable (encrypted/scanned PDF?)")
        return _enforce_skip_contract(
            PipelineResult.for_skip(
                SkipReason.UNREADABLE,
                page_count=result.page_count,
                readable=False,
            )
        )

    extraction_result = finalize_extraction(
        per_page_image_candidates,
        path.stem.lower(),
        vector_stats=vector_stats,
    )
    result.images = extraction_result.images
    result.source_image_count = extraction_result.source_image_count
    result.images_truncated = extraction_result.images_truncated
    result.vector_uncertainty = extraction_result.vector_uncertainty

    # Inject U+FFFD placeholders for sub-threshold raster glyphs (emoji
    # the figure path drops) into both extraction paths, skipping rects
    # already covered by a text-layer emoji codepoint. Runs after the
    # readability gate (so unreadable PDFs discard glyph state) and
    # after the font_counts snapshot above (so the synthetic font never
    # enters body_fonts/dominant_font), but before cleanup/structure so
    # each placeholder is treated as ordinary body text. Placement runs
    # independently per path; compare_extractions is page-level word
    # multiset, so the same token added to both paths stays balanced.
    if glyph_candidates:
        orphans, skipped_coincident = filter_coincident(
            glyph_candidates,
            text_emoji_by_page,
        )
        glyph_stats = inject_glyph_spans(all_mupdf_blocks, orphans)
        inject_glyph_spans(all_spatial_blocks, orphans)
        result.glyph_stats = GlyphPassStats(
            injected=glyph_stats.injected,
            skipped_coincident=skipped_coincident,
            free_standing=glyph_stats.free_standing,
        )
        if result.glyph_stats.fired:
            _log.info(
                "Glyph placeholders: injected=%d skipped_coincident=%d "
                "free_standing=%d",
                result.glyph_stats.injected,
                result.glyph_stats.skipped_coincident,
                result.glyph_stats.free_standing,
            )

    repeating = detect_repeating(all_edge_items, result.page_count, page_height)
    if repeating:
        _log.info("Stripping %d repeating header/footer patterns", len(repeating))
        current().discards.append(("headers", f"{len(repeating)} repeating header/footer "
                                   "pattern(s) removed",
                                   ", ".join(sorted(map(str, repeating))[:_DISCARD_EXAMPLES])[:_DISCARD_DETAIL_CHARS]))
        all_mupdf_blocks = strip_repeating(all_mupdf_blocks, repeating)
        all_spatial_blocks = strip_repeating(all_spatial_blocks, repeating)

    dominant_font = font_counts.most_common(1)[0][0] if font_counts else ""
    propagate_monospace(all_mupdf_blocks, all_spatial_blocks, dominant_font)

    wording_problems = classify_wording(all_mupdf_blocks, page_drawings)

    # Sort blocks into reading order BEFORE cleanup_text, which contains
    # _join_cross_page.  That function merges the first block on page N+1
    # with the last block on page N; if blocks are still in MuPDF's
    # arbitrary extraction order (e.g. code blocks extracted after body
    # text despite higher y-positions) the merge target is wrong and
    # continuation text lands on the wrong block.  Sorting first ensures
    # "last block on the page" means visually bottom-most. The sort also
    # decides which pages are two-column; detect_tables gets that set, so
    # block order and page classification come from the same blocks
    # (the stripped ones: a centred page number in the raw blocks used to
    # hide the gutter on p4098r1 p.4/5 and split the two decisions).
    column_splits: dict[int, float] = {}
    two_column_pages = _column_aware_sort(
        all_mupdf_blocks, page_widths, page_rotations,
        splits_out=column_splits)
    _column_aware_sort(all_spatial_blocks, page_widths, page_rotations)
    if two_column_pages:
        _log.debug("Two-column pages: %s", sorted(two_column_pages))

    all_mupdf_blocks = cleanup_text(all_mupdf_blocks)
    all_spatial_blocks = cleanup_text(all_spatial_blocks)

    all_mupdf_blocks = normalize_spans(all_mupdf_blocks)
    all_spatial_blocks = normalize_spans(all_spatial_blocks)

    wg21_metadata, _ = extract_metadata_from_blocks(
        all_mupdf_blocks, text_colors=page0_colors
    )

    # Snapshot of every page block before detect_tables consumes them:
    # the table trust check counts the text of each table's area in it
    # (select.conservation_error), and the Docling enrichment needs ALL
    # page spans (including those consumed but dropped from sec.lines by
    # the rule-based detector) to correctly populate Docling cell grids.
    pre_detect_blocks = list(all_mupdf_blocks)

    # Every table reader proposes readings; select_tables picks one reading
    # per region and trusts it (HIGH) only when another kind of evidence
    # agrees. detect_tables is the text-position reader ("tomd"); its own
    # consumption of blocks is not used: the text of each selected table's
    # region leaves the prose afterwards (remove_table_regions), and a line
    # whose words are not in the table stays.
    try:
        tomd_sections, _ = detect_tables(
            list(all_mupdf_blocks),
            page_mupdf_tables=page_mupdf_tables,
            two_column_pages=two_column_pages,
        )
    except Exception as exc:  # a failing table reader must not fail the paper: recorded, its text kept as prose
        current().reader_error("detect_tables", None, exc)
        tomd_sections = []
    table_sections = select_tables(tomd_sections, ruled_tables, tagged_tables, pre_detect_blocks,
                                   generator=pdf_generator(doc_metadata))
    # Rows bounded by drawn rules: a record the reader cut into rows is joined.
    for ts in table_sections:
        pages = {ln.page_num for ln in ts.lines or []}
        if len(pages) == 1:
            try:
                merge_rule_bands(ts, page_rules.get(next(iter(pages)), []))
            except Exception as exc:  # a join only; never fail on it, never silently
                current().reader_error("rule-band rows", next(iter(pages)), exc, table=ts)
    all_mupdf_blocks = remove_table_regions(pre_detect_blocks, table_sections)
    all_spatial_blocks = remove_table_regions(all_spatial_blocks, table_sections)
    if table_sections:
        _log.info("Selected %d table(s)", len(table_sections))

    # --- Optional Docling ML table processing ---
    # When ml_tables=True and Docling is available:
    #   1. Enrich existing rule-based tables with Docling cell grids.
    #   2. Discover new tables that rule-based detection missed
    #      (borderless tables), consuming their blocks so they
    #      don't become duplicate paragraphs.
    if ml_tables and _docling_available():
        docling_tables = _extract_docling_tables(path)
        if docling_tables:
            if table_sections:
                n = _enrich_tables_with_docling(
                    table_sections, docling_tables, pre_detect_blocks
                )
                if n:
                    _log.info("Docling enriched %d/%d table(s)", n, len(table_sections))

            all_mupdf_blocks = _absorb_cross_page_spec_rows(
                table_sections, all_mupdf_blocks, docling_tables
            )

            new_tables, all_mupdf_blocks = _discover_tables_with_docling(
                docling_tables, all_mupdf_blocks, table_sections
            )
            if new_tables:
                table_sections.extend(new_tables)
                all_spatial_blocks = exclude_table_regions(
                    all_spatial_blocks, new_tables
                )
                _log.info("Docling discovered %d new table(s)", len(new_tables))

    sections = compare_extractions(all_mupdf_blocks, all_spatial_blocks)

    # On a two-column page the section list is already column-then-y.
    # Inserting a table by raw y pulls a right-column table (small y)
    # up into the left column. The split from the same sort keeps it
    # in its column.
    _insert_table_sections(
        sections, table_sections, page_rotations, column_splits)

    if result.images:
        _log.info(
            "Extracted %d image(s) (cap %s)",
            len(result.images),
            "tripped" if result.images_truncated else "ok",
        )
        sections = _insert_image_sections(sections, result.images)

    has_title = "title" in wg21_metadata

    # --- Phase 1: Metadata extraction ---
    # Two pathways, merged in precedence order (last wins):
    #   1. metadata_yaml.extract.extract_metadata - PDF section line scan (lowest)
    #   2. wg21.extract_metadata_from_blocks - PDF block-level scan (wins)
    structure_metadata, sections = _extract_metadata_yaml(sections)
    metadata = {**structure_metadata, **wg21_metadata}

    # --- Phase 1b: Body structuring (may detect title for metadata) ---
    body_metadata, sections, nesting_corrections = structure_body(
        sections, has_title=has_title, figure_regions=all_figure_regions or None,
        metadata_title=metadata.get("title"),
    )
    for k, v in body_metadata.items():
        if k not in metadata:
            metadata[k] = v

    # Glyph placeholders that attached (before structure ran) to a line
    # now classified CODE or folded into a TABLE are removed: a U+FFFD in
    # a fenced block reads as a syntax error, and tables render
    # structurally. The marker discloses the count so the loss is not
    # silent. Runs after structure has assigned section kinds.
    if result.glyph_stats is not None:
        result.glyph_stats.skipped_code_section = drop_glyphs_in_code_and_tables(
            sections
        )

    # Vector-image post-processing
    if result.images:
        total_dropped = 0
        result.images, sections, dropped_a = _filter_vector_images_against_structural(
            result.images, sections
        )
        total_dropped += dropped_a
        result.images, sections, dropped_b = _filter_overlapping_vector_images(
            result.images, sections
        )
        total_dropped += dropped_b
        sections, captures_by_id, dropped_caption_ids = (
            _filter_sections_inside_vector_images(
                result.images,
                sections,
            )
        )
        if captures_by_id or dropped_caption_ids:
            from dataclasses import replace as _replace

            # Thread the captures and caption-drop flags into BOTH
            # ``result.images`` AND every
            # IMAGE section's ``image_ref``. Both containers share the
            # same ``ExtractedImage`` instances (placed by
            # ``_insert_image_sections``), so ``id()`` lookup is valid
            # against the keys in ``captures_by_id`` (which were taken
            # from the same instances inside the filter). ``Section`` is
            # a mutable dataclass (types.py:103) so direct rebind of
            # ``image_ref`` is allowed.
            #
            # Ordering matters: insert PARAGRAPHs FIRST (while
            # ``sec.image_ref`` still points at the pre-replace
            # objects whose ids match ``captures_by_id`` keys), THEN
            # rebind. Doing the rebind first would change
            # ``id(sec.image_ref)`` to the new object's id, breaking
            # the insertion loop's lookup.
            new_sections: list[Section] = []
            for sec in sections:
                new_sections.append(sec)
                if (
                    sec.kind == SectionKind.IMAGE
                    and sec.image_ref is not None
                    and id(sec.image_ref) in captures_by_id
                ):
                    for letter, caption_text in sorted(
                        captures_by_id[id(sec.image_ref)]
                    ):
                        # Collapse internal whitespace (incl. newlines
                        # from the structure pass's wrap-join) to single
                        # spaces so the italic wrapper renders as one
                        # unwrapped paragraph, matching the existing
                        # PARAGRAPH emit path's behaviour.
                        unwrapped = " ".join(caption_text.split())
                        new_sections.append(
                            Section(
                                kind=SectionKind.PARAGRAPH,
                                text=("*" + _escape_italic_text(unwrapped) + "*"),
                                confidence=Confidence.MEDIUM,
                                page_num=sec.page_num,
                            )
                        )
            sections = new_sections

            replaced: dict[int, ExtractedImage] = {
                id(im): _replace(
                    im,
                    sub_captions=tuple(sorted(captures_by_id.get(id(im), ()))),
                    caption_body_dropped=id(im) in dropped_caption_ids,
                )
                for im in result.images
                if id(im) in captures_by_id or id(im) in dropped_caption_ids
            }
            for sec in sections:
                if (
                    sec.kind == SectionKind.IMAGE
                    and sec.image_ref is not None
                    and id(sec.image_ref) in replaced
                ):
                    sec.image_ref = replaced[id(sec.image_ref)]
            result.images = [replaced.get(id(im), im) for im in result.images]
        if total_dropped and result.vector_uncertainty is not None:
            new_kept = sum(1 for im in result.images if im.source == "vector")
            result.vector_uncertainty = replace(
                result.vector_uncertainty,
                kept=new_kept,
            )

    if "document" not in metadata:
        stem_match = DOC_NUM_RE.search(path.stem)
        if stem_match:
            metadata["document"] = stem_match.group(1).upper()

    if "date" not in metadata and pdf_info_date:
        metadata["date"] = pdf_info_date

    override_revision_from_filename(metadata, path)

    if not metadata.get("title"):
        for sec in sections:
            if sec.kind == SectionKind.HEADING:
                first_line = sec.text.split("\n")[0].strip().lstrip("# ").strip()
                if first_line and first_line.lower().rstrip(":") not in KNOWN_SECTIONS:
                    metadata["title"] = first_line
                    break

    if not metadata.get("title") and pdf_info_title:
        _TITLE_BOILERPLATE_RE = re.compile(
            r"^(?:Microsoft\s+Word|Document\d|Untitled|"
            r"[DPN]\d{3,5}(?:R\d+)?|Presentation\d?)$",
            re.IGNORECASE,
        )
        if not _TITLE_BOILERPLATE_RE.match(pdf_info_title):
            metadata["title"] = pdf_info_title

    # Strip leading paper-ID prefix from titles regardless of extraction
    # pathway (wg21, structure, heading fallback, PDF info). Import from
    # structure where the regex is defined to keep a single source of truth.
    if metadata.get("title"):
        stripped = _TITLE_PID_PREFIX_RE.sub("", metadata["title"]).strip()
        if stripped:
            metadata["title"] = stripped

    if "reply-to" not in metadata:
        pdf_info_author = (doc_metadata.get("author") or "").strip()
        if pdf_info_author and len(pdf_info_author) >= 4:
            _AUTHOR_BOILERPLATE_RE = re.compile(
                r"^(?:Admin|Scanner|Unknown|Default|User|Owner|"
                r"Microsoft|Adobe|LaTeX|TeX|MiKTeX|pdfTeX|dvips|"
                r"Acrobat|LibreOffice|OpenOffice|Google|Apple|"
                r"[a-z0-9._-]+\.(?:pdf|doc|docx|tex))$",
                re.IGNORECASE,
            )
            if not _AUTHOR_BOILERPLATE_RE.match(pdf_info_author):
                metadata["reply-to"] = [pdf_info_author]

    _enrich_pdf_reply_to(metadata, all_mupdf_blocks)
    # --- Phase 1c: Metadata fallbacks & enrichment (metadata_yaml) ---
    _apply_pdf_metadata_fallbacks(
        metadata,
        path,
        pdf_info_date,
        pdf_info_title,
        doc_metadata,
        sections,
        all_mupdf_blocks,
        _TITLE_PID_PREFIX_RE,
    )

    # --- Phase 1d: Metadata stripping from body sections (metadata_yaml) ---
    _strip_pre_heading_fragments(sections)
    _strip_metadata_headings_new(sections, metadata)
    _promote_abstract_from_uncertain(sections)
    _strip_pre_content_paragraphs(sections)

    # Demote TABLE sections with dot-leaders back to PARAGRAPH so
    # TOC detection can recognize them.  Horizontal-row table detection
    # can misclassify TOC entries (section number + title + page number
    # on the same y-line) as table rows; reverting them here lets the
    # existing find_toc_indices / label-anchored logic strip them.
    # A table two kinds of evidence agree on is exempt; a demoted table
    # carries a possible-table mark, so the demotion is never silent.
    for sec in sections:
        if (sec.kind == SectionKind.TABLE and has_dot_leader(sec.text)
                and sec.confidence != Confidence.HIGH):
            sec.metadata["possible_table"] = _MARK_DOT_LEADER
            sec.kind = SectionKind.PARAGRAPH
            sec.table_kind = None
            sec.table_strategy = None
            sec.columns = None

    texts = [sec.text.split("\n")[0].strip() for sec in sections]
    full_texts = [sec.text for sec in sections]
    heading_texts = {
        sec.text.split("\n")[0].strip()
        for sec in sections
        if sec.kind == SectionKind.HEADING
    }
    structural_hints = _toc_structural_hints(sections) if not heading_texts else None
    # A body heading matches itself in heading_texts; pass per-section heading
    # flags so find_toc_indices excludes them and does not delete the body.
    # The guard keeps the _toc_structured exception so a genuine numbered TOC
    # entry that section numbering classified as a heading is still stripped.
    is_heading = [sec.kind == SectionKind.HEADING for sec in sections]
    toc_indices = find_toc_indices(
        texts,
        heading_texts,
        structural_hints,
        full_texts=full_texts,
        is_heading=is_heading,
    )

    # Plausibility guard: reject phantom TOC detection.
    # A valid TOC must have at least one confirming signal:
    #   (a) dot leaders in at least one section,
    #   (b) a "Contents" / "Table of Contents" label in the document, or
    #   (c) a heading inside the detected block also exists outside it
    #       (the inside copy is a TOC reference, the outside is the real heading).
    # Without any signal the "TOC" is a phantom from heading self-matching,
    # common in short dense papers where the gap between headings <= _MAX_GAP.
    if toc_indices:
        # IMAGE sections are never TOC content.
        toc_indices = {
            i for i in toc_indices if sections[i].kind is not SectionKind.IMAGE
        }

    if toc_indices:
        _has_dot = any(has_dot_leader(sections[i].text) for i in toc_indices)
        _has_label = any(
            is_toc_label(s.text.split("\n")[0].strip()) for s in sections
        )
        if not _has_dot and not _has_label:
            _inside = set()
            for i in toc_indices:
                if sections[i].kind == SectionKind.HEADING:
                    _n = sections[i].text.split("\n")[0].strip().lower().rstrip(":")
                    if _n:
                        _inside.add(_n)
            _outside = set()
            for i, s in enumerate(sections):
                if i not in toc_indices and s.kind == SectionKind.HEADING:
                    _n = s.text.split("\n")[0].strip().lower().rstrip(":")
                    if _n:
                        _outside.add(_n)
            if not (_inside & _outside):
                _log.info(
                    "Rejected phantom TOC (%d entries, no confirming signal)",
                    len(toc_indices),
                )
                toc_indices = set()

    for sec in sections:
        _drop_leading_contents(sec)

    for li, sec in enumerate(sections):
        if li in toc_indices:
            continue
        fl = next(
            (ln.strip() for ln in sec.text.split("\n") if ln.strip()),
            "",
        )
        if not is_toc_label(fl):
            continue
        candidate = {li}
        numbered = 0
        for j in range(li + 1, min(li + 40, len(sections))):
            if j in toc_indices:
                continue
            sec_j = sections[j]
            jfl = sec_j.text.split("\n")[0].strip()
            has_numbered = False
            j_dot = any(has_dot_leader(ln) for ln in sec_j.text.split("\n"))
            for line in sec_j.text.split("\n"):
                stripped = line.strip()
                if _NUMBERED_LINE_RE.match(stripped) or _BARE_PAGE_NUM_RE.match(
                    stripped
                ):
                    has_numbered = True
                    numbered += 1
            if j_dot or has_numbered:
                candidate.add(j)
                if j_dot and not has_numbered:
                    numbered += 1
            elif jfl.lower() in ("ii", "iii", "iv", "v", "vi", "vii", "viii"):
                candidate.add(j)
            elif sec_j.kind == SectionKind.TABLE and not j_dot:
                candidate.add(j)
            elif sec_j.kind == SectionKind.HEADING and not has_numbered and not j_dot:
                break
            elif jfl.strip() == "":
                continue
            else:
                break
        if len(candidate) > 1 and numbered >= _LABEL_TOC_MIN_NUMBERED_LINES:
            toc_indices |= candidate
            _log.info("Label-anchored TOC: %d entries after '%s'", len(candidate), fl)

    if toc_indices:
        non_toc_known: set[str] = set()
        for i, sec in enumerate(sections):
            if i not in toc_indices and sec.kind == SectionKind.HEADING:
                fl = sec.text.split("\n")[0].strip()
                if _is_known_section(fl):
                    non_toc_known.add(fl.lower().rstrip(":"))

        protected = set()
        for idx in sorted(toc_indices):
            sec = sections[idx]
            if sec.kind == SectionKind.HEADING:
                fl = sec.text.split("\n")[0].strip()
                if _is_known_section(fl):
                    if has_dot_leader(sec.text):
                        continue
                    if fl.lower().rstrip(":") in non_toc_known:
                        continue
                    protected.add(idx)
                    is_abstract_heading = fl.lower().rstrip(":") == "abstract"
                    first_body_confirmed = False
                    for nxt in range(idx + 1, len(sections)):
                        if nxt not in toc_indices:
                            break
                        nxt_sec = sections[nxt]
                        if nxt_sec.kind == SectionKind.HEADING:
                            if (
                                is_abstract_heading
                                and not first_body_confirmed
                                and nxt_sec.confidence == Confidence.LOW
                            ):
                                nxt_sec.kind = SectionKind.PARAGRAPH
                                nxt_sec.heading_level = 0
                                first_body_confirmed = True
                                protected.add(nxt)
                                continue
                            parent_level = sections[idx].heading_level
                            if (
                                parent_level > 0
                                and nxt_sec.heading_level > parent_level
                            ):
                                protected.add(nxt)
                                first_body_confirmed = True
                                continue
                            break
                        if nxt_sec.kind == SectionKind.TABLE:
                            if first_body_confirmed:
                                protected.add(nxt)
                                continue
                            break
                        nxt_fl = nxt_sec.text.split("\n")[0].strip()
                        if has_dot_leader(nxt_fl):
                            break
                        if not first_body_confirmed and _SECTION_NUM_START_RE.match(
                            nxt_fl
                        ):
                            break
                        nxt_words = len(nxt_sec.text.split())
                        if not first_body_confirmed:
                            if (
                                not is_abstract_heading
                                and nxt_words < _TOC_BODY_PROTECT_MIN_WORDS
                            ):
                                break
                            first_body_confirmed = True
                        protected.add(nxt)
        if protected:
            _log.debug(
                "Protecting %d section heading(s) from TOC removal: %s",
                len(protected),
                [
                    sections[i].text.split("\n")[0].strip()[:60]
                    for i in sorted(protected)
                ],
            )
            toc_indices -= protected
        if toc_indices:
            sections[:] = [s for i, s in enumerate(sections) if i not in toc_indices]

    sections[:] = [
        s for s in sections
        if not (s.kind == SectionKind.PARAGRAPH
                and is_toc_label(s.text.split("\n")[0].strip())
                and len(s.text.split("\n")[0].strip().split()) <= _TOC_LABEL_MAX_WORDS)
    ]

    _dedup_abstract_new(sections)
    _rescue_stranded_abstract_body(sections)

    _strip_metadata_from_uncertain(sections, metadata)
    _reorder_abstract_in_uncertain(sections)

    # Remove a leaked TOC that survived find_toc_indices: a mix of empty
    # duplicate headings and title-like paragraph/list entries, plus the
    # non-recurring stragglers (front-region only) that fragment the block.
    sections = drop_leaked_toc_entries(sections)

    # Every table gets a graded level (L0-L5, levels.py): how a flagged table
    # may be wrong. A table classified as not a table (rendered as text) is a
    # possible-table mark instead.
    for sec in sections:
        if sec.kind != SectionKind.TABLE:
            continue
        if sec.table_strategy == TableStrategy.SKIP.value:
            sec.metadata["possible_table"] = _MARK_FALSE_POSITIVE
        else:
            sec.metadata["level"] = assign_level(sec)

    md = emit_markdown(
        metadata,
        sections,
        images_truncated=result.images_truncated,
        source_image_count=result.source_image_count,
        vector_uncertainty=result.vector_uncertainty,
        glyph_stats=result.glyph_stats,
    )
    prompts = emit_prompts(sections)

    if wording_problems:
        wording_prompts = [
            (
                "The PDF wording-detection pass flagged the following issue. "
                "Review and correct the affected region in the converted "
                "Markdown.\n\n"
                f"{problem}"
            )
            for problem in wording_problems
        ]
        prompts = (prompts or []) + wording_prompts

    # The paper summary: what was done with the tables, what was removed and
    # why, which readers raised. One comment after the front matter; the
    # removed content, reader errors and summary as prompt elements when the
    # paper has prompts at all.
    ctx = current()
    summary = build_summary(sections, ctx.discards, ctx.record.errors, pdf_generator(doc_metadata))
    if md.strip():
        md = _insert_after_front_matter(md, header_comment(summary))
    if prompts:
        prompts = prompts + prompt_elements(summary, ctx.discards, ctx.record.errors)
    result.summary = summary

    result.md = md
    result.prompts = prompts
    result.sections = sections
    result.metadata = metadata
    result.nesting_corrections = nesting_corrections
    return _enforce_skip_contract(result)
