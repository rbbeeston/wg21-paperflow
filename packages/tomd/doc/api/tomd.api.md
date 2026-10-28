# tomd API surface

78 modules, 86 classes, 196 functions, 85 methods, 348 fields. Typed: 862 of 959 functions and methods (89%).

## Contents

- [`__init__.py`](#init-py)
- [`api.py`](#api-py): ConvertedPaper, convert_paper, convert_paper_full
- [`cli.py`](#cli-py): main
- [`domain/__init__.py`](#domain-init-py)
- [`domain/document.py`](#domain-document-py): ConvertedPaper, PaperDocument, SkipReason
- [`domain/elements.py`](#domain-elements-py): BlockElement, Blockquote, CodeBlock, ElementKind, Heading, ImageElement, ListBlock, ListItem, Paragraph, ThematicBreak, UncertainElement, WordingBlock
- [`domain/image.py`](#domain-image-py): ExtractedImage
- [`domain/metadata.py`](#domain-metadata-py): PaperMetadata
- [`domain/span.py`](#domain-span-py): CodeSpan, ContainerSpan, DeletedSpan, EmphasisSpan, InsertedSpan, LineBreakSpan, LinkSpan, Span, StrongSpan, SubscriptSpan, SuperscriptSpan, TextSpan
- [`domain/table.py`](#domain-table-py): Cell, CellAlign, CodeCell, Table, TableRow, TableStrategy, TextCell
- [`errors.py`](#errors-py): CheckContentArgError, TomdError, UnsupportedSourceFormatError
- [`lib/__init__.py`](#lib-init-py)
- [`lib/batch.py`](#lib-batch-py): BatchRunResult, format_batch_finished, format_batch_progress_line, format_batch_timeout, run_parallel_batch
- [`lib/body/__init__.py`](#lib-body-init-py)
- [`lib/body/abstract.py`](#lib-body-abstract-py): dedup_abstract, promote_abstract_from_uncertain, reorder_abstract_in_uncertain, rescue_stranded_abstract_body, strip_metadata_from_uncertain
- [`lib/check_content.py`](#lib-check-content-py): ContentCheckBatchResult, ContentCheckResult, MisalignedRegion, check_paper_content, compute_content_coverage, format_content_check_report, run_content_check_batch, write_content_check_json_atomic
- [`lib/golden_compare.py`](#lib-golden-compare-py): AxisScore, Block, ListEntry, NormalizedDoc, StructuralScore, compare, normalize
- [`lib/golden_gaps.py`](#lib-golden-gaps-py): Gap, draft_issues, locate_gaps
- [`lib/golden_qa.py`](#lib-golden-qa-py): AxisReport, FidelityVerdict, ReblessOutcome, ScoreResult, anchors_path, bless_stem, build_review_prompt, download_source, facts_path, fidelity_verdict, find_source, generate_ideal, ...
- [`lib/html/__init__.py`](#lib-html-init-py)
- [`lib/html/convert.py`](#lib-html-convert-py): convert_html
- [`lib/html/extract.py`](#lib-html-extract-py): detect_generator, extract_metadata, parse_html, strip_boilerplate
- [`lib/html/images.py`](#lib-html-images-py): HtmlImagesResult, load_html_images
- [`lib/html/render.py`](#lib-html-render-py): render_body
- [`lib/metadata_yaml/__init__.py`](#lib-metadata-yaml-init-py)
- [`lib/metadata_yaml/extract.py`](#lib-metadata-yaml-extract-py): apply_pdf_metadata_fallbacks, enrich_pdf_reply_to, extract_metadata
- [`lib/metadata_yaml/format.py`](#lib-metadata-yaml-format-py): format_front_matter, parse_front_matter, sanitize_metadata, strip_front_matter, FRONT_MATTER_ORDER, FRONT_MATTER_RE
- [`lib/metadata_yaml/strip.py`](#lib-metadata-yaml-strip-py): strip_metadata_headings, strip_pre_content_paragraphs, strip_pre_heading_fragments
- [`lib/pdf/__init__.py`](#lib-pdf-init-py)
- [`lib/pdf/_fitz_lock.py`](#lib-pdf-fitz-lock-py)
- [`lib/pdf/cleanup.py`](#lib-pdf-cleanup-py): DehyphenatedPair, HyphenEvidence, cleanup_text, collect_hyphen_evidence, dehyphenate_pair, detect_repeating, escape_leading_atx, find_hidden_regions, get_edge_items, normalize_whitespace, strip_hidden_blocks, strip_repeating
- [`lib/pdf/code_format.py`](#lib-pdf-code-format-py): is_diagram_block, maybe_normalize_code_line, normalize_code_line
- [`lib/pdf/code_grid.py`](#lib-pdf-code-grid-py): CodeGrid
- [`lib/pdf/docling_backend.py`](#lib-pdf-docling-backend-py): absorb_cross_page_spec_rows, discover_tables_with_docling, docling_available, enrich_tables_with_docling, extract_docling_tables
- [`lib/pdf/emit.py`](#lib-pdf-emit-py): emit_markdown, emit_prompts, is_flagged_table, renumber_uncertain_markers, LIST_BULLET
- [`lib/pdf/emoji_data.py`](#lib-pdf-emoji-data-py): EMOJI_PRESENTATION_RANGES, UNICODE_EMOJI_VERSION
- [`lib/pdf/evidence.py`](#lib-pdf-evidence-py): Entry, Record, CODE_ERRORS
- [`lib/pdf/extract.py`](#lib-pdf-extract-py): attach_links, collect_links, extract_mupdf, extract_spatial
- [`lib/pdf/figures.py`](#lib-pdf-figures-py): detect_figure_regions
- [`lib/pdf/glyphs.py`](#lib-pdf-glyphs-py): GlyphCandidate, GlyphPassStats, collect_glyph_candidates, collect_text_emoji_bboxes, drop_glyphs_in_code_and_tables, filter_coincident, glyph_to_char, inject_glyph_spans, is_glyph_only_block, GLYPH_FONT_SENTINEL, GLYPH_PLACEHOLDER_MARKER_TEMPLATE, UNKNOWN_GLYPH
- [`lib/pdf/images.py`](#lib-pdf-images-py): ExtractedImage, ExtractionResult, VectorUncertaintyStats, extract_page_images, finalize_extraction, MIN_IMAGE_DIM_PT, TRUNCATION_MARKER_TEMPLATE
- [`lib/pdf/levels.py`](#lib-pdf-levels-py): assign, cell_markers, comment, NAMES, SHOWN_FROM
- [`lib/pdf/mono.py`](#lib-pdf-mono-py): classify_monospace, propagate_monospace
- [`lib/pdf/pagecache.py`](#lib-pdf-pagecache-py): rawdict
- [`lib/pdf/pipeline.py`](#lib-pdf-pipeline-py): PipelineResult, run_pipeline
- [`lib/pdf/poll.py`](#lib-pdf-poll-py): extract_poll_tables
- [`lib/pdf/qa.py`](#lib-pdf-qa-py): QABatchResult, QAMetrics, compute_metrics, format_qa_report, run_qa_batch, write_qa_json_atomic
- [`lib/pdf/rowbands.py`](#lib-pdf-rowbands-py): merge_rule_bands, MAX_FILL, MIN_RULES, MIN_SEGMENT
- [`lib/pdf/ruled.py`](#lib-pdf-ruled-py): drawn_spans, extract_ruled_tables, page_hrules
- [`lib/pdf/runctx.py`](#lib-pdf-runctx-py): RunContext, current, run_scope, ERROR_MESSAGE_LIMIT
- [`lib/pdf/select.py`](#lib-pdf-select-py): candidate_from_section, candidates_agree, class_check, closed_exempt, conservation_error, cross_reader_continuation, join_split_words, mark_matrix, page_furniture, partial_reading, remove_table_regions, select_tables, ...
- [`lib/pdf/spans.py`](#lib-pdf-spans-py): normalize_spans
- [`lib/pdf/stacked.py`](#lib-pdf-stacked-py): split_stacked
- [`lib/pdf/structure.py`](#lib-pdf-structure-py): compare_extractions, drop_leaked_toc_entries, heading_confidence, structure_body, structure_sections
- [`lib/pdf/summary.py`](#lib-pdf-summary-py): build, generator, header_comment, prompt_elements, unfamiliarity, COMMON_LAYOUTS, KNOWN_GENERATORS
- [`lib/pdf/table.py`](#lib-pdf-table-py): TableKind, TableStrategy, detect_tables, exclude_table_regions
- [`lib/pdf/tagged.py`](#lib-pdf-tagged-py): extract_tagged_tables
- [`lib/pdf/types.py`](#lib-pdf-types-py): Block, Confidence, FigureEdge, FigureGraph, FigureNode, FigureRegion, Line, PageEdgeItem, Section, SectionKind, SkipReason, Span, ...
- [`lib/pdf/vector_images.py`](#lib-pdf-vector-images-py): extract_page_vector_images, format_uncertainty_marker, should_emit_marker, ALLOWED_REASON_KEYS, REASON_ASPECT_EXTREME, REASON_BBOX_TOO_LARGE, REASON_CLUSTERS_OVERFLOW, REASON_EDGE_BAND, REASON_TEXT_OVERLAP, REASON_TOO_FEW_ITEMS, REASON_TOO_SMALL, REASON_WORDING_COLOR, ...
- [`lib/pdf/wg21.py`](#lib-pdf-wg21-py): extract_metadata_from_blocks, REPLY_TO_CONTINUATION_CAP
- [`lib/pdf/wording.py`](#lib-pdf-wording-py): classify_wording, collect_line_drawings, is_foreign_chromatic, is_green_ins, is_red_del, is_wording_rgb
- [`lib/pdf/wording_emit.py`](#lib-pdf-wording-emit-py)
- [`lib/shared.py`](#lib-shared-py): apply_strip_leading_h1, ascii_escape, dedup_paragraphs, deobfuscate_email, enrich_reply_to_names, normalize_date, override_revision_from_filename, parse_author_lines, strip_format_chars, strip_freeform_metadata_lines, strip_leading_h1, strip_orphan_toc_list, ...
- [`lib/similarity.py`](#lib-similarity-py): fuzzy_match_label, similar, word_jaccard
- [`lib/tables.py`](#lib-tables-py): cell_style, code_cell, text_cell, MIXED_TABLE_MARKER, TABLE_CLOSE, TABLE_OPEN
- [`lib/toc.py`](#lib-toc-py): find_toc_indices, has_dot_leader, is_toc_label, normalize_toc_entry, MIN_TOC_RUN
- [`lib/wording_cleanup.py`](#lib-wording-cleanup-py): strip_redundant_tags
- [`lib/wording_markup.py`](#lib-wording-markup-py): wording_tag_open, LEGACY_FENCE_MARKER, LEGACY_WORDING_FENCE_RE, WORDING_CLASSES, WORDING_TAGS, WORDING_TAG_RE
- [`lib/wording_policy.py`](#lib-wording-policy-py): implicit_role_for, UNIFORM_ROLE_THRESHOLD
- [`writers/__init__.py`](#writers-init-py)
- [`writers/base.py`](#writers-base-py): DocumentWriter
- [`writers/markdown/__init__.py`](#writers-markdown-init-py)
- [`writers/markdown/blocks.py`](#writers-markdown-blocks-py): strip_redundant_roles, write_element
- [`writers/markdown/front_matter.py`](#writers-markdown-front-matter-py): write_front_matter
- [`writers/markdown/normalizers.py`](#writers-markdown-normalizers-py): normalize_front_matter, strip_body_metadata_text, strip_toc
- [`writers/markdown/spans.py`](#writers-markdown-spans-py): format_code_span, write_span, write_spans
- [`writers/markdown/tables.py`](#writers-markdown-tables-py): write_table
- [`writers/markdown/writer.py`](#writers-markdown-writer-py): MarkdownWriter

<a id="init-py"></a>

## `__init__.py` ([source](../../src/tomd/__init__.py))

```python
"""tomd: PDF and HTML to Markdown converter for WG21 papers."""
```

<a id="api-py"></a>

## `api.py` ([source](../../src/tomd/api.py))

Typed: 7 of 9 functions and methods (77%).

```python
"""Public tomd API: convert a staged paper source to markdown.

``convert_paper(paper_id, source_path, meta)`` is the only supported
entry point. The function is pure: it reads the source file from disk,
converts to markdown, and returns the markdown plus any optional LLM
reconcile prompts. Persisting the result is the caller's job, done
through a :class:`paperstore.StorageBackend` so non-filesystem backends
work without changes here.

YAML front-matter fallback lives here: whatever tomd could not extract
from the source paper is filled in from the mailing-index row for the
paper. Fields already present in the paper's front matter win.

The returned markdown's front matter is always emitted in the strict
canonical key order ``title, document, date, intent, audience,
reply-to`` (unknown keys after ``audience``, ``reply-to`` always last),
regardless of the source format or the order in which fallback fields
were merged. The ``_normalize_front_matter`` pass enforces this
invariant.
"""

@dataclass(frozen=True)
class ConvertedPaper:
    """Full output of one ``convert_paper_full`` invocation.

    Adds image-extraction fields on top of the markdown / prompts /
    intent triple that ``convert_paper`` returns. Consumers that don't
    care about images can keep calling ``convert_paper``; the CLI
    convert orchestration uses this structured form to persist image
    bytes and decide whether to invalidate downstream pipelines.

    ``skipped`` is True for empty PDFs, slide decks, standards-draft
    early exits, or unreadable sources. In that case ``markdown`` is the empty
    string and ``images`` is empty - the caller writes nothing to
    disk and accumulates the paper in a "skipped" report bucket.
    """
    markdown: str
    prompts: list[str] | None
    intent: str
    images: list[ExtractedImage] = field(default_factory=list)
    source_image_count: int = 0
    images_truncated: bool = False
    skipped: bool = False
    skip_reason: SkipReason | None = None
    source_raster_count: int = 0
    source_vector_count: int = 0
    # The PDF paper summary (tables trusted, flagged and marked, removed
    # content, reader errors); None for HTML and skipped papers.
    summary: dict | None = None
    @classmethod
    def skipped_from(cls, raw: PipelineResult) -> 'ConvertedPaper':
        """Translate a skipped :class:`PipelineResult` into a skipped
        :class:`ConvertedPaper`.
        """
        # called by: convert_paper_full

def convert_paper(paper_id: str, source_path: Path, meta: dict) -> tuple[str, list[str] | None, str]:
    """Convert a staged source file to markdown. Pure: no database or
    filesystem writes.

    Thin wrapper over :func:`convert_paper_full` that returns the
    historical ``(markdown, prompts, extracted_intent)`` triple. New
    callers that need the extracted image data should call
    :func:`convert_paper_full` directly.

    Raises:
        RuntimeError: tomd produced no usable markdown.
    """
    # calls: convert_paper_full

def convert_paper_full(paper_id: str, source_path: Path, meta: dict, *, html_images_manifest=None, extract_vector: bool = False, whiteout_text: bool = False) -> ConvertedPaper:
    """Convert a staged source file, returning markdown AND image data.

    All inputs are pre-fetched by the caller. Reads ``source_path`` from
    disk, runs the appropriate converter, applies YAML front-matter
    fallback from ``meta``, canonicalizes front-matter key order, strips
    TOC blocks, and returns a :class:`ConvertedPaper` carrying both the
    markdown and the list of extracted images.

    For HTML sources, pass the parsed
    :class:`paperstore.html_manifest.HtmlImagesManifest` (or None)
    via ``html_images_manifest``. With a manifest, ``<img>`` tags in
    the source HTML are rewritten to point at the mailing-fetched
    on-disk filenames; without one, ``<img>`` tags are suppressed so
    no raw ``data:`` URI leaks into the markdown.

    Slide-deck, standards-draft, and unreadable PDFs produce a
    ``ConvertedPaper`` with ``skipped=True``, empty markdown, and
    empty images. The caller writes nothing to disk for skipped
    papers and accumulates them in a "skipped" summary bucket.

    The returned markdown's YAML front matter is guaranteed to use the
    strict canonical key order ``title, document, date, intent,
    audience, reply-to``.
    """
    # untyped: html_images_manifest
    # calls: _convert_with_tomd_full, ConvertedPaper.skipped_from, _normalize_front_matter, _strip_body_metadata_text, format.parse_front_matter, _strip_toc, emit.renumber_uncertain_markers, _extract_intent_from_front_matter, ConvertedPaper
    # called by: convert_paper

# + 7 private module-level names
```

<a id="cli-py"></a>

## `cli.py` ([source](../../src/tomd/cli.py))

Typed: 21 of 21 functions and methods (100%).

```python
"""tomd developer CLI: the golden QA workflow.

The package's sanctioned CLI boundary: the one tomd module that prints and
persists. All scoring, blessing, rendering, and gap logic lives in
`tomd.lib.golden_qa` / `tomd.lib.golden_gaps` (data-returning); this module only
parses arguments, calls those functions, and reports. Verbs operate on the
golden fixtures directory, never the paperstore workspace:

    tomd tables <pdf|pid> [--page N] [--trace]  table diagnostic (page, shape, kind, source)
    tomd add <paper_id> [source]   download (or copy) a source; render pages if PDF
    tomd generate <paper_id>       seed a candidate ideal from tomd's own conversion (no LLM)
    tomd review <paper_id>         LLM punch-list of structural divergences vs source (optional)
    tomd render <paper_id>         render a PDF source to page images
    tomd score <paper_id> | --all  per-axis score vs committed baseline
    tomd bless <paper_id>          validate a candidate ideal, record baseline
    tomd issue <paper_id>          draft ready-to-file issues from the gaps
                                    --create  file them via gh CLI
    tomd rebless <paper_id> | --all ratchet baselines up after a tomd improvement
    tomd fact <paper_id>           create or edit comprehension fact assertions
    tomd anchor <paper_id>         create or edit structural anchor tripwires

Every verb takes the same first argument, a `paper_id` (the WG21 id including
revision, `P4228R0`), normalized to the lowercase fixture stem at parse time.
"""

def main(argv: list[str] | None = None) -> int:
    # calls: _paper_id, _all_flag
    ...

# + 20 private module-level names
```

<a id="domain-init-py"></a>

## `domain/__init__.py` ([source](../../src/tomd/domain/__init__.py))

```python
"""Distributed under the Boost Software License, Version 1.0. (See accompanying

file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)

Official repository: https://github.com/cppalliance/wg21-paperflow
"""
```

<a id="domain-document-py"></a>

## `domain/document.py` ([source](../../src/tomd/domain/document.py))

Typed: 1 of 1 functions and methods (100%).

```python
"""Distributed under the Boost Software License, Version 1.0. (See accompanying

file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)

Official repository: https://github.com/cppalliance/wg21-paperflow
"""

@dataclass
class ConvertedPaper:
    """Final result container of paper conversion."""
    paper_id: str
    markdown: str
    metadata: PaperMetadata = field(default_factory=PaperMetadata)
    images: list[ExtractedImage] = field(default_factory=list)
    is_skipped: bool = False
    skip_reason: SkipReason | None = None
    @classmethod
    def from_document(cls, doc: PaperDocument, markdown: str) -> 'ConvertedPaper':
        """Construct a ConvertedPaper from a PaperDocument and generated Markdown."""

@dataclass
class PaperDocument:
    """Intermediate Representation (IR) AST container for a WG21 paper."""
    paper_id: str
    metadata: PaperMetadata = field(default_factory=PaperMetadata)
    elements: list[BlockElement] = field(default_factory=list)
    body: str = ''
    images: list[ExtractedImage] = field(default_factory=list)
    is_skipped: bool = False
    skip_reason: SkipReason | None = None

class SkipReason(StrEnum):
    """Reason a paper was skipped during conversion."""
    EMPTY_CONTENT = 'empty_content'
    SLIDE_DECK = 'slide_deck'
    STANDARDS_DRAFT = 'standards_draft'
    UNREADABLE = 'unreadable'
```

<a id="domain-elements-py"></a>

## `domain/elements.py` ([source](../../src/tomd/domain/elements.py))

Typed: 29 of 29 functions and methods (100%).

```python
"""Block-level AST nodes for WG21 paper documents.

Code diffs are represented on ``CodeBlock`` via its optional ``lines`` field
(per-line span sequences carrying ``InsertedSpan`` / ``DeletedSpan`` role runs)
rather than a separate element class, keeping one code block type across the
AST and writer.

Distributed under the Boost Software License, Version 1.0. (See accompanying

file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)

Official repository: https://github.com/cppalliance/wg21-paperflow
"""

@dataclass
class BlockElement:
    """Base class for all document-level block AST nodes."""
    def role_text(self, target_type: type[Span]) -> str:
        """Return concatenated plain text of inline spans matching ``target_type``."""
    @property
    def text(self) -> str:
        """Return recursive unformatted plain text of this block."""
    def unwrap_spans(self, target_type: type[Span]) -> Self:
        """Return a copy of this block with ``target_type`` spans unwrapped."""

@dataclass
class Blockquote(BlockElement):
    """Indented quotation or note block."""
    children: list[BlockElement] = field(default_factory=list)
    role: str | None = None
    @classmethod
    def from_text(cls, content: str, role: str | None = None) -> 'Blockquote':
        # calls: Paragraph.from_text
        ...
    def role_text(self, target_type: type[Span]) -> str: ...
    @property
    def text(self) -> str: ...
    def unwrap_spans(self, target_type: type[Span]) -> Self: ...

@dataclass
class CodeBlock(BlockElement):
    """Multi-line code block; ``lines`` carries inline role spans for code diffs."""
    code: str = ''
    language: str = 'cpp'
    title: str | None = None
    lines: list[list[Span]] | None = None
    @property
    def text(self) -> str: ...

class ElementKind(StrEnum):
    """Enumeration of block element kinds."""
    HEADING = 'heading'
    PARAGRAPH = 'paragraph'
    CODE_BLOCK = 'code_block'
    TABLE = 'table'
    LIST = 'list'
    BLOCKQUOTE = 'blockquote'
    WORDING = 'wording'
    THEMATIC_BREAK = 'thematic_break'
    IMAGE = 'image'
    UNCERTAIN = 'uncertain'

@dataclass
class Heading(BlockElement):
    """Section heading with depth level."""
    level: int
    spans: list[Span] = field(default_factory=list)
    @classmethod
    def from_text(cls, level: int, text: str) -> 'Heading':
        # calls: span.TextSpan
        ...
    def role_text(self, target_type: type[Span]) -> str: ...
    @property
    def text(self) -> str: ...
    def unwrap_spans(self, target_type: type[Span]) -> Self: ...

@dataclass
class ImageElement(BlockElement):
    """Block image reference with caption and alt text."""
    caption: str
    alt: str = ''
    stored_filename: str = ''
    @property
    def text(self) -> str: ...

@dataclass
class ListBlock(BlockElement):
    """Ordered or unordered list; ``start`` numbers the first ordered item."""
    items: list[ListItem] = field(default_factory=list)
    ordered: bool = False
    start: int = 1
    def role_text(self, target_type: type[Span]) -> str: ...
    @property
    def text(self) -> str: ...
    def unwrap_spans(self, target_type: type[Span]) -> Self: ...

@dataclass
class ListItem:
    """Individual list item: an inline label plus optional continuation blocks."""
    spans: list[Span] = field(default_factory=list)
    children: list[BlockElement] = field(default_factory=list)
    marker: str | None = None
    @classmethod
    def from_text(cls, text: str) -> 'ListItem':
        # calls: span.TextSpan
        ...
    def role_text(self, target_type: type[Span]) -> str: ...
    @property
    def text(self) -> str: ...
    def unwrap_spans(self, target_type: type[Span]) -> Self: ...

@dataclass
class Paragraph(BlockElement):
    """Prose paragraph containing inline text spans."""
    spans: list[Span] = field(default_factory=list)
    @classmethod
    def from_text(cls, text: str) -> 'Paragraph':
        # calls: span.TextSpan
        # called by: Blockquote.from_text, WordingBlock.from_text
        ...
    def role_text(self, target_type: type[Span]) -> str: ...
    @property
    def text(self) -> str: ...
    def unwrap_spans(self, target_type: type[Span]) -> Self: ...

@dataclass
class ThematicBreak(BlockElement):
    """Horizontal divider / thematic break."""

@dataclass
class UncertainElement(BlockElement):
    """Flagged block with conversion uncertainty or reviewer prompt."""
    prompt: str
    raw_content: str = ''
    @property
    def text(self) -> str: ...

@dataclass
class WordingBlock(BlockElement):
    """Proposed standard wording modification block."""
    role: WordingRole = 'wording'
    children: list[BlockElement] = field(default_factory=list)
    @classmethod
    def from_text(cls, text: str, role: WordingRole = 'wording') -> 'WordingBlock':
        # calls: Paragraph.from_text
        ...
    def role_text(self, target_type: type[Span]) -> str: ...
    @property
    def text(self) -> str: ...
    def unwrap_spans(self, target_type: type[Span]) -> Self: ...
```

<a id="domain-image-py"></a>

## `domain/image.py` ([source](../../src/tomd/domain/image.py))

```python
"""Distributed under the Boost Software License, Version 1.0. (See accompanying

file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)

Official repository: https://github.com/cppalliance/wg21-paperflow
"""

@dataclass(frozen=True)
class ExtractedImage:
    """Canonical representation of an extracted figure or illustration."""
    stored_filename: str
    bytes: 'bytes | None' = None
    caption: str = ''
    alt: str = ''
    source: str = 'raster'
```

<a id="domain-metadata-py"></a>

## `domain/metadata.py` ([source](../../src/tomd/domain/metadata.py))

Typed: 2 of 2 functions and methods (100%).

```python
"""Distributed under the Boost Software License, Version 1.0. (See accompanying

file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)

Official repository: https://github.com/cppalliance/wg21-paperflow
"""

@dataclass
class PaperMetadata:
    """Structured metadata for a WG21 paper."""
    title: str = ''
    document: str = ''
    date: str = ''
    intent: str = ''
    audience: list[str] | str = field(default_factory=list)
    reply_to: list[str] | str = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)
    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> 'PaperMetadata':
        """Construct PaperMetadata from a dictionary of front matter keys."""
    def to_dict(self) -> dict[str, Any]:
        """Serialize metadata into a dict ordered by canonical FRONT_MATTER_ORDER."""
```

<a id="domain-span-py"></a>

## `domain/span.py` ([source](../../src/tomd/domain/span.py))

Typed: 14 of 14 functions and methods (100%).

```python
"""Distributed under the Boost Software License, Version 1.0. (See accompanying

file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)

Official repository: https://github.com/cppalliance/wg21-paperflow
"""

@dataclass(frozen=True)
class CodeSpan(Span):
    """Inline code snippet leaf."""
    code: str
    @property
    def text(self) -> str: ...

@dataclass(frozen=True)
class ContainerSpan(Span):
    """Base class for semantic inline spans that wrap child spans."""
    children: tuple[Span, ...] = field(default_factory=tuple)
    @classmethod
    def from_text(cls, text: str) -> Self:
        # calls: TextSpan
        ...
    def map_text(self, fn: Callable[[str], str]) -> Self: ...
    def role_text(self, target_type: type[Span]) -> str: ...
    @property
    def text(self) -> str: ...
    def unwrap(self, target_type: type[Span]) -> tuple[Span, ...]: ...

@dataclass(frozen=True)
class DeletedSpan(ContainerSpan):
    """Deleted wording text container."""
    wording_role: ClassVar[Literal['ins', 'del'] | None] = 'del'

@dataclass(frozen=True)
class EmphasisSpan(ContainerSpan):
    """Emphasized inline text container."""

@dataclass(frozen=True)
class InsertedSpan(ContainerSpan):
    """Inserted wording text container."""
    wording_role: ClassVar[Literal['ins', 'del'] | None] = 'ins'

@dataclass(frozen=True)
class LineBreakSpan(Span):
    """Hard line break within a block or table cell."""
    @property
    def text(self) -> str: ...

@dataclass(frozen=True)
class LinkSpan(ContainerSpan):
    """Hyperlinked inline text pointing to a target URL."""
    url: str = ''
    title: str | None = None
    @classmethod
    def from_text(cls, text: str, url: str = '', title: str | None = None) -> 'LinkSpan':
        # calls: TextSpan
        ...

@dataclass(frozen=True)
class Span:
    """Base class for all semantic inline text nodes."""
    wording_role: ClassVar[Literal['ins', 'del'] | None] = None
    def map_text(self, fn: Callable[[str], str]) -> Self:
        """Return a copy of this span with ``fn`` applied to plain text leaves."""
    def role_text(self, target_type: type['Span']) -> str:
        """Return concatenated plain text of spans matching ``target_type``."""
    @property
    def text(self) -> str:
        """Return recursive unformatted plain text of this span."""
    def unwrap(self, target_type: type['Span']) -> tuple['Span', ...]:
        """Return span sequence with ``target_type`` containers replaced by their children."""

@dataclass(frozen=True)
class StrongSpan(ContainerSpan):
    """Strongly emphasized inline text container."""

@dataclass(frozen=True)
class SubscriptSpan(ContainerSpan):
    """Subscript inline text container."""

@dataclass(frozen=True)
class SuperscriptSpan(ContainerSpan):
    """Superscript inline text container."""

@dataclass(frozen=True)
class TextSpan(Span):
    """Plain unformatted text leaf."""
    content: str
    def map_text(self, fn: Callable[[str], str]) -> Self: ...
    @property
    def text(self) -> str: ...
```

<a id="domain-table-py"></a>

## `domain/table.py` ([source](../../src/tomd/domain/table.py))

Typed: 11 of 11 functions and methods (100%).

```python
"""Distributed under the Boost Software License, Version 1.0. (See accompanying

file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)

Official repository: https://github.com/cppalliance/wg21-paperflow
"""

@dataclass
class Cell:
    """Base table cell container."""
    align: CellAlign = CellAlign.DEFAULT
    width: str | None = None
    def role_text(self, target_type: type[Span]) -> str:
        """Return concatenated plain text of inline spans matching ``target_type``."""
    @property
    def text(self) -> str:
        """Return plain unformatted text of this cell."""
    def unwrap_spans(self, target_type: type[Span]) -> Self:
        """Return a copy of this cell with ``target_type`` spans unwrapped."""

class CellAlign(StrEnum):
    """Cell text alignment."""
    LEFT = 'left'
    CENTER = 'center'
    RIGHT = 'right'
    DEFAULT = 'default'

@dataclass
class CodeCell(Cell):
    """Table cell containing a code block (e.g. Tony Tables)."""
    code: str = ''
    language: str = 'cpp'
    @property
    def text(self) -> str: ...

@dataclass
class Table(BlockElement):
    """Table structure with explicit headers, rows, and rendering strategy."""
    headers: list[Cell] = field(default_factory=list)
    rows: list[TableRow] = field(default_factory=list)
    strategy: TableStrategy = TableStrategy.PIPE
    caption: str | None = None
    def role_text(self, target_type: type[Span]) -> str: ...
    @property
    def text(self) -> str: ...
    def unwrap_spans(self, target_type: type[Span]) -> Self:
        # calls: TableRow
        ...

@dataclass
class TableRow:
    """A row of cells in a table body."""
    cells: list[Cell] = field(default_factory=list)

class TableStrategy(StrEnum):
    """Output rendering strategy for tables."""
    PIPE = 'pipe'

@dataclass
class TextCell(Cell):
    """Table cell containing inline formatted text spans."""
    spans: list[Span] = field(default_factory=list)
    @classmethod
    def from_text(cls, text: str, align: CellAlign = CellAlign.DEFAULT, width: str | None = None) -> 'TextCell':
        # calls: span.TextSpan
        ...
    def role_text(self, target_type: type[Span]) -> str: ...
    @property
    def text(self) -> str: ...
    def unwrap_spans(self, target_type: type[Span]) -> Self: ...
```

<a id="errors-py"></a>

## `errors.py` ([source](../../src/tomd/errors.py))

```python
"""Error hierarchy for the tomd converter."""

class CheckContentArgError(TomdError):
    """Raised when :func:`tomd.lib.check_content.check_paper_content` receives
    an unsupported source suffix.
    """

class TomdError(Exception):
    """Base class for tomd-raised exceptions."""

class UnsupportedSourceFormatError(TomdError):
    """Raised when a source path has a suffix other than ``.pdf`` / ``.html`` / ``.htm``."""
```

<a id="lib-init-py"></a>

## `lib/__init__.py` ([source](../../src/tomd/lib/__init__.py))

```python
"""Re-exports from tomd.lib.shared and tomd.lib.metadata_yaml for backward compatibility."""
```

<a id="lib-batch-py"></a>

## `lib/batch.py` ([source](../../src/tomd/lib/batch.py))

Typed: 5 of 5 functions and methods (100%).

```python
"""Shared parallel batch runner for tomd QA and content-check batches."""

@dataclass(frozen=True)
class BatchRunResult:
    """Outcome of a parallel or sequential batch run."""
    outcomes: tuple[tuple[str, TResult | Exception], ...]
    timed_out: tuple[str, ...]
    elapsed_sec: float

def format_batch_finished(elapsed_sec: float, total: int) -> str:
    """Return the trailing batch-finished line for stderr."""

def format_batch_progress_line(done: int, total: int, item_id: str, t0: float) -> str:
    """Return the carriage-return progress line for stderr."""

def format_batch_timeout(timed_out: Sequence[str], timeout_sec: int) -> str:
    """Return the timeout abort line for stderr."""

def run_parallel_batch(items: list[tuple[str, TItem]], worker: Callable[[TItem], TResult], *, workers: int = 1, timeout_sec: int = 120, poll_interval_sec: float = _DEFAULT_POLL_INTERVAL_SEC, on_progress: ProgressCallback | None = None) -> BatchRunResult[TResult]:
    """Run *worker* over *items* with optional process parallelism.

    Each entry in *items* is ``(item_id, payload)``. Progress fires
    after each completion with ``ProgressEvent.step`` equal to the
    1-based completion count (matching existing QA/content-check output).
    """
    # calls: BatchRunResult, _fire_progress
    # called by: check_content.run_content_check_batch, qa.run_qa_batch

# + 1 private module-level name
```

<a id="lib-body-init-py"></a>

## `lib/body/__init__.py` ([source](../../src/tomd/lib/body/__init__.py))

```python
"""Body content processing for WG21 paper markdown output."""
```

<a id="lib-body-abstract-py"></a>

## `lib/body/abstract.py` ([source](../../src/tomd/lib/body/abstract.py))

Typed: 8 of 8 functions and methods (100%).

```python
"""Body cleanup: abstract dedup and metadata-echo removal from UNCERTAIN sections."""

def dedup_abstract(sections: list[Section]) -> None:
    """Remove duplicate Abstract headings, keeping the one with body content.

    After TOC stripping, the real Abstract heading (from the metadata zone)
    and a protected TOC entry for "Abstract" can both survive. This removes
    the empty duplicate. Mutates *sections* in-place.
    """
    # called by: pipeline.run_pipeline

def promote_abstract_from_uncertain(sections: list[Section]) -> None:
    """Promote an Abstract heading + body out of a page-0 UNCERTAIN section.

    When dual extraction disagrees on page 0, the Abstract heading and its
    body paragraph can end up merged into a single UNCERTAIN section. This
    prevents downstream phases (strip_pre_content_paragraphs) from
    recognizing Abstract as a content boundary. This function splits the
    UNCERTAIN section into proper HEADING + PARAGRAPH sections so the
    Abstract survives metadata stripping.

    Guards (all must hold for the function to fire):
    - No existing content heading (numbered or known-section name) exists
      on page 0. If one exists, strip_pre_content_paragraphs already has a
      boundary and the Abstract would not be stripped.
    - No existing Abstract HEADING exists on page 0 (a duplicate on a later
      page is caught by dedup_abstract downstream).
    - The abstract body must contain at least 10 words.

    Must run BEFORE strip_pre_content_paragraphs in the pipeline.
    Mutates *sections* in-place.
    """
    # calls: types.Section
    # called by: pipeline.run_pipeline

def reorder_abstract_in_uncertain(sections: list[Section]) -> None:
    """Move Abstract block to the top of UNCERTAIN sections on page 0.

    Two-column PDFs often have CONTENTS and body text extracted before
    the Abstract (which sits at the bottom of page 0). This finds the
    Abstract heading within the UNCERTAIN text and moves it (plus its
    paragraph) to the beginning. Mutates *sections* in-place.
    """
    # called by: pipeline.run_pipeline

def rescue_stranded_abstract_body(sections: list[Section]) -> None:
    """Move a paragraph stranded after the next heading back under Abstract.

    In two-column PDFs, column-aware sorting emits all left-column content
    before right-column content.  When the Abstract heading and the next
    heading (e.g. Background) are both in the left column, the abstract
    body text (top of the right column, same y-level) ends up after the
    next heading.  This detects the pattern and moves the paragraph back.

    Detection: Abstract HEADING at *i* is immediately followed by another
    HEADING at *i+1* (no body).  A PARAGRAPH on page 0 exists at *i+2*.
    The paragraph's top-y is closer to the Abstract heading's top-y than
    to the intervening heading's top-y, confirming it was in the opposite
    column at the Abstract's vertical level.

    Mutates *sections* in-place.
    """
    # calls: _section_top_y
    # called by: pipeline.run_pipeline

def strip_metadata_from_uncertain(sections: list[Section], metadata: dict) -> None:
    """Remove lines from UNCERTAIN sections that echo front-matter metadata.

    Two-column PDFs and UNCERTAIN regions often contain a raw dump of
    page 0 including the metadata block. Since metadata is already in the
    YAML front matter, these lines are duplicates. Strips both labeled
    lines (``Date: ...``) and bare values (``January 22, 2026``).
    Mutates *sections* in-place.
    """
    # calls: _build_bare_value_matchers, _is_bare_metadata_value
    # called by: pipeline.run_pipeline

# + 3 private module-level names
```

<a id="lib-check-content-py"></a>

## `lib/check_content.py` ([source](../../src/tomd/lib/check_content.py))

Typed: 25 of 25 functions and methods (100%).

```python
"""Content-coverage check: does the converted Markdown represent the source?

Complement to ``lib.pdf.qa``. QA scores structure on Markdown alone;
this module compares source text against the converted Markdown and
flags drops, truncations, and tool-emitted artefacts.

Headline metric is *coverage*: the fraction of source-text tokens that
appear in the Markdown. A second metric, *drift*, measures the
opposite (tokens in Markdown that are not in the source). Both run on
a normalized token stream; structural classification (heading vs
paragraph vs code) is QA's job, not this module's.

The "markdown-only" rule in ``lib.pdf.qa`` is QA-specific. This
sibling reads both source and Markdown by design.

See ``check_content_arch.md`` (colocated) for the algorithm
walkthrough: pipeline steps, techniques by layer, named constants,
edge cases, and the calibration plan for ``_COVERAGE_NEEDS_REVIEW``.
"""

@dataclass(frozen=True)
class ContentCheckBatchResult:
    """Outcome of a batch content-coverage check."""
    results: tuple[ContentCheckResult, ...]
    skipped: tuple[tuple[str, str], ...]
    errors: tuple[tuple[str, str], ...]
    timed_out: tuple[str, ...]
    elapsed_sec: float

@dataclass(frozen=True)
class ContentCheckResult:
    """Per-paper content-coverage result.

    ``coverage`` is the share of *source* tokens whose shingles appear
    in the Markdown; ``drift`` is the share of *markdown* tokens whose
    shingles do not appear in the source. Both are in ``[0.0, 1.0]``.

    ``unigram_coverage`` / ``unigram_drift`` are the same measures at the
    single-token (word) level, ignoring order. They are a complementary
    signal: a large ``unigram_coverage - coverage`` gap means the text is
    present but locally reformatted (faithful, e.g. PDF reflow or stripped
    furniture), whereas a low ``unigram_coverage`` means content is genuinely
    missing. Trustworthy as "faithful" only alongside low drift; never a
    pass/fail gate on its own.

    Coverage will never reach 1.0 in practice: tomd intentionally
    strips headers, footers, page numbers, and tables of contents, so
    the source extraction always carries content the Markdown cannot.
    """
    paper_id: str
    source_format: Literal['pdf', 'html']
    coverage: float
    drift: float
    # Same metrics at the single-token level (order-insensitive). Placed
    # among the non-default fields (before missing_regions/extra_regions,
    # which carry defaults): a non-default field cannot follow a defaulted
    # one. check_paper_content always supplies them; old JSON is handled in
    # _result_from_dict.
    unigram_coverage: float
    unigram_drift: float
    source_token_count: int
    markdown_token_count: int
    missing_regions: tuple[MisalignedRegion, ...] = field(default_factory=tuple)
    extra_regions: tuple[MisalignedRegion, ...] = field(default_factory=tuple)

@dataclass(frozen=True)
class MisalignedRegion:
    """A contiguous run of tokens present on one side but not the other.

    ``side`` is the side the tokens came from. Source-side regions are
    "missing" (in the PDF/HTML, dropped by tomd); Markdown-side regions
    are "extra" (in the Markdown without a counterpart in the source).
    """
    side: Literal['source', 'markdown']
    token_start: int
    token_end: int
    sample: str
    page: int | None = None

def check_paper_content(pid: str, backend: StorageBackend) -> ContentCheckResult:
    """Run the content-coverage check for one paper.

    Reads source and Markdown through the backend, then delegates to
    :func:`compute_content_coverage`. Library function: returns data,
    never persists. The CLI module owns reporting.

    Raises:
        paperstore.MissingSourceError: if ``<pid>.pdf|.html`` not staged.
        paperstore.MissingPaperMdError: if ``<pid>.md`` not written.
        tomd.CheckContentArgError: if the source suffix is neither
            ``.pdf`` nor ``.html``.
    """
    # calls: compute_content_coverage
    # called by: _check_one_from_paths

def compute_content_coverage(source_path: Path, md_text: str, paper_id: str | None = None) -> ContentCheckResult:
    """Content-coverage of ``md_text`` against ``source_path``, source agnostic.

    The path-and-string core of :func:`check_paper_content`. Used by the
    golden-QA fidelity gate to score a candidate ideal against its source
    without staging it in a backend.

    Raises:
        tomd.CheckContentArgError: if the source suffix is neither
            ``.pdf`` nor ``.html``.
    """
    # calls: _extract_pdf_stream, _extract_html_stream, errors.CheckContentArgError, _extract_markdown_stream, _shingle_hashes, _multiset_coverage, _local_coverage_windows, _regions_from_opcodes, _dedup_regions, ContentCheckResult
    # called by: check_paper_content, golden_qa.fidelity_verdict

def format_content_check_report(results: Sequence[ContentCheckResult], skipped: Sequence[tuple[str, str]], errors: Sequence[tuple[str, str]]) -> str:
    """Return the ranked content-check report text for stdout."""

def run_content_check_batch(items: list[tuple[str, Path]], *, workers: int = 1, timeout: int = _CHECK_BATCH_TIMEOUT_SEC, on_progress: ProgressCallback | None = None) -> ContentCheckBatchResult:
    """Run check-content for each ``(paper_id, workspace_dir)`` pair.

    CLI-adjacent: callers format output via :func:`format_content_check_report`.

    Parallel workers, straggler timeout, and ranked summary data. The
    workspace path travels with each item so workers can open their own
    backend (a ``StorageBackend`` does not survive ``pickle``-based IPC
    reliably).
    """
    # calls: batch.run_parallel_batch, _accumulate, ContentCheckBatchResult

def write_content_check_json_atomic(json_path: Path, results: Sequence[ContentCheckResult]) -> None:
    """Atomically write per-paper content-check metrics as JSON."""
    # calls: _result_to_dict

# + 21 private module-level names
```

<a id="lib-golden-compare-py"></a>

## `lib/golden_compare.py` ([source](../../src/tomd/lib/golden_compare.py))

Typed: 18 of 19 functions and methods (94%).

```python
"""Deterministic structural comparator for golden QA.

Parses two Markdown strings into a normalized block tree and scores how
well they match across six independent axes (front-matter, heading, list,
code, table, per-block text). Pure: no I/O, no LLM, no pipeline state.
Same inputs always give the same score.
"""

@dataclass
class AxisScore:
    name: str
    score: float
    detail: str = ''
    sub: dict[str, float] = field(default_factory=dict)

@dataclass
class Block:
    kind: str  # "heading" | "paragraph" | "list" | "code" | "table"
    text: str = ''
    level: int = 0
    items: tuple[ListEntry, ...] = ()
    code_lang: str = ''
    code_lines: int = 0
    table_rows: int = 0
    table_cols: int = 0

@dataclass(frozen=True)
class ListEntry:
    depth: int
    ordered: bool
    marker: str
    text: str

@dataclass
class NormalizedDoc:
    front_matter_keys: tuple[str, ...]
    blocks: list[Block] = field(default_factory=list)

@dataclass
class StructuralScore:
    axes: dict[str, AxisScore]
    composite: float
    worst_present_axis: str

def compare(tomd_md: str, golden_md: str) -> StructuralScore:
    # calls: normalize, _frontmatter_axis, _heading_axis, _list_axis, _code_axis, _table_axis, _text_axis, _present_axes, StructuralScore
    # called by: golden_gaps.locate_gaps, golden_qa.issue_for_stem, golden_qa.score_report, golden_qa.score_result, golden_qa.score_stem
    ...

def normalize(md_text: str) -> NormalizedDoc:
    # calls: _block_from_token, NormalizedDoc, _front_matter_keys
    # called by: compare, golden_gaps.locate_gaps
    ...

# + 17 private module-level names
```

<a id="lib-golden-gaps-py"></a>

## `lib/golden_gaps.py` ([source](../../src/tomd/lib/golden_gaps.py))

Typed: 8 of 8 functions and methods (100%).

```python
"""Deterministic gap locator and issue drafter for golden QA.

A reporting layer on top of the comparator (`golden_compare`): it locates the
per-axis divergences between tomd's output and the blessed ideal, then drafts
ready-to-file GitHub issues carrying the objectivity triple (axis score, located
divergence, violated contract rule). Pure: no LLM, no network, no `gh` calls.
The maintainer reviews a draft and files it by hand.
"""

@dataclass(frozen=True)
class Gap:
    axis: str  # "frontmatter" | "heading" | "list" | "code" | "table" | "text"
    kind: str  # "wrong-level" | "missing" | "extra" | "wrong" | "drift"
    tomd: str  # what tomd produced
    ideal: str  # what the ideal has
    rule: str  # the cited contract rule the divergence violates

def draft_issues(stem: str, gaps: list[Gap], scores: dict[str, float]) -> list[str]:
    """One ready-to-file issue draft per axis that has gaps.

    Each draft carries the objectivity triple: the axis score, the located
    divergences, and the cited contract rule, plus a repro command and a
    suggested origin module.
    """
    # called by: golden_qa.issue_for_stem

def locate_gaps(tomd_md: str, ideal_md: str) -> list[Gap]:
    """Locate the per-axis divergences between tomd output and the ideal.

    Heading gaps are granular (which heading, what level); list/code/table/
    front-matter gaps are coarse (count or dimension mismatch); the text gap is
    a single drift flag when the verbatim-text axis falls below 1.0.
    """
    # calls: golden_compare.normalize, _frontmatter_gaps, _heading_gaps, _list_gaps, _code_gaps, _table_gaps, golden_compare.compare, Gap
    # called by: golden_qa.issue_for_stem

# + 6 private module-level names
```

<a id="lib-golden-qa-py"></a>

## `lib/golden_qa.py` ([source](../../src/tomd/lib/golden_qa.py))

Typed: 28 of 30 functions and methods (93%).

```python
"""Golden QA orchestration helpers: locate a paper's source, convert it with
tomd, and score it against its blessed ideal.

Scoring and gap helpers are pure (return data). The three orchestrator
functions that drive the dev workflow -- `generate_ideal`, `bless_stem`, and
`rebless_stems` -- own their own persistence: they write the ideal file and
the baselines manifest as part of their contract. The CLI in `cli.py` calls
them and reports results; it does not re-persist what they have already written.
"""

@dataclass(frozen=True)
class AxisReport:
    axis: str
    current: float
    baseline: float | None
    delta: float | None
    detail: str
    sub: dict[str, float]

@dataclass(frozen=True)
class FidelityVerdict:
    ok: bool
    coverage: float
    drift: float
    reason: str = ''

@dataclass(frozen=True)
class ReblessOutcome:
    stem: str
    old: dict[str, float]
    new: dict[str, float]
    lowered: dict[str, tuple[float, float]]  # axis -> (old, new) where new < old
    whisker_verdict: str | None = None  # "pass"/"review"/"fail", or None if unavailable

@dataclass(frozen=True)
class ScoreResult:
    """Full score output: structural axes plus optional whisker and comprehension panels."""
    axes: list[AxisReport]
    whisker: dict | None  # whisker score-file JSON, or None if unavailable
    comprehension: dict | None  # whisker check-facts JSON, or None if no facts/anchors

def anchors_path(golden_dir: Path, stem: str) -> Path:
    """Path to the anchors JSON for `stem` (anchors/<stem>.anchors.json)."""
    # called by: cli._cmd_anchor, _call_whisker_check_facts

def bless_stem(stem: str, golden_dir: Path, manifest: Path) -> dict[str, float]:
    """Validate `<stem>.ideal.md` against its source, then merge its baseline
    row into `manifest`. Raises ValueError if the candidate fails the gate.
    """
    # calls: find_source, ideal_path, fidelity_verdict, is_unedited_seed, _call_whisker_score_file, score_stem
    # called by: cli._cmd_bless

def build_review_prompt(stem: str, src: Path, golden_dir: Path, candidate_md: str, skill_text: str = '') -> str:
    """The structural-review prompt: the tomd-review contract plus concrete inputs.

    `skill_text` is the canonical contract (the tomd-review SKILL.md), embedded so
    the command and interactive use share one source of truth; when empty a stub
    fallback is used. PDF source points at the pre-rendered page images; HTML is
    embedded inline.
    """
    # called by: review_ideal

def download_source(stem: str, golden_dir: Path, *, opener=_fetch) -> Path:
    """Download the WG21 source for `stem` from wg21.link into the golden dir.

    Follows the wg21.link redirect to the canonical PDF or HTML and saves it as
    `<stem>.<ext>`. Network is used only here; the rest of the QA flow is offline.
    `opener(url) -> (final_url, bytes)` is injectable for testing.
    """
    # untyped: opener
    # calls: source_dir, _source_ext
    # called by: cli._cmd_add, generate_ideal

def facts_path(golden_dir: Path, stem: str) -> Path:
    """Path to the facts JSONL for `stem` (facts/<stem>.facts.jsonl)."""
    # called by: cli._cmd_fact, _call_whisker_check_facts

def fidelity_verdict(source_path: Path, candidate_md: str) -> FidelityVerdict:
    """Coarse "not gutted" guard: does the candidate ideal still contain the
    source's content?

    Catches an ideal that DROPPED or gutted a large fraction of the paper. It
    does NOT detect paraphrase: shingled coverage is blind to rewording that
    keeps the vocabulary, and a faithful ideal scores about the same as tomd's
    own output (~0.84 coverage / ~0.11 drift on P4228R0). The human review at
    bless time is the authority on verbatim content; do not lean on this gate
    for that.
    """
    # calls: check_content.compute_content_coverage, FidelityVerdict
    # called by: cli._cmd_bless, bless_stem

def find_source(stem: str, golden_dir: Path) -> Path | None:
    """The staged source for `stem`: a PDF or HTML file under sources/."""
    # calls: source_dir
    # called by: cli._cmd_add, cli._cmd_bless, cli._cmd_render, bless_stem, generate_ideal, issue_for_stem, rebless_stems, review_ideal, score_result, tomd_markdown

def generate_ideal(stem: str, golden_dir: Path) -> Path:
    """Seed a candidate ideal for `stem` from tomd's OWN conversion (no LLM).

    The starting draft for the human to correct. It runs the same conversion
    `score_stem` compares against, so a freshly seeded ideal is byte-identical to
    tomd's output and scores 1.0 on every axis. tomd already gets the content
    right; the human edits the draft's STRUCTURE toward what the source shows
    (heading levels, list nesting, fences, tables), and that correction is what
    opens the gap the gate then tracks. Cheap and instant: no model, no tokens.
    Optionally run `review_ideal` for an LLM punch-list of suspected divergences,
    then `bless_stem` (with human review) is the gate.
    """
    # calls: find_source, download_source, ideal_path
    # called by: cli._cmd_generate

def ideal_path(golden_dir: Path, stem: str) -> Path:
    """Path to the blessed ideal for `stem` (ideals/<stem>.md)."""
    # called by: cli._cmd_bless, bless_stem, generate_ideal, is_unedited_seed, issue_for_stem, rebless_stems, review_ideal, score_report, score_result, score_stem

def is_unedited_seed(stem: str, golden_dir: Path) -> bool:
    """True if `stem`'s ideal is byte-identical to tomd's current conversion.

    The signature of a raw `generate` seed that was never hand-corrected: a
    genuine structural correction makes the ideal differ from tomd's output (and
    the comparator scores semantically, so even a structurally-perfect corrected
    ideal differs byte-wise from tomd's emit). Identity therefore means the
    correction step was skipped, so the ideal tests nothing the byte-exact
    snapshot net does not already cover. Returns False if either side is missing.
    """
    # calls: tomd_markdown, ideal_path
    # called by: bless_stem

def issue_for_stem(stem: str, golden_dir: Path) -> list[str]:
    """Locate gaps for `stem` and draft one ready-to-file issue per defect axis."""
    # calls: tomd_markdown, ideal_path, golden_gaps.locate_gaps, golden_compare.compare, golden_gaps.draft_issues, find_source, _call_whisker_score_file, _format_region_snippets
    # called by: cli._cmd_issue

def rebless_stems(stems: list[str], golden_dir: Path, manifest: Path, *, force: bool = False) -> list[ReblessOutcome]:
    """Recompute baselines for `stems` and write them, ratcheting UP only.

    The routine ratchet after a verified tomd improvement: it raises each
    paper's baseline to the current score. It refuses (raises ValueError,
    leaving the manifest untouched) if any axis would drop below its committed
    baseline, unless `force` is set, so a careless rebless cannot enshrine the
    regression the gate exists to catch.
    """
    # calls: score_stem, tomd_markdown, find_source, ideal_path, _call_whisker_score_file, ReblessOutcome
    # called by: cli._cmd_rebless

def render_pdf_pages(pdf_path: Path, out_dir: Path, dpi: int = _RENDER_DPI) -> list[Path]:
    """Render each page of `pdf_path` to a PNG in `out_dir`; return written paths.

    Page images are the vision input for the tomd-review step (PDF sources):
    transient build artifacts, not committed fixtures.
    """
    # called by: cli._cmd_add, cli._cmd_render, review_ideal

def review_ideal(stem: str, golden_dir: Path, *, runner=_claude_runner) -> str:
    """LLM structural review of `stem`'s candidate ideal against its source.

    The optional de-anchoring step: because the seed comes from tomd, a human can
    rubber-stamp tomd's own structural mistakes. This asks an LLM to compare the
    source to the candidate ideal and return a punch-list of suspected STRUCTURAL
    divergences (never verbatim content). Returns the punch-list text; the caller
    prints it. For PDFs it renders the page images if they are not already staged.
    `runner(prompt, golden_dir) -> text` is injectable for testing.
    """
    # untyped: runner
    # calls: find_source, ideal_path, render_pdf_pages, build_review_prompt, review_skill_text
    # called by: cli._cmd_review

def review_skill_text(golden_dir: Path) -> str:
    """The committed tomd-review skill contract, or '' if not present."""
    # calls: _repo_root
    # called by: review_ideal

def score_report(stem: str, golden_dir: Path, manifest: Path) -> list[AxisReport]:
    """Per-axis current score vs committed baseline, with deltas and sub-signals.

    The human-facing superset of :func:`score_stem`: each row carries the
    committed baseline, the delta, the axis detail string, and (for heading)
    the sub-signals, so the CLI can print a self-explaining table.
    """
    # calls: tomd_markdown, ideal_path, golden_compare.compare, AxisReport

def score_result(stem: str, golden_dir: Path, manifest: Path) -> ScoreResult:
    """Full score: structural axes, whisker metrics panel, comprehension panel.

    Superset of :func:`score_report`. The whisker and comprehension panels are
    None when whisker is unavailable or no facts/anchors files exist. The
    structural axes are always present.
    """
    # calls: tomd_markdown, ideal_path, golden_compare.compare, AxisReport, find_source, _call_whisker_score_file, _call_whisker_check_facts, ScoreResult
    # called by: cli._cmd_score

def score_stem(stem: str, golden_dir: Path) -> dict[str, float]:
    """Per-axis structural score of tomd's output vs the blessed `<stem>.ideal.md`."""
    # calls: tomd_markdown, ideal_path, golden_compare.compare
    # called by: bless_stem, rebless_stems

def source_dir(golden_dir: Path) -> Path:
    # called by: download_source, find_source, stage_source
    ...

def stage_source(stem: str, source_path: Path, golden_dir: Path) -> Path:
    """Copy a source file into the golden dir as `<stem>.<ext>`; return the dest."""
    # calls: source_dir
    # called by: cli._cmd_add

def tomd_markdown(stem: str, golden_dir: Path) -> str | None:
    """Convert the staged source for `stem`, dispatching by source type."""
    # calls: find_source
    # called by: is_unedited_seed, issue_for_stem, rebless_stems, score_report, score_result, score_stem

def validate_anchors_json(data: dict) -> list[str]:
    """Validate an anchor spec dict. Returns list of error strings (empty = valid)."""
    # called by: cli._cmd_anchor

def validate_facts_jsonl(text: str) -> list[str]:
    """Validate JSONL fact assertions. Returns list of error strings (empty = valid)."""
    # called by: cli._cmd_fact

# + 7 private module-level names
```

<a id="lib-html-init-py"></a>

## `lib/html/__init__.py` ([source](../../src/tomd/lib/html/__init__.py))

```python
"""HTML to Markdown converter."""
```

<a id="lib-html-convert-py"></a>

## `lib/html/convert.py` ([source](../../src/tomd/lib/html/convert.py))

Typed: 1 of 1 functions and methods (100%).

```python
"""HTML to Markdown converter for WG21 papers."""

def convert_html(path: Path | os.PathLike[str], *, html_images_result: HtmlImagesResult | None = None) -> tuple[str, list[str] | None]:
    """Convert an HTML file to Markdown.

    Reads the file as UTF-8 (with replacement for decode errors). Returns
    ``(markdown_text, prompts_or_none)`` where ``prompts_or_none`` is a
    list of self-contained LLM reconcile prompts (one per flagged HTML
    conversion issue) or ``None`` when conversion was fully clean.

    ``<img>`` tags never reach the markdown (#408): the LLM consumer
    cannot use pixels, so no image syntax, raw ``data:`` URI, or
    unresolvable remote URL is emitted, with or without a manifest.
    ``html_images_result`` is still accepted so the caller can persist
    the sidecar files and so the truncation marker can disclose on-disk
    image counts.
    """
    # calls: extract.parse_html, extract.detect_generator, extract.extract_metadata, extract.strip_boilerplate, render.render_body
```

<a id="lib-html-extract-py"></a>

## `lib/html/extract.py` ([source](../../src/tomd/lib/html/extract.py))

Typed: 23 of 23 functions and methods (100%).

```python
"""HTML parsing, generator detection, metadata extraction, and boilerplate stripping."""

def detect_generator(soup: BeautifulSoup) -> str:
    """Identify which tool generated this HTML paper.

    Returns one of: "mpark", "bikeshed", "hackmd", "wg21", "schultke",
    "dascandy/fiets", "hatemplate", "hand-written", "unknown".
    Checks meta generator tag first, then structural heuristics.
    """
    # called by: check_content._extract_html_stream, convert.convert_html

def extract_metadata(soup: BeautifulSoup, generator: str) -> dict:
    """Extract WG21 metadata fields from the HTML.

    Two-phase architecture:
      Phase 1 -- generator-specific extractor (structural, high confidence).
      Phase 2 -- ``_enrich_reply_to`` post-pass that fills bare-name entries
                 with emails found anywhere in the metadata region.

    Returns a dict with possible keys: title, document, date,
    audience, reply-to.
    """
    # calls: _extract_mpark_metadata, _extract_bikeshed_metadata, _extract_handwritten_metadata, _extract_wg21_metadata, _extract_schultke_metadata, _extract_hatemplate_metadata, _extract_generic_metadata, _enrich_reply_to
    # called by: convert.convert_html

def parse_html(text: str) -> BeautifulSoup:
    """Parse HTML with the built-in parser (forgiving of malformed HTML)."""
    # called by: convert.convert_html

def strip_boilerplate(soup: BeautifulSoup, generator: str) -> list[str]:
    """Remove non-content elements from `soup` in-place.

    Returns list of problem descriptions.
    """
    # calls: _remove_title_h1
    # called by: check_content._extract_html_stream, convert.convert_html

# + 19 private module-level names
```

<a id="lib-html-images-py"></a>

## `lib/html/images.py` ([source](../../src/tomd/lib/html/images.py))

Typed: 1 of 1 functions and methods (100%).

```python
"""HTML side of the embedded-image flow.

Reads the typed ``<pid>.html-images.json`` manifest that the mailing
fetcher wrote alongside the source HTML, applies the same 20-image cap
the PDF path uses (see :mod:`tomd.lib.pdf.images`), and returns a list
of :class:`ExtractedImage` records for sidecar persistence accounting.

Pure module: no network, no disk reads of image bytes. The bytes are
already on disk from mailing time. The convert step no longer rewrites
``<img>`` references - images never reach the markdown (#408) - so this
result only feeds sidecar persistence accounting and the truncation
marker.
"""

@dataclass(frozen=True)
class HtmlImagesResult:
    """Output of :func:`load_html_images`.

    ``images`` is the capped, document-order list the caller persists
    as sidecar files; the renderer never emits image syntax (#408).
    """
    images: list[ExtractedImage] = field(default_factory=list)
    source_image_count: int = 0
    images_truncated: bool = False

def load_html_images(manifest: HtmlImagesManifest) -> HtmlImagesResult:
    """Build :class:`ExtractedImage` records from a parsed manifest.

    Cap matches the PDF path's :data:`_MAX_IMAGES_PER_PAPER`. Truncation
    drops images with the highest ``document_order`` so the kept set is
    the earliest ones. Caption priority for ``suggested_alt``:
    ``caption_text`` (from ``<figcaption>``) > ``alt_attr`` (from
    ``<img alt=...>``) > empty.

    ``ExtractedImage.bytes`` is the empty bytes sentinel here: the
    mailing fetcher already persisted the bytes at download time, so
    the convert orchestration must not re-write them. ``ExtractedImage.bbox``
    is ``(0, 0, 0, 0)`` because HTML has no spatial concept; document
    order is retained in ``index_on_page``.
    """
    # calls: images.ExtractedImage, HtmlImagesResult
    # called by: api._convert_with_tomd_full
```

<a id="lib-html-render-py"></a>

## `lib/html/render.py` ([source](../../src/tomd/lib/html/render.py))

Typed: 49 of 51 functions and methods (96%).

```python
"""DOM-to-Markdown rendering for WG21 HTML papers."""

def render_body(soup: BeautifulSoup, generator: str) -> str:
    """Render the HTML body to Markdown.

    Warning: this function may mutate the soup tree (extracting nested
    list elements). Do not reuse the soup object after calling this.
    """
    # calls: _normalize_eelis_wording, _fix_misnested_blocks, _fix_misnested_list_items, _fix_misnested_table_cells, _fix_misnested_dl_items, _wrap_bare_blockquote_inline, _normalize_heading_levels, _render_children
    # called by: convert.convert_html

# + 50 private module-level names
```

<a id="lib-metadata-yaml-init-py"></a>

## `lib/metadata_yaml/__init__.py` ([source](../../src/tomd/lib/metadata_yaml/__init__.py))

```python
"""Metadata extraction and YAML front matter formatting for WG21 papers.

Imports are deferred to avoid circular dependency with tomd.lib.shared.
Use direct imports from submodules:
  from tomd.lib.metadata_yaml.format import format_front_matter
  from tomd.lib.metadata_yaml.extract import extract_metadata
  from tomd.lib.metadata_yaml.strip import strip_metadata_headings
"""
```

<a id="lib-metadata-yaml-extract-py"></a>

## `lib/metadata_yaml/extract.py` ([source](../../src/tomd/lib/metadata_yaml/extract.py))

Typed: 3 of 3 functions and methods (100%).

```python
"""Metadata field extraction from PDF sections and blocks.

Pathway 1 (section-line regex scan) and safety-net email fallback.
"""

def apply_pdf_metadata_fallbacks(metadata: dict, path: Path, pdf_info_date: str | None, pdf_info_title: str | None, doc_metadata: dict, sections: list[Section], all_mupdf_blocks: list, title_pid_prefix_re: re.Pattern) -> None:
    """Fill missing metadata fields from PDF-info and filename fallbacks.

    Called after primary extraction (section-line scan + wg21 block scan)
    has populated what it can. This function applies lower-precedence
    fallbacks: document from filename, date from PDF info, title from
    first heading or PDF info, reply-to from PDF info author, and
    email enrichment from page-0 blocks.

    Mutates *metadata* in place.
    """
    # calls: shared.override_revision_from_filename, enrich_pdf_reply_to
    # called by: pipeline.run_pipeline

def enrich_pdf_reply_to(metadata: dict, blocks: list, *, max_lines: int = 30) -> None:
    """Safety-net post-pass: scan page 0 for emails missed by labeled extractors.

    Mirrors the HTML _enrich_reply_to pattern. Runs after wg21/structure merge.
    """
    # called by: apply_pdf_metadata_fallbacks, pipeline.run_pipeline

def extract_metadata(sections: list[Section]) -> tuple[dict[str, str | list[str]], list[Section]]:
    """Pull WG21 metadata fields from early sections into a dict.

    PDF section line scan (pathway 1 of 3). Lower precedence than
    wg21.extract_metadata_from_blocks; both are merged in convert_pdf.

    Returns (metadata_dict, remaining_sections).
    """
    # called by: pipeline.run_pipeline, structure.structure_sections
```

<a id="lib-metadata-yaml-format-py"></a>

## `lib/metadata_yaml/format.py` ([source](../../src/tomd/lib/metadata_yaml/format.py))

Typed: 7 of 8 functions and methods (87%).

```python
"""YAML front matter formatting and parsing for WG21 paper metadata.

Canonical field order, YAML serialization, and parsing. Single source of
truth for the strict-order contract described in CLAUDE.md.

``parse_front_matter`` recognizes only the shapes ``format_front_matter``
emits: scalar ``key: value`` (optionally double-quoted) and ``key:``
followed by indented ``- "item"`` lines.
"""

def format_front_matter(metadata: dict) -> str:
    """Format metadata dict as YAML front matter in strict canonical order.

    Strict-order contract: keys are emitted exactly in the order
    ``title, document, date, intent, audience, reply-to``. Missing keys
    are skipped (no placeholders, no blank lines). Unknown keys appear
    after ``audience`` so ``reply-to`` is always last. Callers and
    downstream tools may rely on this ordering for diffs and parsing.

    Title and values containing YAML-special characters are double-quoted
    with backslash-escaping for embedded quotes, backslashes, and newlines.
    Reply-to is a YAML list of double-quoted strings. Returns the empty
    string when ``metadata`` is empty.
    """
    # calls: _yaml_value
    # called by: api._normalize_front_matter, front_matter.write_front_matter, normalizers.normalize_front_matter

def parse_front_matter(md: str) -> FrontMatterDict:
    """Parse YAML front matter from markdown into a metadata dict.

    Scalar keys map to ``str``; list-valued keys (e.g. ``reply-to``) map to
    ``list[str]``. Returns an empty dict when no front matter block is present.
    """
    # calls: _parse_front_matter_body
    # called by: api._extract_intent_from_front_matter, api._normalize_front_matter, api.convert_paper_full, qa._count_mojibake, qa.compute_metrics, normalizers.normalize_front_matter, writer.MarkdownWriter.write

def sanitize_metadata(metadata: dict) -> dict:
    """Clean up extracted metadata values before formatting.

    Fixes: embedded newlines in title, metadata labels in title text,
    double angle brackets in reply-to entries, non-author reply-to values.
    """
    # called by: api._normalize_front_matter, normalizers.normalize_front_matter

def strip_front_matter(md: str) -> str:
    """Return markdown with the leading YAML front matter block removed."""
    # called by: api._normalize_front_matter, check_content._extract_markdown_stream, normalizers.normalize_front_matter

FRONT_MATTER_ORDER = ...

FRONT_MATTER_RE = ...

# + 4 private module-level names
```

<a id="lib-metadata-yaml-strip-py"></a>

## `lib/metadata_yaml/strip.py` ([source](../../src/tomd/lib/metadata_yaml/strip.py))

Typed: 7 of 7 functions and methods (100%).

```python
"""Strip metadata headings from page 0 that duplicate front-matter content."""

def strip_metadata_headings(sections: list[Section], metadata: dict) -> int:
    """Remove page-0 heading sections that duplicate front-matter metadata.

    Strips headings that contain document numbers, dates, author lists,
    category labels, or separator lines when the corresponding data is
    already captured in the YAML front matter. Only touches headings
    before the first content heading (numbered section or known section
    name like Abstract/Motivation).

    Returns the number of sections removed.
    """
    # calls: _is_content_heading, _title_stem_words, _matches_author_name
    # called by: pipeline.run_pipeline

def strip_pre_content_paragraphs(sections: list[Section]) -> int:
    """Strip page-0 paragraphs that sit before the first content heading.

    After strip_metadata_headings removes title-echo headings, metadata
    paragraphs (doc numbers, author affiliations) may become the leading
    sections. These are already captured in YAML front matter and must not
    appear in body. Mutates *sections* in-place.

    Returns the number of sections removed.
    """
    # calls: _is_content_heading, _looks_like_metadata_paragraph
    # called by: pipeline.run_pipeline

def strip_pre_heading_fragments(sections: list[Section]) -> int:
    """Strip non-heading page-0 sections that sit before the first heading.

    After metadata extraction, leftover sections (author names, doc numbers,
    affiliations) would otherwise appear as duplicate body text. This removes
    them. Mutates *sections* in-place.

    Returns the number of sections removed.
    """
    # called by: pipeline.run_pipeline

# + 4 private module-level names
```

<a id="lib-pdf-init-py"></a>

## `lib/pdf/__init__.py` ([source](../../src/tomd/lib/pdf/__init__.py))

```python
"""PDF to Markdown converter."""
```

<a id="lib-pdf-fitz-lock-py"></a>

## `lib/pdf/_fitz_lock.py` ([source](../../src/tomd/lib/pdf/_fitz_lock.py))

```python
"""Shared process-wide lock that must be held for all PyMuPDF (fitz) sessions."""
```

<a id="lib-pdf-cleanup-py"></a>

## `lib/pdf/cleanup.py` ([source](../../src/tomd/lib/pdf/cleanup.py))

Typed: 15 of 16 functions and methods (93%).

```python
"""Header/footer detection and text cleanup for PDF extraction."""

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

def cleanup_text(blocks: list[Block]) -> list[Block]:
    """Apply all text cleanup operations to extracted blocks."""
    # calls: _collapse_spaces, types.Line, types.Block, _join_cross_page, collect_hyphen_evidence, dehyphenate_pair
    # called by: pipeline.run_pipeline

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
    # calls: HyphenEvidence
    # called by: cleanup_text, structure._merge_paragraphs

def dehyphenate_pair(last_line: Line, next_line: Line, evidence: HyphenEvidence) -> DehyphenatedPair | None:
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
    # calls: _compound_seen, _keep_hyphen, types.Line, DehyphenatedPair
    # called by: cleanup_text, structure._merge_paragraphs

def detect_repeating(all_edge_items: list[list[PageEdgeItem]], total_pages: int, page_height: float = 0.0) -> set[tuple[float, str]]:
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
    # calls: _y_bucket
    # called by: pipeline.run_pipeline

def escape_leading_atx(text: str) -> str:
    """Backslash-escape a "#" that would turn a body block into a heading.

    The text is unchanged for readers; only Markdown's block parser is
    affected. Text already backslash-escaped upstream (the sub-caption path in
    ``emit._escape_italic_text``) does not match and is left alone. Shared by
    the paragraph and wording-prose renderers, the two emit paths that flatten
    PDF lines into a single body block.
    """
    # called by: emit._render_paragraph_spans, wording_emit._render_wording_section, blocks._format_wording_paragraph

def find_hidden_regions(page, body_fonts: set[str] | None = None) -> set[tuple[float, float, float, float]]:
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
    # untyped: page
    # called by: pipeline.run_pipeline

def get_edge_items(blocks: list[Block], page_num: int) -> list[PageEdgeItem]:
    """Get the top N and bottom N text items from a page by y-coordinate.

    Deduplicates by (text, rounded y-position) to avoid counting the
    same visual item twice when blocks overlap edge regions.
    """
    # calls: types.PageEdgeItem
    # called by: pipeline.run_pipeline

def normalize_whitespace(text: str) -> str:
    """Collapse runs of spaces, replace non-breaking spaces, strip trailing."""
    # calls: _collapse_spaces
    # called by: emit._render_paragraph_spans, wording_emit._render_wording_section, blocks._format_wording_paragraph

def strip_hidden_blocks(blocks: list[Block], hidden_by_page: dict[int, set[tuple[float, float, float, float]]]) -> list[Block]:
    """Remove blocks whose text is entirely within hidden regions.

    *hidden_by_page* maps page numbers to sets of bboxes so that
    hidden regions on one page cannot accidentally match visible
    text on a different page that happens to share the same
    coordinates.
    """
    # called by: pipeline.run_pipeline

def strip_repeating(blocks: list[Block], repeating: set[tuple[float, str]]) -> list[Block]:
    """Remove lines (or individual spans) matching repeating header/footer
    patterns from blocks.

    Spatial-path lines merge left/center/right header columns (one span
    per column). The whole-line text then won't match any single pattern,
    but each column-span will; per-span stripping handles that while
    preserving non-header content that shares the header y-coordinate
    (e.g. a one-off appendix title).
    """
    # calls: _is_edge_block, _y_bucket
    # called by: pipeline.run_pipeline

# + 6 private module-level names
```

<a id="lib-pdf-code-format-py"></a>

## `lib/pdf/code_format.py` ([source](../../src/tomd/lib/pdf/code_format.py))

Typed: 12 of 12 functions and methods (100%).

```python
"""Whitespace normalization for code-block lines.

WG21 PDFs encode C++ code with justified spacing that leaks into the
text layer as artifact spaces around punctuation that no human author
writes:

    template <typename From >
    [[ maybe_unused ]] To x = L:: lowest ();
    converting_limits_throws <To, From >()

These artifacts originate in PDF kerning + the dual-extraction word-gap
heuristic; they are not meaningful C++. This module rewrites the most
common patterns on a per-line basis, scoped to ``SectionKind.CODE``.

Conservative-by-default: any line containing a string or character
literal delimiter (``"`` or ``'``) is left untouched, since the rules
would otherwise corrupt literal contents (``"a < b"`` -> ``"a< b"``).
The corpus is template/declaration-heavy and rarely contains literals,
so the skip is a small loss for a large safety margin.

:func:`is_diagram_block` detects text-layer ASCII diagrams (box-drawing
glyphs, Unicode arrows, math symbols, pipe/slash art). When any line
in a CODE block trips a diagram signal, the whole block skips
:func:`normalize_code_line` so spacing is preserved verbatim.
"""

def is_diagram_block(lines: Iterable[str], *, math_symbols: bool = True) -> bool:
    """Return True when any line signals a text-layer ASCII diagram.

    Whole-block skip: one diagram line disables normalization for every
    line in the CODE section. Signals are box-drawing glyphs, Unicode
    arrows (ASCII ``->`` is deliberately excluded), math symbols
    (empty set, section sign, sub/superscript), and pipe/slash ASCII
    art whose characters are confined to spacing and diagram punctuation.

    ``math_symbols=False`` drops the math-symbol signal. It is a
    spacing-preservation signal, safe for the PDF caller (preserving
    spacing in real C++ costs nothing), but too weak to classify a
    block as non-code: WG21 papers cite clauses with ``§`` inside
    ordinary C++ comments.
    """
    # calls: _has_box_drawing, _has_unicode_arrow, _has_diagram_special, _is_ascii_art_line
    # called by: render._looks_like_diagram, emit._render_code_block, emit._render_code_block_with_gutter

def maybe_normalize_code_line(line: str, *, preserve_spacing: bool) -> str:
    """Normalize a code line unless the block is a diagram (spacing preserved)."""
    # calls: normalize_code_line
    # called by: emit._render_code_block, emit._render_code_block_with_gutter

def normalize_code_line(line: str) -> str:
    """Tighten PDF-kerning artifact whitespace on a single code line.

    Operates on the line text (indented or not; leading whitespace is
    preserved). Returns the input unchanged for:

    * lines containing string/character literal delimiters (``"`` / ``'``),
    * preprocessor directives (``#include <hdr>`` must keep its space),
    * lines whose *code* portion (everything before the first ``//``)

    The literal check runs on the code portion only, so a quote that
    lives in a trailing comment (``vector <From> result; // don't``)
    no longer disables tightening of the code. This stays safe even
    when a ``//`` sits inside a string literal: the split leaves the
    opening quote in the code portion, so the literal check still trips
    and the line is returned untouched.

    All tightening rules then apply only to the pre-``//`` portion, so
    identifiers in trailing comments (``// also in <proxy>``) are never
    mistaken for template names.
    """
    # calls: _is_preprocessor_directive, _split_at_line_comment, _has_string_literal, _tighten_ident_open_angle, _tighten_ident_open_paren
    # called by: maybe_normalize_code_line, wording_emit._render_wording_code_block, wording_emit._render_wording_code_diff_line, wording_emit._role_tag

# + 9 private module-level names
```

<a id="lib-pdf-code-grid-py"></a>

## `lib/pdf/code_grid.py` ([source](../../src/tomd/lib/pdf/code_grid.py))

Typed: 5 of 5 functions and methods (100%).

```python
"""Character-grid reconstruction from PDF glyph x-positions.

PDF text extraction does not preserve the leading whitespace of code
lines reliably: indentation is carried by glyph x-coordinates, not by
space characters in the text layer. To render a fenced code block we
reconstruct the character column of each glyph from its x-position
relative to a grid origin, divided by the monospace character width.

``CodeGrid`` is that grid: an ``(origin_x, char_w)`` pair with two
operations. ``column`` maps a raw x to a character column; ``indent``
maps a whole line to its leading-space count, reconciling the
x-derived indent against the literal text indent (the x-position is the
source of truth; the literal count is trusted only when it agrees).

The two classmethods encode the two ways the grid origin and width are
chosen in practice:

* ``for_code_section`` - origin at the block's left margin (leftmost
  content glyph), width sampled from any multi-glyph span. Used for
  plain code blocks and code-shaped wording diffs.
* ``for_gutter`` - origin supplied by the caller (the leftmost gutter
  glyph), width sampled from monospace spans only so a multi-digit
  serif line number cannot be measured as the code character width.

The non-monospace vs monospace-only width split between the two
constructors is intentional and preserved; unifying it is a separate
semantic change that would move golden output.
"""

@dataclass(frozen=True)
class CodeGrid:
    """A character grid for reconstructing code-line indentation.

    ``origin_x`` is the x-coordinate that maps to column 0; ``char_w``
    is the monospace character width in points.
    """
    origin_x: float
    char_w: float
    def column(self, x: float) -> int:
        """Character column for a glyph x, clamped at zero.

        Returns 0 when the character width is non-positive (a section
        with nothing measurable to scale by), matching the conservative
        no-indent fallback.
        """
        # called by: CodeGrid.indent
    @classmethod
    def for_code_section(cls, sec: Section) -> 'CodeGrid':
        """Grid with origin at the block left margin, width from mono spans.

        The origin samples each line's first *content* span (the same
        accessor :meth:`indent` uses), not ``spans[0]``: a line whose
        leading span is whitespace-only would otherwise be dropped from
        the origin computation, and if every line started that way the
        origin fell back to ``0.0`` and inflated every reconstructed
        indent.

        Width estimation passes ``mono_only=True`` so a proportional
        (serif) leading comment cannot be the first qualifying span and
        skew the per-character pitch for the monospace code that
        follows. :meth:`for_gutter` already uses the same constraint.
        """
        # calls: _estimate_char_width
        # called by: emit._render_code_block, wording_emit._render_wording_code_block, wording_emit._render_wording_code_diff
    @classmethod
    def for_gutter(cls, sec: Section, origin_x: float) -> 'CodeGrid':
        """Grid with a caller-supplied origin, width from mono spans only."""
        # calls: _estimate_char_width
        # called by: emit._render_code_block_with_gutter
    def indent(self, line: Line, *, max_indent: int | None = None) -> int:
        """Leading-space count for a code line.

        Reconciles the x-derived indent against the literal text indent:
        when both are positive and agree, the literal count is used;
        otherwise the x-derived column wins (it is the reliable signal),
        falling back to the literal count only when the x-derived column
        is zero. When ``max_indent`` is given and the result exceeds it,
        returns 0: an implausibly deep indent means the line's first
        glyph is a right-margin element extraction split onto its own
        line, not real nesting, so it is pinned to column zero.
        """
        # calls: CodeGrid.column

# + 1 private module-level name
```

<a id="lib-pdf-docling-backend-py"></a>

## `lib/pdf/docling_backend.py` ([source](../../src/tomd/lib/pdf/docling_backend.py))

Typed: 12 of 13 functions and methods (92%).

```python
"""Docling ML backend for table enrichment and discovery.

Provides table structure detection via Docling's TableFormer model,
combined with PyMuPDF spans for font-rich cell content. Docling is an
optional dependency (requires ``pip install docling``); all functions
degrade gracefully when it is unavailable.

Architecture: "Enrichment + Discovery"
  - tomd's rule-based detect_tables() remains the master for table
    detection AND positioning (page_num, lines, insertion order).
  - Docling runs separately to detect table cell grids.
  - enrich_tables_with_docling() matches rule-based Sections to
    Docling-detected tables by page + bbox overlap, then replaces
    the rule-based columns grid with Docling's cell structure
    (populated with PyMuPDF spans for font metadata preservation).
  - discover_tables_with_docling() finds Docling tables that have
    no rule-based counterpart (borderless tables the heuristic
    detector missed), builds TABLE sections from remaining blocks,
    and removes consumed blocks so they don't become paragraphs.
  - Sections that don't match any Docling table are left unchanged.
"""

def absorb_cross_page_spec_rows(table_sections: list[Section], remaining_blocks: list[Block], docling_tables: dict[int, list[dict]]) -> list[Block]:
    """Absorb orphaned data rows from the previous page into SPEC_TABLE sections.

    When a spec table spans two pages, the first page may contain the
    repeated header and one or more data rows that were not detected as a
    table (e.g. because MuPDF's phantom-table guard rejected the
    full-page bbox).  This function finds such orphaned rows, builds
    grid entries, and inserts them into the enriched SPEC_TABLE grid.

    Returns the updated *remaining_blocks* with consumed blocks removed.
    """
    # calls: types.Span
    # called by: pipeline.run_pipeline

def discover_tables_with_docling(docling_tables: dict[int, list[dict]], remaining_blocks: list[Block], existing_table_sections: list[Section]) -> tuple[list[Section], list[Block]]:
    """Discover tables that only Docling detected (rule-based missed).

    For each Docling table that does NOT overlap any existing rule-based
    TABLE section, collects PyMuPDF blocks within the table bbox, builds
    a cell grid populated with spans, classifies, and creates a new
    ``Section(kind=TABLE)``.

    Returns ``(new_table_sections, updated_remaining_blocks)`` where
    consumed blocks have been removed from the remaining list.
    """
    # calls: _section_y_range, _y_iou, _blocks_in_bbox, _collect_spans_for_cell, table._classify_and_annotate, _render_table_text, types.Section
    # called by: pipeline.run_pipeline

def docling_available() -> bool:
    """Return True if the docling package is importable."""
    # called by: extract_docling_tables, pipeline.run_pipeline

def enrich_tables_with_docling(table_sections: list[Section], docling_tables: dict[int, list[dict]], remaining_blocks: list[Block] | None = None) -> int:
    """Enrich rule-based table sections with Docling cell grids.

    For each rule-based TABLE section, finds the best-matching Docling
    table on the same page (by y-range IoU).  When matched, replaces
    the section's ``columns`` grid with Docling's cell structure,
    populated with PyMuPDF spans (preserving font metadata).

    Spans are collected from the section's own lines AND from
    *remaining_blocks* on the same page that fall within the Docling
    table bbox.  This ensures that header rows or boundary rows
    excluded by the rule-based detector (but included in Docling's
    grid) still get populated with PyMuPDF spans.

    The section's ``kind``, ``page_num``, ``lines``, and positioning
    are NOT changed -- only the cell content grid is replaced.

    Mutates *table_sections* in place.  Returns the number of sections
    that were enriched.
    """
    # calls: _section_y_range, _y_iou, _flat_spans_from_section, _blocks_in_bbox, _collect_spans_for_cell, table._classify_and_annotate
    # called by: pipeline.run_pipeline

def extract_docling_tables(pdf_path: Path) -> dict[int, list[dict]]:
    """Run Docling on *pdf_path* and return per-page table structures.

    Returns ``{page_num: [table_info, ...]}`` where each *table_info*
    is a dict with keys:

    - ``bbox``: normalized (x0, y0, x1, y1) of the full table
    - ``num_rows``: int
    - ``num_cols``: int
    - ``cells``: list of dicts with ``row``, ``col``, ``row_span``,
      ``col_span``, ``bbox``, ``text``

    Returns an empty dict on failure or when Docling is unavailable.
    """
    # calls: docling_available, _normalize_table_bbox
    # called by: pipeline.run_pipeline

# + 8 private module-level names
```

<a id="lib-pdf-emit-py"></a>

## `lib/pdf/emit.py` ([source](../../src/tomd/lib/pdf/emit.py))

Typed: 42 of 42 functions and methods (100%).

```python
"""Markdown and companion prompts file generation."""

def emit_markdown(metadata: dict, sections: list[Section], *, annotate: bool = False, images_truncated: bool = False, source_image_count: int = 0, vector_uncertainty: VectorUncertaintyStats | None = None, glyph_stats: GlyphPassStats | None = None) -> str:
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
    # calls: _assign_emdash_nesting, _annotate_wrap, _render_section_md, is_flagged_table, levels.comment, vector_images.should_emit_marker, vector_images.format_uncertainty_marker, shared._find_front_matter_end, renumber_uncertain_markers
    # called by: pipeline.run_pipeline

def emit_prompts(sections: list[Section]) -> list[str] | None:
    """Generate self-contained LLM reconcile prompts for uncertain regions.

    Each returned element is a complete prompt the operator can paste into
    any LLM verbatim. Returns ``None`` when there are no uncertain regions.
    """
    # calls: is_flagged_table, _table_prompt
    # called by: pipeline.run_pipeline

def is_flagged_table(sec: Section) -> bool:
    """A TABLE section no second kind of evidence confirmed (select.trust_tables)."""
    # called by: _is_flagged, emit_markdown, emit_prompts

def renumber_uncertain_markers(md: str) -> str:
    """Point every ``tomd:uncertain:L{a}-L{b}`` marker at the lines under it.

    Emit numbers the markers as it writes them; later rewrites (duplicate
    paragraphs collapsed, the table style block, front matter normalized,
    the contents stripped) shift lines. Each marker keeps the number of lines
    it covers and is renumbered from its own position: the covered text
    starts two lines below the marker.
    """
    # called by: api.convert_paper_full, emit_markdown, pipeline._insert_after_front_matter

# The single Markdown unordered-list marker this converter emits, at every
# nesting depth. "-" over "*" because the HTML renderer already emits "-", the
# blessed ideals standardize on it, and it cannot be read as emphasis if a
# stray bullet glyph survives mid-text (#303).
LIST_BULLET = '-'

# + 38 private module-level names
```

<a id="lib-pdf-emoji-data-py"></a>

## `lib/pdf/emoji_data.py` ([source](../../src/tomd/lib/pdf/emoji_data.py))

```python
"""Vendored Unicode ``Emoji_Presentation`` ranges (GENERATED - do not edit).

Regenerate with ``study/emoji-glyphs/generate_emoji_presentation.py``.
Source: Unicode ``emoji-data.txt`` (UTS #51), Version: 17.0.

A codepoint with ``Emoji_Presentation=Yes`` defaults to emoji (colour
glyph) rendering. ``tomd.lib.pdf.glyphs`` uses these ranges to detect
text-layer emoji for the placeholder coincidence filter.
"""

# (start, end) inclusive codepoint ranges, sorted and merged.
EMOJI_PRESENTATION_RANGES: tuple[tuple[int, int], ...] = ...

UNICODE_EMOJI_VERSION = '17.0'
```

<a id="lib-pdf-evidence-py"></a>

## `lib/pdf/evidence.py` ([source](../../src/tomd/lib/pdf/evidence.py))

Typed: 1 of 4 functions and methods (25%).

```python
"""The evidence record: what every table reader saw, nominated and rejected, and why.

A reader that looks at an area and decides "not a table" records the area, the
rule that decided, and the kind of information the rule used. Later steps (the
region scan, the prompts, the paper summary) read the record instead of each
reader's private verdict, so nothing is dropped without a trace.

One record per conversion, held by the run's context (``runctx.RunContext``).

Information types: "words" (text positions), "paths" (drawn lines, boxes,
shading), "tree" (tagged structure), "meaning" (content kinds, poll
vocabulary, code similarity), "document" (captions, counts, generator).
"""

@dataclass
class Entry:
    kind: str  # "nominated" | "excluded" | "feature"
    scan: str  # which reader or check wrote it
    page: int
    bbox: Box
    rule: str  # the rule that decided (or the feature's name)
    info: str  # information type the rule used
    value: object = None  # a feature's value, or extra detail
    observed: bool = True  # observed on the page, or inferred

@dataclass
class Record:
    entries: list[Entry] = field(default_factory=list)
    # every candidate reading: (source, page, bbox, rows of cell text)
    readings: list[tuple] = field(default_factory=list)
    # readers, checks and specialists that raised: never swallowed silently
    errors: list[dict] = field(default_factory=list)
    def exclude(self, scan: str, page: int, bbox: Box, rule: str, info: str, value=None) -> None:
        # untyped: value
        # calls: Entry
        ...
    def feature(self, scan: str, page: int, bbox: Box, name: str, info: str, value, observed: bool = True) -> None:
        # untyped: value
        # calls: Entry
        ...
    def nominate(self, scan: str, page: int, bbox: Box, cue: str, info: str, value=None) -> None:
        # untyped: value
        # calls: Entry
        ...
    def on_page(self, page: int, kind: str | None = None) -> list[Entry]: ...

# Exceptions that mean the code is wrong, not the PDF: the release gate fails on any of them.
CODE_ERRORS = ...
```

<a id="lib-pdf-extract-py"></a>

## `lib/pdf/extract.py` ([source](../../src/tomd/lib/pdf/extract.py))

Typed: 1 of 4 functions and methods (25%).

```python
"""Dual-path PDF text extraction: MuPDF grouping and spatial rules."""

def attach_links(blocks: list[Block], links: list[dict]) -> None:
    """Match link annotations to text spans by bounding rect overlap.

    Mutates spans in-place (sets `link_url`). If multiple links
    overlap the same span, the best-overlap link wins.
    """
    # called by: pipeline.run_pipeline

def collect_links(page) -> list[dict]:
    """Collect hyperlink annotations from a page.

    Returns a list of dicts with 'uri' and 'bbox' keys.
    Only http, https, and mailto schemes are kept.
    """
    # untyped: page
    # called by: pipeline.run_pipeline

def extract_mupdf(page, page_num: int) -> list[Block]:
    """Extract text using MuPDF's built-in block/line/span hierarchy.

    Uses page.get_text("dict"). Returns MuPDF's interpretation of
    paragraphs, lines, and word groupings with font metadata preserved.
    """
    # untyped: page
    # calls: types.Span, mono.classify_monospace, types.Line, types.Block
    # called by: pipeline.run_pipeline

def extract_spatial(page, page_num: int) -> list[Block]:
    """Extract text using raw character coordinates and spatial rules.

    Uses page.get_text("rawdict") for per-character bounding boxes.
    Classifies each consecutive character pair via four elif branches,
    using font-size-relative named constants from types.py:

      dy > PARA_SPACING_RATIO * avg_fs  -> flush block (paragraph break)
      dy > LINE_SPACING_RATIO * avg_fs  -> flush line (new line, same block)
      dy > WORD_GAP_RATIO    * avg_fs  -> flush line (large vertical gap)
      dx > WORD_GAP_RATIO    * avg_fs  -> flush word + insert space span
    """
    # untyped: page
    # calls: types.Span, mono.classify_monospace, types.compute_bbox, types.Line, types.Block
    # called by: pipeline.run_pipeline
```

<a id="lib-pdf-figures-py"></a>

## `lib/pdf/figures.py` ([source](../../src/tomd/lib/pdf/figures.py))

Typed: 18 of 18 functions and methods (100%).

```python
"""Detect inline figure regions (flow diagrams, box-arrow figures) from PDF
vector graphics.

Uses page.get_drawings() to find bordered rectangles (boxes with stroke color)
that appear 2+ times in proximity, indicating a diagram rather than body text.

Design B (conservative): detection only produces figure region bboxes.
No blocks are excluded from extraction.  The heading guard in structure.py
uses these bboxes to re-classify diagram text as SectionKind.FIGURE instead
of HEADING.
"""

def detect_figure_regions(drawings: list[dict], page_num: int, page_width: float) -> list[FigureRegion]:
    """Detect figure regions on a single page from its vector drawings.

    Returns a list of FigureRegion for regions that contain 2+ bordered
    boxes in close proximity (indicating a flow diagram or similar figure).

    Args:
        drawings: output of page.get_drawings()
        page_num: 0-based page number
        page_width: page width in points (for filtering page-wide rects)
    """
    # calls: _is_bordered_box, _is_arrowhead, _is_connector, _is_dashed_connector, _group_boxes, _merge_connected_groups, _absorb_adjacent_groups, _group_bbox, _connector_in_region, _match_topology, types.FigureRegion
    # called by: pipeline.run_pipeline

# + 17 private module-level names
```

<a id="lib-pdf-glyphs-py"></a>

## `lib/pdf/glyphs.py` ([source](../../src/tomd/lib/pdf/glyphs.py))

Typed: 13 of 13 functions and methods (100%).

```python
"""Inline glyph-placeholder pass: sub-threshold raster glyphs -> U+FFFD.

Some PDFs embed emoji (and other symbols the chosen font cannot
represent) as tiny raster image XObjects, typically 8-18pt. The figure
path drops anything below :data:`tomd.lib.pdf.images.MIN_IMAGE_DIM_PT`
because such glyphs are not figures. When the emoji exists *only* as the
raster (no text-layer codepoint), it would vanish from the output
silently. This pass records each such glyph by injecting the Unicode
REPLACEMENT CHARACTER U+FFFD (``UNKNOWN_GLYPH``) into the body-text
stream at the glyph's reading-order position.

It does **not** try to recover *which* emoji it was: that is the
forward-compatible recovery feature (see
``notes/emoji-glyph-utf8-recovery-plan.md``), which swaps
:func:`glyph_to_char` for a Noto hash-match with ``UNKNOWN_GLYPH`` as
its fallback. The placement machinery here is reused unchanged.

Coincidence filter: a few papers ship both a text-layer emoji codepoint
*and* a raster glyph of the same emoji at the same on-page position. The
codepoint is already in the markdown, so injecting a placeholder there
would duplicate content (``X`` -> ``X<placeholder>``). Such rects are
detected by position against text-layer emoji (Unicode
``Emoji_Presentation`` property, plus VS16-qualified text-default emoji)
and skipped.

Library code returns/mutates data; the CLI owns persistence. This module
mutates the block lists passed to :func:`inject_glyph_spans` in place.
"""

@dataclass(frozen=True)
class GlyphCandidate:
    """One sub-threshold raster rect, before coincidence filtering.

    ``page`` is 1-based (matching ``pymupdf`` page numbering and
    :class:`tomd.lib.pdf.images.ExtractedImage.page`); the recovery
    feature extends this dataclass with a perceptual-hash field.
    """
    page: int
    bbox: tuple[float, float, float, float]

@dataclass
class GlyphPassStats:
    """Per-paper accounting for the glyph-placeholder pass.

    ``injected`` counts placeholders actually placed (orphan rects);
    ``skipped_coincident`` counts rects dropped because a text-layer
    emoji codepoint already covered the position; ``free_standing``
    counts injected placeholders that fell back to a synthesised
    single-line block (a subset of ``injected``); ``skipped_code_section``
    counts placeholders removed post-structure because the line they
    attached to became a CODE or TABLE section (a subset of the
    originally ``injected`` count).
    """
    injected: int = 0
    skipped_coincident: int = 0
    free_standing: int = 0
    skipped_code_section: int = 0
    @property
    def fired(self) -> bool:
        """True if the pass produced anything worth disclosing."""

def collect_glyph_candidates(page: 'pymupdf.Page') -> list[GlyphCandidate]:
    """Return one :class:`GlyphCandidate` per sub-threshold image rect.

    Enumerates ``page.get_images(full=True)`` and, for each xref, every
    rect from ``page.get_image_rects(xref)`` whose smaller dimension is
    below :data:`MIN_IMAGE_DIM_PT` - the same threshold the figure path
    uses to drop these.

    Dedup is **by on-page position, not by xref**: one visual glyph is
    one placeholder. A single emoji xref drawn at N *distinct* positions
    yields N candidates (unlike :func:`finalize_extraction`, which would
    collapse them to one), but exact-duplicate rects at the *same*
    position - which ``get_image_rects`` emits repeatedly when an xref
    recurs in the resource dict - collapse to one. Two distinct glyphs
    cannot share an identical rect, so position dedup is lossless.
    """
    # calls: GlyphCandidate
    # called by: pipeline.run_pipeline

def collect_text_emoji_bboxes(page: 'pymupdf.Page') -> list[tuple[float, float, float, float]]:
    """Return per-character bboxes of text-layer emoji on the page.

    Reads ``page.get_text("rawdict")`` (the only ``get_text`` shape that
    exposes per-character bboxes via the ``chars`` key; the plain
    ``dict`` shape gives span-level bboxes only). A character is a
    text-layer emoji when its codepoint has ``Emoji_Presentation=Yes``,
    or when it is immediately followed by U+FE0F (VS16), which forces
    emoji presentation of a text-default base. U+FE0F and U+200D (ZWJ)
    never contribute their own bbox.
    """
    # calls: _is_emoji_presentation
    # called by: pipeline.run_pipeline

def drop_glyphs_in_code_and_tables(sections: list[Section]) -> int:
    """Remove placeholder spans that landed inside CODE/TABLE sections.

    Injection runs before structure, so a glyph may attach to a line that
    structure later classifies as CODE (rendered in a fenced block, where
    a U+FFFD reads as a syntax error) or that table detection folds into a
    TABLE (rendered structurally from ``columns``). Such placeholders are
    removed here in place and the count returned, so the caller can record
    it in ``GlyphPassStats.skipped_code_section`` and the marker can
    disclose the loss rather than letting a `�` corrupt code/table output.

    Membership-based: a glyph is "in" a section iff it attached to one of
    that section's lines or table cells. A glyph belongs to exactly one
    line, hence one section, so there is no bbox-overlap "straddle" and no
    overlap threshold applies (this differs from the vector-image
    structural filter, which tests bbox overlap because vectors are not
    line-anchored).
    """
    # called by: pipeline.run_pipeline

def filter_coincident(candidates: list[GlyphCandidate], text_emoji_by_page: dict[int, list[tuple[float, float, float, float]]], *, tolerance: float = _GLYPH_COINCIDENT_TOLERANCE_PT) -> tuple[list[GlyphCandidate], int]:
    """Split candidates into (orphans, skipped_coincident_count).

    A candidate is coincident when its centre lies within ``tolerance``
    of any text-layer emoji centre **on the same page** - the text
    codepoint already carries the content, so a placeholder there would
    duplicate it. Coincidence is per-position, not per-paper: text emoji
    elsewhere on the page do not suppress an orphan glyph.
    """
    # calls: _bbox_centre
    # called by: pipeline.run_pipeline

def glyph_to_char(cand: GlyphCandidate) -> str:
    """Return the character to emit for a glyph candidate.

    This is the swap seam for the recovery feature. Today every glyph
    becomes the ``UNKNOWN_GLYPH`` placeholder.
    """
    # called by: inject_glyph_spans

def inject_glyph_spans(blocks: list[Block], candidates: list[GlyphCandidate], *, y_tolerance: float = _GLYPH_LINE_Y_TOLERANCE_PT) -> GlyphPassStats:
    """Inject one placeholder span per candidate into ``blocks`` in place.

    For each candidate (processed in ``(page, y0, x0)`` order) the line
    whose y-range contains the glyph centre receives a synthetic span at
    its x-ordered position; the containing :class:`Line` and
    :class:`Block` bboxes are recomputed. When several lines qualify on
    the y axis (multi-column layouts put two columns at the same y), the
    line whose **x-range covers the glyph centre** wins, so a right-column
    glyph attaches to the right-column line; ties (and the no-x-cover
    case) break on smallest y-distance. A candidate with no line within
    ``y_tolerance`` falls back to a synthesised single-line block appended
    to ``blocks`` (counted as ``free_standing``).

    Returns a :class:`GlyphPassStats` with ``injected`` and
    ``free_standing`` populated; ``skipped_coincident`` is the caller's
    to set from :func:`filter_coincident`. The caller runs this once per
    extraction path with the same orphan list; the two paths hold
    independent block objects, so mutating one never aliases the other.
    """
    # calls: GlyphPassStats, _bbox_centre, glyph_to_char, _make_glyph_span, _recompute_line_bbox, _recompute_block_bbox, types.Line, types.Block
    # called by: pipeline.run_pipeline

def is_glyph_only_block(block: Block) -> bool:
    """True if every non-empty span in the block is a glyph placeholder.

    Used by structure.py to keep a synthesised free-standing placeholder
    block out of position-based list detection.
    """

# Synthetic font name marking an injected glyph span. Shared with the
# recovery feature: mono.py / spans.py / structure.py key their
# inert-span short-circuits off this exact constant, so it must be one
# name, not a per-feature literal.
GLYPH_FONT_SENTINEL = 'tomd-glyph'

# Emitted at end-of-body when the pass fired. ``placeholders`` is the
# count of U+FFFD actually present in the emitted body (computed by
# emit.py after duplicate-paragraph collapse), so a reader grepping the
# file finds a matching number. ``skipped_coincident`` is the count of
# sub-threshold rects suppressed because a text-layer emoji codepoint
# already covered the position - those carry no body character, so they
# are reported here for traceability rather than counted in the body.
# ``skipped_code_section`` counts placeholders removed post-structure
# because the line they attached to became part of a CODE or TABLE
# section (a U+FFFD inside a fenced code block reads as a syntax error;
# a table renders structurally). Those carry no body character either.
GLYPH_PLACEHOLDER_MARKER_TEMPLATE = ...

# The character emitted for an unrecoverable embedded glyph. U+FFFD
# REPLACEMENT CHARACTER is Unicode's canonical "a character that could
# not be represented."
UNKNOWN_GLYPH = '�'

# + 5 private module-level names
```

<a id="lib-pdf-images-py"></a>

## `lib/pdf/images.py` ([source](../../src/tomd/lib/pdf/images.py))

Typed: 5 of 6 functions and methods (83%).

```python
"""Embedded raster image extraction (Resource-Dictionary path).

Independent of the MuPDF dict and spatial rawdict text-extraction paths.
This module reads each page's resource dictionary via
``page.get_images(full=True)`` to enumerate the raster image XObjects
referenced by the page, looks up their on-page rectangles via
``page.get_image_rects(xref)``, and pulls the raw bytes via
``doc.extract_image(xref)``. Captions are recovered by a regex over
spatial-path text blocks near each image's bbox.

What this path sees: every embedded JPEG / PNG / JPX, regardless of
rendering.

What this path does NOT see, by design:

- Vector drawings (paths and lines, e.g. flowcharts and graph diagrams).
  ``pymupdf`` does not expose them as images. Page-region rasterisation
  is a future feature; see ``packages/tomd/improvements.md`` section 4
  for the layout-aware extraction path that would unlock this.
- Scanned-page PDFs whose body is one image per page. They trip the
  ``_MAX_IMAGES_PER_PAPER`` cap; see the same reference.

Outputs feed :class:`SectionKind.IMAGE` sections. Library code returns
data and never writes to disk; the CLI orchestration in ``cli.convert``
persists ``ExtractedImage.bytes`` via ``backend.write_paper_image``.
"""

@dataclass(frozen=True)
class ExtractedImage:
    """One embedded raster image kept for emission to markdown.

    All fields except ``index_on_page`` and ``stored_filename`` are
    derived during the per-page extraction phase; the index and the
    filename are assigned by :func:`finalize_extraction` after global
    xref deduplication, so that the position numbering reflects the
    final canonical (page, y0, x0) order rather than ``pymupdf``'s
    enumeration.

    Field semantics across the two producer paths:

    - **PDF (this module)**: every field is populated. ``bytes`` carries
      the raw embedded-raster bytes pulled via ``doc.extract_image``.
      The CLI convert orchestration persists those bytes via
      ``backend.write_paper_image``.
    - **HTML (tomd.lib.html.images)**: built from the
      ``HtmlImagesManifest`` sidecar that mailing already wrote to
      disk. ``bytes`` is the empty bytes sentinel ``b""`` (the bytes
      are already on disk; no re-write needed), ``bbox`` is
      ``(0.0, 0.0, 0.0, 0.0)`` (HTML has no spatial concept), and
      ``xref`` is ``0`` (not applicable). ``page`` is ``0`` (the
      paperstore-wide "no page concept" sentinel). The CLI
      orchestration in ``cli.process._stage_convert`` checks
      ``bytes`` truthiness to decide whether to call
      ``write_paper_image``.
    """
    page: int  # 1-based for PDF, 0 for HTML
    index_on_page: int  # 1-based, after y/x sort
    ext: str  # "png" | "jpeg" | "jpx" | ...
    bytes: bytes  # empty for HTML
    bbox: tuple[float, float, float, float]  # (x0, y0, x1, y1); zeros for HTML
    suggested_alt: str
    stored_filename: str  # "<pid>-fig{page}-{index}.{ext}"
    xref: int  # PDF xref; 0 for HTML
    source: ImageSource = 'raster'  # "raster" (embedded XObject) | "vector" (rasterised clusters)
    # Sub-captions captured by ``pipeline._filter_sections_inside_vector_images``.
    # Each entry is ``(letter, full_text)`` where ``letter`` is the
    # ``_SUB_CAPTION_RE`` letter group (``"a"``, ``"b"``, ...) and
    # ``full_text`` is the dropped section's full text (``Section.text``).
    # Tuple, not list - this dataclass is frozen, and a mutable list
    # default would invite hidden append-mutation. Empty for raster
    # papers and any vector image without a captured sub-caption.
    sub_captions: tuple[tuple[str, str], ...] = ()
    # True when the pipeline dropped this image's overall body caption
    # section (the ``_normalize_caption`` equality gate in
    # ``pipeline._filter_sections_inside_vector_images``). Emit keys on
    # this: only then is the caption re-emitted as an italic paragraph -
    # when the gate kept the body (caption merged with trailing prose),
    # the body still carries the caption and re-emitting would
    # duplicate it (#408). Always False for HTML images (their body is
    # never filtered) and for images without alt-text attribution.
    caption_body_dropped: bool = False

@dataclass(frozen=True)
class ExtractionResult:
    """Output of :func:`finalize_extraction`.

    - ``images``: up to :data:`_MAX_IMAGES_PER_PAPER` entries, sorted
      by ``(page, bbox.y0, bbox.x0)``. Empty iff the document has no
      embedded raster images.
    - ``source_image_count``: number of unique xrefs in the source,
      regardless of cap. The CLI logs ``kept M of N`` from this field.
    - ``images_truncated``: True iff ``source_image_count`` exceeded
      the cap.
    - ``vector_uncertainty``: per-paper vector-extraction accounting,
      or ``None`` for raster-only or HTML papers. The emit step
      reads it to decide whether to append the uncertainty marker.
    """
    images: list[ExtractedImage]
    source_image_count: int
    images_truncated: bool
    vector_uncertainty: VectorUncertaintyStats | None = None

@dataclass(frozen=True)
class VectorUncertaintyStats:
    """Per-paper accounting of the vector-extraction filter pipeline.

    Surfaced as the trailing ``tomd:vector-extraction-uncertain`` marker
    appended to ``paper.md`` when extraction was attempted and at least
    one cluster was rejected or at least one page was skipped. Field
    semantics are documented in the vector-extraction plan's section
    1.6a; the closed key set for ``reasons`` is enforced by tests.

    All counts are non-negative integers. ``reasons`` is a frozen
    mapping ``reason -> count`` where reason is one of:
    ``clusters_overflow``, ``edge_band``, ``text_overlap``,
    ``too_few_items``, ``too_small``, ``wording_color``.
    """
    pages_scanned: int
    candidates: int
    kept: int
    rejected: int
    reasons: Mapping[str, int]
    pages_skipped: int

def extract_page_images(page: 'pymupdf.Page', page_blocks: Sequence['Block']) -> list[_PageImageCandidate]:
    """Enumerate embedded raster images for a single page.

    Called per page inside step 1 of the pipeline (the document must
    still be open). Reads ``page.get_images(full=True)``, looks up
    bbox rectangles via ``page.get_image_rects(xref)``, pulls bytes
    via ``doc.extract_image(xref)``, and runs the caption-proximity
    heuristic over the provided spatial-path text blocks for this page.

    Returns one :class:`_PageImageCandidate` per image rect on the
    page. Cross-page deduplication and capping happen later in
    :func:`finalize_extraction`.
    """
    # calls: _bbox_to_tuple, _caption_for, _PageImageCandidate
    # called by: pipeline.run_pipeline

def finalize_extraction(per_page: Iterable[Iterable[_PageImageCandidate]], pid: str, *, vector_stats: '_VectorExtractionStats | None' = None) -> ExtractionResult:
    """Dedupe by xref, apply the cap, assign stable filenames.

    ``per_page`` is the per-page candidate lists from
    :func:`extract_page_images`. ``pid`` is the lowercased paper id
    used for the ``<pid>-fig{page}-{index}.{ext}`` filenames.

    Steps:

    1. Flatten all candidates into one list.
    2. Group by ``xref``. For each unique xref, pick the
       smallest ``(page, bbox.y0, bbox.x0)`` rect as canonical.
       Other rects of the same xref produce no output - a logo that
       appears on every page contributes one IMAGE section, at its
       first occurrence.
    3. Sort the unique-xref representatives by their canonical
       ``(page, y0, x0)``.
    4. Truncate to :data:`_MAX_IMAGES_PER_PAPER`.
    5. Within each surviving image's first-occurrence page, assign
       ``index_on_page`` after sorting that page's survivors by
       ``(y0, x0)`` - so filenames stay stable across ``pymupdf``
       major-version bumps that might change ``get_images``'s order.
    """
    # calls: ExtractedImage, VectorUncertaintyStats, ExtractionResult
    # called by: pipeline.run_pipeline

# Minimum bbox dimension (smaller of width, height) for an embedded
# raster to be treated as a figure. Anything smaller is assumed to be
# a font-replacement glyph - PDF renderers embed inline emoji as tiny
# PNGs (typically 8-18pt) when the font can't represent the codepoint.
# Such glyphs are not figures: they have no caption, no standalone
# meaning, and their natural pixel resolution (often 64x64+) does
# not match their on-page rendered size. Promoting them to IMAGE
# sections (a) inserts phantom figures at wrong y-positions in the
# markdown, (b) produces over-sized renderings in the preview, and
# (c) inflates the cap (corpus survey N5007: 107 inline emoji, all
# under 18pt). 20pt is calibrated to survey: smallest genuine figure
# bbox in the workspace is 24x24, comfortably above the threshold.
# Public (no underscore) because the glyph-placeholder pass in
# ``glyphs.py`` shares this threshold as its single source of truth:
# rasters below it that the figure path drops are treated as
# font-replacement glyphs and emitted as a U+FFFD placeholder.
# Trade-off documented: papers where MuPDF's text path *also*
# extracts the emoji as a Unicode character (the common case)
# render the emoji correctly inline and the phantom IMAGE goes
# away. Papers where the emoji exists *only* as the embedded raster
# (N5007's editor's report) had the emoji lost from the output
# entirely before the glyph-placeholder pass; it now emits a
# ``U+FFFD`` placeholder at the glyph's position (see ``glyphs.py``).
MIN_IMAGE_DIM_PT = 20.0

# End-of-body HTML comment appended when the cap fires. Shared between
# the PDF emit path (tomd.lib.pdf.emit) and the HTML emit path
# (tomd.lib.html.convert) so the marker shape stays identical across
# source formats. Invisible to the rendered HTML; visible to anyone
# grepping the raw markdown for "truncated".
TRUNCATION_MARKER_TEMPLATE = ...

# + 4 private module-level names
```

<a id="lib-pdf-levels-py"></a>

## `lib/pdf/levels.py` ([source](../../src/tomd/lib/pdf/levels.py))

Typed: 4 of 4 functions and methods (100%).

```python
"""Graded table levels (L0-L5) and cell markers, from the table's own evidence.

HIGH / UNCERTAIN says only whether to trust a table; a reader of the output
(an agent evaluating the paper) also needs to know how a flagged table may be
wrong, so it can tell a nearly-right reading from a misattributed one:

  L0 trusted               HIGH: independent sources agree
  L1 likely                flagged, but the words fit the drawn cells evenly
  L2 minor                 flagged on one source only; every check on content passed
  L3 structure uncertain   readers disagree, the fit or layout check failed, relational
                           violations, the extent is open (a table may continue)
  L4 content at risk       text duplicated or misattributed (conservation surplus),
                           damaged text, cells read out of order, a reader error, repaired
     L4 incomplete         text of the area missing from the cells, nothing duplicated or
                           out of order: content missing, what is there is not contradicted
  L5 mark only             a possible table that was not produced (a mark, not a table)

The most severe level that applies is the table's level. Cell markers list the
cells where the table's alternative readings (same shape) disagree. Levels are
metadata: the table's content is unchanged.
"""

def assign(sec: Section) -> dict:
    """{"level", "name", "why", "incomplete", "cells"} for a table section."""
    # calls: cell_markers
    # called by: pipeline.run_pipeline

def cell_markers(sec: Section) -> list[tuple[int, int]]:
    """Cells where an alternative reading of the same shape disagrees with the table."""
    # calls: _rows
    # called by: assign

def comment(info: dict) -> str:
    """The ``tomd:level`` comment written above a flagged table."""
    # called by: emit.emit_markdown

NAMES = ...

# First level shown in the Markdown: L0 and L1 carry no level comment.
SHOWN_FROM = 2

# + 1 private module-level name
```

<a id="lib-pdf-mono-py"></a>

## `lib/pdf/mono.py` ([source](../../src/tomd/lib/pdf/mono.py))

Typed: 8 of 8 functions and methods (100%).

```python
"""Triple-signal monospace font detection.

Three independent signals:
  1. Font name decomposition (strip modifiers, split camelCase, check keywords)
  2. Glyph bounding box widths are uniform (low coefficient of variation)
  3. Glyph x-origin spacing is uniform (measures advance width directly)

Acceptance rules:
  - Two or more signals agreeing: accept (high confidence)
  - Signal 3 alone: accept (measures the defining property of monospace)
  - Signal 1 alone: accept (fallback when no glyph data is available)
  - Signal 2 alone: reject (weakest signal, bbox widths are noisy)

The spatial extraction path (rawdict) provides per-character data for signals
2 and 3. The MuPDF dict path does not. The pipeline orchestrator propagates
spatial glyph-width decisions to MuPDF spans of the same font after extraction.
"""

def classify_monospace(font_name: str, char_widths: list[float] | None = None, char_x_origins: list[float] | None = None, chars: list[str] | None = None) -> bool:
    """Accept or reject monospace classification from available signals.

    Called during extraction when raw character data is available
    (all three signals), or later with just font_name (signal 1 only).
    When chars and char_x_origins are provided, compares advance widths
    (x-origin spacings) of fat characters (M, W) against thin characters
    (i, l) to reject proportional fonts early. Advance widths are uniform
    in monospace fonts regardless of glyph body width, so the ratio of fat
    to thin advance widths is close to 1.0 for monospace and much larger
    for proportional fonts.
    """
    # calls: _font_name_is_monospace, _glyph_widths_uniform, _glyph_spacing_uniform
    # called by: extract.extract_mupdf, extract.extract_spatial, propagate_monospace, ruled._chars_to_lines, ruled._page_words, tagged._lines_of

def propagate_monospace(mupdf_blocks: list[Block], spatial_blocks: list[Block], dominant_font: str) -> None:
    """Apply spatial path's glyph-width monospace decisions to MuPDF spans.

    Only propagates fonts whose spatial spans are mostly classified
    monospace (by character count). Short spans of digits or thin
    characters can false-positive the per-glyph signal, so requiring a
    majority keeps proportional fonts (e.g. a regular text font with a
    handful of "1" or "3.1" spans) out of the mono set.

    The dominant_font is still discarded unless it passes a
    name-based mono check, to avoid body text leaking into code blocks
    when metrics happen to agree across a majority.
    """
    # calls: classify_monospace
    # called by: pipeline.run_pipeline

# + 6 private module-level names
```

<a id="lib-pdf-pagecache-py"></a>

## `lib/pdf/pagecache.py` ([source](../../src/tomd/lib/pdf/pagecache.py))

Typed: 1 of 2 functions and methods (50%).

```python
"""One rawdict extraction per page, shared by the readers that need characters.
The cache lives on the document object, so it goes away with it and is never
shared between conversions.
"""

def rawdict(page):
    # untyped: page, return
    # calls: _dedup_raw
    # called by: poll.extract_poll_tables, ruled._grid_tables_in, ruled.extract_ruled_tables
    ...

# + 1 private module-level name
```

<a id="lib-pdf-pipeline-py"></a>

## `lib/pdf/pipeline.py` ([source](../../src/tomd/lib/pdf/pipeline.py))

Typed: 29 of 40 functions and methods (72%).

```python
"""PDF to Markdown converter - pipeline entry point."""

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
    md: str = ''
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
    def for_skip(cls, reason: SkipReason, *, page_count: int = 0, prompts: list[str] | None = None, readable: bool = True) -> 'PipelineResult':
        """Construct a complete skip result.

        Single source of truth for exit-condition fields on early-exit
        paths; bypasses partial-build mutation. Named ``for_skip`` (not
        ``skipped``) to avoid shadowing the ``skipped`` dataclass field.
        """
        # called by: run_pipeline

def run_pipeline(path: Path, *, ml_tables: bool = False, visualize: bool = False, extract_vector: bool = False, whiteout_text: bool = False) -> PipelineResult:
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
    # calls: PipelineResult, images._VectorExtractionStats, _enforce_skip_contract, PipelineResult.for_skip, _is_slide_deck, _is_standards_draft, extract.extract_mupdf, extract.extract_spatial, cleanup.get_edge_items, extract.collect_links, extract.attach_links, images.extract_page_images, +77 more

# + 38 private module-level names
```

<a id="lib-pdf-poll-py"></a>

## `lib/pdf/poll.py` ([source](../../src/tomd/lib/pdf/poll.py))

Typed: 2 of 8 functions and methods (25%).

```python
"""WG21 poll result tables.

WG21 papers and minutes record straw polls in a fixed shape: a header line
"SF F N A SA" (Strongly For, For, Neutral, Against, Strongly Against) with
the vote counts in the line below, one count under each header. Authors draw
it in many ways - ruled, unruled, inside a coloured box, tab-aligned - and
the other table sources miss most of them (too few rules, no tags), so this
source looks for the shape itself.

A poll is recognised when a text line consists of exactly the five header
tokens in order. Rows of numbers directly below whose numbers sit under the
header columns are its counts (up to _MAX_ROWS). A suggested poll with no
counts yet is emitted with an empty vote row when one is drawn under the
header, otherwise as a header-only table. A header followed by text on
the same line ("SF F N A SA: 4 5 1 0 0") is inline prose and is left alone.
"""

def extract_poll_tables(page, page_num: int, words_hint=None) -> list[TableCandidate]:
    """Poll result tables on one page. `words_hint` (the page's words, already
    extracted) lets a page with no vote label skip the character extraction.
    """
    # untyped: page, words_hint
    # calls: _clean, _split_pipes, pagecache.rawdict, ruled._page_words, _baseline_lines, select.vote_header, _label_cells, _header_prefix, _row_cells, _strip_zero_width, ruled._chars_to_lines, ruled._word_chars, +1 more
    # called by: pipeline.run_pipeline

# + 7 private module-level names
```

<a id="lib-pdf-qa-py"></a>

## `lib/pdf/qa.py` ([source](../../src/tomd/lib/pdf/qa.py))

Typed: 16 of 16 functions and methods (100%).

```python
"""Quality assurance metrics and scoring for Markdown conversion output.

Parses the Markdown output with mistune to validate structure from
the reader's perspective, not from pipeline internals.

DESIGN CONSTRAINT: compute_metrics() takes only a Markdown string.
No page count, no file format, no pipeline internals. Every signal
must be derivable from the Markdown text alone. This keeps scoring
format-agnostic (works on PDF output, HTML output, or any Markdown)
and prevents coupling between the scorer and the converter.
"""

@dataclass(frozen=True)
class QABatchResult:
    """Outcome of a batch QA scoring run.

    ``metrics`` holds successfully scored papers (including in-process
    scoring failures rendered as zero-score rows; see :func:`_qa_one`).
    ``errors`` is the canonical list of worker-level failures and is what
    :func:`format_qa_report` renders. ``timed_out`` is a typed subset view
    of ``errors`` (paper ids only) for callers that need to enumerate just
    the timeouts without parsing error messages.
    """
    metrics: tuple[QAMetrics, ...]
    errors: tuple[tuple[str, str], ...]
    timed_out: tuple[str, ...]
    elapsed_sec: float

@dataclass
class QAMetrics:
    """Per-document quality metrics computed purely from Markdown text."""
    file: str = ''
    total_chars: int = 0
    heading_count: int = 0
    max_heading_level: int = 0
    code_block_count: int = 0
    list_count: int = 0
    table_count: int = 0
    front_matter_count: int = 0
    has_doc_number: bool = False
    uncertain_count: int = 0
    unfenced_code_lines: int = 0
    paragraph_count: int = 0
    mojibake_count: int = 0
    heading_level_skips: int = 0
    wording_section_count: int = 0
    table_parse_errors: int = 0
    lossy_table_count: int = 0
    empty_output: bool = False
    score: int = 100
    issues: list[str] = field(default_factory=list)

def compute_metrics(md_text: str, file: str = '') -> QAMetrics:
    """Compute QA metrics by parsing the Markdown output with mistune.

    Takes only the Markdown text. No page count, no format hints.
    Everything is derived from the text itself.
    """
    # calls: QAMetrics, format.parse_front_matter, _count_unfenced_code, _count_mojibake, _heading_level_skips, _count_wording_blocks, _count_table_parse_errors, _score
    # called by: _qa_one

def format_qa_report(results: Sequence[QAMetrics], errors: Sequence[tuple[str, str]] = ()) -> str:
    """Return the ranked QA report text for stdout."""

def run_qa_batch(items: list[tuple[str, str]], *, workers: int = 1, timeout: int = _QA_BATCH_TIMEOUT_SEC, on_progress: ProgressCallback | None = None) -> QABatchResult:
    """Score a batch of converted papers and return ranked metrics.

    CLI-adjacent: callers format output via :func:`format_qa_report`.

    *items* is a list of ``(paper_id, markdown_text)`` pairs. Each markdown
    string is scored independently via :func:`compute_metrics`. Uses
    *workers* parallel processes (default 1 = sequential); *timeout* is
    seconds of no progress before aborting remaining items.
    """
    # calls: batch.run_parallel_batch, _qa_metrics_from_dict, QABatchResult

def write_qa_json_atomic(path: Path, results: Sequence[QAMetrics]) -> None:
    """Atomically write per-paper QA metrics as JSON."""

# + 12 private module-level names
```

<a id="lib-pdf-rowbands-py"></a>

## `lib/pdf/rowbands.py` ([source](../../src/tomd/lib/pdf/rowbands.py))

Typed: 0 of 3 functions and methods (0%).

```python
"""Rows bounded by drawn rules (2026-10-24).

In a drawn grid whose records are separated by horizontal rules (comment forms such as national-
body ballots), every text line between the same pair of rules belongs to one record. A reader
that cuts a multi-line record into several rows leaves the continuation lines as rows whose key
(first) column is empty. Such a row is joined to the row above when it lies wholly below that
row and no drawn rule crosses the two rows' combined extent; the joined cell keeps its lines
("
" span between them).

Only joins, never splits. Applies to single-page readings inside a ruled grid: at least
MIN_RULES horizontal rules each covering 60% of the table's width (segments at one height
merged). Measured on the tuning sets (REPORT.md, rule-bounded rows, version 4b): 14 tables
changed, all better, none worse; a version without the empty-key condition broke tables whose
grids rule only the header and border, and one testing only the gap between rows merged across
a rule running through a reading's rows.
"""

def merge_rule_bands(sec, rules) -> int:
    """Join empty-key continuation rows into the record above within one rule band; returns the
    number of rows joined. rules: the page's horizontal rule segments (y, x0, x1).
    """
    # untyped: sec, rules
    # calls: _full_rules, _text, types.Span
    # called by: pipeline.run_pipeline

# a row filling this share of its other (non-key) columns is a record of its own, never a
# continuation (user, 2026-10-24): in a grouped grid the first column is blank on every row of a
# group after the first, and those rows are full. 0.67 is the strictest value that keeps every
# tuning-set gain (0.5 keeps 7 of 14).
MAX_FILL = 0.67

MIN_RULES = 4

MIN_SEGMENT = 15.0  # pt: shorter strokes are not row separators

# + 2 private module-level names
```

<a id="lib-pdf-ruled-py"></a>

## `lib/pdf/ruled.py` ([source](../../src/tomd/lib/pdf/ruled.py))

Typed: 8 of 40 functions and methods (20%).

```python
"""Table detection from ruling lines (vector drawings).

An extractor independent of the MuPDF text blocks that table.py uses: it
looks only at the lines and thin rectangles a page draws, and at character
positions to fill cells.

Two techniques:
  Grid tables: PyMuPDF's page.find_tables(strategy="lines") for tables
    ruled in both directions (Word, Google Docs, LibreOffice exports).
  Rule-band tables: LaTeX/booktabs and ReportLab tables draw only
    horizontal rules. Rules sharing an x-extent form a group; rows come
    from the bands between rules, columns from x positions where a column
    starts in most rows, plus x ranges that no word covers.

Cell text is rebuilt from the page's characters (rawdict), grouped into
Lines and Spans the same way extract.py builds them, so fonts, bold,
italic and monospace survive. Words are assigned to a cell whole, by
their starting x, so text that overruns into the next column stays in its
own cell.

Known gaps: a booktabs table split by a page break is not detected (each
part has too few rules); column boundaries are ambiguous for tables with
very few rows. Both are caught downstream by the rule checks or by
disagreement with the other extractors.
"""

def drawn_spans(page, columns, spans) -> list[dict]:
    """the spans a closed grid's own lines allow: a span inferred from the text's
    position is dropped when a drawn line separates the cells it would join (the
    grid draws every cell it has; an empty drawn cell is not part of its neighbour)
    """
    # untyped: page, columns, spans
    # calls: _segments

def extract_ruled_tables(page, page_num: int, drawings=None) -> list[TableCandidate]:
    """All tables on one page that ruling lines reveal."""
    # untyped: page, drawings
    # calls: _unrotate, pagecache.rawdict, _page_chars, _page_words, _grid_tables, _column_ruled_tables, _bad_flags, runctx.current, select.table_flags, _horizontal_rules, _rule_groups, _overlaps, +2 more
    # called by: pipeline.run_pipeline

def page_hrules(page, drawings=None) -> list[tuple[float, float, float]]:
    """Drawn horizontal separators on the page: (y, x0, x1)."""
    # untyped: page, drawings
    # called by: pipeline.run_pipeline

# + 37 private module-level names
```

<a id="lib-pdf-runctx-py"></a>

## `lib/pdf/runctx.py` ([source](../../src/tomd/lib/pdf/runctx.py))

Typed: 1 of 3 functions and methods (33%).

```python
"""Per-run context: the state one ``run_pipeline`` call owns.

Table readers and checks record what they saw (the evidence record) and what
raised (reader errors). That state belongs to one conversion, so it lives in a
``RunContext`` opened by ``run_pipeline`` with ``run_scope()``, never in module
globals: two papers converted on two threads each see only their own context
(``contextvars`` gives every thread its own value).
"""

@dataclass
class RunContext:
    record: Record = field(default_factory=Record)
    # content removed on purpose: (what, why, an example); listed in the summary and prompts
    discards: list[tuple[str, str, str]] = field(default_factory=list)
    # drawn grids the rule reader excluded (failed checks): rejected readings for the marks
    excluded_grids: list = field(default_factory=list)
    # re-raise reader errors instead of recording them (tests of a reader's own failures)
    strict: bool = False
    def reader_error(self, stage: str, page: int | None, exc: BaseException, table=None) -> None:
        """Record a reader, check or specialist that raised: stage, page (None for the
        whole paper), exception type and message, and whether it is a code error. A table
        the failure touched carries the stage in ``metadata["reader_errors"]``, so the
        mark survives the section being copied.
        """
        # untyped: table

def current() -> RunContext:
    """The active run's context. Outside ``run_pipeline`` (a reader called directly,
    as in unit tests) a detached context is returned, so recording never fails.
    """
    # calls: RunContext
    # called by: pipeline._filter_sections_inside_vector_images, pipeline.run_pipeline, ruled._bands_to_table, ruled._column_ruled_tables, ruled._mark_icon_cells, ruled.extract_ruled_tables, select._continuation_votes, select.cross_reader_continuation, select.select_tables, select.stitch_pages, tagged.extract_tagged_tables

@contextlib.contextmanager
def run_scope():
    """Open a fresh context for one conversion; restore the previous one on exit."""
    # untyped: return
    # calls: RunContext
    # called by: pipeline._in_run_scope

# Longest exception message kept in a reader-error entry.
ERROR_MESSAGE_LIMIT = 300
```

<a id="lib-pdf-select-py"></a>

## `lib/pdf/select.py` ([source](../../src/tomd/lib/pdf/select.py))

Typed: 40 of 48 functions and methods (83%).

```python
"""Table selection: one reading per region, trusted only when another kind of evidence agrees.

Independent readers propose tables (``TableCandidate``): the text-position
detector (``table.detect_tables``, source "tomd"), the PDF's accessibility
tags (``tagged.py``), and the readers ported after them. ``select_tables``
groups the proposals by position, picks one reading per region, and sets its
confidence from agreement between readers plus rule checks:

  - another reader agrees cell for cell (or the text reading is a correct
    subset of a ruled table)                     -> HIGH
  - only one reader found the table              -> UNCERTAIN
  - readers found it but disagree                -> UNCERTAIN, every version kept
  - the cells lose or repeat the text of the
    table's area (``conservation_error``), cell text read out of order,
    a damaged text layer, an open extent          -> UNCERTAIN

A reading that fails the rule checks (``table_flags``) and has no better
version is dropped, so its text stays in the document as prose; the evidence
record keeps it. A selected reading of paperflow's own detector keeps that
section's table kind and rendering strategy.
"""

def candidate_from_section(sec: Section) -> TableCandidate:
    """Wrap a detect_tables() section (cells are span lists) as a candidate."""
    # calls: types.Line, types.TableCandidate
    # called by: select_tables

def candidates_agree(a: TableCandidate, b: TableCandidate) -> bool:
    """Same grid shape and every cell matching."""
    # calls: _cells_agree
    # called by: select_tables

def class_check(cand: TableCandidate) -> str:
    """Why this table can be trusted from one source, or "".

    Each check is specific to how the table was built, and only used when
    the classifier puts the region in the matching layout class:
      - poll: exactly the SF F N A SA (or F N A) header, then rows that are
        all vote counts, or one all-empty row (a suggested poll);
      - grid: read from drawn cell boundaries, rectangular, no column or
        row left empty;
      - tags: from a well-formed structure tree, every row as wide as the
        table, no empty column.
    """
    # calls: _is_bad, vote_header
    # called by: select_tables

def closed_exempt(t) -> bool:
    """a closed grid's own layout explains its empty cells, unless a whole column is
    empty (a doubled rule read as a column of its own)
    """
    # untyped: t
    # called by: ruled._bad_flags, _is_bad, sparse_mapping

def conservation_error(cand: TableCandidate, blocks: list[Block]) -> str:
    """Check that the text in the table's area went into its cells exactly once.

    The area is where the cells' own lines sit on each page. Every letter and
    digit of the page lines centred in that area must appear in the cells as
    often as on the page: a deficit is text the table lost (a dropped row,
    an overprinted word), a surplus is text it duplicated. Compared as
    character counts, so line breaks, hyphenation and spacing do not matter.
    Returns "" when conserved, else a note for the prompt.
    """
    # calls: _aligned_neighbour_row
    # called by: select_tables

def cross_reader_continuation(cands: list[TableCandidate], blocks: list[Block], furniture: frozenset = frozenset()) -> list[TableCandidate]:
    """A table continuing across a page is the same table whichever reader read
    each piece (user: preserve meaningful spatial relationships regardless of
    mechanism). After every reader's own stitching, a piece ending low on page N
    joins a piece from a different reader starting high on page N+1 under the
    same conditions as same-reader stitching: the same column count and column
    starts (or extent), no different header, nothing between them (page
    furniture aside). Polls are never joined this way. The joined table keeps
    the first piece's reader, is flagged 'cross-reader' and records both.
    """
    # calls: _page_span, _new_header, _same_columns, _text_outside, _overlap, _same_header, _carry, types.TableCandidate, runctx.current
    # called by: select_tables

def join_split_words(cands: list[TableCandidate], blocks: list[Block]) -> None:
    """A word split by a narrow cell is still one word (user, 2026-10-21): a cell line
    that runs to the cell's right edge ending mid-token, followed by a line that
    continues the token, is joined without a space - when the joined token occurs
    elsewhere in the document and one of the pieces never occurs on its own there, or
    when the break splits one identifier (underscores in both pieces, the second piece not
    a name used on its own elsewhere) or one long number
    or paper name (a run of 5+ characters ending in a digit, broken before a remainder
    of at most two digits: "P0876R1" / "1", "20210" / "6") and a piece never occurs on
    its own. A name followed by a number ("SC 22") and a year followed by a version
    ("2022" / "17.14") are never joined.
    The next line is marked (joins_prev); cell text and spans honour the mark.
    """
    # called by: select_tables

def mark_matrix(cand: TableCandidate) -> bool:
    """A check-mark matrix (status, feature or compliance tables): row keys in
    the first column, and the filled cells beside them are marks. Sparse by
    design, so empty cells and sparse or ragged columns are not misreadings.
    """
    # called by: _is_bad, select_tables

def page_furniture(blocks: list[Block], min_pages: int = 3) -> frozenset:
    """Lines repeated at the same height on several pages once digits are
    normalised: running headers and footers with page numbers that header
    stripping missed (a header block holding the page number).
    """
    # calls: _furniture_key
    # called by: select_tables

def partial_reading(primary: TableCandidate, other: TableCandidate) -> bool:
    """True when `other` is tomd's text-position reading of part of a fully
    ruled table: same columns, and every one of its rows matches, cell for
    cell, a row of the ruled table in the same order. The text-position
    detector often stops early or starts late on ruled tables; a correct
    subset confirms the rows it saw rather than contradicting the rest.
    """
    # calls: _cells_agree, _all_bold
    # called by: select_tables

def remove_table_regions(blocks: list[Block], tables: list[Section]) -> list[Block]:
    """Drop the lines that fall inside any chosen table's region.

    A line inside the region whose text is not in the table is kept, so it
    stays in the document as ordinary text: never lose words to a table whose
    cells missed them.
    """
    # calls: types.Block
    # called by: pipeline.run_pipeline

def select_tables(tomd_sections: list[Section], ruled: list[TableCandidate], tagged: list[TableCandidate], blocks: list[Block], polls: list[TableCandidate] = (), rejected: list[TableCandidate] | None = None, codepairs: list[TableCandidate] = (), content: list[TableCandidate] = (), generator: str = 'unknown') -> list[Section]:
    """Choose one table per region from the three extractors.

    Primary version by source priority (tags, polls, ruling lines, text positions),
    skipping versions that fail the rule checks. Confidence:
      - another source agrees cell for cell, or tomd's
        reading is a correct subset of a ruled table -> HIGH
      - only one source found the table            -> UNCERTAIN
      - other sources found it but disagree        -> UNCERTAIN, and every
        version is kept for the prompts file
      - the cells lose or duplicate text of the
        table's area (conservation_error)          -> UNCERTAIN
    A candidate that fails the rule checks and has no better version is
    dropped, so its blocks flow back into normal processing. Dropped
    candidates from the drawing and tag sources are appended to `rejected`
    when given: their area probably is a table, so flag.py marks it.
    """
    # calls: candidate_from_section, page_furniture, stitch_pages, cross_reader_continuation, split_at_headers, join_split_words, stacked.split_stacked, runctx.current, table_flags, _is_bad, _row_top, _same_region, +14 more
    # called by: pipeline.run_pipeline

def sparse_mapping(t) -> bool:
    """a closed grid of two or more drawn columns whose rows mostly fill only their first
    cell with a short label (a mapping where most entries have no counterpart): a table,
    not a framed paragraph under a lead-in line (whose single cells are prose)
    """
    # untyped: t
    # calls: closed_exempt
    # called by: ruled._bad_flags, _is_bad

def split_at_headers(cand: TableCandidate) -> list[TableCandidate]:
    """Two tables stacked in one reading: a different header row inside the body
    (short bold labels after a non-bold row) starts a new table (the user's
    header rule; an identical header repeated is the same table and stays).
    Single-page readings only; tags and polls delimit their own tables.
    """
    # calls: _is_header_row, types.TableCandidate, _bold_row, _same_header, _carry
    # called by: select_tables

def stitch_pages(cands: list[TableCandidate], blocks: list[Block], furniture: frozenset = frozenset()) -> list[TableCandidate]:
    """Join a table that ends one page with one that starts the next page.

    Requires the same column count and x-extent, and no text after the first
    part or before the second (headers and footers are already stripped from
    blocks) - a caption in between means two different tables. A header row
    that the PDF repeats on the continuation is dropped.
    """
    # calls: _new_header, _same_columns, _continuation_votes, _text_outside, _same_header, _carry, types.TableCandidate, runctx.current
    # called by: select_tables

def table_flags(cand: TableCandidate) -> list[str]:
    """Rule-based sanity checks. Flags in BAD_TABLE_FLAGS mean the grid is
    probably wrong; the others are informational.
    """
    # calls: _split_code_cell
    # called by: ruled._bad_flags, ruled.extract_ruled_tables, select_tables

def vote_header(labels: list[str]) -> bool:
    """These cell texts form a poll header (see VOTE_LABELS)."""
    # called by: poll._header_prefix, poll.extract_poll_tables, class_check

def witness(primary: TableCandidate, agreeing: list[TableCandidate], cands: list[TableCandidate], blocks: list[Block]) -> dict:
    """Per property, the distinct information sources behind the agreeing readings."""
    # calls: _extent_open
    # called by: select_tables

BAD_TABLE_FLAGS = ...

# a closed drawn grid's lines fix its cells: empty, merged and full-width cells are the
# author's layout there, not a misread (the content checks still apply)
CLOSED_GRID_EXEMPT = ...

# Readers whose readings are kept (flagged, reason "rule-check") when they fail
# the rule checks and no other reading covers their region. During the port,
# the readers that read those layouts in tomd-tables (polls, drawn rules, the
# content reader) and the marks for dropped readings (flag.py) are not here
# yet; once they are, this set is emptied and such readings are dropped as
# there, their text kept as prose and marked.
KEPT_WHEN_UNREPLACED = frozenset({'tomd'})

# Vote labels and their side: +1 for, 0 neutral, -1 against. A header is a
# line made only of these, in that order (for ... neutral ... against):
# "SF F N A SA", "SF WF N WA SA", "F N A", "Strongly Favor ... Strongly Against".
VOTE_LABELS = ...

# No HIGH for a table whose cells hold multi-line code: such a table renders as a
# pipe table with a whole code block in each cell, while a code comparison is read
# line by line. Removed by port step 8, which brings the paired-fence rendering of
# code comparisons.
WITHHOLD_TRUST_FOR_CODE_CELLS = True

# No HIGH at all until the checks that follow agreement are ported: the extent
# step (rows above or below a reading, a title row), layout verification and the
# classifier gate. Two readers can agree on a reading that misses a row; in
# tomd-tables those checks lower such tables. Removed by port step 9.
WITHHOLD_TRUST_UNTIL_VERIFIED = True

# + 30 private module-level names
```

<a id="lib-pdf-spans-py"></a>

## `lib/pdf/spans.py` ([source](../../src/tomd/lib/pdf/spans.py))

Typed: 8 of 8 functions and methods (100%).

```python
"""Span normalization - snap style boundaries to word edges.

When a bold or italic boundary falls inside a word (no whitespace
between adjacent spans with different styles), extend the styled
region to the word boundary. Monospace boundaries are exempt
because code boundaries are intentional.
"""

def normalize_spans(blocks: list[Block]) -> list[Block]:
    """Snap bold/italic style boundaries to word edges across all blocks.

    Monospace boundaries are exempt (code boundaries are intentional).
    """
    # calls: _normalize_line_spans, types.Line, types.Block
    # called by: pipeline.run_pipeline

# + 7 private module-level names
```

<a id="lib-pdf-stacked-py"></a>

## `lib/pdf/stacked.py` ([source](../../src/tomd/lib/pdf/stacked.py))

Typed: 5 of 5 functions and methods (100%).

```python
"""Stacked entries are one row each (table convention, "Rows: one row per entry").

Several entries stacked in one drawn band, on baselines shared across columns
("Linux / QNX / NetBSD" beside three function names), are one row each; a cell
whose text wraps is still one row (a wrap breaks at a space, so a line of one
token followed by another line is a new entry). Learned from the vision readers (Table
Transformer, Docling): a line is its own row unless something shows it wraps.

A row is split between two baselines when the lower baseline holds lines in
two or more columns, one of them the row's first column (where an entry's key
sits), and, in every column with a line on both baselines, the
upper line did not run to the column's edge (the next line's first word would
have fitted after it) and the lower line is not a word joined to the upper
one. Rows of C++ statements (a line ending in ; { or }, a preprocessor line, a
comment) are code blocks and are
never split, nor are rows holding a listing (monospace lines with words on them,
such as assembly); the header row and all-bold rows are left as they are.
"""

def split_stacked(cand: TableCandidate) -> TableCandidate:
    # calls: _code_block, _height, _baseline, types.TableCandidate
    # called by: select.select_tables
    ...

# + 4 private module-level names
```

<a id="lib-pdf-structure-py"></a>

## `lib/pdf/structure.py` ([source](../../src/tomd/lib/pdf/structure.py))

Typed: 83 of 86 functions and methods (96%).

```python
"""Dual-path comparison, heading intelligence, and document structuring."""

def compare_extractions(mupdf_blocks: list[Block], spatial_blocks: list[Block]) -> list[Section]:
    """Compare two extraction paths using per-page word-level multiset similarity.

    Groups blocks by page and computes a word-count overlap ratio for each
    page. High similarity = confident (PARAGRAPH). Low similarity = uncertain.
    Small uncertain regions below MIN_UNCERTAIN_WORDS are promoted to confident.
    """
    # calls: _block_words, _word_similarity, _make_paragraph_section, types.Section, _order_sections_reading
    # called by: pipeline.run_pipeline

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
    # calls: toc.normalize_toc_entry, _entry_title, _is_title_like_straggler, _is_empty_heading, _compute_body_start, _has_alpha_title, _run_recurrence_density, _straggler_forward_references, _section_is_trivial, toc.is_toc_label
    # called by: pipeline.run_pipeline

def heading_confidence(has_number: bool, number_level: int, font_level: int | None, is_bold: bool, is_known: bool) -> tuple[int, Confidence]:
    """Determine heading level and confidence from multiple signals.

    Bold alone (no section number, no enlarged font, not a known name)
    yields level 0 with LOW confidence.  The caller must assign a
    context-derived level (typically previous_heading_level + 1) before
    accepting the heading.  This keeps the function stateless while
    allowing bold-only sub-headings (common in WG21 papers) to enter
    the heading path.
    """
    # called by: _structure_body_impl

def structure_body(sections: list[Section], has_title: bool = False, figure_regions: list | None = None, metadata_title: str | None = None) -> tuple[dict, list[Section], int]:
    """Body structuring only, without metadata extraction.

    Called after metadata extraction is complete.
    Returns (body_metadata, structured_sections, nesting_corrections).
    body_metadata may contain a 'title' if one was detected during structuring.

    ``metadata_title`` is the title already extracted upstream (WG21 block
    scan / PDF info). It lets font-size ranking distinguish the real title
    block from a same-position body heading; see ``_title_section_for_ranking``.
    """
    # calls: _structure_body_impl
    # called by: pipeline.run_pipeline

def structure_sections(sections: list[Section], has_title: bool = False) -> tuple[dict, list[Section], int]:
    """Apply heading intelligence, paragraph grouping, and list detection.

    If has_title is True, the title was already extracted from front matter
    and no title detection is performed.

    Returns (metadata_dict, structured_sections, nesting_corrections).

    Note: metadata extraction is done internally for backward compatibility.
    New callers should use structure_body() after separate metadata extraction.
    """
    # calls: extract.extract_metadata, _structure_body_impl

# + 81 private module-level names
```

<a id="lib-pdf-summary-py"></a>

## `lib/pdf/summary.py` ([source](../../src/tomd/lib/pdf/summary.py))

Typed: 4 of 5 functions and methods (80%).

```python
"""Paper-level summary: what tomd did with this paper's tables, and how unlike
the measured papers this one is.

The output feeds AI analysis of WG21 papers, where a trusted-but-wrong
conversion is the costly failure, so every conversion carries:
  - tables trusted (HIGH), flagged (UNCERTAIN) and marked (possible tables),
    with their pages; content removed on purpose and why; reader errors;
  - an unfamiliarity score: how unlike the measured papers this one is
    (generator not seen in the measured sets, rare layout classes, rotated
    text);
  - a paper-level confidence: the chance that the paper's tables hold no
    silent error. It is "not estimated" here: the calibrated model belongs to
    the conversion it was fitted on, and is refitted on this pipeline's output
    before a figure is published.

Machine-readable (``PipelineResult.summary``, persisted by the CLI beside the
Markdown), one ``tomd:summary`` comment after the front matter, and prompt
elements for the removed content, the reader errors and the summary.
"""

def build(sections, discards: list[tuple[str, str, str]], reader_errors: list[dict], generator_name: str) -> dict:
    """The paper summary (JSON-serializable)."""
    # untyped: sections
    # calls: unfamiliarity
    # called by: pipeline.run_pipeline

def generator(meta: dict) -> str:
    """The PDF producer's family, from the document metadata."""
    # called by: pipeline.run_pipeline

def header_comment(s: dict) -> str:
    """The one-line ``tomd:summary`` comment written after the front matter."""
    # called by: pipeline.run_pipeline

def prompt_elements(s: dict, discards: list[tuple[str, str, str]], reader_errors: list[dict]) -> list[str]:
    """Self-contained prompt elements: removed content, reader errors, the summary."""
    # called by: pipeline.run_pipeline

def unfamiliarity(generator_name: str, layouts: list[str], rotated: bool, skipped: bool) -> tuple[float, list[str]]:
    """0 (like the measured papers) .. 1 (unlike them), with the reasons."""
    # called by: build

COMMON_LAYOUTS = {'poll', 'grid', 'rule-per-row', 'tagged', 'booktabs'}

# Generators of the measured papers (the answer-key sets).
KNOWN_GENERATORS = ...
```

<a id="lib-pdf-table-py"></a>

## `lib/pdf/table.py` ([source](../../src/tomd/lib/pdf/table.py))

Typed: 101 of 102 functions and methods (99%).

```python
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

class TableKind(Enum):
    """What kind of table this section represents."""
    CLEAN_MATRIX = 'clean_matrix'
    INLINE_GRID = 'inline_grid'
    PROSE_TABLE = 'prose_table'
    CODE_COMPARISON = 'code_comparison'
    SPEC_TABLE = 'spec_table'
    KEY_VALUE = 'key_value'
    BIBLIOGRAPHY = 'bibliography'
    NB_BALLOT = 'nb_ballot'
    FALSE_POSITIVE = 'false_positive'

class TableStrategy(Enum):
    """How to render this table in markdown."""
    PIPE_TABLE = 'pipe_table'
    CODE_BLOCKS = 'code_blocks'
    HTML_TABLE = 'html_table'
    SKIP = 'skip'

def detect_tables(blocks: list[Block], *, page_mupdf_tables: dict[int, list[dict]] | None = None, two_column_pages: frozenset[int] = frozenset()) -> tuple[list[Section], list[Block]]:
    """Detect table regions from MuPDF block structure.

    Returns (table_sections, remaining_blocks).
    Table sections have kind=TABLE with high confidence.
    Remaining blocks are the non-table blocks for normal processing.
    """
    # calls: _find_column_xs, _filter_phantom_mupdf_tables, _detect_spec_tables_by_label, _detect_side_by_side_tables, _block_column_positions, _same_baseline_header_columns, _unpack_multirow_body, _row_from_lines, _last_column_is_page_numbers, _is_labeled_contents_table, _classify_and_annotate, types.Block, +31 more
    # called by: pipeline.run_pipeline

def exclude_table_regions(blocks: list[Block], table_sections: list[Section]) -> list[Block]:
    """Remove blocks or lines whose vertical midpoint falls within a detected table region.

    For multi-page tables, builds per-page y-ranges from individual
    lines so that content on continuation pages is also excluded.
    """
    # calls: types.Block, types.compute_bbox
    # called by: pipeline.run_pipeline

# + 102 private module-level names
```

<a id="lib-pdf-tagged-py"></a>

## `lib/pdf/tagged.py` ([source](../../src/tomd/lib/pdf/tagged.py))

Typed: 2 of 6 functions and methods (33%).

```python
"""Table detection from the PDF's accessibility tags (Tagged PDF).

When the producing application wrote a structure tree (Google Docs, Word,
LibreOffice, Typst, Chrome print), tables are explicitly marked up as
Table / TR / TH / TD elements. PyMuPDF exposes them per page through
get_text("dict") with TEXT_COLLECT_STRUCTURE: structure nodes appear as
blocks of type 2 that contain the text blocks they own.

Cross-page tables: a Table element continued on the next page appears on
both pages with the same structure index, so the parts are joined by
index; a row split by the page break (same TR index) is joined too.

Empty cells own no text, so a page's dict may omit them. Rows shorter
than the table are therefore re-aligned by x position against the column
positions of full rows.

Untagged PDFs (LaTeX/pdfTeX, ReportLab, most tools) simply yield nothing.
"""

def extract_tagged_tables(doc) -> list[TableCandidate]:
    """All tables marked up in the document's structure tree.

    When MuPDF reports structure-tree errors while reading the pages (some
    Word exports), every candidate gets the "tags-malformed" flag so table
    selection ranks it below the ruling-line version.
    """
    # untyped: doc
    # calls: _page_tables, runctx.current, _realign, types.TableCandidate
    # called by: pipeline.run_pipeline

# + 5 private module-level names
```

<a id="lib-pdf-types-py"></a>

## `lib/pdf/types.py` ([source](../../src/tomd/lib/pdf/types.py))

Typed: 16 of 16 functions and methods (100%).

```python
"""Shared data types, constants, and precompiled regex patterns for PDF conversion."""

@dataclass
class Block:
    """A group of lines forming a paragraph-level unit."""
    lines: list[Line] = field(default_factory=list)
    bbox: tuple[float, float, float, float] = (0, 0, 0, 0)
    page_num: int = 0
    def first_content_line(self) -> 'Line | None':
        """First line carrying non-whitespace text, or None if blank."""
    @property
    def font_size(self) -> float:
        """Most common font size among lines (one vote per line)."""
    def last_content_line(self) -> 'Line | None':
        """Last line carrying non-whitespace text, or None if blank."""
    @property
    def text(self) -> str: ...

class Confidence(Enum):
    """Confidence level for structural classification decisions."""
    HIGH = 'high'
    MEDIUM = 'medium'
    LOW = 'low'
    UNCERTAIN = 'uncertain'

@dataclass
class FigureEdge:
    """A directed edge between two nodes in a diagram graph."""
    source_idx: int
    target_idx: int
    bidirectional: bool = False
    dashed: bool = False
    label: str = ''
    y_position: float = 0.0

@dataclass
class FigureGraph:
    """Directed graph extracted from a vector-graphic diagram."""
    nodes: list[FigureNode] = field(default_factory=list)
    edges: list[FigureEdge] = field(default_factory=list)
    @property
    def is_linear(self) -> bool:
        """True when the graph forms a single chain with no branches or cycles."""

@dataclass
class FigureNode:
    """A node (box) in a detected diagram graph."""
    text: str
    bbox: tuple[float, float, float, float]

@dataclass
class FigureRegion:
    """A detected vector-graphic figure region on a page."""
    page_num: int
    bbox: tuple[float, float, float, float]
    graph: FigureGraph | None = None

@dataclass
class Line:
    """A sequence of spans forming a single line of text."""
    spans: list[Span] = field(default_factory=list)
    bbox: tuple[float, float, float, float] = (0, 0, 0, 0)
    page_num: int = 0
    def first_content_span(self) -> 'Span | None':
        """First span carrying non-whitespace text, or None if blank."""
    @property
    def font_size(self) -> float:
        """Maximum font size among non-whitespace spans."""
    @property
    def is_bold(self) -> bool: ...
    @property
    def is_monospace(self) -> bool: ...
    @property
    def text(self) -> str: ...

@dataclass
class PageEdgeItem:
    """A text item near the top or bottom of a page, used for header/footer detection."""
    text: str
    y: float
    page_num: int
    bbox: tuple[float, float, float, float] = (0, 0, 0, 0)

@dataclass
class Section:
    """A classified region of the document."""
    kind: SectionKind
    text: str
    confidence: Confidence = Confidence.HIGH
    heading_level: int = 0
    lines: list[Line] = field(default_factory=list)
    mupdf_text: str = ''
    spatial_text: str = ''
    page_num: int = 0
    font_size: float = 0.0
    metadata: dict[str, object] = field(default_factory=dict)
    columns: list[list[list[Span]]] = field(default_factory=list)
    fence_lang: str = 'cpp'
    indent_level: int = 0
    table_kind: str | None = None
    table_strategy: str | None = None
    table_source: str | None = None
    table_continuation: bool = False
    figure_graph: FigureGraph | None = None
    image_ref: 'ExtractedImage | None' = None

class SectionKind(Enum):
    """The structural role of a document section."""
    TITLE = 'title'
    HEADING = 'heading'
    PARAGRAPH = 'paragraph'
    LIST = 'list'
    CODE = 'code'
    TABLE = 'table'
    IMAGE = 'image'
    UNCERTAIN = 'uncertain'
    WORDING = 'wording'
    WORDING_ADD = 'wording-add'
    WORDING_REMOVE = 'wording-remove'
    FIGURE = 'figure'

class SkipReason(StrEnum):
    """Closed set of early-exit reasons for :class:`PipelineResult`."""
    EMPTY_PDF = 'empty pdf'
    SLIDE_DECK = 'slide deck'
    STANDARDS_DRAFT = 'standards draft'
    UNREADABLE = 'unreadable'

@dataclass
class Span:
    """A run of text with uniform font properties."""
    text: str
    font_name: str = ''
    font_size: float = 0.0
    bold: bool = False
    italic: bool = False
    monospace: bool = False
    bbox: tuple[float, float, float, float] = (0, 0, 0, 0)
    origin: tuple[float, float] = (0, 0)
    color: int = 0
    link_url: str | None = None
    wording_role: str | None = None

@dataclass
class TableCandidate:
    """A table proposed by one independent reader, before selection.

    rows[r][c] is the list of Lines in that cell (several Lines when the
    cell wraps). bboxes maps page_num -> bbox of the table's part on that
    page; a table continued across a page break has several entries.
    """
    source: str  # the reader: "tomd", "tags", "grid", "rules", ...
    rows: list[list[list[Line]]]
    bboxes: dict[int, tuple[float, float, float, float]] = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)
    def cell_text(self, r: int, c: int) -> str:
        # called by: TableCandidate.text_rows
        ...
    @property
    def pages(self) -> list[int]: ...
    @property
    def shape(self) -> tuple[int, int]: ...
    def text_rows(self) -> list[list[str]]:
        # calls: TableCandidate.cell_text
        ...

def compute_bbox(bboxes: list[tuple]) -> tuple[float, float, float, float]:
    """Compute the bounding box enclosing all given bbox tuples.

    Raises ValueError (via min/max) if bboxes is empty. Callers must
    ensure at least one bbox is present.
    """
    # called by: extract.extract_spatial, glyphs._recompute_block_bbox, glyphs._recompute_line_bbox, structure._section_bbox, table.detect_tables, table.exclude_table_regions

def is_readable(text: str) -> bool:
    """Return True if text looks like real content rather than encoded garbage.

    Heuristic check that rejects PDFs with very low alphanumeric content,
    such as scanned-image-only PDFs or CID-encoded artifacts that produce
    mostly non-alphanumeric output.
    """
    # called by: pipeline.run_pipeline

AUDIENCE_RE = re.compile('Audience[:\\s]+(.+)', re.IGNORECASE)

BULLET_CHARS = frozenset('•‣●◦⁃∙▪▫○')

BULLET_RE = re.compile('^[\\s]*[-*' + ''.join(BULLET_CHARS) + ']\\s+')

COMPOUND_PREFIXES = ...

# Line-anchored pattern targeting "Document Number: PXXXXRN" field lines in
# PDF block text. More restrictive than DOC_NUM_RE in lib/__init__.py, which
# is a broad substring match used for header stripping and HTML contexts;
# both patterns share the core DOC_NUM_PATTERN shape.
DOC_FIELD_RE = ...

# The varying-text footer-band rule only fires in the bottom page margin
# (y > page_height * this fraction). Restricting it to the margin keeps it from
# misfiring on the section-heading band at the top of body pages, whose bare
# section numbers ("1", "2", ...) also look like recurring page numbers.
EDGE_BAND_BOTTOM_FRACTION = 0.85

EDGE_ITEMS_PER_PAGE = 3

FALLBACK_BODY_SIZE = 11.0

FALLBACK_FONT_SIZE = 12.0

KNOWN_SECTIONS = ...

LINE_SPACING_RATIO = 1.8

MIN_UNCERTAIN_WORDS = 10

NUMBERED_LIST_RE = ...

PAGE_NUM_RE = re.compile('^\\d+$|^[Pp]age\\s+\\d+|^\\d+\\s+of\\s+\\d+')

PARA_SPACING_RATIO = 2.5

# Minimum pages a text must appear on (as fraction) to be a header/footer
REPEATING_THRESHOLD = 0.5

REPLY_TO_RE = ...

# A running footer band recurs at a fixed bottom-margin y across pages but its
# text varies per page (e.g. "Scope", "Normative references 2", "§ 6.9.2.2 6").
# The band is identified by a bare page number recurring in it. The strip is
# bounded two ways so it never drops body content: it fires only inside small
# edge (footer) blocks, never tall body blocks, and only on lines this short or
# shorter (running titles are short; a wide body line that shares the band's y
# survives the word cap regardless).
RUNNING_FOOTER_MAX_WORDS = 8

# Section number at the start of a line with required trailing content
# (used for heading detection); shares the core shape with
# SECTION_NUM_PREFIX_RE in lib/__init__.py.
SECTION_NUM_RE = re.compile(f'^({SECTION_NUM_PATTERN})\\s+(.+)')

# Similarity threshold for dual-path comparison (word-level)
SIMILARITY_THRESHOLD = 0.82

TERMINAL_PUNCTUATION = frozenset('.?!:')

# Spatial rule thresholds (relative to font size)
WORD_GAP_RATIO = 0.3

# Y-position tolerance for header/footer matching across pages
Y_TOLERANCE = 2.0

# Zero-width invisibles that str.strip() does not remove (ZWSP, ZWNJ,
# ZWJ, ZWNBSP/BOM). A line carrying only these counts as empty for
# positioning and bullet-marker detection. Single source for the strip
# sets in structure.py. Note: glyphs.py's _ZERO_WIDTH_JOINER (U+200D) is
# a distinct, emoji-sequence concept and intentionally not derived here.
ZERO_WIDTH_CHARS = frozenset({8203, 8204, 8205, 65279})
```

<a id="lib-pdf-vector-images-py"></a>

## `lib/pdf/vector_images.py` ([source](../../src/tomd/lib/pdf/vector_images.py))

Typed: 21 of 22 functions and methods (95%).

```python
"""Vector-figure extraction via path-operator clustering.

Independent of :mod:`tomd.lib.pdf.images`, which only sees raster
XObjects pulled from each page's resource dictionary. This module
enumerates a page's vector drawing operations via
``pymupdf.Page.get_drawings()``, clusters spatially adjacent strokes
into figure candidates, filters clusters that don't look like figures
(too small, too text-overlapped, in the page edge band,
ins/del-coloured), and rasterises each surviving cluster to PNG via
``page.get_pixmap(clip=cluster_bbox, dpi=_RASTERISE_DPI)``.

The heuristic is intentional. Each constant is documented inline with
its calibration rationale, and the per-paper uncertainty marker
(:data:`VECTOR_UNCERTAINTY_MARKER_TEMPLATE`) surfaces every drop so a
reader can see why a diagram was missed.

Outputs feed :func:`tomd.lib.pdf.images.finalize_extraction` via
:class:`_PageImageCandidate` records with ``source="vector"`` and a
synthetic negative ``xref`` from :func:`_synthetic_xref` so the cap
and dedup paths handle raster + vector symmetrically.

What we deliberately do NOT do here:

- No grid-pattern proxy. An earlier draft of the plan proposed one to
  distinguish tables from diagrams, but it false-rejected legitimate
  swim-lane diagrams, sequence diagrams with three or more lifelines,
  and comparison matrices drawn as aligned rectangles. The text-
  overlap filter handles the table case structurally (tables have
  text in their cells; diagrams generally do not).
- No per-drawing-item colour walk in :func:`_is_ins_del_coloured`.
  ``drawing["items"]`` tuples carry Point and Rect coordinates whose
  values could land in a wording hue band by coincidence and silently
  exclude real diagrams.
"""

def extract_page_vector_images(page: 'pymupdf.Page', page_blocks: Sequence['Block'], *, whiteout_text: bool = False) -> tuple[list[_PageImageCandidate], _PageVectorStats]:
    """Per-page vector-figure extraction.

    Returns ``(candidates, per_page_stats)``. Stats bubble up via
    tuple return rather than a mutable accumulator parameter so the
    function stays library-pure (no shared mutable state across
    callers). The pipeline's per-page loop sums the per-page stats
    into the run-level :class:`_VectorExtractionStats` accumulator
    that :func:`tomd.lib.pdf.images.finalize_extraction` eventually
    surfaces via :class:`VectorUncertaintyStats`.

    Called from step 1 of the pipeline, alongside
    :func:`tomd.lib.pdf.images.extract_page_images` (the raster path).
    The document must still be open because the rasterisation call
    needs the live page.

    Pipeline (matches plan section 1.1):

      1. Collect drawings via ``page.get_drawings()``; early-exit on
         ``_MIN_PAGE_DRAWING_ITEMS``.
      2. Hard cap on per-page item count via ``_MAX_DRAWINGS_PER_PAGE``;
         the page is skipped entirely if exceeded, contributing to
         ``pages_skipped``.
      3. Drop drawings whose stroke / fill colour is in the wording
         hue band (counted as ``wording_color``).
      4. Drop drawings whose bbox sits entirely inside the header /
         footer edge band (counted as ``edge_band``).
      5. Cluster surviving drawings by single-linkage on bbox
         distance (``_CLUSTER_LINK_DISTANCE_PT``).
      6. Per-cluster filter: ``_MIN_CLUSTER_DIM_PT`` on both axes,
         ``_MIN_CLUSTER_ITEM_COUNT``, ``_MAX_TEXT_OVERLAP_FRACTION``,
         and the page-cluster cap ``_MAX_CLUSTERS_PER_PAGE``.
      7. Rasterise each surviving cluster via ``page.get_pixmap``,
         optionally painting over text lines if ``whiteout_text``.
      8. Run :func:`tomd.lib.pdf.images._caption_for` against the
         cluster bbox.
      9. Return one :class:`_PageImageCandidate` per cluster with
         ``source="vector"`` and a synthetic negative ``xref``.
    """
    # calls: _is_ins_del_coloured, _drawing_bbox, _bbox_fully_in_edge_band, _cluster_drawings, _merge_close_clusters, _merge_row_clusters, _merge_sub_figure_clusters, _detect_frame_drawings, _merge_clusters_into_frames, _drawing_coverage_sum, _text_overlap_fraction, _whiteout_text_in_pixmap, +3 more
    # called by: pipeline.run_pipeline

def format_uncertainty_marker(stats: VectorUncertaintyStats) -> str:
    """Format the per-paper uncertainty marker.

    Reasons dict is iterated in alphabetical key order (D7). Foreign
    keys (outside :data:`ALLOWED_REASON_KEYS`) raise ``ValueError`` so
    a maintainer who adds a new filter without updating the closed
    key set fails loudly at test time rather than emitting a marker
    consumers can't parse.
    """
    # called by: emit.emit_markdown

def should_emit_marker(stats: VectorUncertaintyStats) -> bool:
    """True when there's something honest to disclose.

    Marker is emitted when extraction was attempted (pages_scanned > 0
    OR pages_skipped > 0) AND something was rejected or skipped
    (rejected > 0 OR pages_skipped > 0). On HTML papers, where vector
    extraction never runs, the marker is absent by construction
    (stats is None upstream); this predicate handles only the
    PDF-stats-present case.
    """
    # called by: emit.emit_markdown

# The closed set of valid reason keys. Adding a new key is a versioned
# change to the marker contract (see plan section 1.6a "Marker
# stability"). The tuple is the source of truth for tests that pin
# the contract.
ALLOWED_REASON_KEYS: tuple[str, ...] = ...

REASON_ASPECT_EXTREME = 'aspect_extreme'

REASON_BBOX_TOO_LARGE = 'bbox_too_large'

REASON_CLUSTERS_OVERFLOW = 'clusters_overflow'

REASON_EDGE_BAND = 'edge_band'

REASON_TEXT_OVERLAP = 'text_overlap'

REASON_TOO_FEW_ITEMS = 'too_few_items'

REASON_TOO_SMALL = 'too_small'

REASON_WORDING_COLOR = 'wording_color'

VECTOR_UNCERTAINTY_MARKER_TEMPLATE = ...

# + 19 private module-level names
```

<a id="lib-pdf-wg21-py"></a>

## `lib/pdf/wg21.py` ([source](../../src/tomd/lib/pdf/wg21.py))

Typed: 7 of 7 functions and methods (100%).

```python
"""WG21-specific metadata extraction from PDF blocks.

Parses the metadata block at the top of WG21 papers (document number,
date, audience, reply-to) from the raw MuPDF block structure, before
table detection or structuring runs.
"""

def extract_metadata_from_blocks(blocks: list[Block], text_colors: dict[float, float] | None = None) -> tuple[dict, set[int]]:
    """Extract WG21 metadata from the first blocks of page 0.

    PDF block-level scan (pathway 2 of 3). Higher precedence than
    structure._extract_metadata; both are merged in run_pipeline with this
    result winning on key conflicts.

    Handles two formats:
      - Scrivener: each field is its own block (label on line 0, value on line 1+)
      - Google Docs: multiple fields in one block (each line has label: value)

    Title is chosen by two signals: largest font size (primary) and
    darkest color (secondary, via space-color proxy for Type 3 fonts).

    Returns (metadata_dict, consumed_block_indices).
    Metadata dict keys: "title", "document", "date", "intent", "audience", "reply-to".
    All keys are optional; only fields found in the PDF are included.
    "reply-to" value is a list of "Name <email>" strings.
    """
    # calls: _strip_bullets, _clean, _lookup_lightness, _store_field, _parse_authors, _is_already_present
    # called by: pipeline.run_pipeline

# Maximum number of continuation blocks consumed after a reply-to label.
REPLY_TO_CONTINUATION_CAP = 5

# + 6 private module-level names
```

<a id="lib-pdf-wording-py"></a>

## `lib/pdf/wording.py` ([source](../../src/tomd/lib/pdf/wording.py))

Typed: 17 of 23 functions and methods (73%).

```python
"""Wording section detection via multi-signal HSV color + drawing analysis.

Detects ins/del markup in WG21 PDF papers by combining three signals:
  1. Block-level color contamination filter - blocks containing non-wording
     chromatic colors (purple, orange, cyan) are syntax-highlighted code
     and are skipped entirely. So are blocks whose palette has two or
     more distinct shades inside one wording band (two greens: a Pygments
     keyword and a number), since a diff framework paints ins in exactly
     one color and del in exactly one color.
  2. Line-level wording detection - lines where the majority of non-link
     characters are green/red, or where green/red spans appear on an
     otherwise-black line (partial-line wording pattern).
  3. Span-level classification - green spans become ins; red spans with
     a confirmed strikethrough drawing become del.

Hyperlinks (span.link_url set) are excluded from all checks and fractions.
Insertions require no drawing decoration. Deletions require a strikethrough
drawing whose width overlaps at least 30% of the span to avoid matching
table borders and decorative rules.

Known WG21 framework diff colors (for reference):
  mpark/wg21:     add=#006e28 (H=142), rm=#bf0303 (H=1)
  tcbrindle:      add=#008019 (H=150), rm=#ff0000 (H=0)
  cplusplus/draft: add=#009999 (H=180, teal), rm=#ff0000 (H=0)
  schultke:       ins=#17752d (H=138), del=#be1621 (H=355)
All fall within our HSV ranges: green 90-180, red <=30 or >=330.
"""

def classify_wording(blocks: list[Block], page_drawings: dict[int, list]) -> list[str]:
    """Classify spans as ins/del/context using multi-signal analysis.

    Three-layer filter:
      1. Blocks with foreign chromatic colors (not green/red/blue), or with
         two or more distinct shades inside one wording band, are skipped:
         they are syntax-highlighted code, not wording markup.
      2. Lines qualify if either the majority (>50%) of non-link characters
         are green/red, or if any green/red spans appear with the remaining
         text being black (partial-line wording pattern).
      3. Green spans on qualifying lines become ins (no drawing required).
         Red spans become del only with a confirmed strikethrough drawing.

    Sets span.wording_role on matching spans.
    Returns an empty list (reserved for future diagnostic messages).
    """
    # calls: _block_has_foreign_colors, _block_has_highlighter_palette, _block_has_confirmed_strikethrough, _line_wording_fraction, _line_has_wording_on_black, _line_has_confirmed_strikethrough, is_green_ins, _span_is_comment, is_red_del, _match_strikethrough, _is_chromatic, _color_int_to_rgb
    # called by: pipeline.run_pipeline

def collect_line_drawings(page) -> list[tuple[float, float, float, tuple]]:
    """Collect horizontal line drawings from a page for decoration detection.

    Returns list of (y, x0, x1, color_rgb) for horizontal lines.
    """
    # untyped: page
    # called by: pipeline.run_pipeline

def is_foreign_chromatic(color_int: int) -> bool:
    """True if color is chromatic but not green, red, or blue.

    A foreign chromatic color is the signature of syntax-highlighted
    code (purple, orange, cyan, olive, ...). It is used both by the
    block-level wording filter here and by the section-level guard in
    :mod:`structure` that keeps a syntax-highlighted code listing from
    being reclassified as wording markup.
    """
    # calls: _is_chromatic, _is_wording_color, _is_blue_link
    # called by: structure._section_has_foreign_chromatic, _block_has_foreign_colors

def is_green_ins(color_int: int) -> bool:
    """True if color is in the green hue range with sufficient saturation."""
    # calls: _hsv, _in_green_band
    # called by: _block_has_highlighter_palette, classify_wording

def is_red_del(color_int: int) -> bool:
    """True if color is in the red hue range with sufficient saturation."""
    # calls: _hsv, _in_red_band
    # called by: _block_has_highlighter_palette, _line_has_confirmed_strikethrough, classify_wording

def is_wording_rgb(r: float, g: float, b: float) -> bool:
    """True if (r, g, b) floats in [0, 1] sit in the ins (green) or del (red) hue band.

    Mirrors :func:`_is_wording_color` for callers that already have RGB
    floats, such as ``pymupdf.Page.get_drawings()``, which yields
    ``color`` and ``fill`` as float tuples rather than the packed-int
    format ``wording.py`` originally consumed. Both predicates delegate
    to :func:`_in_green_band` / :func:`_in_red_band`, so the hue-band
    rule lives in one place.
    """
    # calls: _in_green_band, _in_red_band
    # called by: vector_images._colour_in_wording_band

# + 17 private module-level names
```

<a id="lib-pdf-wording-emit-py"></a>

## `lib/pdf/wording_emit.py` ([source](../../src/tomd/lib/pdf/wording_emit.py))

Typed: 9 of 9 functions and methods (100%).

```python
"""Wording-section rendering for the PDF emitter.

A wording section renders in one of three shapes, fidelity first: a
wholesale fenced code block, a fenced code diff (a code fence carrying
inline ``<ins>`` / ``<del>`` markers), or prose. All three live here so
:mod:`emit` keeps to general block dispatch. The uniform-role boundary
shared with :mod:`lib.wording_cleanup` lives in
:mod:`lib.wording_policy`; the code-promotion knobs below are emit-only
because they need span-level structure the assembled Markdown has
already collapsed.

No Pandoc fenced div (``:::wording-add`` and friends) wraps the result:
the divs said nothing the shape and the inline tags do not, and they
were noise in the converted Markdown. Which shape a section takes, and
which inline tags survive, is unchanged.
"""

# + 9 private module-level names
```

<a id="lib-shared-py"></a>

## `lib/shared.py` ([source](../../src/tomd/lib/shared.py))

Typed: 18 of 19 functions and methods (94%).

```python
"""Shared text utilities and constants for PDF and HTML converters."""

def apply_strip_leading_h1(md: str, title: str, max_level: int = 1) -> str:
    """Strip a leading title heading from the body after YAML front matter."""
    # calls: _find_front_matter_end, strip_leading_h1
    # called by: writer.MarkdownWriter.write

def ascii_escape(text: str) -> str:
    """Encode non-ASCII characters as HTML character references.

    Uses named entities for common diacritics (e.g. &uuml; for u-umlaut),
    falls back to numeric references (e.g. &#8212;) for others.
    """

def dedup_paragraphs(md: str) -> str:
    """Remove duplicate paragraphs from Markdown text.

    Two passes:
    1. Consecutive identical paragraphs are collapsed to one.
    2. Any paragraph longer than 40 chars appearing more than 10 times
       total is capped at 10 occurrences (keeps the first 10).

    Headings and code fences are never dropped.
    """

def deobfuscate_email(text: str) -> tuple[str, tuple[int, int]] | None:
    """Reverse common anti-spam email obfuscation patterns.

    Handles three families (checked most-specific-first):
    - Underscore-based: ``user_at_domain.com`` (n5038/n5040 pattern)
    - Word/bracket AT+DOT: ``user at domain dot com``, all bracket variants
    - AT-only: ``user AT domain.tld`` (obfuscated AT, real dots in domain)

    Returns ``(email, (match_start, match_end))`` when the reconstructed
    address passes ``EMAIL_RE`` validation, or ``None``.  The span refers
    to the obfuscated region in *text* so callers can slice the name
    portion without re-matching.  Shared across HTML and PDF pipelines.
    """
    # called by: parse_author_lines

def enrich_reply_to_names(reply_to: list[str], author_names: list[str]) -> list[str]:
    """Pair bare ``<email>`` reply-to entries with author names.

    For each entry that has an email but no name (e.g. ``<daveed@example.com>``),
    extract the email local-part and domain, then check each *author_names*
    entry for a last-name match against either the local-part or the domain
    (case-insensitive).  If exactly one author matches, pair them.

    ``author_names`` should contain bare name strings (no email) already
    present in ``reply_to`` or elsewhere in the paper metadata.  Names that
    already have an email (contain ``<`` or ``@``) are skipped as candidates.

    Returns a new list; the input is not mutated.
    """
    # calls: _looks_like_person_name

def normalize_date(text: str) -> str | None:
    """Parse common date formats and return ISO YYYY-MM-DD, or None.

    Tries in order:
      1. ISO literal (YYYY-MM-DD) via DATE_RE
      2. Slash-separated YYYY/MM/DD (common in WG21 papers)
      3. Natural "Month DD, YYYY" (e.g. "February 22, 2026")
      4. European "DD Month YYYY" (e.g. "22 February 2026")

    Returns None when no recognized date format is found.
    """

def override_revision_from_filename(metadata: dict, path: Path) -> None:
    """Override document revision from filename when the base paper number
    matches but revisions differ. Skip when the extracted document has a
    D-prefix (draft), since D/P mismatches are expected WG21 workflow.
    """
    # called by: extract.apply_pdf_metadata_fallbacks, pipeline.run_pipeline

def parse_author_lines(lines, clean_line=None, skip_line=None):
    """Parse author name + email pairs from an iterable of raw line strings.

    Each entry in the returned list is either 'Name <email>' when a name
    and email are found together, or a bare name string when no email
    follows. `clean_line` normalizes each line before processing (default:
    str.strip). `skip_line` returns True for lines that are not author
    content, such as metadata labels (default: never skip).
    """
    # untyped: lines, clean_line, skip_line, return
    # calls: deobfuscate_email

def strip_format_chars(text: str) -> str:
    """Remove Unicode format characters (category Cf)."""

def strip_freeform_metadata_lines(md: str, metadata: dict | None = None) -> str:
    """Public entry point for free-form metadata stripping.

    Called from ``api.convert_paper`` after ``_strip_body_metadata_text``,
    so it runs on the final markdown but does not affect the golden-test
    layer (``run_pipeline`` / ``convert_html``).

    When ``metadata`` is provided, content-aware stripping kicks in:
    structural lines (headings, list items) carrying metadata and bare
    author+email lines are also removed.
    """
    # calls: _strip_freeform_metadata_lines
    # called by: writer.MarkdownWriter.write

def strip_leading_h1(body: str, title: str = '', max_level: int = 1) -> str:
    """Remove a leading heading from body text if it duplicates the title.

    Strips the first non-blank line if it is an ATX heading no deeper than
    `max_level` and either matches the front-matter title or (H1 only) is the
    very first content. The HTML path passes `max_level=2`: its body headings
    start at H2 (the title is the only H1), so a title-duplicate first heading
    arrives as `## Title`, not `# Title`. PDF keeps the default H1-only behavior.
    Also handles plaintext title echoes (no '#' prefix) and promotes a bare
    "Abstract" line immediately following to ``## Abstract``.
    """
    # calls: _titles_match
    # called by: apply_strip_leading_h1

def strip_orphan_toc_list(md: str) -> str:
    """Remove bullet-list TOCs orphaned before the first heading.

    Some WG21 PDFs have a minimal Table of Contents as a bullet list of
    section names (no dot-leaders, no page numbers). These survive PDF
    extraction as orphan content between the front matter and the first
    ``## `` heading. This helper strips them when the majority of bullet
    texts match actual headings in the document.
    """
    # calls: _find_front_matter_end

def strip_redundant_body_meta(md: str) -> str:
    """Remove body lines that duplicate YAML frontmatter metadata.

    Strips:
    - Standalone 'Document number: XXX' lines
    - Pipe tables immediately following front matter that contain only
      metadata fields (Document number, Date, Audience, Reply-to),
      followed by a --- HR separator
    """
    # calls: _strip_metadata_table

ALLOWED_LINK_SCHEMES = frozenset({'http', 'https', 'mailto'})

# Canonical mapping from a language spelling (a CSS class token, a Pandoc
# ``sourceCode`` suffix, or a standalone label line) to the fence language
# tomd emits. Single source of truth shared by the PDF standalone
# language-label detector (lib/pdf/structure.py) and the HTML class-based
# detector (lib/html/render.py) so the recognized-language set is not
# duplicated. Extend here, never in a consumer.
CODE_LANG_LABELS = ...

DATE_RE = re.compile('\\b(\\d{4}-\\d{2}-\\d{2})\\b')

DEFAULT_FENCE_LANG = 'cpp'

# Core pattern shapes (no anchors, no label context) reused across modules
# so every document- and section-number pattern has a single source of truth.
# `lib/pdf/types.py` builds the labeled PDF variants (DOC_FIELD_RE,
# SECTION_NUM_RE) on top of these.
DOC_NUM_PATTERN = '[DPN]\\d{3,5}R\\d+|[DPN]\\d{3,5}|N\\d{3,5}|SD-\\d+'

# Broad document-number match used for header stripping and HTML metadata.
# For line-anchored field extraction in PDF blocks, see DOC_FIELD_RE in
# lib/pdf/types.py, which targets "Document Number: PXXXXrN" line prefixes.
DOC_NUM_RE = re.compile(f'\\b({DOC_NUM_PATTERN})\\b', re.IGNORECASE)

EMAIL_RE = re.compile('[\\w.+-]+@[\\w.-]+\\.\\w+')

FORMAT_CHARS = ...

SECTION_NUM_PATTERN = f'(?:\\d+(?:\\.\\d+)*|{_ROMAN})'

# Leading section-number prefix used by the HTML renderer to strip a number
# (e.g. "2.1.3 " or "1. ") from heading text.
SECTION_NUM_PREFIX_RE = re.compile(f'^{SECTION_NUM_PATTERN}\\.?\\s+')

# + 6 private module-level names
```

<a id="lib-similarity-py"></a>

## `lib/similarity.py` ([source](../../src/tomd/lib/similarity.py))

Typed: 6 of 6 functions and methods (100%).

```python
"""String similarity algorithms for fuzzy matching.

Two independent algorithms with per-algorithm thresholds:
  1. SequenceMatcher - character-level (difflib, stdlib)
  2. Jaccard - word-level set overlap

A 200-character circuit breaker protects against expensive
comparisons on paragraph-length strings.

Format-agnostic: no domain-specific constants here. Callers
provide their own canonical sets and thresholds.
"""

def fuzzy_match_label(candidate: str, known: Iterable[str], threshold: float = _LABEL_MATCH_THRESHOLD) -> str | None:
    """Return the best-matching known label, or ``None`` if below *threshold*.

    Compares *candidate* against every string in *known* using symmetric
    SequenceMatcher similarity. Returns the highest-scoring known string
    whose score meets *threshold*, or ``None``.

    Callers provide the canonical set; this function carries no
    domain-specific knowledge.
    """
    # calls: _symmetric_similarity
    # called by: extract._match_field

def similar(a: str, b: str) -> bool:
    """True if EITHER algorithm scores above its calibrated threshold.

    The per-string check is lenient because the caller (TOC detection)
    provides a second guard via the 3+ consecutive run requirement.
    Identical strings short-circuit to True regardless of length; the
    200-char gate only protects against expensive fuzzy-compare work.
    """
    # calls: _sequence_similarity, _jaccard_similarity
    # called by: toc.find_toc_indices

def word_jaccard(a: str, b: str) -> float:
    """Public word-level Jaccard similarity (0.0-1.0).

    Lowercased whitespace-token set overlap. Two empty strings score 1.0;
    one empty scores 0.0. Used by the golden structural comparator for the
    per-block text axis.
    """
    # calls: _jaccard_similarity
    # called by: golden_compare._text_axis_score

# + 3 private module-level names
```

<a id="lib-tables-py"></a>

## `lib/tables.py` ([source](../../src/tomd/lib/tables.py))

Typed: 4 of 4 functions and methods (100%).

```python
"""Shared HTML-table markup for code-comparison tables ("Tony Tables").

The PDF emitter (``lib/pdf/emit.py::_render_html_table``) and the HTML renderer
(``lib/html/render.py::_render_mixed_code_table``) both emit side-by-side
comparison tables, and a paper's comparison should look the same whether it
arrived as a PDF or as HTML. This module owns the *markup primitives* both
sides share so that table tag, cell style, and code-cell wrapping are identical
by construction.

It deliberately owns only the markup, not the iteration: each converter keeps
its own row/cell walk because their inputs differ fundamentally (the PDF side
has spans plus rowspan/continuation/NB-ballot concerns; the HTML side has a DOM
with inline tags to preserve). The one residual difference is the *inner* text
of non-code cells: the PDF side passes escaped plain text, the HTML side passes
sanitized inline HTML. That is inherent to the inputs and out of scope here.
"""

def cell_style(num_cols: int) -> str:
    """Per-cell inline style with equal column widths for ``num_cols`` columns."""
    # called by: render._render_mixed_code_table, emit._render_html_table

def code_cell(tag: str, code_text: str, style: str, *, rowspan: int = 1) -> str:
    """Render a code cell: ``<pre><code>`` wrapping HTML-escaped ``code_text``.

    ``tag`` is ``"th"`` or ``"td"``. ``code_text`` is raw code; this function
    escapes it, so ``<``/``&``/quotes survive inside the ``<pre>``.
    Blank lines are preserved as ``&#10;`` so they survive HTML rendering.
    """
    # calls: _rowspan_attr
    # called by: render._render_mixed_code_table, emit._render_html_table

def text_cell(tag: str, inner_html: str, style: str, *, rowspan: int = 1) -> str:
    """Render a non-code cell. ``inner_html`` is emitted verbatim.

    The caller is responsible for preparing ``inner_html``: the PDF side passes
    HTML-escaped plain text, the HTML side passes sanitized inline HTML. This
    function never escapes, so it does not double-escape pre-escaped text nor
    mangle the kept inline tags.
    """
    # calls: _rowspan_attr
    # called by: render._render_mixed_code_table, emit._render_html_table

# Marker flagging a structure-preserving HTML table (vs a lossy flattened one).
# Emitted by the HTML renderer for every mixed table, and by the PDF emitter
# for CODE_COMPARISON tables (not its SPEC_TABLE / nb_ballot kinds).
MIXED_TABLE_MARKER = '<!-- tomd:mixed-table -->'

TABLE_CLOSE = '</table>'

# Inline-styled table open tag. WG21 markdown is consumed by renderers with no
# shared stylesheet, so the presentation travels with the element.
TABLE_OPEN = ...

# + 1 private module-level name
```

<a id="lib-toc-py"></a>

## `lib/toc.py` ([source](../../src/tomd/lib/toc.py))

Typed: 7 of 7 functions and methods (100%).

```python
"""Table of Contents detection.

Format-agnostic: operates on plain strings and returns indices.
No dependency on PDF or HTML converter types.
"""

def find_toc_indices(texts: list[str], headings: set[str], structural_hints: list[bool] | None = None, full_texts: list[str] | None = None, is_heading: list[bool] | None = None) -> set[int]:
    """Return indices of entries that form a Table of Contents.

    texts: ordered list of section first-line texts from the document
    headings: set of known heading texts to match against
    structural_hints: optional per-section booleans marking entries that
        look like TOC entries by structure (standalone page number on the
        second line at a consistent x position). Used as a fallback when
        headings is empty, e.g. in headingless wording-only papers.
    full_texts: optional full section texts (multi-line). When provided,
        dot-leader detection checks the full text, catching leaders on
        lines beyond the first.
    is_heading: optional per-section booleans marking which sections are
        themselves headings in the body. A heading cannot count as a TOC
        *match* (it would match itself against the heading set and the
        gap-fill would then swallow the prose between body headings, deleting
        the body of short papers) UNLESS its own text is shaped like a TOC
        line (see _toc_structured), which preserves stripping of a genuine
        numbered TOC entry that section numbering classified as a heading.

    Production contract: any caller that passes a non-empty `headings` set
    derived from the document's own headings MUST also pass `is_heading`.
    Omitting it resurrects the body-deletion bug (every heading self-matches).
    A debug line is logged when the likely-misuse shape is seen.

    Both texts and headings are normalized before comparison. Detects runs
    of MIN_TOC_RUN+ consecutive matches, bridging only trivial gap sections
    (see _bridgeable). Also includes any "Table of Contents" label immediately
    preceding a run.

    Companion pass: a heading-kind TOC whose entries lack the dot-leader shape
    is deliberately *not* matched here (the is_heading guard), so it leaks as
    empty duplicate headings; `pdf/structure.py:drop_leaked_toc_entries`
    removes those, gating on the same shared `MIN_TOC_RUN`. The two functions
    are the structural and the post-structure halves of one "what is a TOC"
    definition; keep them in sync.
    """
    # calls: normalize_toc_entry, similarity.similar, has_dot_leader, _toc_structured, _first_line, _bridgeable, is_toc_label
    # called by: pipeline.run_pipeline

def has_dot_leader(text: str) -> bool:
    """Check for dot leaders in any form (compact or spaced).

    Uses _DOT_LEADER_DETECT_RE (5+ dots) instead of _DOT_LEADER_RE (2+)
    to avoid false positives on ellipsis and C++ variadic syntax.
    """
    # called by: pipeline.run_pipeline, find_toc_indices

def is_toc_label(text: str) -> bool:
    """Check if text is a TOC heading label."""
    # called by: pipeline._leading_contents, pipeline.run_pipeline, structure.drop_leaked_toc_entries, table._same_page_contents_label, find_toc_indices

def normalize_toc_entry(text: str) -> str:
    """Normalize text for TOC comparison.

    Strips trailing page numbers, dot leaders, section number prefixes.
    Collapses whitespace, lowercases.
    """
    # calls: _first_line
    # called by: structure._has_alpha_title, structure.drop_leaked_toc_entries, find_toc_indices

# Minimum length of a contiguous run that counts as a Table of Contents.
# Public because `pdf/structure.py:drop_leaked_toc_entries` (the
# companion pass that removes leaked TOC entries that `find_toc_indices`
# deliberately stops matching, #122) gates on the same run length. Shared
# so the two "what is a TOC" definitions cannot drift.
MIN_TOC_RUN = 3

# + 3 private module-level names
```

<a id="lib-wording-cleanup-py"></a>

## `lib/wording_cleanup.py` ([source](../../src/tomd/lib/wording_cleanup.py))

Typed: 1 of 1 functions and methods (100%).

```python
"""Redundant-tag cleanup for a rendered wording section.

When a section is overwhelmingly one role, its inline ``<ins>`` /
``<del>`` tags say nothing the section's own role does not, and they
bury the prose in markup. :func:`strip_redundant_tags` removes them
while preserving contrarian tags (a ``<del>`` inside an otherwise
inserted block marks an intra-block edit and must survive).

Both the PDF emitter (``lib/pdf/wording_emit.py``) and the HTML renderer
(``lib/html/render.py``) call this on the text they have just rendered,
passing the section's wording class. It used to run instead as a pass
over the assembled Markdown, keyed on the ``:::wording-add`` fences the
emitters wrapped each section in; those fences are no longer emitted, so
the role is handed in directly rather than parsed back out. The
character-ratio policy is unchanged.

Code-shaped sections are unaffected, exactly as before. A uniform-role
fenced block carries no inline role tags and trips the "no role chars"
early return; a mixed fenced diff is rendered as a neutral ``wording``
section and trips the ``implicit is None`` early return, so its
``<ins>`` / ``<del>`` markers stay literal inside the fence.
"""

def strip_redundant_tags(div_class: str, text: str) -> str:
    """Strip inline role tags that a uniform-role wording section repeats.

    ``div_class`` is the section's wording class (``wording-add``,
    ``wording-remove``, or the neutral ``wording``); ``text`` is the
    already-rendered Markdown for that one section.

    Idempotent: running this on already-clean output is a no-op. Neutral
    sections are never modified (they exist exactly to carry mixed
    ``<ins>`` / ``<del>`` diffs).
    """
    # calls: wording_policy.implicit_role_for
    # called by: render._render_wording_div, wording_emit._render_wording_section
```

<a id="lib-wording-markup-py"></a>

## `lib/wording_markup.py` ([source](../../src/tomd/lib/wording_markup.py))

Typed: 1 of 1 functions and methods (100%).

```python
"""Single source of truth for tomd wording-markup syntax.

Proposed standard-text edits are emitted as inline ``<ins>``/``<del>``
tags and nothing else. The emitters (``lib.pdf.wording_emit``,
``lib.html.render``), the scoring detector (``lib.pdf.qa``), and the
content checker (``lib.check_content``) all depend on this exact syntax.
Defining it once here, and deriving both the emitter format helper and
the checker strip rules from the same constants, makes them unable to
drift apart.

tomd no longer emits Pandoc fenced wording divs (``:::wording-add`` ...
``:::``): they duplicated what the inline tags already say and were pure
noise in the converted Markdown. The fence *recognizer* below survives
only so ``lib.check_content`` can normalize a ``<pid>.md`` produced by an
older tomd; nothing emits that syntax any more.

New wording emission must go through the helper here, not a fresh
literal: a hardcoded ``<ins>`` at a new call site is the one drift the
round-trip test (``tests/test_wording_markup.py``) cannot see.
"""

def wording_tag_open(tag: str, inner: str) -> str:
    """Inline edit tag wrapping ``inner``, e.g. ``<ins>x</ins>``."""
    # called by: render._inline_text_nodes, blocks._wrap_wording_tag

# Legacy fenced-div syntax, recognized but never emitted. ``WORDING_CLASSES``
# must equal the wording ``SectionKind`` values; ``test_wording_markup``
# asserts the enum agreement so the two cannot diverge silently.
LEGACY_FENCE_MARKER = ':::'

LEGACY_WORDING_FENCE_RE = ...

WORDING_CLASSES = ('wording', 'wording-add', 'wording-remove')

# Inline edit tags.
WORDING_TAGS = ('ins', 'del')

WORDING_TAG_RE = ...
```

<a id="lib-wording-policy-py"></a>

## `lib/wording_policy.py` ([source](../../src/tomd/lib/wording_policy.py))

Typed: 1 of 1 functions and methods (100%).

```python
"""Shared wording-emit/cleanup policy.

The PDF emitter (``lib/pdf/emit.py`` and its ``lib/pdf/wording_emit.py``
helpers) and the post-render cleanup pass (``lib/wording_cleanup.py``)
make two decisions against the same contract:

- the **uniform-role threshold**: at or above this fraction of role-bearing
  characters, a directional wording div is "uniform" enough that the
  inline ``<ins>`` / ``<del>`` tags are redundant with the div itself, and
- the **implicit role** carried by each directional div class.

These two values are the single boundary the two stages must agree on. If
they drift apart, emit can promote a section while cleanup leaves the tags
(or vice versa). Keeping them here makes that contract explicit and shared.

Emit-only knobs (monospace dominance, code-promotion minimum lines,
maximum reconstructed indent) intentionally do NOT live here: they depend
on span-level structure the assembled Markdown has already collapsed, so
cleanup can never use them.
"""

def implicit_role_for(div_class: str) -> str | None:
    """Return the inline role implied by a wording div class.

    ``wording-add`` implies ``ins``, ``wording-remove`` implies ``del``,
    and the neutral ``wording`` div implies no role (it exists exactly to
    carry mixed diffs). Unknown classes return ``None``.
    """
    # called by: wording_emit._render_wording_section, wording_cleanup.strip_redundant_tags, blocks.strip_redundant_roles

# At or above this fraction of role-bearing visible characters, a
# directional wording div is uniform and its inline role tags are
# redundant with the div-level signal.
UNIFORM_ROLE_THRESHOLD = 0.95
```

<a id="writers-init-py"></a>

## `writers/__init__.py` ([source](../../src/tomd/writers/__init__.py))

```python
"""Distributed under the Boost Software License, Version 1.0. (See accompanying

file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)

Official repository: https://github.com/cppalliance/wg21-paperflow
"""
```

<a id="writers-base-py"></a>

## `writers/base.py` ([source](../../src/tomd/writers/base.py))

Typed: 1 of 1 functions and methods (100%).

```python
"""Distributed under the Boost Software License, Version 1.0. (See accompanying

file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)

Official repository: https://github.com/cppalliance/wg21-paperflow
"""

@runtime_checkable
class DocumentWriter(Protocol):
    """Uniform backend interface for document emitters."""
    def write(self, document: PaperDocument, meta: dict[str, Any] | None = None) -> str:
        """Format a PaperDocument into output text representation."""
```

<a id="writers-markdown-init-py"></a>

## `writers/markdown/__init__.py` ([source](../../src/tomd/writers/markdown/__init__.py))

```python
"""Distributed under the Boost Software License, Version 1.0. (See accompanying

file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)

Official repository: https://github.com/cppalliance/wg21-paperflow
"""
```

<a id="writers-markdown-blocks-py"></a>

## `writers/markdown/blocks.py` ([source](../../src/tomd/writers/markdown/blocks.py))

Typed: 26 of 26 functions and methods (100%).

```python
"""Distributed under the Boost Software License, Version 1.0. (See accompanying

file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)

Official repository: https://github.com/cppalliance/wg21-paperflow
"""

def strip_redundant_roles(block: WordingBlock) -> WordingBlock:
    """Unwrap redundant inline role spans when ``block`` is uniformly one role."""
    # calls: wording_policy.implicit_role_for, _non_ws_len
    # called by: _write_wording_block

@singledispatch
def write_element(element: BlockElement) -> str:
    """Format a single BlockElement into Markdown text."""
    # called by: _format_blockquote, _format_list_item, _format_wording_child, writer.MarkdownWriter.write

# + 24 private module-level names
```

<a id="writers-markdown-front-matter-py"></a>

## `writers/markdown/front_matter.py` ([source](../../src/tomd/writers/markdown/front_matter.py))

Typed: 2 of 2 functions and methods (100%).

```python
"""Distributed under the Boost Software License, Version 1.0. (See accompanying

file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)

Official repository: https://github.com/cppalliance/wg21-paperflow
"""

def write_front_matter(metadata: PaperMetadata | dict[str, Any] | None) -> str:
    """Format metadata as YAML front matter via the canonical ``format_front_matter``."""
    # calls: format.format_front_matter, _drop_blanks
    # called by: writer.MarkdownWriter.write

# + 1 private module-level name
```

<a id="writers-markdown-normalizers-py"></a>

## `writers/markdown/normalizers.py` ([source](../../src/tomd/writers/markdown/normalizers.py))

Typed: 4 of 4 functions and methods (100%).

```python
"""Distributed under the Boost Software License, Version 1.0. (See accompanying

file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)

Official repository: https://github.com/cppalliance/wg21-paperflow
"""

def normalize_front_matter(md: str, mailing_meta: dict[str, Any] | None) -> str:
    """Parse front matter once, sanitize, apply mailing fallback, and re-emit."""
    # calls: format.parse_front_matter, format.strip_front_matter, format.sanitize_metadata, format.format_front_matter
    # called by: writer.MarkdownWriter.write

def strip_body_metadata_text(md: str) -> str:
    """Remove redundant metadata pipe tables from body text after front matter."""
    # called by: writer.MarkdownWriter.write

def strip_toc(text: str) -> str:
    """Remove Table of Contents block from Markdown string."""
    # called by: writer.MarkdownWriter.write

# + 1 private module-level name
```

<a id="writers-markdown-spans-py"></a>

## `writers/markdown/spans.py` ([source](../../src/tomd/writers/markdown/spans.py))

Typed: 14 of 14 functions and methods (100%).

```python
"""Distributed under the Boost Software License, Version 1.0. (See accompanying

file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)

Official repository: https://github.com/cppalliance/wg21-paperflow
"""

def format_code_span(code: str) -> str:
    """Format an inline code span handling embedded backticks."""
    # called by: _write_code_span, tables._format_pipe_cell

@singledispatch
def write_span(span: Span) -> str:
    """Recursively format a domain Span AST node into Markdown/HTML text."""
    # called by: write_spans

def write_spans(spans: Sequence[Span]) -> str:
    """Format a sequence of Spans into concatenated Markdown text."""
    # calls: write_span
    # called by: blocks._format_list_item, blocks._write_heading, blocks._write_paragraph, blocks._write_wording_spans, _write_deleted_span, _write_emphasis_span, _write_inserted_span, _write_link_span, _write_strong_span, _write_subscript_span, _write_superscript_span, tables._format_pipe_cell

# + 11 private module-level names
```

<a id="writers-markdown-tables-py"></a>

## `writers/markdown/tables.py` ([source](../../src/tomd/writers/markdown/tables.py))

Typed: 2 of 2 functions and methods (100%).

```python
"""Distributed under the Boost Software License, Version 1.0. (See accompanying

file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)

Official repository: https://github.com/cppalliance/wg21-paperflow
"""

def write_table(table: Table) -> str:
    """Format a Table AST node as a pure Markdown GFM pipe table."""
    # calls: _format_pipe_cell
    # called by: blocks._write_table, writer.MarkdownWriter.write

# + 1 private module-level name
```

<a id="writers-markdown-writer-py"></a>

## `writers/markdown/writer.py` ([source](../../src/tomd/writers/markdown/writer.py))

Typed: 1 of 1 functions and methods (100%).

```python
"""Distributed under the Boost Software License, Version 1.0. (See accompanying

file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)

Official repository: https://github.com/cppalliance/wg21-paperflow
"""

class MarkdownWriter:
    """Canonical Markdown backend writer and normalizer for PaperDocument ASTs."""
    def write(self, document: PaperDocument, meta: dict[str, Any] | None = None) -> str:
        """Format a PaperDocument into canonical Markdown text."""
        # calls: front_matter.write_front_matter, tables.write_table, blocks.write_element, normalizers.normalize_front_matter, normalizers.strip_body_metadata_text, shared.strip_freeform_metadata_lines, format.parse_front_matter, shared.apply_strip_leading_h1, normalizers.strip_toc
```

## Index

- `absorb_cross_page_spec_rows`: [`lib/pdf/docling_backend.py`](#lib-pdf-docling-backend-py)
- `ALLOWED_LINK_SCHEMES`: [`lib/shared.py`](#lib-shared-py)
- `ALLOWED_REASON_KEYS`: [`lib/pdf/vector_images.py`](#lib-pdf-vector-images-py)
- `anchors_path`: [`lib/golden_qa.py`](#lib-golden-qa-py)
- `apply_pdf_metadata_fallbacks`: [`lib/metadata_yaml/extract.py`](#lib-metadata-yaml-extract-py)
- `apply_strip_leading_h1`: [`lib/shared.py`](#lib-shared-py)
- `ascii_escape`: [`lib/shared.py`](#lib-shared-py)
- `assign`: [`lib/pdf/levels.py`](#lib-pdf-levels-py)
- `attach_links`: [`lib/pdf/extract.py`](#lib-pdf-extract-py)
- `AUDIENCE_RE`: [`lib/pdf/types.py`](#lib-pdf-types-py)
- `AxisReport`: [`lib/golden_qa.py`](#lib-golden-qa-py)
- `AxisScore`: [`lib/golden_compare.py`](#lib-golden-compare-py)
- `BAD_TABLE_FLAGS`: [`lib/pdf/select.py`](#lib-pdf-select-py)
- `BatchRunResult`: [`lib/batch.py`](#lib-batch-py)
- `bless_stem`: [`lib/golden_qa.py`](#lib-golden-qa-py)
- `Block`: [`lib/golden_compare.py`](#lib-golden-compare-py)
- `Block`: [`lib/pdf/types.py`](#lib-pdf-types-py)
- `BlockElement`: [`domain/elements.py`](#domain-elements-py)
- `Blockquote`: [`domain/elements.py`](#domain-elements-py)
- `build`: [`lib/pdf/summary.py`](#lib-pdf-summary-py)
- `build_review_prompt`: [`lib/golden_qa.py`](#lib-golden-qa-py)
- `BULLET_CHARS`: [`lib/pdf/types.py`](#lib-pdf-types-py)
- `BULLET_RE`: [`lib/pdf/types.py`](#lib-pdf-types-py)
- `candidate_from_section`: [`lib/pdf/select.py`](#lib-pdf-select-py)
- `candidates_agree`: [`lib/pdf/select.py`](#lib-pdf-select-py)
- `Cell`: [`domain/table.py`](#domain-table-py)
- `cell_markers`: [`lib/pdf/levels.py`](#lib-pdf-levels-py)
- `cell_style`: [`lib/tables.py`](#lib-tables-py)
- `CellAlign`: [`domain/table.py`](#domain-table-py)
- `check_paper_content`: [`lib/check_content.py`](#lib-check-content-py)
- `CheckContentArgError`: [`errors.py`](#errors-py)
- `class_check`: [`lib/pdf/select.py`](#lib-pdf-select-py)
- `classify_monospace`: [`lib/pdf/mono.py`](#lib-pdf-mono-py)
- `classify_wording`: [`lib/pdf/wording.py`](#lib-pdf-wording-py)
- `cleanup_text`: [`lib/pdf/cleanup.py`](#lib-pdf-cleanup-py)
- `closed_exempt`: [`lib/pdf/select.py`](#lib-pdf-select-py)
- `CLOSED_GRID_EXEMPT`: [`lib/pdf/select.py`](#lib-pdf-select-py)
- `code_cell`: [`lib/tables.py`](#lib-tables-py)
- `CODE_ERRORS`: [`lib/pdf/evidence.py`](#lib-pdf-evidence-py)
- `CODE_LANG_LABELS`: [`lib/shared.py`](#lib-shared-py)
- `CodeBlock`: [`domain/elements.py`](#domain-elements-py)
- `CodeCell`: [`domain/table.py`](#domain-table-py)
- `CodeGrid`: [`lib/pdf/code_grid.py`](#lib-pdf-code-grid-py)
- `CodeSpan`: [`domain/span.py`](#domain-span-py)
- `collect_glyph_candidates`: [`lib/pdf/glyphs.py`](#lib-pdf-glyphs-py)
- `collect_hyphen_evidence`: [`lib/pdf/cleanup.py`](#lib-pdf-cleanup-py)
- `collect_line_drawings`: [`lib/pdf/wording.py`](#lib-pdf-wording-py)
- `collect_links`: [`lib/pdf/extract.py`](#lib-pdf-extract-py)
- `collect_text_emoji_bboxes`: [`lib/pdf/glyphs.py`](#lib-pdf-glyphs-py)
- `comment`: [`lib/pdf/levels.py`](#lib-pdf-levels-py)
- `COMMON_LAYOUTS`: [`lib/pdf/summary.py`](#lib-pdf-summary-py)
- `compare`: [`lib/golden_compare.py`](#lib-golden-compare-py)
- `compare_extractions`: [`lib/pdf/structure.py`](#lib-pdf-structure-py)
- `COMPOUND_PREFIXES`: [`lib/pdf/types.py`](#lib-pdf-types-py)
- `compute_bbox`: [`lib/pdf/types.py`](#lib-pdf-types-py)
- `compute_content_coverage`: [`lib/check_content.py`](#lib-check-content-py)
- `compute_metrics`: [`lib/pdf/qa.py`](#lib-pdf-qa-py)
- `Confidence`: [`lib/pdf/types.py`](#lib-pdf-types-py)
- `conservation_error`: [`lib/pdf/select.py`](#lib-pdf-select-py)
- `ContainerSpan`: [`domain/span.py`](#domain-span-py)
- `ContentCheckBatchResult`: [`lib/check_content.py`](#lib-check-content-py)
- `ContentCheckResult`: [`lib/check_content.py`](#lib-check-content-py)
- `convert_html`: [`lib/html/convert.py`](#lib-html-convert-py)
- `convert_paper`: [`api.py`](#api-py)
- `convert_paper_full`: [`api.py`](#api-py)
- `ConvertedPaper`: [`api.py`](#api-py)
- `ConvertedPaper`: [`domain/document.py`](#domain-document-py)
- `cross_reader_continuation`: [`lib/pdf/select.py`](#lib-pdf-select-py)
- `current`: [`lib/pdf/runctx.py`](#lib-pdf-runctx-py)
- `DATE_RE`: [`lib/shared.py`](#lib-shared-py)
- `dedup_abstract`: [`lib/body/abstract.py`](#lib-body-abstract-py)
- `dedup_paragraphs`: [`lib/shared.py`](#lib-shared-py)
- `DEFAULT_FENCE_LANG`: [`lib/shared.py`](#lib-shared-py)
- `dehyphenate_pair`: [`lib/pdf/cleanup.py`](#lib-pdf-cleanup-py)
- `DehyphenatedPair`: [`lib/pdf/cleanup.py`](#lib-pdf-cleanup-py)
- `DeletedSpan`: [`domain/span.py`](#domain-span-py)
- `deobfuscate_email`: [`lib/shared.py`](#lib-shared-py)
- `detect_figure_regions`: [`lib/pdf/figures.py`](#lib-pdf-figures-py)
- `detect_generator`: [`lib/html/extract.py`](#lib-html-extract-py)
- `detect_repeating`: [`lib/pdf/cleanup.py`](#lib-pdf-cleanup-py)
- `detect_tables`: [`lib/pdf/table.py`](#lib-pdf-table-py)
- `discover_tables_with_docling`: [`lib/pdf/docling_backend.py`](#lib-pdf-docling-backend-py)
- `DOC_FIELD_RE`: [`lib/pdf/types.py`](#lib-pdf-types-py)
- `DOC_NUM_PATTERN`: [`lib/shared.py`](#lib-shared-py)
- `DOC_NUM_RE`: [`lib/shared.py`](#lib-shared-py)
- `docling_available`: [`lib/pdf/docling_backend.py`](#lib-pdf-docling-backend-py)
- `DocumentWriter`: [`writers/base.py`](#writers-base-py)
- `download_source`: [`lib/golden_qa.py`](#lib-golden-qa-py)
- `draft_issues`: [`lib/golden_gaps.py`](#lib-golden-gaps-py)
- `drawn_spans`: [`lib/pdf/ruled.py`](#lib-pdf-ruled-py)
- `drop_glyphs_in_code_and_tables`: [`lib/pdf/glyphs.py`](#lib-pdf-glyphs-py)
- `drop_leaked_toc_entries`: [`lib/pdf/structure.py`](#lib-pdf-structure-py)
- `EDGE_BAND_BOTTOM_FRACTION`: [`lib/pdf/types.py`](#lib-pdf-types-py)
- `EDGE_ITEMS_PER_PAGE`: [`lib/pdf/types.py`](#lib-pdf-types-py)
- `ElementKind`: [`domain/elements.py`](#domain-elements-py)
- `EMAIL_RE`: [`lib/shared.py`](#lib-shared-py)
- `emit_markdown`: [`lib/pdf/emit.py`](#lib-pdf-emit-py)
- `emit_prompts`: [`lib/pdf/emit.py`](#lib-pdf-emit-py)
- `EMOJI_PRESENTATION_RANGES`: [`lib/pdf/emoji_data.py`](#lib-pdf-emoji-data-py)
- `EmphasisSpan`: [`domain/span.py`](#domain-span-py)
- `enrich_pdf_reply_to`: [`lib/metadata_yaml/extract.py`](#lib-metadata-yaml-extract-py)
- `enrich_reply_to_names`: [`lib/shared.py`](#lib-shared-py)
- `enrich_tables_with_docling`: [`lib/pdf/docling_backend.py`](#lib-pdf-docling-backend-py)
- `Entry`: [`lib/pdf/evidence.py`](#lib-pdf-evidence-py)
- `ERROR_MESSAGE_LIMIT`: [`lib/pdf/runctx.py`](#lib-pdf-runctx-py)
- `escape_leading_atx`: [`lib/pdf/cleanup.py`](#lib-pdf-cleanup-py)
- `exclude_table_regions`: [`lib/pdf/table.py`](#lib-pdf-table-py)
- `extract_docling_tables`: [`lib/pdf/docling_backend.py`](#lib-pdf-docling-backend-py)
- `extract_metadata`: [`lib/html/extract.py`](#lib-html-extract-py)
- `extract_metadata`: [`lib/metadata_yaml/extract.py`](#lib-metadata-yaml-extract-py)
- `extract_metadata_from_blocks`: [`lib/pdf/wg21.py`](#lib-pdf-wg21-py)
- `extract_mupdf`: [`lib/pdf/extract.py`](#lib-pdf-extract-py)
- `extract_page_images`: [`lib/pdf/images.py`](#lib-pdf-images-py)
- `extract_page_vector_images`: [`lib/pdf/vector_images.py`](#lib-pdf-vector-images-py)
- `extract_poll_tables`: [`lib/pdf/poll.py`](#lib-pdf-poll-py)
- `extract_ruled_tables`: [`lib/pdf/ruled.py`](#lib-pdf-ruled-py)
- `extract_spatial`: [`lib/pdf/extract.py`](#lib-pdf-extract-py)
- `extract_tagged_tables`: [`lib/pdf/tagged.py`](#lib-pdf-tagged-py)
- `ExtractedImage`: [`domain/image.py`](#domain-image-py)
- `ExtractedImage`: [`lib/pdf/images.py`](#lib-pdf-images-py)
- `ExtractionResult`: [`lib/pdf/images.py`](#lib-pdf-images-py)
- `facts_path`: [`lib/golden_qa.py`](#lib-golden-qa-py)
- `FALLBACK_BODY_SIZE`: [`lib/pdf/types.py`](#lib-pdf-types-py)
- `FALLBACK_FONT_SIZE`: [`lib/pdf/types.py`](#lib-pdf-types-py)
- `fidelity_verdict`: [`lib/golden_qa.py`](#lib-golden-qa-py)
- `FidelityVerdict`: [`lib/golden_qa.py`](#lib-golden-qa-py)
- `FigureEdge`: [`lib/pdf/types.py`](#lib-pdf-types-py)
- `FigureGraph`: [`lib/pdf/types.py`](#lib-pdf-types-py)
- `FigureNode`: [`lib/pdf/types.py`](#lib-pdf-types-py)
- `FigureRegion`: [`lib/pdf/types.py`](#lib-pdf-types-py)
- `filter_coincident`: [`lib/pdf/glyphs.py`](#lib-pdf-glyphs-py)
- `finalize_extraction`: [`lib/pdf/images.py`](#lib-pdf-images-py)
- `find_hidden_regions`: [`lib/pdf/cleanup.py`](#lib-pdf-cleanup-py)
- `find_source`: [`lib/golden_qa.py`](#lib-golden-qa-py)
- `find_toc_indices`: [`lib/toc.py`](#lib-toc-py)
- `format_batch_finished`: [`lib/batch.py`](#lib-batch-py)
- `format_batch_progress_line`: [`lib/batch.py`](#lib-batch-py)
- `format_batch_timeout`: [`lib/batch.py`](#lib-batch-py)
- `FORMAT_CHARS`: [`lib/shared.py`](#lib-shared-py)
- `format_code_span`: [`writers/markdown/spans.py`](#writers-markdown-spans-py)
- `format_content_check_report`: [`lib/check_content.py`](#lib-check-content-py)
- `format_front_matter`: [`lib/metadata_yaml/format.py`](#lib-metadata-yaml-format-py)
- `format_qa_report`: [`lib/pdf/qa.py`](#lib-pdf-qa-py)
- `format_uncertainty_marker`: [`lib/pdf/vector_images.py`](#lib-pdf-vector-images-py)
- `FRONT_MATTER_ORDER`: [`lib/metadata_yaml/format.py`](#lib-metadata-yaml-format-py)
- `FRONT_MATTER_RE`: [`lib/metadata_yaml/format.py`](#lib-metadata-yaml-format-py)
- `fuzzy_match_label`: [`lib/similarity.py`](#lib-similarity-py)
- `Gap`: [`lib/golden_gaps.py`](#lib-golden-gaps-py)
- `generate_ideal`: [`lib/golden_qa.py`](#lib-golden-qa-py)
- `generator`: [`lib/pdf/summary.py`](#lib-pdf-summary-py)
- `get_edge_items`: [`lib/pdf/cleanup.py`](#lib-pdf-cleanup-py)
- `GLYPH_FONT_SENTINEL`: [`lib/pdf/glyphs.py`](#lib-pdf-glyphs-py)
- `GLYPH_PLACEHOLDER_MARKER_TEMPLATE`: [`lib/pdf/glyphs.py`](#lib-pdf-glyphs-py)
- `glyph_to_char`: [`lib/pdf/glyphs.py`](#lib-pdf-glyphs-py)
- `GlyphCandidate`: [`lib/pdf/glyphs.py`](#lib-pdf-glyphs-py)
- `GlyphPassStats`: [`lib/pdf/glyphs.py`](#lib-pdf-glyphs-py)
- `has_dot_leader`: [`lib/toc.py`](#lib-toc-py)
- `header_comment`: [`lib/pdf/summary.py`](#lib-pdf-summary-py)
- `Heading`: [`domain/elements.py`](#domain-elements-py)
- `heading_confidence`: [`lib/pdf/structure.py`](#lib-pdf-structure-py)
- `HtmlImagesResult`: [`lib/html/images.py`](#lib-html-images-py)
- `HyphenEvidence`: [`lib/pdf/cleanup.py`](#lib-pdf-cleanup-py)
- `ideal_path`: [`lib/golden_qa.py`](#lib-golden-qa-py)
- `ImageElement`: [`domain/elements.py`](#domain-elements-py)
- `implicit_role_for`: [`lib/wording_policy.py`](#lib-wording-policy-py)
- `inject_glyph_spans`: [`lib/pdf/glyphs.py`](#lib-pdf-glyphs-py)
- `InsertedSpan`: [`domain/span.py`](#domain-span-py)
- `is_diagram_block`: [`lib/pdf/code_format.py`](#lib-pdf-code-format-py)
- `is_flagged_table`: [`lib/pdf/emit.py`](#lib-pdf-emit-py)
- `is_foreign_chromatic`: [`lib/pdf/wording.py`](#lib-pdf-wording-py)
- `is_glyph_only_block`: [`lib/pdf/glyphs.py`](#lib-pdf-glyphs-py)
- `is_green_ins`: [`lib/pdf/wording.py`](#lib-pdf-wording-py)
- `is_readable`: [`lib/pdf/types.py`](#lib-pdf-types-py)
- `is_red_del`: [`lib/pdf/wording.py`](#lib-pdf-wording-py)
- `is_toc_label`: [`lib/toc.py`](#lib-toc-py)
- `is_unedited_seed`: [`lib/golden_qa.py`](#lib-golden-qa-py)
- `is_wording_rgb`: [`lib/pdf/wording.py`](#lib-pdf-wording-py)
- `issue_for_stem`: [`lib/golden_qa.py`](#lib-golden-qa-py)
- `join_split_words`: [`lib/pdf/select.py`](#lib-pdf-select-py)
- `KEPT_WHEN_UNREPLACED`: [`lib/pdf/select.py`](#lib-pdf-select-py)
- `KNOWN_GENERATORS`: [`lib/pdf/summary.py`](#lib-pdf-summary-py)
- `KNOWN_SECTIONS`: [`lib/pdf/types.py`](#lib-pdf-types-py)
- `LEGACY_FENCE_MARKER`: [`lib/wording_markup.py`](#lib-wording-markup-py)
- `LEGACY_WORDING_FENCE_RE`: [`lib/wording_markup.py`](#lib-wording-markup-py)
- `Line`: [`lib/pdf/types.py`](#lib-pdf-types-py)
- `LINE_SPACING_RATIO`: [`lib/pdf/types.py`](#lib-pdf-types-py)
- `LineBreakSpan`: [`domain/span.py`](#domain-span-py)
- `LinkSpan`: [`domain/span.py`](#domain-span-py)
- `LIST_BULLET`: [`lib/pdf/emit.py`](#lib-pdf-emit-py)
- `ListBlock`: [`domain/elements.py`](#domain-elements-py)
- `ListEntry`: [`lib/golden_compare.py`](#lib-golden-compare-py)
- `ListItem`: [`domain/elements.py`](#domain-elements-py)
- `load_html_images`: [`lib/html/images.py`](#lib-html-images-py)
- `locate_gaps`: [`lib/golden_gaps.py`](#lib-golden-gaps-py)
- `main`: [`cli.py`](#cli-py)
- `mark_matrix`: [`lib/pdf/select.py`](#lib-pdf-select-py)
- `MarkdownWriter`: [`writers/markdown/writer.py`](#writers-markdown-writer-py)
- `MAX_FILL`: [`lib/pdf/rowbands.py`](#lib-pdf-rowbands-py)
- `maybe_normalize_code_line`: [`lib/pdf/code_format.py`](#lib-pdf-code-format-py)
- `merge_rule_bands`: [`lib/pdf/rowbands.py`](#lib-pdf-rowbands-py)
- `MIN_IMAGE_DIM_PT`: [`lib/pdf/images.py`](#lib-pdf-images-py)
- `MIN_RULES`: [`lib/pdf/rowbands.py`](#lib-pdf-rowbands-py)
- `MIN_SEGMENT`: [`lib/pdf/rowbands.py`](#lib-pdf-rowbands-py)
- `MIN_TOC_RUN`: [`lib/toc.py`](#lib-toc-py)
- `MIN_UNCERTAIN_WORDS`: [`lib/pdf/types.py`](#lib-pdf-types-py)
- `MisalignedRegion`: [`lib/check_content.py`](#lib-check-content-py)
- `MIXED_TABLE_MARKER`: [`lib/tables.py`](#lib-tables-py)
- `NAMES`: [`lib/pdf/levels.py`](#lib-pdf-levels-py)
- `normalize`: [`lib/golden_compare.py`](#lib-golden-compare-py)
- `normalize_code_line`: [`lib/pdf/code_format.py`](#lib-pdf-code-format-py)
- `normalize_date`: [`lib/shared.py`](#lib-shared-py)
- `normalize_front_matter`: [`writers/markdown/normalizers.py`](#writers-markdown-normalizers-py)
- `normalize_spans`: [`lib/pdf/spans.py`](#lib-pdf-spans-py)
- `normalize_toc_entry`: [`lib/toc.py`](#lib-toc-py)
- `normalize_whitespace`: [`lib/pdf/cleanup.py`](#lib-pdf-cleanup-py)
- `NormalizedDoc`: [`lib/golden_compare.py`](#lib-golden-compare-py)
- `NUMBERED_LIST_RE`: [`lib/pdf/types.py`](#lib-pdf-types-py)
- `override_revision_from_filename`: [`lib/shared.py`](#lib-shared-py)
- `page_furniture`: [`lib/pdf/select.py`](#lib-pdf-select-py)
- `page_hrules`: [`lib/pdf/ruled.py`](#lib-pdf-ruled-py)
- `PAGE_NUM_RE`: [`lib/pdf/types.py`](#lib-pdf-types-py)
- `PageEdgeItem`: [`lib/pdf/types.py`](#lib-pdf-types-py)
- `PaperDocument`: [`domain/document.py`](#domain-document-py)
- `PaperMetadata`: [`domain/metadata.py`](#domain-metadata-py)
- `PARA_SPACING_RATIO`: [`lib/pdf/types.py`](#lib-pdf-types-py)
- `Paragraph`: [`domain/elements.py`](#domain-elements-py)
- `parse_author_lines`: [`lib/shared.py`](#lib-shared-py)
- `parse_front_matter`: [`lib/metadata_yaml/format.py`](#lib-metadata-yaml-format-py)
- `parse_html`: [`lib/html/extract.py`](#lib-html-extract-py)
- `partial_reading`: [`lib/pdf/select.py`](#lib-pdf-select-py)
- `PipelineResult`: [`lib/pdf/pipeline.py`](#lib-pdf-pipeline-py)
- `promote_abstract_from_uncertain`: [`lib/body/abstract.py`](#lib-body-abstract-py)
- `prompt_elements`: [`lib/pdf/summary.py`](#lib-pdf-summary-py)
- `propagate_monospace`: [`lib/pdf/mono.py`](#lib-pdf-mono-py)
- `QABatchResult`: [`lib/pdf/qa.py`](#lib-pdf-qa-py)
- `QAMetrics`: [`lib/pdf/qa.py`](#lib-pdf-qa-py)
- `rawdict`: [`lib/pdf/pagecache.py`](#lib-pdf-pagecache-py)
- `REASON_ASPECT_EXTREME`: [`lib/pdf/vector_images.py`](#lib-pdf-vector-images-py)
- `REASON_BBOX_TOO_LARGE`: [`lib/pdf/vector_images.py`](#lib-pdf-vector-images-py)
- `REASON_CLUSTERS_OVERFLOW`: [`lib/pdf/vector_images.py`](#lib-pdf-vector-images-py)
- `REASON_EDGE_BAND`: [`lib/pdf/vector_images.py`](#lib-pdf-vector-images-py)
- `REASON_TEXT_OVERLAP`: [`lib/pdf/vector_images.py`](#lib-pdf-vector-images-py)
- `REASON_TOO_FEW_ITEMS`: [`lib/pdf/vector_images.py`](#lib-pdf-vector-images-py)
- `REASON_TOO_SMALL`: [`lib/pdf/vector_images.py`](#lib-pdf-vector-images-py)
- `REASON_WORDING_COLOR`: [`lib/pdf/vector_images.py`](#lib-pdf-vector-images-py)
- `rebless_stems`: [`lib/golden_qa.py`](#lib-golden-qa-py)
- `ReblessOutcome`: [`lib/golden_qa.py`](#lib-golden-qa-py)
- `Record`: [`lib/pdf/evidence.py`](#lib-pdf-evidence-py)
- `remove_table_regions`: [`lib/pdf/select.py`](#lib-pdf-select-py)
- `render_body`: [`lib/html/render.py`](#lib-html-render-py)
- `render_pdf_pages`: [`lib/golden_qa.py`](#lib-golden-qa-py)
- `renumber_uncertain_markers`: [`lib/pdf/emit.py`](#lib-pdf-emit-py)
- `reorder_abstract_in_uncertain`: [`lib/body/abstract.py`](#lib-body-abstract-py)
- `REPEATING_THRESHOLD`: [`lib/pdf/types.py`](#lib-pdf-types-py)
- `REPLY_TO_CONTINUATION_CAP`: [`lib/pdf/wg21.py`](#lib-pdf-wg21-py)
- `REPLY_TO_RE`: [`lib/pdf/types.py`](#lib-pdf-types-py)
- `rescue_stranded_abstract_body`: [`lib/body/abstract.py`](#lib-body-abstract-py)
- `review_ideal`: [`lib/golden_qa.py`](#lib-golden-qa-py)
- `review_skill_text`: [`lib/golden_qa.py`](#lib-golden-qa-py)
- `run_content_check_batch`: [`lib/check_content.py`](#lib-check-content-py)
- `run_parallel_batch`: [`lib/batch.py`](#lib-batch-py)
- `run_pipeline`: [`lib/pdf/pipeline.py`](#lib-pdf-pipeline-py)
- `run_qa_batch`: [`lib/pdf/qa.py`](#lib-pdf-qa-py)
- `run_scope`: [`lib/pdf/runctx.py`](#lib-pdf-runctx-py)
- `RunContext`: [`lib/pdf/runctx.py`](#lib-pdf-runctx-py)
- `RUNNING_FOOTER_MAX_WORDS`: [`lib/pdf/types.py`](#lib-pdf-types-py)
- `sanitize_metadata`: [`lib/metadata_yaml/format.py`](#lib-metadata-yaml-format-py)
- `score_report`: [`lib/golden_qa.py`](#lib-golden-qa-py)
- `score_result`: [`lib/golden_qa.py`](#lib-golden-qa-py)
- `score_stem`: [`lib/golden_qa.py`](#lib-golden-qa-py)
- `ScoreResult`: [`lib/golden_qa.py`](#lib-golden-qa-py)
- `Section`: [`lib/pdf/types.py`](#lib-pdf-types-py)
- `SECTION_NUM_PATTERN`: [`lib/shared.py`](#lib-shared-py)
- `SECTION_NUM_PREFIX_RE`: [`lib/shared.py`](#lib-shared-py)
- `SECTION_NUM_RE`: [`lib/pdf/types.py`](#lib-pdf-types-py)
- `SectionKind`: [`lib/pdf/types.py`](#lib-pdf-types-py)
- `select_tables`: [`lib/pdf/select.py`](#lib-pdf-select-py)
- `should_emit_marker`: [`lib/pdf/vector_images.py`](#lib-pdf-vector-images-py)
- `SHOWN_FROM`: [`lib/pdf/levels.py`](#lib-pdf-levels-py)
- `similar`: [`lib/similarity.py`](#lib-similarity-py)
- `SIMILARITY_THRESHOLD`: [`lib/pdf/types.py`](#lib-pdf-types-py)
- `SkipReason`: [`domain/document.py`](#domain-document-py)
- `SkipReason`: [`lib/pdf/types.py`](#lib-pdf-types-py)
- `source_dir`: [`lib/golden_qa.py`](#lib-golden-qa-py)
- `Span`: [`domain/span.py`](#domain-span-py)
- `Span`: [`lib/pdf/types.py`](#lib-pdf-types-py)
- `sparse_mapping`: [`lib/pdf/select.py`](#lib-pdf-select-py)
- `split_at_headers`: [`lib/pdf/select.py`](#lib-pdf-select-py)
- `split_stacked`: [`lib/pdf/stacked.py`](#lib-pdf-stacked-py)
- `stage_source`: [`lib/golden_qa.py`](#lib-golden-qa-py)
- `stitch_pages`: [`lib/pdf/select.py`](#lib-pdf-select-py)
- `strip_body_metadata_text`: [`writers/markdown/normalizers.py`](#writers-markdown-normalizers-py)
- `strip_boilerplate`: [`lib/html/extract.py`](#lib-html-extract-py)
- `strip_format_chars`: [`lib/shared.py`](#lib-shared-py)
- `strip_freeform_metadata_lines`: [`lib/shared.py`](#lib-shared-py)
- `strip_front_matter`: [`lib/metadata_yaml/format.py`](#lib-metadata-yaml-format-py)
- `strip_hidden_blocks`: [`lib/pdf/cleanup.py`](#lib-pdf-cleanup-py)
- `strip_leading_h1`: [`lib/shared.py`](#lib-shared-py)
- `strip_metadata_from_uncertain`: [`lib/body/abstract.py`](#lib-body-abstract-py)
- `strip_metadata_headings`: [`lib/metadata_yaml/strip.py`](#lib-metadata-yaml-strip-py)
- `strip_orphan_toc_list`: [`lib/shared.py`](#lib-shared-py)
- `strip_pre_content_paragraphs`: [`lib/metadata_yaml/strip.py`](#lib-metadata-yaml-strip-py)
- `strip_pre_heading_fragments`: [`lib/metadata_yaml/strip.py`](#lib-metadata-yaml-strip-py)
- `strip_redundant_body_meta`: [`lib/shared.py`](#lib-shared-py)
- `strip_redundant_roles`: [`writers/markdown/blocks.py`](#writers-markdown-blocks-py)
- `strip_redundant_tags`: [`lib/wording_cleanup.py`](#lib-wording-cleanup-py)
- `strip_repeating`: [`lib/pdf/cleanup.py`](#lib-pdf-cleanup-py)
- `strip_toc`: [`writers/markdown/normalizers.py`](#writers-markdown-normalizers-py)
- `StrongSpan`: [`domain/span.py`](#domain-span-py)
- `StructuralScore`: [`lib/golden_compare.py`](#lib-golden-compare-py)
- `structure_body`: [`lib/pdf/structure.py`](#lib-pdf-structure-py)
- `structure_sections`: [`lib/pdf/structure.py`](#lib-pdf-structure-py)
- `SubscriptSpan`: [`domain/span.py`](#domain-span-py)
- `SuperscriptSpan`: [`domain/span.py`](#domain-span-py)
- `Table`: [`domain/table.py`](#domain-table-py)
- `TABLE_CLOSE`: [`lib/tables.py`](#lib-tables-py)
- `table_flags`: [`lib/pdf/select.py`](#lib-pdf-select-py)
- `TABLE_OPEN`: [`lib/tables.py`](#lib-tables-py)
- `TableCandidate`: [`lib/pdf/types.py`](#lib-pdf-types-py)
- `TableKind`: [`lib/pdf/table.py`](#lib-pdf-table-py)
- `TableRow`: [`domain/table.py`](#domain-table-py)
- `TableStrategy`: [`domain/table.py`](#domain-table-py)
- `TableStrategy`: [`lib/pdf/table.py`](#lib-pdf-table-py)
- `TERMINAL_PUNCTUATION`: [`lib/pdf/types.py`](#lib-pdf-types-py)
- `text_cell`: [`lib/tables.py`](#lib-tables-py)
- `TextCell`: [`domain/table.py`](#domain-table-py)
- `TextSpan`: [`domain/span.py`](#domain-span-py)
- `ThematicBreak`: [`domain/elements.py`](#domain-elements-py)
- `tomd_markdown`: [`lib/golden_qa.py`](#lib-golden-qa-py)
- `TomdError`: [`errors.py`](#errors-py)
- `TRUNCATION_MARKER_TEMPLATE`: [`lib/pdf/images.py`](#lib-pdf-images-py)
- `UncertainElement`: [`domain/elements.py`](#domain-elements-py)
- `unfamiliarity`: [`lib/pdf/summary.py`](#lib-pdf-summary-py)
- `UNICODE_EMOJI_VERSION`: [`lib/pdf/emoji_data.py`](#lib-pdf-emoji-data-py)
- `UNIFORM_ROLE_THRESHOLD`: [`lib/wording_policy.py`](#lib-wording-policy-py)
- `UNKNOWN_GLYPH`: [`lib/pdf/glyphs.py`](#lib-pdf-glyphs-py)
- `UnsupportedSourceFormatError`: [`errors.py`](#errors-py)
- `validate_anchors_json`: [`lib/golden_qa.py`](#lib-golden-qa-py)
- `validate_facts_jsonl`: [`lib/golden_qa.py`](#lib-golden-qa-py)
- `VECTOR_UNCERTAINTY_MARKER_TEMPLATE`: [`lib/pdf/vector_images.py`](#lib-pdf-vector-images-py)
- `VectorUncertaintyStats`: [`lib/pdf/images.py`](#lib-pdf-images-py)
- `vote_header`: [`lib/pdf/select.py`](#lib-pdf-select-py)
- `VOTE_LABELS`: [`lib/pdf/select.py`](#lib-pdf-select-py)
- `WITHHOLD_TRUST_FOR_CODE_CELLS`: [`lib/pdf/select.py`](#lib-pdf-select-py)
- `WITHHOLD_TRUST_UNTIL_VERIFIED`: [`lib/pdf/select.py`](#lib-pdf-select-py)
- `witness`: [`lib/pdf/select.py`](#lib-pdf-select-py)
- `WORD_GAP_RATIO`: [`lib/pdf/types.py`](#lib-pdf-types-py)
- `word_jaccard`: [`lib/similarity.py`](#lib-similarity-py)
- `WORDING_CLASSES`: [`lib/wording_markup.py`](#lib-wording-markup-py)
- `wording_tag_open`: [`lib/wording_markup.py`](#lib-wording-markup-py)
- `WORDING_TAG_RE`: [`lib/wording_markup.py`](#lib-wording-markup-py)
- `WORDING_TAGS`: [`lib/wording_markup.py`](#lib-wording-markup-py)
- `WordingBlock`: [`domain/elements.py`](#domain-elements-py)
- `write_content_check_json_atomic`: [`lib/check_content.py`](#lib-check-content-py)
- `write_element`: [`writers/markdown/blocks.py`](#writers-markdown-blocks-py)
- `write_front_matter`: [`writers/markdown/front_matter.py`](#writers-markdown-front-matter-py)
- `write_qa_json_atomic`: [`lib/pdf/qa.py`](#lib-pdf-qa-py)
- `write_span`: [`writers/markdown/spans.py`](#writers-markdown-spans-py)
- `write_spans`: [`writers/markdown/spans.py`](#writers-markdown-spans-py)
- `write_table`: [`writers/markdown/tables.py`](#writers-markdown-tables-py)
- `Y_TOLERANCE`: [`lib/pdf/types.py`](#lib-pdf-types-py)
- `ZERO_WIDTH_CHARS`: [`lib/pdf/types.py`](#lib-pdf-types-py)
