# Port map: tomd `tables-reportlab` onto paperflow `packages/tomd`

Sources read: `work/paperflow/paperflow-tomd.api.md` (paperflow, master cab5420), `wt/tomd/doc/api/tomd.api.md`, `wt/tomd/doc/design-tomd.md`, `wt/tomd/doc/plan-tomd-tables.md`, paperflow `packages/tomd/src/tomd/CLAUDE.md`, `improvements.md`, root `CLAUDE.md`. Sources were opened only to confirm the points cited as `module.py:line`. Paperflow has no `plans/` folder.

The two packages share an ancestor. `types.py` (Block/Line/Span/Section/Confidence) is nearly identical on both sides. After the split, paperflow grew the original text-position detector into a 6,951-line `lib/pdf/table.py` with Docling, figures, images, glyphs and a domain/writer layer. Our branch kept a 1,611-line `table.py` and built the multi-reader, evidence-based table path around it.

Classes: **a** = paperflow already has it, possibly in another form. **b** = conflicts with paperflow's design. **c** = can be added cleanly.

## Summary table

| # | Our component / decision | Class | Paperflow location | Note |
|---|---|---|---|---|
| 1 | Tagged reader (structure tree) | c | not found | new `lib/pdf/tagged.py`, run inside the `run_pipeline` fitz session |
| 2 | Poll reader | a | `table.py:_detect_horizontal_row_tables` (Pass 3), `_is_lone_vote_header` | text-position form only; no pipe/drawn-poll path |
| 3 | Grid reader (ruled both ways) | a | `pipeline.py:_detect_drawing_grids`, `table.py:_detect_mupdf_native_tables` (Pass 5), `_detect_inline_grid_tables` (2b), `_rows_from_drawn_grid` | uses MuPDF `find_tables` plus synthetic grids |
| 4 | Rule-band reader (booktabs, shaded rows) | c | not found (`_grid_from_rule_chain` needs vertical rules) | `_detect_banded_rotated_tables` covers rotated bands only |
| 5 | Column-rules reader | c | not found | |
| 6 | Code-pairs reader | a | `table.py:_detect_side_by_side_tables` (Pass 2), `_merge_code_rows` → `TableKind.CODE_COMPARISON` | rendering conflicts (row 42) |
| 7 | Content-first builder | c | not found | |
| 8 | Records reader | c | not found (`TableKind.BIBLIOGRAPHY` is a classification) | |
| 9 | Text-position reader | a | `table.py:detect_tables` (pre-pass, Passes 1–5, post-passes) | far more evolved than ours; open question 1 |
| 10 | Rotated pages / upright copy | a | `pipeline.py` `page_rotations`, `table.py:_rot_bbox`, `_assemble_rotated_fragment` | different mechanism |
| 11 | Level-0 document measure | c | not found | `docmeasure.measure` |
| 12 | Evidence record | c | not found | must become per-run, not module-global (row 34) |
| 13 | Region scan and `checks/` | c | not found | |
| 14 | Selection across competing readings | b | `detect_tables`: each pass consumes blocks | no competing readings exist to compare |
| 15 | Conservation check | c | not found (`check_content.py` is paper-level coverage) | |
| 16 | HIGH only on agreement plus conservation | b | `Confidence.HIGH` set by every pass (`table.py:1098,1807,2008,…`), `docling_backend.py:743` | paperflow trusts single-source tables |
| 17 | Gate / layout classifier (trees) | b | `table.py:_compute_table_signals`, `_classify_table`, `_STRATEGY_MAP` | rule-based `TableKind` picks the rendering, not the trust |
| 18 | Verification (layout, fit witness, relations, dimensions) | c | not found | |
| 19 | Repairs (escalation, smallest-set, inferred cells) | c | not found | |
| 20 | Extent step, header-below, full-width, stacked | a | `table.py:_collect_header_cluster`, `_absorb_hash_header_above_number`, `_drop_separator_rows`, `_detect_header_block` | header absorption only |
| 21 | Trust levels L0–L5 | b | `types.Confidence` is "the output contract" (`improvements.md` §1.5) | no flagged-table state; tables carry no level |
| 22 | Possible-table marks / drop-to-mark | b | FALSE_POSITIVE → `emit._render_table_as_text` with no marker; `pipeline.py:2456` dot-leader demotion; `pipeline._filter_sections_inside_vector_images` | paperflow drops silently |
| 23 | One marker per marked area (grouping) | c | `emit_markdown` UNCERTAIN loop (`emit.py:1252`) | |
| 24 | Hidden text / visibility, appendix | b | `cleanup.find_hidden_regions`, `strip_hidden_blocks` | paperflow deliberately ignores render mode 3 |
| 25 | Unreadable text layer → `tomd:not-converted`; skipped → `tomd:skipped` | b | `pipeline._enforce_skip_contract`, `SkipReason.UNREADABLE` | the contract asserts empty md |
| 26 | Graphic-text / image-page warnings | b | none; front matter must lead (`FRONT_MATTER_RE = \A---`) | ours puts warnings before the front matter |
| 27 | Summary JSON and paper confidence | c | `PipelineResult`, `api.ConvertedPaper`, `cli/orchestrator.py` → `backend.write_intermediate` | new fields plus one write |
| 28 | Prompts file (one Markdown string) | b | `emit.emit_prompts -> list[str] \| None`, stored as `<pid>.prompts.json` | different shape and contract |
| 29 | LLM repair and second look | b | root `CLAUDE.md` (model sovereignty, D1, D6), tomd `CLAUDE.md` "LLM v2 deferred" | direct Anthropic SDK, hard-coded models |
| 30 | LLM budgets (run, paper, check) | b | `pipeline` `UsageLimits` (D9) | paperflow budgets through its own runner |
| 31 | LLM code guard | c | — | pure function, moves with the tier |
| 32 | Determinism (byte-identical under any hash seed) | c | root `CLAUDE.md` Determinism/D7 (prompt ordering only), `vector_images.py:484` | no seed test found |
| 33 | Locality (one table answers for itself) | b | `cleanup.collect_hyphen_evidence` (document-wide), `table._merge_cross_page_fragments` | |
| 34 | Per-run state under concurrency | b | `_fitz_lock._FITZ_LOCK`, `tests/test_concurrent_convert.py` | our module globals are not thread-safe |
| 35 | Rule-band rows plus fill guard | c | not found | `rowbands.merge_rule_bands` after selection |
| 36 | Continuation notes, never joined | b | `table_continuation=True` (`table.py:4515,5286,6762`), `emit.py:1216` fold, `docling_backend.absorb_cross_page_spec_rows` | paperflow joins pages |
| 37 | Image-grid check (never HIGH) | c | not found | `classify.image_share` |
| 38 | Reader-error scoping | c | not found | |
| 39 | Hyphen dictionary in cells (table words plus pinned list) | b | `cleanup.dehyphenate_pair` / `HyphenEvidence`, applied by `cleanup_text` before `detect_tables` | doc-wide evidence edits cell lines first |
| 40 | Number rule (two numbers on two lines never join) | c | `emit._flatten_cell` | |
| 41 | Span flattening, `tomd:merged`, `tomd:use` | b | `lib/tables.py` HTML tables (`TABLE_OPEN`, rowspan), `emit._render_html_table` | paperflow renders HTML for SPEC/NB tables |
| 42 | Code-comparison rendering (paired fences) | b | `_STRATEGY_MAP[CODE_COMPARISON]=HTML_TABLE`, `MIXED_TABLE_MARKER` | |
| 43 | TOC fixes (a selected table is never contents) | b | `pipeline.py:2456` demotes dot-leader TABLE; `structure.drop_leaked_toc_entries`; `api._strip_toc` | |
| 44 | Figure-table labels | c | `figures.detect_figure_regions` → `FigureRegion` | could reuse paperflow's regions |
| 45 | Opt-in OCR check, Jev tier | c | — | extra dependency (tesseract) |

