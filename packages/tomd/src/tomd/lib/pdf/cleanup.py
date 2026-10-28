"""Header/footer detection and text cleanup for PDF extraction."""

import fitz
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, replace

from .. import strip_format_chars, DOC_NUM_RE
from .types import (
    Block, Line, PageEdgeItem,
    Y_TOLERANCE, REPEATING_THRESHOLD, EDGE_ITEMS_PER_PAGE,
    RUNNING_FOOTER_MAX_WORDS, EDGE_BAND_BOTTOM_FRACTION,
    TERMINAL_PUNCTUATION,
    PAGE_NUM_RE, COMPOUND_PREFIXES,
)
from .wg21 import _LABEL_RE as _WG21_LABEL_RE

_log = logging.getLogger(__name__)

_EDGE_BLOCK_MAX_HEIGHT = 30.0
_EDGE_BLOCK_TOP_MAX_Y = 60.0
_EDGE_BLOCK_BOTTOM_MIN_Y = 700.0

# A text "recurs" once it appears at the same edge y-position on at least this
# many distinct pages. Floor for the alternating-header coverage-union branch.
_MIN_RECUR_PAGES = 2
# Max distinct texts an alternating running header may have (title on recto,
# authors on verso = 2). Bounds the coverage-union branch so it cannot fire on
# many-variant edge recurrence (slide-title sets, recurring code-line clusters).
_MAX_HEADER_VARIANTS = 2


def _is_edge_block(block: Block) -> bool:
    """Whether a block is a small assembly hugging the top or bottom page edge.

    Header/footer chrome sits in short blocks at the page margins; body text
    flows in tall blocks spanning the text column. The footer-band strip and
    the co-location strip both use this to avoid touching body content.
    """
    blk_height = block.bbox[3] - block.bbox[1]
    blk_top = block.bbox[1]
    return (blk_height < _EDGE_BLOCK_MAX_HEIGHT
            and (blk_top < _EDGE_BLOCK_TOP_MAX_Y
                 or blk_top > _EDGE_BLOCK_BOTTOM_MIN_Y))


def _y_bucket(bbox: tuple[float, float, float, float]) -> float:
    """Quantize a bbox's vertical center to the Y_TOLERANCE grid."""
    y_center = (bbox[1] + bbox[3]) / 2.0
    return round(y_center / Y_TOLERANCE) * Y_TOLERANCE


def get_edge_items(blocks: list[Block], page_num: int) -> list[PageEdgeItem]:
    """Get the top N and bottom N text items from a page by y-coordinate.

    Deduplicates by (text, rounded y-position) to avoid counting the
    same visual item twice when blocks overlap edge regions.
    """
    _COLUMNAR_X_GAP = 50.0

    items = []
    for block in blocks:
        # Skip columnar blocks: 2+ lines at widely separated x-positions
        # are table column headers, not repeating page headers/footers.
        if len(block.lines) >= 2:
            x0s = [ln.bbox[0] for ln in block.lines if ln.text.strip()]
            if x0s and max(x0s) - min(x0s) > _COLUMNAR_X_GAP:
                continue
        for line in block.lines:
            text = line.text.strip()
            if not text:
                continue
            y_center = (line.bbox[1] + line.bbox[3]) / 2.0
            items.append(PageEdgeItem(
                text=text,
                y=y_center,
                page_num=page_num,
                bbox=line.bbox,
            ))

    if not items:
        return []

    items.sort(key=lambda it: it.y)
    top = items[:EDGE_ITEMS_PER_PAGE]
    bottom = items[-EDGE_ITEMS_PER_PAGE:]
    seen = set()
    result = []
    for it in top + bottom:
        key = (it.text, round(it.y, 1))
        if key not in seen:
            seen.add(key)
            result.append(it)
    return result


