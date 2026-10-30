# tomd table trust: a plan in Python declarations

tomd turns WG21 papers into Markdown that a person or an AI can read. This plan covers the rebuilt table path for PDFs on the branch `tables-reportlab`. The prose path and the HTML path do not change.

The data shapes come first, written as Python declarations, and the prose stays short. Most declarations here are **generated** from the code, not drawn by hand. A small tool, `pyheader`, reads the Python source at a git commit without running it. It prints every class, field and function signature with the first paragraph of its docstring, and no bodies, in a fixed order. A diff between two commits therefore shows changes to declarations only. In a diff block, `-` is `master`, `+` is the branch, and an unmarked line is unchanged context. The full diff is in `doc/declarations-master-to-branch.md`.

The whole API, generated: [doc/api/tomd.api.md](api/tomd.api.md).

A few blocks are **drawn**, and say so. They describe data the code keeps in a plain `dict`, so there is no declaration for a tool to print. They list the keys the code actually reads and writes.

<product-contract>

## Product Requirements

The rule: trust a table only when independent kinds of evidence agree, and say how every other table may be wrong. Against answer keys built blind by AI agents from page images and the text layer, under written conventions decided by a person (a blind re-key of 30 papers by other agents agrees on 147 of 154 tables, 95.5%, and 5,974 of 5,990 cells), mean per-table accuracy on the tuning sets rose from 12.3% to 84.2%. The targets, 90 to 95% on the tuning sets and 80% on unseen papers, are not met.

- Problem and users:
  - Readers are people and AI models reading converted papers. Downstream programs parse the output.
  - On `master`, tomd emits every table at the same confidence as confident prose, so a wrong table looks trusted. It trusted 991 tables that were wrong or were not tables, and missed 1,570 tables with no warning.
- Goals:
  - Trust a table only on agreement between independent kinds of evidence.
  - Lose nothing silently. Every dropped candidate leaves a trace.
  - Say how a flagged table may be wrong, with a graded level.
  - Give the same bytes for the same PDF, and never let one table's evidence change another table.
- Non-goals:
  - Changing the prose path (two independent extractions of each page, compared word by word) or the HTML path.
  - Joining a table split across pages. No measured signal separates a continued table from a separate one.
  - Letting a language model write table text.
- Success criteria:
  - Tuning-set accuracy of 90 to 95%, and 80% on unseen papers. Neither is met yet.
  - No trusted table is wrong: 447 of 447 on the tuning sets and 27 of 27 on fresh10.
- Constraints:
  - Ordinary use never calls a network.
  - Every behaviour change ships behind a switch and passes the release gate.
  - The comment syntax in the Markdown is a public format. New fields go at the end, and nothing is renamed.
- Open questions:
  - **Which repository is the merge target?** This branch is built on `cppalliance/tomd` at `556cb4a` (19 April). tomd has since moved into `cppalliance/wg21-paperflow/packages/tomd`, which has diverged a long way: its `table.py` is about 288 KB against 9 KB on this base. It also has features this branch never saw: Docling tables behind `ml_tables`, `_enforce_skip_contract`, and six more comment markers (such as `tomd:glyph-placeholders` and `tomd:lossy-table`). Merging into paperflow means a port, not a merge.
  - Should `paper.summary.json` be a separate file, part of the prompts file, or behind a flag?
  - Nobody has tried feeding the prompts file back to a model to correct the Markdown automatically. Is that the next experiment?
  - The answer keys were made by models (AI agents), and so were the blind re-key and the second category labeller. Keys made by models may share a model's blind spots; a human spot-check of a sample is still to do.
  - Tables tomd sees but cannot build are the largest remaining loss. Should the optional AI step be allowed to build them from the page's words, under the same rules as repairs?

## Functional Specification

One conversion writes up to three files. The Markdown stays plain. Every doubt goes into HTML comments in the Markdown, into the prompts file, and into the summary JSON. A Markdown viewer shows clean tables, and a program reads the comments.

- Actors and workflows:
  - A person or an AI reads `paper.md`. A program parses the comments and `paper.summary.json`.
  - An operator runs `tomd paper.pdf`. With `--corpus`, the optional AI step is on and the run ends with one status line giving the tokens spent and the budget.
