"""Tests for lib.pdf.emit."""

from conftest import make_section, make_line, make_span
from tomd.lib.pdf.types import SectionKind, Confidence, Section, Span, Line
from tomd.lib.pdf.emit import (
    _emdash_bullet_items,
    emit_markdown,
    emit_prompts,
    _render_code_block,
    _detect_code_gutter,
)
from tomd.lib.pdf.wording_emit import (
    _render_wording_line,
    _render_wording_section,
)


def test_emit_heading():
    sec = make_section("Introduction", kind=SectionKind.HEADING,
                       heading_level=2)
    md = emit_markdown({}, [sec])
    assert "## Introduction" in md


def test_emit_heading_joins_all_lines():
    """A heading split across lines (number / title / clause tag laid out
    with wide x-gaps on one visual line) renders as a single heading, not
    just the first line (the bare section number)."""
    sec = make_section(
        "1\nScope\n[scope]", kind=SectionKind.HEADING, heading_level=2,
        lines=[make_line(["1"]), make_line(["Scope"]), make_line(["[scope]"])],
    )
    md = emit_markdown({}, [sec])
    assert "## 1 Scope [scope]" in md


def test_emit_heading_dedupes_overprinted_lines():
    """A heading the PDF overprints several times at the same position (faux
    bold) renders once, not repeated."""
    sec = make_section(
        "Abstract\nAbstract\nAbstract", kind=SectionKind.HEADING,
        heading_level=2,
        lines=[make_line(["Abstract"]), make_line(["Abstract"]),
               make_line(["Abstract"])],
    )
    md = emit_markdown({}, [sec])
    assert "## Abstract\n" in md or md.strip().endswith("## Abstract")
    assert "Abstract Abstract" not in md


def test_emit_heading_excludes_lower_baseline_body_line():
    """A line on a lower baseline than the heading's own row is emitted as a
    body paragraph below the heading, not folded into the heading line.

    This pins the deliberate trade-off in ``_render_heading_spans``: grouping
    is same-row only, so a wrapped title or wrongly-absorbed body line drops
    to a paragraph rather than being joined back into the heading."""
    sec = make_section(
        "1\nScope\nBody prose here", kind=SectionKind.HEADING, heading_level=2,
        lines=[
            Line(spans=[make_span("1")], bbox=(50, 50, 70, 62), page_num=0),
            Line(spans=[make_span("Scope")], bbox=(80, 50, 200, 62), page_num=0),
            Line(spans=[make_span("Body prose here")],
                 bbox=(50, 75, 400, 87), page_num=0),
        ],
    )
    md = emit_markdown({}, [sec])
    assert "## 1 Scope" in md
    assert "Body prose here" not in md.split("\n")[0]
    assert "Body prose here" in md


def test_emit_heading_joins_mixed_font_row_by_baseline():
    """A single visual row mixing font sizes (a large section number beside a
    small-caps title) stays one heading. The glyph tops differ even though the
    baselines align, so grouping must key on the vertical midpoint, not the
    top edge; keying on the top edge would demote the title to a paragraph."""
    sec = make_section(
        "19\nSCOPE", kind=SectionKind.HEADING, heading_level=2,
        lines=[
            Line(spans=[make_span("19", font_size=24.0)],
                 bbox=(50, 30, 90, 62), page_num=0),
            Line(spans=[make_span("SCOPE", font_size=10.0)],
                 bbox=(100, 50, 300, 60), page_num=0),
        ],
    )
    md = emit_markdown({}, [sec])
    assert "## 19 SCOPE" in md


def test_emit_heading_joins_split_row_when_font_size_zero():
    """Type-3/bitmap fonts report ``font_size`` 0, so the same-row tolerance
    would collapse to 0 and join only exact-midpoint lines, demoting a split
    "1" / "Scope" title to a body paragraph. A fallback font size keeps the row
    together."""
    sec = make_section(
        "1\nScope", kind=SectionKind.HEADING, heading_level=2,
        lines=[
            Line(spans=[make_span("1", font_size=0.0)],
                 bbox=(50, 100, 70, 122), page_num=0),     # midpoint 111
            Line(spans=[make_span("Scope", font_size=0.0)],
                 bbox=(80, 105, 200, 121), page_num=0),    # midpoint 113
        ],
    )
    md = emit_markdown({}, [sec])
    assert "## 1 Scope" in md


def test_emit_paragraph_unwrapped():
    sec = make_section("Hello world")
    md = emit_markdown({}, [sec])
    assert "Hello world" in md


def test_emit_code_fenced():
    sec = make_section("int main() {}", kind=SectionKind.CODE,
                       fence_lang="cpp")
    sec.lines[0].spans[0].monospace = True
    md = emit_markdown({}, [sec])
    assert "```cpp" in md
    assert "int main()" in md


def test_emit_uncertain_has_comment():
    sec = make_section("uncertain text", kind=SectionKind.UNCERTAIN,
                       confidence=Confidence.UNCERTAIN)
    sec.mupdf_text = "uncertain text"
    sec.spatial_text = "different text"
    md = emit_markdown({}, [sec])
    assert "<!-- tomd:uncertain:" in md


def test_emit_prompts_none_when_no_uncertain():
    sec = make_section("hello")
    assert emit_prompts([sec]) is None


def test_emit_prompts_returns_one_self_contained_prompt_per_region():
    sec_a = make_section(
        "uncertain a", kind=SectionKind.UNCERTAIN, confidence=Confidence.UNCERTAIN
    )
    sec_a.mupdf_text = "mupdf a"
    sec_a.spatial_text = "spatial a"
    sec_a.page_num = 3
    sec_b = make_section(
        "uncertain b", kind=SectionKind.UNCERTAIN, confidence=Confidence.UNCERTAIN
    )
    sec_b.mupdf_text = "mupdf b"
    sec_b.spatial_text = "spatial b"
    sec_b.page_num = 7

    result = emit_prompts([sec_a, sec_b])
    assert isinstance(result, list)
    assert len(result) == 2

    for r in result:
        assert "MuPDF extraction" in r
        assert "Spatial extraction" in r
        assert "CRITICAL" in r
        assert "verbatim" in r

    assert "page 3" in result[0]
    assert "mupdf a" in result[0]
    assert "page 7" in result[1]
    assert "mupdf b" in result[1]