def detect_repeating(all_edge_items: list[list[PageEdgeItem]],
                     total_pages: int,
                     page_height: float = 0.0) -> set[tuple[float, str]]:
    """Identify header/footer items that repeat across pages.

    For each page, captures the top and bottom EDGE_ITEMS_PER_PAGE items
    by y-coordinate. The unit of repetition is the distinct PAGE: a text is
    a running header/footer when it appears at the same y-position on at
    least half the pages (>= threshold distinct pages). The dual MuPDF +
    spatial extraction paths each contribute one item per page, so distinct
    pages, not raw item counts, are what cross the threshold.

    Within a gated bucket where no single text reaches threshold, the
    coverage-union fallback handles alternating headers (title on recto,
    authors on verso): a set of at most _MAX_HEADER_VARIANTS verbatim texts,
    each recurring on >= _MIN_RECUR_PAGES pages, whose page union covers
    >= threshold pages, is stripped together.

    page_height (the representative page height in points) gates the
    varying-text footer-band rule to the bottom margin; pass 0.0 to
    disable that rule (the exact-text, page-number, and doc-number rules
    are unaffected).

    Returns a set of (y_region, text_or_pattern) tuples to strip.
    """
    if total_pages < 3:
        return set()

    footer_band_min_y = (page_height * EDGE_BAND_BOTTOM_FRACTION
                         if page_height > 0 else None)

    threshold = total_pages * REPEATING_THRESHOLD
    y_buckets: dict[float, list[PageEdgeItem]] = defaultdict(list)

    for page_items in all_edge_items:
        for item in page_items:
            y_buckets[_y_bucket(item.bbox)].append(item)

    repeating = set()
    for y_key, items in y_buckets.items():
        pages_seen = len(set(it.page_num for it in items))
        if pages_seen < threshold:
            continue
        texts = [it.text for it in items]

        if all(PAGE_NUM_RE.match(t) for t in texts):
            repeating.add((y_key, "__PAGE_NUM__"))
            _log.debug("Repeating page number at y=%.1f", y_key)
            continue

        if all(DOC_NUM_RE.search(t) for t in texts):
            repeating.add((y_key, "__DOC_NUM__"))
            _log.debug("Repeating doc number at y=%.1f", y_key)
            continue

        # Running footer band: the edge y recurs across pages but the text
        # varies per page (a running section title plus its page number, e.g.
        # "Normative references 2" or "§ 6.9.2.2 6"). Neither the exact-text
        # nor the all-page-number rule catches a band of mixed text, but a
        # bare page number recurring in the band on at least half the pages
        # is a reliable signal that the whole band is page chrome. Gate to the
        # bottom margin so the section-heading band at the top of body pages,
        # whose bare section numbers also match PAGE_NUM_RE, is never stripped.
        if footer_band_min_y is not None and y_key > footer_band_min_y:
            page_num_pages = {
                it.page_num for it in items if PAGE_NUM_RE.match(it.text)
            }
            if len(page_num_pages) >= threshold:
                repeating.add((y_key, "__EDGE_BAND__"))
                _log.debug("Repeating footer band at y=%.1f", y_key)
                continue

        # A running header/footer recurs across distinct PAGES. Count distinct
        # pages per text: the dual MuPDF+spatial paths each contribute one item
        # per page, so counting raw items double-counts (a single-page line
        # reaches the old count threshold and is wrongly stripped).
        text_pages: dict[str, set[int]] = defaultdict(set)
        for it in items:
            text_pages[it.text].add(it.page_num)
        hit = False
        for text, pages in text_pages.items():
            if len(pages) >= threshold:
                repeating.add((y_key, text))
                _log.debug("Repeating exact: y=%.1f text=%r", y_key, text)
                hit = True
        if not hit:
            # Alternating header: no single text reaches threshold, but a small
            # set of verbatim-repeating texts (each on >= _MIN_RECUR_PAGES
            # pages) together covers >= threshold pages (title on recto, authors
            # on verso). The variant cap keeps this from firing on many-variant
            # recurrence (slide-title sets, code-line clusters); a real
            # alternating header has at most _MAX_HEADER_VARIANTS distinct texts.
            recurring = {t: pg for t, pg in text_pages.items()
                         if len(pg) >= _MIN_RECUR_PAGES}
            if 0 < len(recurring) <= _MAX_HEADER_VARIANTS:
                covered: set[int] = set()
                for pg in recurring.values():
                    covered |= pg
                if len(covered) >= threshold:
                    for text in recurring:
                        repeating.add((y_key, text))
                        _log.debug("Repeating union: y=%.1f text=%r",
                                   y_key, text)

    return repeating


