"""Markdown and companion prompts file generation."""

import html as _html
import logging
import re

from .. import (
    DEFAULT_FENCE_LANG,
    apply_strip_leading_h1,
    dedup_paragraphs,
    format_front_matter,
    strip_redundant_body_meta,
    strip_orphan_toc_list,
)
from .. import tables as _tables
from ..shared import _find_front_matter_end
from .cleanup import escape_leading_atx, normalize_whitespace
from .code_format import is_diagram_block, maybe_normalize_code_line
from .code_grid import CodeGrid
from .wording_emit import _render_wording_section
from .glyphs import (
    GLYPH_PLACEHOLDER_MARKER_TEMPLATE,
    UNKNOWN_GLYPH,
    GlyphPassStats,
)
from .images import TRUNCATION_MARKER_TEMPLATE, VectorUncertaintyStats
from .levels import SHOWN_FROM, comment as level_comment
from .types import Line, Span, Section, SectionKind, Confidence, BULLET_CHARS, BULLET_RE, NUMBERED_LIST_RE, FALLBACK_FONT_SIZE
from .vector_images import format_uncertainty_marker, should_emit_marker
_log = logging.getLogger(__name__)

# A heading section can span multiple Line objects two ways: a single visual
# line split horizontally by wide x-gaps (number / title / clause tag share
# one baseline), or a following body line the section wrongly absorbed (a
# lower baseline). Only lines on the heading's own baseline (its first
# non-empty line) are joined; a line is on that baseline if its y-top is
# within this fraction of the heading font size. The next text row sits a
# full line-height (~1.2x font) below, so it is excluded.
_HEADING_SAME_ROW_FONT_FRACTION = 0.6


def _render_span(span: Span, skip_bold: bool = False) -> str:
    """Render a single non-monospace span with inline Markdown formatting.

    Monospace spans are handled by _render_line_spans via group merging.
    """
    text = span.text
    if not text.strip():
        return text

    stripped = text.strip()
    leading = text[:len(text) - len(text.lstrip())]
    trailing = text[len(text.rstrip()):]

    bold = span.bold and not skip_bold

    if span.link_url:
        inner = f"[{stripped}]({span.link_url})"
        if bold and span.italic:
            inner = f"***{inner}***"
        elif bold:
            inner = f"**{inner}**"
        elif span.italic:
            inner = f"*{inner}*"
        return f"{leading}{inner}{trailing}"

    if bold and span.italic:
        return f"{leading}***{stripped}***{trailing}"
    if bold:
        return f"{leading}**{stripped}**{trailing}"
    if span.italic:
        return f"{leading}*{stripped}*{trailing}"

    return text


def _render_line_spans(line: Line, in_code_section: bool = False,
                       suppress_bold: bool = False) -> str:
    """Render all spans in a line with inline formatting applied.

    Merges consecutive monospace spans into a single backtick pair
    to avoid fragmented output like `std``::``:stop_token`.
    """
    if in_code_section:
        return "".join(s.text for s in line.spans)

    groups: list[tuple[bool, list[Span]]] = []
    for span in line.spans:
        is_mono = span.monospace and span.text.strip()
        if groups and groups[-1][0] == is_mono:
            groups[-1][1].append(span)
        else:
            groups.append((is_mono, [span]))

    parts = []
    for is_mono, spans in groups:
        if is_mono:
            merged_text = "".join(s.text for s in spans)
            stripped = merged_text.strip()
            if stripped:
                leading = merged_text[:len(merged_text) - len(merged_text.lstrip())]
                trailing = merged_text[len(merged_text.rstrip()):]
                parts.append(f"{leading}`{stripped}`{trailing}")
            else:
                parts.append(merged_text)
        else:
            for span in spans:
                if suppress_bold:
                    parts.append(_render_span(span, skip_bold=True))
                else:
                    parts.append(_render_span(span))
    return "".join(parts)


# The single Markdown unordered-list marker this converter emits, at every
# nesting depth. "-" over "*" because the HTML renderer already emits "-", the
# blessed ideals standardize on it, and it cannot be read as emphasis if a
# stray bullet glyph survives mid-text (#303).
LIST_BULLET = "-"


# A line that opens an em/en-dash bulleted item. The dash is followed by
# whitespace, or by nothing at all: standardese enumerations lay the marker out
# as its own column, so extraction hands us the dash alone on its own ``Line``
# ("\u2014", then "(5.1)", then the item text). Only the dash is consumed; the
# grouping below strips what follows.
_EMDASH_BULLET_RE = re.compile(r"^[\u2013\u2014](?=\s|$)")

# Minimum items for an em-dash block whose lines do NOT all carry a marker to
# read as a list. One marked line followed by unmarked lines is far more likely
# to be a paragraph that happens to open on an em-dash than a one-item list, so
# the wrapped-continuation path needs a second marked line to commit.
_EMDASH_LIST_MIN_ITEMS = 2


def _emdash_bullet_items(non_empty: list[str]) -> list[str] | None:
    """Group em-dash-bulleted lines into items, or None if this is not a list.

    A marker line opens an item; every unmarked line folds into the item above
    it. That is how both shapes of a real enumeration reach us:

    - a *wrapped* item, whose tail line carries no dash;
    - a *column-laid-out* item, where the dash, the paragraph number and the
      text are three separate ``Line`` objects on one visual row.

    Requiring *every* line to carry a marker (the previous rule) failed on both
    and collapsed the whole list into one run-together paragraph (#303, P3556R0's
    [module.import] and [cpp.pre] enumerations).

    The all-marked case keeps its old behaviour, including for a single line;
    otherwise ``_EMDASH_LIST_MIN_ITEMS`` items are needed to commit.

    A marker with no text after it is not an item. Dropping it before the
    minimum-items test keeps a bare trailing dash from both emitting an empty
    ``"- "`` bullet and padding a prose block up to the commit threshold.
    """
    if not non_empty or not _EMDASH_BULLET_RE.match(non_empty[0]):
        return None
    items: list[list[str]] = []
    for ln in non_empty:
        if _EMDASH_BULLET_RE.match(ln):
            items.append([_EMDASH_BULLET_RE.sub("", ln, count=1).strip()])
        else:
            items[-1].append(ln)
    all_marked = len(items) == len(non_empty)
    items = [parts for parts in items if any(parts)]
    if not items or not (all_marked or len(items) >= _EMDASH_LIST_MIN_ITEMS):
        return None
    return [f"{LIST_BULLET} " + " ".join(p for p in parts if p)
            for parts in items]