def test_front_matter_title_quoted():
    md = emit_markdown({"title": "My Paper: A Study"}, [])
    assert 'title: "My Paper: A Study"' in md


def test_front_matter_reply_to_list():
    meta = {"reply-to": ["Alice <a@b.com>", "Bob <c@d.com>"]}
    md = emit_markdown(meta, [])
    assert "reply-to:" in md
    assert '"Alice <a@b.com>"' in md
    assert '"Bob <c@d.com>"' in md


def test_front_matter_special_chars_quoted():
    from tomd.lib import format_front_matter
    result = format_front_matter({"document": "P1234R0", "audience": "SG1: Concurrency"})
    assert '"SG1: Concurrency"' in result


def test_front_matter_canonical_order():
    """All six known keys come out in strict canonical order regardless of input order."""
    from tomd.lib import format_front_matter
    meta = {
        "reply-to": ["Alice <a@x>"],
        "audience": "LEWG",
        "intent": "info",
        "date": "2026-04-28",
        "document": "P9999R0",
        "title": "Canonical Test",
    }
    result = format_front_matter(meta)
    lines = result.splitlines()
    keys = [l.split(":")[0] for l in lines if l and not l.startswith((" ", "\t", "-")) and l != "---"]
    assert keys[0] == "title"
    assert "reply-to" in keys
    assert keys[-1] == "reply-to", "reply-to must always be last"
    assert keys.index("title") < keys.index("document") < keys.index("date")
    assert keys.index("date") < keys.index("intent") < keys.index("audience")
    assert 'title: "Canonical Test"' in result
    assert "document: P9999R0" in result
    assert "revision" not in result


def test_front_matter_intent_position():
    """`intent` lands between `date` and `audience`."""
    from tomd.lib import format_front_matter
    result = format_front_matter({
        "title": "T",
        "date": "2026-04-28",
        "intent": "ask",
        "audience": "LWG",
    })
    title_pos = result.index("title:")
    date_pos = result.index("date:")
    intent_pos = result.index("intent:")
    audience_pos = result.index("audience:")
    assert title_pos < date_pos < intent_pos < audience_pos


def test_front_matter_skips_missing_keys():
    """Missing keys produce no placeholders and no blank lines."""
    from tomd.lib import format_front_matter
    result = format_front_matter({"title": "T", "document": "P1R0"})
    assert 'title: "T"' in result
    assert "document: P1R0" in result
    assert "intent" not in result


def test_front_matter_unknown_keys_keep_reply_to_last():
    """Unknown keys land after canonical scalars; reply-to stays last."""
    from tomd.lib import format_front_matter
    result = format_front_matter({
        "title": "T",
        "audience": "LWG",
        "reply-to": ["X <x@y>"],
        "paper-type": "proposal",
    })
    audience_pos = result.index("audience:")
    paper_type_pos = result.index("paper-type:")
    reply_to_pos = result.index("reply-to:")
    assert audience_pos < paper_type_pos < reply_to_pos


def test_emit_list():
    span = make_span("- item one")
    line = make_line(["- item one"])
    sec = make_section("- item one", kind=SectionKind.LIST)
    md = emit_markdown({}, [sec])
    assert "- item one" in md


def test_emit_list_top_level_bullet_uses_dash():
    """Every depth uses the same "-" marker; nesting is carried by the indent."""
    sec = make_section("● item", kind=SectionKind.LIST)
    md = emit_markdown({}, [sec])
    assert "- item" in md
    assert "●" not in md
    assert "* item" not in md


def test_emit_list_nested_bullet_indented_dash():
    sec = make_section("○ nested", kind=SectionKind.LIST, indent_level=1)
    md = emit_markdown({}, [sec])
    assert "  - nested" in md


def test_emit_list_circle_glyph_not_emitted_literally():
    """U+25CB is a recognized bullet, never left as a literal glyph (issue #150)."""
    sec = make_section("○ child", kind=SectionKind.LIST, indent_level=1)
    md = emit_markdown({}, [sec])
    assert "○" not in md


def test_emit_list_deeper_nesting_indents_more():
    sec = make_section("○ deep", kind=SectionKind.LIST, indent_level=2)
    md = emit_markdown({}, [sec])
    assert "    - deep" in md


def test_emit_list_unwraps_wrapped_item():
    """A single bullet item split across PDF lines renders as one line."""
    line1 = make_line(["○ Perform a check of the value"])
    line2 = make_line(["expected."])
    sec = make_section(
        "○ Perform a check of the value\nexpected.",
        kind=SectionKind.LIST, lines=[line1, line2], indent_level=1,
    )
    md = emit_markdown({}, [sec])
    assert "  - Perform a check of the value expected." in md


def test_emit_list_multiple_clean_items_one_per_line():
    line1 = make_line(["● first"])
    line2 = make_line(["● second"])
    sec = make_section("● first\n● second",
                       kind=SectionKind.LIST, lines=[line1, line2])
    md = emit_markdown({}, [sec])
    assert "- first" in md
    assert "- second" in md


def test_emit_list_numbered_item_keeps_own_marker():
    """An item that already carries an ordinal marker keeps it, not a bullet.

    Exercises the _format_list_item branch for self-marked items directly
    rather than only through the golden files.
    """
    sec = make_section("2. The override keyword shall be added",
                       kind=SectionKind.LIST)
    md = emit_markdown({}, [sec])
    assert "2. The override keyword shall be added" in md


def test_emit_list_consecutive_numbered_items_split():
    """Successive numbered lines stay separate items (current item numbered)."""
    line1 = make_line(["1. first"])
    line2 = make_line(["2. second"])
    sec = make_section("1. first\n2. second",
                       kind=SectionKind.LIST, lines=[line1, line2])
    md = emit_markdown({}, [sec])
    assert "1. first" in md
    assert "2. second" in md


