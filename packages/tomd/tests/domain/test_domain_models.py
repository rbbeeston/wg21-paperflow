"""
Distributed under the Boost Software License, Version 1.0. (See accompanying

file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)

Official repository: https://github.com/cppalliance/wg21-paperflow
"""

from dataclasses import FrozenInstanceError
import pytest

from tomd.api import ConvertedPaper
from tomd.domain.diagnostics import (
    Diagnostics,
    GlyphPassStats,
    VectorUncertaintyStats,
)
from tomd.domain.document import PaperDocument, SkipReason
from tomd.domain.elements import (
    BlockElement,
    Blockquote,
    CodeBlock,
    Confidence,
    ElementKind,
    Heading,
    ImageElement,
    ListBlock,
    ListItem,
    Paragraph,
    Provenance,
    ThematicBreak,
    UncertainElement,
    WordingBlock,
)
from tomd.domain.image import ExtractedImage
from tomd.domain.metadata import PaperMetadata
from tomd.lib.metadata_yaml.format import FRONT_MATTER_ORDER
from tomd.domain.span import (
    CodeSpan,
    ContainerSpan,
    DeletedSpan,
    EmphasisSpan,
    InsertedSpan,
    LineBreakSpan,
    LinkSpan,
    Span,
    StrongSpan,
    SubscriptSpan,
    SuperscriptSpan,
    TextSpan,
)
from tomd.domain.table import (
    Cell,
    CellAlign,
    CodeCell,
    Table,
    TableRow,
    TableStrategy,
    TextCell,
)


def test_span_primitives_and_immutability():
    text = TextSpan(content="hello")
    assert text.content == "hello"
    assert text.text == "hello"

    code = CodeSpan(code="std::vector<int>")
    assert code.code == "std::vector<int>"
    assert code.text == "std::vector<int>"

    lb = LineBreakSpan()
    assert lb.text == "\n"

    # Spans are frozen dataclasses
    with pytest.raises(FrozenInstanceError):
        text.content = "modified"  # type: ignore[misc]


def test_enums_and_base_types():
    # Base Span
    base_span = Span()
    assert base_span.text == ""

    # Base Cell
    base_cell = Cell(align=CellAlign.RIGHT, width="100px")
    assert base_cell.align == CellAlign.RIGHT
    assert base_cell.width == "100px"
    assert base_cell.text == ""

    # ElementKind enumeration
    assert ElementKind.HEADING == "heading"
    assert ElementKind.PARAGRAPH == "paragraph"
    assert ElementKind.CODE_BLOCK == "code_block"
    assert ElementKind.TABLE == "table"
    assert ElementKind.LIST == "list"
    assert ElementKind.BLOCKQUOTE == "blockquote"
    assert ElementKind.WORDING == "wording"
    assert ElementKind.THEMATIC_BREAK == "thematic_break"
    assert ElementKind.IMAGE == "image"
    assert ElementKind.UNCERTAIN == "uncertain"

    # SkipReason enumeration (canonical legacy values)
    assert SkipReason.EMPTY_PDF == "empty pdf"
    assert SkipReason.SLIDE_DECK == "slide deck"
    assert SkipReason.STANDARDS_DRAFT == "standards draft"
    assert SkipReason.UNREADABLE == "unreadable"


def test_container_spans_and_nesting():
    strong = StrongSpan.from_text("bold")
    assert strong.text == "bold"
    assert len(strong.children) == 1
    assert isinstance(strong.children[0], TextSpan)

    emphasis = EmphasisSpan.from_text("italic")
    assert emphasis.text == "italic"
    assert isinstance(emphasis, ContainerSpan)

    deleted = DeletedSpan.from_text("deleted")
    assert deleted.text == "deleted"
    assert deleted.wording_role == "del"

    inserted = InsertedSpan.from_text("inserted")
    assert inserted.text == "inserted"
    assert inserted.wording_role == "ins"

    sub = SubscriptSpan.from_text("sub")
    assert sub.text == "sub"

    sup = SuperscriptSpan.from_text("sup")
    assert sup.text == "sup"

    link = LinkSpan.from_text("Link Text", "https://isocpp.org", title="ISO C++")
    assert link.text == "Link Text"
    assert link.url == "https://isocpp.org"
    assert link.title == "ISO C++"

    nested = StrongSpan(
        children=(
            EmphasisSpan(children=(TextSpan("nested "),)),
            CodeSpan("code"),
        )
    )
    assert nested.text == "nested code"