def _render_paragraph_spans(sec: Section) -> str:
    """Render a paragraph section using span-level formatting, then unwrap.

    Falls back to ``sec.text`` when ``sec.lines`` is empty, bypassing
    ``_render_line_spans`` so pre-escaped text (e.g. sub-caption sections
    with ``*...*`` wrappers) is not double-processed. PDF line breaks in
    the text are still flattened to spaces.

    A block whose first line opens with an em-dash or en-dash bullet marker
    renders as a list instead; see :func:`_emdash_bullet_items`.
    """
    if not sec.lines:
        return escape_leading_atx(
            " ".join(ln.strip() for ln in sec.text.split("\n") if ln.strip()))
    rendered_lines = []
    for line in sec.lines:
        rendered_lines.append(_render_line_spans(line))
    text = "\n".join(rendered_lines)
    text = normalize_whitespace(text)
    lines = text.split("\n")
    non_empty = [ln.strip() for ln in lines if ln.strip()]
    items = _emdash_bullet_items(non_empty)
    if items is not None:
        prefix = "  " * sec.indent_level
        return "\n".join(prefix + item for item in items)
    return escape_leading_atx(
        " ".join(ln.strip() for ln in lines if ln.strip()))

def _render_heading_spans(sec: Section) -> str:
    """Render a heading, joining the lines that share its visual baseline.

    The PDF can split a single heading line across several ``Line`` objects
    with wide horizontal gaps (ISO/standardese headings lay out
    "1   Scope   [scope]" as three lines on one baseline). Rendering only the
    first line would emit the bare section number ("## 1"); markdown headings
    are one line, so the lines sharing the heading's baseline are joined.

    Only the heading's own visual row is joined: a section that wrongly
    absorbs a following body line must not pull that prose into the heading,
    and such a line sits on a lower baseline. Identical line texts are also
    collapsed: some PDFs overprint a heading several times at the same
    position to simulate bold, and joining those verbatim would repeat it.

    Bold is suppressed because the ATX prefix already conveys heading weight.
    When line 0 is a bare section number (e.g. "1", "3.2", "I."), subsequent
    lines at the same font size are joined to recover the title text that
    MuPDF split onto a separate line.

    Deliberate trade-off: grouping is purely same-row. A heading whose title
    genuinely *wraps* onto a second baseline has its continuation emitted as a
    body paragraph below the heading, not folded back into the heading line.
    The older line-continuation heuristic (trailing comma/conjunction, etc.)
    was dropped for simplicity; wrapped section titles are rare in the WG21
    corpus and no golden regressed. Body prose that a heading section wrongly
    absorbs sits on a lower baseline too and is handled by the same rule, so
    the simpler grouping serves both. ``test_emit_heading_excludes_lower``
    ``_baseline_body_line`` pins this behaviour.

    Row membership keys on each line's vertical midpoint, not its top edge:
    on a single visual row mixing font sizes (a large section number beside a
    small-caps title) the glyph tops differ even though the baselines align,
    so the midpoint tracks the shared baseline far more robustly. This matches
    the midpoint convention used in ``cleanup.py``.

    If the heading section contains additional body lines (e.g. table cells
    merged into a single section), those are emitted as a paragraph below
    the heading so content is not lost.
    """
    prefix = "#" * sec.heading_level

    rows = [((ln.bbox[1] + ln.bbox[3]) / 2.0, ln.font_size,
             _render_line_spans(ln, suppress_bold=True).strip(), ln)
            for ln in sec.lines]
    rows = [r for r in rows if r[2]]
    if not rows:
        clean_text = sec.text.split("\n")[0].strip()
        return f"{prefix} {clean_text}" if clean_text else ""

    anchor_y, anchor_fs, _, _ = rows[0]
    # Type-3/bitmap fonts report font_size 0; fall back so the tolerance never
    # collapses to 0 and demotes a same-baseline title to a body paragraph.
    row_tol = (anchor_fs or FALLBACK_FONT_SIZE) * _HEADING_SAME_ROW_FONT_FRACTION

    seen: set[str] = set()
    parts: list[str] = []
    remainder_lines: list[str] = []
    for y, _, text, ln in rows:
        if abs(y - anchor_y) <= row_tol:
            if text not in seen:
                seen.add(text)
                parts.append(text)
        else:
            body_line = _render_line_spans(ln).strip()
            if body_line:
                remainder_lines.append(body_line)

    clean_text = " ".join(parts).strip()
    if not clean_text:
        return ""
    heading = f"{prefix} {clean_text}"

    if remainder_lines:
        head_norm = re.sub(r"[^a-z0-9\s]", "", clean_text.lower()).strip()
        body_parts = []
        for rl in remainder_lines:
            rl_norm = re.sub(r"[^a-z0-9\s]", "", rl.lower()).strip()
            if rl_norm and rl_norm != head_norm:
                body_parts.append(rl)
        if body_parts:
            return f"{heading}\n\n{' '.join(body_parts)}"
    return heading


def _normalize_bullet(char: str) -> str:
    """Replace a Unicode bullet character with ``LIST_BULLET``."""
    if char in BULLET_CHARS:
        return LIST_BULLET
    return char


def _normalize_bullets(text: str) -> str:
    """Replace Unicode bullet characters with ``LIST_BULLET`` throughout text."""
    return "".join(_normalize_bullet(ch) for ch in text)


# Two spaces of leading indentation per nesting level. Markdown nests a
# sublist when its marker is indented past the parent item's content.
_LIST_INDENT_UNIT = "  "


_ITEM_TERMINAL_PUNCT = frozenset(".:;?!")


def _is_numbered_item(text: str) -> bool:
    """Whether a line opens an item with an explicit ordinal marker (``1.``, ``b)``)."""
    return bool(NUMBERED_LIST_RE.match(text.lstrip()))


def _reads_unfinished(text: str) -> bool:
    """Whether an item's accumulated text looks cut off mid-sentence."""
    stripped = text.rstrip().rstrip('"”’\'')
    return bool(stripped) and stripped[-1] not in _ITEM_TERMINAL_PUNCT


def _is_list_item_start(text: str, current_item: str) -> bool:
    """Whether a rendered line begins a new list item (vs. a wrapped continuation).

    A bullet glyph or literal ``-``/``*`` marker always opens an item. An
    ordinal marker (``1.``, ``b)``) is treated as a wrapped continuation,
    not a new item, only when the current item is itself unnumbered AND
    reads as cut off mid-sentence: e.g. a bullet ``...meeting in`` wrapping
    to ``2017. The...``. A current item that is already numbered, or that
    ends in terminal punctuation, takes the ordinal as a genuine new item,
    so ``2.`` after ``1.`` and a ``d)`` label after a finished bullet both
    stay separate (issue #175 review).
    """
    stripped = text.lstrip()
    if not stripped:
        return False
    if stripped[0] in BULLET_CHARS or BULLET_RE.match(stripped):
        return True
    if NUMBERED_LIST_RE.match(stripped):
        return _is_numbered_item(current_item) or not _reads_unfinished(current_item)
    return False


# A literal "*" list marker carried over from the source (some PDFs typeset
# their bullets as plain asterisks, so no BULLET_CHARS glyph is present).
_ASTERISK_MARKER_RE = re.compile(r"^\*\s+")