Counts: **a = 6, b = 18, c = 21** (45 rows).

## Per-component notes

### The readers

- **1 Tagged (c).** Nothing in paperflow reads the structure tree. The `blk_tagged` hits in `table.py:3248` are unrelated. `extract_tagged_tables(doc)` needs the open `doc`, so call it inside the `with _FITZ_LOCK:` session in `run_pipeline`, next to the per-page `get_drawings()` loop (`pipeline.py:2033`).
- **2 Poll (a).** Pass 3 handles SF/F/N/A/SA headers and synthesises an empty suggested-poll row (`_is_lone_vote_header`). It works from blocks only. Ours (`poll.extract_poll_tables(page, page_num)`) reads page words and handles pipes and drawn polls. Port ours as a separate reader; Pass 3 becomes part of the text-position reading.
- **3 Grid (a).** `_detect_drawing_grids` injects synthetic `find_tables()` entries (`source="drawing_grid"`) into `page_mupdf_tables`, and Pass 5 and Pass 2b consume them. Ours (`ruled.extract_ruled_tables(page, page_num, drawings)`) is an independent paths-type reader. Both can coexist: ours as a witness, theirs inside the text-position reader. Never count the two as two independent witnesses, since both read paths.
- **4–5 Rule band, column rules (c).** `_grid_from_rule_chain` keeps only rules "joined by a vertical rule" (`pipeline.py:390`), so booktabs and ReportLab rule-per-row tables are not read as grids. Add `ruled.py` (rule bands and `_column_ruled_tables`) unchanged.
- **6 Code pairs (a).** Pass 2 is the Tony-Table detector. Our `codepair.find_code_pairs` adds same-code evidence (meaning). Keep Pass 2 inside the text-position reading and add ours as a reader.
- **7–8 Content builder, records (c).** No content-first builder or periodic-line reader exists. Attach `content.content_candidates(pages, regions, …)` and `records.records_candidates` after the scan, as now.
- **9 Text positions (a).** Paperflow's `detect_tables(blocks, *, page_mupdf_tables, two_column_pages)` is the strongest piece to keep. It is corpus-tuned on 768 tables, and it handles two-column pages and citation, YBA and contents-list families. Wrap its sections with our `candidate_from_section` and feed them to selection as the `tomd` source, instead of porting our 1,611-line `table.py:detect_tables`.
- **10 Rotation (a).** Paperflow handles rotated pages by bbox transforms and `_detect_banded_rotated_tables`. Ours makes an upright copy of each page (`_upright_page`). Pick one per reader; mixing the two coordinate frames in one evidence record is a bug risk.
- **11 Level 0 (c).** `docmeasure.measure(page_words)`. No paperflow equivalent.