def strip_repeating(blocks: list[Block], repeating: set[tuple[float, str]],
                    ) -> list[Block]:
    """Remove lines (or individual spans) matching repeating header/footer
    patterns from blocks.

    Spatial-path lines merge left/center/right header columns (one span
    per column). The whole-line text then won't match any single pattern,
    but each column-span will; per-span stripping handles that while
    preserving non-header content that shares the header y-coordinate
    (e.g. a one-off appendix title).
    """
    if not repeating:
        return blocks

    _page0_meta_y = 0.0
    for blk in blocks:
        if blk.page_num != 0:
            break
        for ln in blk.lines:
            cleaned = strip_format_chars(ln.text).strip()
            if _WG21_LABEL_RE.match(cleaned):
                _page0_meta_y = ln.bbox[3] + 20.0

    patterns_by_y: dict[float, list[str]] = defaultdict(list)
    for ry, rp in repeating:
        patterns_by_y[ry].append(rp)

    def _patterns_near(y_key: float) -> list[str]:
        return (patterns_by_y.get(y_key - Y_TOLERANCE, [])
                + patterns_by_y.get(y_key, [])
                + patterns_by_y.get(y_key + Y_TOLERANCE, []))

    def _matches(text: str, rpattern: str, whole_line: bool = False,
                 is_edge_block: bool = True) -> bool:
        if rpattern == text:
            return True
        if rpattern == "__PAGE_NUM__" and PAGE_NUM_RE.match(text):
            return True
        if rpattern == "__DOC_NUM__" and DOC_NUM_RE.search(text):
            return True
        # A footer band strips whole short lines (never individual spans:
        # span-level matching would shred a long body line that happens to
        # share the band's y) and only inside small edge blocks. The band is a
        # varying-text heuristic, so without the edge-block gate a genuine
        # short body line that lands in the band's y-bucket would be dropped.
        if (rpattern == "__EDGE_BAND__" and whole_line and is_edge_block
                and len(text.split()) <= RUNNING_FOOTER_MAX_WORDS):
            return True
        return False

    result = []
    for block in blocks:
        block_is_edge = _is_edge_block(block)
        kept_lines = []
        # Track y-buckets of stripped lines so co-located sibling lines
        # (variable header text like "3 Motivation" next to repeating
        # "P3948R1") are also stripped.
        stripped_y_buckets: set[float] = set()
        for line in block.lines:
            text = line.text.strip()
            if not text:
                kept_lines.append(line)
                continue

            line_patterns = _patterns_near(_y_bucket(line.bbox))
            if not line_patterns:
                kept_lines.append(line)
                continue

            if any(_matches(text, rp, whole_line=True, is_edge_block=block_is_edge)
                   for rp in line_patterns):
                if block.page_num == 0 and line.bbox[1] < _page0_meta_y:
                    kept_lines.append(line)
                    continue
                stripped_y_buckets.add(_y_bucket(line.bbox))
                continue

            kept_spans = []
            stripped_any = False
            for span in line.spans:
                span_text = span.text.strip()
                if not span_text:
                    kept_spans.append(span)
                    continue
                span_patterns = _patterns_near(_y_bucket(span.bbox))
                if any(_matches(span_text, rp) for rp in span_patterns):
                    stripped_any = True
                    continue
                kept_spans.append(span)

            if not any(sp.text.strip() for sp in kept_spans):
                stripped_y_buckets.add(_y_bucket(line.bbox))
                continue

            kept_lines.append(
                replace(line, spans=kept_spans) if stripped_any else line)

        # Second pass: strip lines co-located with stripped header lines.
        # Only applies to small blocks at page edges (true header/footer
        # assemblies). Body blocks in the middle of the page are never
        # affected, even if they share a y-bucket with a stripped line.
        # A long line is body, never header/footer chrome (the same
        # word-count test the __EDGE_BAND__ rule uses), so it survives the
        # co-location strip even when it shares a stripped y-bucket.
        if stripped_y_buckets and kept_lines:
            if block_is_edge:
                kept_lines = [
                    ln for ln in kept_lines
                    if _y_bucket(ln.bbox) not in stripped_y_buckets
                    or len(ln.text.split()) > RUNNING_FOOTER_MAX_WORDS
                ]

        if kept_lines:
            result.append(replace(block, lines=kept_lines))
    return result