def _format_list_item(text: str, depth: int) -> str:
    """Format one list item at the given nesting depth.

    An unordered item gets ``LIST_BULLET`` at every depth (indented two spaces
    per level), whether its source marker was a Unicode bullet glyph or a
    literal ``*``. Depth used to switch the marker to ``*`` at the top level,
    which made every unordered list in a PDF-sourced paper differ from the same
    list in an HTML-sourced one and from the blessed ideals (#303); nesting is
    carried by the indent, never by the marker glyph. Rewriting a literal ``*``
    marker also removes the one shape where an item's own text could be read as
    emphasis. An ordinal marker (``1.``, ``b)``) is meaningful and is kept.
    """
    text = text.strip()
    indent = _LIST_INDENT_UNIT * max(depth, 0)
    if text[:1] in BULLET_CHARS:
        return f"{indent}{LIST_BULLET} {_normalize_bullets(text[1:].lstrip())}"
    if _ASTERISK_MARKER_RE.match(text):
        body = _ASTERISK_MARKER_RE.sub("", text, count=1)
        return f"{indent}{LIST_BULLET} {_normalize_bullets(body)}"
    return f"{indent}{_normalize_bullets(text)}"


def _render_list_spans(sec: Section) -> str:
    """Render a list section, unwrapping each item and indenting nested ones.

    A LIST section is either a single (possibly line-wrapped) item from the
    position splitter or several clean bullet lines from the classification
    loop. Lines that start a new item open an item; the rest are wrapped
    continuations joined onto it. ``indent_level`` (assigned by
    :func:`structure._assign_list_nesting`) sets the nesting depth.
    """
    depth = max(sec.indent_level, 0)
    if not sec.lines:
        return _format_list_item(sec.text, depth)

    items: list[list[str]] = []
    for line in sec.lines:
        rendered = _render_line_spans(line).strip()
        if not rendered:
            continue
        current_item = " ".join(items[-1]) if items else ""
        if not items or _is_list_item_start(rendered, current_item):
            items.append([rendered])
        else:
            items[-1].append(rendered)

    return "\n".join(_format_list_item(" ".join(parts), depth) for parts in items)


# Two code fragments whose vertical centers are within this many points
# belong to the same visual row. WG21 code lines are ~12pt apart, so a
# few points cleanly separates "same line, wide gap" from "next line."
_ROW_Y_TOLERANCE = 3.0

# Separator inserted when a trailing same-row fragment (a right-aligned
# `// comment`) is rejoined to the code it annotates.
_SAME_ROW_JOIN = "  "

# A code block needs at least this many line-number candidates before
# the left column is treated as a gutter. Two stray numeric tokens
# (an array literal split across lines) must never trigger it.
_GUTTER_MIN_NUMBERS = 3

# A gutter cell is a pure integer (the source line number) and nothing
# else. Anchored so `1.` or `1)` list markers do not qualify.
_GUTTER_NUMBER_RE = re.compile(r"^\d+$")

# Maximum reconstructed indent for the gutter code path. Line-numbered
# listings are line-by-line code (rarely nested past a few levels); the
# deepest legitimate column observed in the gutter goldens is 8, so 32
# leaves comfortable headroom (4x) while still pinning a right-margin
# anchor (e.g. a stable-name fragment split onto its own line at x=500)
# back to column zero instead of pushing the real code past the right
# margin. The plain native path is intentionally uncapped because its
# legitimate continuation indents reach the high 30s.
_MAX_GUTTER_CODE_INDENT = 32


def _line_y_center(line: Line) -> float | None:
    """Vertical center of a line's first non-blank glyph, or None if blank."""
    for span in line.spans:
        if span.text.strip():
            return (span.bbox[1] + span.bbox[3]) / 2.0
    return None


def _first_nonspace_x(line: Line) -> float:
    """X-position of a line's first non-blank glyph (inf if fully blank)."""
    span = line.first_content_span()
    return span.bbox[0] if span is not None else float("inf")


def _group_code_rows(lines: list[Line]) -> list[list[Line]]:
    """Group lines that share one visual row (same y) into a single row.

    PDF extraction splits a code line from its right-aligned trailing
    comment (``f(v,5);    // good``) into separate ``Line`` objects
    because of the wide horizontal gap: the gap reads as a column break,
    not the line break it looks like. The two fragments share a y-range,
    so the vertical center is the reliable signal that they are really
    one line. A blank line resets the run so nothing merges across it.
    """
    rows: list[list[Line]] = []
    prev_center: float | None = None
    for line in lines:
        center = _line_y_center(line)
        if (center is not None and prev_center is not None
                and abs(center - prev_center) <= _ROW_Y_TOLERANCE):
            rows[-1].append(line)
        else:
            rows.append([line])
        prev_center = center
    return rows


def _gutter_line_value(line: Line) -> tuple[int, float, float] | None:
    """Return ``(value, x0, right_x)`` if a line is a gutter line-number cell.

    A gutter cell is a line whose every non-blank span is
    non-monospace (the source line numbers are typeset in the body
    serif font, not the code font) and whose text is a bare integer.
    Returns ``None`` for anything else: monospace lines, blank lines,
    and decorated numbers (``1.``, ``1)``) the regex rejects.
    """
    nonblank = [s for s in line.spans if s.text.strip()]
    if not nonblank or any(s.monospace for s in nonblank):
        return None
    text = line.text.strip()
    if not _GUTTER_NUMBER_RE.match(text):
        return None
    x0 = min(s.bbox[0] for s in nonblank)
    right_x = max(s.bbox[2] for s in nonblank)
    return int(text), x0, right_x


