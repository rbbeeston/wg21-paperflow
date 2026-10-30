"""
Distributed under the Boost Software License, Version 1.0. (See accompanying

file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)

Official repository: https://github.com/cppalliance/wg21-paperflow
"""

from __future__ import annotations

import pytest

from tomd.domain.diagnostics import (
    Diagnostics,
    GlyphPassStats,
    VectorUncertaintyStats,
)
from tomd.domain.document import PaperDocument
from tomd.domain.elements import Confidence, Paragraph
from tomd.domain.image import ExtractedImage
from tomd.domain.metadata import PaperMetadata
from tomd.lib.pdf.emit import emit_markdown
from tomd.lib.pdf.glyphs import UNKNOWN_GLYPH
from tomd.lib.pdf.types import Line, Section, SectionKind, Span as PdfSpan
from tomd.writers.markdown import MarkdownWriter, append_trailer_markers

_META_DICT = {"title": "Marker Twin Test", "document": "P9999R0"}
_PAPER_META = PaperMetadata(title="Marker Twin Test", document="P9999R0")


def _pdf_paragraph_section(text: str) -> Section:
    line = Line(spans=[PdfSpan(text=text, font_name="Body", font_size=11.0)])
    return Section(
        kind=SectionKind.PARAGRAPH,
        text=text,
        confidence=Confidence.HIGH,
        lines=[line],
    )


def _sample_image(index: int = 1) -> ExtractedImage:
    return ExtractedImage(
        page=1,
        index_on_page=index,
        ext="png",
        bytes=b"PNGDATA",
        bbox=(10.0, 10.0, 100.0, 100.0),
        suggested_alt="",
        stored_filename=f"p9999r0-fig1-{index}.png",
        xref=index,
    )


def _pdf_image_section(img: ExtractedImage) -> Section:
    return Section(
        kind=SectionKind.IMAGE,
        text="",
        confidence=Confidence.HIGH,
        page_num=0,
        image_ref=img,
    )


def _assert_twin_output(
    text: str,
    *,
    images: tuple[ExtractedImage, ...] = (),
    diagnostics: Diagnostics = Diagnostics(),
) -> str:
    doc = PaperDocument(
        paper_id="P9999R0",
        metadata=_PAPER_META,
        elements=[Paragraph.from_text(text)],
        images=list(images),
        diagnostics=diagnostics,
    )
    sections = [_pdf_paragraph_section(text), *(_pdf_image_section(img) for img in images)]
    expected = emit_markdown(
        dict(_META_DICT),
        sections,
        images_truncated=diagnostics.images_truncated,
        source_image_count=diagnostics.source_image_count,
        vector_uncertainty=diagnostics.vector_uncertainty,
        glyph_stats=diagnostics.glyph_stats,
    )
    actual = MarkdownWriter().write(doc)
    assert actual == expected
    return actual