def _join_cross_page(blocks: list[Block]) -> list[Block]:
    """Join paragraphs that span page boundaries.

    When the last block on page N ends without terminal punctuation
    and the first block on page N+1 starts with a lowercase letter,
    merge them into one block.  At most ONE block per page boundary
    is merged; further blocks from the same source page are kept
    separate so that ``compare_extractions`` (which groups by
    ``page_num``) still sees them on their original page.

    Gated off when either boundary line is monospace: this heuristic
    exists for prose sentences cut by a page break, but C++ statements
    routinely end in ``;`` / ``}`` / ``)`` (none of which are in
    ``TERMINAL_PUNCTUATION``) and just as routinely start the next line
    lowercase (``if``, ``else``, ``return``, a variable name), so a code
    block that happens to cross a page boundary trips this heuristic on
    prose grounds alone. Joining it would also silently move that
    block's ``page_num`` to the earlier page (see the bbox comment
    below), which desyncs ``compare_extractions``'s per-page word
    comparison between the two extraction paths whenever the other path
    segments its blocks differently at that same boundary and does not
    trip the same misfire - the page then reads as a dual-path
    disagreement (``<!-- tomd:uncertain -->``) even though both paths
    extracted the same text.
    """
    if len(blocks) < 2:
        return blocks

    result = [replace(blocks[0], lines=list(blocks[0].lines))]
    merged_boundary: int | None = None

    for block in blocks[1:]:
        prev = result[-1]
        prev_text = prev.text.rstrip()
        cur_text = block.text.lstrip()

        cross_page = prev.page_num != block.page_num
        if cross_page and block.page_num != merged_boundary:
            merged_boundary = None

        fs_diff = (
            abs(prev.font_size - block.font_size)
            if (prev.font_size and block.font_size)
            else 0.0
        )

        prev_last = prev.last_content_line()
        cur_first = block.first_content_line()
        prev_mono = prev_last.is_monospace if prev_last is not None else False
        cur_mono = cur_first.is_monospace if cur_first is not None else False

        if (cross_page
                and merged_boundary is None
                and prev_text
                and cur_text
                and not PAGE_NUM_RE.match(prev_text)
                and prev_text[-1] not in TERMINAL_PUNCTUATION
                and cur_text[0].islower()
                and not prev_mono
                and not cur_mono
                and fs_diff <= 1.5):
            prev.lines.extend(block.lines)
            # Keep the original page's bbox: page coordinates are
            # independent per page, so mixing y-values from page N+1
            # into a page N bbox produces a nonsensical y_mid that
            # breaks _column_aware_sort ordering.
            merged_boundary = block.page_num
        else:
            result.append(replace(block, lines=list(block.lines)))

    return result


# Targets spaces and tabs only (not newlines); distinct from
# structure._MULTI_SPACE_RE which targets all \s including newlines.
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
_NBSP = "\u00a0"


def _collapse_spaces(text: str) -> str:
    """Replace non-breaking spaces and collapse runs of spaces/tabs to one."""
    return _MULTI_SPACE_RE.sub(" ", text.replace(_NBSP, " "))


def normalize_whitespace(text: str) -> str:
    """Collapse runs of spaces, replace non-breaking spaces, strip trailing."""
    text = strip_format_chars(text)
    text = _collapse_spaces(text)
    lines = [line.rstrip() for line in text.split("\n")]
    return "\n".join(lines)


# An ATX heading opener at column 0: one to six "#" then whitespace or nothing.
# A body block that starts this way is read by every Markdown parser as a
# heading, so a preprocessor directive quoted in prose (P3556R0 quotes the
# [cpp.include] grammar as `# include ... new-line causes the replacement of
# that directive by ...`) silently becomes an H1 (#302).
_LEADING_ATX_RE = re.compile(r"^(#{1,6})(\s|$)")


def escape_leading_atx(text: str) -> str:
    """Backslash-escape a "#" that would turn a body block into a heading.

    The text is unchanged for readers; only Markdown's block parser is
    affected. Text already backslash-escaped upstream (the sub-caption path in
    ``emit._escape_italic_text``) does not match and is left alone. Shared by
    the paragraph and wording-prose renderers, the two emit paths that flatten
    PDF lines into a single body block.
    """
    return _LEADING_ATX_RE.sub(r"\\\1\2", text)