### Evidence, scan, selection and verification

- **12 Evidence record (c).** Nothing in paperflow corresponds. `evidence.current()` / `reset()` is a module global; in paperflow it must be a per-run object threaded through `run_pipeline` (row 34).
- **13 Scan (c).** `scan.run_scan(path, record, tables, builds)` reopens the PDF by path. Every fitz use must hold `_FITZ_LOCK` (`_fitz_lock.py` lists the sites), so add it to that list.
- **14 Selection (b).** Each `detect_tables` pass removes the blocks it matched, so there is exactly one reading per region. Our design needs every reader to read the same region. Paperflow's passes stay as one reader (row 9), and `select_tables` arbitrates outside them.
- **15 Conservation (c).** `conservation_error(cand, blocks)` needs blocks before `detect_tables` consumes them. Paperflow already snapshots them for Docling (`pre_detect_blocks`, `pipeline.py:2210`); take the same snapshot unconditionally.
- **16 Agreement (b).** Every paperflow pass sets `Confidence.HIGH`. The one exception is `_split_trailing_horizontal_rows` → MEDIUM (`table.py:3491`). Docling discoveries are also HIGH (`docling_backend.py:743`). Porting ours lowers most paperflow tables to UNCERTAIN, which moves its goldens and its `qa` score.
- **17 Gate (b).** Paperflow's `_classify_table` returns a `TableKind` that selects the rendering (`_STRATEGY_MAP`). FALSE_POSITIVE renders as paragraphs. Our `classify.gate_tables(doc, pages, sections)` uses learned trees for table-or-not and layout class, and can only lower trust (or raise on a pure leaf). The two taxonomies differ: keep `TableKind` for rendering and ours for trust.
- **18–19 Verification, repairs (c).** These are pure functions over a Section plus page words (`validate.verify_layout`, `fit.fit`, `relations.check`, `validate.escalate`, `repair.place_stray_words`). They attach after selection, before structure.
- **20 Extent (a).** `_collect_header_cluster` (header rows above on the table's columns) overlaps our extent "alignment" rule. Run our `extent.extend` on all candidates and leave paperflow's post-pass inside the text-position reader. Expect double-attachment cases.

### Trust, marks and the output contract

- **21 Levels (b).** Paperflow's `Confidence` enum is declared a stable output contract, and tables have no flagged state. `levels.assign(sec)` can be added as metadata plus a `tomd:level` comment, but tables that today render plain will gain markers.
- **22 Marks (b).** Paperflow loses candidates without a trace in three places. FALSE_POSITIVE tables render as text with no marker. A dot-leader TABLE is demoted to PARAGRAPH. CODE/TABLE sections mostly inside a vector cluster are dropped (`_filter_sections_inside_vector_images`, only when `extract_vector`). Our policy needs each of these to leave a mark or a `removed` entry.
- **23 Grouping (c).** The UNCERTAIN loop at `emit.py:1252` writes one marker per section. Our grouping replaces it.
- **24 Visibility (b).** Paperflow's `find_hidden_regions` targets Google Docs widget text and "intentionally ignores" render mode 3, because MuPDF dict output already drops it. Ours redacts mode 3 and six more classes and quotes the text in a fenced appendix in `paper.md`. Downstream paperflow agents read `paper.md`, which `wrap_source` wraps, so the appendix puts possibly injected text in front of them (open question 4).
- **25 Skip/unreadable (b).** `_enforce_skip_contract` raises `AssertionError` when `skipped` is set and md is non-empty, or when `readable=False` without `skipped`. Ours writes `<!-- tomd:skipped:… -->` and `<!-- tomd:not-converted … -->` into md (`lib/pdf/__init__.py:189,502`). The orchestrator writes nothing for skipped papers (`cli/orchestrator.py:79`).
- **26 Warnings (b).** Ours runs `md = warn + md` (`lib/pdf/__init__.py:852`), which puts the warnings above the front matter. `api._normalize_front_matter` parses with `\A---`, so fallback and key ordering would fail. Move the warnings below the front matter.
- **27 Summary (c).** Add `summary: dict | None` to `PipelineResult` and to `api.ConvertedPaper`. Have the orchestrator call `backend.write_intermediate(pid, "summary", …)`, the same way it stores prompts (`cli/jobs.py:508`). The `tomd:summary` header goes after the front matter. `api._normalize_front_matter` and `api._strip_toc` rewrite md afterwards, so every `tomd:uncertain:L…` line number (ours and theirs) can shift (open question 5).
- **28 Prompts (b).** Paperflow's contract is a JSON array, one self-contained prompt per uncertain region (tomd `CLAUDE.md`, "Honest Output"). Ours is one Markdown document with sections: alternatives, removed list, reader errors, visibility, summary. Port as extra array elements, or keep ours as a separate intermediate.

### The LLM tier

- **29–30 LLM tier and budgets (b).** Root `CLAUDE.md` requires that every LLM call go through `pipeline.run_agent` / `run_task` (D1). It also requires typed `output_type` (D6), `UsageLimits` passed to `run` (D9), and agents created by intent, not by model name. Pipelines must work on `vllm_thinking` open-weight backends ("Model sovereignty"). tomd's declared dependencies (pymupdf, bs4, mistune, ftfy, paperstore) exclude `anthropic`. Ours calls the Anthropic SDK directly, hard-codes `claude-opus-5-5` / `claude-sonnet-5-5`, needs a vision model, and reads budgets from `TOMD_LLM_*` environment switches.
- **31 Code guard (c).** `llmrepair.code_guard(first, repaired)` is pure and moves with whatever tier is ported.

### Invariants

- **32 Determinism (c).** Paperflow's rule is quality-stability, with D7 sorting only for prompts. No `PYTHONHASHSEED` byte-identity test exists for tomd. Add our two-seed test. Paperflow's `vector_images.py:484` already avoids hash randomness.
- **33 Locality (b).** `cleanup_text` applies document-wide `HyphenEvidence` to all blocks before `detect_tables`. A cell's text therefore depends on words elsewhere in the paper, which our rule forbids. Page-joining passes (`_merge_cross_page_fragments`, `_join_ruled_grid_continuations`, `_try_cross_page_continuation`) also tie tables across pages.
- **34 Concurrency (b).** Paperflow runs `run_pipeline` on threads (`test_concurrent_convert.py`), and `_FITZ_LOCK` covers only the fitz session. Several of ours are module globals: `evidence.current()`, `pagecache` caches, `emit.set_hyphenating` / `HYPHEN_STATS`, `llmrepair.reset_paper` / `paper_record`, and `llmcheck.state`. These would mix papers. Several of our post-close steps reopen fitz (`run_scan(path)`, `gate_tables(doc…)`, `continuation.annotate(doc…)`, `label_figure_tables(doc…)`, visibility rendering) and would need the lock.

### Rows, continuations and cell text

- **35 Rule-band rows (c).** `rowbands.merge_rule_bands(sec, rules)` works per section. Attach it after selection.
- **36 Continuations (b).** Paperflow strips the repeated header, sets `table_continuation=True`, and `emit_markdown` folds the piece into the previous TABLE. The fold mutates `prev.columns` in place (`emit.py:1216–1240`). Docling adds `absorb_cross_page_spec_rows`. Ours never joins: no measured signal separated continued tables from separate ones, and the note was right 10 of 15 times. Paperflow goldens expect the joins.
- **37 Image grid (c).** `classify.image_share(page, bbox)` attaches in the gate. It interacts with paperflow's raster/vector extraction: an image-cell grid may also become IMAGE sections.
- **38 Reader errors (c).** Paperflow has no per-reader `try`/`except`; a raise ends the paper. Wrap each reader with `evidence.reader_error(stage, page, exc, table)`.
- **39 Hyphens (b).** See row 33. Ours decides a cell's line-end hyphen from the table's own words plus `worddict` (pinned SHA-256). Paperflow has already joined the lines before any reader runs. Either keep `cleanup_text` from dehyphenating lines inside table candidates, or accept that block-based and word-based readers disagree.
- **40 Number rule (c).** Goes in the cell renderer that replaces `_flatten_cell`.

### Rendering, contents and figures

- **41–42 Rendering (b).** Paperflow emits inline-styled HTML `<table>` for SPEC_TABLE, NB_BALLOT and CODE_COMPARISON (`lib/tables.py`; NB rowspans). Code comparisons get `<!-- tomd:mixed-table -->` and `<pre><code>` cells. Ours writes pipe tables with spans flattened by meaning plus a `tomd:merged` comment, and code comparisons as paired fences under `tomd:table kind=code-comparison`. `golden_compare` parses only pipe tables (mistune `table` plugin), so each choice changes a different golden axis.
- **43 TOC (b).** `pipeline.py:2456` turns any TABLE with a dot leader into PARAGRAPH, so a selected table can be removed as contents. Ours forbids that and requires a TOC entry to name a later heading. `drop_leaked_toc_entries` and `api._strip_toc` are paperflow's two other TOC removers; keep both but exempt selected tables.
- **44–45 Figures, OCR, Jev (c).** `label_figure_tables(doc, sections)` could take paperflow's `FigureRegion`s. OCR needs tesseract, which is not in paperflow's dependencies; it is opt-in.

## Paperflow features we lack

| Feature | Module / function | What it does | Must the port preserve it? | Interaction with our design |
|---|---|---|---|---|
| Docling ML tables | `docling_backend.extract_docling_tables`, `enrich_tables_with_docling`, `discover_tables_with_docling`, `absorb_cross_page_spec_rows`; `run_pipeline(ml_tables=True)` | re-grids rule-based tables with TableFormer cells; adds tables only Docling saw; absorbs cross-page spec rows | It is opt-in and dead in production: `api._convert_with_tomd_full` and `cli` never pass `ml_tables`, and `docling` is not a dependency. Keep it compiling. | **Bypasses trust.** Discovered tables get `Confidence.HIGH` (`docling_backend.py:743`); enrichment replaces `columns` and keeps HIGH. Under our design Docling is one more words/vision reader: never a sole witness, its tables UNCERTAIN unless another type agrees. |
| Skip contract | `pipeline._enforce_skip_contract`, `PipelineResult.for_skip`, `SkipReason` | asserts skipped ⇔ empty md, typed reason, no images | Yes; tests `test_pipeline_skip_contract.py`; orchestrator relies on it | Conflicts with our `tomd:skipped` / `tomd:not-converted` markdown (row 25) |
| `tomd:glyph-placeholders` | `glyphs.GLYPH_PLACEHOLDER_MARKER_TEMPLATE`, `emit_markdown(glyph_stats=)` | U+FFFD for raster-only emoji glyphs, end-of-body count | Yes (always on) | `glyphs.drop_glyphs_in_code_and_tables` needs `Section.lines` on our tables. Glyph spans (`GLYPH_FONT_SENTINEL`) sit in blocks but not in page words, so block readers and word readers disagree. |
| `tomd:images-truncated` | `images.TRUNCATION_MARKER_TEMPLATE` | image cap (20) reached | Yes | none |
| `tomd:vector-extraction-uncertain` | `vector_images.format_uncertainty_marker`, `should_emit_marker` | per-paper vector accounting | Yes (opt-in `extract_vector`) | Vector clusters drop TABLE sections (row 22) and use TABLE bboxes to reject vectors (`pipeline._filter_vector_images_against_structural`) |
| `tomd:mixed-table` | `lib/tables.MIXED_TABLE_MARKER` | structure-preserving HTML table (HTML path and PDF code comparisons) | Yes on HTML; PDF use conflicts (row 42) | |
| `tomd:lossy-table` | `html/render.py:_LOSSY_TABLE_MARKER`; counted by `qa.py:44` | HTML table that could not be a pipe table | Yes (HTML only) | none for PDF |
| `tomd:svg-dropped` | `html/render.py:_DROPPED_SVG_MARKER` | HTML inline SVG removed | Yes (HTML only) | none |
| `tomd:uncertain prompt="…"` variant | `writers/markdown/blocks.py:312` | domain writer's form of the uncertainty marker | Keep; the domain path is not wired (below) | same marker name, different syntax from ours (`tomd:uncertain:L…`) |
| Figures | `figures.detect_figure_regions`, `types.FigureRegion/FigureGraph`, `SectionKind.FIGURE` | box-and-arrow diagrams → FIGURE (heading guard) | Yes | Diagram boxes look like grids; ours has `table.diagram_boxes` and `TOMD_DIAGRAMS` (off) |
| Raster images | `images.extract_page_images`, `finalize_extraction`, `ExtractedImage`, `SectionKind.IMAGE`, `pipeline._insert_image_sections`, caption attribution | sidecar image files plus italic caption | Yes (`ConvertedPaper.images`, paperstore writes) | Ours has no image extraction. Caption-band drops can remove table captions. |
| Vector images | `vector_images.extract_page_vector_images` | rasterise drawing clusters | Yes (opt-in) | Drops TABLE/CODE sections inside clusters silently (row 22) |
| Code grid | `code_grid.CodeGrid` (`for_code_section`, `for_gutter`, `indent`) | code indentation from glyph x | Yes; used by `emit`, `wording_emit` | Useful for our code-pair cells; not used by tables today |
| Code format, wording emit, dingbats, emoji | `code_format.normalize_code_line`, `is_diagram_block`; `wording_emit`; `emit._decode_dingbats`; `emoji_data` | code kerning cleanup, wording render, symbol decoding | Yes | `_decode_dingbats` runs inside table cell rendering; keep it in our renderer |
| Two-column pages | `pipeline._detect_column_split`, `_column_aware_sort`, `_insert_table_sections(…, column_splits)` | column-order reading and table insertion | Yes | Our insertion is by y only; reuse theirs |
| Domain layer | `domain/*` (`PaperDocument`, `Table`, `TextCell`, `CodeCell`, `UncertainElement`), `writers/markdown/*` (`MarkdownWriter`, `write_table`) | typed IR plus a writer | Keep; **not wired**: only tests and `domain`/`writers` import it | If wired later, `Table` has no confidence, level or page field (below) |
| Public API | `api.convert_paper`, `convert_paper_full`, `api.ConvertedPaper` | front-matter fallback, key order, `_strip_toc` | Yes (the only supported entry point) | Needs `summary`; post-processing shifts line markers |
| Paperstore integration | `cli/orchestrator.py`, `cli/jobs.py`, `StorageBackend.write_paper_md`, `write_intermediate`, `write_paper_image` | persistence | Yes | Summary JSON → `write_intermediate(pid,"summary")` |
| QA (markdown-only) | `qa.compute_metrics(md_text)`, `run_qa_batch`, `QAMetrics.uncertain_count`, `table_parse_errors`, `lossy_table_count` | scores from the Markdown text alone | Yes | Every marker we add costs QA score (`qa.py:399`, capped penalty), so our marks lower paperflow's QA |
| Content coverage | `check_content.check_paper_content`, `compute_content_coverage` | source-vs-md shingle coverage | Yes | The hidden-text appendix and comments may count as coverage |
| Golden QA | `golden_qa`, `golden_compare.compare`, `golden_gaps`, `cli` verbs (score/bless/rebless/anchor/fact/tables) | per-axis scores against blessed ideals | Yes | Port will move the baselines: rebless needed |
| Batch, abstract, metadata | `batch.run_parallel_batch`, `body.abstract.*`, `metadata_yaml.*` | parallel runs, abstract rescue, YAML fallback | Yes | none |
| fitz lock | `_fitz_lock._FITZ_LOCK` | serialises MuPDF sessions | Yes | Our extra fitz sites must join it |

## Data model: paperflow vs ours

Shared, identical in both API reports:

```python
class Confidence(Enum): HIGH='high'; MEDIUM='medium'; LOW='low'; UNCERTAIN='uncertain'
columns: list[list[list[Span]]] = field(default_factory=list)   # Section: rows -> cells -> spans
```

Paperflow `lib/pdf/types.py` `Section` adds table fields that ours does not have:

```python
    table_kind: str | None = None
    table_strategy: str | None = None
    table_source: str | None = None
    table_continuation: bool = False
    figure_graph: FigureGraph | None = None
    image_ref: 'ExtractedImage | None' = None
```

Paperflow `lib/pdf/table.py`:

```python
class TableKind(Enum):  CLEAN_MATRIX, INLINE_GRID, PROSE_TABLE, CODE_COMPARISON, SPEC_TABLE, KEY_VALUE, BIBLIOGRAPHY, NB_BALLOT, FALSE_POSITIVE
class TableStrategy(Enum):  PIPE_TABLE, CODE_BLOCKS, HTML_TABLE, SKIP
def detect_tables(blocks: list[Block], *, page_mupdf_tables: dict[int, list[dict]] | None = None, two_column_pages: frozenset[int] = frozenset()) -> tuple[list[Section], list[Block]]:
```

Paperflow domain layer (`domain/table.py`), not used by the PDF pipeline:

```python
class Table(BlockElement):
    headers: list[Cell] = field(default_factory=list)
    rows: list[TableRow] = field(default_factory=list)
    strategy: TableStrategy = TableStrategy.PIPE
    caption: str | None = None
```

Docling's intermediate form is a dict per table: `bbox`, `num_rows`, `num_cols`, `cells[{row, col, row_span, col_span, bbox, text}]`.

Ours (`lib/pdf/types.py`): there are no table fields on `Section`. Everything lives in `Section.metadata` (`table_source`, `level`, `page_bboxes`, `region_bbox`, `possible_table`, `continues_from`, `table_versions`, `witness`, `inferred_cells`, `llm_repair`, …). Candidates come before selection:

```python
@dataclass
class TableCandidate:
    source: str  # "tags" | "grid" | "rules" | "tomd"
    rows: list[list[list[Line]]]
    bboxes: dict[int, tuple[float, float, float, float]] = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)
```

Confidence representation:

| | Paperflow | Ours |
|---|---|---|
| Trust | `Section.confidence`, HIGH for nearly every table; MEDIUM in one pass | `Section.confidence` HIGH only on agreement plus conservation, otherwise UNCERTAIN |
| Grade | none | `metadata["level"]` L0–L5, from `levels.assign(sec) -> dict` |
| Kind | `table_kind` (rendering) | layout class from the gate trees |
| Provenance | `table_source` (pass name: `side_by_side_prepass`, `multirow_body`, …) | `metadata["table_source"]` (reader), `table_versions` |
| Pages | `page_num` (first page, 0-based) + line `page_num`s; continuation is a separate section | `metadata["page_bboxes"]` {page: bbox} |
| Paper-level | none (QA score is computed from md) | summary `confidence` {value, low, high, band, …} |

Our `Section.metadata` holds dicts and lists of tuples. Both sides type it `dict[str, str | list[str]]`, so this is a typing gap, not a runtime one.

## Entry point for scoring one PDF with our harness

The public API is `tomd.api.convert_paper_full(paper_id: str, source_path: Path, meta: dict, *, html_images_manifest=None, extract_vector: bool = False, whiteout_text: bool = False) -> ConvertedPaper`. It returns `markdown`, `prompts`, `intent`, `images`, `skipped`, `skip_reason`, but no per-table data, so scoring from it means parsing pipe and HTML tables out of the Markdown.

For per-table pages and cells, use the PDF entry it wraps, `tomd.lib.pdf.run_pipeline(path: Path, *, ml_tables=False, visualize=False, extract_vector=False, whiteout_text=False) -> PipelineResult`, and read `result.sections`:

```python
from tomd.lib.pdf import run_pipeline
from tomd.lib.pdf.types import SectionKind
r = run_pipeline(pdf)                                   # api uses ml_tables=False
tabs = [s for s in r.sections
        if s.kind == SectionKind.TABLE
        and not s.table_continuation                    # already folded into the previous table
        and s.table_strategy != "skip"]                 # FALSE_POSITIVE renders as text
for s in tabs:
    pages = sorted({ln.page_num for ln in s.lines} | {s.page_num})   # 0-based
    rows = [["".join(sp.text for sp in cell) for cell in row] for row in s.columns]
```

Caveats:

1. `emit_markdown` mutates the head table's `columns` in place to add the continuation rows (`emit.py:1216–1240`), while the continuation sections stay in `r.sections`. Skip them, or rows are counted twice. Their `page_num` gives the extra pages.
2. `Section.page_num` is 0-based; `ExtractedImage.page` is 1-based.
3. Dot-leader tables are demoted to PARAGRAPH, and vector-cluster drops apply only with `extract_vector=True`.
4. `r.skipped` papers have no sections.
5. The `tomd tables <pdf> [--page N]` CLI prints the same data (`p{page_num} RxC kind/source header`).

## Open questions for the user or the reviewer

1. **Which text-position reader?** Keep paperflow's 6,951-line `detect_tables` as the `tomd` source feeding our selection (recommended), or replace it with ours? Its passes consume blocks, so it can only be one reader, never several.
2. **Trust model.** Accept that most paperflow tables drop from HIGH to UNCERTAIN, gaining markers and losing `qa` score? Or ship levels as metadata only, without changing `Confidence` (`improvements.md` §1.5 calls the enum a contract)?
3. **Page joins.** Paperflow joins continuations (emit fold, Docling absorb); our measurement found no signal that justifies a join. Keep their joins, take our notes, or emit joins with a note?
4. **Hidden-text appendix in `paper.md`.** Paperflow agents read it (wrapped by `wrap_source`). Move the quoted text to the summary/prompts intermediate only?
5. **Line-numbered markers.** `api._normalize_front_matter` and `_strip_toc` rewrite md after emit, so `tomd:uncertain:L…` ranges (theirs and ours) can be stale. Recompute in `api.py`, or drop line numbers?
6. **Skip/unreadable.** Change `_enforce_skip_contract` to allow a marker-only md, or move our `not-converted` / `skipped` notes to `skip_reason` and the summary?
7. **LLM tier.** Re-home it on `pipeline.run_agent` with typed output and an intent-named, open-weight-capable vision agent, or leave it out of the port? It is Anthropic-only, hard-codes models, and ships as tomd env switches.
8. **About 90 `TOMD_*` switches.** Paperflow tomd reads no environment variables except `EDITOR`. Bake the measured defaults in and drop the switches, or keep them?
9. **Rendering.** For CODE_COMPARISON, SPEC_TABLE and NB_BALLOT, choose paperflow's HTML tables or our pipe tables plus `tomd:merged` / paired fences. Their goldens and `golden_compare` count only pipe tables.
10. **Domain layer.** `domain.Table` / `writers` are not wired into the PDF path. Port into `Section` (today's path) or wait for the IR? `Table` has no confidence, level or page fields.
11. **Docling.** Remove it, or make it a reader under our rules? Today it is opt-in, not a dependency, never called by the API, and marks its output HIGH.
12. **Hyphenation.** Exempt table-candidate lines from document-wide `cleanup_text` dehyphenation (locality), at the cost of a second pre-cleanup block copy?
13. **Concurrency.** Is converting the module-global evidence/pagecache/LLM state to a per-run context in scope for the port's first PR? It is required for threaded `run_pipeline`.
14. **Measurement.** Our numbers (84.2% tuning) were measured on our pipeline. After the port, the harness must re-run on paperflow's pipeline (two-column handling, glyphs, captions, Docling off) before any claim carries over.