def test_paper_metadata_roundtrip_and_ordering():
    data = {
        "title": "A Title",
        "document": "P1234R0",
        "date": "2026-01-15",
        "intent": "change",
        "audience": ["EWG", "LEWG"],
        "reply-to": ["Author <author@example.com>"],
        "extra_field": "preserved",
    }
    meta = PaperMetadata.from_dict(data)
    assert meta.title == "A Title"
    assert meta.document == "P1234R0"
    assert meta.date == "2026-01-15"
    assert meta.intent == "change"
    assert meta.audience == ["EWG", "LEWG"]
    assert meta.reply_to == ["Author <author@example.com>"]
    assert meta.extra == {"extra_field": "preserved"}

    out = meta.to_dict()
    assert out["title"] == "A Title"
    assert out["document"] == "P1234R0"
    assert out["date"] == "2026-01-15"
    assert out["intent"] == "change"
    assert out["audience"] == ["EWG", "LEWG"]
    assert out["reply-to"] == ["Author <author@example.com>"]
    assert out["extra_field"] == "preserved"

    # Keys in FRONT_MATTER_ORDER appear in exact expected sequence
    out_keys = list(out.keys())
    for i, key in enumerate(FRONT_MATTER_ORDER):
        assert out_keys[i] == key

    empty_meta = PaperMetadata.from_dict(None)
    assert empty_meta.title == ""
    assert empty_meta.to_dict() == {}


def test_table_and_cells():
    header_left = TextCell.from_text("Before", align=CellAlign.LEFT, width="50%")
    header_right = TextCell.from_text("After", align=CellAlign.LEFT, width="50%")
    assert header_left.text == "Before"
    assert header_left.align == CellAlign.LEFT
    assert header_left.width == "50%"

    code_cell = CodeCell(code="void f();", language="cpp", width="50%")
    assert code_cell.text == "void f();"
    assert code_cell.code == "void f();"
    assert code_cell.language == "cpp"

    text_cell = TextCell(
        spans=[TextSpan("Returns "), CodeSpan("nullopt")],
        align=CellAlign.CENTER,
    )
    assert text_cell.text == "Returns nullopt"
    assert text_cell.align == CellAlign.CENTER

    row = TableRow(cells=[code_cell, text_cell])
    assert len(row.cells) == 2

    table = Table(
        headers=[header_left, header_right],
        rows=[row],
        caption="Comparison Table",
    )
    assert table.strategy == TableStrategy.PIPE
    assert table.caption == "Comparison Table"
    assert len(table.rows) == 1
    assert isinstance(table, BlockElement)


def test_image_models():
    extracted = ExtractedImage(
        page=1,
        index_on_page=2,
        ext="png",
        bytes=b"\x89PNG\r\n\x1a\n",
        bbox=(10.0, 20.0, 110.0, 120.0),
        suggested_alt="Figure 1: State machine",
        stored_filename="p1234r0-fig1-2.png",
        xref=42,
    )
    assert extracted.source == "raster"
    assert extracted.sub_captions == ()
    assert extracted.caption_body_dropped is False

    with pytest.raises(FrozenInstanceError):
        extracted.page = 2  # type: ignore[misc]


def test_block_elements_hierarchy():
    h = Heading.from_text(level=2, text="Introduction")
    assert h.level == 2
    assert h.text == "Introduction"
    assert isinstance(h, BlockElement)

    p = Paragraph.from_text("A simple paragraph.")
    assert p.text == "A simple paragraph."
    assert isinstance(p, BlockElement)

    cb = CodeBlock(code='auto x = 42;\nstd::print("{}\\n", x);', language="cpp", title="sample.cpp")
    assert cb.code.startswith("auto x = 42;")
    assert cb.language == "cpp"
    assert cb.title == "sample.cpp"
    assert isinstance(cb, BlockElement)

    item1 = ListItem.from_text("First item")
    item2 = ListItem(spans=[StrongSpan.from_text("Second"), TextSpan(" item")])
    list_blk = ListBlock(items=[item1, item2], ordered=True)
    assert list_blk.ordered is True
    assert len(list_blk.items) == 2
    assert list_blk.items[1].text == "Second item"
    assert isinstance(list_blk, BlockElement)

    bq = Blockquote.from_text("This is quoted.", role="note")
    assert bq.role == "note"
    assert bq.text == "This is quoted."
    assert isinstance(bq, BlockElement)

    wb = WordingBlock.from_text("Change [basic.def] as follows:", role="wording")
    assert wb.role == "wording"
    assert wb.text == "Change [basic.def] as follows:"
    assert isinstance(wb, BlockElement)

    cb_diff = CodeBlock(
        language="cpp",
        lines=[
            [TextSpan("template<class U>")],
            [TextSpan("  constexpr "), DeletedSpan.from_text("explicit"), TextSpan(" void f();")],
        ],
    )
    assert cb_diff.text == "template<class U>\n  constexpr explicit void f();"

    tb = ThematicBreak()
    assert isinstance(tb, BlockElement)

    img = ImageElement(caption="Figure 1", alt="Diagram", stored_filename="fig1.png")
    assert img.stored_filename == "fig1.png"
    assert img.text == "Figure 1"
    assert isinstance(img, BlockElement)

    unc = UncertainElement(
        mupdf_text="mupdf version",
        spatial_text="spatial version",
        page=4,
        text="mupdf version",
        context_before="before text",
        context_after="after text",
    )
    assert unc.mupdf_text == "mupdf version"
    assert unc.spatial_text == "spatial version"
    assert unc.page == 4
    assert unc.text == "mupdf version"
    assert unc.context_before == "before text"
    assert unc.context_after == "after text"
    assert unc.provenance is None
    assert "This region is on page 4." in unc.get_reconciliation_prompt()
    assert isinstance(unc, BlockElement)