def test_emit_list_year_continuation_stays_joined():
    """A wrapped bullet continuation starting with a year does not split.

    The continuation "2017. The meeting..." matches the numbered-list
    pattern, but the open item is a bullet (not numbered), so it stays
    joined instead of opening a phantom numbered item (issue #175 review).
    """
    line1 = make_line(["● Approved at the meeting in"])
    line2 = make_line(["2017. The decision still stands."])
    sec = make_section("● Approved at the meeting in\n2017. The decision still stands.",
                       kind=SectionKind.LIST, lines=[line1, line2])
    md = emit_markdown({}, [sec])
    assert "- Approved at the meeting in 2017. The decision still stands." in md


def test_emit_list_ordinal_after_finished_bullet_stays_separate():
    """A genuine ordinal label after a completed bullet is its own item.

    Regression guard (issue #175, p1068r11): the bullet ends in terminal
    punctuation, so "d) ..." must not be absorbed as a continuation the way
    a mid-sentence wrap would be.
    """
    line1 = make_line(["● It may be considered a controversial feature."])
    line2 = make_line(["d) Constraining iterators and ranges"])
    sec = make_section(
        "● It may be considered a controversial feature.\n"
        "d) Constraining iterators and ranges",
        kind=SectionKind.LIST, lines=[line1, line2],
    )
    md = emit_markdown({}, [sec])
    assert "- It may be considered a controversial feature." in md
    assert "d) Constraining iterators and ranges" in md
    assert "feature. d)" not in md


def test_emit_table():
    from tomd.lib.pdf.types import Section
    sec = Section(
        kind=SectionKind.TABLE,
        text="",
        columns=[
            [[make_span("Header A")], [make_span("Header B")]],
            [[make_span("Cell 1")], [make_span("Cell 2")]],
        ],
    )
    md = emit_markdown({}, [sec])
    assert "Header A" in md
    assert "Header B" in md
    assert "---" in md
    assert "Cell 1" in md


def test_emit_code_comparison_html_table():
    """A CODE_COMPARISON table renders via the shared comparison markup:
    the mixed-table marker, <th> headers, and <pre><code> code cells. This is
    byte-identical to what the HTML converter emits (see lib/tables.py)."""
    from tomd.lib.pdf.types import Section
    sec = Section(
        kind=SectionKind.TABLE,
        text="",
        table_strategy="html_table",
        table_kind="code_comparison",
        columns=[
            [[make_span("Before")], [make_span("After")]],
            [[make_span("int verbose();")], [make_span("int proposed();")]],
        ],
    )
    md = emit_markdown({}, [sec])
    assert "<!-- tomd:mixed-table -->" in md
    assert ">Before</th>" in md
    assert ">After</th>" in md
    assert '<pre style="margin: 0;"><code>int verbose();</code></pre>' in md
    assert '<pre style="margin: 0;"><code>int proposed();</code></pre>' in md


def test_emit_spec_table_html_no_mixed_marker():
    """Other html_table kinds (here SPEC_TABLE) render as an HTML table with
    the shared <pre><code> cells but carry no mixed-table marker: only code
    comparisons are marked, matching the HTML side."""
    from tomd.lib.pdf.types import Section
    sec = Section(
        kind=SectionKind.TABLE,
        text="",
        table_strategy="html_table",
        table_kind="spec_table",
        columns=[
            [[make_span("Expression")], [make_span("Return type")]],
            [[make_span("a.foo()")], [make_span("int")]],
        ],
    )
    md = emit_markdown({}, [sec])
    assert "<!-- tomd:mixed-table -->" not in md
    assert "<table" in md
    assert '<pre style="margin: 0;"><code>' in md


def test_emit_wording_section():
    from tomd.lib.pdf.types import Section
    span = make_span("added text")
    span.wording_role = "ins"
    line = make_line(["added text"])
    line.spans[0].wording_role = "ins"
    sec = Section(
        kind=SectionKind.WORDING_ADD,
        text="added text",
        lines=[line],
    )
    md = emit_markdown({}, [sec])
    # No fenced div, and the section is uniformly inserted so its
    # redundant <ins> tag is stripped: just the prose survives.
    assert ":::" not in md
    assert "added text" in md


def test_emit_wording_remove_section():
    from tomd.lib.pdf.types import Section
    line = make_line(["removed text"])
    line.spans[0].wording_role = "del"
    sec = Section(
        kind=SectionKind.WORDING_REMOVE,
        text="removed text",
        lines=[line],
    )
    md = emit_markdown({}, [sec])
    assert ":::" not in md
    assert "removed text" in md


def _ins(text: str) -> Span:
    s = Span(text=text)
    s.wording_role = "ins"
    return s


def _del(text: str) -> Span:
    s = Span(text=text)
    s.wording_role = "del"
    return s


def _plain(text: str) -> Span:
    return Span(text=text)


