#
# Copyright (c) 2026 Sergio DuBois (sentientsergio@gmail.com)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
#
# Official repository: https://github.com/cppalliance/wg21-paperflow
#

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

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from tomd.lib.metadata_yaml.format import (
    FRONT_MATTER_RE,
    format_front_matter,
    parse_front_matter,
    sanitize_metadata,
    strip_front_matter,
)
from tomd.errors import UnsupportedSourceFormatError
from tomd.lib import (
    apply_strip_leading_h1,
    strip_freeform_metadata_lines,
    EMAIL_RE,
)
from tomd.lib.html import convert_html
from tomd.lib.html.images import load_html_images
from tomd.lib.pdf import ExtractedImage, PipelineResult, SkipReason, run_pipeline
from tomd.lib.pdf.emit import renumber_uncertain_markers

__all__ = ["ConvertedPaper", "convert_paper", "convert_paper_full"]


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
    def skipped_from(cls, raw: PipelineResult) -> "ConvertedPaper":
        """Translate a skipped :class:`PipelineResult` into a skipped
        :class:`ConvertedPaper`.
        """
        return cls(
            markdown="",
            prompts=raw.prompts,
            intent="",
            images=[],
            source_image_count=0,
            images_truncated=False,
            skipped=True,
            skip_reason=raw.skip_reason,
        )


logger = logging.getLogger(__name__)

_TOC_MAX_LINES = 300
# Matches a `Contents` (or `Table of Contents`) heading and the TOC entries
# beneath it, up to the first real section heading of any level. The heading
# line consumes only horizontal whitespace (`[ \t]*`), never the blank line
# after it: if `\s*` ate that newline, the body `(.*?)` would start at the next
# heading's `#` and the boundary lookahead (which needs a leading newline) could
# not fire on an immediately-adjacent heading, so the strip would swallow the
# first real section too (e.g. wg21 HTML, where `strip_boilerplate` removes the
# `div.toc` but leaves an empty `## Contents` directly before the first section).
# The boundary recognises any heading level (`#{1,6}`) so a deeper first section
# also terminates the strip.
_TOC_RE = re.compile(
    r"(?m)^(?:#{1,6}\s*)?(?:Table of )?Contents[ \t]*$\r?\n?"
    r"(.*?)"
    r"(?=\r?\n#{1,6}\s|\Z)",
    re.DOTALL | re.IGNORECASE,
)

_FALLBACK_KEY_MAP = {
    "title": "title",
    "paper_id": "document",
    "document_date": "date",
    "subgroup": "audience",  # mailing row key
    "target_group": "audience",  # DB row key (SqliteBackend)
    "authors": "reply-to",
}

# Keys where mailing metadata is authoritative and should override
# whatever the source document contains. SD-7 mandates that D-numbers
# (draft circulation) never appear in published mailings; the mailing
# paper_id (P/N-number) is the canonical identifier.
_OVERRIDE_KEYS = {"document"}

def _strip_toc_replace(m: re.Match[str]) -> str:
    span = m.group(0)
    if span.count("\n") > _TOC_MAX_LINES:
        return span
    return "\n"


def _strip_toc(text: str) -> str:
    """Remove a Table of Contents block from the converted Markdown.

    Removes a `Contents` label and the TOC entries beneath it, up to the first
    real section heading of any level, and never the first section itself. This
    is the output-level (Markdown string) TOC remover, run on all output in
    `convert_paper_full`; for HTML it is the only TOC remover. The sibling
    structure-level remover for the PDF path is
    `lib/pdf/structure.py:drop_leaked_toc_entries` (operates on the Section list
    before Markdown is emitted). An over-long match is left in place by
    `_strip_toc_replace` (the `_TOC_MAX_LINES` guard).
    """
    return _TOC_RE.sub(_strip_toc_replace, text)