@pytest.mark.parametrize(
    ("text", "images", "diagnostics", "expected_substr", "absent_substr"),
    [
        pytest.param(
            "Body paragraph for truncation test.",
            (),
            Diagnostics(images_truncated=True, source_image_count=25),
            "<!-- tomd:images-truncated: kept 0 of 25 images. 25 image(s) dropped",
            None,
            id="truncated-zero-kept",
        ),
        pytest.param(
            "Body paragraph with one kept figure.",
            (_sample_image(1),),
            Diagnostics(images_truncated=True, source_image_count=25),
            "<!-- tomd:images-truncated: kept 1 of 25 images. 24 image(s) dropped",
            None,
            id="truncated-one-kept",
        ),
        pytest.param(
            "Body paragraph without truncation.",
            (_sample_image(1),),
            Diagnostics(images_truncated=False, source_image_count=1),
            None,
            "tomd:images-truncated",
            id="not-truncated",
        ),
        pytest.param(
            "Body paragraph where kept equals source count.",
            (_sample_image(1),),
            Diagnostics(images_truncated=True, source_image_count=1),
            None,
            "tomd:images-truncated",
            id="truncated-flag-with-zero-dropped",
        ),
        pytest.param(
            "Body paragraph for vector uncertainty.",
            (),
            Diagnostics(
                vector_uncertainty=VectorUncertaintyStats(
                    pages_scanned=4,
                    candidates=10,
                    kept=3,
                    rejected=7,
                    reasons={"too_small": 4, "edge_band": 1, "text_overlap": 2},
                    pages_skipped=1,
                ),
            ),
            "reasons={edge_band:1, text_overlap:2, too_small:4} pages_skipped=1.",
            None,
            id="vector-uncertain-rejected-and-skipped",
        ),
        pytest.param(
            "Body paragraph with skipped page only.",
            (),
            Diagnostics(
                vector_uncertainty=VectorUncertaintyStats(
                    pages_scanned=2,
                    candidates=0,
                    kept=0,
                    rejected=0,
                    reasons={},
                    pages_skipped=1,
                ),
            ),
            "<!-- tomd:vector-extraction-uncertain: pages_scanned=2 candidates=0 kept=0 rejected=0 reasons={} pages_skipped=1.",
            None,
            id="vector-uncertain-pages-skipped-only",
        ),
        pytest.param(
            "Body paragraph with clean vector extraction.",
            (),
            Diagnostics(
                vector_uncertainty=VectorUncertaintyStats(
                    pages_scanned=3,
                    candidates=2,
                    kept=2,
                    rejected=0,
                    reasons={},
                    pages_skipped=0,
                ),
            ),
            None,
            "tomd:vector-extraction-uncertain",
            id="vector-clean-suppressed",
        ),
        pytest.param(
            "Body paragraph with unattempted vector extraction.",
            (),
            Diagnostics(
                vector_uncertainty=VectorUncertaintyStats(
                    pages_scanned=0,
                    candidates=0,
                    kept=0,
                    rejected=0,
                    reasons={},
                    pages_skipped=0,
                ),
            ),
            None,
            "tomd:vector-extraction-uncertain",
            id="vector-unattempted-suppressed",
        ),
        pytest.param(
            f"Consensus {UNKNOWN_GLYPH} increased {UNKNOWN_GLYPH} significantly.",
            (),
            Diagnostics(glyph_stats=GlyphPassStats(injected=2)),
            "<!-- tomd:glyph-placeholders: placeholders=2 skipped_coincident=0 skipped_code_section=0 -->",
            None,
            id="glyph-placeholders-without-skips",
        ),
        pytest.param(
            f"One inline glyph {UNKNOWN_GLYPH} survived.",
            (),
            Diagnostics(
                glyph_stats=GlyphPassStats(
                    injected=2,
                    skipped_coincident=3,
                    free_standing=0,
                    skipped_code_section=1,
                ),
            ),
            "<!-- tomd:glyph-placeholders: placeholders=1 skipped_coincident=3 skipped_code_section=1 -->",
            None,
            id="glyph-placeholders-with-skips",
        ),
        pytest.param(
            "All glyphs were coincident with text-layer emoji.",
            (),
            Diagnostics(glyph_stats=GlyphPassStats(skipped_coincident=4)),
            "<!-- tomd:glyph-placeholders: placeholders=0 skipped_coincident=4 skipped_code_section=0 -->",
            None,
            id="glyph-zero-present-with-coincident-skips",
        ),
        pytest.param(
            "Injected glyph was later removed from body.",
            (),
            Diagnostics(glyph_stats=GlyphPassStats(injected=1, free_standing=1)),
            None,
            "tomd:glyph-placeholders",
            id="glyph-injected-but-none-present-or-skipped",
        ),
        pytest.param(
            "Plain prose with no placeholders.",
            (),
            Diagnostics(glyph_stats=GlyphPassStats()),
            None,
            "tomd:glyph-placeholders",
            id="glyph-empty-stats-suppressed",
        ),
    ],
)
def test_twin_individual_markers(
    text: str,
    images: tuple[ExtractedImage, ...],
    diagnostics: Diagnostics,
    expected_substr: str | None,
    absent_substr: str | None,
):
    actual = _assert_twin_output(text, images=images, diagnostics=diagnostics)
    if expected_substr is not None:
        assert expected_substr in actual
    if absent_substr is not None:
        assert absent_substr not in actual


def test_twin_all_three_markers_together_and_order():
    actual = _assert_twin_output(
        f"Paragraph with glyph {UNKNOWN_GLYPH} and all three markers.",
        images=(_sample_image(1),),
        diagnostics=Diagnostics(
            images_truncated=True,
            source_image_count=22,
            vector_uncertainty=VectorUncertaintyStats(
                pages_scanned=2,
                candidates=5,
                kept=1,
                rejected=4,
                reasons={"too_small": 2, "wording_color": 2},
                pages_skipped=0,
            ),
            glyph_stats=GlyphPassStats(
                injected=2,
                skipped_coincident=1,
                skipped_code_section=1,
            ),
        ),
    )
    trunc_pos = actual.index("<!-- tomd:images-truncated:")
    vec_pos = actual.index("<!-- tomd:vector-extraction-uncertain:")
    glyph_pos = actual.index("<!-- tomd:glyph-placeholders:")
    assert trunc_pos < vec_pos < glyph_pos


def test_separate_write_body_and_append_trailer_markers():
    text = f"Separate body and trailer {UNKNOWN_GLYPH} call."
    img = _sample_image(1)
    diag = Diagnostics(
        images_truncated=True,
        source_image_count=21,
        vector_uncertainty=VectorUncertaintyStats(
            pages_scanned=1,
            candidates=2,
            kept=1,
            rejected=1,
            reasons={"too_few_items": 1},
            pages_skipped=0,
        ),
        glyph_stats=GlyphPassStats(injected=1, skipped_coincident=2),
    )
    doc = PaperDocument(
        paper_id="P9999R0",
        metadata=_PAPER_META,
        elements=[Paragraph.from_text(text)],
        images=[img],
        diagnostics=diag,
    )
    writer = MarkdownWriter()
    body_md = writer.write_body(doc)
    assert "<!-- tomd:" not in body_md

    combined = append_trailer_markers(body_md, diag, kept_image_count=len(doc.images))
    assert combined == writer.write(doc)