def _detect_code_gutter(
    sec: Section,
) -> tuple[dict[int, tuple[int, float]], float] | None:
    """Detect a left-margin source-line-number gutter in a CODE section.

    WG21 listings sometimes print a line-number column to the left of
    the code (P0876's fiber examples). Extraction keeps each number as
    its own non-monospace ``Line`` sharing the y-range of its code
    line. This finds that column so the renderer can keep the numbers
    while still reconstructing the code's own indentation.

    Returns ``(numbers, origin_x)`` where ``numbers`` maps a code line's
    index within ``sec.lines`` to ``(value, num_x0)`` for each code line
    that has a paired gutter number, and ``origin_x`` is the leftmost
    gutter glyph x (the grid origin shared by numbers and code). Keying
    by position (not object identity) keeps the pairing valid even if the
    lines are copied between detection and rendering. Returns ``None``
    unless at least ``_GUTTER_MIN_NUMBERS`` candidates form a strictly
    increasing sequence to the left of the monospace margin.
    """
    mono_x = [
        s.bbox[0] for ln in sec.lines for s in ln.spans
        if s.monospace and s.text.strip()
    ]
    if not mono_x:
        return None
    code_left = min(mono_x)

    gutter: list[tuple[int, int, float]] = []
    for i, ln in enumerate(sec.lines):
        cell = _gutter_line_value(ln)
        if cell is not None and cell[2] <= code_left:
            gutter.append((i, cell[0], cell[1]))

    if len(gutter) < _GUTTER_MIN_NUMBERS:
        return None
    values = [v for _, v, _ in gutter]
    if not all(b > a for a, b in zip(values, values[1:])):
        return None

    origin_x = min(x0 for _, _, x0 in gutter)
    gutter_idx = {i for i, _, _ in gutter}
    code_indices = [
        i for i, ln in enumerate(sec.lines)
        if i not in gutter_idx and any(s.text.strip() for s in ln.spans)
    ]

    numbers: dict[int, tuple[int, float]] = {}
    for gi, value, num_x0 in gutter:
        gy = _line_y_center(sec.lines[gi])
        if gy is None:
            continue
        best: int | None = None
        best_dy: float | None = None
        for ci in code_indices:
            cy = _line_y_center(sec.lines[ci])
            if cy is None:
                continue
            dy = abs(cy - gy)
            if dy <= _ROW_Y_TOLERANCE and (best_dy is None or dy < best_dy):
                best, best_dy = ci, dy
        if best is not None:
            numbers[best] = (value, num_x0)

    if not numbers:
        return None
    return numbers, origin_x


def _section_span_text_lines(sec: Section) -> list[str]:
    return ["".join(span.text for span in line.spans) for line in sec.lines]


def _render_code_block(sec: Section) -> str:
    """Render a code section as a fenced code block.

    Uses glyph x-positions to calculate indentation: the offset
    of each line's first character from the block's left margin,
    divided by the monospace character width. Fragments that share a
    visual row (a code line plus its right-aligned ``// comment``,
    split by extraction) are merged back onto one line.

    When the section carries a source-line-number gutter (see
    :func:`_detect_code_gutter`), rendering is delegated to
    :func:`_render_code_block_with_gutter`, which keeps the numbers.
    """
    lang = sec.fence_lang or DEFAULT_FENCE_LANG
    if not sec.lines:
        return f"```{lang}\n{sec.text}\n```"

    gutter = _detect_code_gutter(sec)
    if gutter is not None:
        return _render_code_block_with_gutter(sec, lang, gutter)

    preserve_spacing = is_diagram_block(_section_span_text_lines(sec))

    grid = CodeGrid.for_code_section(sec)

    def render_single(line: Line) -> str:
        raw = _render_line_spans(line, in_code_section=True)
        if not line.spans:
            return maybe_normalize_code_line(
                raw, preserve_spacing=preserve_spacing,
            )
        indent = grid.indent(line)
        return " " * indent + maybe_normalize_code_line(
            raw.lstrip(), preserve_spacing=preserve_spacing,
        )

    lines = []
    for row in _group_code_rows(sec.lines):
        if len(row) == 1:
            lines.append(render_single(row[0]))
            continue
        frags = sorted(
            (f for f in row if any(s.text.strip() for s in f.spans)),
            key=_first_nonspace_x,
        )
        if not frags:
            lines.append(render_single(row[0]))
            continue
        rendered = render_single(frags[0])
        for frag in frags[1:]:
            tail = maybe_normalize_code_line(
                _render_line_spans(frag, in_code_section=True).strip(),
                preserve_spacing=preserve_spacing,
            )
            if tail:
                rendered += _SAME_ROW_JOIN + tail
        lines.append(rendered)
    code = "\n".join(lines)
    return f"```{lang}\n{code}\n```"


def _render_code_block_with_gutter(
    sec: Section,
    lang: str,
    gutter: tuple[dict[int, tuple[int, float]], float],
) -> str:
    """Render a code block that carries a source-line-number gutter.

    Numbers and code share one character grid whose origin is the
    leftmost gutter glyph, so each fragment's column is
    ``round((x0 - origin_x) / char_w)``. Because the PDF right-aligns
    the gutter, placing each number left-aligned at its own column
    reproduces the right-aligned column, while the code keeps its true
    indentation (the gap between gutter and code falls out of the
    geometry, not a hardcoded separator). Trailing same-row fragments
    (a right-aligned ``// comment``) are collapsed with
    :data:`_SAME_ROW_JOIN` rather than grid-placed, to avoid runs of
    filler whitespace.
    """
    numbers, origin_x = gutter
    preserve_spacing = is_diagram_block(_section_span_text_lines(sec))

    grid = CodeGrid.for_gutter(sec, origin_x)
    index_of = {id(ln): i for i, ln in enumerate(sec.lines)}
    code_lines = [
        ln for ln in sec.lines if _gutter_line_value(ln) is None
    ]

    out_lines: list[str] = []
    for row in _group_code_rows(code_lines):
        frags = sorted(
            (f for f in row if any(s.text.strip() for s in f.spans)),
            key=_first_nonspace_x,
        )
        number: tuple[int, float] | None = None
        for f in row:
            candidate = numbers.get(index_of[id(f)])
            if candidate is not None:
                number = candidate
                break

        if not frags:
            out_lines.append("")
            continue

        lead = frags[0]
        code_col = grid.column(_first_nonspace_x(lead))
        # An implausibly deep column means the leading fragment is a
        # right-margin element (a stable-name anchor split onto its
        # own line), not real indentation; pin it back to column zero
        # so the actual code is not pushed past the right margin.
        if code_col > _MAX_GUTTER_CODE_INDENT:
            code_col = 0
        code_str = maybe_normalize_code_line(
            _render_line_spans(lead, in_code_section=True).lstrip(),
            preserve_spacing=preserve_spacing,
        )

        if number is not None:
            value, num_x0 = number
            num_str = str(value)
            buf = " " * grid.column(num_x0) + num_str
        else:
            buf = ""
        if code_col <= len(buf):
            code_col = len(buf) + 1 if buf else 0
        buf += " " * (code_col - len(buf)) + code_str

        for frag in frags[1:]:
            tail = maybe_normalize_code_line(
                _render_line_spans(frag, in_code_section=True).strip(),
                preserve_spacing=preserve_spacing,
            )
            if tail:
                buf += _SAME_ROW_JOIN + tail
        out_lines.append(buf)

    code = "\n".join(out_lines)
    return f"```{lang}\n{code}\n```"


# Intentionally limited to the two ZapfDingbats glyphs observed in the
# corpus (checkmark and cross).  Unmapped dingbats pass through as-is;
# extend this map when new glyphs are encountered in real papers.
_DINGBATS_MAP: dict[int, str] = {
    0x14: "✓",
    0x18: "✗",
}