def _normalize_front_matter(md: str, mailing_meta: dict | None) -> str:
    """Parse front matter once, sanitize, apply mailing fallback, and re-emit.

    Replaces the former three-pass sequence of ``_sanitize_front_matter``,
    ``_apply_metadata_fallback``, and ``_canonicalize_front_matter``.
    """
    parsed = parse_front_matter(md)
    rest = strip_front_matter(md)

    if not parsed and not mailing_meta:
        return md

    # Sanitize title and reply-to values.
    parsed = sanitize_metadata(parsed)

    # Inject missing fields (or override authoritative ones) from mailing.
    if mailing_meta:
        present = set(parsed)
        # Bare-name-only reply-to (no emails) should not block the
        # mailing fallback: the mailing may have richer author+email data.
        rt = parsed.get("reply-to")
        if isinstance(rt, list) and rt and not any(EMAIL_RE.search(e) for e in rt):
            present.discard("reply-to")
        added_yaml_keys: set[str] = set()
        for src_key, yaml_key in _FALLBACK_KEY_MAP.items():
            if yaml_key in added_yaml_keys:
                continue
            is_override = yaml_key in _OVERRIDE_KEYS
            if yaml_key in present and not is_override:
                continue
            val = (
                mailing_meta.get(src_key)
                if isinstance(mailing_meta, dict)
                else getattr(mailing_meta, src_key, None)
            )
            if val in (None, "", []):
                continue
            if yaml_key == "date":
                logger.debug(
                    "Date fallback from mailing (%s=%r): source had no date",
                    src_key,
                    val,
                )
            parsed[yaml_key] = val
            added_yaml_keys.add(yaml_key)

    if not parsed:
        return md

    new_block = format_front_matter(parsed)
    if not new_block:
        return md

    return f"{new_block}\n\n{rest.lstrip()}"


_METADATA_TABLE_LINE_RE = re.compile(
    r"^\|\s*(?:Doc(?:ument)?\.?\s*(?:No\.?|Number|#)|Date|Reply[- ]?to|"
    r"Audience|Author|Editor|Project|Email|Subgroup)\s*",
    re.IGNORECASE,
)

_PIPE_TABLE_ROW_RE = re.compile(r"^\|.*\|$")
_PIPE_SEPARATOR_RE = re.compile(r"^\|[\s\-:|]+\|$")

_METADATA_TABLE_SCAN_DEPTH = 30
_MIN_LABEL_ROWS_FOR_TABLE_STRIP = 2


def _strip_body_metadata_text(md: str) -> str:
    """Remove metadata pipe tables from the body (after front matter).

    Scans the first ~20 non-blank lines of the body for pipe tables whose
    rows contain metadata labels (Doc No, Date, Author, etc.). Removes
    complete tables (including separator rows) when >=2 label rows are found.
    """
    match = FRONT_MATTER_RE.match(md)
    if not match:
        return md

    front = md[: match.end()]
    body = md[match.end() :]

    lines = body.split("\n")
    to_remove: set[int] = set()
    i = 0
    scan_limit = min(len(lines), _METADATA_TABLE_SCAN_DEPTH)

    while i < scan_limit:
        if not lines[i].strip():
            i += 1
            continue

        if _PIPE_TABLE_ROW_RE.match(lines[i].strip()):
            table_start = i
            table_end = i
            label_count = 0

            while table_end < len(lines) and (
                _PIPE_TABLE_ROW_RE.match(lines[table_end].strip())
                or _PIPE_SEPARATOR_RE.match(lines[table_end].strip())
            ):
                if _METADATA_TABLE_LINE_RE.match(lines[table_end].strip()):
                    label_count += 1
                table_end += 1

            if label_count >= _MIN_LABEL_ROWS_FOR_TABLE_STRIP:
                for j in range(table_start, table_end):
                    to_remove.add(j)
                i = table_end
                continue

        if lines[i].strip().startswith("#"):
            break

        i += 1

    if not to_remove:
        return md

    new_lines = [ln for j, ln in enumerate(lines) if j not in to_remove]
    return front + "\n".join(new_lines)


@dataclass(frozen=True)
class _RawConversion:
    """Internal shape returned by :func:`_convert_with_tomd_full`."""

    md: str
    prompts: list[str] | None
    images: list[ExtractedImage]
    source_image_count: int
    images_truncated: bool
    skipped: bool
    skip_reason: SkipReason | None
    source_raster_count: int = 0
    source_vector_count: int = 0
    summary: dict | None = None