def find_hidden_regions(page, body_fonts: set[str] | None = None,
                        ) -> set[tuple[float, float, float, float]]:
    """Find regions of hidden text on a page.

    Detects Google Docs widget artifacts: non-document font with
    non-black color (e.g. Roboto/Material UI framework text rendered
    as dropdown values).

    Rendering mode 3 (invisible text) is intentionally ignored.
    MuPDF's dict/rawdict APIs already exclude mode 3 text from
    extraction output. Collecting mode 3 bboxes would only match
    against the visible text at the same coordinates, causing
    false-positive stripping on Chrome "Save as PDF" output where
    an invisible accessibility overlay covers every page.
    """
    hidden_bboxes = set()

    if body_fonts is None:
        return hidden_bboxes

    for span in page.get_texttrace():
        if span.get("type") == 3:
            continue

        font = span.get("font", "")
        font_lower = font.lower()
        color = span.get("color")
        is_black = (color == 0 or color == (0, 0, 0)
                    or color == 0x000000)
        if (font_lower not in body_fonts
                and not is_black
                and any(p in font_lower
                        for p in ("roboto", "google", "material"))):
            for ch in span.get("chars", []):
                hidden_bboxes.add(tuple(ch[3]))

    return hidden_bboxes


def strip_hidden_blocks(
    blocks: list[Block],
    hidden_by_page: dict[int, set[tuple[float, float, float, float]]],
) -> list[Block]:
    """Remove blocks whose text is entirely within hidden regions.

    *hidden_by_page* maps page numbers to sets of bboxes so that
    hidden regions on one page cannot accidentally match visible
    text on a different page that happens to share the same
    coordinates.
    """
    if not hidden_by_page:
        return blocks

    result = []
    for block in blocks:
        page_hidden = hidden_by_page.get(block.page_num)
        if not page_hidden:
            result.append(block)
            continue
        has_visible = False
        for line in block.lines:
            for span in line.spans:
                if not span.text.strip():
                    continue
                span_rect = fitz.Rect(span.bbox)
                is_hidden = any(
                    fitz.Rect(hb).intersects(span_rect)
                    for hb in page_hidden
                )
                if not is_hidden:
                    has_visible = True
                    break
            if has_visible:
                break
        if has_visible:
            result.append(block)
    return result


# Word or hyphenated compound: Unicode alphanumeric runs (no underscore)
# joined by single hyphens. Pure numbers are dropped by the caller;
# leading/trailing punctuation is never part of a match, so "point,"
# yields "point", "(lane-count)" yields "lane-count" and "convertible_"
# yields "convertible".
_HYPHEN_TOKEN_RE = re.compile(r"[^\W_]+(?:-[^\W_]+)*")


@dataclass(frozen=True)
class HyphenEvidence:
    """What a document itself says about its hyphenated words.

    Lowercased. ``words`` are tokens seen standalone (never as a wrap
    fragment), ``compounds`` are ``a-b`` tokens seen mid-line, ``tails``
    are the last parts of those compounds. Built once per document by
    :func:`collect_hyphen_evidence`; consumed by :func:`dehyphenate_pair`.
    """
    words: frozenset[str]
    compounds: frozenset[str]
    tails: frozenset[str]


def collect_hyphen_evidence(lines: list[Line]) -> HyphenEvidence:
    """Gather word and compound evidence from lines in document order.

    A line-ending hyphen marks a wrap: the fragment before it and the
    first token of the following line are excluded from the counts, so
    ``imple-`` / ``mentation`` never registers ``imple`` or ``mentation``
    as standalone words. Everything else is evidence: ``non-associative``
    written on one line proves the compound, ``nondeterminism`` written
    whole proves the glued form.

    Code lines contribute compounds only (an exposition-only identifier
    such as ``simd-consteval-broadcast-arg`` is attested by its own
    listing), never words or tails: identifier fragments (``some_time``)
    and arithmetic (``n-1``) are not prose vocabulary.
    """
    words: set[str] = set()
    compounds: set[str] = set()
    tails: set[str] = set()
    prev_wrapped = False
    for line in lines:
        text = line.text.strip()
        if not text:
            continue
        tokens = [m.group(0).lower() for m in _HYPHEN_TOKEN_RE.finditer(text)]
        wrapped = text.endswith("-") and not text[:-1].endswith((" ", "\t"))
        if wrapped:
            tokens = tokens[:-1]
        if prev_wrapped:
            tokens = tokens[1:]
        prev_wrapped = wrapped
        is_code = line.is_monospace
        for tok in tokens:
            if not any(ch.isalpha() for ch in tok):
                continue
            if "-" in tok:
                compounds.add(tok)
                if not is_code:
                    tails.add(tok.rsplit("-", 1)[1])
            elif not is_code:
                words.add(tok)
    return HyphenEvidence(frozenset(words), frozenset(compounds), frozenset(tails))


