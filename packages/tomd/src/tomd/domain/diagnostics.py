"""
Distributed under the Boost Software License, Version 1.0. (See accompanying

file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)

Official repository: https://github.com/cppalliance/wg21-paperflow
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class VectorUncertaintyStats:
    """Per-paper accounting of the vector-extraction filter pipeline.

    ``reasons`` maps filter reason keys from the closed ``ALLOWED_REASON_KEYS``
    set to non-negative drop counts.
    """

    pages_scanned: int
    candidates: int
    kept: int
    rejected: int
    reasons: Mapping[str, int]
    pages_skipped: int


@dataclass
class GlyphPassStats:
    """Per-paper accounting for the glyph-placeholder pass.

    ``free_standing`` and ``skipped_code_section`` are subsets of ``injected``;
    ``skipped_coincident`` is disjoint from ``injected``.
    """

    injected: int = 0
    skipped_coincident: int = 0
    free_standing: int = 0
    skipped_code_section: int = 0

    @property
    def fired(self) -> bool:
        """True if the pass produced anything worth logging."""
        return (
            self.injected
            + self.skipped_coincident
            + self.free_standing
            + self.skipped_code_section
        ) > 0

    def should_emit_marker(self, present: int) -> bool:
        """True when surviving body placeholders or skipped counts warrant a trailer marker."""
        return (
            present
            + self.skipped_coincident
            + self.skipped_code_section
        ) > 0


@dataclass(frozen=True)
class Diagnostics:
    """Per-paper conversion diagnostics and trailer-marker inputs."""

    images_truncated: bool = False
    source_image_count: int = 0
    vector_uncertainty: VectorUncertaintyStats | None = None
    glyph_stats: GlyphPassStats | None = None
    extra_prompts: tuple[str, ...] = ()

    def dropped_image_count(self, kept_image_count: int) -> int:
        """Return number of truncated images to disclose, or 0 when not truncated."""
        if not self.images_truncated or self.source_image_count <= 0:
            return 0
        return max(self.source_image_count - kept_image_count, 0)
