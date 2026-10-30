"""Dual-path comparison, heading intelligence, and document structuring."""

import logging
import math
import re
import statistics
import unicodedata
from collections import Counter
from dataclasses import replace

from .. import (
    CODE_LANG_LABELS, DATE_RE, DEFAULT_FENCE_LANG, SECTION_NUM_PATTERN,
    SECTION_NUM_PREFIX_RE, strip_format_chars,
)
# `drop_leaked_toc_entries` reuses toc.py's TOC-recognition helpers so the
# two "what is a TOC" definitions stay a single source of truth (see #122).
from ..toc import MIN_TOC_RUN, is_toc_label, normalize_toc_entry
from .cleanup import collect_hyphen_evidence, dehyphenate_pair
from .glyphs import GLYPH_FONT_SENTINEL, UNKNOWN_GLYPH
from .wording import is_foreign_chromatic
from tomd.domain.elements import Confidence

from .types import (
    Block, Line, Span, Section, SectionKind,
    FigureRegion,
    SIMILARITY_THRESHOLD, TERMINAL_PUNCTUATION, FALLBACK_BODY_SIZE,
    MIN_UNCERTAIN_WORDS, compute_bbox,
    SECTION_NUM_RE,
    BULLET_RE, NUMBERED_LIST_RE, KNOWN_SECTIONS, BULLET_CHARS,
    ZERO_WIDTH_CHARS,
)

_HEADING_SIZE_RATIO = 1.05
_TITLE_SIZE_RATIO = 1.2

# Minimum font-size drop (points) between a heading's first line and a
# subsequent line to trigger a heading/body split.  Calibrated from corpus:
# real heading+body merges show 2+ pt differences; same-level heading
# continuations show 0-1 pt jitter.
_HEADING_BODY_SPLIT_DELTA = 2.0

# Max words in a heading's first physical line. Beyond this the line is
# prose, not a title. Numbered spec clauses ("1 A fiber is a single flow
# of control...") and numeric arithmetic results that happen to start a
# continuation line both trigger SECTION_NUM_RE; this length cap rejects
# them downstream. Real WG21 section titles are 1-8 words.
_HEADING_MAX_WORDS = 12

# Characters that indicate code, not a heading. Used to reject
# bold-only heading candidates that are really code fragments.
_CODE_CHARS = frozenset("{}();=<>[]")


def _line_color(line) -> int | None:
    """Dominant text color of a line (first non-whitespace span), or None."""
    for span in line.spans:
        if span.text.strip():
            return span.color
    return None


_TITLE_MAX_LENGTH = 120
# Max font-size deviation (fraction) for a subsequent LARGE section to
# be treated as a title continuation rather than a new heading.
# Calibrated from corpus: real continuations are 0-6.3%; non-continuations
# start at 20%+. The 10% threshold sits in the 14-point gap between the
# two populations.
_TITLE_CONT_FONT_TOL = 0.10
_TITLE_CONT_SKIP = frozenset({
    "revisions", "contents", "foreword", "agenda",
    "table of contents", "tony table",
})
_TITLE_CONT_DATE_RE = re.compile(
    r"^\s*(?:january|february|march|april|may|june|july|august|"
    r"september|october|november|december"
    r"|\d{4}[-/]\d{2}|\d{1,2}\s+\w+\s+\d{4})",
    re.IGNORECASE,
)
# Strip leading paper-ID prefix (e.g. "P4016R0 — ...", "Nicolai Josuttis: P3725R2: ...")
# from extracted titles. Only strips when meaningful text remains after removal.
_TITLE_PID_PREFIX_RE = re.compile(
    r"^(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s*:\s*)?"  # optional "Firstname Lastname: "
    r"[PNpn]\d{3,5}[Rr]\d+\s*[\-\u2014:,.]?\s*",
)
_BODY_MARGIN_FRACTION = 0.1
_BULLET_JOIN_MAX_CHARS = 3


_log = logging.getLogger(__name__)

# Intentionally narrower than qa.py's _STRUCTURAL_CODE_RE.
# Here the regex drives the rescue pass (promoting paragraphs to code
# blocks). Broader patterns (template<, namespace/class/struct/enum)
# cause false positives on flattened tables, so they are excluded.
_STRUCTURAL_CODE_RE = re.compile(
    r"^\s*[{}]|"               # standalone brace lines
    r";\s*$|"                  # trailing semicolons
    r"#include\s*<|"           # preprocessor includes
    r"#define\s+\w|"           # preprocessor defines
    r"\w+\s*\([^)]*\)\s*\{|"  # function_name(...) {
    r"\w+\s*\([^)]*\)\s*;|"   # declaration: name(...);
    r"^\s*static_assert\s*\(|" # static_assert(
    r"^\s*//[^/]|"             # C++ line comments (not URLs with //)
    r"^\s*(?:constexpr|consteval|constinit|template\s*<|namespace)\b",
    re.MULTILINE,
)

_RESCUE_MIN_CODE_LINES = 3


# str.translate table that drops the shared ZERO_WIDTH_CHARS (types.py),
# so a line carrying only zero-width invisibles counts as empty.
_ZERO_WIDTH = {c: None for c in ZERO_WIDTH_CHARS}


def _section_geometry_lines(sec: Section) -> list[Line]:
    """Lines that carry usable geometry for positioning ``sec``.

    A line qualifies only when it is on the section's own page, carries a
    real bbox (not the default (0, 0, 0, 0)), and has real text after
    stripping whitespace and zero-width invisibles. The own-page filter
    matters because the cross-page join (cleanup step) appends a
    continuation line from the next page into the last section of a page;
    that line's small top-of-page y must not anchor the section. A
    section's page_num is where it begins, which is the correct anchor
    page. The UNKNOWN_GLYPH placeholder is intentionally not stripped: it
    stands at a real reading-order position and represents real (if
    unidentified) content, so it anchors like any other content line.
    """
    return [
        ln for ln in sec.lines
        if ln.page_num == sec.page_num
        and ln.bbox != (0, 0, 0, 0)
        and ln.text.translate(_ZERO_WIDTH).strip()
    ]


def _section_top_y(sec: Section) -> float:
    """Topmost y of a section's content lines, for reading-order repair.

    A section with no anchorable line returns +inf, sorting to the end of
    its page rather than being hoisted above positioned content. In
    practice every section compare_extractions builds carries block lines
    with real bboxes; the +inf path is purely defensive.
    """
    ys = [ln.bbox[1] for ln in _section_geometry_lines(sec)]
    return min(ys) if ys else math.inf


# Two sections are side-by-side (different columns) when they overlap
# vertically but are separated by a horizontal gutter. A page with any
# such pair is multi-column; MuPDF already emits it in column reading
# order, so the repair leaves it untouched. Thresholds are permissive
# because the failure mode of over-detecting is benign (forgo the repair
# on that page), while under-detecting would interleave real columns.
_COLUMN_GUTTER_MIN = 10.0    # min horizontal gap (pt) between columns
_COLUMN_VOVERLAP_MIN = 3.0   # min vertical overlap (pt) to be side-by-side


def _section_bbox(sec: Section) -> tuple[float, float, float, float] | None:
    """Bounding box over a section's positioned content lines, or None.

    Shares _section_geometry_lines with _section_top_y so the column
    guard and the y-anchor agree on which lines carry usable geometry.
    """
    boxes = [ln.bbox for ln in _section_geometry_lines(sec)]
    return compute_bbox(boxes) if boxes else None


def _page_is_multicolumn(page_sections: list[Section]) -> bool:
    """True if any two sections are side-by-side (same y band, gutter between)."""
    boxes = [b for b in (_section_bbox(s) for s in page_sections) if b]
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            voverlap = min(a[3], b[3]) - max(a[1], b[1])
            if voverlap < _COLUMN_VOVERLAP_MIN:
                continue
            gutter = max(b[0] - a[2], a[0] - b[2])
            if gutter >= _COLUMN_GUTTER_MIN:
                return True
    return False


def _reorders_only_monospace(original: list[Section],
                             y_sorted: list[Section]) -> bool:
    """True if y_sorted moves only all-monospace sections vs original.

    Compares the non-monospace subsequences by identity: if every
    non-monospace section sits in the same relative position before and
    after the sort, the only sections that moved are code blocks.

    The lengths are always equal (y_sorted is a permutation of original),
    but the explicit length check makes that precondition local rather
    than resting on it implicitly: without it a shorter list would let
    zip truncate and wrongly report a reordered set as unchanged.
    """
    anchors_orig = [s for s in original if not _section_is_all_monospace(s)]
    anchors_sorted = [s for s in y_sorted if not _section_is_all_monospace(s)]
    return (len(anchors_orig) == len(anchors_sorted)
            and all(a is b for a, b in zip(anchors_orig, anchors_sorted)))


def _order_sections_reading(sections: list[Section]) -> list[Section]:
    """Repair MuPDF's block order where a code block is out of reading order.

    MuPDF's block stream is not always in reading order: a monospace
    code block physically at the top/middle of a page can be reported
    last (observed on P4007R0 pages 9 and 12, where it lands next to
    another code block and _detect_code_blocks then merges the two into
    one fenced block at the wrong position).

    The repair is deliberately narrow. Per page, sections are sorted
    top-to-bottom by y, but the sorted order is accepted only when both
    guards pass:

    - The page is single-column (_page_is_multicolumn is False). A
      multi-column page, whether its columns are prose (TOC, revision
      history) or side-by-side code comparisons, is already in column
      reading order; a y-sort would interleave the columns.
    - The reorder moves nothing except all-monospace ("code") sections
      (_reorders_only_monospace). The relative order of non-monospace
      anchors (prose, headings, title/TOC/metadata, footers) stays
      byte-for-byte unchanged, so position-sensitive downstream passes
      (TOC stripping, duplicate collapse) see the order they always did.

    Together these keep the fix to its purpose: relocate a misplaced
    code block on an otherwise single-flow page (P4007R0) and nothing
    else. The sort is stable, so equal-y sections keep MuPDF order.
    """
    by_page: dict[int, list[Section]] = {}
    for sec in sections:
        by_page.setdefault(sec.page_num, []).append(sec)
    ordered: list[Section] = []
    for pg in sorted(by_page):
        page_sections = by_page[pg]
        y_sorted = sorted(page_sections, key=_section_top_y)
        if (not _page_is_multicolumn(page_sections)
                and _reorders_only_monospace(page_sections, y_sorted)):
            ordered.extend(y_sorted)
        else:
            ordered.extend(page_sections)
    return ordered


def _make_paragraph_section(block: Block) -> Section:
    """Construct a high-confidence PARAGRAPH Section from a Block."""
    return Section(
        kind=SectionKind.PARAGRAPH,
        text=block.text,
        confidence=Confidence.HIGH,
        lines=block.lines,
        page_num=block.page_num,
        font_size=block.font_size,
    )


def _block_words(blocks: list[Block]) -> list[str]:
    """Flatten blocks to a list of words for comparison.

    Glyph-placeholder characters (U+FFFD) are stripped before
    tokenising: they are injected identically into both extraction
    paths, so leaving them in cannot change the relative similarity, but
    a placeholder that joins a word in one path and stands alone in the
    other would. Stripping keeps the page word-multiset comparison
    unaffected by the glyph pass.
    """
    words = []
    for block in blocks:
        for line in block.lines:
            text = line.text.replace(UNKNOWN_GLYPH, " ")
            words.extend(text.split())
    return words


def _word_similarity(words_a: list[str], words_b: list[str]) -> float:
    """Compute word-level similarity between two word lists."""
    if not words_a and not words_b:
        return 1.0
    if not words_a or not words_b:
        return 0.0
    set_a = Counter(words_a)
    set_b = Counter(words_b)
    intersection = sum((set_a & set_b).values())
    total = max(sum(set_a.values()), sum(set_b.values()))
    return intersection / total if total > 0 else 0.0


def compare_extractions(mupdf_blocks: list[Block],
                        spatial_blocks: list[Block],
                        ) -> list[Section]:
    """Compare two extraction paths using per-page word-level multiset similarity.

    Groups blocks by page and computes a word-count overlap ratio for each
    page. High similarity = confident (PARAGRAPH). Low similarity = uncertain.
    Small uncertain regions below MIN_UNCERTAIN_WORDS are promoted to confident.
    """
    mupdf_by_page: dict[int, list[Block]] = {}
    spatial_by_page: dict[int, list[Block]] = {}
    for b in mupdf_blocks:
        mupdf_by_page.setdefault(b.page_num, []).append(b)
    for b in spatial_blocks:
        spatial_by_page.setdefault(b.page_num, []).append(b)

    all_pages = sorted(set(mupdf_by_page) | set(spatial_by_page))
    sections: list[Section] = []

    for pg in all_pages:
        m_blocks = mupdf_by_page.get(pg, [])
        s_blocks = spatial_by_page.get(pg, [])

        m_words = _block_words(m_blocks)
        s_words = _block_words(s_blocks)
        sim = _word_similarity(m_words, s_words)

        if sim < SIMILARITY_THRESHOLD:
            m_joined = unicodedata.normalize('NFC', " ".join(m_words))
            s_joined = unicodedata.normalize('NFC', " ".join(s_words))
            if m_joined == s_joined:
                sim = 1.0

        # When spatial has zero words (e.g. all blocks removed by table
        # exclusion) but mupdf has content, trust mupdf directly.  The
        # absence of spatial data is a pipeline artifact, not a real
        # extraction disagreement.
        if not s_words and m_words:
            sim = 1.0

        if sim >= SIMILARITY_THRESHOLD:
            for block in m_blocks:
                sections.append(_make_paragraph_section(block))
        else:
            _log.debug("Page %d: similarity %.2f < threshold, marking uncertain",
                        pg, sim)
            m_text = "\n\n".join(b.text for b in m_blocks)
            s_text = "\n\n".join(b.text for b in s_blocks)
            sections.append(Section(
                kind=SectionKind.UNCERTAIN,
                text=m_text,
                confidence=Confidence.UNCERTAIN,
                mupdf_text=m_text,
                spatial_text=s_text,
                page_num=pg,
                lines=[ln for b in m_blocks for ln in b.lines],
            ))

    all_pages_set = set(all_pages)
    uncertain_pages = [pg for pg in all_pages
                       if any(s.kind == SectionKind.UNCERTAIN and s.page_num == pg
                              for s in sections)]
    promoted: set[int] = set()
    for pg in uncertain_pages:
        if pg in promoted:
            continue
        next_pg = pg + 1
        if next_pg not in all_pages_set:
            continue
        m_words_2 = _block_words(mupdf_by_page.get(pg, []) +
                                 mupdf_by_page.get(next_pg, []))
        s_words_2 = _block_words(spatial_by_page.get(pg, []) +
                                 spatial_by_page.get(next_pg, []))
        if _word_similarity(m_words_2, s_words_2) >= SIMILARITY_THRESHOLD:
            promoted.add(pg)
            promoted.add(next_pg)

    if promoted:
        # `promoted` holds both the uncertain pages and the confident neighbours
        # they paired with. Only pages that carry an UNCERTAIN section have it
        # removed by the filter below and need their blocks re-emitted as
        # paragraphs; a confident neighbour still holds the PARAGRAPH sections
        # built for it on the first pass, so re-emitting it here would place
        # every block on that page twice.
        promoted_uncertain = {s.page_num for s in sections
                              if s.kind == SectionKind.UNCERTAIN
                              and s.page_num in promoted}
        kept = [s for s in sections
                if not (s.kind == SectionKind.UNCERTAIN
                        and s.page_num in promoted)]
        for pg in sorted(promoted_uncertain):
            for block in mupdf_by_page.get(pg, []):
                kept.append(_make_paragraph_section(block))
        sections = kept

    still_uncertain = [pg for pg in all_pages
                       if any(s.kind == SectionKind.UNCERTAIN and s.page_num == pg
                              for s in sections)]
    if still_uncertain:
        m_words_all: list[str] = []
        s_words_all: list[str] = []
        for pg in still_uncertain:
            m_words_all.extend(_block_words(mupdf_by_page.get(pg, [])))
            s_words_all.extend(_block_words(spatial_by_page.get(pg, [])))
        m_all_nfc = unicodedata.normalize('NFC', " ".join(m_words_all))
        s_all_nfc = unicodedata.normalize('NFC', " ".join(s_words_all))
        doc_match = (m_all_nfc == s_all_nfc
                     or _word_similarity(m_words_all, s_words_all)
                     >= SIMILARITY_THRESHOLD)
        if doc_match:
            bulk_promoted = set(still_uncertain)
            # Defence-in-depth only: `still_uncertain` pages all carry an
            # UNCERTAIN section by construction, so `promoted_uncertain` here
            # always equals `bulk_promoted` and this guard is a no-op. It mirrors
            # the pairwise block above so the two re-insertion paths cannot drift.
            promoted_uncertain = {s.page_num for s in sections
                                  if s.kind == SectionKind.UNCERTAIN
                                  and s.page_num in bulk_promoted}
            kept = [s for s in sections
                    if not (s.kind == SectionKind.UNCERTAIN
                            and s.page_num in bulk_promoted)]
            for pg in sorted(promoted_uncertain):
                for block in mupdf_by_page.get(pg, []):
                    kept.append(_make_paragraph_section(block))
            sections = kept

    sections = _order_sections_reading(sections)

    for sec in sections:
        if sec.kind != SectionKind.UNCERTAIN:
            continue
        m_len = len(sec.mupdf_text.split()) if sec.mupdf_text else 0
        s_len = len(sec.spatial_text.split()) if sec.spatial_text else 0
        if min(m_len, s_len) < MIN_UNCERTAIN_WORDS:
            sec.kind = SectionKind.PARAGRAPH
            sec.confidence = Confidence.LOW
            sec.mupdf_text = ""
            sec.spatial_text = ""

    return sections


