"""
Distributed under the Boost Software License, Version 1.0. (See accompanying

file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)

Official repository: https://github.com/cppalliance/wg21-paperflow
"""

from __future__ import annotations

from tomd.domain.diagnostics import (
    Diagnostics,
    GlyphPassStats,
    VectorUncertaintyStats,
)
from tomd.lib.pdf.glyphs import (
    GLYPH_PLACEHOLDER_MARKER_TEMPLATE,
    UNKNOWN_GLYPH,
)
from tomd.lib.pdf.images import TRUNCATION_MARKER_TEMPLATE
from tomd.lib.pdf.vector_images import (
    format_uncertainty_marker,
    should_emit_marker,
)


def _render_truncation_marker(
    diagnostics: Diagnostics,
    kept_image_count: int,
) -> str:
    dropped = diagnostics.dropped_image_count(kept_image_count)
    if dropped <= 0:
        return ""
    return TRUNCATION_MARKER_TEMPLATE.format(
        kept=kept_image_count,
        total=diagnostics.source_image_count,
        dropped=dropped,
    )


def _render_vector_uncertainty_marker(
    stats: VectorUncertaintyStats | None,
) -> str:
    if stats is None or not should_emit_marker(stats):
        return ""
    return format_uncertainty_marker(stats)


def _render_glyph_placeholder_marker(
    stats: GlyphPassStats | None,
    body_md: str,
) -> str:
    if stats is None:
        return ""
    present = body_md.count(UNKNOWN_GLYPH)
    if not stats.should_emit_marker(present):
        return ""
    return GLYPH_PLACEHOLDER_MARKER_TEMPLATE.format(
        placeholders=present,
        skipped_coincident=stats.skipped_coincident,
        skipped_code_section=stats.skipped_code_section,
    )


def append_trailer_markers(
    body_md: str,
    diagnostics: Diagnostics,
    *,
    kept_image_count: int,
) -> str:
    """Append trailing HTML-comment markers in legacy order: truncation, vector, glyph."""
    markers = [
        marker
        for marker in (
            _render_truncation_marker(diagnostics, kept_image_count),
            _render_vector_uncertainty_marker(diagnostics.vector_uncertainty),
            _render_glyph_placeholder_marker(diagnostics.glyph_stats, body_md),
        )
        if marker
    ]
    if not markers:
        return body_md
    base = body_md.rstrip()
    parts = [base, *markers] if base else markers
    return "\n\n".join(parts) + "\n"