@dataclass(frozen=True)
class DehyphenatedPair:
    """Result of joining a line-ending hyphen with the next line's word.

    ``last_line`` now ends with ``joined``; ``next_line`` has lost
    ``first_word`` (None when that was its only content). ``prefix_token``
    is the hyphen-terminated token that ``joined`` replaces, so callers
    holding a separate text copy can patch it the same way.
    """
    last_line: Line
    next_line: Line | None
    prefix_token: str
    first_word: str
    joined: str


def _compound_seen(prefix_full: str, tail_full: str, evidence: HyphenEvidence) -> bool:
    """True if the wrapped pair is attested hyphenated elsewhere.

    Both the innermost pair (``lane-assignment`` from ``per-lane-`` /
    ``assignment``) and the whole token (``simd-consteval-broadcast-arg``
    from ``simd-consteval-`` / ``broadcast-arg``) count.
    """
    prefix = prefix_full.lower()
    tail = tail_full.lower()
    return (f"{prefix}-{tail}" in evidence.compounds
            or f"{prefix.rsplit('-', 1)[-1]}-{tail.split('-', 1)[0]}" in evidence.compounds)


def _keep_hyphen(prefix_full: str, tail_full: str, evidence: HyphenEvidence) -> bool:
    """Decide whether a wrapped prose ``prefix-`` / ``tail`` pair is a compound.

    Document evidence first, then form: the compound seen hyphenated
    mid-line keeps it, the glued word seen whole drops it, a known compound
    prefix keeps it, an acronym or digit-led prefix (``SIMD-``, ``64-``)
    keeps it, two halves that both live as standalone words keep it, a
    tail that ends another compound of the paper keeps it. Otherwise it is
    a syllable break and the halves glue.

    Model boundary: a TeX syllable break whose halves are both common words
    (``how-`` / ``ever``) is kept unless the whole word occurs elsewhere in
    the paper, which for common words it does.

    shortcut: no suffix word list, so ``build-`` / ``proof`` with neither
    half attested glues to ``buildproof``; the upgrade path is a dictionary
    or a corpus-derived compound list, not a hand-kept suffix set.
    """
    if _compound_seen(prefix_full, tail_full, evidence):
        return True
    prefix_key_raw = prefix_full.rsplit("-", 1)[-1]
    prefix_key = prefix_key_raw.lower()
    tail = tail_full.lower().split("-", 1)[0]
    if f"{prefix_key}{tail}" in evidence.words:
        return False
    if prefix_key in COMPOUND_PREFIXES:
        return True
    if prefix_key_raw.isupper() or prefix_key_raw[0].isdigit():
        return True
    if prefix_key in evidence.words and tail in evidence.words:
        return True
    return tail in evidence.tails