def _decode_dingbats(span: Span) -> Span:
    """Replace Dingbats-encoded control chars with Unicode equivalents.

    MuPDF passes through raw byte values for ZapfDingbats glyphs
    (e.g. 0x14 → ✓, 0x18 → ✗).  These are C0 control characters in
    Unicode and would be invisible or stripped.  Only fires for spans
    with font_name containing "Dingbats".
    """
    if "Dingbats" not in (span.font_name or ""):
        return span
    out: list[str] = []
    changed = False
    for ch in span.text:
        mapped = _DINGBATS_MAP.get(ord(ch))
        if mapped:
            out.append(mapped)
            changed = True
        else:
            out.append(ch)
    if not changed:
        return span
    return Span(
        text="".join(out),
        font_name=span.font_name,
        font_size=span.font_size,
        bold=span.bold,
        italic=span.italic,
        monospace=span.monospace,
        bbox=span.bbox,
        origin=span.origin,
        color=span.color,
        link_url=span.link_url,
        wording_role=span.wording_role,
    )


def _render_cell_spans(spans: list, suppress_bold: bool = False) -> str:
    """Render a table cell's spans with inline formatting.

    When every non-whitespace span is monospace, all spans are merged into a
    single backtick pair to avoid fragmented output like `t``<``U`.
    Newline marker spans (from table.py line-merge) become spaces in pipe tables.
    """
    if not spans:
        return ""
    # Decode Dingbats font control chars (✓/✗) before rendering
    spans = [_decode_dingbats(s) for s in spans]
    # Replace newline markers with spaces for pipe-table rendering. The
    # marker is whitespace-only but its exact spelling varies by producer
    # ("\n", " \n", "\n  "), so test the shape rather than the literal.
    flat_spans = []
    for s in spans:
        if not s.text.strip() and "\n" in s.text:
            if flat_spans and flat_spans[-1].text.endswith(" "):
                continue
            flat_spans.append(Span(text=" "))
        else:
            flat_spans.append(s)
    text_spans = [s for s in flat_spans if s.text.strip()]
    if text_spans and all(s.monospace for s in text_spans):
        merged = "".join(s.text for s in flat_spans).strip()
        if merged:
            return f"`{merged}`"
    line = Line(spans=flat_spans)
    result = _render_line_spans(line, suppress_bold=suppress_bold).strip()
    return result.replace("|", "\\|")


def _spans_to_code_lines(spans: list) -> str:
    """Convert cell spans to multi-line code text.

    Newline marker spans (text="\\n") from table.py line-merge are
    converted to actual newlines. All other spans are concatenated as raw text.
    """
    if not spans:
        return ""
    spans = [_decode_dingbats(s) for s in spans]
    parts: list[str] = []
    for sp in spans:
        if sp.text == "\n":
            parts.append("\n")
        else:
            parts.append(sp.text)
    return "".join(parts).strip()


def _render_code_comparison(sec: Section) -> str:
    """Render a code-comparison table as side-by-side fenced code blocks.

    Each cell may contain multiple logical lines marked by newline spans
    (text="\\n") inserted by table.py during cell merge.
    If the first row contains short labels (e.g. "Before" / "After"),
    they are used as headings above each code block.
    """
    if not sec.columns:
        return sec.text

    rows = sec.columns
    num_cols = max(len(row) for row in rows) if rows else 0

    # Detect header row: first row with only short text (<=3 words per cell)
    headers: list[str] = []
    data_start = 0
    if rows:
        first_row = rows[0]
        first_row_texts = []
        for cell in first_row:
            t = "".join(_decode_dingbats(s).text for s in cell).strip()
            first_row_texts.append(t)
        if all(len(t.split()) <= 3 for t in first_row_texts) and any(first_row_texts):
            headers = first_row_texts
            data_start = 1

    blocks_per_col: list[list[str]] = [[] for _ in range(num_cols)]
    for row in rows[data_start:]:
        for col_idx in range(num_cols):
            if col_idx < len(row):
                cell_spans = row[col_idx]
                cell_text = _spans_to_code_lines(cell_spans)
            else:
                cell_text = ""
            blocks_per_col[col_idx].append(cell_text)

    parts = []
    for col_idx, col_lines in enumerate(blocks_per_col):
        content = "\n".join(col_lines).strip()
        if content:
            label = ""
            if headers and col_idx < len(headers) and headers[col_idx]:
                label = f"// {headers[col_idx]}\n"
            parts.append(f"```cpp\n{label}{content}\n```")

    return "\n\n".join(parts)


def _render_table_as_text(sec: Section) -> str:
    """Render a false-positive table as plain paragraphs."""
    if not sec.columns:
        return sec.text

    parts = []
    for row in sec.columns:
        row_parts = []
        for cell_spans in row:
            cell_text = "".join(
                _decode_dingbats(s).text for s in cell_spans).strip()
            if cell_text:
                row_parts.append(cell_text)
        if row_parts:
            parts.append(" ".join(row_parts))

    return "\n\n".join(parts)


def _cell_text(row: list, ci: int) -> str:
    """Extract plain text from a cell's span list."""
    if ci >= len(row):
        return ""
    return "".join(s.text for s in row[ci]).strip()


def _render_html_table(sec: Section) -> str:
    """Render a table as HTML with <pre> blocks for multi-line code cells.

    Used for code-comparison tables (e.g. "Tony Tables") where each cell
    contains multi-line code that would be flattened by a pipe table.

    When ``sec.table_continuation`` is true the section is a cross-page
    continuation whose duplicate header has been stripped.  All rows are
    rendered as ``<td>`` data cells (no ``<th>`` header row).
    """
    if not sec.columns:
        return sec.text

    rows = sec.columns
    is_continuation = getattr(sec, "table_continuation", False)
    num_cols = max(len(row) for row in rows)
    # Shared markup (table tag, cell style, <pre><code> wrapping) lives in
    # lib/tables.py so PDF and HTML comparison tables render identically.
    _S = _tables.cell_style(num_cols)
    parts: list[str] = []
    # Mark code comparisons as structure-preserving, matching the HTML
    # renderer. Other html_table kinds (SPEC_TABLE, nb_ballot) are not
    # "mixed code" tables, so they carry no marker.
    if getattr(sec, "table_kind", None) == "code_comparison":
        parts.append(_tables.MIXED_TABLE_MARKER)
    parts.append(_tables.TABLE_OPEN)

    # NB-ballot cells: newlines are MuPDF line-wrapping artifacts from
    # narrow PDF columns, not semantic breaks. Collapse to spaces.
    is_nb_ballot = getattr(sec, "table_kind", None) == "nb_ballot"
    collapse_newlines = is_nb_ballot

    # Pre-compute rowspan for col-0 in NB-ballot tables: when consecutive
    # data rows have an empty col-0 they are continuations of the same NB
    # number, so the first row's col-0 cell spans them all (like the PDF).
    col0_rowspan: dict[int, int] = {}  # ri -> span count (only for starters)
    col0_skip: set[int] = set()        # ri values to skip col-0 rendering
    if is_nb_ballot:
        ri = 1 if not is_continuation else 0  # skip header row
        while ri < len(rows):
            span_start = ri
            span_count = 1
            while (ri + span_count < len(rows)
                   and _cell_text(rows[ri + span_count], 0) == ""):
                span_count += 1
            if span_count > 1:
                col0_rowspan[span_start] = span_count
                for k in range(span_start + 1, span_start + span_count):
                    col0_skip.add(k)
            ri += span_count

    for ri, row in enumerate(rows):
        parts.append("<tr>")
        is_header = (ri == 0 and not is_continuation)
        tag = "th" if is_header else "td"
        for ci in range(num_cols):
            if ci == 0 and ri in col0_skip:
                continue
            cell_spans = row[ci] if ci < len(row) else []
            cell_spans = [_decode_dingbats(s) for s in cell_spans]
            cell_lines: list[str] = []
            current_line: list[str] = []
            for span in cell_spans:
                if span.text == "\n":
                    cell_lines.append("".join(current_line))
                    current_line = []
                else:
                    current_line.append(span.text)
            if current_line:
                cell_lines.append("".join(current_line))
            if collapse_newlines:
                text = " ".join(
                    part for line in cell_lines
                    for part in [line.strip()] if part
                ).strip()
            else:
                text = "\n".join(cell_lines).strip()
            rowspan = col0_rowspan[ri] if (ci == 0 and ri in col0_rowspan) else 1
            if is_header or not text:
                # Header/empty cells carry plain escaped text (the PDF side
                # has spans, not inline tags); text_cell emits it verbatim.
                parts.append(_tables.text_cell(
                    tag, _html.escape(text), _S, rowspan=rowspan))
            else:
                parts.append(_tables.code_cell(tag, text, _S, rowspan=rowspan))
        parts.append("</tr>")

    parts.append(_tables.TABLE_CLOSE)
    return "\n".join(parts)