class TestRenderWordingLine:
    def _line(self, *spans: Span) -> Line:
        return Line(spans=list(spans))

    def test_single_ins(self):
        result = _render_wording_line(self._line(_ins("added")))
        assert result == "<ins>added</ins>"

    def test_single_del(self):
        result = _render_wording_line(self._line(_del("removed")))
        assert result == "<del>removed</del>"

    def test_adjacent_ins_merged(self):
        result = _render_wording_line(self._line(_ins("A"), _ins("B")))
        assert result == "<ins>AB</ins>"

    def test_adjacent_del_merged(self):
        result = _render_wording_line(self._line(_del("X"), _del("Y")))
        assert result == "<del>XY</del>"

    def test_whitespace_between_same_role_absorbed(self):
        result = _render_wording_line(self._line(_ins("A"), _plain(" "), _ins("B")))
        assert result == "<ins>A B</ins>"

    def test_whitespace_between_different_roles_emitted(self):
        result = _render_wording_line(self._line(_ins("A"), _plain(" "), _del("B")))
        assert result == "<ins>A</ins> <del>B</del>"

    def test_ins_then_del_not_merged(self):
        result = _render_wording_line(self._line(_ins("add"), _del("remove")))
        assert result == "<ins>add</ins><del>remove</del>"

    def test_context_between_ins_not_merged(self):
        ctx = Span(text=" context ")
        ctx.wording_role = "context"
        result = _render_wording_line(self._line(_ins("A"), ctx, _ins("B")))
        assert result == "<ins>A</ins> context <ins>B</ins>"

    def test_many_fragmented_ins_merged(self):
        """Reproduces the p3596r0 fragment: 8 separate ins → one block."""
        spans = [
            _ins("1"), _plain(" "), _ins("Specified in:"),
            _ins(" [lifetime.outside.pointer.delete]"), _plain(" "),
            _ins("For a pointer"), _plain(" "), _ins("pointing to an object."),
        ]
        result = _render_wording_line(self._line(*spans))
        assert result.count("<ins>") == 1
        assert "1 Specified in:" in result
        assert "pointing to an object." in result

    def test_leading_whitespace_preserved(self):
        result = _render_wording_line(self._line(_plain("  "), _ins("code")))
        assert result == "  <ins>code</ins>"

    def test_empty_line(self):
        assert _render_wording_line(Line(spans=[])) == ""

    def test_non_role_angle_brackets_escaped(self):
        # Regression: a non-role code fragment like the `<float>` in
        # `vec<float>` must not be eaten by the wording div's HTML parser.
        v = Span(text="<float>", monospace=True)
        result = _render_wording_line(self._line(_del("native_simd"), v))
        assert result == "<del>native_simd</del>&lt;float&gt;"

    def test_angle_brackets_inside_role_escaped(self):
        # Brackets inside an ins/del tag are escaped too; the tag stays.
        result = _render_wording_line(
            self._line(_ins("template<class U>")))
        assert result == "<ins>template&lt;class U&gt;</ins>"

    def test_ampersand_escaped(self):
        amp = Span(text="U&& value", monospace=True)
        result = _render_wording_line(self._line(_del("x"), amp))
        assert result == "<del>x</del>U&amp;&amp; value"


def _mono_span(text: str, role: str | None = None) -> Span:
    s = Span(text=text, monospace=True)
    if role is not None:
        s.wording_role = role
    return s


def _make_wording_section(kind: SectionKind, lines: list[Line]) -> Section:
    text = "\n".join("".join(s.text for s in ln.spans) for ln in lines)
    return Section(kind=kind, text=text, lines=lines)


