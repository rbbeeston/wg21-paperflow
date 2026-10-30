"""
Distributed under the Boost Software License, Version 1.0. (See accompanying

file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)

Official repository: https://github.com/cppalliance/wg21-paperflow
"""

from typing import Any

import pytest

from conftest import make_line, make_section
from tomd.domain import (
    BlockElement,
    CodeBlock,
    Confidence,
    Heading,
    ImageElement,
    ListBlock,
    PaperDocument,
    PaperMetadata,
    Paragraph,
    Provenance,
    TextSpan,
    UncertainElement,
    WordingBlock,
)
from tomd.lib.pdf.emit import emit_markdown, emit_prompts
from tomd.lib.pdf.types import Section, SectionKind
from tomd.writers import MarkdownWriter

_FRONT_MATTER_META: dict[str, Any] = {
    "title": "constexpr for <cmath>",
    "document": "P0533R9",
    "date": "2021-11-12",
    "intent": "change",
    "audience": "LWG, CWG",
    "reply-to": [
        "Edward J. Rosten <erosten@snap.com>",
        "Oliver J. Rosten <oliver.rosten@gmail.com>",
    ],
}


def _uncertain_section(
    text: str,
    *,
    page_num: int = 0,
    mupdf_text: str = "",
    spatial_text: str = "",
) -> Section:
    return make_section(
        text,
        kind=SectionKind.UNCERTAIN,
        confidence=Confidence.UNCERTAIN,
        page_num=page_num,
        mupdf_text=mupdf_text,
        spatial_text=spatial_text,
    )


def _code_section(code: str, *, page_num: int = 0) -> Section:
    lines = [
        make_line(
            [ln],
            page_num=page_num,
            monospace=True,
            bbox=(50.0, i * 14.0, 400.0, i * 14.0 + 12.0),
        )
        for i, ln in enumerate(code.split("\n"))
    ]
    return make_section(code, kind=SectionKind.CODE, page_num=page_num, lines=lines)


def _sections_to_document(
    sections: list[Section],
    meta: dict[str, Any] | None = None,
) -> PaperDocument:
    elements: list[BlockElement] = []
    for idx, sec in enumerate(sections):
        prov = Provenance(page=sec.page_num, confidence=sec.confidence)
        match sec.kind:
            case SectionKind.UNCERTAIN:
                before = sections[idx - 1] if idx > 0 else None
                after = sections[idx + 1] if idx + 1 < len(sections) else None
                elements.append(
                    UncertainElement(
                        mupdf_text=sec.mupdf_text,
                        spatial_text=sec.spatial_text,
                        page=sec.page_num,
                        text=sec.text,
                        context_before=(
                            before.text[:200].strip()
                            if before and before.kind != SectionKind.UNCERTAIN
                            else ""
                        ),
                        context_after=(
                            after.text[:200].strip()
                            if after and after.kind != SectionKind.UNCERTAIN
                            else ""
                        ),
                        provenance=prov,
                    )
                )
            case SectionKind.HEADING | SectionKind.TITLE:
                level = 1 if sec.kind == SectionKind.TITLE else sec.heading_level
                elements.append(Heading(level, [TextSpan(sec.text)], provenance=prov))
            case SectionKind.CODE:
                elements.append(CodeBlock(code=sec.text, language=sec.fence_lang, provenance=prov))
            case SectionKind.IMAGE:
                elements.append(ImageElement(caption="", alt="", provenance=prov))
            case SectionKind.LIST:
                elements.append(ListBlock(items=[], provenance=prov))
            case SectionKind.WORDING:
                elements.append(WordingBlock(children=[], provenance=prov))
            case _:
                elements.append(Paragraph([TextSpan(sec.text)], provenance=prov))

    return PaperDocument(
        paper_id="P0000R0",
        metadata=PaperMetadata.from_dict(meta),
        elements=elements,
    )


def _assert_twin_parity(
    sections: list[Section],
    meta: dict[str, Any] | None = None,
) -> tuple[str, list[str] | None]:
    metadata = meta or {}
    doc = _sections_to_document(sections, metadata)
    actual_md = MarkdownWriter().write(doc)
    actual_prompts = doc.get_reconciliation_prompts()
    assert actual_md == emit_markdown(metadata, sections)
    assert actual_prompts == emit_prompts(sections)
    return actual_md, actual_prompts