_CELL_WRAP_RE = re.compile(r"\s*\n\s*")


def _flatten_cell(text: str) -> str:
    """Collapse a soft-wrapped cell onto one line for pipe-table rendering.

    Only whitespace runs containing a newline are collapsed, so how much
    space surrounds the wrap point does not matter and space runs elsewhere
    (inline code) are left alone.
    """
    return _CELL_WRAP_RE.sub(" ", text).strip()


def _render_table(sec: Section) -> str:
    """Render a table section according to its assigned strategy."""
    if sec.table_strategy == "code_blocks":
        return _render_code_comparison(sec)
    if sec.table_strategy == "html_table":
        return _render_html_table(sec)
    if sec.table_strategy == "skip":
        return _render_table_as_text(sec)

    if not sec.columns:
        return sec.text

    rows = sec.columns
    is_continuation = getattr(sec, "table_continuation", False)
    num_cols = max(len(row) for row in rows)

    lines = []
    if is_continuation:
        data_rows = rows
    else:
        header = rows[0]
        header_cells = [
            _flatten_cell(_render_cell_spans(cell, suppress_bold=True))
            for cell in header
        ]
        while len(header_cells) < num_cols:
            header_cells.append("")
        lines.append("| " + " | ".join(header_cells) + " |")
        lines.append("| " + " | ".join(["---"] * num_cols) + " |")
        data_rows = rows[1:]

    for row in data_rows:
        cells = [
            _flatten_cell(_render_cell_spans(cell))
            for cell in row
        ]
        while len(cells) < num_cols:
            cells.append("")
        lines.append("| " + " | ".join(cells) + " |")

    return "\n".join(lines)


_ITALIC_INLINE_ESCAPE_RE = re.compile(r"([\\*_`])")
# Leading characters that would otherwise be parsed as a list marker,
# blockquote, ATX heading, or ordered-list start. The synthesised
# sub-caption paragraph (text == "*...*") would be misclassified if any
# of these appears at column 0 inside the italics wrapper.
_LEADING_BLOCK_CHARS = ("-", "*", "+", ">", "#")
_LEADING_ORDERED_RE = re.compile(r"^(\d+)\.")


def _escape_italic_text(text: str) -> str:
    """Escape characters that would break a ``*...*`` italic wrapper.

    Used by the sub-caption insertion path in the pipeline (sub-caption
    PARAGRAPH sections are emitted as ``*<escaped>*``). Escapes:

    - ``\\`` so a trailing backslash doesn't eat the closing ``*``.
    - ``*``, ``_``, and backticks so they don't terminate the wrapper
      or open a code span.
    - A leading list/quote/heading character so the paragraph doesn't
      render as a list item, blockquote, or heading once the italics
      wrapper is in place.
    """
    escaped = _ITALIC_INLINE_ESCAPE_RE.sub(r"\\\1", text)
    if not escaped:
        return escaped
    if escaped[0] in _LEADING_BLOCK_CHARS:
        # The first character has already been backslash-escaped if it
        # was ``*``; the other leading-block characters need their own
        # leading backslash.
        if escaped[0] != "\\":
            escaped = "\\" + escaped
    else:
        m = _LEADING_ORDERED_RE.match(escaped)
        if m:
            escaped = escaped[:m.end() - 1] + "\\." + escaped[m.end():]
    return escaped


def _render_image(sec: Section) -> str:
    """Render a :class:`SectionKind.IMAGE` section as its caption text.

    No image syntax is ever emitted (#408): the LLM consumer cannot use
    pixels, and the sidecar file on disk is not a markdown concern. The
    caption is re-emitted as an italic paragraph (same shape as
    sub-caption paragraphs) only when the pipeline dropped the body copy
    (:attr:`ExtractedImage.caption_body_dropped`) - when the equality
    gate kept the body section (caption merged with trailing prose), the
    body still carries the caption and re-emitting would duplicate it.
    An image without a dropped body caption renders as nothing.

    Reads the alt text from :attr:`Section.image_ref.suggested_alt`
    (not :attr:`Section.text` - IMAGE sections carry empty text by
    design, see types.py).
    """
    if sec.image_ref is None:
        return ""
    alt = sec.image_ref.suggested_alt
    if not alt or not sec.image_ref.caption_body_dropped:
        return ""
    return "*" + _escape_italic_text(alt) + "*"


def _render_section_md(sec: Section) -> str:
    """Render a single section to Markdown."""
    if sec.kind in (SectionKind.TITLE, SectionKind.HEADING):
        return _render_heading_spans(sec)

    if sec.kind == SectionKind.TABLE:
        return _render_table(sec)

    if sec.kind == SectionKind.IMAGE:
        return _render_image(sec)

    if sec.kind == SectionKind.CODE:
        return _render_code_block(sec)

    if sec.kind == SectionKind.LIST:
        return _render_list_spans(sec)

    if sec.kind in (SectionKind.WORDING, SectionKind.WORDING_ADD,
                    SectionKind.WORDING_REMOVE):
        return _render_wording_section(sec)

    if sec.kind == SectionKind.FIGURE:
        # Figures (vector-graphic diagrams) are not supported: tomd never
        # attempts to describe them in text. The FIGURE classification
        # still exists upstream to keep diagram label fragments out of
        # heading/paragraph/table classification; here it is simply
        # dropped from the output.
        return ""

    if sec.kind == SectionKind.PARAGRAPH:
        return _render_paragraph_spans(sec)

    return sec.text