def dehyphenate_pair(last_line: Line, next_line: Line,
                     evidence: HyphenEvidence) -> DehyphenatedPair | None:
    """Join a line-ending hyphen with the first word of the next line.

    Returns None when the pair is not a wrap: no trailing hyphen, a bare
    dash (``foo -``), an uppercase continuation, or a font change (prose
    ``over-`` followed by a code line ``int ilogb(...)`` is a paragraph
    running into a listing, not a wrapped word). Otherwise the next line's
    first word is pulled up onto the last line, glued (``imple-`` +
    ``mentation`` -> ``implementation``) or kept as a compound (``non-`` +
    ``associative`` -> ``non-associative``) per :func:`_keep_hyphen`.
    Pulling the word up on keep is what removes the dangling
    ``non- associative`` when the lines are later flattened with a space.

    The form rules apply to prose only. Inside monospace text, or when the
    hyphen follows a non-alphanumeric (``convertible_-`` / ``to``), only a
    compound attested elsewhere keeps the hyphen; everything else glues,
    as before. A prefix without any alphanumeric (a glyph placeholder,
    ``--``) glues too.
    """
    if not last_line.spans or not next_line.spans:
        return None
    last_span = last_line.spans[-1]
    next_first = next_line.spans[0]
    # MuPDF spans may carry a trailing space at line end; it is not content.
    last_text = last_span.text.rstrip()
    next_text = next_first.text.lstrip()
    if not last_text.endswith("-") or len(last_text) < 2 or last_text[-2].isspace():
        return None
    if not next_text or not next_text[0].islower():
        return None
    first_word = next_text.split()[0]
    prefix_raw = last_text[:-1].split()[-1]
    # Evidence keys are bare alphanumerics: "(non" -> "non", "point," -> "point".
    prefix_runs = _HYPHEN_TOKEN_RE.findall(prefix_raw)
    tail_match = _HYPHEN_TOKEN_RE.match(first_word)
    # A word fragment only continues in the same font; a non-word prefix
    # (glyph placeholder, "--") has no font to match and glues as before.
    if prefix_runs and last_span.monospace != next_first.monospace:
        return None
    keep = False
    if prefix_runs and tail_match is not None:
        if last_span.monospace or not last_text[-2].isalnum():
            keep = _compound_seen(prefix_runs[-1], tail_match.group(0), evidence)
        else:
            keep = _keep_hyphen(prefix_runs[-1], tail_match.group(0), evidence)

    if keep:
        joined = f"{prefix_raw}-{first_word}"
        new_last_text = last_text + first_word
    else:
        joined = f"{prefix_raw}{first_word}"
        new_last_text = last_text[:-1] + first_word
    new_last = Line(spans=last_line.spans[:-1] + [replace(last_span, text=new_last_text)],
                    bbox=last_line.bbox, page_num=last_line.page_num)

    remainder = next_text[len(first_word):].lstrip()
    if remainder:
        new_next = Line(spans=[replace(next_first, text=remainder)] + next_line.spans[1:],
                        bbox=next_line.bbox, page_num=next_line.page_num)
    elif len(next_line.spans) > 1:
        new_next = Line(spans=next_line.spans[1:],
                        bbox=next_line.bbox, page_num=next_line.page_num)
    else:
        new_next = None
    return DehyphenatedPair(new_last, new_next, f"{prefix_raw}-", first_word, joined)


def _in_regions(line: Line, regions: list | None) -> bool:
    """The line's centre lies inside one of the (page, bbox) regions."""
    if not regions:
        return False
    cx, cy = (line.bbox[0] + line.bbox[2]) / 2, (line.bbox[1] + line.bbox[3]) / 2
    return any(pg == line.page_num and bb[0] <= cx <= bb[2] and bb[1] <= cy <= bb[3] for pg, bb in regions)


def cleanup_text(blocks: list[Block], keep_hyphens: list | None = None) -> list[Block]:
    """Apply all text cleanup operations to extracted blocks.

    ``keep_hyphens`` lists (page, bbox) regions a table reader located: a
    line-end hyphen there is a table cell's and is decided when the cell is
    rendered (emit.py), not by the document-wide pass."""
    result = []
    for block in blocks:
        cleaned_lines = []
        for line in block.lines:
            cleaned_spans = []
            for span in line.spans:
                new_text = strip_format_chars(span.text)
                if not span.monospace:
                    new_text = _collapse_spaces(new_text)
                cleaned_spans.append(replace(span, text=new_text))
            cleaned_lines.append(Line(
                spans=cleaned_spans,
                bbox=line.bbox,
                page_num=line.page_num,
            ))
        result.append(Block(
            lines=cleaned_lines,
            bbox=block.bbox,
            page_num=block.page_num,
        ))

    result = _join_cross_page(result)

    # T9 dehyphenation. Evidence comes from the whole document so a
    # compound written on one line elsewhere decides its wrapped twin.
    evidence = collect_hyphen_evidence([ln for blk in result for ln in blk.lines])
    dehyphenated = []
    for block in result:
        lines = list(block.lines)
        new_lines = []
        i = 0
        while i < len(lines):
            line = lines[i]
            if i + 1 < len(lines) and not _in_regions(line, keep_hyphens):
                pair = dehyphenate_pair(line, lines[i + 1], evidence)
                if pair is not None:
                    line = pair.last_line
                    if pair.next_line is None:
                        del lines[i + 1]
                    else:
                        lines[i + 1] = pair.next_line
            new_lines.append(line)
            i += 1

        dehyphenated.append(Block(
            lines=new_lines,
            bbox=block.bbox,
            page_num=block.page_num,
        ))

    return dehyphenated