# A heading counts as "empty" when every section between it and the next
# heading is shorter than this: a leaked TOC entry's only "body" is a stray
# split page number or short fragment, never real prose. Validated against the
# 2026 corpus. Coupling caveat: this threshold and `MIN_TOC_RUN` (toc.py) are
# corpus-tuned. A future paper with a 2-entry leaked TOC, or a leaked entry
# whose stray fragment exceeds 40 chars, under-removes silently (a cosmetic
# duplicate heading remains). Body text is safe: only sections whose text
# exactly recurs as a later heading, within a run anchored by at least one
# empty heading, are removed.
_TOC_ENTRY_MAX_BODY_CHARS = 40

# Kinds that are never trivial regardless of text length. IMAGE sections are
# built with text="" (the canonical alt text lives in image_ref, not sec.text),
# so _section_is_trivial would always return True for them, silently sweeping
# real figures. TABLE and CODE sections may also be short in text but represent
# real structured content. Matches the kind guard already present in the sibling
# find_toc_indices path in pipeline.py.
_TOC_SWEEP_SKIP_KINDS = frozenset({
    SectionKind.IMAGE, SectionKind.TABLE, SectionKind.CODE,
})


def _section_is_trivial(sec: Section) -> bool:
    """True if a non-heading section is too small to count as body.

    A leaked TOC entry's "body" is at most a split page number or short
    fragment; real prose, code, tables, and lists exceed the threshold and
    make the heading above them non-empty (hence not removable).
    """
    return len(sec.text.strip()) < _TOC_ENTRY_MAX_BODY_CHARS


# A physical line that is *only* a section number ("8", "3.1", "15."). When a
# heading or leaked TOC entry renders the number on its own line and wraps the
# title to the next, the title (not the bare number) must drive recurrence
# matching; see `_entry_title`. Digit-only: "1", "2.3", "3.1.2". Roman
# numerals and single capital letters are handled by the module-level
# _BARE_SECTION_NUM_RE below; that broader pattern must not be used here
# because it also matches short prose tokens ("A", "I") and would over-fold.
_BARE_DIGIT_NUM_RE = re.compile(r"^\d+(?:\.\d+)*\.?$")


# Max text lines a PARAGRAPH/LIST section may have to still count as a leaked
# TOC entry. A leaked entry the heading classifier left as body text (a title
# line such as "3. The Rationale for Unification") is at most a title that
# wrapped once; three or more lines is real prose and is never an entry,
# whatever its first line matches. This is the load-bearing protection against
# absorbing real single-line-ish content through the emptiness bridging below.
# Line count is derived from sec.text (the canonical text field) not sec.lines
# (raw PDF Line objects, which may be empty for HTML or synthetic sections).
# Coupling caveat: corpus-tuned alongside `_TOC_ENTRY_MAX_BODY_CHARS` and
# `MIN_TOC_RUN` (toc.py); a paper needing a different bound changes the
# constant, not the call sites.
_TOC_ENTRY_MAX_LINES = 2


def _entry_title(sec: Section) -> str:
    """The single-line title used as a section's TOC recurrence key.

    Usually a section's title is its first physical line. But a heading and its
    leaked TOC counterpart frequently render the section number on its own
    physical line with the title wrapped to the next (`"1\\nComparison table"`).
    First-line-only normalization would reduce that to the bare number `"1"`,
    which then matches *any* other number-on-its-own-line section: a wording
    paragraph `"8\\nEffects: Equivalent to: ..."` would falsely match an
    `"8\\nAcknowledgements"` heading (both reduce to `"8"`) and the real wording
    be deleted as a phantom entry (observed on p2988r9). When the first physical
    line is only a section number, fold in the next line so the real title
    drives the match: `"1\\nComparison table"` -> `"1 Comparison table"`
    (-> `"comparison table"`), while `"8\\nEffects: ..."` keeps its prose and
    matches no heading title.
    """
    lines = [ln.strip() for ln in sec.text.split("\n") if ln.strip()]
    if not lines:
        return ""
    if len(lines) > 1 and _BARE_DIGIT_NUM_RE.match(lines[0]):
        return lines[0] + " " + lines[1]
    return lines[0]


def _is_paragraphish(sec: Section) -> bool:
    """True for the body-text kinds a leaked TOC entry can hide in.

    A Table of Contents line the heading classifier did not promote stays a
    PARAGRAPH, or a LIST when it carries a list-marker shape ("3. The
    Rationale ..." matches NUMBERED_LIST_RE). Both must be candidate
    non-heading entries; a PARAGRAPH-only check misses the LIST-kind entries
    that dominate papers like P4094R0.
    """
    return sec.kind in (SectionKind.PARAGRAPH, SectionKind.LIST)


# Recurrence-density floor for a removable run: at least this fraction of a
# run's counted members (entries + in-span stragglers) must recur as later
# headings (i.e. be entries). A genuine leaked TOC is overwhelmingly recurring
# entries with a few non-recurring stragglers wedged in; a body region that
# coincidentally forms a heading-anchored run is mostly non-recurring and is
# rejected here. Corpus-tuned alongside `MIN_TOC_RUN`/`_TOC_ENTRY_MAX_LINES`;
# it gates a per-run property, so it generalizes, but density alone is not
# sufficient (repeated spec boilerplate is dense too) - the front-region bound
# is what makes it safe. See the pt5 plan.
_TOC_RUN_MIN_RECUR_FRACTION = 0.75

# Minimum normalized-title length (chars) for the paragraph-straggler
# forward-reference gate to consider a containment match. Below this a title is
# too short for "appears as a later heading" to mean anything (a two-letter
# fragment is a substring of half the document). Corpus-tuned.
_TOC_STRAGGLER_MIN_TITLE_LEN = 6


def _has_alpha_title(sec: Section) -> bool:
    """True if the section's normalized recurrence title has alphabetic content.

    A TOC entry's title is real words. A section that reduces to a bare number
    or a stray extraction glyph ("8", "?", "page") has no place in a leaked-TOC
    run and must never be a straggler or an entry.
    """
    norm = normalize_toc_entry(_entry_title(sec))
    return bool(norm) and any(c.isalpha() for c in norm)


def _is_title_like_straggler(sec: Section) -> bool:
    """True if a non-heading section is shaped like a leaked-TOC title line.

    PARAGRAPH/LIST, at most `_TOC_ENTRY_MAX_LINES` text lines (derived from
    `sec.text`; a title that wrapped at most once; three or more lines is real
    prose), with alphabetic title content. This is the *shape* test only - it
    says nothing about recurrence. A recurring title-like line is a non-heading
    entry; a non-recurring one is a bridge straggler. Both share this shape.
    """
    return (_is_paragraphish(sec)
            and len(sec.text.split("\n")) <= _TOC_ENTRY_MAX_LINES
            and _has_alpha_title(sec))


def _is_empty_heading(sections: list[Section], i: int) -> bool:
    """True if the heading at `i` has no real body before the next heading.

    Empty means every section between this heading and the next heading is
    either trivial (a split page number) or a title-like non-heading (a leaked
    TOC line the classifier left as PARAGRAPH/LIST). This broadens the earlier
    definition, which bridged only trivial or *recurring* non-heading entries:
    a heading over a single non-recurring title-like line (P4016R0's
    `## 1.2 Motivating example` above a leaked appendix title) still counts
    empty, so it can be a straggler.
    Recurrence is decided by the caller; emptiness is shape-only.
    """
    sec = sections[i]
    if sec.kind != SectionKind.HEADING:
        return False
    for j in range(i + 1, len(sections)):
        if sections[j].kind == SectionKind.HEADING:
            break
        if sections[j].kind in _TOC_SWEEP_SKIP_KINDS:
            return False
        if not (_section_is_trivial(sections[j])
                or _is_title_like_straggler(sections[j])):
            return False
    return True


def _straggler_forward_references(
        title_norm: str, i: int,
        heading_titles: list[tuple[int, str]]) -> bool:
    """True if a paragraph straggler's title appears as a *later* heading.

    The defining property of a real TOC entry is that it is a forward reference:
    its title text appears downstream as a section heading. A unique body
    sentence is not. Match is bidirectional containment (one normalized title is
    a substring of the other) because the leaked TOC line often carries a
    trailing qualifier the real heading lacks (`Appendix D: ... Structure
    (Informative)` -> heading `Appendix D: ... Structure`). The target must be a
    later HEADING, not arbitrary later text: matching against paragraphs would
    re-admit repeated body wording (p2846r6's `Effects:` boilerplate).

    This gate is necessarily *loose* on its own (containment with a length
    floor); its safety is the conjunction with the other gates (in-span,
    front-region, anchor, density), never this check alone. Applied only to
    paragraph/list stragglers; empty-heading stragglers are exempt because
    heading text drifts between TOC and body (renumbering, smart quotes, a body
    heading absorbed into prose), and a hard gate there would wrongly keep
    legitimate leaked headings (P4007R0's `8.1`-`8.4`). Fails safe: a paragraph
    straggler whose target heading was never captured is simply kept.
    """
    if (len(title_norm) < _TOC_STRAGGLER_MIN_TITLE_LEN
            or not any(c.isalpha() for c in title_norm)):
        return False
    for j, htitle in heading_titles:
        if j <= i or len(htitle) < _TOC_STRAGGLER_MIN_TITLE_LEN:
            continue
        if title_norm in htitle or htitle in title_norm:
            return True
    return False


def _run_recurrence_density(num_entries: int, num_in_span_stragglers: int) -> float:
    """Fraction of a run's counted members that are recurring entries."""
    total = num_entries + num_in_span_stragglers
    if total == 0:
        return 0.0
    return num_entries / total


def _compute_body_start(sections: list[Section], recurs: list[bool]) -> int:
    """Index of the first real body section; straggler bridging stops here.

    The first non-recurring, non-trivial, `>= 2`-line PARAGRAPH marks where the
    front matter ends and the body begins. Relaxed straggler bridging fires only
    before this index, because the recurrence signal is unreliable in the body
    (spec boilerplate recurs verbatim across methods and can form a dense
    empty-heading-anchored run), while leaked TOCs are always front matter.
    Returns `len(sections)` if no such paragraph exists (whole document is front
    region; the other gates still constrain removal).

    Fails safe both ways: a *late* mis-detection cannot delete prose (the
    forward-reference gate keeps a unique paragraph regardless of `body_start`),
    only an empty heading; an *early* mis-detection (e.g. a 2-line non-recurring
    appendix entry mid-block) merely truncates the front region and under-removes
    (cosmetic).
    """
    for i, sec in enumerate(sections):
        if (sec.kind == SectionKind.PARAGRAPH
                and not _section_is_trivial(sec)
                and not recurs[i]
                and len(sec.lines) >= 2):  # sec.lines counts physical PDF lines, not \n splits; reliable here because _compute_body_start is PDF-only
            return i
    return len(sections)


def drop_leaked_toc_entries(sections: list[Section]) -> list[Section]:
    """Remove a leaked Table of Contents left behind as mixed heading/body kinds.

    Companion to `toc.find_toc_indices` (the dot-leader structural detector,
    shared `MIN_TOC_RUN`). #122 stopped `find_toc_indices` from matching a
    heading-kind section unless it carries a dot-leader page-number shape, so a
    Table of Contents whose entries lack that shape leaks past it. Such a leaked
    TOC is in fact a *mix* of kinds: some entries become empty duplicate
    HEADINGs, others stay short title-like PARAGRAPH or LIST sections ("3. The
    Rationale for Unification"). This pass removes the whole block.

    Entries are unified by **recurrence as a later heading** (empty recurring
    headings + title-like recurring paragraph/list). A real leaked TOC is often
    *fragmented* by non-recurring **stragglers** the body classifier handled
    differently from the recurring entries: title-like paragraph/list lines whose
    body heading text drifted, and once-only empty headings. This pass bridges
    stragglers as in-span run members so the block coalesces and removes whole
    (P4016R0's ~146-entry appendix dump, P4007R0's `8.1`-`8.4` objections).

    Body-safety is a **conjunction of gates, not any single one** (a future
    maintainer must not loosen one assuming another carries the weight):

    - **Heading anchor:** a removable run needs >= 1 empty-heading entry, so
      paragraph/list members are deleted only inside a confirmed heading-kind TOC
      block.
    - **Front-region bound:** straggler bridging fires only before `body_start`
      (the first real body paragraph). Spec boilerplate recurs verbatim across
      methods and can form a dense empty-heading-anchored run in the body; the
      bound keeps the relaxation out of the body (where strict, trivial-only
      bridging still applies). This is what stops p2846r6's `Effects:` wording
      loss.
    - **Recurrence-density floor:** a run is removed only if a strong majority of
      its counted members recur as later headings.
    - **In-span / trailing rule:** only stragglers strictly between the run's
      first and last *entry* are removed; trailing stragglers (past the last
      entry) are kept, even though the scan bridged them. This is what keeps a
      real section, and real single-line abstract prose, that immediately follows
      a front-matter TOC (P4016R0's idx150/151).
    - **Forward-reference gate** (paragraph/list stragglers only): such a
      straggler is removed only if its title appears as a later heading, so a
      unique body sentence is never deleted. Empty-heading stragglers are exempt
      (heading text drifts; gating them regresses P4007R0); their residual risk is
      heading-level loss, covered by the anchor/density/front/in-span guards.

    "Empty" is interpreted loosely: non-trivial sections that are themselves
    heading titles recurring later (adjacent TOC entries that `find_toc_indices`
    did not strip, e.g. long chapter titles formatted as a list) are treated as
    transparent and do not block the preceding heading's eligibility.

    Pure and deterministic (D7): built by ordered iteration; the removal set
    gates membership only and never feeds prompt-bound output.
    """
    n = len(sections)

    # 1. normalized heading title (fold-aware, see `_entry_title`) -> ordered
    #    list of HEADING indices; plus the ordered (index, title) list the
    #    forward-reference gate scans.
    title_indices: dict[str, list[int]] = {}
    heading_titles: list[tuple[int, str]] = []
    for i, sec in enumerate(sections):
        if sec.kind == SectionKind.HEADING:
            norm = normalize_toc_entry(_entry_title(sec))
            title_indices.setdefault(norm, []).append(i)
            heading_titles.append((i, norm))

    def _recurs_later(sec: Section, i: int) -> bool:
        norm = normalize_toc_entry(_entry_title(sec))
        # A TOC entry's title is real words. Require at least one letter in the
        # normalized form, so a section that reduces to a bare number or a stray
        # extraction glyph ("8", "■", "?") cannot recurrence-match. Combined
        # with `_entry_title`'s number-line folding, this blocks the phantom
        # match between a wording paragraph and an unrelated numbered heading
        # while still matching real titled entries.
        if not norm or not any(c.isalpha() for c in norm):
            return False
        return any(k > i for k in title_indices.get(norm, []))

    recurs = [_recurs_later(sections[i], i) for i in range(n)]

    # 2. entry-ness. A non-heading entry is a title-like paragraph/list that
    #    recurs as a later heading. A heading entry is an empty heading (shape
    #    only, broadened to bridge title-like non-headings) that recurs.
    nonheading_entry = [
        _is_title_like_straggler(sections[i]) and recurs[i] for i in range(n)]
    heading_entry = [
        _is_empty_heading(sections, i) and recurs[i] for i in range(n)]
    entry = [heading_entry[i] or nonheading_entry[i] for i in range(n)]

    # 3. front-region bound: relaxed straggler bridging fires only before the
    #    first real body paragraph.
    body_start = _compute_body_start(sections, recurs)

    def _is_straggler(i: int) -> bool:
        # A non-entry section bridged in-span: a title-like (non-recurring)
        # paragraph/list, or a once-only empty heading. Entries are excluded
        # (a recurring title-like line is a non-heading entry; a recurring empty
        # heading is a heading entry).
        if entry[i]:
            return False
        if _is_title_like_straggler(sections[i]):
            return True
        return _is_empty_heading(sections, i) and _has_alpha_title(sections[i])

    # 4. group entries into runs, bridging trivial fragments (anywhere) and
    #    stragglers (front-region only), then flush.
    to_remove: set[int] = set()

    def _flush(entries: list[int], strags: list[int]) -> None:
        # Known limitation (recall): a leaked TOC entry whose body counterpart
        # is not a recurrence-matching heading carries no signal _recurs_later
        # can use. Such entries return False from _recurs_later, are never
        # placed in `entry`, and therefore never reach this function. They
        # survive in the output. P4007R0's once-only objection-title headings
        # (e.g. "8.1 C++ needs a standard task...") are the confirmed case
        # for the recurring-entry class; the straggler bridging in this pass
        # now catches them via the front-region + forward-reference gates.
        # Catching entries with no recurrence signal at all would require a
        # non-recurrence discriminator (position, distance from TOC label),
        # which was deliberately deferred as too risky for body-safety.
        # MIN_TOC_RUN is counted on ENTRIES, not stragglers.
        if len(entries) < MIN_TOC_RUN:
            return
        # Heading anchor.
        if not any(heading_entry[i] for i in entries):
            return
        lo, hi = entries[0], entries[-1]
        # In-span / trailing rule: only stragglers strictly between the first and
        # last entry are candidates; trailing stragglers (the scan bridged them
        # past `hi`) are kept. This protects a real section, and real single-line
        # abstract prose, that follows a front-matter TOC (P4016R0 idx150/151).
        in_span = [i for i in strags if lo < i < hi]
        # Recurrence-density floor: density alone is insufficient (boilerplate is
        # dense), but combined with the front bound it rejects a coincidental
        # in-front anchor over mostly-non-recurring lines.
        if _run_recurrence_density(len(entries), len(in_span)) < _TOC_RUN_MIN_RECUR_FRACTION:
            return
        # Strictly-deepening rejection: a run whose heading subsequence forms a
        # 15/15.1/15.1.1 ascending sequence is a real clause-container stack,
        # not a leaked TOC. Applies to all-heading and mixed runs alike; require
        # at least two headings so the check is non-vacuous.
        heading_entries = [i for i in entries if sections[i].kind == SectionKind.HEADING]
        if len(heading_entries) >= 2:
            levels = [sections[i].heading_level for i in heading_entries]
            if all(b > a for a, b in zip(levels, levels[1:])):
                return
        for i in entries:
            to_remove.add(i)
        in_span_set = set(in_span)
        for i in in_span:
            if _is_title_like_straggler(sections[i]):
                # Paragraph/list straggler: forward-reference gate. The check is
                # applied here as a removal *filter*, not in the run scan, so a
                # failing straggler is bridged-but-kept (the run continued, the
                # tail is still removed, at most one stray line survives).
                title_norm = normalize_toc_entry(_entry_title(sections[i]))
                if _straggler_forward_references(title_norm, i, heading_titles):
                    to_remove.add(i)
            else:
                # Empty-heading straggler: exempt from the forward-reference gate
                # (heading text drifts; gating it regresses P4007R0).
                to_remove.add(i)
        # Trivial fragments (split page numbers) up to the next real (non-entry)
        # heading after the last entry. The trailing-exclusion rule applies to
        # *stragglers* (the prose-risk class), not to trivial page-number debris,
        # which pt4 swept up to the next real section and which is never real
        # content (< `_TOC_ENTRY_MAX_BODY_CHARS`). Stragglers are skipped here so
        # a bridged-but-kept paragraph straggler survives; real prose is
        # non-trivial and never matches.
        end = next((k for k in range(hi + 1, n)
                    if sections[k].kind == SectionKind.HEADING and not entry[k]),
                   n)
        for j in range(lo + 1, end):
            if (j not in to_remove
                    and j not in in_span_set
                    and sections[j].kind != SectionKind.HEADING
                    and sections[j].kind not in _TOC_SWEEP_SKIP_KINDS
                    and _section_is_trivial(sections[j])):
                to_remove.add(j)
        # A "Table of Contents" / "Contents" label immediately preceding the run,
        # whether it is paragraph-kind or heading-kind (P4003R1's leaked
        # `### Table of Contents`). Walk back over trivial filler to reach it.
        p = lo - 1
        while p >= 0:
            if is_toc_label(sections[p].text):
                to_remove.add(p)
                p -= 1
                continue
            if (sections[p].kind != SectionKind.HEADING
                    and _section_is_trivial(sections[p])):
                p -= 1
                continue
            break

    entries: list[int] = []
    strags: list[int] = []
    for i in range(n):
        if entry[i]:
            entries.append(i)
        elif (entries and sections[i].kind != SectionKind.HEADING
                and sections[i].kind not in _TOC_SWEEP_SKIP_KINDS
                and _section_is_trivial(sections[i])):
            # Non-heading trivial filler (a split page number) bridges
            # consecutive entries; it neither opens nor closes a run.
            continue
        elif entries and i < body_start and _is_straggler(i):
            # Front-region straggler bridges the run (removal decided in _flush).
            strags.append(i)
        else:
            _flush(entries, strags)
            entries, strags = [], []
    _flush(entries, strags)

    if not to_remove:
        return sections
    return [s for i, s in enumerate(sections) if i not in to_remove]