class TestRenderWordingSection:
    """Emit-level tests for the PDF wording renderer.

    No Pandoc fenced div is emitted. Which shape a section takes is owned
    here; whether a uniform section's now-redundant inline tags are
    stripped is delegated to ``lib.wording_cleanup`` (exercised by
    ``test_wording_cleanup.py``) and applied before this returns.
    """

    def test_uniform_add_strips_redundant_ins_tags(self):
        line = Line(spans=[_ins("• added bullet")])
        sec = _make_wording_section(SectionKind.WORDING_ADD, [line])
        out = _render_wording_section(sec)
        assert out == "• added bullet"
        assert ":::" not in out

    def test_uniform_remove_strips_redundant_del_tags(self):
        line = Line(spans=[_del("doomed paragraph")])
        sec = _make_wording_section(SectionKind.WORDING_REMOVE, [line])
        out = _render_wording_section(sec)
        assert out == "doomed paragraph"
        assert ":::" not in out

    def test_mixed_add_emits_inline_tags(self):
        line = Line(spans=[
            _plain("context "),
            _ins("inserted"),
            _plain(" tail"),
        ])
        sec = _make_wording_section(SectionKind.WORDING_ADD, [line])
        out = _render_wording_section(sec)
        assert "<ins>inserted</ins>" in out
        assert "context" in out
        assert "tail" in out

    def test_wording_neutral_keeps_all_tags(self):
        line = Line(spans=[_ins("new"), _plain(" / "), _del("old")])
        sec = _make_wording_section(SectionKind.WORDING, [line])
        out = _render_wording_section(sec)
        assert "<ins>new</ins>" in out
        assert "<del>old</del>" in out

    def test_multiline_mono_uniform_add_promoted_to_fenced_code(self):
        l1 = Line(spans=[_mono_span("template<class From, class To>", "ins")])
        l2 = Line(spans=[
            _mono_span("concept simd-consteval-broadcast-arg = see below;",
                       "ins"),
        ])
        sec = _make_wording_section(SectionKind.WORDING_ADD, [l1, l2])
        out = _render_wording_section(sec)
        assert "```cpp" in out
        assert "template<class From, class To>" in out
        assert "concept simd-consteval-broadcast-arg" in out
        # Code-promoted divs carry no inline role tags by construction.
        assert "<ins>" not in out

    def test_uniform_code_fence_preserves_indentation(self):
        # A uniform-ins monospace block whose second line sits a few
        # columns to the right (a hanging-indent continuation): the fence
        # must reconstruct that indent from glyph x-positions via CodeGrid
        # instead of flushing every line to column zero.
        s1 = Span(text="ab", monospace=True, bbox=(100.0, 0.0, 112.0, 10.0))
        s1.wording_role = "ins"
        s2 = Span(text="cd", monospace=True, bbox=(118.0, 12.0, 130.0, 22.0))
        s2.wording_role = "ins"
        sec = _make_wording_section(
            SectionKind.WORDING_ADD, [Line(spans=[s1]), Line(spans=[s2])])
        out = _render_wording_section(sec)
        assert "```cpp" in out
        assert "\nab\n" in out
        assert "\n   cd\n" in out

    def test_code_diff_normalizes_kerning_inside_del_tag(self):
        # The diff path normalizes PDF kerning in role-less context
        # already, but until M4 the inner text of an ``<ins>`` / ``<del>``
        # tag kept the raw extracted spacing. Verify that a contrived
        # ``explicit (see below)`` deletion is cleaned to
        # ``explicit(see below)`` inside the tag, matching how the same
        # token would render outside any role span.
        l1 = Line(spans=[_mono_span("template<class U>")])
        l2 = Line(spans=[
            _mono_span("  constexpr "),
            _mono_span("explicit (see below)", "del"),
            _mono_span(" basic_vec(U&& value) noexcept;"),
        ])
        sec = _make_wording_section(SectionKind.WORDING_REMOVE, [l1, l2])
        out = _render_wording_section(sec)
        assert "<del>explicit(see below)</del>" in out
        assert "explicit (see below)" not in out

    def test_uniform_code_fence_preserves_blank_lines(self):
        # A uniform-ins multi-line monospace block whose middle line is
        # blank in the source PDF (a paragraph break inside a declaration
        # list) must render with that blank line preserved inside the
        # fence, mirroring the plain code path. Dropping it silently
        # rewraps unrelated declarations together.
        s1 = Span(text="int a;", monospace=True, bbox=(0.0, 0.0, 12.0, 10.0))
        s1.wording_role = "ins"
        s3 = Span(text="int b;", monospace=True, bbox=(0.0, 24.0, 12.0, 34.0))
        s3.wording_role = "ins"
        sec = _make_wording_section(
            SectionKind.WORDING_ADD,
            [Line(spans=[s1]), Line(spans=[]), Line(spans=[s3])],
        )
        out = _render_wording_section(sec)
        assert "```cpp" in out
        assert "int a;\n\nint b;" in out

    def test_near_uniform_add_with_minority_del_falls_through_to_diff(self):
        # An almost-uniform-ins block that still carries a small ``<del>``
        # run must NOT take the directional-fence path (shape 1), which
        # drops inline role tags: the deletion would silently disappear (a
        # fidelity violation). The implicit-role share is well above
        # ``UNIFORM_ROLE_THRESHOLD`` (0.95) but the contrarian-char count
        # is non-zero, so it falls through to the fenced code diff
        # (shape 2), which keeps the ``<del>`` marker verbatim inside the
        # fence.
        ins_payload = _mono_span("x" * 200, "ins")
        del_payload = _mono_span("noexcept", "del")
        l1 = Line(spans=[ins_payload])
        l2 = Line(spans=[del_payload])
        sec = _make_wording_section(SectionKind.WORDING_ADD, [l1, l2])
        out = _render_wording_section(sec)
        assert out.splitlines()[0] == "```cpp"
        assert ":::" not in out
        assert "<del>noexcept</del>" in out

    def test_multiline_mono_mixed_emits_fenced_code_diff(self):
        # Monospace, multi-line, but NOT uniform role: a partial edit
        # inside a code listing. Emit a real ``cpp`` fence (raw angle
        # brackets / ampersands, real newlines: the C++ stays valid and
        # copy-pasteable, issue #299) with no surrounding div. The inline
        # ``<del>`` marker survives inside the fence as literal text.
        l1 = Line(spans=[_mono_span("template<class U>")])
        l2 = Line(spans=[
            _mono_span("  constexpr "),
            _mono_span("explicit(see below)", "del"),
            _mono_span(" basic_vec(U&& value) noexcept;"),
        ])
        sec = _make_wording_section(SectionKind.WORDING_REMOVE, [l1, l2])
        out = _render_wording_section(sec)
        assert out.splitlines()[0] == "```cpp"
        assert ":::" not in out
        assert "<br>" not in out
        assert "<del>explicit(see below)</del>" in out
        # Code angle brackets / ampersands are raw inside the fence.
        assert "template<class U>" in out
        assert "basic_vec(U&& value)" in out
        assert "&lt;" not in out
        assert "&amp;" not in out
        assert "  constexpr" in out

    def test_singleline_mono_bullet_not_promoted(self):
        # Bullet item like "• common_type_t<From, To> is To," can be 86%
        # monospace by character count but must stay a list item: the
        # multi-line guard in the emitter prevents promotion.
        line = Line(spans=[
            Span(text="• "),
            _mono_span("common_type_t<From, To>", "ins"),
            Span(text=" is To,"),
        ])
        line.spans[0].wording_role = "ins"
        line.spans[2].wording_role = "ins"
        sec = _make_wording_section(SectionKind.WORDING_ADD, [line])
        out = _render_wording_section(sec)
        assert "```" not in out
        assert "common_type_t&lt;From, To&gt;" in out

    def test_prose_uniform_add_not_promoted_to_code(self):
        # Pure prose, all-ins: no code fence (the post-cleanup pass
        # will drop the redundant ins tags later).
        l1 = Line(spans=[_ins("First inserted sentence.")])
        l2 = Line(spans=[_ins("Second inserted sentence.")])
        sec = _make_wording_section(SectionKind.WORDING_ADD, [l1, l2])
        out = _render_wording_section(sec)
        assert "```" not in out
        assert "First inserted sentence." in out
        assert "Second inserted sentence." in out


from tomd.lib import sanitize_metadata as _sanitize_metadata


class TestSanitizeMetadata:
    """Tests for sanitize_metadata post-processing."""

    def test_title_with_metadata_labels(self):
        md = _sanitize_metadata({
            "title": "Paper Number: P1068R11 Title: Vector API Authors: Bob"
        })
        assert md["title"] == "Vector API"

    def test_title_with_newlines(self):
        md = _sanitize_metadata({
            "title": "Unicode in the Library, Part\n1: UTF Transcoding"
        })
        assert "\n" not in md["title"]
        assert md["title"] == "Unicode in the Library, Part 1: UTF Transcoding"

    def test_title_without_labels_unchanged(self):
        md = _sanitize_metadata({"title": "A Normal Title"})
        assert md["title"] == "A Normal Title"

    def test_reply_to_double_angle_bracket(self):
        md = _sanitize_metadata({
            "reply-to": ["Mingxin Wang < <mingxwa@microsoft.com>"]
        })
        assert md["reply-to"] == ["Mingxin Wang <mingxwa@microsoft.com>"]

    def test_reply_to_non_author_filtered(self):
        md = _sanitize_metadata({
            "reply-to": [
                "Bob <bob@email.com>",
                "Target: C++26",
                "Proposed Wording for Concurrent Data",
                "Structures: Read-Copy-Update RCU",
            ]
        })
        assert md["reply-to"] == ["Bob <bob@email.com>"]

    def test_reply_to_all_filtered_removes_key(self):
        md = _sanitize_metadata({
            "reply-to": ["Target: C++26"]
        })
        assert "reply-to" not in md

    def test_no_mutation_of_input(self):
        original = {"title": "Good Title", "reply-to": ["Author <a@b.com>"]}
        result = _sanitize_metadata(original)
        assert result is not original