def _convert_with_tomd_full(
    path: Path,
    *,
    html_images_manifest=None,
    extract_vector: bool = False,
    whiteout_text: bool = False,
) -> _RawConversion:
    """Dispatch by file suffix, returning the full pipeline output.

    For PDF sources, routes through :func:`run_pipeline` so the caller
    has access to the extracted image bytes alongside the markdown.
    For HTML sources with a manifest, runs the HTML renderer (which
    never emits image syntax into the markdown, #408) and surfaces the
    ExtractedImage list (bytes already on disk from mailing - they
    aren't re-persisted by the convert stage).

    ``extract_vector`` and ``whiteout_text`` are PDF-only and forwarded
    to :func:`tomd.lib.pdf.run_pipeline`. They are accepted in the HTML
    branch but ignored, so a CLI flag does not have to know the source
    format up front.
    """
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        r = run_pipeline(
            path,
            extract_vector=extract_vector,
            whiteout_text=whiteout_text,
        )
        raster = sum(1 for im in r.images if im.source == "raster")
        vector = sum(1 for im in r.images if im.source == "vector")
        return _RawConversion(
            md=r.md,
            prompts=r.prompts,
            images=list(r.images),
            source_image_count=r.source_image_count,
            images_truncated=r.images_truncated,
            skipped=r.skipped,
            skip_reason=r.skip_reason,
            source_raster_count=raster,
            source_vector_count=vector,
            summary=r.summary,
        )
    if suffix in (".html", ".htm"):
        html_result = None
        if html_images_manifest is not None:
            html_result = load_html_images(html_images_manifest)
        md, prompts = convert_html(path, html_images_result=html_result)
        if html_result is None:
            return _RawConversion(
                md=md,
                prompts=prompts,
                images=[],
                source_image_count=0,
                images_truncated=False,
                skipped=False,
                skip_reason=None,
            )
        return _RawConversion(
            md=md,
            prompts=prompts,
            images=list(html_result.images),
            source_image_count=html_result.source_image_count,
            images_truncated=html_result.images_truncated,
            skipped=False,
            skip_reason=None,
        )
    raise UnsupportedSourceFormatError(
        f"Unsupported source format {suffix!r} for {path.name}; "
        f"expected .pdf, .html, or .htm"
    )


def _extract_intent_from_front_matter(md: str) -> str:
    """Return the ``intent`` value from the markdown YAML front matter, or ``""``."""
    intent = parse_front_matter(md).get("intent", "")
    return intent if isinstance(intent, str) else ""


def convert_paper_full(
    paper_id: str,
    source_path: Path,
    meta: dict,
    *,
    html_images_manifest=None,
    extract_vector: bool = False,
    whiteout_text: bool = False,
) -> ConvertedPaper:
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
    raw = _convert_with_tomd_full(
        source_path,
        html_images_manifest=html_images_manifest,
        extract_vector=extract_vector,
        whiteout_text=whiteout_text,
    )

    if raw.prompts:
        logger.warning(
            "tomd [%s] flagged %d uncertain region(s)",
            paper_id,
            len(raw.prompts),
        )

    if raw.skipped:
        return ConvertedPaper.skipped_from(
            PipelineResult(
                md="",
                prompts=raw.prompts,
                skipped=True,
                skip_reason=raw.skip_reason,
            )
        )

    if not raw.md or not raw.md.strip():
        raise RuntimeError(
            f"tomd produced empty markdown for {paper_id} "
            f"({source_path.suffix.lower()} source; not a typed skip)."
        )

    md = _normalize_front_matter(raw.md, meta)
    md = _strip_body_metadata_text(md)
    md = strip_freeform_metadata_lines(md, metadata=meta)

    # Re-run H1 stripping: leaked metadata before the H1 may have
    # blocked strip_leading_h1 in the emit layer.
    title = parse_front_matter(md).get("title")
    if isinstance(title, str) and title:
        md = apply_strip_leading_h1(md, title)

    md = _strip_toc(md)
    # the rewrites above shift lines: point uncertainty markers at their text again
    md = renumber_uncertain_markers(md)

    extracted_intent = _extract_intent_from_front_matter(md)
    return ConvertedPaper(
        markdown=md,
        prompts=raw.prompts,
        intent=extracted_intent,
        images=raw.images,
        source_image_count=raw.source_image_count,
        images_truncated=raw.images_truncated,
        skipped=False,
        skip_reason=None,
        source_raster_count=raw.source_raster_count,
        source_vector_count=raw.source_vector_count,
        summary=raw.summary,
    )


def convert_paper(
    paper_id: str,
    source_path: Path,
    meta: dict,
) -> tuple[str, list[str] | None, str]:
    """Convert a staged source file to markdown. Pure: no database or
    filesystem writes.

    Thin wrapper over :func:`convert_paper_full` that returns the
    historical ``(markdown, prompts, extracted_intent)`` triple. New
    callers that need the extracted image data should call
    :func:`convert_paper_full` directly.

    Raises:
        RuntimeError: tomd produced no usable markdown.
    """
    r = convert_paper_full(paper_id, source_path, meta)
    if r.skipped:
        raise RuntimeError(
            f"tomd produced empty markdown for {paper_id} "
            f"({r.skip_reason.value if r.skip_reason else 'slide deck, standards draft, or unreadable source'})."
        )
    return r.markdown, r.prompts, r.intent
