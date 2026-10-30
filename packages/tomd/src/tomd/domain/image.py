"""
Distributed under the Boost Software License, Version 1.0. (See accompanying

file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)

Official repository: https://github.com/cppalliance/wg21-paperflow
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ImageSource = Literal["raster", "vector"]


@dataclass(frozen=True)
class ExtractedImage:
    """Extracted sidecar image record shared by the PDF and HTML paths.

    PDF populates every field from ``pymupdf`` extraction; HTML populates
    from ``HtmlImagesManifest`` with sentinels ``page=0``, ``bytes=b""``
    (already persisted by mailing, so ``cli`` skips re-writing when ``bytes``
    is empty), ``bbox=(0.0, 0.0, 0.0, 0.0)``, and ``xref=0``.
    ``caption_body_dropped`` is True only when the PDF pipeline dropped the
    body caption section, gating italic caption re-emission (#408).
    """

    page: int
    index_on_page: int
    ext: str
    bytes: bytes
    bbox: tuple[float, float, float, float]
    suggested_alt: str
    stored_filename: str
    xref: int
    source: ImageSource = "raster"
    sub_captions: tuple[tuple[str, str], ...] = ()
    caption_body_dropped: bool = False
