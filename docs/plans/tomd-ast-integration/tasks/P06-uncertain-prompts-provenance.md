# P06: Uncertain Regions, Reconcile Prompts, and Block Provenance

## Context

When `tomd` converts a PDF paper into Markdown, it extracts text from each page using two independent algorithms:
1. **MuPDF extraction** (`mupdf_text`): PyMuPDF's native text-block ordering.
2. **Spatial extraction** (`spatial_text`): geometric clustering of spans and lines by bounding box.

When the two extractions agree (`Confidence.HIGH`, `MEDIUM`, or `LOW`), the converter classifies the text into normal structural blocks (headings, paragraphs, lists, code blocks, tables). When they disagree on a page (`Confidence.UNCERTAIN`), `tomd` does not silently guess. Instead, it does two things:

1. **Marks the region in `<pid>.md`** with a 1-based line-range HTML comment above the MuPDF text:
   ```markdown
   <!-- tomd:uncertain:L120-L125 -->

   <MuPDF extracted text>
   ```
2. **Generates an LLM reconciliation prompt in `<pid>.prompts.json`** containing the page number, both extractions (`mupdf_text` and `spatial_text`), and up to 200 characters of the preceding and following confident sections (`context_before` and `context_after`).

Previously, the AST domain (`tomd.domain`) and `MarkdownWriter` only had a placeholder `UncertainElement(prompt, raw_content)` that could not represent dual-path extractions, compute line-range markers, or build reconciliation prompts. Additionally, `BlockElement` had no field to carry source `page` and `Confidence` metadata (which `lib/pdf` tracks on every `Section`).

## Approach

1. **Block Provenance (`Confidence` and `Provenance` in `domain/elements.py`)**
   - Define `Confidence(StrEnum)` (`HIGH`, `MEDIUM`, `LOW`, `UNCERTAIN`) and `Provenance(page: int, confidence: Confidence)` directly in `tomd.domain.elements` (re-exported from `tomd.domain`), and update internal callers to import `Confidence` from `tomd.domain.elements` so `domain` never imports from `lib/pdf`.
   - Keep `provenance: Provenance | None = field(default=None, kw_only=True)` on `BlockElement`.

2. **`UncertainElement` and Jinja2 Prompt Templates (`tomd/prompts/`)**
   - `UncertainElement` in `domain/elements.py` holds `mupdf_text: str`, `spatial_text: str`, `page: int`, `text: str = ""` (with a comment explaining that `text` holds the body text emitted under the `<!-- tomd:uncertain:... -->` marker in Markdown, typically `mupdf_text` after any downstream trimming such as abstract extraction, and serves as a fallback when either extraction string is empty), `context_before: str = ""`, and `context_after: str = ""`.
   - Create `packages/tomd/src/tomd/prompts/`:
     - `uncertain_element.md.j2`: Jinja2 template for the uncertain-region reconciliation prompt.
     - `render.py`: defines `PROMPTS_DIR` and `render_prompt(name: str, **context: Any) -> str` backed by `jinja2.Environment(loader=FileSystemLoader(PROMPTS_DIR), undefined=StrictUndefined)`.
     - `__init__.py`: re-exports `PROMPTS_DIR` and `render_prompt`.
   - Add `"jinja2"` to `dependencies` in `packages/tomd/pyproject.toml`.
   - Implement `UncertainElement.get_reconciliation_prompt(self) -> str` in `domain/elements.py` delegating to `render_prompt("uncertain_element.md.j2", **asdict(self))`.
   - Implement `PaperDocument.get_reconciliation_prompts(self) -> list[str] | None` in `domain/document.py` collecting prompts from all `UncertainElement` blocks in document order (returning `None` when there are none, matching `emit_prompts`).

