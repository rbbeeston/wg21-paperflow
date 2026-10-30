# Porting table trust into paperflow tomd: a plan in Python declarations

Our branch `tables-reportlab` (code at `5809ae7`) rebuilt tomd's PDF table path around one rule: trust a table only when independent kinds of evidence agree, and lose nothing silently. The merge target is now `cppalliance/wg21-paperflow` `packages/tomd` (master `cab5420`). The two packages share an ancestor but have diverged far: paperflow's `lib/pdf/table.py` is 6,951 lines against our 1,611, and paperflow added Docling, figures, images, glyphs, a skip contract and a golden QA workflow we never saw. This is a port in small gated steps, not a merge.

**Direction (decided 2026-10-27, Sean Parsons, paperflow's tomd owner, relayed by the user):** our work replaces tomd's table parsing now, before Sean works in that code. Where a component conflicts, ours replaces paperflow's parsing; the two are not reconciled side by side. Paperflow's public surface stays: the CLI, the output files, the skip contract, the model-sovereignty rules D1, D6 and D9, and anything paperflow-only callers use. Where ours lacks a paperflow feature (its page joins, its two-column handling, table families our readers do not cover), paperflow's piece stays, under our trust rules. Each step is shaped as one reviewable PR against `cppalliance/wg21-paperflow`, safety core first. Port existing work only: no new features or tuning until after the merge.

The plan follows [`tomd-tables-plan.md`](tomd-tables-plan.md): product contract, implementation contract, verification contract, decision record, execution plan. It is based on [`port-map.md`](port-map.md) (45 decisions classed a/b/c and 14 open questions); row numbers below (`row 16`) refer to that map.

Declarations carry one of four labels. **Generated (paperflow)**: printed by `tools/pyheader.py` from `wt_paperflow` at `cab5420`, no bodies. **Generated (ours)**: quoted from `doc/api/tomd.api.md` (pysurface, `5809ae7`). **Drawn**: data the code keeps in a plain `dict`. **Proposed**: no code exists yet on either side. In a diff block, `-` is paperflow today, `+` is the port, and an unmarked line is unchanged context.

<product-contract>

## Product Requirements

The rule carries over unchanged: a table is trusted only on agreement between different kinds of evidence plus conservation, every other table says how it may be wrong, and nothing is dropped without a trace. Paperflow's own rules already ask for this. Its tomd `CLAUDE.md` says "Never classify based on a single signal" and that disagreement "is the data", and `improvements.md` §1.5 keeps the `Confidence` enum as the contract while letting signals "raise or lower confidence". The port fits inside both.

- Problem and users:
  - Readers of `paper.md` are people and paperflow's analytical agents (dissect, agora), which read it wrapped by `pipeline.tools.wrap_source`. Programs read `PipelineResult`, `ConvertedPaper` and the paperstore intermediates.
  - Today paperflow sets `Confidence.HIGH` on nearly every table (every pass, and Docling discoveries), and `emit_markdown` never renders a TABLE section's confidence: only `SectionKind.UNCERTAIN` sections get markers (`emit.py:1252`), and only the `annotate` preview reads `sec.confidence`. A reader of `paper.md` sees every table as equally certain, right or wrong.
- Goals:
  - Bring paperflow to our safety floor first: no wrong table trusted, no table dropped silently, then raise accuracy reader by reader.
  - Keep paperflow's public surface (CLI, output files, skip contract, D1, D6, D9, interfaces paperflow-only callers use). In every other conflict our parsing replaces paperflow's (Table 2).
- Non-goals:
  - Changing paperflow's prose path, HTML path, image and figure extraction, front matter or skip semantics beyond what Table 2 names.
  - Wiring paperflow's unused `domain/` and `writers/` layer.
  - Any LLM call in ordinary conversion.
- Success criteria:
  - Every port step passes the release gate on paperflow's pipeline (verification contract).
  - After the safety core (steps 1 to 4): wrong trusted 0 and accuracy unchanged from paperflow's baseline.
  - After all readers: the paperflow port reaches our branch's numbers within the gate's noise, measured on paperflow's pipeline, not assumed from ours.
- Constraints:
  - Paperflow's rules (root `CLAUDE.md`): model sovereignty, D1 to D11, `Library functions return data. Callers persist`, no lazy imports, `__init__.py` re-exports only, named constants for thresholds, `logging` not `print`, commented broad excepts, no `default=str`, BSL-1.0 header on new files, no em dashes.
  - The comment syntax in the Markdown is a public format on both sides. New fields go at the end; nothing is renamed.

| Measure | paperflow `cab5420`, ml_tables off (PyMuPDF 1.27, its pin) | Control: ml off, PyMuPDF 2.0 (Docling environment) | paperflow ml_tables on, offline (PyMuPDF 2.0) | Ours `5809ae7` |
|---|---|---|---|---|
| Tuning: mean per-table accuracy (median) | 48.6% (45.1) | 47.6% (44.7) | 50.8% (60.6) | 84.2% (100) |
| Tuning: tables exactly right (of 1,746) | 630 | 543 | 422 | 1,280 |
| Tuning: missed | 725, none marked | 660, none marked | 600, none marked | 180, of which 47 silent |
| Tuning: trusted and exactly right | 562 | 481 | 367 | 447 (every trusted table is right) |
| Tuning: trusted on a key page, not exact (page-level, includes pieces) | 847 | 963 | 1,202 | 0 |
| Tuning: trusted on a page with no key table | 320 | 441 | 561 | 0 (false-HIGH 0) |
| fresh10: mean per-table accuracy (of 142) | 33.8% | 39.2% | 40.8% | 67.1% |
| fresh10: exact / missed | 32 / 78 | 34 / 66 | 26 / 60 | 67 / 31 |
| fresh10: trusted not exact / trusted false | 226 / 64 | 250 / 60 | 298 / 74 | 0 wrong trusted |
| Seconds per page, tuning / fresh10 (one process, run alone) | 0.050 / 0.064 | not timed (ran concurrently) | 0.279 / 0.356 | 0.111 / 0.189 (LLM off; full conversion with emit and summary) |

*Table 1. Baselines, same answer keys and scorer, gate denominators 1,746 (tuning) and 142 (fresh10). Paperflow's "trusted" is section confidence HIGH, which its Markdown does not show. The answer keys were built blind by AI agents from page images and the text layer, under conventions decided by a person; they are not hand-checked. Paperflow often writes a code comparison as separate fenced code blocks (`TableStrategy.CODE_BLOCKS`), which the scorer cannot see as a table, so part of its 725 misses is a rendering choice, not a detection failure. The ml_tables-on run used the Docling environment (PyMuPDF 2.0), so it compares with the control column, not the pinned one; it ran offline, one process, alone, with no errors and no download attempts. Against the control, ml_tables on raises the mean (47.6% to 50.8% on tuning, 39.2% to 40.8% on fresh10) but gets fewer tables exactly right (543 to 422; 34 to 26) and trusts more wrong or false tables (1,404 to 1,763 on tuning). The pinned column's "missed" counts key tables with no matching table; "trusted" counts are page-level, so a table broken into pieces counts once per piece.*

## Functional Specification

What changes for a paperflow user, and what stays.

- Tables are trusted only on agreement. `Section.confidence` stays the enum; it is `HIGH` only when two kinds of evidence agree and conservation holds, otherwise `UNCERTAIN`. No cell text changes in the step that introduces this.
- Each table carries a level L0 to L5 in `Section.metadata["level"]` (our Table 2 in [`tomd-tables-plan.md`](tomd-tables-plan.md): trusted, likely, minor, structure-uncertain, content-at-risk, mark-only). Flagged tables get a `tomd:level` comment plus paperflow's own `<!-- tomd:uncertain:L{a}-L{b} -->` marker, so paperflow's prompts, QA and readers keep one marker syntax.
- Every dropped candidate leaves a possible-table mark (L5) in the Markdown or a `removed` entry in the summary, including the three places paperflow drops silently today (row 22).
- A paper summary (counts by level, removed content and why, confidence, unfamiliarity) is returned on `PipelineResult.summary` and `ConvertedPaper.summary`, and the CLI persists it with `backend.write_intermediate(pid, "summary", ...)`, as it does prompts.
- What stays: YAML front matter is always first (`\A---`); the skip contract (skipped means empty md, typed `SkipReason`); `<pid>.prompts.json` as a JSON array of self-contained prompts, absent when nothing is uncertain; raster and vector images, figures, glyph placeholders and their markers; `ml_tables` stays opt-in and off.

| Row | Conflict | Proposed resolution | Who decides |
|---|---|---|---|
| 14, 16 | Paperflow's passes each consume blocks, so there is one reading per region, and every pass sets HIGH | Ours replaces it: our readers and `select_tables` decide every table. Paperflow passes that cover what ours does not (two-column pages, families our readers miss) stay as one reader under the agreement rule, and are removed once ours covers them | Decided (direction, 2026-10-27) |
| 17 | `TableKind` picks the rendering; our classifier picks trust | Our classifier decides trust; `TableKind` is kept only where it picks paperflow's public rendering (open question 9) | Decided (direction) |
| 21 | `Confidence` is a declared contract; tables have no level | Enum unchanged; level lives in `metadata` and a comment | Settled by `improvements.md` §1.5 |
| 22 | FALSE_POSITIVE, dot-leader demotion and vector-cluster drops leave no trace | Each leaves an L5 mark or a `removed` summary entry | Settled |
| 24 | Our hidden-text appendix puts possibly injected text into `paper.md`, which agents read | Remove hidden text from readers as now; quote it only in the summary and prompts intermediates, never in `paper.md` | Decided by default (open question 4) |
| 25 | Skip contract asserts empty md; ours writes `tomd:skipped` / `tomd:not-converted` | Keep paperflow's contract (public surface); our reason goes to `skip_reason` and the summary | Decided (direction) |
| 26 | Our warnings go above the front matter | Below the front matter, always | Settled |
| 28 | Prompts are a JSON array; ours is one Markdown file | Our sections become extra self-contained array elements, in a fixed sorted order | Settled |
| 29, 30 | Our LLM tier calls Anthropic directly with fixed models and env budgets | Last step, re-homed on `pipeline.run_agent` with typed output and `UsageLimits`, outside tomd's conversion (D1, D6, D9 kept) | Decided (direction) |
| 33, 39 | Document-wide hyphen evidence edits cell lines before any reader runs | Table-candidate lines are exempt from document-wide dehyphenation (a second block copy); word readers read the raw page words | Decided by default (open question 11) |
| 34 | Our module globals mix papers under threads | Per-run context, step 1 | Settled |
| 36 | Paperflow joins continued tables; ours never joins | Ours lacks a join, so paperflow's join stays under our trust rules: a `tomd:continues` note and a cap at L3 | Decided by default (open question 3) |
| 41, 42 | Paperflow renders SPEC, NB and code comparisons as HTML or separate fences; ours as pipe tables and paired fences | Keep paperflow's renderers through the readers; decide code comparisons in step 8 with numbers | Vinnie (open question 9) |
| 43 | Dot-leader demotion can remove a selected table as contents | A table with agreement is exempt; every demotion leaves a mark | Settled |

*Table 2. The conflicting decisions (class b in the map) and how the port resolves them. Default since 2026-10-27: ours replaces paperflow's parsing; paperflow's public surface and the features ours lacks stay.*

</product-contract>
<implementation-contract>

## Technical Design

Paperflow's pipeline stays the spine. Its `detect_tables` becomes one reader among several; our readers run inside the existing fitz session and write candidates into a per-run context; `select_tables` arbitrates after paperflow's `detect_tables` and before `_insert_table_sections`; verification, levels and marks follow; `emit_markdown` writes the comments; the CLI persists the summary.

- Attach points (paperflow `lib/pdf/pipeline.py`): the fitz session `with _FITZ_LOCK:` (`:1914` to `:2103`) for readers that need the open page or `doc` (tagged, ruled, poll, page words, drawings); the block snapshot `pre_detect_blocks` (`:2210`, today only when `ml_tables`) taken always, for conservation; `detect_tables` (`:2212`) unchanged; selection between `:2212` and `_insert_table_sections` (`:2257`); levels and marks after structure and the dot-leader demotion (`:2456`); `emit_markdown` (`:2665`) and `emit_prompts` (`:2673`).
- Post-close steps that reopen the PDF (scan, classifier, continuation notes, figure labels, visibility rendering) take `_FITZ_LOCK` and join the site list in `_fitz_lock.py`.
- Our `lib/pdf/__init__.py:_run_pipeline` logic goes into `pipeline.py` and new named modules, since paperflow's `__init__.py` files hold re-exports only.
- Rotated pages: per reader, one coordinate frame. Our readers keep the upright copy; paperflow's passes keep `_rot_bbox`. Candidates are converted to page coordinates before they enter the evidence record (row 10).

### Old: paperflow's declarations

```python
# Generated (paperflow cab5420): lib/pdf/types.py, excerpt
class Confidence(Enum):
    # Confidence level for structural classification decisions.
    HIGH = 'high'
    MEDIUM = 'medium'
    LOW = 'low'
    UNCERTAIN = 'uncertain'

@dataclass
class Section:
    # A classified region of the document.
    kind: SectionKind
    text: str
    confidence: Confidence = Confidence.HIGH
    heading_level: int = 0
    lines: list[Line] = field(default_factory=list)
    mupdf_text: str = ''
    spatial_text: str = ''
    page_num: int = 0
    font_size: float = 0.0
    metadata: dict[str, str | list[str]] = field(default_factory=dict)
    columns: list[list[list[Span]]] = field(default_factory=list)
    fence_lang: str = 'cpp'
    indent_level: int = 0
    table_kind: str | None = None
    table_strategy: str | None = None
    table_source: str | None = None
    table_continuation: bool = False
    figure_graph: FigureGraph | None = None
    image_ref: 'ExtractedImage | None' = None

class SkipReason(StrEnum):
    EMPTY_PDF = 'empty pdf'
    SLIDE_DECK = 'slide deck'
    STANDARDS_DRAFT = 'standards draft'
    UNREADABLE = 'unreadable'
```

```python
# Generated (paperflow cab5420): lib/pdf/table.py and lib/pdf/emit.py, public
class TableKind(Enum):
    CLEAN_MATRIX = 'clean_matrix'; INLINE_GRID = 'inline_grid'; PROSE_TABLE = 'prose_table'
    CODE_COMPARISON = 'code_comparison'; SPEC_TABLE = 'spec_table'; KEY_VALUE = 'key_value'
    BIBLIOGRAPHY = 'bibliography'; NB_BALLOT = 'nb_ballot'; FALSE_POSITIVE = 'false_positive'

class TableStrategy(Enum):
    PIPE_TABLE = 'pipe_table'; CODE_BLOCKS = 'code_blocks'; HTML_TABLE = 'html_table'; SKIP = 'skip'

# Detect table regions from MuPDF block structure.
def detect_tables(blocks: list[Block], *, page_mupdf_tables: dict[int, list[dict]] | None = None, two_column_pages: frozenset[int] = frozenset()) -> tuple[list[Section], list[Block]]: ...
# Remove blocks or lines whose vertical midpoint falls within a detected table region.
def exclude_table_regions(blocks: list[Block], table_sections: list[Section]) -> list[Block]: ...

# Generate the output Markdown from structured sections.
def emit_markdown(metadata: dict, sections: list[Section], *, annotate: bool = False, images_truncated: bool = False, source_image_count: int = 0, vector_uncertainty: VectorUncertaintyStats | None = None, glyph_stats: GlyphPassStats | None = None) -> str: ...
# Generate self-contained LLM reconcile prompts for uncertain regions.
def emit_prompts(sections: list[Section]) -> list[str] | None: ...
```

```python
# Generated (paperflow cab5420, --private): the sites the port touches
def _enforce_skip_contract(result: PipelineResult) -> PipelineResult: ...
def _insert_table_sections(sections: list, table_sections: list, page_rotations: dict[int, tuple], column_splits: dict[int, float]) -> None: ...
def _filter_sections_inside_vector_images(images: list[ExtractedImage], sections: list[Section], *, threshold: float = _SECTION_INSIDE_VECTOR_THRESHOLD, structural_threshold: float = _STRUCTURAL_INSIDE_VECTOR_THRESHOLD) -> tuple[list[Section], dict[int, list[tuple[str, str]]]]: ...
def _render_table_as_text(sec: Section) -> str: ...      # emit.py: FALSE_POSITIVE, no marker
def _flatten_cell(text: str) -> str: ...                  # emit.py
def cleanup_text(blocks: list[Block]) -> list[Block]: ... # cleanup.py: document-wide dehyphenation
def enrich_tables_with_docling(table_sections: list[Section], docling_tables: dict[int, list[dict]], remaining_blocks: list[Block] | None = None) -> int: ...
def discover_tables_with_docling(docling_tables: dict[int, list[dict]], remaining_blocks: list[Block], existing_table_sections: list[Section]) -> tuple[list[Section], list[Block]]: ...
_FITZ_LOCK = threading.Lock()                              # _fitz_lock.py
```

### New: what the port adds or changes

```diff
 @dataclass
 class PipelineResult:
     # Full output of the PDF conversion pipeline, used for QA scoring.
     md: str = ''
     prompts: list[str] | None = None
     sections: list[Section] = field(default_factory=list)
     ...
     vector_uncertainty: VectorUncertaintyStats | None = None
     glyph_stats: GlyphPassStats | None = None
+    # every content the pipeline decided to drop: (what, why, detail)
+    discards: list = field(default_factory=list)
+    # the paper summary (Figure 4); None for a skipped paper
+    summary: dict | None = None
 
 # Run the full PDF conversion pipeline, returning all intermediate data.
 def run_pipeline(path: Path, *, ml_tables: bool = False, visualize: bool = False, extract_vector: bool = False, whiteout_text: bool = False) -> PipelineResult: ...
```

*Figure 1. `lib/pdf/pipeline.py` (generated paperflow, `+` lines from ours, with `summary` proposed). The signature of `run_pipeline` does not change. New fields go last, with defaults, so `for_skip` and every caller keep working.*

```diff
 @dataclass(frozen=True)
 class ConvertedPaper:
     markdown: str
     prompts: list[str] | None
     intent: str
     ...
     source_raster_count: int = 0
     source_vector_count: int = 0
+    summary: dict | None = None
```

*Figure 2. `api.py` (generated paperflow, `+` proposed). `cli/orchestrator.py` adds one `backend.write_intermediate(pid, "summary", ...)` beside the prompts write (`cli/jobs.py:508`); tomd itself writes nothing.*

```diff
 @dataclass
 class Section:
     ...
-    metadata: dict[str, str | list[str]] = field(default_factory=dict)
+    metadata: dict[str, object] = field(default_factory=dict)
     ...
+@dataclass
+class TableCandidate:
+    # A table proposed by one independent extractor, before selection.
+    source: str
+    rows: list[list[list[Line]]]
+    bboxes: dict[int, tuple[float, float, float, float]] = field(default_factory=dict)
+    flags: list[str] = field(default_factory=list)
```

*Figure 3. `lib/pdf/types.py`. `TableCandidate` is generated (ours). The `metadata` type is proposed: both sides already store dicts and tuples there, so this fixes the annotation, not the runtime. Paperflow's table fields on `Section` stay; the port adds no field.*

```python
# Proposed: lib/pdf/runctx.py. One per run_pipeline call, passed explicitly.
# Replaces our module globals: evidence.current()/reset(), the pagecache caches,
# emit.set_hyphenating / HYPHEN_STATS, llmrepair.paper_record, llmcheck.state.
@dataclass
class RunContext:
    record: Record                                   # evidence.Record, generated (ours)
    generator: str = 'unknown'                       # the PDF producer
    page_words: dict[int, list] = field(default_factory=dict)
    page_drawings: dict[int, list] = field(default_factory=dict)
    candidates: dict[str, list[TableCandidate]] = field(default_factory=dict)  # by reader
    pre_detect_blocks: list[Block] = field(default_factory=list)              # for conservation
    def reader_error(self, stage: str, page, exc: BaseException, table=None) -> None: ...
```

```diff
+# Generated (ours) evidence.py
+@dataclass
+class Entry:
+    kind: str; scan: str; page: int; bbox: Box; rule: str; info: str
+    value: object = None
+    observed: bool = True
+@dataclass
+class Record:
+    entries: list[Entry] = field(default_factory=list)
+    readings: list[tuple] = field(default_factory=list)
+    doc_measure: object = None
+    errors: list[dict] = field(default_factory=list)
+    def exclude(self, scan: str, page: int, bbox: Box, rule: str, info: str, value=None) -> None: ...
+    def feature(self, scan: str, page: int, bbox: Box, name: str, info: str, value, observed=True) -> None: ...
+    def nominate(self, scan: str, page: int, bbox: Box, cue: str, info: str, value=None) -> None: ...
+    def on_page(self, page: int, kind: str | None = None) -> list[Entry]: ...
-def current() -> Record: ...
-def reset() -> Record: ...
```

*Figure 4. The per-run context (proposed) and the evidence record (generated, ours). In the port, `current()` and `reset()` do not exist: every reader, check and step takes the context.*

```diff
 # Detect table regions from MuPDF block structure.
 def detect_tables(blocks: list[Block], *, page_mupdf_tables: dict[int, list[dict]] | None = None, two_column_pages: frozenset[int] = frozenset()) -> tuple[list[Section], list[Block]]: ...
+def candidate_from_section(sec: Section) -> TableCandidate: ...
+def candidates_agree(a: TableCandidate, b: TableCandidate) -> bool: ...
+def conservation_error(cand: TableCandidate, blocks: list[Block]) -> str: ...
+def select_tables(tomd_sections: list[Section], ruled: list[TableCandidate], tagged: list[TableCandidate], blocks: list[Block], polls: list[TableCandidate] = (), rejected: list[TableCandidate] | None = None, codepairs: list[TableCandidate] = (), content: list[TableCandidate] = (), generator: str = 'unknown') -> list[Section]: ...
+def extract_tagged_tables(doc) -> list[TableCandidate]: ...
+def extract_ruled_tables(page, page_num: int, drawings=None) -> list[TableCandidate]: ...
+def extract_poll_tables(page, page_num: int, words_hint=None) -> list[TableCandidate]: ...
+def find_code_pairs(blocks: list[Block], rules_for=None) -> list[TableCandidate]: ...
+def content_candidates(pages, regions, specialists=None, rules_by_page=None) -> list[TableCandidate]: ...
+def records_candidates(pages, regions) -> list[TableCandidate]: ...
```

*Figure 5. The readers and selection (generated, ours; `detect_tables` is paperflow's, unchanged). In the port, `select_tables` lives in a new `lib/pdf/select.py`, not in paperflow's 6,951-line `table.py`, and takes the `RunContext` as a keyword (proposed). Paperflow's `_detect_drawing_grids` and Pass 5 stay inside its reader; our `extract_ruled_tables` reads paths too, so the two are never counted as two witnesses.*

```diff
+def assign(sec) -> dict: ...                          # levels.py: {"level","name","why","incomplete","cells"}
+def comment(info: dict) -> str: ...                   # levels.py: the tomd:level comment
+def gate_tables(doc, pages, sections: list[Section], paper: str = '') -> dict: ...   # classify.py: lowers only
+def image_share(page, bbox) -> float: ...             # classify.py: an image grid is never L0
+def run_scan(path, record, tables, builds: list | None = None) -> list: ...         # scan.py
+def dropped_nomination_regions(record, tables) -> list: ...
+def build(result, sections, evidence, generator: str) -> dict: ...                   # summary.py
 # Generate the output Markdown from structured sections.
-def emit_markdown(metadata: dict, sections: list[Section], *, annotate: bool = False, images_truncated: bool = False, source_image_count: int = 0, vector_uncertainty: VectorUncertaintyStats | None = None, glyph_stats: GlyphPassStats | None = None) -> str: ...
+def emit_markdown(metadata: dict, sections: list[Section], *, annotate: bool = False, images_truncated: bool = False, source_image_count: int = 0, vector_uncertainty: VectorUncertaintyStats | None = None, glyph_stats: GlyphPassStats | None = None, summary: dict | None = None) -> str: ...
 def emit_prompts(sections: list[Section]) -> list[str] | None: ...
```

*Figure 6. Trust, scan, summary (generated, ours) and the emit change (proposed). `emit_prompts` keeps its signature; flagged tables add elements. `scan.run_scan` reopens the PDF and so takes `_FITZ_LOCK`.*

```python
# drawn: Section.metadata keys a TABLE section gains (from our plan, Figure 6 there)
class TableMeta(TypedDict, total=False):
    table_agreement: str        # "exact" | "subset" | "none"
    uncertain_reasons: list[str]
    table_versions: list[dict]  # other readers' versions, for the prompts
    verified: str
    likely: bool
    level: dict                 # levels.assign()
    region_bbox: tuple[int, Box]
    page_bboxes: dict[int, Box]
    continues_from: dict        # only on a "may continue" note
    possible_table: bool        # L5 marks
```

*Figure 7. Metadata keys (drawn). Paperflow's `table_source` field already names the pass; ours names the reader in the same field, with pass names kept as `tomd/<pass>` so paperflow's `tomd tables` CLI still reads it.*

```python
# Proposed: the AI step, step 14. tomd exposes pure pieces; the agent lives with the
# pipeline framework (D1), never inside run_pipeline.
class RepairAnswer(BaseModel):          # D6: typed output_type
    rows: list[list[list[int]]]         # word indices only: no text can be added
def repair_request(sec: Section, words: list) -> dict: ...
def apply_repair(sec: Section, answer: RepairAnswer, words: list) -> str: ...  # build_columns + verify + code_guard
```

*Figure 8. The AI step's interface (proposed). `build_columns` and `code_guard` move unchanged (generated, ours).*

</implementation-contract>
<verification-contract>

## Testing Plan

Three promises are protected on paperflow's pipeline exactly as on ours: the same bytes every time, one table never changing another, and nothing lost silently.

- Release gate, run on paperflow's pipeline (`bench_paperflow.py`, then `bench_score.py`, then `gate_check.py BEFORE AFTER`), per step, against the previous step's tag:
  - Same answer keys, same scorer, denominators 1,746 (tuning) and 142 (fresh10), `PYTHONHASHSEED=0`.
  - FAIL if any table type or PDF producer loses a correct table, gains a silent miss or a wrong trusted table, any table loses more than one point, or reader errors are above 0.
  - A step that fails twice is reverted, not tuned further.
  - fresh10 is scored at the end of each reader step only. The reserved pool and the mailing released around 2026-10-23 stay untouched until the port is frozen, then are scored once.
- Tuning must generalize: dev and held-out are reported separately for every step that changes a threshold, with no paper-specific constants and a one-sentence mechanism per change.
- Paperflow's own suite keeps passing: `uv run --package tomd pytest` (`just tomd test`), including `test_pipeline_skip_contract.py`, `test_concurrent_convert.py`, the table tests and the golden tests.
  - `test_pdf_golden.py` is byte-exact. A step whose expected effect says "no Markdown change" must pass it untouched. A step that changes Markdown re-snapshots only the stems its expected effect names, and the commit lists every changed stem with the reason.
  - `test_golden_gate.py` holds 17 blessed baselines with a `table` axis. Baselines are never lowered (`rebless --force`) without Vinnie's decision.
- Determinism: a new test converts the 17 golden PDFs under two hash seeds and compares bytes (our `test_output_does_not_depend_on_the_hash_seed`). It runs in step 1 on paperflow as it is, so any existing seed dependence is found before the port adds code. Concurrency: `test_concurrent_convert.py` plus a new test that converts two papers on two threads and compares each to its serial output.
- API docs: every code commit regenerates the pysurface report of paperflow's tomd package (`work/paperflow/paperflow-tomd.api.md` until Vinnie names an in-repo place) in the same commit.
- Machine memory: one heavy job at a time. No two benches, no Docling or Table Transformer beside anything else, at most 4 workers. The ml_tables run is Docling and runs alone.

</verification-contract>
<decision-record>

## Decision Record

- Decisions:
  - **Gate for replacement steps (decided by the user, 2026-10-27).** A step that replaces paperflow's parsing with ours moves tables both ways, so the strict rule (no table loses more than 1 point) cannot hold for it. Such a step passes when: zero wrong-but-trusted tables; silent misses do not rise; a net gain in correct tables; and every table losing more than 1 point is listed in the commit with its cause and the later step expected to fix it (or "accepted" with a reason). Each sequencing guard is a named module constant, listed with the step that removes it. At the end of the port the cumulative result must pass the strict rule against our branch (`5809ae7`) on the tuning sets: no table more than 1 point worse than in our branch unless listed and explained, zero wrong-but-trusted, and 84.2% reproduced or the gap explained. fresh10 runs only then.
  - **Ours replaces paperflow's table parsing (Sean Parsons, 2026-10-27).** *Why:* paperflow's tomd owner wants one parser in place before he works in this code, and two parsers reconciled side by side would be harder to review and to maintain. *Cost:* paperflow's tuning on families our keys may underweight is lost unless kept; so passes that cover what ours does not (two-column pages, families our readers miss) stay as one reader under the agreement rule until ours covers them, and their internal agreement never counts as two witnesses.
  - **Safety before accuracy.** *Why:* paperflow trusts at least 1,167 table readings on the tuning sets that are not exactly right (847 + 320, page-level), and nothing in `paper.md` shows it. *Cost:* after step 2 almost nothing is trusted until independent readers land.
  - **Demote first, show later.** *Why:* paperflow's Markdown does not render a table's confidence, so step 2 changes no bytes of `paper.md` and can be gated alone. *Cost:* until step 3 the gain is visible only to programs reading `Section.confidence`.
  - **The enum stays; levels are metadata.** *Why:* `improvements.md` §1.5 makes `Confidence` the contract. *Cost:* two trust fields to keep consistent (`confidence` HIGH if and only if level L0).
  - **Paperflow's marker syntax for flagged tables.** *Why:* its prompts, QA and readers already parse `tomd:uncertain:L..`. *Cost:* every marker lowers paperflow's markdown-only QA score (capped penalty, `qa.py:399`), which will read as a regression unless the QA weight is decided.
  - **Machine information beside the Markdown.** *Why:* paperflow's own rule (library returns data, CLI persists). *Cost:* one more intermediate per paper.
  - **The AI step leaves conversion.** *Why:* model sovereignty, D1, D6, D9; tomd's dependencies exclude `anthropic`; no lazy imports. *Cost:* our measured +0.14 points (84.16% to 84.30%) is not available until the tier is rebuilt and re-measured on open-weight models.
- Tensions:
  - Paperflow's goldens expect page joins and HTML table rendering; our measurement found no signal that justifies a join, and our keys score pipe and paired-fence renderings. Each choice moves a different golden axis.
  - Paperflow's rule is quality-stability, not byte identity; ours is byte identity under any seed. The port adopts byte identity for tomd only.
  - Locality (one table answers for itself) against paperflow's document-wide dehyphenation and cross-page joins.
- Rejected alternatives:
  - Keeping paperflow's `detect_tables` as the main reader with ours arbitrating outside it (this plan's first version): rejected by the direction of 2026-10-27, because it leaves two parsers to maintain.
  - Porting as one large branch: paperflow's goldens, QA and tests would move all at once, with no way to tell which decision moved which number.
  - Shipping about 90 `TOMD_*` environment switches: paperflow tomd reads no environment variables except `EDITOR`.
  - **Docling as a reader under the agreement rule (decided by the user, 2026-10-26; was step 14).** Paperflow's ml_tables on, against the ml-off control in the same environment (PyMuPDF 2.0), same keys and scorer: tables exactly right fell from 543 to 422 on tuning (34 to 26 on fresh10); trusted tables that are wrong or not a table rose from 1,404 to 1,763 on tuning (310 to 372 on fresh10); the mean rose only from 47.6% to 50.8%. It is about 5.6x slower (0.279 against 0.050 s/page, one process, alone) and loads a model, which our machine can run only alone. Paperflow's existing ml_tables path stays as it is, off by default, untouched and not built on; its tables are outside the trust rule while it is off.
  - **An image-based second witness (Docling or Table Transformer reading the page image), rejected earlier on our branch.** Its precision was 92 to 96%, too low for trust; it is not independent, because its cell text comes from the same text layer our readers use; and it is about 10x slower.

</decision-record>
<execution-plan>

## Execution Instructions

Each step is one commit on branch `tomd-tables-port` (worktree `~/wg21-paperflow-port`, from `master` `cab5420`), pushed to the fork `rbbeeston/wg21-paperflow` after it passes its gate, and shaped so it can be opened as one reviewable PR against `cppalliance/wg21-paperflow` (no PR is opened until the user decides). Each has one gate run and regenerates the API report (pysurface 0.2.0) into `~/tomd-tables-poc/work/paperflow/api/`, outside the repo (Q13). Where a step's reader covers what a paperflow pass did, the same step removes that pass (replacement, not coexistence), and the gate shows the removal loses no correct table. Every step keeps its old behaviour reachable through one named module constant for the gate's A/B run; the constant is removed once the step is accepted (open question 8).

### Step 0. Measure paperflow as it is

- What: run the two-seed byte test on paperflow unchanged. (The ml_tables-on baseline is done: Table 1.)
- Where: no code; `bench_paperflow.py --ml`.
- Gate: none; this sets the gate's first tag (`pf_cab5420`).
- Expected: the ml row of Table 1; a list of any seed-dependent stems.
- Must not break: nothing is written into the paperflow checkout.

### Step 1. Per-run context, reader errors, determinism test

- What: `RunContext` (Figure 4) created in `run_pipeline` and passed to every new step; `reader_error` wraps `detect_tables` and every later reader (paperflow's opt-in ml_tables path is left untouched); the two-seed and two-thread tests.
- Where: new `lib/pdf/runctx.py`, `evidence.py`; `pipeline.py:run_pipeline`.
- Gate: release gate identical to step 0 (no table changes); `test_pdf_golden.py` byte-identical; new tests pass.
- Expected: no output change. A raising pass is recorded instead of failing the paper.
- Must not break: `_FITZ_LOCK` discipline, `test_concurrent_convert.py`, the skip contract.

### Step 2. Conservation and agreement before HIGH (demotion only)

- What: wrap each paperflow table as a `tomd` candidate (`candidate_from_section`), check `conservation_error` against the always-taken `pre_detect_blocks` snapshot, and keep `Confidence.HIGH` only with agreement from another kind of evidence. No reading is replaced and no cell changes. Tables from paperflow's opt-in ml_tables (Docling) path are left as they are: that path is not touched or built on (rejected alternative, Decision Record). Optionally, MuPDF `find_tables` readings already in `page_mupdf_tables` count as a paths witness for tables built by the text passes (Passes 1 to 4), never for Pass 5 or 2b tables built from them.
- Where: new `lib/pdf/select.py:select_tables` (one source for now), called after `pipeline.py:2212`; `pre_detect_blocks` at `:2210` made unconditional.
- Gate: release gate with exact 630 and accuracy 48.6% unchanged; wrong trusted falls to 0; `test_pdf_golden.py` byte-identical (confidence is not rendered).
- Expected: trusted falls from 1,729 table readings to near 0; the 1,167 trusted-not-exact readings stop being trusted; no table lost.
- Must not break: `paper.md` bytes, `TableKind` and rendering, the `annotate` preview (its border colour changes, which is intended).

### Step 3. Levels and marks in the Markdown

- What: `levels.assign` on every table; `tomd:level` comment plus paperflow's `tomd:uncertain:L..` marker on flagged tables; L5 marks for the three silent drops (FALSE_POSITIVE rendered as text, the dot-leader demotion, vector-cluster drops) and for dropped nominations; a table with agreement is exempt from dot-leader demotion; line numbers recomputed after `api._normalize_front_matter` and `api._strip_toc`.
- Where: new `lib/pdf/levels.py`; `emit.py:emit_markdown` (the UNCERTAIN loop at `:1252`, `_render_table_as_text`); `pipeline.py:2456`; `pipeline._filter_sections_inside_vector_images`; `api.py`.
- Gate: release gate; silent misses fall, nothing else moves; changed golden stems listed; front matter still first in every output.
- Expected: most of the 725 unmarked misses that paperflow detected and then dropped become marked; QA `uncertain_count` rises.
- Must not break: `\A---` front matter, the skip contract, paperflow's other markers, `golden_compare` parsing.

### Step 4. Paper summary and prompts elements

- What: `summary.build` returned on `PipelineResult.summary` and `ConvertedPaper.summary`; one `tomd:summary` comment after the front matter; flagged tables' alternative readings, the removed list and reader errors as extra JSON prompt elements in sorted order; the orchestrator persists the summary.
- Where: `lib/pdf/summary.py`, `paper_model.py`; `pipeline.py:run_pipeline`; `api.py:ConvertedPaper`; `emit.py:emit_prompts`; `cli/orchestrator.py`.
- Gate: release gate unchanged; summary JSON serializes without `default=str`; skipped papers carry `summary=None` and empty md.
- Expected: no table change. The paper confidence is our calibrated base rate, refitted on paperflow's output before it is published.
- Must not break: prompts absent when nothing is uncertain; `write_intermediate` usage; `ConvertedPaper.skipped_from`.

### Step 5. Tagged reader

- What: `extract_tagged_tables(doc)` inside the fitz session; its candidates enter `select_tables` (priority 0, `tree`).
- Where: new `lib/pdf/tagged.py`; `pipeline.py` fitz session next to the `get_drawings()` loop (`:2033`).
- Gate: release gate; fresh10 scored.
- Expected: first L0 tables return on tagged PDFs where tags and paperflow agree; exact rises where tags win.
- Must not break: the `blk_tagged` logic in `table.py:3248`, which is unrelated.

### Step 6. Ruled readers: grid, column rules, rule bands

- What: `extract_ruled_tables` (both-way grids, column-rule tables, booktabs and shaded rule bands) and `rowbands.merge_rule_bands` after selection.
- Where: new `lib/pdf/ruled.py`, `rowbands.py`; drawings taken once per page in the fitz session.
- Gate: release gate; fresh10 scored; LaTeX and ReportLab producers reported separately.
- Expected: L0 where paths and words agree; booktabs tables paperflow cannot read as grids (`pipeline.py:390` needs a vertical rule) are read.
- Must not break: `_detect_drawing_grids`, Pass 5, Pass 2b; the two path readers are never two witnesses.

### Step 7. Poll reader

- What: `extract_poll_tables` (page words, pipes, drawn polls) as a `meaning` reader; Pass 3 stays inside paperflow's reader.
- Where: new `lib/pdf/poll.py`.
- Gate: release gate; the poll table type must not lose a correct table.
- Expected: polls trusted where vote vocabulary and words agree.
- Must not break: `_is_lone_vote_header` suggested-poll rows.

### Step 8. Code-pair reader and code-comparison rendering

- What: `find_code_pairs` (same-code evidence) as a reader; then the rendering choice for CODE_COMPARISON, measured both ways.
- Where: new `lib/pdf/codepair.py`; `emit.py` and `_STRATEGY_MAP[CODE_COMPARISON]` only after open question 9 is answered.
- Gate: release gate on both renderings, with the golden diffs shown to Vinnie.
- Expected: code comparisons paperflow writes as separate fenced blocks become scorable tables; this is where much of the gap in misses may close.
- Must not break: `MIXED_TABLE_MARKER` on the HTML path; `code_grid` indentation.

### Step 9. Measures, extent, verification and the classifier

- Done (port step 9, attempt 3, decided 2026-10-28): the extent step was moved to step 10, next to flag.py's drop marks, because on its own it changed a code-pair reading that was then dropped without a mark (p3115r0-t2, a silent miss; attempt 2).
- What: `docmeasure.measure`, `validate.verify_layout`, `fit.fit`, `relations.check`, dimensions; `classify.gate_tables` (lowers only) and `image_share` (an image grid is never L0).
- Where: new modules after selection, before `_insert_table_sections`; `gate_tables` reopens the PDF under `_FITZ_LOCK`.
- Gate: release gate; expect L1 to rise and no correct table lost; double attachment with `_collect_header_cluster` checked by type.
- Expected: graded levels become informative; a few wrong agreements are caught.
- Must not break: raster and vector IMAGE sections in image-cell grids.

### Step 10. Region scan, content builder, records reader

- Done (port step 10, attempt 2, 2026-10-28): marks are set after body structuring, because paperflow merges code lines into a new CODE section afterwards and the mark was lost (four new silent misses in attempt 1).
- What: `extent.extend` (moved here from step 9; it clears the p4178r0 QA baseline pending approval); `scan.run_scan` and `checks/`; `content.content_candidates` and `records.records_candidates` on the areas the scan builds.
- Where: new `lib/pdf/scan.py`, `checks/`, `content.py`, `records.py`; after selection.
- Gate: release gate with held-out reported; reader errors 0.
- Expected: the largest gain on misses (on our branch the builder made about 45% of unread tables exact or one fix away).
- Must not break: figures (`FigureRegion` areas are excluded from building), two-column insertion.

### Step 11. Repairs and cell text

- Done (port step 11, attempt 4, 2026-10-28): figure-table labels moved to step 12 (they need paperflow's FigureRegions). Trust guards are applied after the gate (attempt 3 demoted before it, so escalation re-read agreed tables worse).

- What: escalation, stray-word placement, inferred cells; the number rule and `_decode_dingbats` in the cell renderer that replaces `_flatten_cell`; figure-table labels from paperflow's `FigureRegion`s.
- Where: `validate.escalate`, `repair.place_stray_words`, `emit.py:_flatten_cell`, `figures`.
- Gate: release gate; a repaired table is never above L4.
- Expected: cell-level accuracy gains; no change in trust.
- Must not break: `glyphs.drop_glyphs_in_code_and_tables` (tables need `Section.lines`).

### Step 12. Contents, continuations and hyphen locality

- Also: figure-table labels (moved from step 11), with paperflow's `FigureRegion`s.
- Done (port step 12, attempt 1, 2026-10-28): selected tables exempt from contents removal (removals listed); continuation notes (never a join); figure labels from the caption text near a table (tomd-tables' figures.py as figure_tables.py, not paperflow's FigureRegions); line-end hyphens inside reader regions left to the cell renderer. Paperflow's page joins are unchanged here: the L3 cap on joined tables (open question 3) moves to the end-of-port review.

- What: the policies that wait on decisions: continuation notes and the cap on joined tables (open question 3), TOC removers exempting selected tables, and the exemption of table-candidate lines from document-wide dehyphenation (open question 11).
- Where: `emit.py:1216` fold, `structure.drop_leaked_toc_entries`, `api._strip_toc`, `cleanup.cleanup_text`.
- Gate: release gate and the 17 golden baselines.
- Expected: depends on the answers; each policy is its own commit.
- Must not break: paperflow's two-column order and the blessed `table` axis without a decision.

### Step 13. Hidden text

- What: our visibility classes (render mode 3 and six more) removed before readers; the quoted text goes to the summary and prompts intermediates only (open question 4).
- Where: new `lib/pdf/visibility.py`, beside `cleanup.find_hidden_regions`.
- Gate: release gate; adversarial tests ported; no hidden text in `paper.md`.
- Expected: injected text no longer reaches readers or agents.
- Must not break: paperflow's Google Docs widget stripping.

### Step 14. The AI step under paperflow's model rules

- What: rebuild repair and second look on `pipeline.run_agent` with `RepairAnswer` as `output_type`, `output_retries`, `UsageLimits` at `run` (no vision slot: open question 7); tomd keeps only the pure pieces (Figure 8).
- Where: tomd `repair_request` / `apply_repair`; the agent in `pipeline` or `cli` (open question 7).
- Gate: release gate with the step off (byte-identical) and on (net gain, all repaired tables at L4, budget respected).
- Expected: on our branch, +0.14 points; to be re-measured on open-weight models.
- Must not break: offline `convert`, D1 to D11, no `anthropic` import in tomd.

</execution-plan>

## Open questions: provisional defaults

Each question below has a provisional default (decided 2026-10-26) that the port follows unless the user or Vinnie overrides it. Defaults marked "set by the user" were set through the coordinating session; the rest are the conservative choice. Two still truly need Vinnie or Sean Parsons before the step that uses them: questions 2 and 12; their approvals are collected in one list rather than stopping the port. Since 2026-10-27 the direction above settles conflicts in favour of our parsing, so questions 6, 7 and 9 now follow it: paperflow's public surface stays.

1. **(Vinnie)** After step 2, almost no paperflow table is HIGH until readers land. **Default (conservative):** ship step 2 as metadata only (levels and agreement in `Section.metadata`, `Section.confidence` unchanged) until step 5, so paperflow's output does not change before the readers that restore trust exist.
2. **(Vinnie; needs him before step 3)** Should flagged tables gain `tomd:uncertain` markers in `paper.md`, which lowers paperflow's QA score? **Default (conservative):** no new markers in `paper.md` in step 3; levels go to the summary and prompts only, with QA reported beside the gate, until Vinnie decides whether QA stops counting table markers.
3. **(User, Vinnie)** Page joins. **Decided (default, set by the user):** keep paperflow's page joins, capped at L3, with a note on each joined table.
4. **(User, Vinnie)** Hidden text. **Decided (default, set by the user):** hidden text goes only into the summary and prompts, never into `paper.md`.
5. **(Vinnie)** Line markers after `api.py` rewrites the Markdown. **Default:** recompute the `tomd:uncertain:L..` ranges after the rewrite; the marker syntax is kept.
6. **(Vinnie)** Skip contract. **Default:** keep "skipped means empty md"; our `not-converted` reason moves into `skip_reason` and the summary.
7. **(Vinnie)** AI step. **Default (conservative):** tomd does not depend on `pipeline`; the agent lives in `cli` and calls tomd's pure pieces. No vision slot is in scope for the port.
8. **(Vinnie)** Switches. **Default:** measured defaults baked in, no environment variables; one module constant per step only during the port, removed once the step is accepted.
9. **(Vinnie)** Rendering of CODE_COMPARISON, SPEC_TABLE and NB_BALLOT. **Default (conservative):** keep paperflow's rendering (HTML and separate fences) unchanged; the bench harness scores the HTML tables. A change of rendering is a separate later proposal.
10. **(User, Vinnie)** Docling. **Decided (set by the user):** Docling is not part of the port. Paperflow's existing ml_tables path stays as it is, off by default, untouched and not built on (Decision Record, rejected alternatives). Vinnie may still decide what to do with that path in paperflow itself.
11. **(User)** Hyphens. **Decided (default, set by the user):** table lines are exempt from document-wide dehyphenation (the cost is a second block copy).
12. **(Vinnie; needs him before the first golden change)** Golden baselines. **Default:** one approval per step, by Vinnie, and only the stems named in a step's expected effect may change; no step lowers the `table` axis without his explicit approval.
13. **(Vinnie)** Where the generated API report lives. **Decided (by the user, 2026-10-30, reversing the 2026-10-28 default):** in the branch at `packages/tomd/doc/api/`, regenerated in every code commit, so the reviewer reads the declarations with the code. The port's plan documents go in `docs/plans/tomd-tables-port/`, following paperflow's `docs/plans/` convention.
14. **(User)** Claims. **Decided (default, set by the user):** do not cite 84.2% for paperflow until the port reproduces it on paperflow's pipeline.

## Carried shortfalls

Gate shortfalls a step landed with, each with a known cause and the later step expected to clear it. The fixing step must show each one cleared; the end-of-port strict check must clear all of them.

| Step | Metric | Tables | Cause | Expected fix |
|---|---|---|---|---|
| 9 | table lost > 1 point | p3004r0-t3 (100 -> 0, now a flagged miss) | escalation re-reads the failing ruled reading and keeps paperflow's column-major re-read; tomd-tables reads it correctly after repairs | step 11 (escalation moves with repairs and cell text) |
| 9 | table lost > 1 point | p2749r0-t11 (99.5 -> 82.9) | escalation's re-read splits the wrapped header ("Encoding / prefix") into two rows; no row join yet | step 11 (repairs) |
| 10 | table lost > 1 point, worse than tomd-tables | p2688r1-t26 (100 -> flagged miss), p2843r3-t13 (2.4 -> flagged miss), p2304r3-t1 (36 -> flagged miss), p3135r0-t5 (99.8 -> 11), p1928r14-t52 (99 -> 83), p3018r0-t3 (59 -> 31; branch 33) | the content and records readers now outrank or replace the reading; tomd-tables reads these after repairs, cell text and contents handling | steps 11-12 |
| 10 | new silent miss | p2685r1-t2 | dropped reading with no covering mark; silent in tomd-tables too | end-of-port check (not a regression against 5809ae7) |
| 11 | table lost > 1 point, worse than tomd-tables | p3361r1-t1 (34 -> 32; tomd-tables 76) | tomd-tables' content reader wins this region there; here another reading is kept | step 12 or the end-of-port check |
| 11 | sequencing guard | every table trusted only by agreement with paperflow's reader (TRUST_EXCLUDES_PAPERFLOW_READER) | paperflow's reader reads the same text layer: ten wrong tables trusted on it in attempt 1, none in tomd-tables | after the merge, once that agreement is measured on a fresh sample |
| 11 | sequencing guard | every table paperflow renders as HTML, code blocks or text (TRUST_ONLY_PIPE_RENDERING) | the agreement checks cells, not that rendering: two code comparisons trusted with a row lost (attempt 2) | open question 9 (Vinnie: rendering of these kinds) |

Status after step 12 (2026-10-28), against tomd-tables (run g97):
- cleared: p2749r0-t11 (within 1 point of tomd-tables).
- moved to step 15, all against tomd-tables: p3004r0-t3, p2688r1-t26 and p2843r3-t13 (flagged misses here, read correctly there); p1928r14-t52 (-16.7); p3135r0-t5 (-88.8); p3361r1-t1 (-44.1); p2304r3-t1 (-2.3); p3018r0-t3 (-1.8). Most are a different reading winning selection, which steps 13-14 do not touch.

### Step 15. Carried shortfalls (added 2026-10-28)

- What: the selection and escalation differences behind the carried shortfalls (above), diagnosed one table at a time against tomd-tables; then the end-of-port strict check.
- Gate: rule (b); every carried entry cleared or explained before the strict check.

### Carried against 5809ae7 (fgM): end of port, 2026-10-28 (run pfEnd, commit 9854c1b)

Every earlier "accepted: same as tomd-tables" verdict was judged against run g97 (a reverted experiment), not 5809ae7, and is void. Listed: every table more than 1 point below fgM on the 1,531 tuning tables outside the 37 papers paperflow skips (30), the fresh10 ones outside p2463r0 (6), and the tables silent in the port but marked in 5809ae7 (no point change; 15). Tables that need new reader work are listed, not fixed.

| Table | Set | 5809ae7 | Port | Difference | Cause |
|---|---|---|---|---|---|
| n5057-t1 | dev | correct-uncertain 100.0 | missing-silent 0.0 | -100.0 | no reader reads this table (the grid on the page is a different table); needs reader work |
| p3004r0-t3 | fresh5 | correct-uncertain 100.0 | missing-flagged 0.0 | -100.0 | the gate's escalation keeps paperflow's column-major re-read of a failing ruled reading |
| p2548r6-t2 | fresh8 | correct-high 100.0 | missing-flagged 0.0 | -100.0 | code comparison written by paperflow's own renderer (strategy code_blocks), which the scorer cannot match; open question 9 |
| p4221r1-t2 | fresh2 | wrong-uncertain 99.9 | missing-flagged 0.0 | -99.9 | as p2548r6-t2: paperflow's code-comparison rendering; open question 9 |
| p3100r2-t10 | fresh2 | wrong-uncertain 99.7 | missing-flagged 0.0 | -99.7 | not diagnosed: a near full-page table no kept reading covers |
| p2811r5-t3 | fresh7 | correct-uncertain 100.0 | wrong-uncertain 30.8 | -69.2 | paperflow's reading takes the caption row as the header; 5809ae7 kept the content reading |
| p3005r0-t11 | fresh6 | wrong-uncertain 48.4 | wrong-uncertain 5.1 | -43.3 | paperflow's reading packs rows across a page break; the unpack rule (15a/15d) is single-page only |
| p0957r8-t3 | dev | correct-uncertain 100.0 | wrong-uncertain 57.8 | -42.2 | the agreement rule emits paperflow's reading where it agrees with the grid reading; its cell text differs (port rule, step 5) |
| p2814r0-t11 | fresh7 | wrong-uncertain 37.6 | missing-silent 0.0 | -37.6 | bullet pairs aligned across two columns; no reading is kept and the area gets no mark; needs reader work |
| p3100r2-t9 | fresh2 | correct-uncertain 100.0 | wrong-uncertain 63.5 | -36.5 | the agreement rule emits paperflow's reading where it agrees with the grid reading; its cell text differs (port rule, step 5) |
| p4088r1-t5 | fresh3 | correct-uncertain 100.0 | wrong-uncertain 65.0 | -35.0 | same reader, a different reading: cell rendering or escalation differences of a few cells |
| p3005r0-t4 | fresh6 | wrong-uncertain 66.9 | wrong-uncertain 44.5 | -22.4 | paperflow's reading outranks the content reading (text-position priority); in 5809ae7 tomd-tables' own text-position reading failed the checks here |
| p3086r4-t6 | fresh | correct-uncertain 100.0 | wrong-uncertain 82.6 | -17.4 | paperflow's reading outranks the content reading (text-position priority); in 5809ae7 tomd-tables' own text-position reading failed the checks here |
| p1701r2-t2 | fresh9 | wrong-uncertain 77.1 | wrong-uncertain 60.2 | -16.8 | the agreement rule emits paperflow's reading where it agrees with the grid reading; its cell text differs (port rule, step 5) |
| p1928r14-t52 | fresh5 | correct-uncertain 100.0 | wrong-uncertain 83.3 | -16.7 | paperflow's reading outranks the content reading (text-position priority); in 5809ae7 tomd-tables' own text-position reading failed the checks here |
| p2971r3-t2 | fresh | correct-uncertain 100.0 | wrong-uncertain 83.7 | -16.3 | paperflow's reading outranks the content reading (text-position priority); in 5809ae7 tomd-tables' own text-position reading failed the checks here |
| p2749r0-t5 | fresh8 | correct-uncertain 100.0 | wrong-uncertain 83.7 | -16.3 | paperflow's reading outranks the content reading (text-position priority); in 5809ae7 tomd-tables' own text-position reading failed the checks here |
| p3144r0-t7 | fresh5 | wrong-uncertain 26.4 | wrong-uncertain 11.6 | -14.7 | paperflow's reading outranks the content reading (text-position priority); in 5809ae7 tomd-tables' own text-position reading failed the checks here |
| p3144r0-t6 | fresh5 | wrong-uncertain 24.8 | wrong-uncertain 11.8 | -13.0 | paperflow's reading outranks the content reading (text-position priority); in 5809ae7 tomd-tables' own text-position reading failed the checks here |
| p2993r0-t5 | fresh9 | wrong-uncertain 44.9 | wrong-uncertain 33.5 | -11.4 | paperflow's reading outranks the content reading (text-position priority); in 5809ae7 tomd-tables' own text-position reading failed the checks here |
| p3261r0-t2 | fresh6 | correct-uncertain 100.0 | wrong-uncertain 89.1 | -10.9 | check-mark convention: the port decodes ZapfDingbats to ✓/✗ (paperflow's renderer), the keys keep the raw codes; explained, not a loss |
| p3261r0-t5 | fresh6 | correct-uncertain 100.0 | wrong-uncertain 89.6 | -10.4 | check-mark convention: the port decodes ZapfDingbats to ✓/✗ (paperflow's renderer), the keys keep the raw codes; explained, not a loss |
| p3261r0-t3 | fresh6 | correct-uncertain 100.0 | wrong-uncertain 91.3 | -8.7 | check-mark convention: the port decodes ZapfDingbats to ✓/✗ (paperflow's renderer), the keys keep the raw codes; explained, not a loss |
| p3261r0-t4 | fresh6 | correct-uncertain 100.0 | wrong-uncertain 92.2 | -7.8 | check-mark convention: the port decodes ZapfDingbats to ✓/✗ (paperflow's renderer), the keys keep the raw codes; explained, not a loss |
| p3692r4-t2 | fresh | correct-uncertain 100.0 | wrong-uncertain 94.6 | -5.4 | the agreement rule emits paperflow's reading where it agrees with the grid reading; its cell text differs (port rule, step 5) |
| p3004r0-t14 | fresh5 | correct-uncertain 100.0 | wrong-uncertain 95.3 | -4.7 | paperflow's reading outranks the content reading (text-position priority); in 5809ae7 tomd-tables' own text-position reading failed the checks here |
| p2304r3-t1 | fresh8 | wrong-uncertain 78.5 | wrong-uncertain 76.2 | -2.3 | same reader, a different reading: cell rendering or escalation differences of a few cells |
| n4997-t1 | fresh9 | wrong-uncertain 47.2 | wrong-uncertain 45.0 | -2.2 | same reader, a different reading: cell rendering or escalation differences of a few cells |
| p2396r1-t4 | fresh8 | wrong-uncertain 98.0 | wrong-uncertain 96.2 | -1.9 | the agreement rule emits paperflow's reading where it agrees with the grid reading; its cell text differs (port rule, step 5) |
| p3018r0-t3 | fresh8 | wrong-uncertain 33.0 | wrong-uncertain 31.2 | -1.8 | same reader, a different reading: cell rendering or escalation differences of a few cells |
| p2407r1-t2 | fresh10 | correct-uncertain 100 | missing-flagged 0 | -100.0 | not diagnosed (fresh10 is not tuned on) |
| p1619r2-t2 | fresh10 | wrong-uncertain 90.8 | wrong-uncertain 32.4 | -58.5 | paperflow's reading outranks the rule reading |
| p2221r0-t2 | fresh10 | correct-uncertain 100 | wrong-uncertain 51.2 | -48.8 | paperflow's reading outranks the content reading (text-position priority); in 5809ae7 tomd-tables' own text-position reading failed the checks here |
| p2345r0-t4 | fresh10 | wrong-uncertain 96.9 | wrong-uncertain 63.1 | -33.7 | the agreement rule emits paperflow's reading where it agrees with the grid reading; its cell text differs (port rule, step 5) |
| p0429r9-t2 | fresh10 | wrong-uncertain 93.5 | wrong-uncertain 87.9 | -5.6 | same reader, a different reading: cell rendering or escalation differences of a few cells |
| p1222r4-t2 | fresh10 | wrong-uncertain 93.8 | wrong-uncertain 88.4 | -5.4 | same reader, a different reading: cell rendering or escalation differences of a few cells |

Silent in the port, marked (missing-flagged) in 5809ae7; cause: 5809ae7's possible-table marks came partly from tomd-tables' own text-position reader, whose dropped readings the port no longer has (paperflow's reader replaced it): p2988r12-t5, p3977r0-t2, p4016r0-t5, p3130r4-t13, p3130r4-t16, p3131r3-t5, p3131r3-t6, p1709r5-t44, p2786r7-t4, p3004r0-t7, p3004r0-t20, p2735r0-t46, p2993r0-t9; fresh10: p1985r3-t3, p2461r1-t9. In the other direction, 16 tuning tables silent in 5809ae7 are read or marked by the port.

## Post-merge bug list

Note (2026-10-28): the entries below were judged "same in tomd-tables" against run g97, not 5809ae7; each is re-judged in "Carried against 5809ae7 (fgM)" above.

Losses accepted during the port that are wrong content (not only a different layout), for after the merge. None blocks the port.

- p1068r11 (port steps 6-7, golden QA baseline table 1.00 -> 0.00): the PDF letter-spaces the vote labels ("S F", "S A") and draws a row of "-" under the header; the poll reader does not recognise letter-spaced labels, so the grid reader reads the polls as printed. Same in tomd-tables.
- p3144r0-t6, -t7 (port step 9, 99 -> 12): escalation re-reads the code comparison line per row and both columns hold the same text. Wrong-uncertain in tomd-tables as well (there 2x2 with joined cells); flagged, never trusted.
- p2751r1-t2 (port step 9, 100 -> 87.5): the poll's "SA" header loses its raised footnote mark "3" after the gate's re-read. Wrong-uncertain in tomd-tables as well.
- p2486r1-t2, -t6, -t7 (port step 7): the poll reader reads the header label "Strongly Against" as "Against" (multi-word vote labels grouped wrongly). Same behaviour in tomd-tables.

- Paperflow pin tables that read worse after the port (found 2026-10-28 while applying the approvals; all flagged, none trusted; each stays an expected failure in `tests/port_pending_approval.txt` marked HELD):
  - p0533r9 page 4: the 13-row table merges the "Pass" and "Comment" headers into one column (13x3 read as 13x2); golden table 1.00 -> 0.75 is this.
  - p3978r0 and p3978r3 page 2: the 8x4 code table is read as one 1x2 row of lumped code; golden p3978r0 table 0.75 -> 0.67 is this. p3978r0 page 1: the heading "2 STRAW POLLS" is read as a 4x2 table. p3978r3 page 3: prose and code are read as a 3x2 table.
  - p4016r0 page 44: the "Godbolt links" note becomes a tenth row; page 54: ASCII art and prose become rows (5 -> 8); page 51 loses its table kind.
  - p4096r0 page 9: "Predicted outcome" is split into two columns (5x4 read as 5x5).
  - p4178r0: shapes unchanged, but seven 2x2 tables lose their table kind and their readers disagree on content; not yet checked cell by cell.

## Approvals (2026-10-28, by the user)

The user approved the port's pending list. Applying it showed that the step-6 reason ("drawn-rule readers read these tables") was true for p4047r0 only; the other pin changes are regressions (listed above). Applied:

- The `<br>` convention for wrapped table cells: five `TestFlattenPipeCell` tests now expect `<br>`. The fifth test used single letters, which the stacked-letter rule joins into one word ("a", "b", "c" -> "abc"); it now uses words.
- p3290r4: the page-15 4x2 table's kind reads key_value (shape unchanged).
- p4047r0: the Conclusion table reads five rows; the fifth ("Implementation maturity concerns") is in the PDF and the old 4-row shape dropped it.
- n5040 golden baseline, via `tomd rebless n5040 --force`: table 1.00 -> 0.89, text 0.98 -> 0.97 (labels beside a poll are not cells).
- Open-question defaults approved: Q2 (no new markers in `paper.md`), Q6 (keep the skip contract), Q7 (the AI step lives in `cli`), Q9 (keep paperflow's rendering of the three special table families), Q12 (one golden approval at a time, named stems only), Q13 (the API report stays outside paperflow's repo).

Held, still expected failures: the six other pin tests, and the golden baselines of p0533r9, p3978r0 and p1068r11. The user approved p1068r11 with its fix tracked; it is kept as an expected failure instead of lowering its baseline to 0.00, so the gate still guards it once the fix lands.

## Held fixes (2026-10-29)

Nine held regressions were taken one at a time on `tomd-tables-port`, each a general mechanism, each gated on dev, heldout and fresh..fresh9 (never fresh10). Every gate: HIGH 213, silent 252, wrong-but-trusted 0, no table lost more than a point; content-weighted accuracy 59.59% -> 60.47%, correct 1134 -> 1147 over the chain.

| Case | Commit | Mechanism | Gate (correct) | Restored |
|---|---|---|---|---|
| 2 | a688f71 | ref-qualified function types are whole cells; codepair leaves code-beside-text rows to the table readers | 1134 -> 1136 | p3978r0/r3 page 2 |
| 3 | 9cb5944 | two-column reading of numbered headings flagged numbered-list | 1136 -> 1136 | p3978r0 pin and golden |
| 5 | beada6b | filled background boxes are not grid lines; pipe tables keep their kind | 1136 -> 1141 | p4016r0 pin |
| 6 | df68bbd | column starts crossed in every row are not boundaries; blank code lines kept as `&#10;` | 1141 -> 1145 | p3978r3, p4096r0 pins |
| 7 | aa5e6c2 | wrapped prose is not packed rows; full-width words stay in their cell | 1145 -> 1147 | p4178r0 pin |
| 8 | 0f3f67e | a printed dash separator row is dropped when body rows follow | 1147 -> 1147 | p1068r11 golden (table 0.0 -> 1.0) |
| 4 | held | indent rule for code laid one line per row (patch kept) | failed accuracy gate | none needed: p3978r3 passes after case 6 |

Still held: the p0533r9 golden (text 0.65 < 0.66; a mark cuts its section at the page break).

Post-merge bugs found on the way:

- Case 4's indent fix gives p2351r0-t2's exact key reading, but split-code rejects code laid one line per row, and on p2688r1 p27 removing the bad rules reading lets a codepair truncated at a blank-line gap beat the correct content reading.
- Codepair truncates a pair at a blank-line gap.
- Resolved (convention): `content.py` read `TOMD_ROW_VOTES` from the environment through `__import__('os')`. `_ROW_VOTES` is now the plain constant 99 and `TOMD_ROW_VOTES` no longer exists.
- Resolved (convention, Q13): `packages/tomd/doc/api/` is removed from the branch. The API report is generated into `~/tomd-tables-poc/work/paperflow/api/`, outside paperflow's repo. Reversed 2026-10-30 by the user: the report is back in the branch at `packages/tomd/doc/api/`, regenerated per code commit, and the plan documents are in `docs/plans/tomd-tables-port/`.
- The fifth flatten test (`test_a_cell_never_emits_a_literal_newline`) changed for the stacked-letter rule, not for `<br>`; its pending line was mislabelled.
- The bisect found drops the expected-failure status hid: de575c2 took p1068r11 table 1.0 -> 0.0 (fixed by case 8) and p0533r9 table 1.0 -> 0.75; 4898862 cut p3978r0 code 0.35 -> 0.32; cc7f180 cut p0533r9 text 0.62 -> 0.46 (df64b7a restored it to 0.65).

## Risks

- **Double-counted witnesses.** Paperflow's drawing grids and our ruled reader both read paths; paperflow's text passes and our words readers share text. A miscounted kind of information puts a wrong table at L0. Mitigation: witness kinds are declared per reader and tested.
- **Two coordinate frames.** Paperflow's `_rot_bbox` and our upright copies in one record. Mitigation: conversion to page coordinates at the record boundary, with a rotated-page test.
- **Golden churn hides a regression.** Re-snapshotting many stems at once makes a real loss look like an intended change. Mitigation: only stems named in a step's expected effect may change.
- **QA reads safety as loss.** Markers lower paperflow's markdown-only QA score. Mitigation: report QA beside the gate and settle open question 2 before step 3.
- **Upstream drift.** Paperflow's master moves during the port. Mitigation: rebase per step, and re-run step 0 if `table.py` changes.
- **PyMuPDF drift.** Paperflow under PyMuPDF 2.0 lost 1.0 point and 87 exact tables against its 1.27 pin; our 84.2% and the paperflow baseline both ran on the harness venv's 1.27.2.3, the same as paperflow's pin. Mitigation: hold the pin and record the version in every gate run.
- **Concurrency leaks.** Any module global left over mixes papers under threads. Mitigation: step 1 first, the two-thread test, and a grep for module-level mutable state in every review.
- **Overfitting to the tuning sets.** Our numbers were tuned on our pipeline. Mitigation: dev and held-out reported per step, fresh10 only at reader steps, untouched sets scored once at the end.
- **Answer keys from AI agents.** They may share a model's blind spots; a human spot-check of a sample is still to do.
- **Memory.** An 18 GB machine crashed under concurrent heavy jobs on 2026-10-26. Mitigation: one heavy job at a time, at most 4 workers, Docling always alone.

---

*2026-10-26, Claude Opus 5.5. Paperflow declarations generated by pyheader from `cab5420`; ours quoted from the pysurface report at `5809ae7`.*