@pytest.mark.parametrize(
    ("sections", "meta", "expected_marker"),
    [
        pytest.param(
            [
                _uncertain_section(
                    "uncertain lead line 1\nuncertain lead line 2",
                    mupdf_text="mupdf lead",
                    spatial_text="spatial lead",
                ),
                make_section("Following confident paragraph."),
            ],
            None,
            "<!-- tomd:uncertain:L3-L4 -->",
            id="start-no-front-matter",
        ),
        pytest.param(
            [
                make_section("Introductory paragraph.", page_num=1),
                _uncertain_section(
                    "middle uncertain text",
                    page_num=2,
                    mupdf_text="mupdf middle",
                    spatial_text="spatial middle",
                ),
                make_section("Concluding paragraph.", page_num=2),
            ],
            None,
            "<!-- tomd:uncertain:L5-L5 -->",
            id="middle-no-front-matter",
        ),
        pytest.param(
            [
                make_section("Section Intro", kind=SectionKind.HEADING, heading_level=2, page_num=3),
                make_section("Body text before uncertain region.", page_num=3),
                _uncertain_section(
                    "trailing uncertain block\nwith two lines",
                    page_num=4,
                    mupdf_text="mupdf tail",
                    spatial_text="spatial tail",
                ),
            ],
            None,
            "<!-- tomd:uncertain:L7-L8 -->",
            id="end-no-front-matter",
        ),
        pytest.param(
            [
                _code_section("int a = 1;\nint b = 2;\nreturn a + b;", page_num=1),
                _uncertain_section(
                    "uncertain after multiline code block\nsecond line",
                    page_num=1,
                    mupdf_text="mupdf after code",
                    spatial_text="spatial after code",
                ),
            ],
            None,
            "<!-- tomd:uncertain:L9-L10 -->",
            id="after-multiline-code-block",
        ),
        pytest.param(
            [
                make_section("Preceding confident text.", page_num=1),
                _uncertain_section(
                    "first uncertain region",
                    page_num=1,
                    mupdf_text="mupdf 1",
                    spatial_text="spatial 1",
                ),
                _uncertain_section(
                    "second uncertain region\nspanning two lines",
                    page_num=2,
                    mupdf_text="mupdf 2",
                    spatial_text="spatial 2",
                ),
                make_section("Following confident text.", page_num=2),
            ],
            None,
            "<!-- tomd:uncertain:L9-L10 -->",
            id="adjacent-uncertain-regions",
        ),
        pytest.param(
            [
                make_section("First real paragraph."),
                make_section("   "),
                make_section("   ", kind=SectionKind.HEADING, heading_level=2),
                Section(kind=SectionKind.IMAGE, text="", confidence=Confidence.HIGH, page_num=0),
                _uncertain_section(
                    "uncertain after skipped sections\nsecond line\nthird line",
                    page_num=1,
                    mupdf_text="mupdf after empty",
                    spatial_text="spatial after empty",
                ),
                make_section("", kind=SectionKind.LIST, page_num=1),
                make_section("", kind=SectionKind.WORDING, page_num=1),
                _uncertain_section(
                    "second uncertain after empty list and wording",
                    page_num=2,
                    mupdf_text="mupdf 2",
                    spatial_text="spatial 2",
                ),
            ],
            None,
            "<!-- tomd:uncertain:L5-L7 -->",
            id="after-empty-rendering-sections",
        ),
        pytest.param(
            [
                _uncertain_section(
                    "uncertain at start after front matter",
                    mupdf_text="mupdf start",
                    spatial_text="spatial start",
                ),
                make_section(
                    (
                        "We propose simple criteria for selecting functions in <cmath> "
                        "which should be declared constexpr. " * 4
                    ).strip(),
                ),
                _uncertain_section(
                    "uncertain body line 1\nuncertain body line 2\n\n  ",
                    page_num=5,
                ),
                _code_section("int abs(int j);", page_num=6),
            ],
            _FRONT_MATTER_META,
            "<!-- tomd:uncertain:L14-L14 -->",
            id="with-front-matter-and-long-neighbors",
        ),
        pytest.param(
            [
                make_section("   ", page_num=1),
                _uncertain_section(
                    "fallback text used when mupdf is empty",
                    page_num=2,
                    spatial_text="explicit spatial",
                ),
                make_section("Middle bridge.", page_num=2),
                _uncertain_section(
                    "fallback text used when spatial is empty",
                    page_num=3,
                    mupdf_text="explicit mupdf",
                ),
                make_section(
                    ("Following confident section exceeding two hundred characters. " * 5).strip(),
                    page_num=3,
                ),
            ],
            None,
            "<!-- tomd:uncertain:L3-L3 -->",
            id="asymmetric-extraction-fallbacks-and-long-context-after",
        ),
    ],
)
def test_twin_uncertain_and_prompts_parity(
    sections: list[Section],
    meta: dict[str, Any] | None,
    expected_marker: str,
):
    actual_md, actual_prompts = _assert_twin_parity(sections, meta=meta)
    assert expected_marker in actual_md
    assert actual_prompts is not None


def test_twin_prompts_none_when_no_uncertain():
    sections = [
        make_section("Introduction", kind=SectionKind.HEADING, heading_level=2),
        make_section("All sections are confident."),
    ]
    _, actual_prompts = _assert_twin_parity(sections)
    assert actual_prompts is None