# -- _render_paragraph_spans: sec.text fallback when lines is empty --
# Used by the sub-caption insertion path in pipeline.py: inserted
# PARAGRAPH sections carry pre-built ``text`` (``*<escaped>*``) and
# ``lines=[]``; the fallback below renders the text verbatim,
# bypassing _render_line_spans so the *...* wrapper survives.


from tomd.lib.pdf.emit import _render_paragraph_spans, _escape_italic_text
from tomd.lib.pdf.types import Section


def test_render_paragraph_spans_falls_back_to_text_when_lines_empty():
    sec = Section(
        kind=SectionKind.PARAGRAPH,
        text="*(a) The italic caption.*",
        confidence=Confidence.MEDIUM,
        page_num=5,
        lines=[],
    )
    assert _render_paragraph_spans(sec) == "*(a) The italic caption.*"


def test_render_paragraph_spans_uses_lines_when_present():
    """Sanity guard: the fallback only fires when lines is empty.
    Existing PARAGRAPH sections with non-empty lines still go through
    the span-rendering path."""
    sec = make_section("Hello world")
    # make_section builds one line containing the text.
    out = _render_paragraph_spans(sec)
    assert "Hello world" in out


def test_emit_markdown_renders_inserted_sub_caption_paragraph():
    """End-to-end: an IMAGE section followed by a synthesised
    sub-caption PARAGRAPH (lines=[], text=*...*) renders as the
    italic caption paragraph + a blank line + the italic sub-caption.
    No image syntax is emitted (#408)."""
    from tomd.lib.pdf.images import ExtractedImage
    img = ExtractedImage(
        page=6, index_on_page=1, ext="png", bytes=b"",
        bbox=(86, 0, 506, 284),
        suggested_alt="Figure 1: ...",
        stored_filename="p3127r1-fig6-1.png",
        xref=0, source="vector",
        sub_captions=(("a", "(a) An undirected graph."),),
        caption_body_dropped=True,
    )
    image_section = Section(
        kind=SectionKind.IMAGE, text="",
        confidence=Confidence.MEDIUM, page_num=5,
        image_ref=img,
    )
    sub_section = Section(
        kind=SectionKind.PARAGRAPH,
        text="*(a) An undirected graph.*",
        confidence=Confidence.MEDIUM,
        page_num=5,
        lines=[],
    )
    md = emit_markdown({}, [image_section, sub_section])
    assert "![" not in md
    assert "p3127r1-fig6-1.png" not in md
    assert "*Figure 1: ...*" in md
    assert "*(a) An undirected graph.*" in md
    # The caption paragraph appears BEFORE the sub-caption.
    assert md.index("*Figure 1: ...*") < md.index("*(a)")


def test_emit_markdown_image_caption_not_reemitted_when_body_kept():
    """#408 regression (P0957R8 Fig 1 shape): when the equality gate
    KEPT the body caption section (caption merged with trailing prose),
    the IMAGE section must render as nothing - re-emitting the alt as
    italic would duplicate the caption that is still visible in the
    body."""
    from tomd.lib.pdf.images import ExtractedImage
    img = ExtractedImage(
        page=4, index_on_page=1, ext="png", bytes=b"",
        bbox=(86, 0, 506, 284),
        suggested_alt="Figure 1: Expected memory layout",
        stored_filename="p0957r8-fig4-1.png",
        xref=0, source="raster",
    )
    assert img.caption_body_dropped is False
    image_section = Section(
        kind=SectionKind.IMAGE, text="",
        confidence=Confidence.MEDIUM, page_num=3,
        image_ref=img,
    )
    body_caption = make_section("Figure 1: Expected memory layout")
    md = emit_markdown({}, [image_section, body_caption])
    assert "![" not in md
    assert "p0957r8-fig4-1.png" not in md
    # The caption appears exactly once, from the kept body section.
    assert md.count("Figure 1: Expected memory layout") == 1
    assert "*Figure 1: Expected memory layout*" not in md


# -- _escape_italic_text: markdown-escape correctness ---------------


def test_escape_italic_text_escapes_asterisk():
    assert _escape_italic_text("a * b") == r"a \* b"


def test_escape_italic_text_escapes_underscore():
    assert _escape_italic_text("foo_bar") == r"foo\_bar"


def test_escape_italic_text_escapes_backtick():
    assert _escape_italic_text("code `x` here") == r"code \`x\` here"


def test_escape_italic_text_escapes_backslash():
    assert _escape_italic_text("path\\to\\file") == r"path\\to\\file"


def test_escape_italic_text_escapes_leading_list_marker():
    assert _escape_italic_text("- a list looking line") == r"\- a list looking line"
    # Asterisks are escaped first; the leading-block branch only adds
    # a backslash for "-", "+", ">", "#". The escaped "*" is no longer
    # parsed as a list marker.
    assert _escape_italic_text("* asterisk first") == r"\* asterisk first"
    assert _escape_italic_text("+ plus first") == r"\+ plus first"


def test_escape_italic_text_escapes_leading_blockquote():
    assert _escape_italic_text("> quoted thing") == r"\> quoted thing"


def test_escape_italic_text_escapes_leading_heading():
    assert _escape_italic_text("# heading-shaped") == r"\# heading-shaped"


def test_escape_italic_text_escapes_leading_ordered_list():
    """`1.` at the start would parse as an ordered list marker - the
    period must be escaped so the paragraph stays a paragraph."""
    assert _escape_italic_text("1. first item") == r"1\. first item"
    assert _escape_italic_text("42. answer") == r"42\. answer"


def test_escape_italic_text_passes_plain_text():
    assert _escape_italic_text("plain caption text") == "plain caption text"


def test_escape_italic_text_handles_empty():
    assert _escape_italic_text("") == ""


_CHAR_W = 6.0


def _gspan(text, x0, y0, mono=False):
    """A span on a 6pt/char monospace grid, baseline height 10pt."""
    n = max(len(text.replace(" ", "")), 1)
    return Span(
        text=text, font_name="F", font_size=10.0, monospace=mono,
        bbox=(x0, y0, x0 + _CHAR_W * n, y0 + 10.0),
    )


