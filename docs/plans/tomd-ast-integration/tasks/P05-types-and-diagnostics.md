# P05 Unify shared types, add `Diagnostics`, render trailer markers

| Wave | Deps | Parallel with | Size | Risk |
|------|------|---------------|------|------|
| 1 | P02 | P03, P04, P06, P07 | M | medium |

## Goal

One definition each of `SkipReason`, `ExtractedImage`, and the per-paper diagnostics.
Give `PaperDocument` a typed `diagnostics` field and let the writer render the trailing
HTML-comment markers that `emit_markdown` appends today.

## Read first

- `lib/pdf/types.py` `SkipReason` (values `"empty pdf"`, `"slide deck"`, ...), domain
  `SkipReason` (different names and values), `cli/jobs.py` `_SKIP_REASON_MAP`,
  `cli/models.py:77`, `tests/test_pipeline_skip_contract.py`
- `lib/pdf/images.py`: `ExtractedImage` (line 139), `ImageSource`,
  `TRUNCATION_MARKER_TEMPLATE`, `VectorUncertaintyStats`
- `lib/pdf/vector_images.py`: `format_uncertainty_marker`, `should_emit_marker`
- `lib/pdf/glyphs.py`: `GlyphPassStats`, `GLYPH_PLACEHOLDER_MARKER_TEMPLATE`,
  `UNKNOWN_GLYPH`
- `lib/pdf/emit.py` `emit_markdown` tail (images_truncated marker, vector marker,
  glyph marker computed from the finished body)
- `api.py` `ConvertedPaper` (the real result type)
- `domain/document.py`, `domain/image.py`

## Change

1. Canonical `SkipReason` moves to `domain/document.py` with the legacy member names
   and values (`EMPTY_PDF = "empty pdf"`, ...). `lib/pdf/types.py` re-exports it. The
   old domain members and `ConvertedPaper` (unused) are deleted; `api.ConvertedPaper`
   stays the result type.
2. Canonical `ExtractedImage` moves to `domain/image.py`: the legacy 13-field frozen
   dataclass including `source`, `sub_captions`, `caption_body_dropped`. `lib/pdf/images.py`
   re-exports it (same import path keeps working). Move `ImageSource` with it.
3. Move `VectorUncertaintyStats` and `GlyphPassStats` into a new `domain/diagnostics.py`
   (frozen dataclasses, unchanged fields); re-export from their old modules. Add
   `Diagnostics(images_truncated: bool, source_image_count: int,
   vector_uncertainty: VectorUncertaintyStats | None, glyph_stats: GlyphPassStats | None,
   extra_prompts: tuple[str, ...])`. `extra_prompts` holds already-formatted prompt
   strings (the parser owns the preamble: PDF wording problems, HTML problems).
   `PaperDocument.diagnostics: Diagnostics = Diagnostics()`.
4. `writers/markdown/markers.py` (new): functions that render the three markers by
   calling the existing template/format helpers in `lib/` (do not copy them). The writer
   appends markers after the last element in the legacy order: truncation, vector
   uncertainty, then (last) glyph placeholders. The glyph count must be taken from the
   finished body the same way `emit_markdown` does (`md.count(UNKNOWN_GLYPH)`).
   Write the function so the bridge in P08 can call "body" and "trailer" separately.
5. Update `cli/jobs.py`/`cli/models.py` only if imports break; behavior unchanged.

## Do not

- Change any marker text, the closed reason-key set, or when a marker fires.
- Edit `emit_markdown` (it keeps working through the re-exports).

## Tests

- Skip-contract and image tests still pass unchanged (`test_pipeline_skip_contract.py`,
  `test_images.py`, `test_glyphs.py`).
- Twin tests: for each marker, render with the writer and compare to the string
  `emit_markdown` produces for a one-paragraph section list with the same stats:
  truncated images; vector uncertainty (fires and does not fire per
  `should_emit_marker`); glyph placeholders with and without skipped counts; all three
  together (order).

## Acceptance

Checklist green; `python -c "import tomd.domain, tomd.lib.pdf"` shows no import cycle;
`git diff --stat` shows `lib/` changes only in the re-export lines.

## Handoff (fill in at the end)