3. **1-Based Line Tracking in `MarkdownWriter` (`writer.py` and `blocks.py`)**
   - Remove `RenderContext` from `writers/markdown/blocks.py`.
   - Simplify `format_uncertain_element(element, line_num=1) -> str` in `blocks.py`:
     - The comment sits on `line_num`, a blank line sits on `line_num + 1`, so the text starts at `text_start = line_num + 2` and ends at `text_end = text_start + text.count("\n")`.
   - Track `line_num = 1` directly inside `MarkdownWriter.write_body` in `writer.py`:
     - Every emitted block `b` (including front matter and each non-empty body element) is followed by a blank separator line (`"\n\n"`), so it advances `line_num += b.count("\n") + 2`.
     - Empty or whitespace-only blocks (including empty `Heading`s) are skipped without advancing `line_num`.

4. **Test Refinements (`test_uncertain_and_prompts.py` and `test_domain_models.py`)**
   - Use `match sec.kind:` / `case` syntax in `_sections_to_document` (`packages/tomd/tests/writers/markdown/test_uncertain_and_prompts.py`).
   - Update tests to call `get_reconciliation_prompt()` and `get_reconciliation_prompts()`.

## Files to Modify

- `packages/tomd/pyproject.toml`
- `packages/tomd/src/tomd/prompts/__init__.py` (new)
- `packages/tomd/src/tomd/prompts/render.py` (new)
- `packages/tomd/src/tomd/prompts/uncertain_element.md.j2` (new)
- `packages/tomd/src/tomd/domain/__init__.py`
- `packages/tomd/src/tomd/domain/document.py`
- `packages/tomd/src/tomd/domain/elements.py`
- `packages/tomd/src/tomd/lib/pdf/types.py`
- `packages/tomd/src/tomd/writers/markdown/blocks.py`
- `packages/tomd/src/tomd/writers/markdown/writer.py`
- `packages/tomd/tests/domain/test_domain_models.py`
- `packages/tomd/tests/writers/markdown/test_blocks.py`
- `packages/tomd/tests/writers/markdown/test_uncertain_and_prompts.py`
- `docs/plans/tomd-ast-integration/tasks/P06-uncertain-prompts-provenance.md`

## Reuse

- `jinja2.Environment`, `FileSystemLoader`, `StrictUndefined` (already in the workspace via `assay`) for rendering `tomd/prompts/uncertain_element.md.j2`.
- `tomd.lib.pdf.emit.emit_markdown` and `tomd.lib.pdf.emit.emit_prompts` (`packages/tomd/src/tomd/lib/pdf/emit.py`) as the byte-parity oracle in tests.
- `make_section`, `make_line`, `make_span` (`packages/tomd/tests/conftest.py`) in `test_uncertain_and_prompts.py`.

## Steps

- [x] Change `Confidence` to inherit from `StrEnum` in `packages/tomd/src/tomd/domain/elements.py` and remove the unused `Enum` import.
- [x] Add a comment on `UncertainElement.text` in `packages/tomd/src/tomd/domain/elements.py` explaining what it stores and how it relates to `mupdf_text` and `spatial_text`.
- [x] Add `"jinja2"` to `packages/tomd/pyproject.toml` and create `packages/tomd/src/tomd/prompts/` (`__init__.py`, `render.py`, `uncertain_element.md.j2`).
- [x] Rename `UncertainElement.reconcile_prompt` to `get_reconciliation_prompt` (calling `render_prompt("uncertain_element.md.j2", **asdict(self))`) and `PaperDocument.reconcile_prompts` to `get_reconciliation_prompts`.
- [x] Refactor `_sections_to_document` in `packages/tomd/tests/writers/markdown/test_uncertain_and_prompts.py` to use `match sec.kind:` / `case` and update callers in `test_uncertain_and_prompts.py` and `test_domain_models.py` to use `get_reconciliation_prompt(s)`.
- [x] Run pytest, ruff, and pyright to verify all checks pass and byte parity with `emit_prompts` holds.

## Verification

- `uv run --package tomd pytest packages/tomd/tests -q`
- `uv run ruff check packages tests`
- `uv run pyright packages/tomd/src/tomd packages/tomd/tests`
- `git status --short`