_BODY_PROSE_MIN_CHARS = 500
_BODY_PROSE_MIN_FRACTION = 0.10


def _detect_body_size(sections: list[Section]) -> float:
    """Find the most common font size that represents body text.

    Prefers prose (non-monospace) spans so that code-heavy papers don't
    bias the body size toward the smaller code font. Falls back to the
    overall most common size when prose is insufficient (e.g. wording
    papers that are nearly entirely monospace specification text), since
    in those papers the spec font *is* the body font.
    """
    prose_sizes: Counter[float] = Counter()
    all_sizes: Counter[float] = Counter()
    for sec in sections:
        for line in sec.lines:
            for span in line.spans:
                if not span.text.strip():
                    continue
                all_sizes[span.font_size] += len(span.text)
                if not span.monospace:
                    prose_sizes[span.font_size] += len(span.text)

    prose_total = sum(prose_sizes.values())
    all_total = sum(all_sizes.values())
    prose_sufficient = (
        prose_total >= _BODY_PROSE_MIN_CHARS
        and (all_total == 0 or prose_total >= _BODY_PROSE_MIN_FRACTION * all_total)
    )
    source = prose_sizes if prose_sufficient else all_sizes
    if not source:
        return FALLBACK_BODY_SIZE
    return source.most_common(1)[0][0]


def _rank_font_sizes(sections: list[Section],
                     body_size: float,
                     skip: Section | None = None) -> dict[float, int]:
    """Rank font sizes larger than body. Returns {size: heading_level}.

    ``skip`` excludes one section's line contributions (the document
    title): its font must not define a heading tier, otherwise it takes
    rank 1 and every real body heading ranks one level too deep. Only the
    title's *lines* are dropped, not the size globally, so a real heading
    that happens to share the title's font still contributes that size and
    keeps its tier.
    """
    sizes = set()
    for sec in sections:
        if sec is skip:
            continue
        for line in sec.lines:
            fs = line.font_size
            if fs > body_size * _HEADING_SIZE_RATIO:
                sizes.add(fs)
    ranked = sorted(sizes, reverse=True)
    return {sz: i + 1 for i, sz in enumerate(ranked)}


def _normalize_title_for_match(text: str) -> str:
    """Lowercase, strip the paper-ID prefix, and collapse whitespace."""
    text = _TITLE_PID_PREFIX_RE.sub("", text)
    return " ".join(text.split()).lower()


def _title_section_for_ranking(sections: list[Section],
                               body_size: float,
                               metadata_title: str | None = None,
                               ) -> Section | None:
    """The document-title block, to exclude from font-size ranking.

    The title renders as H1 (front matter) and is not a body heading. If
    its font stays in ``_rank_font_sizes`` it takes rank 1 and pushes every
    body-heading tier one level too deep. Identify it the way the
    classifier does: the first large-font, non-metadata block that precedes
    any numbered section. Returns None when the document opens on numbered
    content (no distinct title block to exclude).

    When ``metadata_title`` is known (the title was already extracted
    upstream from the WG21 block scan or PDF info) the leading large-font
    block is cross-checked against it. If they do not match, that block is a
    body heading, not the title: excluding it would push every real body
    heading one tier too deep (inverted hierarchy), so None is returned and
    the block keeps its font tier.
    """
    large_thresh = body_size * _TITLE_SIZE_RATIO
    meta_norm = _normalize_title_for_match(metadata_title) if metadata_title else ""
    for sec in sections:
        first_line = sec.text.split("\n")[0].strip()
        if not first_line:
            continue
        if SECTION_NUM_RE.match(first_line):
            return None
        if sec.font_size <= large_thresh:
            continue
        if (_is_known_section(first_line)
                or "@" in first_line
                or DATE_RE.match(first_line)
                or len(first_line) > _TITLE_MAX_LENGTH):
            continue
        if meta_norm:
            cand_norm = _normalize_title_for_match(sec.text)
            if not (cand_norm == meta_norm
                    or meta_norm.startswith(cand_norm)
                    or cand_norm.startswith(meta_norm)):
                return None
        return sec
    return None


_ROMAN_RE = re.compile(r"^[IVXLCDM]+$")


def _heading_level_from_number(section_num: str) -> int:
    """Compute heading level from dotted decimal or Roman numeral: depth + 1.

    Roman numerals (I, II, IV, ...) are flat top-level sections = level 2.
    Arabic dotted numbers use dot-count + 2 (1 = 2, 1.1 = 3, 1.1.1 = 4).
    """
    if _ROMAN_RE.match(section_num):
        return 2
    parts = section_num.split(".")
    return len(parts) + 1


def _heading_is_numbered(sec: Section) -> bool:
    """True when the section's first line opens with a section number.

    A numbered heading's level comes from its numbering depth, which is
    authoritative; font-size signals must not override it.
    """
    return bool(SECTION_NUM_RE.match(sec.text.split("\n")[0].strip()))


# Sentence-terminating punctuation. "?" is absent on purpose: question-form
# headings are common in WG21 papers ("Why not represent a proposed API as a
# C++20 range?"), so a trailing "?" is not prose evidence.
_PROSE_TERMINATORS = (".", "!", "…")

# An interior sentence boundary: a terminator, an optional closing quote or
# bracket, whitespace, then the opening of a new sentence. Two sentences on
# one line means prose ("... and other factors. Learn more on the").
_INTERIOR_SENTENCE_RE = re.compile(r"""[.!?…]["')\]]?\s+["“(A-Z]""")


def _reads_as_prose(text: str) -> bool:
    """True when *text* reads as a sentence rather than a heading label."""
    stripped = text.strip()
    if not stripped:
        return False
    if stripped.endswith(_PROSE_TERMINATORS):
        return True
    return bool(_INTERIOR_SENTENCE_RE.search(stripped))


def _weak_heading_qualifies(first_line: str, section_num: str,
                            font_level: int | None, is_bold: bool,
                            is_known: bool) -> bool:
    """Whether a LOW-confidence heading candidate still reads as a heading.

    At LOW confidence exactly one weak signal fired, so the text has to carry
    the heading claim by itself. Two tells reject it (#302):

    - **Paragraph numbering.** A dotless section number with no typographic
      support is standardese paragraph numbering ("3 A preprocessing directive
      of the form") or a sentence opening on a numeral ("I think this general
      approach ..."), not a section number. Dotted numbers ("3.1 Platform
      schema") are unambiguous and keep their number-only promotion.
    - **Sentence punctuation.** See ``_reads_as_prose``. Applied only when the
      line is NOT bold. Bold is an author-applied signal, so a bold sentence is
      a deliberate sub-heading even when it ends in a full stop (P4094R0 sets
      its objection Q&A entries that way: "Q: This is hindsight bias."). The
      tells this gate exists for have no author intent behind them: an
      incidental font-size rank, or an ambiguous leading number.

    Sentence *length* is deliberately not a third tell: the pre-existing
    ``_HEADING_MAX_WORDS`` cap at the call site already rejects long lines at
    LOW confidence, and tightening it further would reject a real question-form
    heading ("Why not represent a proposed API as a C++20 range?", 10 words).

    A line that is *only* a section number ("I.", "8", "3.1") is exempt: it
    carries no text to judge, and `_merge_orphan_heading_numbers` downstream
    is what pairs it with the title block the PDF put in a different font.

    The number is stripped with ``SECTION_NUM_PREFIX_RE``, not
    ``SECTION_NUM_RE``: the prefix form also consumes a *trailing dot*
    ("2. History/Changes from Previous Release"), whose dot-space-capital shape
    would otherwise read as an interior sentence boundary.
    """
    if _BARE_SECTION_NUM_RE.match(first_line):
        return True
    tail = SECTION_NUM_PREFIX_RE.sub("", first_line.strip(), count=1).strip()
    if not tail:
        return False
    if (section_num and "." not in section_num
            and font_level is None and not is_bold and not is_known):
        return False
    if is_bold:
        return True
    return not _reads_as_prose(tail)


def _is_known_section(first_line: str) -> bool:
    """Check if *first_line* names a KNOWN_SECTIONS entry.

    Handles plain names ("Abstract"), numbered prefixes without trailing
    dot ("3.2 Motivation"), and numbered prefixes with trailing dot
    ("1. Introduction", "1.1. Alternatives") by stripping the section
    number before the lookup.
    """
    normalized = first_line.lower().rstrip(":")
    if normalized in KNOWN_SECTIONS:
        return True
    m = SECTION_NUM_RE.match(first_line)
    if m:
        rest = m.group(2).strip().lower().rstrip(":")
        return rest in KNOWN_SECTIONS
    m2 = SECTION_NUM_PREFIX_RE.match(first_line)
    if m2:
        rest = first_line[m2.end():].strip().lower().rstrip(":")
        return rest in KNOWN_SECTIONS
    return False


def heading_confidence(has_number: bool, number_level: int,
                        font_level: int | None, is_bold: bool,
                        is_known: bool) -> tuple[int, Confidence]:
    """Determine heading level and confidence from multiple signals.

    Bold alone (no section number, no enlarged font, not a known name)
    yields level 0 with LOW confidence.  The caller must assign a
    context-derived level (typically previous_heading_level + 1) before
    accepting the heading.  This keeps the function stateless while
    allowing bold-only sub-headings (common in WG21 papers) to enter
    the heading path.
    """
    if has_number:
        level = number_level
        if font_level is not None and font_level == level:
            if is_bold:
                return level, Confidence.HIGH
            return level, Confidence.MEDIUM
        if font_level is not None:
            return level, Confidence.MEDIUM
        if is_bold:
            return level, Confidence.MEDIUM
        return level, Confidence.LOW

    if font_level is not None:
        if is_known and is_bold:
            return 2, Confidence.HIGH
        if is_known:
            return 2, Confidence.MEDIUM
        if is_bold:
            return font_level + 1, Confidence.MEDIUM
        return font_level + 1, Confidence.LOW

    if is_known:
        return 2, Confidence.LOW

    if is_bold:
        return 0, Confidence.LOW

    return 0, Confidence.UNCERTAIN


# Deferred import: metadata_yaml.extract imports from pdf.types which imports
# from pdf.__init__ which imports from structure.py. Moving this to the
# top-level import block creates a circular import.
from ..metadata_yaml.extract import extract_metadata as _extract_metadata  # noqa: E402



def _split_heading_body(sec: Section,
                        body_size: float,
                        ) -> tuple[Section, Section | None]:
    """Split a multi-line section when the first line is a heading and
    the remaining lines are body text at a smaller font size.

    MuPDF sometimes merges a heading and its following paragraph into a
    single Block because they share a bounding region.  This function
    detects the pattern and returns (heading_section, body_section).
    When no split is needed, returns (sec, None).

    Split triggers when *either*:
    - first line font_size exceeds the second by >= _HEADING_BODY_SPLIT_DELTA, or
    - first line is bold and the second is not, AND the first line is
      either above body_size * _HEADING_SIZE_RATIO or short enough to
      be a heading (<= _HEADING_MAX_WORDS words).
    """
    if len(sec.lines) < 2:
        return sec, None

    line0 = sec.lines[0]
    line1 = sec.lines[1]
    fs0 = line0.font_size
    fs1 = line1.font_size

    size_drop = fs0 - fs1 >= _HEADING_BODY_SPLIT_DELTA
    bold_drop = (
        line0.is_bold
        and not line1.is_bold
        and (fs0 >= body_size * _HEADING_SIZE_RATIO
             or len(line0.text.split()) <= _HEADING_MAX_WORDS)
    )

    if not size_drop and not bold_drop:
        return sec, None

    body_lines = sec.lines[1:]
    body_text = "\n".join(ln.text for ln in body_lines).strip()
    if not body_text:
        head = replace(sec, lines=[line0], text=line0.text,
                        font_size=fs0)
        return head, None

    head = replace(sec, lines=[line0], text=line0.text,
                    font_size=fs0)
    body = replace(sec,
                   kind=SectionKind.PARAGRAPH,
                   text=body_text,
                   confidence=Confidence.HIGH,
                   lines=body_lines,
                   font_size=fs1)
    _log.debug("Split heading+body: heading=%r body=%r (fs %.0f->%.0f)",
               line0.text.strip()[:40], body_text[:40], fs0, fs1)
    return head, body


def structure_sections(sections: list[Section],
                       has_title: bool = False,
                       ) -> tuple[dict, list[Section], int]:
    """Apply heading intelligence, paragraph grouping, and list detection.

    If has_title is True, the title was already extracted from front matter
    and no title detection is performed.

    Returns (metadata_dict, structured_sections, nesting_corrections).

    Note: metadata extraction is done internally for backward compatibility.
    New callers should use structure_body() after separate metadata extraction.
    """
    metadata, sections = _extract_metadata(sections)
    return _structure_body_impl(metadata, sections, has_title)


def structure_body(sections: list[Section],
                   has_title: bool = False,
                   figure_regions: list | None = None,
                   metadata_title: str | None = None,
                   ) -> tuple[dict, list[Section], int]:
    """Body structuring only, without metadata extraction.

    Called after metadata extraction is complete.
    Returns (body_metadata, structured_sections, nesting_corrections).
    body_metadata may contain a 'title' if one was detected during structuring.

    ``metadata_title`` is the title already extracted upstream (WG21 block
    scan / PDF info). It lets font-size ranking distinguish the real title
    block from a same-position body heading; see ``_title_section_for_ranking``.
    """
    return _structure_body_impl({}, sections, has_title,
                                figure_regions=figure_regions,
                                metadata_title=metadata_title)