```
Status: done
Files changed:
  - packages/tomd/src/tomd/domain/__init__.py
  - packages/tomd/src/tomd/domain/diagnostics.py (new)
  - packages/tomd/src/tomd/domain/document.py
  - packages/tomd/src/tomd/domain/image.py
  - packages/tomd/src/tomd/lib/pdf/glyphs.py
  - packages/tomd/src/tomd/lib/pdf/images.py
  - packages/tomd/src/tomd/lib/pdf/types.py
  - packages/tomd/src/tomd/writers/markdown/__init__.py
  - packages/tomd/src/tomd/writers/markdown/markers.py (new)
  - packages/tomd/src/tomd/writers/markdown/writer.py
  - packages/tomd/tests/domain/test_domain_models.py
  - packages/tomd/tests/writers/markdown/test_markers.py (new)
Checklist output (tails):
  - pytest domain + writers + skip/images/glyphs: 461 passed, 1 xfailed in 0.58s
  - pytest full tomd: 2580 passed, 7 skipped, 1 xfailed in 134.47s
  - pytest cli: 153 passed in 73.95s
  - ruff check packages tests: All checks passed!
  - pyright domain + writers + tests: 0 errors, 0 warnings, 0 informations
Import-cycle check:
  - `uv run python -c "import tomd.domain, tomd.lib.pdf"` -> exit 0 (no cycle)
  - `uv run python -c "import tomd.lib.pdf, tomd.domain"` -> exit 0 (no cycle)
Known divergences found:
  - `GlyphPassStats` remains a mutable `@dataclass` (not frozen) because `lib/pdf/glyphs.py` (`inject_glyph_spans`) and `lib/pdf/pipeline.py` mutate `stats.injected`, `stats.free_standing`, and `stats.skipped_code_section` in place.
Open questions:
  - none
```

---

# Review follow-ups

Adversarial review of the P05 working tree. Items are ordered by severity and resolved in place.

## R1. Remove `ImageElement` fallback scan and duplicate guard in `MarkdownWriter.write` (medium)

`MarkdownWriter.write` computed `kept_image_count = len(document.images) or sum(1 for elem in document.elements if isinstance(elem, ImageElement))`.
- Kept sidecar images live on `PaperDocument.images`, never as `ImageElement` nodes in `document.elements`.
- Because `0` is falsy in Python, every paper without images triggered an O(N) scan of `document.elements`.
- Callers of `write_body` + `append_trailer_markers` pass `kept_image_count=len(doc.images)`, so the fallback created a discrepancy between `write` and the split path.

Fix: drop `ImageElement` from `writer.py` and pass `kept_image_count=len(document.images)` directly to `append_trailer_markers`.

## R2. Move marker-emission predicates onto domain models and narrow `markers.py` exports (medium)

- `GlyphPassStats` had `fired` (for pipeline log gating) in `domain/diagnostics.py`, while the trailer-marker condition (`present or skipped_coincident or skipped_code_section`) and truncation drop math lived inside `writers/markdown/markers.py`.
- `writers/markdown/markers.py` exported all three per-marker helper functions in addition to `append_trailer_markers`, and `writers/markdown/__init__.py` re-exported all four using relative imports.
- `append_trailer_markers` defaulted `kept_image_count: int = 0`, which silently emits `"kept 0 of N images"` if a caller omits `kept_image_count`.

Fix:
- Add `GlyphPassStats.should_emit_marker(present: int) -> bool` and `Diagnostics.dropped_image_count(kept_image_count: int) -> int` in `domain/diagnostics.py`.
- Make `_render_truncation_marker`, `_render_vector_uncertainty_marker`, and `_render_glyph_placeholder_marker` private helpers taking only the slice of state they need (`stats` rather than full `Diagnostics`).
- Make `kept_image_count: int` a required keyword-only argument on `append_trailer_markers` and export only `append_trailer_markers` from `markers.py` (and `MarkdownWriter`, `append_trailer_markers` from `writers/markdown/__init__.py` via absolute imports).

## R3. Use `field(default_factory=Diagnostics)` on `PaperDocument` (low)

`PaperDocument.diagnostics: Diagnostics = Diagnostics()` shared a single class-attribute default instance across documents.