- States and validation:
  - Every table gets one of six trust levels (Table 2). The most severe level that applies wins, and the level never changes the cell text.
  - For L2 and above, the level comment also lists the cells where other readings of the same shape disagree, as `cells=r1c2,...`.
- Errors and recovery:
  - A reader that raises an exception is recorded, and lowers only the tables its stage touched.
  - A PDF whose text layer is not real text gets a `tomd:not-converted` comment, a warning and confidence 0, never an empty file.
  - With no credentials, a network error or a spent budget, the run continues without the AI step, and the summary says why.
- Security and privacy:
  - Text the page does not show (invisible, white on white, covered, clipped, tiny) is removed before any reader sees it. It is then quoted at the end of the Markdown, labelled as not the paper's visible text and not an instruction, because it could be an instruction aimed at the AI reading the Markdown.
  - tomd never reads, logs or prints an API key.

| File | Written when | Holds |
|---|---|---|
| `paper.md` | Always | The Markdown. Levels, marks and notes are HTML comments |
| `paper.prompts.md` | Only when something is flagged, removed or failed. A stale one is deleted | Every other reading of a flagged table, the removed-content list, reader errors, hidden text, the paper summary |
| `paper.summary.json` | Always (new) | Table counts by level, everything removed and why, the paper's confidence, hidden text, what the AI step did |

*Table 1. The three output files.*

| Level | Name in the code | Plain meaning | Written to the Markdown as |
|---|---|---|---|
| L0 | `trusted` | Two different kinds of evidence agree, and every character in the area is in the cells | A plain table, no marker |
| L1 | `likely` | Flagged, but the words sit evenly inside the drawn cells | `tomd:likely` plus an uncertainty marker |
| L2 | `minor` | One source only, and every content check passed | `tomd:level L2` plus an uncertainty marker |
| L3 | `structure-uncertain` | Readers disagree, a layout check failed, the table's edge is uncertain, or it was joined from two readers | `tomd:level L3` plus an uncertainty marker |
| L4 | `content-at-risk` | Text may be duplicated, misplaced, damaged or out of order, or the table was repaired (by the AI step too). "Incomplete" when text is only missing | `tomd:level L4` plus an uncertainty marker |
| L5 | `mark-only` | A possible table that was not produced | An uncertainty marker over the text |

*Table 2. The trust levels, as `levels.NAMES` names them.*

</product-contract>
<implementation-contract>

## Technical Design

The table path becomes several independent readers that write to one shared record. A region scan decides which areas nobody claimed are tables. Selection, verification and repair turn the readings into one graded table per region. An optional AI step can repair a table's rows and columns, but never its text.

- On `master`, one function, `detect_tables`, finds tables from text-block positions and emits each one at full confidence. On the branch it is one reader among several.
- A table is still a `Section` with `kind=TABLE`. Everything new about it is recorded in `Section.metadata` (Figure 6).
- The order of the pipeline is costly to reverse. Structure classification assumes table regions have already been removed from both text paths. The line numbers in uncertainty markers assume the summary comment and the hidden-text appendix are inserted after emission and shifted for.

### Vocabulary