def _section_in_figure_region(sec: Section,
                              figure_regions: list[FigureRegion],
                              ) -> FigureRegion | None:
    """Return the matching FigureRegion if *sec* overlaps one, else None."""
    if not sec.lines:
        return None
    s_bbox = sec.lines[0].bbox
    s_y0, s_y1 = s_bbox[1], s_bbox[3]
    s_x0, s_x1 = s_bbox[0], s_bbox[2]
    for fr in figure_regions:
        if sec.page_num != fr.page_num:
            continue
        f_x0, f_y0, f_x1, f_y1 = fr.bbox
        if s_x0 < f_x1 and s_x1 > f_x0 and s_y0 < f_y1 and s_y1 > f_y0:
            return fr
    return None


_FIGURE_SANDWICH_MAX_WORDS = 6


def _absorb_figure_sandwiched_sections(sections: list[Section]) -> None:
    """Reclassify a short run of non-FIGURE sections wedged between two
    FIGURE sections on the same page as FIGURE.

    A diagram's box/arrow layout does not always geometrically enclose
    every one of its own labels (e.g. a row/tier caption sitting just
    outside the box cluster's bounding region, such as a vertical axis
    label with no bordered box of its own). Dual-path extraction can
    also split one such label into more than one section. Such a run is
    never real body prose in practice: real prose only ever appears
    before the first figure fragment on a page or after the last, never
    wedged between two figure fragments. Gated on the run's total word
    count so a genuine paragraph that ever ended up sandwiched is left
    alone. Mutates *sections* in place; callers should follow with
    :func:`_merge_figure_sections` to fold the result into one section.
    """
    n = len(sections)
    i = 1
    while i < n - 1:
        if sections[i - 1].kind != SectionKind.FIGURE or sections[i].kind == SectionKind.FIGURE:
            i += 1
            continue
        j = i
        while j < n and sections[j].kind != SectionKind.FIGURE:
            j += 1
        if j == n:
            break
        run = sections[i:j]
        page = sections[i - 1].page_num
        total_words = sum(len(s.text.split()) for s in run)
        if (all(s.page_num == page for s in run)
                and total_words <= _FIGURE_SANDWICH_MAX_WORDS):
            for s in run:
                s.kind = SectionKind.FIGURE
        i = j + 1


def _merge_figure_sections(sections: list[Section]) -> list[Section]:
    """Consolidate consecutive FIGURE sections into one per figure."""
    if not sections:
        return sections
    merged: list[Section] = [sections[0]]
    for sec in sections[1:]:
        prev = merged[-1]
        if (sec.kind == SectionKind.FIGURE
                and prev.kind == SectionKind.FIGURE
                and sec.page_num == prev.page_num):
            prev.text = prev.text + "\n" + sec.text
            prev.lines.extend(sec.lines)
            if sec.figure_graph is not None and prev.figure_graph is None:
                prev.figure_graph = sec.figure_graph
        else:
            merged.append(sec)
    return merged


def _structure_body_impl(metadata: dict,
                         sections: list[Section],
                         has_title: bool = False,
                         figure_regions: list | None = None,
                         metadata_title: str | None = None,
                         ) -> tuple[dict, list[Section], int]:
    """Implementation of body structuring logic."""
    body_size = _detect_body_size(sections)
    effective_title = metadata_title or metadata.get("title")
    title_section = _title_section_for_ranking(
        sections, body_size, effective_title)
    font_ranks = _rank_font_sizes(sections, body_size, skip=title_section)
    if title_section is not None and not font_ranks:
        # Excluding the title emptied the ranking: the title is the only
        # heading-scale font, so there are no real font-based heading tiers
        # for its exclusion to protect. Keep it in to preserve the prior
        # classification (dropping to an empty ranking destabilises the
        # front-region passes and can strip leading body paragraphs).
        font_ranks = _rank_font_sizes(sections, body_size)

    _log.debug("Body size: %.1f, font ranks: %s", body_size, font_ranks)

    title_found = has_title
    structured: list[Section] = []
    skip_indices: set[int] = set()
    last_heading_level = 0

    for idx, sec in enumerate(sections):
        if idx in skip_indices:
            continue

        # A vector-diagram box grid (e.g. a layered architecture figure)
        # can trip the columnar TABLE heuristic in table.py. Figure-region
        # overlap takes precedence over that classification: reclassify to
        # FIGURE so it is dropped at emit time instead of rendered as a
        # fabricated table.
        if sec.kind == SectionKind.TABLE and figure_regions:
            matched_region = _section_in_figure_region(sec, figure_regions)
            if matched_region is not None:
                sec.kind = SectionKind.FIGURE
                sec.confidence = Confidence.HIGH
                if matched_region.graph is not None:
                    sec.figure_graph = matched_region.graph
                structured.append(sec)
                continue

        # IMAGE participates in the y-sort but is opaque to the heading
        # / list / code / wording passes that follow. Short-circuiting
        # here keeps the image_ref payload intact and prevents the
        # adjacency-based passes (paragraph merging, code-block
        # detection, ...) from absorbing or spanning the IMAGE. Tables
        # have the same property for the same reason.
        if sec.kind in (
            SectionKind.UNCERTAIN,
            SectionKind.TABLE,
            SectionKind.IMAGE,
        ):
            structured.append(sec)
            continue

        all_lines = sec.text.split("\n")
        first_line = all_lines[0].strip()

        # Multi-line heading blocks: MuPDF sometimes places the section
        # number ("I.", "2.") on line 0 and the title on line 1.  Join
        # them so SECTION_NUM_RE and _is_known_section see the full heading.
        # Guard: require bold (heading font) to avoid joining numbered list items.
        _sec_is_bold = bool(sec.lines) and sec.lines[0].is_bold
        if (len(all_lines) >= 2
                and _sec_is_bold
                and _BARE_SECTION_NUM_RE.match(first_line)):
            second = all_lines[1].strip()
            if second and len(second.split()) <= _HEADING_MAX_WORDS:
                _log.debug("Multi-line heading join: %r + %r", first_line, second)
                first_line = first_line.rstrip(".").rstrip() + " " + second

        if not title_found:
            is_large = sec.font_size > body_size * _TITLE_SIZE_RATIO
            is_known = (_is_known_section(first_line)
                        or first_line.lower() in ("contents", "table of contents"))
            is_section_num = bool(SECTION_NUM_RE.match(first_line))
            has_email = "@" in first_line
            is_date = bool(DATE_RE.match(first_line))
            too_long = len(first_line) > _TITLE_MAX_LENGTH

            if is_large and (is_known or is_section_num):
                title_found = True
                # Fall through to heading classification below so the
                # section is classified as HEADING, not left as PARAGRAPH.

            if (is_large and not is_section_num and not is_known
                    and not has_email and not is_date and not too_long):
                title_parts = [" ".join(
                    ln.strip() for ln in sec.text.split("\n") if ln.strip()
                )]
                title_fs = sec.font_size
                large_thresh = body_size * _TITLE_SIZE_RATIO
                for j in range(idx + 1, len(sections)):
                    nxt = sections[j]
                    if nxt.font_size <= large_thresh:
                        break
                    fl = nxt.text.split("\n")[0].strip()
                    if abs(nxt.font_size - title_fs) / title_fs > _TITLE_CONT_FONT_TOL:
                        break
                    fl_low = fl.lower().rstrip(":")
                    if _is_known_section(fl) or fl_low in _TITLE_CONT_SKIP:
                        break
                    if SECTION_NUM_RE.match(fl):
                        break
                    if _TITLE_CONT_DATE_RE.match(fl):
                        break
                    if "@" in fl:
                        break
                    if not fl or fl.isspace():
                        break
                    if fl.strip().isdigit():
                        break
                    title_parts.append(fl)
                    skip_indices.add(j)
                raw_title = " ".join(title_parts)
                stripped = _TITLE_PID_PREFIX_RE.sub("", raw_title).strip()
                metadata["title"] = stripped if stripped else raw_title
                sec.kind = SectionKind.TITLE
                sec.heading_level = 1
                sec.confidence = Confidence.HIGH
                title_found = True
                structured.append(sec)
                last_heading_level = 1
                continue

        # Figure-region guard: text overlapping a detected vector-graphic
        # figure is classified as FIGURE to prevent heading misclassification
        # of diagram label fragments (e.g. box labels rendered in bold).
        if figure_regions:
            matched_region = _section_in_figure_region(sec, figure_regions)
            if matched_region is not None:
                sec.kind = SectionKind.FIGURE
                sec.confidence = Confidence.HIGH
                if matched_region.graph is not None:
                    sec.figure_graph = matched_region.graph
                structured.append(sec)
                continue

        m = SECTION_NUM_RE.match(first_line)
        has_number = m is not None
        section_num = m.group(1) if m else ""

        line_fs = sec.font_size
        font_level = font_ranks.get(line_fs)
        # Fallback: if section's most-common font size isn't a heading font,
        # check the first line's font size (handles MuPDF heading+body merges).
        # Only triggers when there is a clear size drop from line 0 to line 1,
        # confirming the heading+body merge pattern.
        if font_level is None and len(sec.lines) >= 2:
            first_fs = sec.lines[0].font_size
            second_fs = sec.lines[1].font_size
            if first_fs - second_fs >= _HEADING_BODY_SPLIT_DELTA:
                first_level = font_ranks.get(first_fs)
                if first_level is not None:
                    font_level = first_level
                    line_fs = first_fs
        is_bold = bool(sec.lines) and sec.lines[0].is_bold
        is_known = _is_known_section(first_line)

        # Sections whose FIRST LINE is just a bullet character plus an
        # injected glyph placeholder ("●" + "�") are list-item prefixes
        # from PDFs that decorate each bullet with an emoji raster. The
        # synthetic sentinel span's bbox-derived font_size can trip
        # heading_confidence's font-rank branch, which would mis-promote
        # the bullet line to a heading and orphan its following paper-
        # title body (canonical case: N5007 page 11's Profiles list).
        # Skip heading classification here; the section then drops to
        # the list-detection branch below or the position-based detector
        # downstream, both of which know how to merge bullet + body.
        #
        # Strip the shared ZERO_WIDTH_CHARS before the emptiness check:
        # some PDFs follow each bullet glyph with a zero-width joiner,
        # which standard ``str.strip()`` does NOT remove. Also strip the
        # placeholder character itself, since a freshly-injected sentinel
        # may have been merged into the bullet line's text representation.
        _BULLET_STRIP_FIRST_LINE = {ord(c): None for c in BULLET_CHARS}
        _BULLET_STRIP_FIRST_LINE.update({c: None for c in ZERO_WIDTH_CHARS})
        _BULLET_STRIP_FIRST_LINE[ord(UNKNOWN_GLYPH)] = None
        _first_line_stripped = first_line.translate(
            _BULLET_STRIP_FIRST_LINE
        ).strip()
        first_line_is_bullet_marker = (
            not _first_line_stripped
            and any(
                s.font_name == GLYPH_FONT_SENTINEL
                for ln in sec.lines for s in ln.spans
            )
        )

        # A monospace first line carrying code-syntax characters (parens,
        # braces, semicolons, ``=``, ``<``/``>``, ``[``/``]``) is a code
        # line, never a WG21 section heading. Single-page PDF extracts
        # skew the font distribution so the code font ranks as a heading
        # size; without this gate a line like ``V f(int n, ...)`` or
        # ``V x = '\1'; // OK`` is promoted to H2 and the rest of the
        # listing is dropped into a PARAGRAPH where emit.py renders each
        # monospace span as inline code, splitting one CODE block into a
        # fence + heading + backticked paragraph. The ``_CODE_CHARS``
        # conjunction is what distinguishes a syntactic code line from a
        # legitimate code-styled heading like ``std::assert`` (monospace
        # at a heading font, but no syntax punctuation).
        is_mono = bool(sec.lines) and sec.lines[0].is_monospace
        first_line_is_mono_code = (
            is_mono and bool(_CODE_CHARS & set(first_line))
        )

        # A section with no visible text (e.g. a blank elevated-font spacer
        # on a TOC page) must never become a heading; otherwise emit.py
        # renders it as a textless "##### ".
        heading_has_text = bool(
            first_line.translate(_ZERO_WIDTH).strip())

        if (heading_has_text
                and (has_number or font_level is not None or is_known or is_bold)
                and not first_line_is_bullet_marker
                and not first_line_is_mono_code):
            number_level = _heading_level_from_number(section_num) if has_number else 0
            level, conf = heading_confidence(
                has_number, number_level, font_level, is_bold, is_known)

            # Color signal: if the first line's color differs from the
            # next body line, the visual distinction strengthens the case
            # for a heading.  Upgrade LOW -> MEDIUM so the prose-length
            # filter does not reject long but visually distinct headings.
            if conf == Confidence.LOW and len(sec.lines) >= 2:
                head_color = _line_color(sec.lines[0])
                body_color = _line_color(sec.lines[1])
                if head_color is not None and body_color is not None and head_color != body_color:
                    conf = Confidence.MEDIUM

            # Bold-only headings: heading_confidence returns level=0.
            # Infer level from the last heading seen (child of it),
            # clamped to at least 3 so bold-only never becomes H2.
            # Reject if the line contains code-like characters or is
            # monospace (avoids misclassifying code fragments as headings).
            if level == 0 and is_bold and conf == Confidence.LOW:
                has_code_chars = bool(_CODE_CHARS & set(first_line))
                is_mono = bool(sec.lines) and sec.lines[0].is_monospace
                if has_code_chars or is_mono:
                    level = 0  # keep as paragraph
                else:
                    level = max(last_heading_level + 1, 3)

            is_prose_length = len(first_line.split()) > _HEADING_MAX_WORDS
            prose_on_weak_signal = is_prose_length and conf == Confidence.LOW
            # Multi-signal gate (#302): one weak signal is not enough on its
            # own, so a LOW-confidence candidate must also *look* like a
            # heading. Without this a footer disclaimer set one point above
            # body size, or a standardese paragraph number, becomes a heading
            # and pollutes the outline every downstream chunker reads.
            if conf == Confidence.LOW and not _weak_heading_qualifies(
                    first_line, section_num, font_level, is_bold, is_known):
                prose_on_weak_signal = True
            if level > 0 and not prose_on_weak_signal:
                head_sec, body_sec = _split_heading_body(sec, body_size)
                head_sec.kind = SectionKind.HEADING
                head_sec.heading_level = level
                head_sec.confidence = conf
                structured.append(head_sec)
                if body_sec is not None:
                    structured.append(body_sec)
                last_heading_level = level
                continue

        lines = sec.text.split("\n")
        is_list = all(
            BULLET_RE.match(ln) or NUMBERED_LIST_RE.match(ln)
            for ln in lines if ln.strip()
        )
        if is_list and any(ln.strip() for ln in lines):
            sec.kind = SectionKind.LIST
            structured.append(sec)
            continue

        sec.kind = SectionKind.PARAGRAPH
        structured.append(sec)

    if figure_regions:
        _absorb_figure_sandwiched_sections(structured)
        structured = _merge_figure_sections(structured)
    structured = _merge_orphan_heading_numbers(structured)
    structured = _detect_lists_by_position(structured)
    structured = _merge_paragraphs(structured)
    structured = _split_mixed_mono_sections(structured)
    _assign_list_nesting(structured)
    structured = _detect_code_blocks(structured)
    structured = [s for s in structured if _detect_lang_label(s) is None]
    structured = _classify_wording_sections(structured)
    structured = _coalesce_code_paragraphs(structured)
    structured = _absorb_code_orphans(structured)
    structured = _rescue_unfenced_code(structured)
    structured = _split_embedded_code(structured)
    structured = _absorb_mono_code_orphans(structured)
    structured = _absorb_trailing_label_into_code(structured)
    structured = _trim_narrative_from_code(structured)
    structured = _peel_trailing_prose_from_code(structured)
    _demote_repeated_low_confidence_numbers(structured)
    nesting_corrections = _validate_nesting(structured)
    return metadata, structured, nesting_corrections


# Bare section number with no heading text (e.g. "1", "2.3", "A").
# Some PDFs render the heading number in large font and the title
# text in a smaller font, producing separate blocks.
_BARE_SECTION_NUM_RE = re.compile(
    rf"^\s*(?:{SECTION_NUM_PATTERN}|[A-Z])\.?\s*$"
)
# Max words in the paragraph that follows an orphan heading number.
# Real heading titles are short; if the next paragraph is longer,
# it's body text, not a title.
_ORPHAN_HEADING_MAX_WORDS = 8


def _merge_orphan_heading_numbers(sections: list[Section]) -> list[Section]:
    """Merge bare-number headings with the following short paragraph.

    Some PDFs (e.g. P4012R0) render heading numbers in large font
    and heading titles in a different, smaller font. The structure
    pass classifies the number as a HEADING and the title as a
    PARAGRAPH. This pass detects that pattern and merges them:
    the heading text becomes "N TITLE" and the paragraph is consumed.
    """
    if len(sections) < 2:
        return sections

    result: list[Section] = []
    skip_next = False

    for i, sec in enumerate(sections):
        if skip_next:
            skip_next = False
            continue

        if (sec.kind == SectionKind.HEADING
                and i + 1 < len(sections)
                and _BARE_SECTION_NUM_RE.match(sec.text.strip())):
            nxt = sections[i + 1]
            nxt_text = nxt.text.strip()
            nxt_words = len(nxt_text.split())
            if (nxt.kind == SectionKind.PARAGRAPH
                    and 0 < nxt_words <= _ORPHAN_HEADING_MAX_WORDS
                    and nxt.page_num == sec.page_num):
                merged_text = f"{sec.text.strip()} {nxt_text}"
                merged = replace(
                    sec,
                    text=merged_text,
                    lines=sec.lines + nxt.lines,
                )
                _log.info("Merged orphan heading number %r + %r -> %r",
                           sec.text.strip(), nxt_text, merged_text)
                result.append(merged)
                skip_next = True
                continue

        result.append(sec)

    return result