def _gline(spans):
    return Line(spans=spans)


def _gutter_section(rows):
    """Build a CODE section from (number_x0, num_text, code_x0, code_text) rows.

    Each row contributes two interleaved lines (the non-monospace gutter
    number, then the monospace code), sharing one y-band, mirroring how
    extraction emits P0876's fiber listings.
    """
    lines = []
    for i, (num_x0, num_text, code_x0, code_text) in enumerate(rows):
        y = i * 12.0
        if num_text is not None:
            lines.append(_gline([_gspan(num_text, num_x0, y, mono=False)]))
        lines.append(_gline([_gspan(code_text, code_x0, y, mono=True)]))
    return Section(kind=SectionKind.CODE, text="", lines=lines, fence_lang="cpp")


class TestCodeGutter:
    def test_gutter_kept_and_indentation_restored(self):
        # Top-level code at col 3 (x=24), nested code at col 5 (x=36);
        # single-digit gutter numbers at x=6 (grid origin).
        sec = _gutter_section([
            (6, "1", 24, "a();"),
            (6, "2", 36, "b();"),
            (6, "3", 24, "c();"),
        ])
        out = _render_code_block(sec)
        lines = out.splitlines()
        assert lines[0] == "```cpp"
        assert lines[-1] == "```"
        body = lines[1:-1]
        assert body == ["1  a();", "2    b();", "3  c();"]
        # Nested line keeps 2 extra spaces of code indent over top-level.
        assert body[1].index("b();") - body[0].index("a();") == 2

    def test_gutter_numbers_right_aligned(self):
        # 9 is shifted right so its right edge aligns with the two-digit
        # numbers' right edge (PDF right-aligned gutter). Origin is the
        # leftmost gutter glyph (x=6, the two-digit numbers).
        sec = _gutter_section([
            (12, "9", 24, "a();"),
            (6, "10", 24, "b();"),
            (6, "11", 24, "c();"),
        ])
        body = _render_code_block(sec).splitlines()[1:-1]
        assert body[0].startswith(" 9 ")
        assert body[1].startswith("10 ")
        assert body[2].startswith("11 ")

    def test_below_threshold_is_not_a_gutter(self):
        # Only two numeric lines: not enough to be a gutter column.
        sec = _gutter_section([
            (6, "1", 24, "a();"),
            (6, "2", 24, "b();"),
        ])
        assert _detect_code_gutter(sec) is None

    def test_non_increasing_is_not_a_gutter(self):
        sec = _gutter_section([
            (6, "1", 24, "a();"),
            (6, "1", 24, "b();"),
            (6, "1", 24, "c();"),
        ])
        assert _detect_code_gutter(sec) is None

    def test_monospace_number_is_not_a_gutter_cell(self):
        # Bare numbers that are themselves monospace (at the code margin)
        # are code, not a gutter, and must not trigger the gutter path.
        lines = [
            _gline([_gspan("10", 24, 0.0, mono=True)]),
            _gline([_gspan("20", 24, 12.0, mono=True)]),
            _gline([_gspan("30", 24, 24.0, mono=True)]),
        ]
        sec = Section(kind=SectionKind.CODE, text="", lines=lines,
                      fence_lang="cpp")
        assert _detect_code_gutter(sec) is None

    def test_plain_code_block_without_gutter_unchanged(self):
        sec = _gutter_section([
            (None, None, 0, "int main() {"),
            (None, None, 12, "return 0;"),
            (None, None, 0, "}"),
        ])
        assert _detect_code_gutter(sec) is None
        body = _render_code_block(sec).splitlines()[1:-1]
        assert body[0] == "int main() {"
        assert body[1] == "  return 0;"
        assert body[2] == "}"

    def test_runaway_code_column_pinned_to_zero(self):
        # A right-margin element (e.g. a stable-name anchor) split onto
        # its own line at x=500 would otherwise produce a code_col in
        # the high 80s on the 6pt grid (round((500-6)/6) = 82), pushing
        # the real code past the right margin. The gutter cap rewrites
        # an implausibly deep column back to 0 so the code stays
        # readable; line numbers and the regular rows are untouched.
        sec = _gutter_section([
            (6, "1", 24, "a();"),
            (6, "2", 24, "b();"),
            (6, "3", 24, "c();"),
            (6, "4", 500, "[anchor]"),
        ])
        body = _render_code_block(sec).splitlines()[1:-1]
        assert body[0] == "1  a();"
        # The fourth row's code starts at column 2 (right after the
        # gutter number + its spacer, because the cap pinned the
        # measured column to 0 and the buf-overflow fallback nudged
        # past the number).
        assert body[3] == "4 [anchor]"


class TestListMarkerNormalization:
    """One marker, "-", at every depth and from every source shape (#303)."""

    def test_literal_asterisk_marker_becomes_dash(self):
        """Some PDFs typeset bullets as plain "*", so no BULLET_CHARS glyph exists."""
        sec = make_section("* Intel oneAPI Math Kernel Library",
                           kind=SectionKind.LIST)
        md = emit_markdown({}, [sec])
        assert "- Intel oneAPI Math Kernel Library" in md
        assert "* Intel" not in md

    def test_trademark_asterisk_inside_item_text_survives(self):
        """Only the leading marker is rewritten; "Java*" is content."""
        sec = make_section("* Java* java.util.Random", kind=SectionKind.LIST)
        md = emit_markdown({}, [sec])
        assert "- Java* java.util.Random" in md

    def test_nested_bullet_keeps_dash_and_indent(self):
        sec = make_section("○ nested", kind=SectionKind.LIST, indent_level=1)
        md = emit_markdown({}, [sec])
        assert "  - nested" in md

    def test_ordinal_marker_is_not_rewritten(self):
        sec = make_section("2. The override keyword shall be added",
                           kind=SectionKind.LIST)
        md = emit_markdown({}, [sec])
        assert "2. The override keyword shall be added" in md

    def test_leading_emphasis_is_not_a_list_marker(self):
        """The "\\s+" in _ASTERISK_MARKER_RE is what keeps "*word*" intact.

        Loosening it to "\\s*" would eat the opening emphasis delimiter and
        leave the closing one behind, silently corrupting the text. Pinned
        because nothing else in the suite would go red for it.
        """
        sec = make_section("*emphasized* lead-in", kind=SectionKind.LIST)
        md = emit_markdown({}, [sec])
        assert "*emphasized* lead-in" in md
        assert "- emphasized" not in md