def test_provenance_and_confidence():
    assert Confidence.HIGH.value == "high"
    assert Confidence.MEDIUM.value == "medium"
    assert Confidence.LOW.value == "low"
    assert Confidence.UNCERTAIN.value == "uncertain"

    prov = Provenance(page=3, confidence=Confidence.MEDIUM)
    assert prov.page == 3
    assert prov.confidence == Confidence.MEDIUM
    with pytest.raises(FrozenInstanceError):
        prov.page = 5  # type: ignore[misc]

    para = Paragraph(spans=[TextSpan("hello")], provenance=prov)
    assert para.provenance == prov
    assert Paragraph.from_text("default").provenance is None


def test_list_item_text_includes_children():
    nested = ListBlock(items=[ListItem.from_text("child")])
    item = ListItem(spans=[TextSpan("label")], children=[Paragraph.from_text("more"), nested])
    assert item.text == "label\nmore\nchild"
    assert ListItem(children=[Paragraph.from_text("only")]).text == "only"


def test_blockquote_and_wording_text_include_children():
    bq = Blockquote(children=[Paragraph.from_text("first"), Paragraph.from_text("second")])
    assert bq.text == "first\nsecond"

    wb = WordingBlock(
        role="wording-add",
        children=[Paragraph.from_text("clause 1"), CodeBlock(code="int x;")],
    )
    assert wb.text == "clause 1\nint x;"


def test_document_and_conversion_containers():
    meta = PaperMetadata(title="Sample Paper", document="P9999R0")
    h2 = Heading.from_text(2, "Proposed Wording")
    p = Paragraph.from_text("Text here.")

    doc = PaperDocument(
        paper_id="P9999R0",
        metadata=meta,
        elements=[h2, p],
    )
    assert doc.paper_id == "P9999R0"
    assert len(doc.elements) == 2
    assert not doc.is_skipped
    assert doc.skip_reason is None
    assert doc.diagnostics == Diagnostics()
    assert doc.get_reconciliation_prompts() is None

    skipped_doc = PaperDocument(
        paper_id="P0000R0",
        metadata=meta,
        is_skipped=True,
        skip_reason=SkipReason.EMPTY_PDF,
    )
    assert skipped_doc.is_skipped is True
    assert skipped_doc.skip_reason == SkipReason.EMPTY_PDF

    converted = ConvertedPaper(
        markdown="---\ntitle: Sample Paper\n---\n\n## Proposed Wording\n\nText here.\n",
        prompts=None,
        intent="info",
    )
    assert "Proposed Wording" in converted.markdown


@pytest.mark.parametrize(
    ("stats", "present", "expected_fired", "expected_marker"),
    [
        (GlyphPassStats(), 0, False, False),
        (GlyphPassStats(injected=1), 0, True, False),
        (GlyphPassStats(free_standing=1), 0, True, False),
        (GlyphPassStats(injected=1), 1, True, True),
        (GlyphPassStats(skipped_coincident=1), 0, True, True),
        (GlyphPassStats(skipped_code_section=1), 0, True, True),
    ],
)
def test_glyph_pass_stats_predicates(
    stats: GlyphPassStats,
    present: int,
    expected_fired: bool,
    expected_marker: bool,
):
    assert stats.fired is expected_fired
    assert stats.should_emit_marker(present) is expected_marker


def test_diagnostics_models():
    vec_stats = VectorUncertaintyStats(
        pages_scanned=2,
        candidates=3,
        kept=1,
        rejected=2,
        reasons={"too_small": 2},
        pages_skipped=0,
    )
    assert vec_stats.rejected == 2
    with pytest.raises(FrozenInstanceError):
        vec_stats.kept = 0  # type: ignore[misc]

    default_diag = Diagnostics()
    assert default_diag.dropped_image_count(0) == 0
    assert Diagnostics(images_truncated=False, source_image_count=25).dropped_image_count(20) == 0
    assert Diagnostics(images_truncated=True, source_image_count=20).dropped_image_count(20) == 0
    assert Diagnostics(images_truncated=True, source_image_count=25).dropped_image_count(20) == 5