_BULLET_SPLIT_RE = re.compile(
    r"(?=[" + "".join(BULLET_CHARS) + r"][\s\u200b])"
)

_INDENT_TOLERANCE = 5.0


def _get_body_margin(sections: list[Section]) -> float:
    """Find the leftmost frequent x-position (= body left margin).

    Uses the leftmost x that accounts for at least 10% of lines,
    rather than the most common x, to handle PDFs where indented
    content is more frequent than body text.
    """
    x_counts: Counter[float] = Counter()
    for sec in sections:
        for line in sec.lines:
            if line.text.strip() and line.spans:
                x = round(line.bbox[0] / _INDENT_TOLERANCE) * _INDENT_TOLERANCE
                x_counts[x] += 1
    if not x_counts:
        return 0.0
    total = sum(x_counts.values())
    threshold = total * _BODY_MARGIN_FRACTION
    for x in sorted(x_counts.keys()):
        if x_counts[x] >= threshold:
            return x
    return x_counts.most_common(1)[0][0]


def _line_starts_with_bullet(line) -> bool:
    """Check if a line starts with a bullet character."""
    text = line.text.strip()
    if not text:
        return False
    return text[0] in BULLET_CHARS


def _detect_lists_by_position(sections: list[Section]) -> list[Section]:
    """Detect list structure using line x-positions and bullet characters.

    Uses indentation (x-coordinate) to identify list items. Lines
    indented from the body margin that start with a bullet character
    are list items. Lines at the body margin between bullet groups
    are parent list items. Also handles inline bullet splitting
    when position data is unavailable.
    """
    body_margin = _get_body_margin(sections)

    result = []
    for sec in sections:
        if sec.kind != SectionKind.PARAGRAPH:
            result.append(sec)
            continue

        # A free-standing glyph placeholder block (only U+FFFD spans) must
        # not be read as a list item by the x-coordinate heuristic.
        sec_spans = [s for ln in sec.lines for s in ln.spans if s.text.strip()]
        if sec_spans and all(s.font_name == GLYPH_FONT_SENTINEL
                             for s in sec_spans):
            result.append(sec)
            continue

        if sec.lines:
            items = _split_section_by_position(sec, body_margin)
            result.extend(items)
        else:
            items = _split_inline_bullets_text(sec)
            result.extend(items)

    return result


def _join_bullet_marker_lines(lines: list) -> list:
    """Join bullet marker lines with their following text lines.

    Some PDFs render the dash/bullet on one line (x=90) and the text
    on the next line (x=108). Combine them into a single line.
    """
    if len(lines) < 2:
        return lines
    result = []
    i = 0
    while i < len(lines):
        line = lines[i]
        text = line.text.strip()
        if not line.spans:
            result.append(line)
            i += 1
            continue
        if (text and text[0] in BULLET_CHARS and len(text) <= _BULLET_JOIN_MAX_CHARS
                and i + 1 < len(lines)):
            next_line = lines[i + 1]
            bullet = strip_format_chars(text).rstrip()
            bullet_span = Span(
                text=bullet + " ",
                font_name=line.spans[0].font_name if line.spans else "",
                font_size=line.spans[0].font_size if line.spans else 0,
                bold=line.spans[0].bold if line.spans else False,
                italic=line.spans[0].italic if line.spans else False,
                monospace=line.spans[0].monospace if line.spans else False,
                bbox=line.spans[0].bbox if line.spans else (0, 0, 0, 0),
                origin=line.spans[0].origin if line.spans else (0, 0),
            )
            combined_spans = [bullet_span] + list(next_line.spans)
            result.append(Line(
                spans=combined_spans,
                bbox=(line.bbox[0], line.bbox[1], next_line.bbox[2], next_line.bbox[3]),
                page_num=line.page_num,
            ))
            i += 2
        else:
            result.append(line)
            i += 1
    return result


def _split_section_by_position(sec: Section, body_margin: float) -> list[Section]:
    """Split a section into list items using line x-positions."""
    lines = _join_bullet_marker_lines(sec.lines)

    indented_bullets = []
    for line in lines:
        if not line.text.strip() or not line.spans:
            continue
        x = line.bbox[0]
        if x > body_margin + _INDENT_TOLERANCE and _line_starts_with_bullet(line):
            indented_bullets.append(line)

    if len(indented_bullets) < 1:
        return [sec]

    items: list[Section] = []
    current_lines: list = []
    current_is_bullet = False

    for line in lines:
        if not line.text.strip():
            if current_lines:
                current_lines.append(line)
            continue

        x = line.bbox[0]
        is_bullet = _line_starts_with_bullet(line)
        # We only need item boundaries here (is this bullet indented past
        # the body margin); nesting depth is assigned later, relative to
        # siblings, by _assign_list_nesting.
        is_indented = x > body_margin + _INDENT_TOLERANCE

        if is_bullet and is_indented:
            if current_lines:
                text = "\n".join(ln.text for ln in current_lines if ln.text.strip())
                items.append(Section(
                    kind=SectionKind.LIST if current_is_bullet else SectionKind.PARAGRAPH,
                    text=text,
                    confidence=sec.confidence,
                    lines=list(current_lines),
                    page_num=sec.page_num,
                    font_size=sec.font_size,
                ))
            current_lines = [line]
            current_is_bullet = True
        elif not is_indented and current_is_bullet:
            if current_lines:
                text = "\n".join(ln.text for ln in current_lines if ln.text.strip())
                items.append(Section(
                    kind=SectionKind.LIST,
                    text=text,
                    confidence=sec.confidence,
                    lines=list(current_lines),
                    page_num=sec.page_num,
                    font_size=sec.font_size,
                ))
            current_lines = [line]
            current_is_bullet = False
        else:
            current_lines.append(line)

    if current_lines:
        text = "\n".join(ln.text for ln in current_lines if ln.text.strip())
        if text.strip():
            items.append(Section(
                kind=SectionKind.LIST if current_is_bullet else SectionKind.PARAGRAPH,
                text=text,
                confidence=sec.confidence,
                lines=list(current_lines),
                page_num=sec.page_num,
                font_size=sec.font_size,
            ))

    if not items:
        return [sec]

    bullet_count = sum(1 for it in items if it.kind == SectionKind.LIST)
    if bullet_count < 1:
        return [sec]

    return items


def _split_inline_bullets_text(sec: Section) -> list[Section]:
    """Fallback: split paragraphs at Unicode bullet characters in text."""
    text = sec.text
    parts = _BULLET_SPLIT_RE.split(text)
    if len(parts) <= 1:
        return [sec]

    result = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        starts_with_bullet = part[0] in BULLET_CHARS
        result.append(Section(
            kind=SectionKind.LIST if starts_with_bullet else SectionKind.PARAGRAPH,
            text=part,
            confidence=sec.confidence,
            lines=[],
            page_num=sec.page_num,
            font_size=sec.font_size,
        ))
    return result if result else [sec]


def _bullet_x(sec: Section) -> float | None:
    """Return the x-position of a list item's bullet (its first content line).

    Text-only list items (from the inline-bullet fallback) carry no
    geometry and return None.
    """
    for line in sec.lines:
        if line.text.strip() and line.spans:
            return line.bbox[0]
    return None


def _assign_list_nesting(sections: list[Section]) -> None:
    """Set ``indent_level`` on LIST sections from their relative x-position.

    Mutates the sections in place. Nesting depth is relative within each
    run of consecutive LIST sections on a single page, not absolute from
    the body margin: the leftmost bullets in a run are depth 0, the next
    x-stop is depth 1, and so on. This is the only place depth is computed
    (the position splitter just finds item boundaries) because a parent
    list and its nested children can arrive as separate sections, so a
    child's depth is only knowable relative to its siblings across the run.

    A run is split at page boundaries before depth is computed. Because
    depth is purely x-relative, a list that continues onto the next page
    (or into a second column) can resume at a different left margin, which
    a whole-run clustering would misread as a new nesting level. Clustering
    each page independently keeps that margin shift from inventing depth.
    """
    i = 0
    while i < len(sections):
        if sections[i].kind != SectionKind.LIST:
            i += 1
            continue
        j = i
        while j < len(sections) and sections[j].kind == SectionKind.LIST:
            j += 1
        run = sections[i:j]
        start = 0
        for k in range(1, len(run) + 1):
            if k == len(run) or run[k].page_num != run[start].page_num:
                _set_run_depths(run[start:k])
                start = k
        i = j


def _set_run_depths(run: list[Section]) -> None:
    """Assign relative nesting depth to each LIST section in one run.

    Bullet x-positions are clustered into stops (gaps wider than
    ``_INDENT_TOLERANCE`` open a new stop); an item's depth is the number
    of stops it sits clear to the right of, using the same tolerance as
    the clustering so the two never disagree.

    Clustering is greedy against the last stop, so a chain of bullets each
    within tolerance of the previous but spanning more than tolerance
    end-to-end (e.g. 50, 54, 58 at tolerance 5 -> stops 50, 58) can place
    near-neighbours at different depths. This is acceptable: real PDFs keep
    same-level bullets at a consistent x well inside the tolerance, so the
    evenly-bridged spread does not occur in practice.
    """
    positioned = [(x, sec) for sec in run if (x := _bullet_x(sec)) is not None]
    if not positioned:
        return

    stops: list[float] = []
    for x in sorted(x for x, _ in positioned):
        if not stops or x - stops[-1] > _INDENT_TOLERANCE:
            stops.append(x)

    for x, sec in positioned:
        sec.indent_level = sum(1 for stop in stops if x - stop > _INDENT_TOLERANCE)


_LIST_CONTINUATION_INDENT = 10.0  # min extra x-offset (pt) for indent merge
_BULLET_LIKE = BULLET_CHARS | frozenset("\u25cb\u25b8\u25ba\u25c6\u2013\u2014")
# A block that continues the sentence of the block above sits exactly one
# line pitch below it: baseline to baseline, in font sizes, the same value
# for every wrapped line of a document (P4016R0 1.500 over 979 samples,
# P0957R8 1.566 +-0.04, P4100R1/P4182R0/P4094R0 1.850) and independent of
# the ascender/descender boxes, which overlap under tight leading and
# grow on lines with inline code. A paragraph break adds the paragraph
# spacing: +0.5 at the smallest common setting (Word, 6pt after 12pt
# text; LaTeX parskip 0.5 baselineskip is +0.6). Bibliographies and
# definition lists set at line pitch are told apart lexically and by the
# wrap proof below.
_WRAP_PITCH_TOL = 0.15  # font sizes
_WRAP_PITCH_MIN = 0.5  # font sizes; closer baselines are the same line
_PARAGRAPH_CONTINUATION_FONT_TOL = 0.5  # pt; a wrapped line keeps its size
# The wrapped line starts at the paragraph's left edge: never right of the
# line above (that is a column or an indented item), at most a first-line
# indent left of it, and only when the line above is the paragraph's
# first line (any later line already sits at the edge).
_CONTINUATION_LEFT_TOL = 2.0  # pt
_CONTINUATION_INDENT_MAX = 2.0  # font sizes
# Average glyph advance of proportional body text, in font sizes. Used to
# estimate whether the next block's first word would have fit on the
# previous line.
# shortcut: one flat glyph width; switch to the first word's span bbox if
# wraps before short code tokens (`+`, `L),`) turn out to be missed.
_AVG_CHAR_WIDTH = 0.5
# A layout measure (text margin, wrap pitch) needs at least this many
# witnesses. One long URL or a lone short list in an otherwise empty
# document establishes neither.
_LAYOUT_WITNESS_MIN = 3
# The text margin is the largest line end that enough paragraph or list
# lines share within this tolerance.
_MARGIN_WITNESS_TOL = 6.0  # pt
# Quotes, emphasis and closing brackets that may follow a sentence's
# final punctuation (`"unified interface."`, `**bold.**`).
_CLOSING_MARKS = "*`\"'\u2019\u201d)]"
# `(1)`, `(iii)`, `a)`: an enumeration label opens an item, never a
# continuation, whatever the geometry says.
_ENUM_LABEL_RE = re.compile(r"^\(?(?:\d+|[ivxlc]+|[a-z])\)\s", re.IGNORECASE)
# A bracketed start continues a sentence when the closing bracket is
# followed by punctuation or a lowercase word (`[numerics.defns]. GEN...`,
# `[algorithms.parallel.exec], `, `[4] and [5]`). Followed by anything
# else it labels a bibliography entry (`[GB-SEQ] = https://...`,
# `[N4950] Working Draft`) or opens a note (`[Note: ...`).
_BRACKET_CONTINUATION_RE = re.compile(r"^\[[^\]]+\](?:[.,;:)]|\s+[a-z])")


def _starts_inline_continuation(sec: Section) -> bool:
    """A paragraph whose first token cannot open a sentence of its own.

    An opening parenthesis (``(lane count L), the expression``), a
    bracketed reference the sentence runs on from (``[numerics.defns].
    GENERALIZED_SUM ...``, see :data:`_BRACKET_CONTINUATION_RE`) or an
    inline code span on a mixed prose line (``GENERALIZED_SUM, operand
    reordering);``) continues the sentence above; MuPDF starts a new
    block there because the glyph run changes. A line that is all
    monospace is code, and a bullet, list number or enumeration label
    opens an item, so none of those qualifies.
    """
    text = sec.text.lstrip()
    if (not text or BULLET_RE.match(text) or NUMBERED_LIST_RE.match(text)
            or _ENUM_LABEL_RE.match(text)):
        return False
    first = next((ln for ln in sec.lines if ln.text.strip()), None)
    if first is None or first.is_monospace:
        return False
    if text[0] == "(":
        return True
    if text[0] == "[":
        return bool(_BRACKET_CONTINUATION_RE.match(text))
    spans = [s for s in first.spans if s.text.strip()]
    return bool(spans) and spans[0].monospace


def _continues_lowercase(prev: Section, sec: Section) -> bool:
    """The lowercase rule: ``prev`` ends without terminal punctuation and
    ``sec`` starts with a lowercase letter, so the line wrapped."""
    prev_text = prev.text.rstrip()
    cur_text = sec.text.lstrip()
    return (bool(prev_text) and bool(cur_text)
            and prev_text[-1] not in TERMINAL_PUNCTUATION
            and cur_text[0].islower())


def _baseline(line: Line) -> float:
    """Baseline y of a line: the first content span's origin, or the box
    bottom when the extractor supplied no origin (synthetic lines)."""
    for span in line.spans:
        if span.text.strip() and span.origin[1]:
            return span.origin[1]
    return line.bbox[3]


def _content_lines(sec: Section) -> list[Line]:
    return [ln for ln in sec.lines if ln.text.strip()]


def _pitch_ratio(upper: Line, lower: Line) -> float | None:
    """Baseline distance from ``upper`` to ``lower`` in font sizes, or
    None when the lines are on different pages, without a font size, or
    too close to be separate lines."""
    fs = upper.font_size
    if upper.page_num != lower.page_num or not fs:
        return None
    ratio = (_baseline(lower) - _baseline(upper)) / fs
    return ratio if ratio >= _WRAP_PITCH_MIN else None


def _wrap_pitch(sections: list[Section],
                kinds: frozenset[SectionKind]) -> float | None:
    """The document's line pitch for wrapped prose, in font sizes.

    Median over the pairs known to be wraps: consecutive prose lines
    inside one section, and section boundaries the lowercase rule merges
    (:func:`_continues_lowercase`). Some producers give MuPDF one block
    per line, so a document may have no multi-line section at all and
    the boundary sample carries it. Code lines are excluded: listings are
    still paragraphs here and often set at a different pitch. None below
    :data:`_LAYOUT_WITNESS_MIN` samples.
    """
    samples: list[float] = []
    for sec in sections:
        if sec.kind not in kinds:
            continue
        lines = [ln for ln in _content_lines(sec) if not ln.is_monospace]
        for upper, lower in zip(lines, lines[1:]):
            ratio = _pitch_ratio(upper, lower)
            if ratio is not None:
                samples.append(ratio)
    for prev, sec in zip(sections, sections[1:]):
        if (prev.kind not in kinds or sec.kind not in kinds
                or not _continues_lowercase(prev, sec)):
            continue
        prev_lines, sec_lines = _content_lines(prev), _content_lines(sec)
        if not prev_lines or not sec_lines:
            continue
        upper, lower = prev_lines[-1], sec_lines[0]
        if upper.is_monospace or lower.is_monospace:
            continue
        ratio = _pitch_ratio(upper, lower)
        if ratio is not None:
            samples.append(ratio)
    if len(samples) < _LAYOUT_WITNESS_MIN:
        return None
    return statistics.median(samples)