_EMDASH_NESTING_X_THRESHOLD = 6.0


def _is_emdash_bullet_section(sec: Section) -> bool:
    """True when every non-empty raw line starts with an em/en-dash bullet."""
    if sec.kind != SectionKind.PARAGRAPH or not sec.lines:
        return False
    for line in sec.lines:
        raw = "".join(s.text for s in line.spans).strip()
        if raw and not _EMDASH_BULLET_RE.match(raw):
            return False
    return bool(sec.lines)


def _section_min_x0(sec: Section) -> float:
    """Leftmost x-coordinate across all lines in the section."""
    x0s = [ln.bbox[0] for ln in sec.lines if ln.bbox]
    return min(x0s) if x0s else 0.0


def _assign_emdash_nesting(sections: list[Section]) -> None:
    """Pre-pass: set indent_level on consecutive em-dash bullet sections.

    Groups of adjacent em-dash PARAGRAPH sections are identified.
    Within each group, the leftmost x0 is the base level (indent 0).
    Sections whose x0 is shifted right by >= _EMDASH_NESTING_X_THRESHOLD
    get increasing indent_level values.
    """
    n = len(sections)
    i = 0
    while i < n:
        if not _is_emdash_bullet_section(sections[i]):
            i += 1
            continue
        group_start = i
        while i < n and _is_emdash_bullet_section(sections[i]):
            i += 1
        group = sections[group_start:i]
        if len(group) < 2:
            continue
        x0s = [_section_min_x0(s) for s in group]
        base_x0 = min(x0s)
        unique_x = sorted(set(x0s))
        level_map: dict[float, int] = {}
        for ux in unique_x:
            if ux - base_x0 < _EMDASH_NESTING_X_THRESHOLD:
                level_map[ux] = 0
            else:
                level_map[ux] = len(
                    [v for v in level_map.values() if v > 0]
                ) + 1
        for sec, x0 in zip(group, x0s):
            sec.indent_level = level_map.get(x0, 0)


def _annotate_wrap(rendered: str, sec: Section) -> str:
    """Wrap rendered markdown in a colored HTML div for highlight mode."""
    from .highlight import KIND_COLORS, CONFIDENCE_BORDERS
    bg = KIND_COLORS.get(sec.kind.value, "transparent")
    border = CONFIDENCE_BORDERS.get(sec.confidence.value, "3px solid #ccc")
    kind_label = sec.kind.value.replace("-", " ")
    return (
        f'<div style="background:{bg};border-left:{border};'
        f'padding:4px 10px;margin:2px 0;border-radius:3px" '
        f'title="{kind_label} | {sec.confidence.value} | page {sec.page_num}">\n\n'
        f'{rendered}\n\n'
        f'</div>'
    )


def emit_markdown(
    metadata: dict,
    sections: list[Section],
    *,
    annotate: bool = False,
    images_truncated: bool = False,
    source_image_count: int = 0,
    vector_uncertainty: VectorUncertaintyStats | None = None,
    glyph_stats: GlyphPassStats | None = None,
) -> str:
    """Generate the output Markdown from structured sections.

    Confident sections are clean Markdown. Uncertain sections emit
    the MuPDF version marked with an HTML comment.

    When *annotate* is True, each section's rendered markdown is wrapped
    in a colored HTML ``<div>`` whose background indicates the
    ``SectionKind`` and whose left-border indicates ``Confidence``.
    The result is valid markdown+HTML that scrivener renders correctly,
    producing the same layout as the normal view but with colored
    section backgrounds.  Used by the preview highlight overlay.

    When ``images_truncated`` is True, an HTML comment is appended at
    end-of-body recording how many images were kept versus how many
    the source contained.

    When ``vector_uncertainty`` is non-None and
    :func:`should_emit_marker` returns True, a second HTML comment is
    appended with the per-paper vector-extraction accounting (pages
    scanned / skipped, candidates, kept, rejected, reasons dict). The
    marker exists so a reader can see why diagrams might be missing
    or surprisingly present.

    When ``glyph_stats`` is non-None and the glyph-placeholder pass
    placed any U+FFFD or skipped any coincident rect, a trailing
    ``tomd:glyph-placeholders`` comment is appended last - its
    ``placeholders`` count is taken from the finished body (after
    duplicate-paragraph collapse) so it matches a grep of the output.
    """
    _assign_emdash_nesting(sections)

    # Pre-pass: fold cross-page table continuations into the preceding
    # table so they render as a single HTML/pipe table.  The detection
    # layer marks the continuation with table_continuation=True and has
    # already stripped its duplicate header row.
    folded: set[int] = set()
    for i in range(len(sections) - 1, 0, -1):
        sec = sections[i]
        if (sec.kind == SectionKind.TABLE
                and getattr(sec, "table_continuation", False)
                and sec.columns):
            # Walk backwards to find the preceding TABLE section
            # (skipping any interleaved non-table sections like page
            # numbers or headings that the pipeline may have inserted).
            for j in range(i - 1, -1, -1):
                prev = sections[j]
                if prev.kind == SectionKind.TABLE and prev.columns:
                    prev.columns.extend(sec.columns)
                    prev.text = "\n".join(
                        " | ".join(
                            "".join(s.text for s in cell).strip()
                            for cell in row)
                        for row in prev.columns)
                    folded.add(i)
                    break
    if folded:
        sections = [s for i, s in enumerate(sections) if i not in folded]

    parts: list[str] = []

    fm = format_front_matter(metadata)
    if fm:
        parts.append(fm)

    line_num = fm.count("\n") + 3 if fm else 1

    for sec in sections:
        if sec.kind == SectionKind.UNCERTAIN:
            text = sec.text.rstrip()
            text_lines = text.count("\n") + 1
            text_start = line_num + 2
            comment = f"<!-- tomd:uncertain:L{text_start}-L{text_start + text_lines - 1} -->"
            if annotate:
                parts.append(_annotate_wrap(comment + "\n\n" + text, sec))
            else:
                parts.append(comment)
                parts.append(text)
            line_num += text_lines + 3
            continue

        rendered = _render_section_md(sec)
        if not rendered.strip():
            continue
        # Skip headings that render as bare ATX prefix with no text.
        if sec.kind in (SectionKind.TITLE, SectionKind.HEADING):
            if not rendered.lstrip("#").strip():
                continue
        if is_flagged_table(sec) or sec.metadata.get("possible_table"):
            # A table no second kind of evidence confirmed, or text that may be a
            # table no reader produced: marked like any uncertain region, its
            # rendering kept. A table's level comment (levels.py) says how it may
            # be wrong; the marker touches the table.
            head = []
            lv = sec.metadata.get("level") if sec.kind == SectionKind.TABLE else None
            if lv and lv.get("level", 0) >= SHOWN_FROM and not sec.metadata.get("possible_table"):
                head.append(level_comment(lv))
            text_lines = rendered.count("\n") + 1
            text_start = line_num + 2 * len(head) + 2
            block = head + [f"<!-- tomd:uncertain:L{text_start}-L{text_start + text_lines - 1} -->", rendered]
            if annotate:
                parts.append(_annotate_wrap("\n\n".join(block), sec))
            else:
                parts.extend(block)
            line_num += 2 * len(head) + text_lines + 3
            continue
        if annotate:
            rendered = _annotate_wrap(rendered, sec)
        parts.append(rendered)
        line_num += rendered.count("\n") + 2

    if images_truncated and source_image_count > 0:
        kept_count = sum(
            1 for sec in sections if sec.kind == SectionKind.IMAGE
        )
        dropped = source_image_count - kept_count
        if dropped > 0:
            parts.append(TRUNCATION_MARKER_TEMPLATE.format(
                kept=kept_count,
                total=source_image_count,
                dropped=dropped,
            ))

    if vector_uncertainty is not None and should_emit_marker(vector_uncertainty):
        parts.append(format_uncertainty_marker(vector_uncertainty))

    md = "\n\n".join(parts)
    md = dedup_paragraphs(md)
    md = strip_redundant_body_meta(md)
    md = strip_orphan_toc_list(md)

    # Inject a <style> block for table borders when the document
    # contains HTML tables. VS Code / Cursor markdown preview strips
    # inline style attributes but honours embedded <style> tags.
    if "<table " in md:
        _TABLE_CSS = (
            "<style>\n"
            "table, th, td { border: 1px solid #999; "
            "border-collapse: collapse; padding: 6px 10px; }\n"
            "th { background: #f5f5f5; }\n"
            "</style>"
        )
        insert_after = None
        if fm:
            fm_end = _find_front_matter_end(md)
            if fm_end is not None:
                line_end = md.find("\n", fm_end)
                if line_end >= 0:
                    insert_after = line_end + 1
        if insert_after is not None:
            md = md[:insert_after] + "\n" + _TABLE_CSS + "\n" + md[insert_after:]
        else:
            md = _TABLE_CSS + "\n\n" + md

    if fm:
        md = apply_strip_leading_h1(md, metadata.get("title", ""))

    # Glyph-placeholder marker, appended last so its ``placeholders``
    # count reflects the U+FFFD actually present in the finished body
    # (after duplicate-paragraph collapse), matching what a reader greps.
    # Fires when any placeholder survived or any coincident rect was
    # skipped (a pure-coincident paper still emits placeholders=0 for
    # traceability).
    if glyph_stats is not None:
        present = md.count(UNKNOWN_GLYPH)
        if (present or glyph_stats.skipped_coincident
                or glyph_stats.skipped_code_section):
            md = md.rstrip() + "\n\n" + GLYPH_PLACEHOLDER_MARKER_TEMPLATE.format(
                placeholders=present,
                skipped_coincident=glyph_stats.skipped_coincident,
                skipped_code_section=glyph_stats.skipped_code_section,
            )

    md = md.rstrip() + "\n"
    if not annotate:
        md = renumber_uncertain_markers(md)
    return md


