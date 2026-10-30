#
# Copyright (c) 2026 Dmitriy Chukhin (dmitriy@lincolnloop.com)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
#
# Official repository: https://github.com/cppalliance/wg21-paperflow
#

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

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from paperstore.html_manifest import HtmlImagesManifest

from tomd.domain.image import ExtractedImage
from tomd.lib.pdf.images import _MAX_IMAGES_PER_PAPER


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
    entries = sorted(manifest.entries, key=lambda e: e.document_order)
    source_image_count = len(entries)
    truncated = source_image_count > _MAX_IMAGES_PER_PAPER
    kept = entries[:_MAX_IMAGES_PER_PAPER] if truncated else entries

    images: list[ExtractedImage] = []
    for entry in kept:
        alt = entry.caption_text or entry.alt_attr or ""
        ext = Path(entry.stored_filename).suffix.lstrip(".").lower() or "bin"
        images.append(ExtractedImage(
            page=0,
            index_on_page=entry.document_order,
            ext=ext,
            bytes=b"",
            bbox=(0.0, 0.0, 0.0, 0.0),
            suggested_alt=alt,
            stored_filename=entry.stored_filename,
            xref=0,
        ))

    return HtmlImagesResult(
        images=images,
        source_image_count=source_image_count,
        images_truncated=truncated,
    )