def _text_margin(sections: list[Section],
                 kinds: frozenset[SectionKind]) -> float | None:
    """The document's right text margin, or None when nothing establishes one.

    The margin is the largest line end shared by at least
    :data:`_LAYOUT_WITNESS_MIN` lines of the given kinds anywhere in the
    document; body pages share one measure, and a ragged-right paper with
    sparse pages (P4182R0, tables on most pages) still reaches the margin
    a few times over the whole document. Code listings are still
    paragraphs at this stage and a wide one inflates the value, as does
    the right column of a two-column layout; both only disable the inline
    merge (fail closed). A document with fewer than three lines reaching
    its true margin gets a smaller one; the pitch gate still stands.
    """
    xs = sorted((ln.bbox[2] for s in sections if s.kind in kinds
                 for ln in s.lines if ln.text.strip()), reverse=True)
    for i, edge in enumerate(xs):
        witnesses = sum(1 for x in xs[i:] if x >= edge - _MARGIN_WITNESS_TOL)
        if witnesses >= _LAYOUT_WITNESS_MIN:
            return edge
    return None


def _is_wrapped_continuation(prev: Section, sec: Section,
                             right_edge: float | None,
                             pitch: float | None) -> bool:
    """Geometry says ``sec`` continues the line ``prev`` broke mid-sentence.

    Same page and font size; ``sec``'s first line sits exactly one wrap
    pitch (:func:`_wrap_pitch`, baseline to baseline) below ``prev``'s
    last line, starting at that line's left edge (or a first-line indent
    to its left when that line is the paragraph's only line); and
    ``sec``'s first word would not have fit on that last line before
    ``right_edge`` (the text margin, see :func:`_text_margin`). A line
    wraps only when the next word does not fit, so a short last line
    (list item, definition entry, bibliography URL followed by a short
    label) never qualifies, and a document without an established margin
    or pitch never merges.
    """
    if not right_edge or pitch is None:
        return False
    fs = prev.font_size
    if not fs or abs(sec.font_size - fs) > _PARAGRAPH_CONTINUATION_FONT_TOL:
        return False
    prev_lines = _content_lines(prev)
    last = prev_lines[-1] if prev_lines else None
    first = next(iter(_content_lines(sec)), None)
    if last is None or first is None:
        return False
    ratio = _pitch_ratio(last, first)
    if ratio is None or abs(ratio - pitch) > _WRAP_PITCH_TOL:
        return False
    dx = first.bbox[0] - last.bbox[0]
    indent = (_CONTINUATION_INDENT_MAX * fs if len(prev_lines) == 1
              else _CONTINUATION_LEFT_TOL)
    if not (-indent <= dx <= _CONTINUATION_LEFT_TOL):
        return False
    first_word = sec.text.split()[0]
    needed = (len(first_word) + 1) * _AVG_CHAR_WIDTH * fs  # word + space
    return last.bbox[2] + needed > right_edge


def _merge_paragraphs(sections: list[Section]) -> list[Section]:
    """Merge consecutive sections that are continuations.

    When a section ends without terminal punctuation and the next
    paragraph starts with a lowercase letter, they are the same
    logical paragraph split by PDF line wrapping. Works for
    PARAGRAPH+PARAGRAPH and LIST+PARAGRAPH (bullet continuation).

    Also merges PARAGRAPH into a preceding LIST when the paragraph is
    x-indented relative to the list item, indicating it is a
    continuation of the same list entry (e.g. a second sentence under
    a numbered item that MuPDF placed in a separate block).

    A text merge whose boundary is a hyphen-terminated line (MuPDF opens
    a new block after ``floating-`` at ordinary line spacing) runs T9's
    :func:`dehyphenate_pair` on the boundary pair, so the joined
    paragraph reads ``floating-point`` / ``implementation-defined`` and
    never ``floating- point``. The block-internal wraps were handled in
    ``cleanup_text``; this is the same rule for the wraps it cannot see.

    The same block split also lands before an opening bracket or an
    inline code span (``... topology coordinate`` / ``(lane count L), the
    expression ...``). Those starts are not lowercase, so they merge only
    when the geometry proves a wrap (:func:`_is_wrapped_continuation`):
    same page and font, the next block one wrap pitch below and at the
    same left edge, and its first word too wide for the room left before
    the text margin.
    """
    if len(sections) < 2:
        return sections

    mergeable = frozenset({SectionKind.PARAGRAPH, SectionKind.LIST})
    evidence = collect_hyphen_evidence([ln for s in sections for ln in s.lines])
    # A wrapped line is one whose successor word would have crossed the
    # text margin, sitting one wrap pitch below.
    margin = _text_margin(sections, mergeable)
    pitch = _wrap_pitch(sections, mergeable)

    result = [replace(sections[0], lines=list(sections[0].lines))]
    for sec in sections[1:]:
        prev = result[-1]
        if (prev.kind in mergeable
                and sec.kind == SectionKind.PARAGRAPH
                and prev.text.rstrip()
                and sec.text.lstrip()):
            text_merge = _continues_lowercase(prev, sec)

            indent_merge = False
            if (prev.kind == SectionKind.LIST
                    and prev.lines and sec.lines
                    and sec.page_num == prev.page_num):
                prev_x0 = prev.lines[0].bbox[0]
                prev_last_x0 = prev.lines[-1].bbox[0]
                sec_x0 = sec.lines[0].bbox[0]
                y_gap = sec.lines[0].bbox[1] - prev.lines[-1].bbox[3]
                max_gap = prev.font_size * 2.0
                first_char = sec.text.lstrip()[:1]
                if (sec_x0 - prev_x0 >= _LIST_CONTINUATION_INDENT
                        and sec_x0 >= prev_last_x0
                        and 0 <= y_gap <= max_gap
                        and first_char not in _BULLET_LIKE):
                    indent_merge = True

            inline_merge = False
            if not text_merge and not indent_merge:
                # `"unified interface."` ends a sentence although its last
                # character is a quote; a trailing hyphen needs T9, which
                # only the lowercase path runs.
                bare_end = prev.text.rstrip().rstrip(_CLOSING_MARKS)[-1:]
                inline_merge = (
                    bool(bare_end)
                    and bare_end not in TERMINAL_PUNCTUATION
                    and bare_end != "-"
                    and _starts_inline_continuation(sec)
                    and _is_wrapped_continuation(prev, sec, margin, pitch))

            pair = None
            if text_merge and not indent_merge and prev.lines and sec.lines:
                pair = dehyphenate_pair(prev.lines[-1], sec.lines[0], evidence)
                # text and lines must move together; if the section text
                # does not carry the same boundary tokens as its lines,
                # fall through to the plain merge rather than desync them.
                if pair is not None and not (
                        prev.text.rstrip().endswith(pair.prefix_token)
                        and sec.text.lstrip().startswith(pair.first_word)):
                    pair = None

            if pair is not None:
                prev_text = prev.text.rstrip()
                cur_text = sec.text.lstrip()
                prev.text = (prev_text[:-len(pair.prefix_token)] + pair.joined
                             + cur_text[len(pair.first_word):])
                prev.lines[-1] = pair.last_line
                tail_lines = [] if pair.next_line is None else [pair.next_line]
                prev.lines.extend(tail_lines + list(sec.lines[1:]))
                prev.font_size = prev.lines[0].font_size
                continue

            if text_merge or indent_merge or inline_merge:
                joiner = "\n" if indent_merge else " "
                prev.text = prev.text.rstrip() + joiner + sec.text.lstrip()
                prev.lines.extend(sec.lines)
                if prev.lines:
                    prev.font_size = prev.lines[0].font_size
                continue
        result.append(replace(sec, lines=list(sec.lines)))
    return result


def _line_is_monospace(line) -> bool:
    """Check if all non-whitespace spans in a line are monospace."""
    text_spans = [s for s in line.spans if s.text.strip()]
    return bool(text_spans) and all(s.monospace for s in text_spans)


def _section_is_all_monospace(sec: Section) -> bool:
    """Check if every non-whitespace line in a section is monospace."""
    content_lines = [ln for ln in sec.lines if ln.text.strip()]
    return bool(content_lines) and all(_line_is_monospace(ln) for ln in content_lines)


def _section_is_empty(sec: Section) -> bool:
    """Check if a section has no visible text content."""
    return not sec.text.strip()


# Shared with the HTML class-based detector (lib.shared.CODE_LANG_LABELS) so
# the recognized-language set is a single source of truth.
_LANG_LABELS = CODE_LANG_LABELS


def _detect_lang_label(sec: Section) -> str | None:
    """Check if a section is a code block language label."""
    text = strip_format_chars(sec.text).strip().lower()
    return _LANG_LABELS.get(text)


_SPLIT_MIN_MONO_LINES = 3

# A line-leading C++ comment ("//" but not a URL's "://") marks a
# non-monospace line as code in a different font (papers often set
# section-reference comments like "// [c.math.lerp]" in italic serif),
# so the splitter keeps it with the adjacent code rather than splitting
# it off as prose.
_CODE_COMMENT_RE = re.compile(r"^\s*//[^/]")


def _split_mixed_mono_sections(sections: list[Section]) -> list[Section]:
    """Split PARAGRAPH sections that mix a monospace code run with prose.

    compare_extractions can deliver a single section whose lines are a
    long monospace code run preceded or followed by proportional-font
    prose (observed on P4231R0, where a synopsis crossing a page
    boundary arrived merged with the next prose paragraph). Left
    intact, the section is not all-monospace, so _detect_code_blocks
    cannot absorb it into the adjacent code run (the fence splits at
    the page boundary) and _rescue_unfenced_code later promotes the
    entire section, prose included, to CODE.

    Only prose at the section's edges is split off, and only when the
    remaining core is cleanly monospace with at least
    _SPLIT_MIN_MONO_LINES code lines. Non-monospace lines *inside* a
    code run (mixed-font code such as p0533r9's italic
    `// see [library.c]` comments) disqualify the section entirely:
    that pattern is one code block, not code-plus-prose, and is left
    for _rescue_unfenced_code to promote whole.
    """
    result: list[Section] = []
    for sec in sections:
        if sec.kind != SectionKind.PARAGRAPH:
            result.append(sec)
            continue
        segments = _split_lines_at_mono_runs(sec.lines)
        if len(segments) <= 1:
            result.append(sec)
            continue
        _log.info("Split mixed mono/prose section on page %d into %d parts",
                  sec.page_num, len(segments))
        for seg in segments:
            text = "\n".join(ln.text for ln in seg)
            result.append(replace(sec, text=text, lines=seg,
                                  page_num=seg[0].page_num))
    return result


def _split_lines_at_mono_runs(lines: list[Line]) -> list[list[Line]]:
    """Partition lines into edge-prose segments and a monospace core.

    Returns a single segment (no split) unless the lines form a
    cleanly monospace core of at least _SPLIT_MIN_MONO_LINES code
    lines with prose at one or both edges. Blank lines are neutral:
    inside the core they stay with the code; at an edge with prose
    they go to the prose segment.
    """
    def label(ln: Line) -> str:
        if not ln.text.strip():
            return "blank"
        if _line_is_monospace(ln) or _CODE_COMMENT_RE.match(ln.text):
            return "mono"
        return "prose"

    labels = [label(ln) for ln in lines]
    n = len(lines)
    core_start = 0
    while core_start < n and labels[core_start] != "mono":
        core_start += 1
    core_end = n
    while core_end > core_start and labels[core_end - 1] != "mono":
        core_end -= 1

    core = labels[core_start:core_end]
    if "prose" in core or core.count("mono") < _SPLIT_MIN_MONO_LINES:
        return [lines]
    lead_prose = "prose" in labels[:core_start]
    trail_prose = "prose" in labels[core_end:]
    if not lead_prose and not trail_prose:
        return [lines]

    segments: list[list[Line]] = []
    if lead_prose:
        segments.append(lines[:core_start])
    else:
        core_start = 0
    if trail_prose:
        segments.append(lines[core_start:core_end])
        segments.append(lines[core_end:])
    else:
        segments.append(lines[core_start:])
    return segments


def _detect_code_blocks(sections: list[Section]) -> list[Section]:
    """Detect runs of consecutive monospace sections and merge into CODE.

    Bridges empty sections (blank lines in code) between monospace runs.
    Detects language labels (e.g. "C/C++") immediately before code blocks
    and uses them for the fence language.
    """
    result: list[Section] = []
    mono_run: list[Section] = []
    fence_lang = DEFAULT_FENCE_LANG
    pending_label_idx = -1

    def flush_mono():
        nonlocal fence_lang, pending_label_idx
        if not mono_run:
            return
        all_lines = []
        for s in mono_run:
            if _section_is_empty(s):
                all_lines.append(Line(spans=[], bbox=(0, 0, 0, 0)))
            else:
                all_lines.extend(s.lines)
        code_text = "\n".join(ln.text for ln in all_lines)
        result.append(Section(
            kind=SectionKind.CODE,
            text=code_text,
            confidence=Confidence.HIGH,
            lines=all_lines,
            page_num=mono_run[0].page_num,
            fence_lang=fence_lang,
        ))
        if pending_label_idx >= 0 and pending_label_idx < len(result) - 1:
            del result[pending_label_idx]
        mono_run.clear()
        fence_lang = DEFAULT_FENCE_LANG
        pending_label_idx = -1

    for i, sec in enumerate(sections):
        if sec.kind in (SectionKind.PARAGRAPH, SectionKind.LIST, SectionKind.UNCERTAIN):
            if _section_is_all_monospace(sec):
                mono_run.append(sec)
                continue

            if _section_is_empty(sec) and mono_run:
                mono_run.append(sec)
                continue

        if mono_run:
            flush_mono()

        lang = _detect_lang_label(sec)
        if lang is not None:
            result.append(sec)
            fence_lang = lang
            pending_label_idx = len(result) - 1
        else:
            result.append(sec)
            if pending_label_idx >= 0:
                fence_lang = DEFAULT_FENCE_LANG
                pending_label_idx = -1

    flush_mono()
    return result


def _section_has_foreign_chromatic(sec: Section) -> bool:
    """True if any non-link span carries a syntax-highlighting color.

    Foreign chromatic = chromatic but outside the green (ins) / red (del)
    / blue (link) bands. Its presence marks the section as a
    syntax-highlighted code listing. Mirrors the block-level
    ``_block_has_foreign_colors`` filter in :mod:`wording`.
    """
    return any(
        is_foreign_chromatic(s.color)
        for ln in sec.lines for s in ln.spans
        if s.text.strip() and not s.link_url
    )


def _ins_spans_are_bare_numerals(spans: list[Span]) -> bool:
    """True if every ``ins``-tagged span's stripped text is digits only.

    A PDF syntax-highlighting theme that colors numeric literals (e.g. a
    "777" argument in an illustrative code example) can collide with
    WG21's own ins-green hue band. A genuine WG21 insertion marks an
    identifier, keyword, or punctuation token; it is never a bare number
    on its own, so a section whose only "ins" signal is one or more lone
    numeral runs is syntax highlighting, not a real edit.
    """
    return bool(spans) and all(s.text.strip().isdigit() for s in spans)


def _classify_wording_sections(sections: list[Section]) -> list[Section]:
    """Reclassify sections containing wording-marked spans."""
    for sec in sections:
        if sec.kind in (SectionKind.HEADING, SectionKind.TITLE,
                        SectionKind.UNCERTAIN, SectionKind.TABLE,
                        SectionKind.IMAGE):
            continue
        wording_spans = [s for ln in sec.lines for s in ln.spans
                         if s.wording_role and s.text.strip()]
        if not wording_spans:
            continue
        roles = {s.wording_role for s in wording_spans}
        non_context = roles - {"context"}
        # Syntax-highlighted code, not wording markup. A foreign chromatic
        # color (cyan, olive, purple, ...) is the signature of syntax
        # highlighting. When the only wording signal is green ("ins"), that
        # green is a keyword highlight hue that happened to fall in the ins
        # band, not a real insertion, so the section stays CODE rather than
        # collapsing into a single wording line. Sections with a red /
        # strikethrough deletion ("del") are genuine WG21 wording even when
        # the surrounding code is syntax-highlighted, so they are exempt.
        # A lone highlighted numeral (no foreign color companion) is the
        # same false positive under a monochrome numeric-literal theme;
        # see _ins_spans_are_bare_numerals.
        if non_context == {"ins"} and (
                _section_has_foreign_chromatic(sec)
                or _ins_spans_are_bare_numerals(
                    [s for s in wording_spans if s.wording_role == "ins"])):
            continue
        if non_context == {"ins"}:
            sec.kind = SectionKind.WORDING_ADD
        elif non_context == {"del"}:
            sec.kind = SectionKind.WORDING_REMOVE
        elif non_context:
            sec.kind = SectionKind.WORDING
        elif "context" in roles:
            sec.kind = SectionKind.WORDING
    return sections


_WORDING_KINDS = frozenset({
    SectionKind.WORDING,
    SectionKind.WORDING_ADD,
    SectionKind.WORDING_REMOVE,
})


_COALESCE_MAX_LINES = 4

_COALESCE_CODE_RE = re.compile(
    r"^\s*[{}]|"               # standalone brace lines
    r"^\s*namespace\s+\w|"     # namespace declarations
    r"^\s*\.\.\.|"             # ellipsis lines
    r"#include\s*<|"           # preprocessor includes
    r"#define\s+\w|"           # preprocessor defines
    r"\w+\s*\([^)]*\)\s*\{|"  # function_name(...) {
    r"\w+\s*\([^)]*\)\s*;|"   # declaration: name(...);
    r"^\s*static_assert\s*\(|"
    r"^\s*constexpr\b|"
    r"^\s*//[^/]",
    re.MULTILINE,
)