def is_flagged_table(sec: Section) -> bool:
    """A TABLE section no second kind of evidence confirmed (select.trust_tables)."""
    return sec.kind == SectionKind.TABLE and sec.confidence == Confidence.UNCERTAIN


_UNCERTAIN_MARKER_RE = re.compile(r"^<!-- tomd:uncertain:L(\d+)-L(\d+) -->$")
# Lines from an uncertainty marker to the first line it covers: the marker, then a blank line.
_MARKER_TO_TEXT = 2


def renumber_uncertain_markers(md: str) -> str:
    """Point every ``tomd:uncertain:L{a}-L{b}`` marker at the lines under it.

    Emit numbers the markers as it writes them; later rewrites (duplicate
    paragraphs collapsed, the table style block, front matter normalized,
    the contents stripped) shift lines. Each marker keeps the number of lines
    it covers and is renumbered from its own position: the covered text
    starts two lines below the marker.
    """
    lines = md.split("\n")
    for i, ln in enumerate(lines):
        m = _UNCERTAIN_MARKER_RE.match(ln)
        if m:
            span = int(m.group(2)) - int(m.group(1))
            start = i + 1 + _MARKER_TO_TEXT
            lines[i] = f"<!-- tomd:uncertain:L{start}-L{start + span} -->"
    return "\n".join(lines)


def emit_prompts(sections: list[Section]) -> list[str] | None:
    """Generate self-contained LLM reconcile prompts for uncertain regions.

    Each returned element is a complete prompt the operator can paste into
    any LLM verbatim. Returns ``None`` when there are no uncertain regions.
    """
    uncertain = [(idx, s) for idx, s in enumerate(sections)
                 if s.kind == SectionKind.UNCERTAIN]
    if not uncertain:
        return None

    prompts: list[str] = []
    for idx, sec in uncertain:
        ctx_before = ""
        ctx_after = ""
        if idx > 0 and sections[idx - 1].kind != SectionKind.UNCERTAIN:
            ctx_before = sections[idx - 1].text[:200].strip()
        if idx + 1 < len(sections) and sections[idx + 1].kind != SectionKind.UNCERTAIN:
            ctx_after = sections[idx + 1].text[:200].strip()

        parts: list[str] = []
        parts.append(
            "You are reconciling text extracted from a PDF using two independent "
            "methods that produced different results. Reconcile them into clean "
            "Markdown."
        )
        parts.append("")
        parts.append(
            "CRITICAL: Keep ALL data verbatim. Do not summarize, omit, or paraphrase "
            "any text. Every word from the source must appear in your output. You are "
            "only fixing structure (paragraphs, headings, lists, formatting) - never "
            "content."
        )
        parts.append("")
        parts.append(f"This region is on page {sec.page_num}.")
        parts.append("")

        if ctx_before:
            parts.append("Context (preceding confident section):")
            parts.append(f"> {ctx_before}")
            parts.append("")

        parts.append("MuPDF extraction:")
        parts.append("```")
        parts.append(sec.mupdf_text or sec.text)
        parts.append("```")
        parts.append("")
        parts.append("Spatial extraction:")
        parts.append("```")
        parts.append(sec.spatial_text or sec.text)
        parts.append("```")

        if ctx_after:
            parts.append("")
            parts.append("Context (following confident section):")
            parts.append(f"> {ctx_after}")

        prompts.append("\n".join(parts))

    return prompts
