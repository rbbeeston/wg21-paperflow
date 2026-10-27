#
# Copyright (c) 2026 Sergio DuBois (sentientsergio@gmail.com)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
#
# Official repository: https://github.com/cppalliance/wg21-paperflow
#

"""Batch job library for the paperflow pipeline.

Each ``run_*`` function is ``async def`` and returns a result dict with
``succeeded``, ``failed``, and ``skipped`` lists. Workers are coroutines
that return plain result dicts - they never touch the storage backend.
CPU-bound work (tomd conversion) uses ``asyncio.to_thread``. The main coroutine
receives each result via ``asyncio.as_completed`` and writes to the
backend serially, avoiding any SQLite concurrency issues.

Stages: mailing, download, convert. Command modules call
``asyncio.run(jobs.run_*(...))``.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import httpx

from cli.errors import EmptyTargetsError, MixedTargetsError
from cli.models import Paper
from cli.orchestrator import convert_one_paper
from cli.targets import MONTH_RE, resolve_pid
from mailing.download import content_length, default_client, download_paper
from mailing.scrape import discover_years, fetch_all_mailings_for_year
from paperstore import parse_authors_raw
from paperstore.backend import PaperRow, StorageBackend
from paperstore.errors import (
    MissingMailingIndexError,
    MissingPaperMdError,
    MissingSourceError,
)
from paperstore.progress import ProgressCallback, ProgressEvent
from tomd.lib.batch import (
    format_batch_finished,
    format_batch_progress_line,
    format_batch_timeout,
)
from tomd.lib.check_content import (
    format_content_check_report,
    run_content_check_batch,
    write_content_check_json_atomic,
)
from tomd.lib.pdf import SkipReason

logger = logging.getLogger(__name__)

_SKIP_REASON_MAP: dict[SkipReason, str] = {
    SkipReason.EMPTY_PDF: "empty_pdf",
    SkipReason.SLIDE_DECK: "slide_deck",
    SkipReason.STANDARDS_DRAFT: "standards_draft",
    SkipReason.UNREADABLE: "unreadable",
}

MAILING_EARLIEST_YEAR = 2011
DEFAULT_DOWNLOAD_CONCURRENCY = 8


# ---------------------------------------------------------------------------
# Target resolution helpers
# ---------------------------------------------------------------------------


def _validate_targets(targets: list[str]) -> str:
    """Return the target type: 'all', 'years', or 'papers'.

    Raises :class:`EmptyTargetsError` if targets are empty, or
    :class:`MixedTargetsError` if years and paper IDs are mixed.
    """
    if not targets:
        raise EmptyTargetsError("At least one target is required.")
    if targets == ["all"]:
        return "all"
    # Check all are years (4 digits) or all are paper IDs.
    are_years = [t.isdigit() and len(t) == 4 for t in targets]
    if all(are_years):
        return "years"
    if not any(are_years):
        return "papers"
    raise MixedTargetsError(
        "Cannot mix years and paper IDs in one command. " f"Got: {targets!r}"
    )


def _papers_from_scope(
    targets: list[str], target_type: str, backend: StorageBackend
) -> list[PaperRow]:
    """Return paper rows matching the scope, without idempotency filtering."""
    if target_type == "all":
        ids = backend.list_all_paper_ids()
        rows = []
        for pid in ids:
            result = backend.resolve_year_for_paper(pid)
            if result:
                _, row = result
                rows.append(row)
        return rows
    if target_type == "years":
        rows = []
        for year in targets:
            try:
                rows.extend(backend.list_papers_for_year(year))
            except MissingMailingIndexError:
                logger.warning(
                    "No papers found for year %s; run 'paperflow mailing %s' first.",
                    year,
                    year,
                )
        return rows
    # paper IDs
    rows = []
    for pid in targets:
        result = backend.resolve_year_for_paper(pid.upper())
        if result is None:
            logger.warning("Paper %s not found in database.", pid)
        else:
            _, row = result
            rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# run_mailing
# ---------------------------------------------------------------------------


async def run_mailing(
    targets: list[str],
    backend: StorageBackend,
    *,
    current_year: str | None = None,
    force: bool = False,
    on_progress: ProgressCallback | None = None,
) -> dict:
    """Scrape mailing indexes from open-std.org and store in the backend.

    ``targets`` is a list of year strings, or ``["all"]``. Past years
    where ``backend.has_year(year)`` is True are skipped; the current year
    is always re-fetched. Pass ``force=True`` to bypass the skip and
    re-fetch every requested year. ``upsert_year`` preserves
    ``source_file`` and ``markdown_path``, so a forced re-fetch only
    updates mailing metadata (title, authors, url, dates) without touching
    downloaded sources or converted markdown.
    """
    if current_year is None:
        current_year = str(datetime.now(timezone.utc).year)

    target_type = _validate_targets(targets)

    if target_type == "all":
        all_years = discover_years()
        years = sorted(
            y for y in all_years if int(y) >= MAILING_EARLIEST_YEAR
        )
    else:
        years = sorted(targets)

    succeeded = []
    skipped = []
    failed = []
    total_years = len(years)

    for i, year in enumerate(years):
        if on_progress is not None:
            try:
                on_progress(
                    ProgressEvent(
                        step=i,
                        total=total_years,
                        name=f"Mailing {year}",
                        pct=i / total_years if total_years else 1.0,
                    )
                )
            except Exception:
                logger.warning("on_progress hook raised; disabling", exc_info=True)
                on_progress = None

        if not force and year < current_year and backend.has_year(year):
            skipped.append(year)
        else:
            try:
                all_mailings = await asyncio.to_thread(fetch_all_mailings_for_year, year)
                for mailing_id, papers in sorted(all_mailings.items()):
                    backend.upsert_year(year, papers)
                total = len(backend.list_papers_for_year(year))
                succeeded.append({"year": year, "papers": total})
            except Exception as exc:
                logger.exception("Failed to fetch year %s", year)
                failed.append({"year": year, "error": str(exc)})

        if on_progress is not None:
            try:
                on_progress(
                    ProgressEvent(
                        step=i + 1,
                        total=total_years,
                        name=f"Mailing {year}",
                        pct=(i + 1) / total_years if total_years else 1.0,
                    )
                )
            except Exception:
                logger.warning("on_progress hook raised; disabling", exc_info=True)
                on_progress = None

    if on_progress is not None:
        try:
            on_progress(
                ProgressEvent(
                    step=total_years,
                    total=total_years,
                    name="done",
                    pct=1.0,
                )
            )
        except Exception:
            pass

    return {"succeeded": succeeded, "skipped": skipped, "failed": failed}


# ---------------------------------------------------------------------------
# run_download
# ---------------------------------------------------------------------------


async def run_download(
    targets: list[str],
    backend: StorageBackend,
    *,
    force: bool = False,
    verify: bool = False,
    concurrency: int = DEFAULT_DOWNLOAD_CONCURRENCY,
    on_progress: ProgressCallback | None = None,
) -> dict:
    """Download source files for papers. Workers are async httpx calls.

    ``on_progress`` is invoked after each task completion with a
    :class:`~paperstore.progress.ProgressEvent`.
    """
    concurrency = max(1, concurrency)
    target_type = _validate_targets(targets)
    all_papers = _papers_from_scope(targets, target_type, backend)

    # Apply idempotency filter via SQL-equivalent: exclude already-downloaded.
    if not force:
        to_process = [p for p in all_papers if not p.source_file]
    else:
        to_process = [p for p in all_papers if p.url]

    total = len(to_process)
    semaphore = asyncio.Semaphore(concurrency)

    async with default_client() as http:

        async def _one(paper: PaperRow) -> dict:
            pid = paper.paper_id
            url = paper.url
            if not url:
                return {"paper_id": pid, "status": "skipped", "reason": "no_url"}
            async with semaphore:
                if verify and paper.source_file:
                    cl = await content_length(url, client=http)
                    if cl is not None:
                        try:
                            source_path = backend.get_source_path(pid)
                            existing_size = source_path.stat().st_size
                        except (MissingSourceError, FileNotFoundError):
                            existing_size = None
                        if existing_size == cl:
                            return {
                                "paper_id": pid,
                                "status": "skipped",
                                "reason": "verified_match",
                            }
                try:
                    fetched = await download_paper(pid, source_url=url, client=http)
                    if fetched is None:
                        return {
                            "paper_id": pid,
                            "status": "skipped",
                            "reason": "no_url",
                        }
                    content, suffix = fetched
                    return {
                        "paper_id": pid,
                        "content": content,
                        "suffix": suffix,
                        "status": "ok",
                    }
                except httpx.HTTPStatusError as exc:
                    logger.error(
                        "%s: HTTP %d %s",
                        pid,
                        exc.response.status_code,
                        exc.response.reason_phrase,
                    )
                    return {"paper_id": pid, "status": "error", "error": str(exc)}
                except Exception as exc:
                    logger.exception("Download failed for %s", pid)
                    return {"paper_id": pid, "status": "error", "error": str(exc)}

        tasks = [asyncio.create_task(_one(p)) for p in to_process]
        succeeded = []
        failed = []
        to_process_ids = {p.paper_id for p in to_process}
        skipped_papers = [
            {
                "paper_id": p.paper_id,
                "reason": "no_url" if not p.url else "already_staged",
            }
            for p in all_papers
            if p.paper_id not in to_process_ids
        ]

        completed = 0
        for coro in asyncio.as_completed(tasks):
            result = await coro
            if result["status"] == "ok":
                backend.put_source(
                    result["paper_id"], result["content"], suffix=result["suffix"]
                )
                succeeded.append(result["paper_id"])
            elif result["status"] == "skipped":
                skipped_papers.append(result)
            else:
                failed.append(result)
            completed += 1
            if on_progress is not None:
                try:
                    on_progress(
                        ProgressEvent(
                            step=completed,
                            total=total,
                            name=result["paper_id"],
                            pct=completed / total if total else 1.0,
                        )
                    )
                except Exception:
                    logger.warning("on_progress hook raised; disabling", exc_info=True)
                    on_progress = None

    return {"succeeded": succeeded, "skipped": skipped_papers, "failed": failed}


# ---------------------------------------------------------------------------
# run_convert
# ---------------------------------------------------------------------------


async def run_convert(
    targets: list[str],
    backend: StorageBackend,
    *,
    force: bool = False,
    concurrency: int = 4,
    write_prompts: bool = True,
    extract_vector: bool = False,
    whiteout_text: bool = False,
    on_progress: ProgressCallback | None = None,
) -> dict:
    """Convert staged source files to markdown. Workers run in threads.

    ``write_prompts`` controls whether the ``<pid>.prompts.json``
    intermediate is persisted (default True). Set False from CLI flows
    that explicitly opt out via ``--no-prompts``.

    ``extract_vector`` and ``whiteout_text`` are forwarded to the tomd
    PDF pipeline via :func:`convert_one_paper`. Default off; opting
    in extracts vector figures (path-operator clusters) as PNGs
    alongside raster images.

    ``on_progress`` is invoked after each task completion with a
    :class:`~paperstore.progress.ProgressEvent`.
    """
    concurrency = max(1, concurrency)
    target_type = _validate_targets(targets)
    all_papers = _papers_from_scope(targets, target_type, backend)

    if not force:
        to_process = [p for p in all_papers if p.source_file and not p.markdown_path]
    else:
        to_process = [p for p in all_papers if p.source_file]

    total = len(to_process)
    semaphore = asyncio.Semaphore(concurrency)

    def _make_paper(row: PaperRow) -> Paper:
        authors = parse_authors_raw(row.authors or [])
        return Paper(
            document_id=row.paper_id,
            year=row.year,
            title=row.title,
            authors=authors,
            mailing_date=row.mailing_date,
            document_date=row.document_date,
            audience=row.target_group,
            intent=row.intent,
            url=row.url,
            source_file=row.source_file,
            markdown_path=row.markdown_path,
        )

    in_flight: set[str] = set()

    async def _one(paper_row: PaperRow) -> dict:
        pid = paper_row.paper_id
        async with semaphore:
            in_flight.add(pid)
            try:
                paper = _make_paper(paper_row)
                # Worker reads the source but does no backend writes;
                # the main coroutine persists through the backend below.
                result = await asyncio.wait_for(
                    asyncio.to_thread(
                        convert_one_paper,
                        paper,
                        extract_vector=extract_vector,
                        whiteout_text=whiteout_text,
                    ),
                    timeout=120,
                )
                if result.status == "skipped":
                    if result.skip_reason is None:
                        logger.error(
                            "Skipping %s: status=skipped but skip_reason is missing",
                            pid,
                        )
                        return {
                            "paper_id": pid,
                            "status": "error",
                            "error": "missing skip_reason",
                        }
                    bucket = _SKIP_REASON_MAP[result.skip_reason]
                    logger.warning("Skipping %s: %s", pid, result.skip_reason)
                    return {
                        "paper_id": pid,
                        "status": "skipped",
                        "reason": bucket,
                    }
                return {
                    "paper_id": pid,
                    "markdown": result.markdown,
                    "prompts": result.prompts,
                    "intent": result.intent,
                    "title": result.title,
                    "images": result.images,
                    "summary": result.summary,
                    "status": "ok",
                }
            except RuntimeError as exc:
                msg = str(exc)
                logger.exception("Convert failed for %s", pid)
                return {"paper_id": pid, "status": "error", "error": msg}
            except TimeoutError:
                logger.warning("Skipping %s: conversion timed out (120s)", pid)
                return {"paper_id": pid, "status": "skipped", "reason": "timeout"}
            except Exception as exc:
                logger.exception("Convert failed for %s", pid)
                return {"paper_id": pid, "status": "error", "error": str(exc)}
            finally:
                in_flight.discard(pid)

    tasks = [asyncio.create_task(_one(p)) for p in to_process]
    succeeded = []
    failed = []
    to_process_ids = {p.paper_id for p in to_process}
    skipped = [
        {"paper_id": p.paper_id, "reason": "already_converted"}
        for p in all_papers
        if p.paper_id not in to_process_ids
    ]

    completed = 0
    for coro in asyncio.as_completed(tasks):
        result = await coro
        if result["status"] == "ok":
            pid = result["paper_id"]
            # Persist extracted images first so the markdown's image
            # references resolve when a reader opens the file. Mirrors
            # the delete-then-write rebuild in pipeline._stage_convert.
            pdf_images = [img for img in result.get("images", []) if img.bytes]
            if pdf_images:
                backend.delete_paper_images(pid)
                for img in pdf_images:
                    backend.write_paper_image(
                        pid,
                        img.page,
                        img.index_on_page,
                        img.ext,
                        img.bytes,
                    )
            md_path = backend.write_paper_md(pid, result["markdown"])
            if write_prompts and result["prompts"]:
                backend.write_intermediate(pid, "prompts", result["prompts"])
            if result.get("summary") is not None:
                backend.write_intermediate(pid, "summary", result["summary"])
            backend.record_markdown(pid, md_path, intent=result["intent"])
            succeeded.append(pid)
        elif result["status"] == "skipped":
            skipped.append(result)
        else:
            failed.append(result)
        completed += 1
        if on_progress is not None:
            try:
                on_progress(
                    ProgressEvent(
                        step=completed,
                        total=total,
                        name=next(iter(in_flight)) if in_flight else result["paper_id"],
                        pct=completed / total if total else 1.0,
                    )
                )
            except Exception:
                logger.warning("on_progress hook raised; disabling", exc_info=True)
                on_progress = None

    return {"succeeded": succeeded, "skipped": skipped, "failed": failed}


# ---------------------------------------------------------------------------
# run_citations
# ---------------------------------------------------------------------------


async def run_citations(
    targets: list[str],
    backend: StorageBackend,
    *,
    force: bool = False,
    on_progress: ProgressCallback | None = None,
) -> dict:
    """Extract WG21 paper-id citations from converted markdown.

    Pure-Python: calls ``paperstore.citations.extract_citations`` per paper
    and writes the resulting edges to ``paper_citations`` via
    :meth:`StorageBackend.store_paper_citations`. Self-citations (paper
    cites its own exact paper_id) are dropped; revision self-references
    (e.g. P1234R3 citing P1234R1) are kept -- they're meaningful edges.

    ``force=False`` skips papers where ``citations_extracted_at`` is already
    set, matching the artifact-sentinel convention used by ``run_convert``
    (which gates on ``markdown_path``). This correctly settles zero-citation
    papers: extraction was attempted and produced no rows, but the stamp is
    still written, so subsequent runs skip them without re-processing.
    """
    from paperstore.citations import extract_citations

    target_type = _validate_targets(targets)
    all_papers = _papers_from_scope(targets, target_type, backend)

    to_process: list[PaperRow] = []
    skipped: list[dict] = []
    for p in all_papers:
        if not p.markdown_path:
            skipped.append({"paper_id": p.paper_id, "reason": "no_markdown"})
            continue
        if not force and p.citations_extracted_at:
            skipped.append({"paper_id": p.paper_id, "reason": "already_extracted"})
            continue
        to_process.append(p)

    total = len(to_process)
    succeeded: list[str] = []
    failed: list[dict] = []

    for i, paper in enumerate(to_process):
        pid = paper.paper_id
        try:
            md = backend.get_paper_md(pid)
            refs = extract_citations(md)
            # Drop self-citations (exact paper_id match, case-insensitive).
            # CitationRef.paper_id is already upper-cased by extract_citations.
            pid_upper = pid.upper()
            refs = [r for r in refs if r.paper_id != pid_upper]
            backend.store_paper_citations(pid, refs)
            succeeded.append(pid)
        except MissingPaperMdError:
            skipped.append({"paper_id": pid, "reason": "no_markdown"})
        except Exception as exc:
            logger.exception("Citation extraction failed for %s", pid)
            failed.append({"paper_id": pid, "error": str(exc)})

        if on_progress is not None:
            try:
                on_progress(
                    ProgressEvent(
                        step=i + 1,
                        total=total,
                        name=pid,
                        pct=(i + 1) / total if total else 1.0,
                    )
                )
            except Exception:
                logger.warning("on_progress hook raised; disabling", exc_info=True)
                on_progress = None

    return {"succeeded": succeeded, "skipped": skipped, "failed": failed}


# ---------------------------------------------------------------------------
# run_content_check
# ---------------------------------------------------------------------------

_CONTENT_CHECK_TIMEOUT = 120


def _rows_for_content_check_targets(
    targets: list[str],
    backend: StorageBackend,
) -> list[PaperRow]:
    """Resolve CLI targets (paper id, year, year-month) to paper rows.

    Mirrors the dispatch in :func:`cli._process.run_process_command` so
    every target shape `paperflow convert` advertises (paper id, year,
    year-month) reaches :func:`run_content_check`. The older
    :func:`_papers_from_scope` predates year-month targets.
    """
    seen: set[str] = set()
    rows: list[PaperRow] = []

    def _add(row: PaperRow) -> None:
        if row.paper_id in seen:
            return
        seen.add(row.paper_id)
        rows.append(row)

    for target in targets:
        if MONTH_RE.match(target):
            for row in backend.list_papers_since(target):
                _add(row)
        elif target.isdigit() and len(target) == 4:
            try:
                for row in backend.list_papers_for_year(target):
                    _add(row)
            except MissingMailingIndexError:
                logger.warning(
                    "No papers found for year %s; run 'paperflow mailing' first.",
                    target,
                )
        else:
            pid = resolve_pid(target, backend)
            result = backend.resolve_year_for_paper(pid)
            if result is None:
                logger.warning("Paper %s not found in database.", target)
                continue
            _add(result[1])

    return rows


def _make_stderr_progress() -> ProgressCallback:
    """Build a progress handler that writes batch lines to stderr."""
    t0 = time.monotonic()

    def handler(event: ProgressEvent) -> None:
        line = format_batch_progress_line(
            event.step,
            event.total,
            event.name,
            t0,
        )
        print(line, end="", file=sys.stderr)
        sys.stderr.flush()

    return handler


def run_content_check(
    targets: list[str],
    backend: StorageBackend,
    *,
    json_path: Path | None = None,
    workers: int = 1,
    timeout: int = _CONTENT_CHECK_TIMEOUT,
) -> dict:
    """Compare source text against converted markdown for the given targets.

    Synchronous. ``run_content_check_batch`` does its own
    ``ProcessPoolExecutor`` parallelism; workers re-open the backend
    from the workspace path. Skips papers missing either source or
    markdown.
    """
    workers = max(1, workers)
    rows = _rows_for_content_check_targets(targets, backend)

    items: list[tuple[str, Path]] = []
    skipped: list[dict] = []
    workspace_dir = backend.workspace_dir
    for row in rows:
        pid = row.paper_id
        if not row.source_file:
            skipped.append({"paper_id": pid, "reason": "no_source"})
            continue
        if not row.markdown_path:
            skipped.append({"paper_id": pid, "reason": "no_markdown"})
            continue
        items.append((pid, workspace_dir))

    if not items:
        return {"succeeded": [], "skipped": skipped, "failed": []}

    batch = run_content_check_batch(
        items,
        workers=workers,
        timeout=timeout,
        on_progress=_make_stderr_progress(),
    )

    if batch.timed_out:
        print(
            format_batch_timeout(batch.timed_out, timeout),
            file=sys.stderr,
        )
    print(
        format_batch_finished(batch.elapsed_sec, len(items)),
        file=sys.stderr,
    )
    print(
        format_content_check_report(
            batch.results,
            batch.skipped,
            batch.errors,
        ),
        end="",
    )
    if json_path is not None:
        write_content_check_json_atomic(json_path, batch.results)
        print(f"\nDetailed metrics written to {json_path}")

    failed = [{"paper_id": pid, "reason": msg} for pid, msg in batch.errors]

    failed_ids = {entry["paper_id"] for entry in failed}

    return {
        "succeeded": [pid for pid, _ in items if pid not in failed_ids],
        "skipped": skipped,
        "failed": failed,
    }


# ---------------------------------------------------------------------------
# run_full
# ---------------------------------------------------------------------------


def _labeled_progress(
    label: str, callback: ProgressCallback | None,
) -> ProgressCallback | None:
    """Prefix progress events with a pipeline stage label (for ``run_full``)."""
    if callback is None:
        return None

    prefix = f"{label} "

    def handler(ev: ProgressEvent) -> None:
        name = ev.name
        if name == "done":
            name = label
        elif not name.startswith(prefix):
            name = f"{prefix}{name}"
        callback(
            ProgressEvent(
                step=ev.step,
                total=ev.total,
                name=name,
                pct=ev.pct,
            )
        )

    return handler


StageCompleteCallback = Callable[[str, dict | None], None]


async def run_full(
    targets: list[str],
    backend: StorageBackend,
    *,
    force: bool = False,
    verify: bool = False,
    concurrency: int = DEFAULT_DOWNLOAD_CONCURRENCY,
    extract_vector: bool = False,
    whiteout_text: bool = False,
    current_year: str | None = None,
    on_progress: ProgressCallback | None = None,
    on_stage_complete: StageCompleteCallback | None = None,
) -> dict:
    """Chain mailing, download, convert, and citation extraction.

    Mailing runs only when ``targets`` are years or ``["all"]``. For
    paper-ID targets, mailing is skipped entirely; if
    ``on_stage_complete`` is set, it is called with
    ``("mailing", None)`` to signal that the stage did not run.

    Download and convert always run. Convert uses ``concurrency // 2``
    workers (minimum 1). ``extract_vector`` and ``whiteout_text`` are
    forwarded to :func:`run_convert`.

    Citation extraction runs after convert. Failures there are recorded
    in the returned ``"citations"`` aggregate but do not discard earlier
    stage results.

    Returns a dict with ``"download"``, ``"convert"``, and
    ``"citations"`` keys, plus ``"mailing"`` when that stage ran. Each
    stage value is a ``{"succeeded", "skipped", "failed"}`` aggregate.

    ``on_progress`` receives stage-prefixed
    :class:`~paperstore.progress.ProgressEvent` objects (e.g.
    ``"Mailing 2026"``, ``"Downloading P1000R0"``).
    ``on_stage_complete(stage, result)`` is invoked after each of
    mailing, download, and convert; ``result=None`` means the stage was
    not executed.
    """
    target_type = _validate_targets(targets)

    # Determine years for mailing stage.
    if target_type == "years":
        mailing_targets = targets
    elif target_type == "all":
        mailing_targets = ["all"]
    else:
        # Paper IDs: derive years from what's in the DB (or skip mailing stage).
        mailing_targets = None

    results = {}

    if mailing_targets is not None:
        results["mailing"] = await run_mailing(
            mailing_targets, backend,
            current_year=current_year,
            force=force,
            on_progress=_labeled_progress("Mailing", on_progress),
        )
        if on_stage_complete is not None:
            on_stage_complete("mailing", results["mailing"])
    elif on_stage_complete is not None:
        on_stage_complete("mailing", None)

    results["download"] = await run_download(
        targets, backend,
        force=force,
        verify=verify,
        concurrency=concurrency,
        on_progress=_labeled_progress("Downloading", on_progress),
    )
    if on_stage_complete is not None:
        on_stage_complete("download", results["download"])

    results["convert"] = await run_convert(
        targets, backend,
        force=force,
        concurrency=(concurrency // 2) or 1,
        extract_vector=extract_vector,
        whiteout_text=whiteout_text,
        on_progress=_labeled_progress("Converting", on_progress),
    )
    if on_stage_complete is not None:
        on_stage_complete("convert", results["convert"])
    # Citation extraction is an enrichment step over the converted markdown;
    # don't let a failure here mask convert success in the result aggregate.
    try:
        results["citations"] = await run_citations(targets, backend, force=force)
    except Exception as exc:
        logger.exception("run_citations failed; convert results unaffected")
        results["citations"] = {
            "succeeded": [],
            "skipped": [],
            "failed": [{"paper_id": "*", "error": str(exc)}],
        }

    return results