def _coalesce_code_paragraphs(sections: list[Section]) -> list[Section]:
    """Merge adjacent short, code-like PARAGRAPH sections before rescue.

    Multi-line code examples often get split into separate one- or
    two-line paragraphs by the block breaker.  Individually, each
    paragraph falls below _RESCUE_MIN_CODE_LINES and is never rescued.
    This pass scans for runs of consecutive short PARAGRAPH sections
    (at most _COALESCE_MAX_LINES each) where every section matches a
    strict code regex, and merges those runs into a single PARAGRAPH
    whose combined line count is high enough for the rescue pass to
    promote.

    Uses _COALESCE_CODE_RE (excludes trailing-semicolon pattern) to
    avoid merging prose paragraphs whose lines happen to end with ";".
    """
    result: list[Section] = []
    i = 0
    while i < len(sections):
        sec = sections[i]
        lines = sec.text.splitlines()
        if (sec.kind not in (SectionKind.PARAGRAPH, SectionKind.UNCERTAIN)
                or len(lines) > _COALESCE_MAX_LINES
                or not _COALESCE_CODE_RE.search(sec.text)):
            result.append(sec)
            i += 1
            continue
        run = [sec]
        j = i + 1
        while j < len(sections):
            nxt = sections[j]
            nxt_lines = nxt.text.splitlines()
            if (nxt.kind not in (SectionKind.PARAGRAPH, SectionKind.UNCERTAIN)
                    or len(nxt_lines) > _COALESCE_MAX_LINES
                    or not _COALESCE_CODE_RE.search(nxt.text)):
                break
            run.append(nxt)
            j += 1
        if len(run) >= 2:
            merged_text = "\n".join(s.text for s in run)
            # Merge lines alongside text: emit renders CODE from sec.lines,
            # so dropping run[1:] lines here silently loses content (the
            # rescue pass promotes on the full merged_text, but the fence
            # then renders only run[0]'s lines). Keep text and lines in sync.
            merged_lines: list[Line] = []
            for s in run:
                merged_lines.extend(s.lines)
            merged = replace(run[0], text=merged_text, lines=merged_lines)
            result.append(merged)
            _log.info("Coalesced %d code-like paragraphs (%d chars)",
                       len(run), len(merged_text))
        else:
            result.append(sec)
        i = j
    return result


def _absorb_code_orphans(sections: list[Section]) -> list[Section]:
    """Absorb monospace-only first lines from PARAGRAPHs into preceding CODE.

    When a PDF code block is split across MuPDF blocks, the trailing
    fragment (e.g. ``});``) becomes a separate PARAGRAPH whose first
    line(s) are purely monospace. This pass detects that pattern and
    moves monospace-only leading lines back into the preceding CODE
    section, leaving any remaining non-monospace lines as the paragraph.
    """
    result: list[Section] = []
    for sec in sections:
        if (result
                and result[-1].kind == SectionKind.CODE
                and sec.kind == SectionKind.PARAGRAPH
                and sec.page_num == result[-1].page_num
                and sec.lines):
            # Find leading monospace lines.
            mono_lines: list[Line] = []
            rest_lines: list[Line] = []
            found_non_mono = False
            for ln in sec.lines:
                if found_non_mono:
                    rest_lines.append(ln)
                elif ln.is_monospace:
                    mono_lines.append(ln)
                else:
                    found_non_mono = True
                    rest_lines.append(ln)

            if mono_lines:
                prev = result[-1]
                mono_text = "\n".join(
                    "".join(s.text for s in ln.spans) for ln in mono_lines
                )
                result[-1] = replace(
                    prev,
                    text=prev.text + "\n" + mono_text,
                    lines=prev.lines + mono_lines,
                )
                if rest_lines:
                    rest_text = "\n".join(
                        "".join(s.text for s in ln.spans) for ln in rest_lines
                    )
                    result.append(replace(sec, text=rest_text, lines=rest_lines))
                _log.info("Absorbed %d mono orphan line(s) into code block",
                          len(mono_lines))
                continue
        result.append(sec)
    return result


def _rescue_unfenced_code(sections: list[Section]) -> list[Section]:
    """Content-based rescue pass: promote paragraph sections to CODE.

    Runs AFTER _classify_wording_sections so wording-classified sections
    are skipped. Scans lines within each section (not across sections)
    and refuses to promote when any line terminates a natural-language
    section when they lack terminal punctuation in TERMINAL_PUNCTUATION.

    A section is promoted when _RESCUE_MIN_CODE_LINES or more of its
    lines match _STRUCTURAL_CODE_RE.
    """
    for sec in sections:
        if sec.kind in _WORDING_KINDS:
            continue
        if sec.kind != SectionKind.PARAGRAPH:
            continue
        text = sec.text
        lines = text.splitlines()
        code_count = sum(1 for ln in lines if _STRUCTURAL_CODE_RE.search(ln))
        if code_count >= _RESCUE_MIN_CODE_LINES:
            sec.kind = SectionKind.CODE
            sec.fence_lang = DEFAULT_FENCE_LANG
            sec.confidence = Confidence.MEDIUM
            _log.info("Rescued unfenced code section (%d lines): %r",
                      len(lines), text[:40])
    return sections


_SPLIT_MIN_CODE_RUN = 2


def _split_embedded_code(sections: list[Section]) -> list[Section]:
    """Extract an embedded run of monospace code lines from a PARAGRAPH.

    _merge_paragraphs glues a code block into the surrounding prose when
    the code lines lack terminal punctuation (they end in ``{``, ``;``,
    ``}``) and the following prose starts lowercase. The merged section is
    mostly prose, so _rescue_unfenced_code (which promotes a section
    wholesale) leaves it as prose and the code collapses onto one line.

    This pass runs AFTER _classify_wording_sections and
    _rescue_unfenced_code, so it only sees plain PARAGRAPH sections:
    wording sections keep their own grouping, and a comment-above-code
    listing that rescue already promoted to CODE is left intact. Within a
    PARAGRAPH it splits a maximal run of _SPLIT_MIN_CODE_RUN or more
    consecutive all-monospace, code-shaped lines into its own CODE
    section, leaving the surrounding prose as PARAGRAPH sections.

    A PARAGRAPH that survives _detect_code_blocks is never all-monospace,
    so any monospace run it contains is genuinely embedded code.
    """
    result: list[Section] = []
    for sec in sections:
        if sec.kind != SectionKind.PARAGRAPH or len(sec.lines) < _SPLIT_MIN_CODE_RUN:
            result.append(sec)
            continue

        is_code = [
            _line_is_monospace(ln) and bool(ln.text.strip())
            for ln in sec.lines
        ]
        if not any(is_code):
            result.append(sec)
            continue

        # Partition into alternating prose / code-run segments.
        segments: list[tuple[bool, list]] = []
        for code_flag, line in zip(is_code, sec.lines):
            if segments and segments[-1][0] == code_flag:
                segments[-1][1].append(line)
            else:
                segments.append((code_flag, [line]))

        code_idx = {
            i for i, (flag, seg) in enumerate(segments)
            if flag and len(seg) >= _SPLIT_MIN_CODE_RUN
            and _STRUCTURAL_CODE_RE.search("\n".join(ln.text for ln in seg))
        }
        if not code_idx:
            result.append(sec)
            continue

        for i, (flag, seg_lines) in enumerate(segments):
            is_split_code = i in code_idx
            seg_text = "\n".join(ln.text for ln in seg_lines)
            if not seg_text.strip():
                continue
            if is_split_code:
                result.append(Section(
                    kind=SectionKind.CODE,
                    text=seg_text,
                    confidence=Confidence.MEDIUM,
                    lines=list(seg_lines),
                    page_num=sec.page_num,
                    fence_lang=DEFAULT_FENCE_LANG,
                ))
            else:
                result.append(replace(
                    sec, text=seg_text, lines=list(seg_lines),
                ))
    return result


def _merge_adjacent_code_blocks(sections: list[Section]) -> list[Section]:
    """Merge consecutive CODE sections into a single CODE section.

    When adjacent blocks are classified as CODE (e.g. across page breaks,
    or after rescue/splitting passes promote adjacent fragments),
    they represent one continuous source listing and must be emitted
    in a single fenced block.
    """
    if len(sections) < 2:
        return sections
    result: list[Section] = []
    for sec in sections:
        if (result
                and result[-1].kind == SectionKind.CODE
                and sec.kind == SectionKind.CODE
                and (sec.fence_lang == result[-1].fence_lang
                     or not sec.fence_lang
                     or not result[-1].fence_lang)):
            prev = result[-1]
            merged_text = prev.text + "\n" + sec.text
            merged_lines = prev.lines + sec.lines
            lang = prev.fence_lang or sec.fence_lang or DEFAULT_FENCE_LANG
            result[-1] = replace(
                prev,
                text=merged_text,
                lines=merged_lines,
                fence_lang=lang,
            )
            _log.info("Merged adjacent code blocks (%d lines)", len(merged_lines))
        else:
            result.append(sec)
    return result


def _line_is_mono_code(line: Line) -> bool:
    """True if a line is monospace code, optionally with a trailing
    proportional ``//`` comment.

    Handles the mixed-font shape MuPDF produces for pseudo-code with inline
    comments: a monospace span holding the code and the ``//`` marker,
    followed by a proportional span holding the comment text (e.g.
    ``c1: b = new atomic<int>(0);    // gets the same location``). A
    pure-monospace line is also code.

    A line whose leading ``//`` is a comment marker with no code before it
    (a section-reference comment like ``// [c.math.abs]``) or a URI scheme
    separator (``https://``, ``file://``) is NOT code: returning True there
    would pull prose and links into a code fence. ``_STRUCTURAL_CODE_RE``
    and ``_CODE_COMMENT_RE`` make the same URL distinction.
    """
    content = [s for s in line.spans if s.text.strip()]
    if not content:
        return False
    if not content[0].monospace:
        return False
    if all(s.monospace for s in content):
        return True
    # Mixed font: accept only "<monospace code> // <proportional comment>".
    first_nonmono = next(
        i for i, s in enumerate(content) if not s.monospace
    )
    mono_prefix = "".join(s.text for s in content[:first_nonmono])
    if "//" not in mono_prefix:
        return False
    code_before_comment = mono_prefix.split("//", 1)[0].rstrip()
    # Empty: the line starts with the comment marker (prose / section ref).
    # Trailing ":" : the "//" is a URI scheme separator, not a C++ comment.
    if not code_before_comment or code_before_comment.endswith(":"):
        return False
    # The comment must not resume into monospace code.
    if any(s.monospace for s in content[first_nonmono:]):
        return False
    return True


def _absorb_mono_code_orphans(sections: list[Section]) -> list[Section]:
    """Absorb leading mixed-font code lines into a preceding CODE block.

    Sibling of _absorb_code_orphans, but recognises the mixed-font
    ``code // comment`` shape that _absorb_code_orphans (which requires a
    purely monospace line) and _split_embedded_code (which tests
    _line_is_monospace) both miss. When a pseudo-code listing is split
    across MuPDF blocks (e.g. P3181R1 "Reallocating thread C:" followed by
    ``c1:`` / ``c2:`` lines carrying proportional comments), the trailing
    code lines land in a following PARAGRAPH and render as broken inline
    markdown. This pass moves the leading run of such lines back into the
    preceding CODE section.

    Runs LAST (after _split_embedded_code) so the preceding section is
    already classified CODE. Text is rebuilt from each line's text and
    prev.lines is extended in lockstep, keeping Section.text and
    Section.lines in sync (the emitter renders CODE from .lines).
    """
    result: list[Section] = []
    for sec in sections:
        if (result
                and result[-1].kind == SectionKind.CODE
                and sec.kind == SectionKind.PARAGRAPH
                and sec.page_num == result[-1].page_num
                and sec.lines):
            # Maximal leading run of (mono-code or blank) lines, requiring at
            # least one real code line, then trailing blanks trimmed so a
            # blank separating the code from following prose stays with the
            # prose paragraph rather than padding the fence.
            run_len = 0
            saw_code = False
            for ln in sec.lines:
                if _line_is_mono_code(ln):
                    run_len += 1
                    saw_code = True
                elif not ln.text.strip():
                    run_len += 1
                else:
                    break
            while run_len > 0 and not sec.lines[run_len - 1].text.strip():
                run_len -= 1

            if saw_code and run_len > 0:
                absorbed = sec.lines[:run_len]
                rest_lines = sec.lines[run_len:]
                prev = result[-1]
                absorbed_text = "\n".join(ln.text for ln in absorbed)
                result[-1] = replace(
                    prev,
                    text=prev.text + "\n" + absorbed_text,
                    lines=prev.lines + absorbed,
                )
                if rest_lines:
                    rest_text = "\n".join(ln.text for ln in rest_lines)
                    result.append(replace(sec, text=rest_text, lines=rest_lines))
                _log.info("Absorbed %d mixed-font code line(s) into code block",
                          len(absorbed))
                continue
        result.append(sec)
    return result


def _label_first_word(line: Line) -> str:
    """Lowercased first whitespace-delimited token of *line*, '' if blank."""
    parts = line.text.strip().split()
    return parts[0].lower() if parts else ""


def _absorb_trailing_label_into_code(sections: list[Section]) -> list[Section]:
    """Move a trailing pseudo-code listing label out of a PARAGRAPH into the
    head of the CODE block it introduces.

    A labeled listing ("Thread A:" / "Thread B:" / "Reallocating thread C:")
    can have its FIRST label wrap onto the tail of the preceding prose
    paragraph (P3181R1 "Detailed example": "...implementation issues. Thread
    A:" sits in the paragraph, while "Thread B:" and the code live in the next
    CODE section). The label then renders as prose instead of heading the
    fence.

    The move is gated hard so a prose sentence whose last word merely ends in a
    colon is never torn off:

    - the trailing line must classify as a label (_classify_code_line);
    - it must carry no citation bracket ('[') (rules out editing instructions
      like "Modify [dcl.contract.func] as follows:");
    - its first word must match the first word of a label ALREADY inside the
      CODE block (same listing series: "Thread A:" -> "Thread B:"). A prose
      tail ("...populated object:") shares no first word with a code label and
      stays in the prose.

    Sibling of _absorb_mono_code_orphans: rebuilds text/lines in lockstep so
    Section.text and Section.lines stay in sync. Runs before
    _trim_narrative_from_code so the moved label is seen as code.
    """
    result = list(sections)
    i = 0
    while i < len(result) - 1:
        para, code = result[i], result[i + 1]
        if (para.kind == SectionKind.PARAGRAPH
                and code.kind == SectionKind.CODE
                and para.page_num == code.page_num
                and para.lines and code.lines):
            j = len(para.lines)
            while j > 0 and not para.lines[j - 1].text.strip():
                j -= 1
            last = para.lines[j - 1] if j > 0 else None
            if (last is not None
                    and _classify_code_line(last) == "label"
                    and "[" not in last.text
                    and any(ln.text.strip() for ln in para.lines[:j - 1])):
                first = _label_first_word(last)
                code_label_words = {
                    _label_first_word(ln) for ln in code.lines
                    if _classify_code_line(ln) == "label"
                }
                head = next((ln for ln in code.lines if ln.text.strip()), None)
                # Skip when the code block already opens with this exact label
                # (no duplicate head) or opens with narrative (the moved label
                # would inherit a narrative forward neighbour in
                # _trim_narrative_from_code and be peeled straight back out,
                # orphaning it in its own paragraph).
                head_ok = (head is not None
                           and head.text.strip() != last.text.strip()
                           and _classify_code_line(head) != "narrative")
                if first and first in code_label_words and head_ok:
                    moved = para.lines[j - 1:]
                    kept = para.lines[:j - 1]
                    result[i] = replace(
                        para, lines=kept,
                        text="\n".join(ln.text for ln in kept),
                    )
                    merged = moved + code.lines
                    result[i + 1] = replace(
                        code, lines=merged,
                        text="\n".join(ln.text for ln in merged),
                    )
                    _log.info("Moved trailing label %r into following code "
                              "block on page %d", last.text.strip(),
                              code.page_num)
        i += 1
    return result


# Anti-narrative trim: characters that count as code symbols when measuring
# a line's symbol density. Prose carries few of these; code lines (calls,
# declarations, operators, terminators) are dense in them.
_NARRATIVE_CODE_SYMBOLS = frozenset("{}()[];=<>+-*/&|%!~^.,:#")

# A line is narrative (prose wrongly trapped in a fence) when it is NOT
# monospace, carries few code symbols, is mostly alphabetic words, and is
# long enough to be a sentence fragment rather than a short code statement.
_NARRATIVE_MAX_SYMBOL_DENSITY = 0.07
_NARRATIVE_MIN_ALPHA_RATIO = 0.55
_NARRATIVE_MIN_WORDS = 6

# A line is unambiguously code when it is monospace, dense in code symbols,
# or sparse in alphabetic words. These short-circuit the narrative test so a
# dense one-liner (``foo(x);``) is never mistaken for prose.
_CODE_MIN_SYMBOL_DENSITY = 0.10
_CODE_MAX_ALPHA_RATIO = 0.40

# A trailing ``label:`` shorter than this is a structural pseudo-code label
# (``Thread A:``, ``c1:``), kept with the surrounding code, never narrative.
_LABEL_MAX_WORDS = 4

# A wrapped sentence tail (``value;``, ``slate concept.``) absorbed into a
# preceding narrative run: short, alphabetic after stripping trailing prose
# punctuation, and not symbol-dense once that punctuation is removed.
_CONTINUATION_MAX_WORDS = 5
_CONTINUATION_MIN_ALPHA_RATIO = 0.55
_CONTINUATION_MAX_SYMBOL_DENSITY = 0.10
_CONTINUATION_TRAILING_PUNCT = ";:.,"