class TestEmdashBulletItems:
    """Em-dash enumerations must not collapse into one paragraph (#303)."""

    def test_wrapped_item_folds_into_its_marker(self):
        items = _emdash_bullet_items([
            "— (5.1) if their header-names identify different headers or",
            "source files, they import distinct header units;",
            "— (5.2) otherwise, they import the same header unit;",
        ])
        assert items == [
            "- (5.1) if their header-names identify different headers or "
            "source files, they import distinct header units;",
            "- (5.2) otherwise, they import the same header unit;",
        ]

    def test_marker_alone_on_its_own_line(self):
        """Standardese lays the dash, the number and the text out as columns."""
        items = _emdash_bullet_items([
            "—", "(1.1)", "a `#` preprocessing token, or",
            "—", "(1.2)", "an `import` preprocessing token, or",
        ])
        assert items == [
            "- (1.1) a `#` preprocessing token, or",
            "- (1.2) an `import` preprocessing token, or",
        ]

    def test_all_marked_single_line_still_becomes_an_item(self):
        """Pre-existing behaviour: an all-marked block commits at one item."""
        assert _emdash_bullet_items(["— only item"]) == ["- only item"]

    def test_one_marker_then_unmarked_lines_stays_prose(self):
        """Below _EMDASH_LIST_MIN_ITEMS this is a paragraph opening on a dash."""
        assert _emdash_bullet_items([
            "— a dash-led sentence that then",
            "wraps onto a second line",
        ]) is None

    def test_block_not_opening_on_a_marker_is_not_a_list(self):
        assert _emdash_bullet_items(["lead-in text", "— an item"]) is None

    def test_end_note_dash_is_not_a_marker(self):
        """"—end note]" has no whitespace after the dash, so it is content."""
        assert _emdash_bullet_items(["—end note]"]) is None

    def test_lone_marker_with_no_text_is_not_a_list(self):
        assert _emdash_bullet_items(["—"]) is None

    def test_trailing_bare_marker_emits_no_empty_bullet(self):
        """A text-less marker is not an item, so it never emits "- "."""
        assert _emdash_bullet_items(["— a", "—"]) == ["- a"]

    def test_trailing_bare_marker_does_not_pad_prose_to_the_minimum(self):
        """The empty item must not count toward _EMDASH_LIST_MIN_ITEMS."""
        assert _emdash_bullet_items([
            "— a dash-led sentence that then",
            "wraps onto a second line",
            "—",
        ]) is None

    def test_wrapped_enumeration_renders_as_a_list_through_emit(self):
        lines = [make_line(["—"]), make_line(["(5.1)"]),
                 make_line(["if their header-names differ,"]),
                 make_line(["they import distinct header units;"]),
                 make_line(["—"]), make_line(["(5.2)"]),
                 make_line(["otherwise, the same header unit."])]
        sec = make_section("\n".join(ln.text for ln in lines),
                           kind=SectionKind.PARAGRAPH, lines=lines)
        md = emit_markdown({}, [sec])
        assert "- (5.1) if their header-names differ, they import distinct " \
               "header units;" in md
        assert "- (5.2) otherwise, the same header unit." in md


# --- pipe-table cell flattening (issue #360) --------------------------------
#
# A wrapped prose cell reaches the emitter as several spans separated by a
# whitespace-only marker. Producers spell that marker inconsistently, so the
# flattening must key on the shape (whitespace containing a newline) rather
# than on the literal "\n". Since port step 11 the lines of a wrapped cell
# are joined with <br> (the tomd-tables cell renderer), approved 2026-10-28.


def _pipe_table(cells):
    """Render a one-data-row, N-column pipe table and return its lines."""
    header = [[make_span(f"H{i}")] for i in range(len(cells))]
    sec = Section(kind=SectionKind.TABLE, text="", confidence=Confidence.HIGH,
                  columns=[header, cells], table_strategy="pipe_table")
    return emit_markdown({}, [sec]).splitlines()


class TestFlattenPipeCell:
    def test_bare_newline_marker_joins_with_br(self):
        cell = [make_span("Allow "), make_span("\n"),
                make_span("incomplete types")]
        row = _pipe_table([cell, [make_span("ok")]])[-1]
        assert row == "| Allow<br>incomplete types | ok |"

    def test_marker_padded_with_spaces_joins_with_br(self):
        cell = [make_span("Allow "), make_span("  \n  "),
                make_span("incomplete types")]
        row = _pipe_table([cell, [make_span("ok")]])[-1]
        assert row == "| Allow<br>incomplete types | ok |"

    def test_marker_without_surrounding_space_still_joins(self):
        cell = [make_span("sockets"), make_span("\n"), make_span("TLS")]
        row = _pipe_table([cell, [make_span("ok")]])[-1]
        assert row == "| sockets<br>TLS | ok |"

    def test_embedded_newline_joins_with_br(self):
        """The wrap point survives inside a span, not as its own marker."""
        cell = [make_span("Bit-precise integers \nSlides for P3666R1")]
        row = _pipe_table([cell, [make_span("ok")]])[-1]
        assert row == "| Bit-precise integers<br>Slides for P3666R1 | ok |"

    def test_a_cell_never_emits_a_literal_newline(self):
        # words, not single letters: letters stacked in a narrow cell are
        # one word ("S" / "F" -> "SF"), see test_table_cell_render.py
        cell = [make_span("alpha"), make_span("\n\n"), make_span("beta"),
                make_span(" \n"), make_span("gamma")]
        lines = _pipe_table([cell, [make_span("ok")]])
        assert lines[-1] == "| alpha<br>beta<br>gamma | ok |"
        assert not any("\n" in line for line in lines)