| Term | Plain meaning | In the code |
|---|---|---|
| Reader | One independent way to find a table. It proposes candidate tables and records what it rejected | `extract_*`, `detect_tables`, `find_code_pairs`, `build_text`, `read_region` |
| Candidate | One reader's proposed table, before tomd picks one per region | `TableCandidate` |
| Evidence record | One list per conversion of everything every reader nominated, rejected or measured. Later steps read it, never a reader's private verdict | `evidence.Record`, `evidence.Entry` |
| Kind of information | What a piece of evidence comes from: `words` (text positions), `paths` (drawn lines, boxes, shading), `tree` (the PDF's tags), `meaning` (poll vocabulary, shared code), `document` (facts about the whole paper) | `Entry.info` |
| Witness | A kind of information that supports a table. Counted per kind, never per reader. Document facts never count | Two readers that both used `words` count once |
| Region scan | The step that decides what to do with every area a reader or check nominated | `scan.run_scan`, `scan.band` |
| Check | A small test that turns an area into evidence | `checks.Check` |
| Possible-table mark | An area that may be a table but was not produced. Level L5 | an uncertainty marker with `possible_table` set |
| Uncertainty marker | An HTML comment naming the lines of text that follow and are uncertain | `<!-- tomd:uncertain:L120-L131 -->` |
| Conservation | Every letter and digit in a table's area appears in its cells as often as on the page | the `table_note` counts |
| Fit | The words sit evenly inside the drawn cells. Earns L1 | `metadata["likely"]` |
| Prose measure | What ordinary text looks like in this paper: margins, word spacing, hyphenation | `docmeasure` |
| Repair | A change to a flagged table after the readers ran: switching to another reading, placing stray words, or the AI step. A repaired table is never better than L4 | `repair`, `llmrepair.repair` |
| AI step | Optional use of a language model to fix a doubtful table's rows and columns. Off unless `--corpus` | `llmrepair`, `llmcheck` |
| Word indices | The AI step sees the table's words numbered 0, 1, 2 and so on, and answers with those numbers, so it cannot add or change text | `RepairAnswer` |
| Token budget | A cap on how much text the AI step may send and receive, per run and per paper. Tokens are the unit models are billed in | `TOMD_LLM_BUDGET`, `TOMD_LLM_PAPER_BUDGET` |
| Release gate | The check every change must pass on the tuning sets before it lands | outside this repo |
| Silent miss | A table tomd neither produced nor marked | — |

*Table 3. Terms used in this plan.*

| Word | It can mean | This plan uses |
|---|---|---|
| level | A trust level (L0 to L5), or what a check judges (`checks.LEVELS`: document, region, rows, columns, cells, content) | "trust level"; "what a check judges" |
| gate | The small decision trees that can lower a table's level during a run, or the release gate run before a change lands | "classifier"; "release gate" |
| HIGH | Trust level L0, the old `Confidence.HIGH`, or the scan's top likelihood | L0 for trust; "p ≥ 0.8" for the scan |
| key | An answer key, a key table (a table in an answer key), or a table's first column | "answer key", "key table", "first column" |

*Table 4. Words with more than one meaning.*

### Old shape and new shape

| `master` | Branch | What changes |
|---|---|---|
| `detect_tables()` is the only table finder | One reader among seven public ones (Figure 2) | Each reader fails alone and records what it rejected |
| A table section's `Confidence` is always `HIGH` | A trust level L0 to L5 in `metadata["level"]` | Trust is earned, graded and published |
| No record of rejected candidates | `evidence.Record` | Every rejection is kept, with its rule |
| `PipelineResult` | Gains `discards` | Everything dropped, and why |
| `convert_pdf()` returns Markdown and prompts | Adds `convert_pdf_with_summary()` | The command line writes `paper.summary.json` from it |

*Table 5. What replaces what.*

```diff
@@ -88,4 +88,18 @@
     wording_role: str | None = None
 
+@dataclass
+class TableCandidate:
+    # A table proposed by one independent extractor, before selection.
+    source: str
+    rows: list[list[list[Line]]]
+    bboxes: dict[int, tuple[float, float, float, float]] = field(default_factory=dict)
+    flags: list[str] = field(default_factory=list)
+    def cell_text(self, r: int, c: int) -> str: ...
+    @property
+    def pages(self) -> list[int]: ...
+    @property
+    def shape(self) -> tuple[int, int]: ...
+    def text_rows(self) -> list[list[str]]: ...
+
 # Compute the bounding box enclosing all given bbox tuples.
 def compute_bbox(bboxes: list[tuple]) -> tuple[float, float, float, float]: ...
```

*Figure 1. `lib/pdf/types.py` (generated). The only new type in the shared types file is a reader's candidate table.*

```diff
+def find_code_pairs(blocks: list[Block], rules_for=None) -> list[TableCandidate]: ...
+def build_text(words, hrules=(), specialists=None): ...
+def extract_poll_tables(page, page_num: int, words_hint=None) -> list[TableCandidate]: ...
+def read_region(page, page_num: int, bbox) -> list[TableCandidate]: ...
+def extract_ruled_tables(page, page_num: int, drawings=None) -> list[TableCandidate]: ...
 def detect_tables(blocks: list[Block]) -> tuple[list[Section], list[Block]]: ...
+def extract_tagged_tables(doc) -> list[TableCandidate]: ...
```

*Figure 2. The readers (generated). `detect_tables` is unchanged; the six `+` lines are new readers, all returning `TableCandidate`. Two readers have no public function of their own: the column-rule reader inside `ruled.py` labels its tables `grid`, and the repeating-record reader is `read_region`.*

| Reader | Reads | Kind of information | Priority |
|---|---|---|---|
| `tags` | The PDF's own table tags | tree | 0 |
| `poll` | A WG21 straw poll: the line `SF F N A SA` and the counts under it | meaning | 1 |
| `grid` | Tables ruled in both directions, and tables ruled with column lines only | paths | 2 |
| (malformed tags) | Tags MuPDF reports as broken. A priority slot, not a reader | tree | 3 |
| `rules` | Horizontal rules and shaded row boxes (LaTeX booktabs, ReportLab) | paths | 4 |
| `codepair` | Two code listings side by side that share code | words, meaning | 5 |
| `tomd` | Columnar text blocks: the original detector | words | 6 |
| `content` | Rows and columns from where the words sit, in a located area | words | 7 |
| `records` | Repeating kinds of lines, such as name, number, number | meaning | 8 |

*Table 6. The reader priority, from `table._SOURCE_PRIORITY`. When readers disagree, tomd keeps the first reading in this order with no bad flag, and breaks ties within a slot by evidence, never by the order the readers ran.*

### Evidence

```diff
+@dataclass
+class Entry:
+    kind: str
+    scan: str
+    page: int
+    bbox: Box
+    rule: str
+    info: str
+    value: object = None
+    observed: bool = True
+
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
```

*Figure 3. `lib/pdf/evidence.py` (generated). `Entry.kind` is "nominated", "excluded" or "feature". `Entry.info` is the kind of information, and `observed` says whether the fact was seen on the page or inferred by a reader.*

```diff
+# Record a reader, check or specialist that raised (stage, page or None for the whole paper,
+# exception type and message). Tables the failure touched drop to UNCERTAIN ("reader error");
+# the prompts note and the paper summary list it. TOMD_STRICT=1 re-raises instead (tests).
+def reader_error(stage: str, page, exc: BaseException, table=None) -> None: ...
```

*Figure 4. Reader failures (generated). A reader that raises is recorded, never swallowed.*

### Region scan

```diff
+@dataclass
+class AreaContext:
+    # What a region-level check may look at.
+    page: object
+    area: dict
+    generator: str
+    doc_tagged: bool
+    measure: object = None
+    cache: dict = field(default_factory=dict)
+
+@dataclass(frozen=True)
+class Check:
+    name: str
+    levels: tuple[str, ...]
+    info: str
+    cost: int
+    optional: bool
+    run: Callable[['AreaContext'], dict]
+    tier: int = 1
+def band(p: float, info_types: int) -> str: ...
+# P(table) and the features that pushed it most (signed contributions).
+def likelihood(x: dict, model: dict) -> tuple[float, list[tuple[str, float]]]: ...
+# Score every area in the evidence record and decide by band.
+def run_scan(path, record, tables, builds: list | None = None) -> list: ...
```

*Figure 5. `lib/pdf/checks/__init__.py` and `lib/pdf/scan.py` (generated). Every area any reader nominated, including areas a rule rejected, goes through the checks, and a logistic model fitted on the answer keys turns the evidence into a likelihood `p`.*

`band()` turns `p` into an action. **trust**: p ≥ 0.8 and two kinds of information, so the area may compete for L0. **build**: p ≥ 0.55 (or p ≥ 0.8 with only one kind), so the area is built as a table and emitted flagged. **mark**: 0.3 ≤ p < 0.55, so the area gets a possible-table mark. **none**: below 0.3, recorded only.

The checks run cheapest and most decisive first. Word gaps, footprint and caption form a last-resort tier that runs only while an area is undecided. A tier is promoted for a PDF producer where that producer's own measurements show a gain (`GENERATOR_TIER`).

### Trust levels

```python
# drawn: Section.metadata for a TABLE section (the keys the code reads and writes most)
class TableMeta(TypedDict, total=False):
    table_source: str                  # the reader whose reading was kept (Table 6)
    region_bbox: tuple[int, Box]       # (page, box)
    page_bboxes: dict[int, Box]        # every page piece of a table that crosses pages
    table_agreement: str               # "exact" | "subset" | "none": did another reader agree
    uncertain_reasons: list[str]       # why it is not trusted
    table_versions: list[dict]         # the other readers' versions, shown in the prompts file
    verified: str                      # "ok", or what the layout check found
    likely: bool                       # the fit test passed (L1)
    level: dict                        # levels.assign(): {"level", "name", "why", "incomplete", "cells"}
    spans: list[dict]                  # merged cells, kept even though Markdown flattens them
    llm_repair: dict                   # only when the AI step changed it; holds the first reading
    continues_from: dict               # {"page": N, "reasons": [...]}, only on a "may continue" note
```

```diff
+# {"level", "name", "why", "incomplete", "cells"} for a table section
+def assign(sec) -> dict: ...
+# cells where an alternative reading of the same shape disagrees with the table
+def cell_markers(sec) -> list[tuple[int, int]]: ...
+def comment(info: dict) -> str: ...
+NAMES = ...
```

*Figure 6. A table's metadata (drawn) and `lib/pdf/levels.py` (generated). L0 needs agreement between different kinds of evidence plus conservation. A gate of two small decision trees can lower a level. Three rules can only lower one: a grid whose cells are mostly images is never L0, damaged-text characters keep a table out of L0, and characters in the cells more often than on the page force L4.*

### Pipeline and output

```diff
@@ -13,7 +13,17 @@
     skipped: bool = False
     skip_reason: str = ''
+    discards: list = field(default_factory=list)
 
 # Convert a PDF file to Markdown.
 def convert_pdf(path: Path) -> tuple[str, str | None]: ...
 
-# + 5 private functions or classes
+# convert_pdf plus the paper-level summary (summary.py): tables trusted, flagged and marked,
+# confidence and unfamiliarity. Written as JSON beside the Markdown by the command line.
+def convert_pdf_with_summary(path: Path) -> tuple[str, str | None, dict | None]: ...
+
+# Every area a reader or scan nominated and a rule then excluded, where no kept table covers
+# it, as a possible-table region - a drop never leaves the text silent - except the rules
+# above. (page, bbox, reason, rows) like every mark region.
+def dropped_nomination_regions(record, tables) -> list: ...
+
+# + 14 private functions or classes
```

*Figure 7. `lib/pdf/__init__.py` (generated). `PipelineResult` gains `discards`, and a new entry point returns the paper summary with the Markdown and prompts.*

```diff
+def build(result, sections, evidence, generator: str) -> dict: ...
+# The measured chance that this paper's tables hold no silent error: the rate on the answer
+# keys for papers with a similar score, with its interval. An unfamiliar paper never gets the
+# familiar papers' figure: it is capped by unfamiliarity, and the interval widens to match.
+def confidence(s: dict) -> dict | None: ...
+# 0 (like the measured papers) .. 1 (unlike them), with the reasons.
+def unfamiliarity(generator: str, layouts: list[str], undecided: int, areas: int, rotated: bool, measured: bool, skipped: bool) -> tuple[float, list[str]]: ...
```

```python
# drawn: the dict summary.build() returns, written as paper.summary.json
class PaperSummary(TypedDict, total=False):
    tables: dict              # total, trusted, likely, flagged, and the pages of each
    continuations: list[dict] # "may continue" notes
    marks: int                # possible tables not converted
    marked_pages: list[int]
    removed: list[dict]       # {what, why}: page headers, contents pages, hidden text, dropped readings
    scan: dict                # areas, undecided, low_tables
    unfamiliarity: dict       # {score 0-1, reasons}: e.g. a PDF producer tomd was never measured on
    generator: str            # the program that made the PDF: "LaTeX", "Word", ...
    confidence: dict          # {value, low, high, band, papers, capped}: the measured share of similar
                              # papers with no silent table error, with its 95% interval
    visibility: dict          # hidden text found: where, why, how many characters
    witnesses: dict           # optional: what the AI step did, its tokens and time
    reader_errors: list[dict] # optional: readers that failed
```

*Figure 8. The paper summary: `lib/pdf/summary.py` (generated) and the JSON's keys (drawn). The confidence is a measured base rate for similar papers, capped when the paper is unfamiliar. It is not a judgement of this particular paper.*

```diff
+def check_page(page) -> list[dict]: ...
+def classify(page) -> list[dict]: ...
+def markdown(regions: list[dict]) -> str: ...
+def remove_hidden_text(page, regions) -> bool: ...
+def summary(regions: list[dict]) -> dict: ...
```

*Figure 9. Hidden text, `lib/pdf/visibility.py` (generated). Two of the classes (text under an image, text the colour of its background) guess at what lies under the text, so they are confirmed by rendering the region with and without it.*

```text
<!-- tomd:summary tables=12 trusted=5 flagged=6 likely=1 marked=2 confidence=0.91 unfamiliarity=0.00 -->
<!-- tomd:uncertain:L120-L131 -->
<!-- tomd:level L3 structure-uncertain: readers disagree cells=r2c3 -->
<!-- tomd:likely reason=fit (...) -->
<!-- tomd:continues page=14 (may continue the table on page 13: ...; not merged) -->
<!-- tomd:hidden page=3 bbox=... why=same-colour chars=212 -->
<!-- tomd:not-converted pages=1-12 why=unreadable-text-layer -->
```

*Figure 10. Examples of the comment format. The full list is in `doc/design-tomd.md`. The paperflow copy of tomd writes six more markers that this branch does not have (see Open questions).*

### The AI step (off by default)

```diff
+# Cells of spans from word indices, or (None, reason) if the answer is unusable: an index out
+# of range, used twice, or a word left out.
+def build_columns(rows, words): ...
+def code_guard(first, repaired) -> str: ...
+# Try to repair one flagged table in place. Returns what happened.
+def repair(sec, page, bbox, words, verify, client=None) -> str: ...
+MODEL = 'claude-opus-5-5'
```

*Figure 11. `lib/pdf/llmrepair.py` (generated). The model receives the table's words numbered 0, 1, 2 and so on, and answers with rows of those numbers. `build_columns()` refuses an answer that leaves a word out or uses one twice. A repair is kept only if two asks give the same answer, it passes the layout check, and `code_guard()` passes. The table then drops to L4 and keeps its first reading. A second model call, the "second look", can name rows to check, but never changes text or raises a level.*

| Switch | Default | Effect |
|---|---|---|
| `--corpus` | off | Turns on the AI step, with a run budget of 5,000,000 tokens and a paper budget of 51,500 tokens (about $1 at assumed prices) |
| `TOMD_LLM`, `TOMD_LLM_CHECK` | off | AI repair of L3 and L4 tables; the second look |
| `TOMD_LLM_BUDGET`, `TOMD_LLM_PAPER_BUDGET` | none | Tokens per run; repair tokens per paper |
| `TOMD_VISIBILITY` | on | Hidden-text removal |
| `TOMD_SUMMARY`, `TOMD_LEVELS` | on | Summary JSON and header; L0 to L5 comments |
| `TOMD_STRICT` | off | Reader errors re-raise (tests) |

*Table 7. The switches a user or operator may set. Every other improvement ships behind its own `TOMD_<NAME>` switch, on by default, and `=0` restores the earlier behaviour.*

</implementation-contract>
<verification-contract>

## Testing Plan

The tests protect three promises: the same bytes every time, one table never changing another, and nothing lost silently. Quality is measured against answer keys built blind by AI agents from page images and the text layer, under written conventions decided by a person, through a release gate that refuses any loss. Two sets of papers stay untouched until the final benchmark.

- Unit: Figure 12 lists the new tests, generated from the test files. Each name says what it protects.
- Golden tests: the existing `tests/test_pdf_golden.py` stays, and a subset of the answer keys ships as fixtures.
- Release gate (outside the repo): every change runs on the tuning sets with `PYTHONHASHSEED=0`. It fails if any table type or PDF producer loses a correct table, gains a silent miss or a wrong L0, or any table loses more than a point. A change that fails twice is reverted.
- Exit criteria: 90 to 95% on the tuning sets and 80% on unseen papers. Neither is met.

```python
def test_piece_reaching_bottom_then_top_is_noted(): ...
def test_piece_ending_mid_page_is_not_noted(): ...
def test_no_note_without_numbering(): ...
def test_output_does_not_depend_on_the_hash_seed(pdf): ...
def test_one_row_per_code_line_alone_is_not_rejected(): ...
def test_added_line_number_column_is_rejected(): ...
def test_repair_keeping_code_blocks_passes(): ...
def test_prose_tables_are_not_affected(): ...
def test_spent_paper_budget_leaves_table_unrepaired(monkeypatch): ...
def test_no_budget_set_asks_as_before(monkeypatch): ...
def test_no_credentials_runs_on_and_says_so(monkeypatch, tmp_path): ...
def test_off_by_default(monkeypatch): ...
def test_budget_stops_repair(monkeypatch): ...
def test_verified_repair_keeps_first_reading_and_stays_flagged(monkeypatch): ...
def test_every_reader_runs_without_raising(pdf, monkeypatch): ...
def test_a_raising_reader_is_recorded_and_flags_its_tables(monkeypatch): ...
def test_a_stage_that_cannot_touch_tables_downgrades_none(monkeypatch): ...
def test_one_tables_check_failure_does_not_downgrade_its_neighbours(monkeypatch): ...
def test_continuation_row_joins_record_above(): ...
def test_rule_between_rows_keeps_them_apart(): ...
def test_no_grid_no_change(): ...
def test_full_row_with_blank_key_is_its_own_record(): ...
def test_no_undefined_names_in_the_package(): ...
def test_the_check_catches_a_missing_import(tmp_path): ...
def test_comment_follows_front_matter(both): ...
def test_uncertain_markers_still_point_at_their_lines(both): ...
def test_summary_fields(both): ...
def test_remove_table_regions_keeps_text_outside(): ...
def test_standalone_dash_at_cell_line_break_keeps_the_break(): ...
def test_text_in_table_region_but_not_in_table_is_kept(): ...
def test_damaged_text_layer_marks_table_uncertain_with_note(): ...
def test_lost_header_row_above_agreeing_sources_is_uncertain(): ...
def test_jev_calls_are_batched_and_failures_fall_back(monkeypatch): ...
def test_ocr_tokens_short_must_match_long_may_be_fuzzy(): ...
def test_skipped_document_leaves_a_visible_trace(): ...
def test_code_comparison_renders_as_fenced_blocks(): ...
def test_no_hidden_text_in_body(adv): ...
def test_every_hidden_line_listed(adv): ...
def test_summary_and_prompts(adv): ...
def test_off(monkeypatch): ...
def test_duplicate_of_visible_text_kept(): ...
def test_fence_longer_than_backticks(): ...
def test_unreadable_text_layer_is_never_empty(monkeypatch): ...
def test_transparent_text_over_an_image_kept(): ...
```

*Figure 12. New tests on the branch (generated, by name; a selection of the 21 new test files).*

| Role | Sets | Use |
|---|---|---|
| Tuning | dev, heldout, fresh, fresh2 to fresh9 (818 papers, 1,746 answer-key tables) | Development and the release gate |
| Least tuned | fresh10 (99 papers, 142 answer-key tables) | Kept out of development but scored repeatedly, so weakened |
| Untouched | A 200-paper reserved pool, and the WG21 mailing released around 2026-10-23 | Frozen until the code is frozen, then scored once |

*Table 8. The scoring sets.*

| Measure | `master` | Branch, AI step off | Docling | Table Transformer |
|---|---|---|---|---|
| Tuning: mean table accuracy | 12.3% | 84.2% | 51.9% | 45.5% |
| fresh10: mean table accuracy | 4.0% | 67.1% | 42.8% | 36.1% |
| Tables exactly right (of 1,888) | 112 | 1,347 | — | — |
| Missed with no warning | 1,570 | 57 | — | — |
| Trusted but wrong | 991 | 0 | — | — |

*Table 9. Results against the answer keys. Docling (IBM) and Table Transformer (Microsoft) are scored on the same tables. Both beat tomd on two layout types: LaTeX booktabs, and code inside table cells.*

</verification-contract>
<decision-record>

## Decision Record

- Decisions:
  - **Trust needs agreement between different kinds of evidence.** *Why:* two readers of the same text positions are one witness. On p3830r0 all three readers agreed on "WF" where the page prints "F". *Cost:* most correct tables are flagged. 1,280 tuning tables are exactly right, but only 447 are L0 (all 447 right).
  - **Nothing is lost silently.** *Why:* silent misses fell from 1,570 to 57. *Cost:* marks are noisy, with 4,149 uncertainty markers on the tuning sets.
  - **Trust is graded L0 to L5 and published per table.** *Why:* "flagged" alone does not tell an AI reader what may be wrong. *Cost:* L2 to L4 only roughly order risk.
  - **One content builder reads located areas, and drawn lines only confirm it.** *Why:* pointed at tables no reader read, it made about 45% of them exact or one fix away. *Cost:* building tables is the bottleneck, weakest on LaTeX booktabs.
  - **Determinism and locality are invariants.** *Why:* before the fix, 2 of 2,121 tables changed between runs. *Cost:* some paper-wide signals were narrowed or given up.
  - **The AI step is optional, rearranges words only, and is capped.** *Why:* on the tuning sets it took mean accuracy from 84.16% to 84.30%, fixing 30 tables and breaking 21 with the budget on, all still flagged. That is a net gain even counting a wrong fact as twice the harm of a missing one. *Cost:* about $74 for the tuning sets at assumed prices, not checked against billing.
  - **Paper confidence is a measured base rate.** *Cost:* it barely ranks papers (AUC 0.58 on the tuning sets, where 0.5 is chance).
  - **Machine information lives beside the Markdown, never in it.** *Cost:* the comment syntax is now a public format.
- Rejected alternatives:
  - Ranking readers by their track record per PDF producer: failed the release gate twice. Off as `TOMD_TRACK_ORDER`.
  - A model that predicts each reading's accuracy (cross-validated AUC 0.87): could not beat the fixed priority on papers it had not seen. Perfect choosing is worth under 2 points.
  - Rebuilding tables from word positions alone: invented tables, and failed twice.
  - Joining tables across pages: no measured signal separates a continuation from the next table. Revisit when one exists.

</decision-record>
<execution-plan>

## Execution Instructions

Review the 24 stacked branches `pr2/01` to `pr2/24`, which replay the branch in order. `pr2/24` is identical to `tables-reportlab`.

| Step | Branches | Declarations to check | Confidence |
|---|---|---|---|
| 1. This plan and the design document | `pr2/01` | Tables 3 to 6 | High |
| 2. Trust on agreement, and marks | `pr2/04` | `TableCandidate`, Table 6 | High: every later branch builds on it |
| 3. Independence and the evidence record | `pr2/07`, `pr2/08` | `Entry`, `Record` | High |
| 4. The region scan | `pr2/09` | `Check`, `AreaContext`, `band` | High |
| 5. Paper summary and confidence | `pr2/11` | `summary.build`, `PaperSummary` | Medium: refit later, in `pr2/22` |
| 6. Trust levels | `pr2/21` | `levels.assign`, `TableMeta` | High |
| 7. Determinism and locality | `pr2/22` | `reader_error`, the tests in Figure 12 | High |
| 8. The AI step | `pr2/12`, `pr2/24` | `llmrepair.repair`, `code_guard` | Medium: optional and off by default |

*Table 10. Review order. `pr2/02` and `pr2/03` are mostly answer-key fixtures (about 20,000 lines of JSON against under 2,000 of code), and the measuring tools live outside this repo.*

</execution-plan>

---

*2026-10-25, Claude Opus 5.5. Declarations generated by pyheader from `master` and `tables-reportlab`.*