def _line_alpha_ratio(words: list[str]) -> float:
    """Fraction of *words* that are purely alphabetic after stripping quotes,
    parentheses, and hyphens. Higher = more prose-like."""
    if not words:
        return 0.0
    alpha = [w for w in words if w.strip("'\"`()").replace("-", "").isalpha()]
    return len(alpha) / len(words)


def _line_symbol_density(
    text: str, symbols: frozenset[str] = _NARRATIVE_CODE_SYMBOLS
) -> float:
    """Fraction of characters in *text* that are *symbols* (default: code
    symbols). Higher = more code-like. Returns 0.0 for empty text."""
    if not text:
        return 0.0
    return sum(1 for c in text if c in symbols) / len(text)


def _classify_code_line(line: Line) -> str:
    """Classify a line inside a CODE section as code/narrative/label/blank.

    The discriminator is symbol density and alphabetic-word ratio, NOT font:
    proportional-font code (e.g. P4174R0) is still code by its dense symbols,
    and a monospace-styled sentence is still prose by its sparse symbols. A
    leading ``//`` is always a comment (code); a short trailing-colon line is
    a structural label kept with the code.
    """
    s = line.text.strip()
    if not s:
        return "blank"
    if s.startswith("//"):
        return "code"
    words = s.split()
    if len(words) <= _LABEL_MAX_WORDS and s.endswith(":"):
        return "label"
    if _line_is_monospace(line):
        return "code"
    sd = _line_symbol_density(s)
    if sd >= _CODE_MIN_SYMBOL_DENSITY:
        return "code"
    ar = _line_alpha_ratio(words)
    if ar <= _CODE_MAX_ALPHA_RATIO:
        return "code"
    if (len(words) >= _NARRATIVE_MIN_WORDS
            and ar >= _NARRATIVE_MIN_ALPHA_RATIO
            and sd <= _NARRATIVE_MAX_SYMBOL_DENSITY):
        return "narrative"
    return "code"


def _is_narrative_continuation(line: Line) -> bool:
    """True if *line* is a short wrapped prose tail of a preceding narrative
    line (``value;`` after ``... optional initial``).

    Trailing prose punctuation is stripped before measuring so a tail whose
    only symbol is a terminator is absorbed, while a genuine code tail
    (``});``, ``i++;``) stays code: its core is not alphabetic and its symbol
    density stays high.
    """
    s = line.text.strip()
    if not s or s.startswith("//"):
        return False
    if _line_is_monospace(line):
        return False
    core = s.rstrip(_CONTINUATION_TRAILING_PUNCT).strip()
    words = core.split()
    if not words or len(words) > _CONTINUATION_MAX_WORDS:
        return False
    return (_line_alpha_ratio(words) >= _CONTINUATION_MIN_ALPHA_RATIO
            and _line_symbol_density(core) < _CONTINUATION_MAX_SYMBOL_DENSITY)


def _neighbour_narr(kinds: list[str], is_narr: list[bool],
                    i: int, step: int, skip: tuple[str, ...]) -> bool | None:
    """is_narr of the nearest line from index *i* in direction *step* (+1/-1)
    whose kind is not in *skip*; None if none exists in that direction."""
    j = i + step
    while 0 <= j < len(kinds):
        if kinds[j] not in skip:
            return is_narr[j]
        j += step
    return None


def _trim_narrative_from_code(sections: list[Section]) -> list[Section]:
    """Split prose lines out of CODE sections into PARAGRAPH sections.

    Earlier passes (_rescue_unfenced_code wholesale promotion, dual-path
    merges) can fence whole regions of mixed prose and code, leaving narrative
    sentences trapped inside a ``` fence (P3181R1, and the P4174R0 golden
    itself). This pass re-segments each CODE section line by line: narrative
    runs become PARAGRAPH, code runs stay CODE.

    Three rules keep code intact while removing only genuine prose:

    - A line is narrative only by its own typography-independent signals
      (sparse code symbols, mostly alphabetic words); monospace and
      symbol-dense lines are always code.
    - A short wrapped sentence tail rejoins its narrative run
      (_is_narrative_continuation).
    - A single narrative line fully surrounded by code is kept as code
      (cohesion guard): one wrapped comment or wording-bolded list item must
      not fragment a contiguous code block. Only edge runs and interior runs
      of two or more content lines are trimmed.

    Runs LAST in the structure pipeline so all code detection has settled.
    """
    result: list[Section] = []
    for sec in sections:
        if sec.kind != SectionKind.CODE or not sec.lines:
            result.append(sec)
            continue

        kinds = [_classify_code_line(ln) for ln in sec.lines]
        is_narr = [k == "narrative" for k in kinds]

        # Resolve labels first, then blanks. A label introduces what FOLLOWS
        # it, so it inherits its forward neighbour ("Thread A:" above code
        # stays code; a prose connector "For example:" above prose joins the
        # prose, else it emits as a lone label-only fence). Blanks resolve in
        # a SECOND pass so a blank sees the label's already-resolved side: the
        # blank line separating "Thread A:" from "a1: ..." must take the code
        # side, not skip past the label to unrelated prose above and orphan
        # the label in its own fence. Both default to code when isolated.
        for i, k in enumerate(kinds):
            if k != "label":
                continue
            fwd = _neighbour_narr(kinds, is_narr, i, 1, ("blank", "label"))
            back = _neighbour_narr(kinds, is_narr, i, -1, ("blank", "label"))
            is_narr[i] = bool(fwd if fwd is not None else back)
        for i, k in enumerate(kinds):
            if k != "blank":
                continue
            back = _neighbour_narr(kinds, is_narr, i, -1, ("blank",))
            fwd = _neighbour_narr(kinds, is_narr, i, 1, ("blank",))
            is_narr[i] = bool(back if back is not None else fwd)

        # Absorb short wrapped tails into a preceding narrative run.
        for i in range(1, len(sec.lines)):
            if (not is_narr[i] and is_narr[i - 1] and kinds[i] == "code"
                    and _is_narrative_continuation(sec.lines[i])):
                is_narr[i] = True

        # Cohesion guard: keep single interior narrative lines as code.
        # `groups` is a static snapshot; the guard below mutates is_narr while
        # reading boundaries from it. Safe only because the guard flips
        # narrative->code exclusively and `_is_code_group` keys on the
        # original flag, so a reverted group never invents a new code boundary.
        # If a future edit flips code->narrative here, recompute groups first.
        groups: list[tuple[bool, list[int]]] = []
        for idx, flag in enumerate(is_narr):
            if groups and groups[-1][0] == flag:
                groups[-1][1].append(idx)
            else:
                groups.append((flag, [idx]))

        def _is_code_group(g: tuple[bool, list[int]]) -> bool:
            return (not g[0]) and any(sec.lines[k].text.strip() for k in g[1])

        for gi, (flag, idxs) in enumerate(groups):
            if not flag:
                continue
            content = sum(1 for k in idxs if sec.lines[k].text.strip())
            before = any(_is_code_group(groups[j]) for j in range(gi))
            after = any(_is_code_group(groups[j]) for j in range(gi + 1, len(groups)))
            if content == 1 and before and after:
                for k in idxs:
                    is_narr[k] = False

        if not any(is_narr):
            result.append(sec)
            continue

        # Emit alternating code / narrative segments in order.
        segments: list[tuple[bool, list[Line]]] = []
        for flag, ln in zip(is_narr, sec.lines):
            if segments and segments[-1][0] == flag:
                segments[-1][1].append(ln)
            else:
                segments.append((flag, [ln]))

        split_count = 0
        for flag, seg in segments:
            if not any(ln.text.strip() for ln in seg):
                continue
            seg_text = "\n".join(ln.text for ln in seg).strip("\n")
            if flag:
                result.append(Section(
                    kind=SectionKind.PARAGRAPH,
                    text=seg_text,
                    confidence=sec.confidence,
                    lines=list(seg),
                    page_num=sec.page_num,
                ))
                split_count += 1
            else:
                result.append(replace(sec, text=seg_text, lines=list(seg)))
        if split_count:
            _log.info("Trimmed %d narrative run(s) out of a code block on page %d",
                      split_count, sec.page_num)
    return result


# Trailing-prose peel: a citation reference ("[intro.races]p16") is prose, not
# code, so it is removed before measuring a tail line. Structural symbols are
# the code-symbol set minus prose punctuation ('-', '.', ',', ':'), so they
# still mark real code while sentence punctuation does not.
_CITATION_RE = re.compile(r"\[[\w.\-:]+\]\w*")
_PEEL_STRUCT_SYMBOLS = _NARRATIVE_CODE_SYMBOLS - frozenset("-.,:")
# A tail line is prose only if it is sentence-like: enough words, mostly
# alphabetic after stripping prose punctuation, and sparse in structural code
# symbols once citations are removed.
_PEEL_MIN_WORDS = 6
_PEEL_MIN_ALPHA_RATIO = 0.60
_PEEL_MAX_STRUCT_DENSITY = 0.06
# A line ending in one of these is a code statement/brace: a hard stop that
# bounds the peel and protects wrapped code (e.g. a P4174R0 type-list line
# "unsigned long, unsigned long long>;") from being pulled into prose.
_PEEL_CODE_TERMINATORS = (";", "{", "}")


def _is_tail_prose(line: Line) -> bool:
    """True if *line* is a sentence-like prose tail that can be peeled off the
    end of a CODE block (the P3181R1 "If c2 follows ... since b1" tail).

    Conservative by construction: monospace lines, comments, code statements
    ending in ``;{}``, short lines, identifier-heavy lines, and
    symbol-dense lines are all rejected, so only genuine wrapped prose at a
    block's tail qualifies.
    """
    s = line.text.strip()
    if not s or s.startswith("//") or _line_is_monospace(line):
        return False
    if s.endswith(_PEEL_CODE_TERMINATORS):
        return False
    body = _CITATION_RE.sub("", s)
    words = body.split()
    if len(words) < _PEEL_MIN_WORDS:
        return False
    alpha = sum(
        1 for w in words
        if w.strip("'\"`()").strip(_CONTINUATION_TRAILING_PUNCT)
        .replace("-", "").isalpha()
    )
    if alpha / len(words) < _PEEL_MIN_ALPHA_RATIO:
        return False
    return _line_symbol_density(body, _PEEL_STRUCT_SYMBOLS) <= _PEEL_MAX_STRUCT_DENSITY


def _peel_trailing_prose_from_code(sections: list[Section]) -> list[Section]:
    """Split a trailing run of prose lines off the end of a CODE section.

    _trim_narrative_from_code segments interior narrative but keeps lines its
    classifier reads as code. A wrapped prose sentence carrying identifiers and
    a citation ("If c2 follows a1 ... by [intro.races]p16, ... since b1") scores
    as code there, so the tail of P3181R1's "Stronger semantics" listing stays
    fenced and its sentence fragments across the closing ```. This pass walks
    the tail of each CODE block over blank and _is_tail_prose lines, stopping at
    the first real code line, and emits the collected run as a PARAGRAPH.

    Operating only on the tail, behind a ``;{}``/monospace hard stop, keeps
    interior wrapped code (type-lists, multi-line calls) untouched. Runs after
    _trim_narrative_from_code.
    """
    result: list[Section] = []
    for sec in sections:
        if sec.kind != SectionKind.CODE or len(sec.lines) < 2:
            result.append(sec)
            continue
        split = len(sec.lines)
        saw_prose = False
        while split > 0:
            ln = sec.lines[split - 1]
            if not ln.text.strip():
                split -= 1
                continue
            if _is_tail_prose(ln):
                saw_prose = True
                split -= 1
                continue
            break
        code_lines = sec.lines[:split]
        prose_lines = sec.lines[split:]
        if (not saw_prose
                or not any(ln.text.strip() for ln in code_lines)
                or not any(ln.text.strip() for ln in prose_lines)):
            result.append(sec)
            continue
        while code_lines and not code_lines[-1].text.strip():
            code_lines.pop()
        while prose_lines and not prose_lines[0].text.strip():
            prose_lines.pop(0)
        result.append(replace(
            sec, lines=code_lines,
            text="\n".join(ln.text for ln in code_lines),
        ))
        result.append(Section(
            kind=SectionKind.PARAGRAPH,
            text="\n".join(ln.text for ln in prose_lines).strip("\n"),
            confidence=sec.confidence,
            lines=prose_lines,
            page_num=sec.page_num,
        ))
        _log.info("Peeled %d trailing prose line(s) off a code block on page %d",
                  len(prose_lines), sec.page_num)
    return result


_PARAGRAPH_NUM_MIN_REPEATS = 3


def _demote_repeated_low_confidence_numbers(sections: list[Section]) -> None:
    """Demote LOW-confidence numbered headings when their section_num
    repeats often enough to indicate paragraph numbering.

    Real section numbers are unique, but many papers duplicate each one
    between a TOC and the body (count 2), and a real section that ends up
    at LOW confidence can also collide with paragraph numbering elsewhere.
    Paragraph numbering resets per clause ("1 Constraints:", "2 Mandates:",
    then later "1 Preconditions:", ...) so the same number typically shows
    up 5 or more times. Requiring count >= 3 keeps TOC/body pairs and
    section/paragraph 1-on-1 collisions intact while catching the
    paragraph-numbering pattern.

    Only LOW-confidence headings are considered, so a real section title
    with font-size or bold confirmation is preserved regardless.
    """
    counts: Counter[str] = Counter()
    nums_by_index: dict[int, str] = {}
    for i, sec in enumerate(sections):
        if (sec.kind != SectionKind.HEADING
                or sec.confidence != Confidence.LOW):
            continue
        first_line = sec.text.split("\n")[0].strip()
        m = SECTION_NUM_RE.match(first_line)
        if not m:
            continue
        num = m.group(1)
        nums_by_index[i] = num
        counts[num] += 1

    repeated = {num for num, c in counts.items()
                if c >= _PARAGRAPH_NUM_MIN_REPEATS}
    if not repeated:
        return

    for i, num in nums_by_index.items():
        if num in repeated:
            sec = sections[i]
            _log.info("Demote repeated low-conf number %r: %r",
                       num, sec.text[:40])
            sec.kind = SectionKind.PARAGRAPH
            sec.heading_level = 0


_SIBLING_FONT_TOL = 0.1


def _validate_nesting(sections: list[Section]) -> int:
    """Ensure heading levels don't skip more than one level deeper.

    Mutates headings that skip levels: adjusts heading_level and
    downgrades confidence from HIGH to MEDIUM when corrected.

    Also consolidates runs of same-styled headings as siblings. When
    consecutive headings share a font size, they're at the same logical
    level; without this check, a run of similar entries (e.g. a dozen
    "Changes since P0876RN" items) would each get prev_clamped + 1,
    cascading to ever-deeper levels.

    Returns the number of corrections applied.
    """
    prev_level = 0
    prev_font_size: float | None = None
    prev_numbered = False
    corrections = 0
    for sec in sections:
        if sec.kind != SectionKind.HEADING:
            continue
        is_sibling = (
            prev_font_size is not None
            and abs(sec.font_size - prev_font_size) <= _SIBLING_FONT_TOL
        )
        is_numbered = _heading_is_numbered(sec)
        if (is_sibling and prev_level > 0 and sec.heading_level > prev_level
                and not is_numbered):
            # Numbered headings are exempt: their level comes from the
            # section-number depth, which is authoritative. WG21 papers
            # render a subsection ("3.2.1") at the same font size as its
            # parent ("3.2"), so the shared-font sibling heuristic would
            # otherwise clamp the deeper numbered heading up a level
            # (H4 -> H3), collapsing the numbering hierarchy. This mirrors
            # the numbered-exempt guard on the inversion clamp below.
            _log.info("Nesting sibling: h%d -> h%d for %r",
                       sec.heading_level, prev_level, sec.text[:40])
            sec.heading_level = prev_level
            if sec.confidence == Confidence.HIGH:
                sec.confidence = Confidence.MEDIUM
            corrections += 1
        elif (prev_level > 0
              and sec.heading_level > prev_level
              and prev_font_size is not None
              and sec.font_size > prev_font_size + _SIBLING_FONT_TOL
              and not is_numbered and not prev_numbered):
            # Inverted nesting: a larger-font (more prominent) heading must
            # not render deeper than the smaller-font heading before it.
            # Font-rank pollution (e.g. the document title inflating the
            # size ranking) can demote a genuine top-level heading below a
            # known section pinned to ##. Clamp it back to its predecessor's
            # level. Numbered headings are exempt: their level comes from
            # section numbering, not font.
            _log.info("Nesting inversion: h%d -> h%d for %r",
                       sec.heading_level, prev_level, sec.text[:40])
            sec.heading_level = prev_level
            if sec.confidence == Confidence.HIGH:
                sec.confidence = Confidence.MEDIUM
            corrections += 1
        elif prev_level > 0 and sec.heading_level > prev_level + 1:
            corrected = prev_level + 1
            _log.info("Nesting fix: h%d -> h%d for %r",
                       sec.heading_level, corrected,
                       sec.text[:40])
            sec.heading_level = corrected
            if sec.confidence == Confidence.HIGH:
                sec.confidence = Confidence.MEDIUM
            corrections += 1
        prev_level = sec.heading_level
        prev_font_size = sec.font_size
        prev_numbered = is_numbered
    return corrections