Fix: use `field(default_factory=Diagnostics)` in `domain/document.py`, matching `metadata: PaperMetadata = field(default_factory=PaperMetadata)`.

## R4. Restore domain constraint docstrings on `ExtractedImage`, `VectorUncertaintyStats`, and `GlyphPassStats` (low)

Moving `ExtractedImage`, `VectorUncertaintyStats`, and `GlyphPassStats` to `domain/` stripped the docstrings explaining cross-format sentinels (`page=0`, `bytes=b""`, `bbox=(0,0,0,0)`, `xref=0` for HTML; `caption_body_dropped` #408 gate) and field subset relationships (`free_standing` and `skipped_code_section` as subsets of `injected`).

Fix: restore concise domain-constraint docstrings on the canonical classes in `domain/image.py` and `domain/diagnostics.py`.

## R5. Consolidate `test_markers.py` with `@pytest.mark.parametrize` and cover missing boundary cases (medium)

`test_markers.py` had 9 separate functions repeating identical 20-line setup and missed boundary conditions:
- `present == 0` with `skipped_coincident > 0` (must still emit `placeholders=0`),
- `injected > 0` (`stats.fired is True`) with `present == 0` and `skipped_* == 0` (must not emit),
- `images_truncated=True` when `kept == source_image_count` (`dropped == 0`, must not emit),
- vector uncertainty firing solely via `pages_skipped > 0` (`rejected == 0`) and suppressed when `pages_scanned == 0, pages_skipped == 0`.

Fix: replace the 9 repetitive functions with `_assert_twin_output` and a parametrized table covering all 13 single-marker cases plus the 3-marker ordering test and the split `write_body` + `append_trailer_markers` test.

## R6. Clean up `test_domain_models.py` (low)

- Move `lib/pdf` re-export imports to module top level (no function-local imports).
- Remove `not hasattr(..., "ConvertedPaper")` assertions and their dedicated module-alias imports.
- Drop `body=""` from `PaperDocument(...)` construction so it stays compatible with `P02`.
- Test `ExtractedImage` defaults/immutability and parametrize `GlyphPassStats.fired` / `should_emit_marker` across all four counter fields.

## Resolution log

| Item | Outcome |
|------|---------|
| R1 | Done. `writer.py` passes `kept_image_count=len(document.images)` directly; `ImageElement` import removed. |
| R2 | Done. Added `GlyphPassStats.should_emit_marker` and `Diagnostics.dropped_image_count`; made `_render_*` private in `markers.py`; required `kept_image_count`; switched `writers/markdown/__init__.py` to absolute imports. |
| R3 | Done. `PaperDocument.diagnostics` uses `field(default_factory=Diagnostics)`. |
| R4 | Done. Restored concise domain-constraint docstrings in `domain/image.py` and `domain/diagnostics.py`. |
| R5 | Done. Consolidated `test_markers.py` with `@pytest.mark.parametrize` and added the 4 missing boundary cases. |
| R6 | Done. Cleaned up `test_domain_models.py` imports, `PaperDocument` call, and predicate/default coverage. |

## PR #485 review follow-ups (jasonbrazeal)

| Comment | Outcome |
|---------|---------|
| `diagnostics.py`: check sum > 0 instead of `bool(a or b ...)` on int counters in `GlyphPassStats.fired` and `should_emit_marker` | Done. Replaced `bool(... or ...)` with `(...) > 0`. |
| `lib/pdf/{glyphs,images,types}.py`: remove `from tomd.domain... import X as X` re-exports | Done. Removed `as X` re-exports (including `domain/metadata.py`) and updated callers/tests to import domain types directly from `tomd.domain.*`. |
| `test_domain_models.py`: remove `test_diagnostics_models_and_reexports` identity assertions | Done. Removed `Pdf*` alias imports and `is` assertions; renamed test to `test_diagnostics_models`. |
| Avoid library conventions (`__all__` in regular modules) in application code | Done. Removed `__all__` from non-`__init__.py` modules in `domain/` and `writers/markdown/`, and added anti-library-idiom rules to `CLAUDE.md` and global `AGENTS.md`. |
