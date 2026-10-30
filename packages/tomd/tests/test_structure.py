"""Tests for lib.pdf.structure."""

import math

from conftest import make_block, make_line, make_section, make_span
from tomd.domain.elements import Confidence
from tomd.lib.pdf.types import (
    Block, Line, Span, Section, SectionKind,
)
from tomd.lib.pdf.structure import (
    compare_extractions, structure_sections, structure_body,
    drop_leaked_toc_entries,
    heading_confidence, _extract_metadata,
    _detect_body_size, _validate_nesting,
    _rank_font_sizes, _title_section_for_ranking,
    _demote_repeated_low_confidence_numbers,
    _section_top_y, _reorders_only_monospace, _page_is_multicolumn,
    _is_title_like_straggler, _is_empty_heading, _straggler_forward_references,
    _run_recurrence_density, _compute_body_start,
    _classify_wording_sections, _split_embedded_code,
    _coalesce_code_paragraphs,
    _line_is_mono_code, _absorb_mono_code_orphans,
    _classify_code_line, _is_narrative_continuation, _trim_narrative_from_code,
    _absorb_trailing_label_into_code, _is_tail_prose,
    _peel_trailing_prose_from_code,
    _weak_heading_qualifies, _merge_paragraphs,
)


class TestMergeParagraphsDehyphenation:
    """#413: a block boundary after a hyphen runs T9's pair rule, so the
    merged paragraph never reads ``floating- point``."""

    @staticmethod
    def _para(text):
        return make_section(text, lines=[make_line([text])])

    def test_compound_boundary_keeps_hyphen_and_pulls_word_up(self):
        evidence = self._para("All floating-point types.")
        prev = self._para("uses a floating-")
        cur = self._para("point value.")
        merged = _merge_paragraphs([evidence, prev, cur])
        assert len(merged) == 2
        assert merged[1].text == "uses a floating-point value."
        assert [ln.text for ln in merged[1].lines] == [
            "uses a floating-point", "value."]

    def test_syllable_boundary_glues(self):
        prev = self._para("the imple-")
        cur = self._para("mentation follows.")
        merged = _merge_paragraphs([prev, cur])
        assert len(merged) == 1
        assert merged[0].text == "the implementation follows."
        assert [ln.text for ln in merged[0].lines] == [
            "the implementation", "follows."]

    def test_fully_consumed_first_line_is_dropped(self):
        prev = self._para("the imple-")
        cur = make_section("mentation\nfollows.", lines=[
            make_line(["mentation"]), make_line(["follows."])])
        merged = _merge_paragraphs([prev, cur])
        assert merged[0].text == "the implementation\nfollows."
        assert [ln.text for ln in merged[0].lines] == [
            "the implementation", "follows."]

    def test_plain_merge_unchanged(self):
        prev = self._para("a sentence that")
        cur = self._para("continues here.")
        merged = _merge_paragraphs([prev, cur])
        assert merged[0].text == "a sentence that continues here."

    def test_text_lines_mismatch_falls_back_to_plain_merge(self):
        """Section text that does not carry the boundary tokens of its
        lines keeps text and lines in step: neither is dehyphenated."""
        prev = make_section("the imple-", lines=[make_line(["the imple-"])])
        cur = make_section("mentation follows.",
                           lines=[make_line(["[fn] mentation follows."])])
        merged = _merge_paragraphs([prev, cur])
        assert merged[0].text == "the imple- mentation follows."
        assert [ln.text for ln in merged[0].lines] == [
            "the imple-", "[fn] mentation follows."]


class TestMergeParagraphsInlineContinuation:
    """#413: a block that opens with ``(`` or an inline code span one wrap
    pitch below a sentence fragment continues that sentence, when the
    geometry proves the line wrapped."""

    FS = 8.0
    LINE = 10.0  # baseline-to-baseline at 8pt (pitch 1.25 font sizes)
    X0 = 72.0
    RIGHT = 500.0  # the text margin
    BASELINE = 0.8  # baseline sits this far below the line top, in font sizes

    def _line(self, spans, top, *, x0=X0, x1=RIGHT, page=1, font_size=FS,
              mono=None):
        mono = mono or [False] * len(spans)
        origin = (x0, top + self.BASELINE * font_size)
        return Line(
            spans=[make_span(t, font_size=font_size, monospace=m, origin=origin)
                   for t, m in zip(spans, mono)],
            bbox=(x0, top, x1, top + font_size), page_num=page)

    def _para(self, spans, top, *, page=1, font_size=FS, mono=None,
              x0=X0, x1=RIGHT):
        """A one-line block; ``x1`` is where its text ends."""
        line = self._line(spans, top, page=page, font_size=font_size,
                          mono=mono, x0=x0, x1=x1)
        return make_section(line.text, lines=[line], page_num=page,
                            font_size=font_size)

    def _body(self, page=1, pitch=LINE):
        """Four full-width body lines at ``pitch``: the witnesses that
        establish the text margin and the wrap pitch
        (``_LAYOUT_WITNESS_MIN``)."""
        lines = [self._line([f"Body line {i} that runs to the margin."],
                            20.0 + i * pitch, page=page) for i in range(4)]
        return make_section("\n".join(ln.text for ln in lines), lines=lines,
                            page_num=page, font_size=self.FS)

    def _merged(self, *secs, pitch=LINE):
        """Sections after the merge, without the witness body."""
        return _merge_paragraphs([self._body(pitch=pitch), *secs])[1:]

    # -- positive: the line wrapped -------------------------------------

    def test_bracket_start_one_line_below_merges(self):
        prev = self._para(["for a given input order and topology coordinate"], 100.0)
        cur = self._para(["(lane count L), the expression is unique."],
                         100.0 + self.LINE, x1=380.0)
        assert [s.text for s in self._merged(prev, cur)] == [
            "for a given input order and topology coordinate "
            "(lane count L), the expression is unique."]

    def test_square_bracket_start_merges(self):
        prev = self._para(["specification models in"], 100.0)
        cur = self._para(["[numerics.defns]. Both preserve order."],
                         100.0 + self.LINE, x1=300.0)
        assert len(self._merged(prev, cur)) == 1

    def test_inline_code_start_on_mixed_line_merges(self):
        prev = self._para(["permits reassociation (and, under"], 100.0)
        cur = self._para(["GENERALIZED_SUM", ", operand reordering); no wrapper"],
                         100.0 + self.LINE, mono=[True, False], x1=420.0)
        merged = self._merged(prev, cur)
        assert len(merged) == 1
        assert merged[0].text.endswith(
            "under GENERALIZED_SUM, operand reordering); no wrapper")

    def test_next_word_that_would_not_fit_confirms_the_wrap(self):
        """Ragged right: the line stopped 45pt short because the 15-char
        word `(parenthesized)` needed ~65pt (P4016R0 p.5)."""
        prev = self._para(["operands are combined and how they are grouped"],
                          100.0, x1=self.RIGHT - 45.0)
        cur = self._para(["(parenthesized) may produce different results."],
                         100.0 + self.LINE)
        assert len(self._merged(prev, cur)) == 1

    def test_first_line_indent_still_merges(self):
        """P0957R8: a one-line paragraph with an 8.5pt first-line indent
        wraps to the paragraph's left edge."""
        prev = self._para(["we may need to update the code. For example, what if"],
                          100.0, x0=self.X0 + 8.5)
        cur = self._para(["DoSomethingWithDrawable", " needs to call Area()?"],
                         100.0 + self.LINE, mono=[True, False], x1=300.0)
        assert len(self._merged(prev, cur)) == 1

    def test_slight_box_overlap_still_merges(self):
        """Tight leading: MuPDF's line boxes overlap by a fraction of the
        font size (P0957R8: -0.37); the baselines are still one pitch apart."""
        pitch = 0.95 * self.FS
        prev = self._para(["for a given input order and topology coordinate"], 100.0)
        cur = self._para(["(lane count L), the expression is unique."],
                         100.0 + pitch, x1=380.0)
        assert len(self._merged(prev, cur, pitch=pitch)) == 1

    def test_second_line_of_paragraph_wraps_at_its_left_edge(self):
        """The previous block already has two lines (first-line indent,
        then the edge); the continuation aligns with the last one."""
        lines = [self._line(["A paragraph whose first line is indented and"],
                            90.0, x0=self.X0 + 8.5),
                 self._line(["whose second line runs to the margin without"],
                            100.0)]
        prev = make_section("\n".join(ln.text for ln in lines), lines=lines,
                            page_num=1, font_size=self.FS)
        cur = self._para(["(a parenthetical) closing it."], 110.0, x1=300.0)
        assert len(self._merged(prev, cur)) == 1

    def test_citation_bracket_followed_by_lowercase_merges(self):
        prev = self._para(["the semantics are the ones described in"], 100.0)
        cur = self._para(["[4] and refined by [5]."], 110.0, x1=200.0)
        assert len(self._merged(prev, cur)) == 1

    def test_previous_block_spanning_pages_merges_on_its_last_page(self):
        """After a lowercase merge across a page break the section's page
        is still the first page; the wrap test looks at the lines."""
        lines = [self._line(["a sentence that starts on one page and"], 700.0,
                            page=1),
                 self._line(["continues at the top of the next, right up to"],
                            72.0, page=2)]
        prev = make_section("\n".join(ln.text for ln in lines), lines=lines,
                            page_num=1, font_size=self.FS)
        cur = self._para(["(the margin) where it wraps again."], 82.0, page=2,
                         x1=300.0)
        assert len(_merge_paragraphs([self._body(1), prev, cur])) == 2

    # -- negative: lexical ------------------------------------------------

    def test_all_monospace_line_is_code_not_continuation(self):
        prev = self._para(["The call reads"], 100.0)
        cur = self._para(["(void)reduce(v.begin(), v.end());"], 100.0 + self.LINE,
                         mono=[True])
        assert len(self._merged(prev, cur)) == 2

    def test_terminal_punctuation_blocks_merge(self):
        prev = self._para(["The sentence ends here."], 100.0)
        cur = self._para(["(Parenthetical aside follows.)"], 100.0 + self.LINE)
        assert len(self._merged(prev, cur)) == 2

    def test_terminal_punctuation_behind_closing_quote_blocks_merge(self):
        prev = self._para(['the paper calls this "unified interface."'], 100.0)
        cur = self._para(["(Section 5 discusses the cost.)"], 100.0 + self.LINE)
        assert len(self._merged(prev, cur)) == 2

    def test_trailing_hyphen_is_left_to_the_lowercase_path(self):
        prev = self._para(["a topology-"], 100.0)
        cur = self._para(["(lane count) mapping"], 100.0 + self.LINE)
        assert len(self._merged(prev, cur)) == 2

    def test_enumeration_labels_are_not_continuations(self):
        for label in ("(a) keep", "(2) second", "(iii) third", "B) next"):
            prev = self._para(["The options are laid out on the line above"], 100.0)
            cur = self._para([f"{label} item text"], 100.0 + self.LINE)
            assert len(self._merged(prev, cur)) == 2, label

    def test_bracket_label_opening_an_entry_is_not_a_continuation(self):
        """A bibliography label or note opener follows the closing bracket
        with `=`, a capitalised word or nothing: not a sentence running on."""
        for start in ("[GB-PAR] = https://godbolt.org/z/x", "[4] Smith, J.",
                      "[N4950] Working Draft", "[Note: This differs.]"):
            prev = self._para(["a line that runs right up to the text margin"],
                              100.0)
            cur = self._para([start], 100.0 + self.LINE, x1=300.0)
            assert len(self._merged(prev, cur)) == 2, start

    # -- negative: geometry -----------------------------------------------

    def test_paragraph_gap_does_not_merge(self):
        prev = self._para(["a fragment without a period"], 100.0)
        cur = self._para(["(A new paragraph in parentheses.)"], 100.0 + self.FS * 1.9)
        assert len(self._merged(prev, cur)) == 2

    def test_paragraph_spacing_does_not_merge(self):
        """Word's `6pt after` on 12pt text is half a font size on top of
        the pitch, the tightest common paragraph spacing; a wrapped line
        sits at the pitch exactly."""
        prev = self._para(["a fragment without a period that fills the line"],
                          100.0)
        cur = self._para(["(A new paragraph in parentheses.)"],
                         100.0 + self.LINE + 0.5 * self.FS)
        assert len(self._merged(prev, cur)) == 2

    def test_pitch_within_tolerance_merges(self):
        prev = self._para(["a fragment without a period that fills the line"],
                          100.0)
        cur = self._para(["(continued) here."], 100.0 + self.LINE + 0.1 * self.FS,
                         x1=200.0)
        assert len(self._merged(prev, cur)) == 1

    def test_document_without_a_pitch_never_merges(self):
        """Three one-line paragraphs establish a margin but no wrap
        pitch (no multi-line section, no lowercase boundary)."""
        full = [self._para([f"Sentence {i} that runs to the margin."],
                           20.0 + i * self.LINE) for i in range(3)]
        prev = self._para(["a fragment without a period that fills the line"],
                          100.0)
        cur = self._para(["(continued) here."], 100.0 + self.LINE, x1=200.0)
        assert len(_merge_paragraphs([*full, prev, cur])) == 5

    def test_multi_line_block_does_not_take_an_outdented_paragraph(self):
        """A list item's second line sits at the text indent; a body
        paragraph 16pt to its left is a new block, not a first-line indent."""
        lines = [self._line(["- an item whose text wraps onto a second"], 90.0,
                            x0=self.X0 + 16.0),
                 self._line(["line that runs right up to the margin without"],
                            100.0, x0=self.X0 + 16.0)]
        prev = make_section("\n".join(ln.text for ln in lines),
                            kind=SectionKind.LIST, lines=lines, page_num=1,
                            font_size=self.FS)
        cur = self._para(["GENERALIZED_SUM", " permits reassociation."], 110.0,
                         mono=[True, False], x1=230.0)
        assert len(self._merged(prev, cur)) == 2

    def test_page_change_blocks_merge(self):
        prev = self._para(["a fragment without a period"], 700.0, page=1)
        cur = self._para(["(continued) on the next page."], 72.0, page=2)
        assert len(_merge_paragraphs([self._body(1), prev, self._body(2), cur])) == 4

    def test_font_change_blocks_merge(self):
        """A 0.9pt smaller face (8.1pt body, 7.2pt footnote) is a
        different block, not a wrapped line."""
        prev = self._para(["a fragment without a period"], 100.0)
        cur = self._para(["(footnote text in a smaller face)"], 100.0 + self.LINE,
                         font_size=self.FS - 0.9)
        assert len(self._merged(prev, cur)) == 2

    def test_short_last_line_is_not_a_wrap(self):
        """Definition lists: the previous line stops well before the
        margin although the next word would have fit, so nothing wrapped.
        P4016R0 p.25 `V be ...,` / `A be ...:` is this shape."""
        prev = self._para(["V", " be the value type of the input sequence elements,"],
                          100.0, mono=[True, False], x1=300.0)
        cur = self._para(["A", " be the reduction state type:"],
                         100.0 + self.LINE, mono=[True, False], x1=220.0)
        assert len(self._merged(prev, cur)) == 2

    def test_bibliography_url_then_label_is_not_a_wrap(self):
        prev = self._para(["[GB-SEQ] = https://godbolt.org/z/8EEhEqrz6"], 100.0,
                          x1=260.0)
        cur = self._para(["(single-threaded reference; faithful implementation)"],
                         100.0 + self.LINE, x1=420.0)
        assert len(self._merged(prev, cur)) == 2

    def test_bibliography_entries_at_line_pitch_stay_apart(self):
        """A long URL ending near the margin followed by the next label
        one pitch below: the label is lexically an entry opener."""
        prev = self._para(["[GB-SEQ] = https://godbolt.org/z/a/very/long/path/x"],
                          100.0, x1=self.RIGHT - 20.0)
        cur = self._para(["[GB-PAR] = https://godbolt.org/z/b"], 100.0 + self.LINE,
                         x1=300.0)
        assert len(self._merged(prev, cur)) == 2

    def test_page_without_a_margin_never_merges(self):
        """Two short blocks alone on a page establish no text margin, so
        the wrap proof has nothing to measure against."""
        prev = self._para(["V", " be the value type of the input sequence elements,"],
                          100.0, mono=[True, False], x1=300.0)
        cur = self._para(["A", " be the reduction state type:"],
                         100.0 + self.LINE, mono=[True, False], x1=220.0)
        assert len(_merge_paragraphs([prev, cur])) == 2

    def test_lone_long_line_is_not_a_margin(self):
        """One URL wider than everything else is an outlier, not the
        margin; the body lines still establish it."""
        url = self._para(["https://example.invalid/a/very/long/path/that/overflows"],
                         60.0, x1=self.RIGHT + 40.0)
        prev = self._para(["For a given input order and topology coordinate"], 100.0)
        cur = self._para(["(lane count L), the expression is unique."],
                         100.0 + self.LINE, x1=380.0)
        assert len(_merge_paragraphs([self._body(), url, prev, cur])) == 3

    def test_other_column_does_not_merge(self):
        prev = self._para(["left column fragment without"], 100.0,
                          x0=57.0, x1=290.0)
        cur = self._para(["(right column) starts here"], 100.0 + self.LINE,
                         x0=310.0, x1=540.0)
        assert len(self._merged(prev, cur)) == 2

    def test_outdented_label_does_not_merge(self):
        """Hanging indent: item text at the text indent, the next label
        outdented by more than a first-line indent."""
        prev = self._para(["item text that runs to the margin without a stop"],
                          100.0, x0=self.X0 + 2.5 * self.FS)
        cur = self._para(["(see note) opens the next item"], 100.0 + self.LINE,
                         x1=300.0)
        assert len(self._merged(prev, cur)) == 2

    def test_list_item_without_stop_keeps_following_paragraph(self):
        prev = make_section("- third bullet without stop", kind=SectionKind.LIST,
                            lines=[self._line(["- third bullet without stop"],
                                              100.0, x1=210.0)],
                            page_num=1, font_size=self.FS)
        cur = self._para(["GENERALIZED_SUM", " permits reassociation."],
                         100.0 + self.LINE, mono=[True, False], x1=230.0)
        assert len(self._merged(prev, cur)) == 2

    def test_block_above_on_same_baseline_does_not_merge(self):
        """Side-by-side blocks (table cells) have a negative y-gap of a
        full line height."""
        prev = self._para(["left cell text"], 100.0)
        cur = self._para(["(right cell)"], 100.0)
        assert len(self._merged(prev, cur)) == 2


class TestHeadingConfidence:
    def test_number_font_bold(self):
        level, conf = heading_confidence(True, 2, 2, True, False)
        assert level == 2
        assert conf == Confidence.HIGH

    def test_number_font_no_bold(self):
        level, conf = heading_confidence(True, 2, 2, False, False)
        assert level == 2
        assert conf == Confidence.MEDIUM

    def test_number_font_disagree(self):
        level, conf = heading_confidence(True, 2, 3, False, False)
        assert level == 2
        assert conf == Confidence.MEDIUM

    def test_number_bold_no_font(self):
        level, conf = heading_confidence(True, 2, None, True, False)
        assert level == 2
        assert conf == Confidence.MEDIUM

    def test_number_alone(self):
        level, conf = heading_confidence(True, 2, None, False, False)
        assert level == 2
        assert conf == Confidence.LOW

    def test_font_known_bold(self):
        level, conf = heading_confidence(False, 0, 1, True, True)
        assert level == 2
        assert conf == Confidence.HIGH

    def test_font_known_no_bold(self):
        level, conf = heading_confidence(False, 0, 1, False, True)
        assert level == 2
        assert conf == Confidence.MEDIUM

    def test_font_bold(self):
        level, conf = heading_confidence(False, 0, 1, True, False)
        assert level == 2
        assert conf == Confidence.MEDIUM

    def test_font_alone(self):
        level, conf = heading_confidence(False, 0, 1, False, False)
        assert level == 2
        assert conf == Confidence.LOW

    def test_known_alone(self):
        level, conf = heading_confidence(False, 0, None, False, True)
        assert level == 2
        assert conf == Confidence.LOW

    def test_nothing(self):
        level, conf = heading_confidence(False, 0, None, False, False)
        assert level == 0
        assert conf == Confidence.UNCERTAIN


class TestExtractionSimilarity:
    def test_identical_text_confident(self):
        m = [make_block(["alpha beta gamma"], page_num=0)]
        s = [make_block(["alpha beta gamma"], page_num=0)]
        sections = compare_extractions(m, s)
        assert all(sec.kind != SectionKind.UNCERTAIN for sec in sections)

    def test_disjoint_text_uncertain(self):
        m = [make_block(["The quick brown fox jumps over the lazy dog and then some more"], page_num=0)]
        s = [make_block(["Completely unrelated text about different topics entirely and more words"], page_num=0)]
        sections = compare_extractions(m, s)
        assert any(sec.kind == SectionKind.UNCERTAIN for sec in sections)

    def test_high_overlap_confident(self):
        shared = "alpha beta gamma delta epsilon zeta eta theta"
        m = [make_block([shared + " iota"], page_num=0)]
        s = [make_block([shared + " kappa"], page_num=0)]
        sections = compare_extractions(m, s)
        assert all(sec.kind != SectionKind.UNCERTAIN for sec in sections)

    def test_both_empty_no_sections(self):
        sections = compare_extractions([], [])
        assert len(sections) == 0

    def test_one_side_empty_short_demoted(self):
        m = [make_block(["short"], page_num=0)]
        sections = compare_extractions(m, [])
        uncertain = [s for s in sections if s.kind == SectionKind.UNCERTAIN]
        assert len(uncertain) == 0


class TestCompareExtractions:
    def test_identical_blocks_confident(self):
        m = [make_block(["hello world"], page_num=0)]
        s = [make_block(["hello world"], page_num=0)]
        sections = compare_extractions(m, s)
        assert all(sec.kind != SectionKind.UNCERTAIN for sec in sections)

    def test_different_blocks_uncertain(self):
        m = [make_block(["The quick brown fox jumps over the lazy dog and then some more words"], page_num=0)]
        s = [make_block(["Completely unrelated text about different topics entirely with enough words here"], page_num=0)]
        sections = compare_extractions(m, s)
        assert any(sec.kind == SectionKind.UNCERTAIN for sec in sections)

    def test_tiny_uncertain_demoted(self):
        m = [make_block(["short"], page_num=0)]
        s = [make_block(["diff"], page_num=0)]
        sections = compare_extractions(m, s)
        uncertain = [s for s in sections if s.kind == SectionKind.UNCERTAIN]
        assert len(uncertain) == 0


class TestCompareExtractionsOrdering:
    """Regression: promoted pages must not break document order."""

    def test_promoted_pages_preserve_order(self):
        """Sections stay in page_num order even when promotions rewrite the list."""
        shared = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
        p0_m = [make_block([shared], page_num=0)]
        p0_s = [make_block([shared], page_num=0)]

        # Page 1: mupdf/spatial have swapped halves so per-page similarity is low
        p1_m = [make_block(["aaa bbb ccc ddd eee fff ggg hhh iii jjj"], page_num=1)]
        p1_s = [make_block(["kkk lll mmm nnn ooo ppp qqq rrr sss ttt"], page_num=1)]

        # Page 2: carries the other half so combined p1+p2 similarity is high
        p2_m = [make_block(["kkk lll mmm nnn ooo ppp qqq rrr sss ttt"], page_num=2)]
        p2_s = [make_block(["aaa bbb ccc ddd eee fff ggg hhh iii jjj"], page_num=2)]

        p3_m = [make_block([shared], page_num=3)]
        p3_s = [make_block([shared], page_num=3)]

        mupdf = p0_m + p1_m + p2_m + p3_m
        spatial = p0_s + p1_s + p2_s + p3_s

        sections = compare_extractions(mupdf, spatial)
        page_nums = [s.page_num for s in sections]
        assert page_nums == sorted(page_nums), (
            f"Sections out of order after promotion: {page_nums}"
        )


class TestPromotionConfidentNeighbour:
    """A confident page paired into a promotion must not be emitted twice.

    The pairwise promotion loop adds both the uncertain page and its
    forward neighbour to the promoted set. The re-insertion only re-emits
    pages that actually carried an UNCERTAIN section, so a confident
    neighbour (whose PARAGRAPH sections already exist from the first pass)
    keeps its single copy.
    """

    def test_confident_neighbour_not_duplicated_on_promotion(self):
        # Page 0: confident anchor (identical paths).
        p0 = " ".join(f"anchor{i}" for i in range(12))
        p0_m = [make_block([p0], page_num=0)]
        p0_s = [make_block([p0], page_num=0)]

        # Page 1: uncertain alone (paths fully disjoint, each >= 10 words).
        p1_m = [make_block([" ".join(f"alpha{i}" for i in range(12))], page_num=1)]
        p1_s = [make_block([" ".join(f"beta{i}" for i in range(12))], page_num=1)]

        # Page 2: confident (identical paths) and large enough that the
        # combined (page1 + page2) similarity clears SIMILARITY_THRESHOLD:
        # 80 / (12 + 80) = 0.87 >= 0.82, so the pair promotes.
        p2 = " ".join(f"gamma{i}" for i in range(80))
        p2_m = [make_block([p2], page_num=2)]
        p2_s = [make_block([p2], page_num=2)]

        mupdf = p0_m + p1_m + p2_m
        spatial = p0_s + p1_s + p2_s

        sections = compare_extractions(mupdf, spatial)

        # Promotion actually fired: page 1's UNCERTAIN section is gone and its
        # content is emitted as PARAGRAPH. Without this assertion a future
        # SIMILARITY_THRESHOLD retune that stops the pair promoting would make
        # the no-duplication check below pass trivially (green while testing
        # nothing).
        assert not any(s.kind == SectionKind.UNCERTAIN for s in sections)
        page1 = [s for s in sections if s.page_num == 1]
        assert page1 and all(s.kind == SectionKind.PARAGRAPH for s in page1), (
            "page 1 should have been rescued to PARAGRAPH by promotion"
        )

        # The confident neighbour (page 2) appears exactly once.
        page2 = [s for s in sections
                 if s.page_num == 2 and s.kind == SectionKind.PARAGRAPH]
        assert len(page2) == 1, (
            f"confident neighbour emitted {len(page2)} times, expected 1"
        )

    def test_both_neighbours_uncertain_each_emitted_once(self):
        """The genuine cross-page-split case: both pages uncertain alone but
        agreeing combined are each rescued exactly once (no under-rescue)."""
        first = " ".join(f"aaa{i}" for i in range(10))
        second = " ".join(f"bbb{i}" for i in range(10))

        # Page 1 and page 2 each disagree per-page (swapped halves) but agree
        # combined, so both are uncertain alone and both promote.
        p1_m = [make_block([first], page_num=1)]
        p1_s = [make_block([second], page_num=1)]
        p2_m = [make_block([second], page_num=2)]
        p2_s = [make_block([first], page_num=2)]

        sections = compare_extractions(p1_m + p2_m, p1_s + p2_s)

        assert not any(s.kind == SectionKind.UNCERTAIN for s in sections)
        for pg in (1, 2):
            rescued = [s for s in sections
                       if s.page_num == pg and s.kind == SectionKind.PARAGRAPH]
            assert len(rescued) == 1, (
                f"page {pg} emitted {len(rescued)} times, expected 1"
            )


class TestDocumentPoolPromotion:
    """Stage-4 bulk-pool promotion rescues uncertain pages that pairwise misses.

    Pairwise (stage 3) only considers pg and pg+1.  Non-adjacent uncertain
    pages whose next_pg is absent from the document are never paired, so they
    survive into stage 4.  Stage 4 pools ALL still-uncertain pages and checks
    document-wide similarity.

    Construction: three non-adjacent pages (1, 3, 5) using a three-way
    round-robin swap of word sets A, B, C:
      page 1: mupdf=A  spatial=B
      page 3: mupdf=B  spatial=C
      page 5: mupdf=C  spatial=A
    Per-page similarity = 0.0 (sets are disjoint) -> all three uncertain.
    Pages 2, 4, 6 are absent, so pairwise is skipped for all three.
    Pooled Counter(A+B+C) == Counter(B+C+A) -> similarity = 1.0 -> promotes.
    """

    def test_non_adjacent_uncertain_pages_promoted_by_document_pool(self):
        def words(prefix, n=12):
            return " ".join(f"{prefix}{i}" for i in range(n))

        a, b, c = words("alpha"), words("beta"), words("gamma")

        p1_m = [make_block([a], page_num=1)]
        p1_s = [make_block([b], page_num=1)]

        p3_m = [make_block([b], page_num=3)]
        p3_s = [make_block([c], page_num=3)]

        p5_m = [make_block([c], page_num=5)]
        p5_s = [make_block([a], page_num=5)]

        sections = compare_extractions(p1_m + p3_m + p5_m, p1_s + p3_s + p5_s)

        # Stage-4 fired: no UNCERTAIN sections remain.
        assert not any(s.kind == SectionKind.UNCERTAIN for s in sections), (
            "document-pool promotion should have resolved all uncertain pages"
        )
        # Each page emitted exactly once as PARAGRAPH.
        for pg in (1, 3, 5):
            rescued = [s for s in sections
                       if s.page_num == pg and s.kind == SectionKind.PARAGRAPH]
            assert len(rescued) == 1, (
                f"page {pg} emitted {len(rescued)} times after pool promotion, expected 1"
            )


class TestDropLeakedTocHeadings:
    """Leaked TOC remover: empty recurring headings and title-like entries.

    Removes a contiguous recurring run (a TOC block); never touches body,
    lone containers, short runs, or clause-container stacks whose headings
    strictly deepen.
    """

    @staticmethod
    def _h(text, level=2):
        return make_section(text, kind=SectionKind.HEADING, heading_level=level)

    @staticmethod
    def _body(text="This is a substantial body paragraph, well over forty chars."):
        return make_section(text, kind=SectionKind.PARAGRAPH)

    @staticmethod
    def _frag(text):
        return make_section(text, kind=SectionKind.PARAGRAPH)

    @staticmethod
    def _headings(secs):
        return [s.text for s in secs if s.kind == SectionKind.HEADING]

    def test_toc_block_of_recurring_empty_headings_removed(self):
        h, body = self._h, self._body
        secs = [
            h("Abstract"), h("Motivation"), h("Design"),          # leaked TOC
            h("Abstract"), body(), h("Motivation"), body(),
            h("Design"), body(),                                  # real sections
        ]
        out = drop_leaked_toc_entries(secs)
        assert self._headings(out) == ["Abstract", "Motivation", "Design"]
        assert sum(1 for s in out if s.kind == SectionKind.PARAGRAPH) == 3

    def test_heading_with_body_not_removed(self):
        """A recurring heading that HAS a body is never removed (body-safety)."""
        h, body = self._h, self._body
        secs = [
            h("A"), body(), h("B"), body(), h("C"), body(),   # real, recur below
            h("A"), h("B"), h("C"),                           # trailing empties
        ]
        out = drop_leaked_toc_entries(secs)
        # Front A/B/C recur later but have body -> not eligible. Trailing A/B/C
        # are empty but their duplicates are *earlier* -> not eligible. Nothing
        # removed; every body survives.
        assert len(out) == len(secs)
        assert sum(1 for s in out if s.kind == SectionKind.PARAGRAPH) == 3

    def test_lone_recurring_empty_heading_not_removed(self):
        """p3556r0 case: a lone empty container (15 -> 15.1) is spared."""
        h, body = self._h, self._body
        secs = [
            h("1 Intro", 2), body(),
            h("15 Preprocessing directives", 2),          # empty container, recurs
            h("15.1 Preamble", 3), body(),
            h("15 Preprocessing directives", 2),          # the recurrence
            h("15.1 Preamble", 3), body(),
        ]
        out = drop_leaked_toc_entries(secs)
        kept = self._headings(out)
        assert kept.count("15 Preprocessing directives") == 2  # neither removed

    def test_run_length_below_floor_not_removed(self):
        """A run of 2 recurring empty headings is below MIN_TOC_RUN -> kept."""
        h, body = self._h, self._body
        secs = [
            h("Abstract"), h("Motivation"),               # run of 2 only
            h("Abstract"), body(), h("Motivation"), body(),
        ]
        out = drop_leaked_toc_entries(secs)
        assert self._headings(out).count("Abstract") == 2
        assert self._headings(out).count("Motivation") == 2

    def test_trivial_section_within_run_dropped(self):
        """Page-number fragments and a preceding label are swept with the run."""
        h, body, frag = self._h, self._body, self._frag
        secs = [
            frag("Table of Contents"),
            h("Abstract"), frag("3"),
            h("Motivation"), frag("5"),
            h("Design"), frag("7"),
            h("Abstract"), body(), h("Motivation"), body(), h("Design"), body(),
        ]
        out = drop_leaked_toc_entries(secs)
        texts = [s.text for s in out]
        assert "Table of Contents" not in texts
        assert "3" not in texts and "5" not in texts and "7" not in texts
        assert self._headings(out) == ["Abstract", "Motivation", "Design"]
        assert sum(1 for s in out if s.kind == SectionKind.PARAGRAPH) == 3

    def test_recurrence_is_forward_only(self):
        """Trailing empties whose only duplicate is earlier are not removed."""
        h, body = self._h, self._body
        secs = [
            h("A"), body(), h("B"), body(), h("C"), body(),
            h("A"), h("B"), h("C"),     # duplicates are all *earlier*
        ]
        out = drop_leaked_toc_entries(secs)
        assert self._headings(out).count("A") == 2
        assert len(out) == len(secs)

    def test_non_recurring_block_kept(self):
        """A run of >=3 empty headings that do NOT recur later is kept."""
        h, body = self._h, self._body
        secs = [h("A"), h("B"), h("C"), h("D"), body()]
        out = drop_leaked_toc_entries(secs)
        assert self._headings(out) == ["A", "B", "C", "D"]

    def test_normalization_collision_lone_heading_kept(self):
        """`3.1 Overview` / `5.2 Overview` collide but neither is in a >=3 run."""
        h, body = self._h, self._body
        secs = [
            h("3.1 Overview", 3), h("3.2 Details", 3), body(),
            h("5.2 Overview", 3), h("5.3 More", 3), body(),
        ]
        out = drop_leaked_toc_entries(secs)
        # Both "Overview" headings normalize alike, but each is a lone eligible
        # heading (its sibling has body), so no run forms and none is removed.
        assert sum(1 for t in self._headings(out) if "Overview" in t) == 2

    def test_deepening_container_stack_not_removed(self):
        """Strictly-monotonic rejection: pure ascent kept; flat/plateau removed."""
        h, body = self._h, self._body

        def run_with_levels(levels):
            # front: empty recurring headings at the given levels; back: real.
            titles = ["Chapter", "Section", "Subsection"]
            front = [h(t, lvl) for t, lvl in zip(titles, levels)]
            back = []
            for t, lvl in zip(titles, levels):
                back += [h(t, lvl), body()]
            return drop_leaked_toc_entries(front + back)

        # (a) pure ascent [2,3,4] -> rejected (kept): a clause container stack.
        out_a = run_with_levels([2, 3, 4])
        assert self._headings(out_a).count("Chapter") == 2  # front survives

        # (b) flat [2,2,2] -> removed.
        out_b = run_with_levels([2, 2, 2])
        assert self._headings(out_b).count("Chapter") == 1  # front removed

        # (c) discriminating plateau [2,2,3] -> removed (NOT strictly increasing).
        out_c = run_with_levels([2, 2, 3])
        assert self._headings(out_c).count("Chapter") == 1  # front removed

    def test_non_trivial_toc_neighbour_paragraph_removed(self):
        """A PARAGRAPH that recurs as a later heading is removed as a TOC entry.

        A non-trivial (multi-word) paragraph whose text matches a body heading
        is treated as a non-heading TOC entry. It is swept with the run rather
        than blocking the preceding heading's eligibility as body prose would.
        """
        h, body = self._h, self._body
        long_title = "Compatibility and Migration Concerns for Existing Code"
        secs = [
            # Leaked TOC block: three headings, the middle one followed by
            # a non-trivial paragraph whose text is itself a later heading.
            h("Abstract"),
            h("Design"),
            h(long_title),
            # The paragraph below matches a later heading -> nonheading_entry.
            self._frag(long_title),
            h("References"),
            # Real body sections that supply the forward recurrences.
            h("Abstract"), body(),
            h("Design"), body(),
            h(long_title), body(),
            h("References"), body(),
        ]
        out = drop_leaked_toc_entries(secs)
        # The leaked run (first Abstract/Design/long_title/References) is removed.
        assert self._headings(out) == [
            "Abstract", "Design", long_title, "References"
        ]
        # The non-trivial neighbour paragraph is also swept.
        assert not any(s.text == long_title and s.kind == SectionKind.PARAGRAPH
                       for s in out)
        # Body paragraphs are untouched.
        assert sum(1 for s in out if s.kind == SectionKind.PARAGRAPH) == 4

    def test_mixed_run_deepening_headings_not_removed(self):
        """Strictly-deepening rejection applies to the heading subsequence of a
        mixed run, not only to all-heading runs.

        A run containing PARAGRAPH/LIST entries between strictly-ascending
        headings is a real clause-container structure (the non-heading entries
        are preamble/body inside each clause), not a leaked TOC.
        """
        h, body = self._h, self._body

        def lst(text):
            return make_section(text, kind=SectionKind.LIST)
        # Leaked TOC candidate: empty headings at levels 2/3/4, with a LIST
        # entry (recurs as a later heading) between the first two headings.
        # The heading subsequence [2, 3, 4] strictly deepens -> kept.
        front = [h("Chapter", 2), lst("Section"), h("Section", 3), h("Subsection", 4)]
        back = [
            h("Chapter", 2), body(),
            h("Section", 3), body(),
            h("Subsection", 4), body(),
        ]
        out = drop_leaked_toc_entries(front + back)
        # Front headings must survive (run rejected as a clause-container stack).
        headings = [s.text for s in out if s.kind == SectionKind.HEADING]
        assert headings.count("Chapter") == 2
        assert headings.count("Section") == 2
        assert headings.count("Subsection") == 2

    def test_entry_title_roman_numeral_not_folded(self):
        """_entry_title folds "1\\nOverview" but not "IV\\nOverview".

        The digit-only _BARE_DIGIT_NUM_RE guards _entry_title. The broader
        module-level _BARE_SECTION_NUM_RE (roman numerals, single capital
        letters) must not shadow it. When a two-line TOC candidate has a roman
        numeral on its first line but the corresponding body heading is a
        single-line "IV Overview", the wrong regex folds the candidate to
        "IV Overview" -> match -> phantom removal. The correct regex leaves
        the first line as "IV" -> no match against "IV Overview" -> no removal.
        """
        h, body = self._h, self._body
        # TOC candidate: roman numeral on its own line (two-line format).
        # Body heading: title on a single line (single-line format).
        secs = [
            h("IV\nOverview"), h("V\nProposal"), h("VI\nConclusion"),
            h("IV Overview"), body(),
            h("V Proposal"), body(),
            h("VI Conclusion"), body(),
        ]
        out = drop_leaked_toc_entries(secs)
        # With _BARE_DIGIT_NUM_RE: "IV\nOverview" -> entry_title "IV",
        # normalized "iv". Body heading "IV Overview" -> "iv overview". No
        # match -> front three headings survive -> 6 total.
        # With _BARE_SECTION_NUM_RE: "IV\nOverview" -> "IV Overview" ->
        # "iv overview" -> matches body heading -> front three removed -> 3.
        headings = [s.text for s in out if s.kind == SectionKind.HEADING]
        assert headings == [
            "IV\nOverview", "V\nProposal", "VI\nConclusion",  # not removed
            "IV Overview", "V Proposal", "VI Conclusion",      # real body headings
        ]


class TestDropLeakedTocMixedKind:
    """The unified mixed-kind leaked-TOC remover (#122 pt4).

    a real leaked TOC is a mix of empty headings and short title-like
    PARAGRAPH/LIST entries. This pass treats "recurs as a later heading" as the
    single discriminator across both kinds, bridges non-heading entries when
    judging heading emptiness, and gates removal on a heading anchor so
    paragraph/list deletion stays inside a confirmed heading-kind TOC block.
    """

    # Long enough to be non-trivial (>= _TOC_ENTRY_MAX_BODY_CHARS), so these are
    # treated as TOC *entries* by recurrence, not merely bridged as fragments.
    _QUESTIONS = "5. Questions About the Cost of Unification"  # 42 chars
    _FRAMING = "6. The Framing Change and Its Lasting Consequences"  # > 40

    @staticmethod
    def _h(text, level=2):
        return make_section(text, kind=SectionKind.HEADING, heading_level=level)

    @staticmethod
    def _list(text):
        return make_section(text, kind=SectionKind.LIST)

    @staticmethod
    def _para(text):
        return make_section(text, kind=SectionKind.PARAGRAPH)

    @staticmethod
    def _body(text="This is a substantial body paragraph, well over forty chars."):
        return make_section(text, kind=SectionKind.PARAGRAPH)

    @staticmethod
    def _multiline(first, n_lines):
        """A PARAGRAPH whose first line is `first` but spans `n_lines` text lines."""
        lines = [make_line([first])] + [make_line([f"continuation {i}"])
                                        for i in range(1, n_lines)]
        text = "\n".join([first] + [f"continuation {i}" for i in range(1, n_lines)])
        return make_section(text, kind=SectionKind.PARAGRAPH, lines=lines)

    @staticmethod
    def _texts(secs):
        return [s.text for s in secs]

    def test_mixed_kind_toc_block_removed(self):
        """Run alternating empty heading, LIST entry, PARAGRAPH entry, empty
        heading -> entire run removed; the real sections (with body) survive."""
        h, lst, para, body = self._h, self._list, self._para, self._body
        secs = [
            h("Abstract"), lst(self._QUESTIONS), para(self._FRAMING),
            h("3.7 Summary"),                                       # leaked TOC
            h("Abstract"), body(),
            h(self._QUESTIONS), body(),
            h(self._FRAMING), body(),
            h("3.7 Summary"), body(),                               # real
        ]
        out = drop_leaked_toc_entries(secs)
        texts = self._texts(out)
        # The four leaked entries are gone from the front; one real copy of each
        # title remains, every body paragraph survives.
        assert texts.count("Abstract") == 1
        assert texts.count(self._QUESTIONS) == 1
        assert texts.count(self._FRAMING) == 1
        assert texts.count("3.7 Summary") == 1
        assert sum(1 for s in out if s.kind == SectionKind.PARAGRAPH) == 4

    def test_entry_does_not_strand_heading(self):
        """The `3.7 Summary` shape: a heading, then a > 40-char LIST-kind entry,
        then the next heading. Emptiness must bridge the LIST entry so the
        leading heading is not stranded. A PARAGRAPH-only bridge would still
        fail P4094R0, whose entries are LIST-kind, so use a LIST entry here."""
        h, lst, body = self._h, self._list, self._body
        secs = [
            h("3.7 Summary"), lst(self._QUESTIONS), h("5.1 Subpoint"),  # leaked
            h("3.7 Summary"), body(),
            h(self._QUESTIONS), body(),
            h("5.1 Subpoint"), body(),                                  # real
        ]
        out = drop_leaked_toc_entries(secs)
        texts = self._texts(out)
        assert texts.count("3.7 Summary") == 1     # leading heading not stranded
        assert texts.count(self._QUESTIONS) == 1   # the LIST entry was removed
        assert texts.count("5.1 Subpoint") == 1

    def test_real_content_not_removed(self):
        """Body-safety: the load-bearing title-like / anchor gates."""
        h, lst, body = self._h, self._list, self._body

        # (a) a 3-text-line body block whose first line matches a later heading
        #     is NOT an entry (pins the _TOC_ENTRY_MAX_LINES boundary): with the
        #     cap at 2, the block breaks the run and nothing is removed.
        secs_a = [
            h("Abstract"),
            self._multiline("Motivation", 3),   # 3 lines -> not title-like
            h("Design"),
            h("Abstract"), body(),
            h("Motivation"), body(),
            h("Design"), body(),
        ]
        out_a = drop_leaked_toc_entries(secs_a)
        assert len(out_a) == len(secs_a)
        assert any(s.text.startswith("Motivation") and len(s.text.split("\n")) == 3
                   for s in out_a)

        # (b) a lone single-line matching paragraph (run length 1) is not removed.
        secs_b = [self._para("Motivation"), h("Motivation"), body()]
        out_b = drop_leaked_toc_entries(secs_b)
        assert len(out_b) == len(secs_b)

        # (c) the agenda worst case: a real `## Overview` heading whose title does
        #     NOT recur later, followed by >= 3 single-line bullets that each echo
        #     a later heading. No heading anchor (Overview does not recur), so the
        #     emptiness bridging cannot sweep the bullets.
        secs_c = [
            h("Overview"),                       # does not recur -> no anchor
            lst("Goals"), lst("Design"), lst("API"),
            h("Goals"), body(),
            h("Design"), body(),
            h("API"), body(),
        ]
        out_c = drop_leaked_toc_entries(secs_c)
        assert len(out_c) == len(secs_c)

        # (d) a 3-line body block with an EMPTY sec.lines list (as produced by
        #     HTML or synthetic sections) whose first line matches a later heading
        #     is NOT an entry. Before the fix, len(sec.lines)==0 always passed
        #     the cap and such blocks were wrongly swept.
        multi_text = "Motivation\ncontinuation 1\ncontinuation 2"
        prose = make_section(multi_text, kind=SectionKind.PARAGRAPH, lines=[])
        secs_d = [
            h("Abstract"), prose, h("Design"),
            h("Abstract"), body(),
            h("Motivation"), body(),
            h("Design"), body(),
        ]
        out_d = drop_leaked_toc_entries(secs_d)
        assert len(out_d) == len(secs_d)

    def test_pure_paragraph_run_not_removed(self):
        """A contiguous run of >= MIN_TOC_RUN recurring title-like list entries
        with NO empty-heading entry among them is never removed (the anchor)."""
        h, lst, body = self._h, self._list, self._body
        secs = [
            lst("Goals"), lst("Non-goals"), lst("Motivation"),   # pure list run
            h("Goals"), body(),
            h("Non-goals"), body(),
            h("Motivation"), body(),
        ]
        out = drop_leaked_toc_entries(secs)
        assert len(out) == len(secs)

    def test_bare_number_first_line_wording_not_matched(self):
        """Real normative wording whose first physical line is just its
        paragraph number ("8", wrapping "Effects: ..." to line 2) must never be
        removed. First-line-only normalization reduces it to "8" and falsely
        matches a later "8 Acknowledgements" heading (also "8"); the fold-aware
        key keeps the prose so it matches no heading title. Body-loss guard
        (observed on p2988r9)."""
        h, body = self._h, self._body
        wording = make_section(
            "8\nEffects: Equivalent to: return optional<T>(in_place, args);",
            kind=SectionKind.PARAGRAPH,
            lines=[make_line(["8"]),
                   make_line(["Effects: Equivalent to: return optional<T>(in_place, args);"])],
        )
        secs = [
            h("Intro"), wording, h("Summary"),          # would-be run
            h("Intro"), body(),
            h("8\nAcknowledgements"), body(),            # the "8" recurrence target
            h("Summary"), body(),
        ]
        out = drop_leaked_toc_entries(secs)
        assert any(s is wording for s in out), "real wording was deleted"
        assert "Effects: Equivalent to" in "\n".join(s.text for s in out)

    def test_number_on_own_line_entry_still_matched(self):
        """A leaked TOC entry rendered with the section number on its own
        physical line ("1\\nComparison table") still matches its body heading
        after folding, so a run of them is removed. Guards against an
        over-aggressive bare-number guard that would leave them (a real
        number-line TOC must still be cleaned)."""
        body = self._body

        def hh(text):
            a, b = text.split("\n")
            return make_section(text, kind=SectionKind.HEADING, heading_level=2,
                                lines=[make_line([a]), make_line([b])])

        secs = [
            hh("1\nComparison table"), hh("2\nMotivation"), hh("3\nDesign"),  # leaked TOC
            hh("1\nComparison table"), body(),
            hh("2\nMotivation"), body(),
            hh("3\nDesign"), body(),
        ]
        out = drop_leaked_toc_entries(secs)
        texts = self._texts(out)
        assert texts.count("1\nComparison table") == 1   # leaked copy removed
        assert texts.count("2\nMotivation") == 1
        assert sum(1 for s in out if s.kind == SectionKind.PARAGRAPH) == 3

    def test_heading_kind_toc_label_removed(self):
        """A `### Table of Contents` heading immediately preceding a removed run
        is dropped (P4003R1: the label-walk-back handles heading-kind labels too)."""
        h, body = self._h, self._body
        secs = [
            h("Table of Contents", 3),
            h("Abstract"), h("Motivation"), h("Design"),          # leaked TOC
            h("Abstract"), body(),
            h("Motivation"), body(),
            h("Design"), body(),
        ]
        out = drop_leaked_toc_entries(secs)
        texts = self._texts(out)
        assert "Table of Contents" not in texts
        assert texts.count("Abstract") == 1
        assert sum(1 for s in out if s.kind == SectionKind.PARAGRAPH) == 3

    def test_image_inside_run_span_not_swept(self):
        """An IMAGE section between leaked TOC entries must survive.

        IMAGE sections have text="" so _section_is_trivial always returns True
        for them. The in-span sweep must skip IMAGE (and TABLE/CODE) regardless
        of text length, matching the guard already present in find_toc_indices.
        """
        h, body = self._h, self._body
        image = make_section("", kind=SectionKind.IMAGE)
        secs = [
            h("Abstract"), h("Motivation"), image, h("Design"),  # leaked TOC
            h("Abstract"), body(),
            h("Motivation"), body(),
            h("Design"), body(),
        ]
        out = drop_leaked_toc_entries(secs)
        assert any(s.kind == SectionKind.IMAGE for s in out), (
            "IMAGE section was silently swept from inside a TOC run"
        )


class TestDropLeakedTocRelaxedBridging:
    """Relaxed straggler bridging restricted to the front region (#122 pt5).

    pt4 broke a leaked-TOC run at each non-recurring straggler (title-like
    paragraph/list lines whose body heading drifted, once-only empty headings),
    leaving a residual. pt5 bridges stragglers as in-span run members so the
    block coalesces, gated by: a front-region bound (`body_start`), a
    recurrence-density floor, the in-span/trailing rule, and a forward-reference
    gate on paragraph stragglers. Body-safety is the conjunction.
    """

    # Leaked appendix title carrying a trailing qualifier the real heading lacks;
    # > _TOC_ENTRY_MAX_BODY_CHARS so it is a straggler, not a trivial fragment.
    _APPENDIX = ("Appendix D: Standard Wording for Fixed Expression Structure "
                 "(Informative)")
    _APPENDIX_HEADING = "Appendix D: Standard Wording for Fixed Expression Structure"
    # Unique abstract prose: single physical line, > 40 chars, recurs nowhere.
    _UNIQUE = "C++ today offers two distinct endpoints for parallel reduction."

    @staticmethod
    def _h(text, level=2):
        return make_section(text, kind=SectionKind.HEADING, heading_level=level)

    @staticmethod
    def _para(text):
        return make_section(text, kind=SectionKind.PARAGRAPH)

    @staticmethod
    def _m3(first="Real body prose"):
        """A real body PARAGRAPH spanning 3 physical lines (not title-like; the
        first such paragraph defines `body_start`)."""
        lines = [make_line([first]), make_line(["second line of prose"]),
                 make_line(["third line of prose"])]
        text = first + "\nsecond line of prose\nthird line of prose"
        return make_section(text, kind=SectionKind.PARAGRAPH, lines=lines)

    @staticmethod
    def _texts(secs):
        return [s.text for s in secs]

    def test_fragmented_toc_coalesced(self):
        """P4016R0 shape: a run fragmented by a non-recurring title-like
        paragraph straggler AND a non-recurring empty-heading straggler, both
        in-span of a heading anchor -> the entire front block is removed. pt4
        broke the run at each straggler and left a residual."""
        h, para, m3 = self._h, self._para, self._m3
        secs = [
            h("Abstract"),                          # entry
            para(self._APPENDIX),                   # para straggler (forward-refs)
            h("Background and Prior Art"),          # entry
            h("1.2 Motivating example"),            # empty-heading straggler
            h("Design Considerations"),             # entry
            h("Goals and Non-Goals"),               # entry
            h("Proposed API Surface"),              # entry
            h("Conclusion and Future Work"),        # entry  (6 entries, 2 stragglers)
            # real sections (bodies are 3-line, so body_start sits here):
            h("Abstract"), m3("This proposal"),
            h("Background and Prior Art"), m3("Prior art"),
            h("Design Considerations"), m3("The design"),
            h("Goals and Non-Goals"), m3("Goals"),
            h("Proposed API Surface"), m3("The API"),
            h("Conclusion and Future Work"), m3("Conclusion"),
            h(self._APPENDIX_HEADING), m3("Wording"),   # forward-ref target
        ]
        out = drop_leaked_toc_entries(secs)
        texts = self._texts(out)
        # entire leaked front block gone; one real copy of each title remains.
        assert texts.count("Abstract") == 1
        assert self._APPENDIX not in texts             # para straggler removed
        assert "1.2 Motivating example" not in texts   # empty-heading straggler removed
        assert texts.count("Background and Prior Art") == 1
        assert texts.count(self._APPENDIX_HEADING) == 1
        # every real 3-line body paragraph survives.
        assert sum(1 for s in out if len(s.lines) == 3) == 7

    def test_trailing_single_line_real_body_kept(self):
        """The real P4016R0 mechanism: a leaked run immediately followed by a
        real `Abstract` heading and two single-line real-body paragraphs, all in
        the front region, with NO recurring entry after them. The heading is
        judged empty and the single-line paragraphs are title-like, so the scan
        bridges them as stragglers - yet all are KEPT because they are trailing
        (past the last entry). Pins the load-bearing trailing rule for real
        prose, not just the heading."""
        h, para, m3 = self._h, self._para, self._m3
        secs = [
            h("Abstract"), h("Motivation and Scope"), h("Detailed Design"),  # leaked run
            h("Abstract"),                                   # real, empty
            para(self._UNIQUE),                              # real single-line prose
            para("std::accumulate folds left with an initial value here."),  # real prose
            h("Motivation and Scope"), m3("The motivation"),   # body_start here
            h("Detailed Design"), m3("The design"),
        ]
        out = drop_leaked_toc_entries(secs)
        texts = self._texts(out)
        assert texts.count("Abstract") == 1               # leaked copy removed, real kept
        assert self._UNIQUE in texts                      # real single-line prose kept
        assert any("std::accumulate" in t for t in texts)
        assert texts.count("Motivation and Scope") == 1

    def test_body_wording_boilerplate_not_removed(self):
        """The p2846r6 body-loss regression: in the BODY region, repeated
        normative boilerplate headings recur and form a would-be dense anchor,
        with `Effects:`-style wording paragraphs between them. Nothing is removed
        because the front-region restriction keeps bridging strict in the body -
        the wording paragraph is never bridged as a straggler, so it breaks the
        run (exactly pt4)."""
        h, para, m3 = self._h, self._para, self._m3
        secs = [
            h("Synopsis"), m3("The synopsis"),    # body_start = index 1
            h("Mandates:"),
            para("Effects: Constructs a sequence container equal to the range rg."),
            h("Mandates:"),
            para("Returns: a reference to the resulting container by value here."),
            h("Mandates:"),
            para("Throws: nothing unless the allocator throws during construction."),
        ]
        out = drop_leaked_toc_entries(secs)
        assert len(out) == len(secs)                 # nothing removed
        assert any("Effects: Constructs a sequence container" in s.text for s in out)

    def test_paragraph_straggler_removed_only_if_forward_references(self):
        """The forward-reference gate. Two in-span paragraph stragglers in the
        same dense front-region anchored run: (a) one whose title recurs as a
        later heading (with the trailing-qualifier mismatch, pinning
        bidirectional containment) -> removed; (b) one unique-prose line with no
        later heading -> KEPT even though it is in-span. Targets later headings,
        not paragraphs."""
        h, para, m3 = self._h, self._para, self._m3
        secs = [
            h("Abstract"),                 # entry
            h("Background"),               # entry
            para(self._APPENDIX),          # straggler-a (forward-refs) in-span
            h("Design"),                   # entry
            para(self._UNIQUE),            # straggler-b (unique) in-span
            h("Goals"),                    # entry
            h("API Surface"),              # entry
            h("Rationale"),                # entry  (6 entries, 2 in-span stragglers)
            h("Abstract"), m3("a"), h("Background"), m3("b"), h("Design"), m3("c"),
            h("Goals"), m3("d"), h("API Surface"), m3("e"), h("Rationale"), m3("f"),
            h(self._APPENDIX_HEADING), m3("Wording"),    # forward-ref target for (a)
        ]
        out = drop_leaked_toc_entries(secs)
        texts = self._texts(out)
        assert self._APPENDIX not in texts        # (a) forward-references -> removed
        assert self._UNIQUE in texts              # (b) unique prose -> kept (in-span!)
        assert texts.count(self._APPENDIX_HEADING) == 1

    def test_heading_straggler_swept_without_forward_reference(self):
        """P4007R0 protection: a once-only empty-heading straggler in-span in a
        dense front-region run whose title does NOT recur as a later heading is
        removed. The forward-reference gate is NOT applied to heading stragglers
        (heading text drifts), so P4007R0's `8.1`-`8.4` objections are not
        regressed."""
        h, m3 = self._h, self._m3
        objection = '8.1 "C++ needs a standard task. Six years is long enough."'
        secs = [
            h("Abstract"),     # entry
            h("Background"),   # entry
            h(objection),      # empty-heading straggler, non-recurring, in-span
            h("Design"),       # entry
            h("Goals"),        # entry  (4 entries, 1 straggler -> density 0.8)
            h("Abstract"), m3("a"), h("Background"), m3("b"),
            h("Design"), m3("c"), h("Goals"), m3("d"),
        ]
        out = drop_leaked_toc_entries(secs)
        texts = self._texts(out)
        assert objection not in texts             # swept despite no forward-ref
        assert texts.count("Abstract") == 1

    def test_empty_container_heading_in_body_kept(self):
        """A real empty container heading (`## 3 Design` over `### 3.1 Foo`) in a
        region with NO recurring-heading anchor is not removed."""
        h, m3 = self._h, self._m3
        secs = [
            h("3 Design", 2),
            h("3.1 Foo", 3), m3("foo body"),
            h("3.2 Bar", 3), m3("bar body"),
        ]
        out = drop_leaked_toc_entries(secs)
        assert len(out) == len(secs)

    def test_low_density_run_kept(self):
        """An anchored run (>= MIN_TOC_RUN recurring entries) whose in-span
        stragglers push recurrence density below the floor is not removed."""
        h, para, m3 = self._h, self._para, self._m3
        secs = [
            h("Abstract"),                                          # entry
            para("First Straggling Title Line That Does Not Recur Anywhere"),
            para("Second Straggling Title Line That Does Not Recur Anywhere"),
            h("Background"),                                        # entry
            h("Design"),                                           # entry
            # 3 entries + 2 in-span stragglers -> density 0.6 < 0.75
            h("Abstract"), m3("a"), h("Background"), m3("b"), h("Design"), m3("c"),
        ]
        out = drop_leaked_toc_entries(secs)
        assert len(out) == len(secs)               # density floor spares the run

    def test_trailing_stragglers_not_removed(self):
        """A dense anchored run followed by bridged stragglers with no further
        entry after them: the entries are removed but every trailing straggler is
        kept. Directly pins the trailing-exclusion / `last_entry` boundary."""
        h, para, m3 = self._h, self._para, self._m3
        trailing_para = "A Trailing Section Title Line That Wraps Once Here Now"
        trailing_head = "4.1 A Trailing Subsection Heading That Does Not Recur"
        secs = [
            h("Abstract"), h("Background"), h("Design"),   # 3 recurring entries
            para(trailing_para),                            # trailing para straggler
            h(trailing_head),                               # trailing heading straggler
            h("Abstract"), m3("a"), h("Background"), m3("b"), h("Design"), m3("c"),
        ]
        out = drop_leaked_toc_entries(secs)
        texts = self._texts(out)
        assert texts.count("Abstract") == 1        # leaked entries removed
        assert trailing_para in texts              # trailing stragglers kept
        assert trailing_head in texts


class TestLeakedTocPredicates:
    """Per-predicate unit tests (#122 pt5 decomposition): each gate is a small
    named predicate so a future refactor cannot silently drop one layer."""

    @staticmethod
    def _h(text, level=2):
        return make_section(text, kind=SectionKind.HEADING, heading_level=level)

    @staticmethod
    def _para(text, lines=None):
        return make_section(text, kind=SectionKind.PARAGRAPH, lines=lines)

    def test_is_title_like_straggler(self):
        # single-line title-like paragraph with alphabetic content -> True
        assert _is_title_like_straggler(self._para("Appendix D: Some Real Title Here"))
        # 3-physical-line paragraph -> not title-like (real prose)
        three = self._para(
            "first\nsecond\nthird",
            lines=[make_line(["first"]), make_line(["second"]), make_line(["third"])])
        assert not _is_title_like_straggler(three)
        # bare-number / no-alpha title -> False
        assert not _is_title_like_straggler(self._para("12"))
        # a HEADING is never a title-like (non-heading) straggler
        assert not _is_title_like_straggler(self._h("Appendix D: Title"))

    def test_is_empty_heading(self):
        # heading followed only by a title-like non-heading -> empty
        secs = [self._h("1.2 Motivating example"),
                self._para("Appendix D: Some Title That Is Title-Like"),
                self._h("Next")]
        assert _is_empty_heading(secs, 0)
        # heading followed by real multi-line prose -> not empty (the prose must
        # be > _TOC_ENTRY_MAX_BODY_CHARS so it is non-trivial, and > 2 lines so it
        # is not title-like).
        prose = self._para(
            "This is a real multi-line body paragraph that is clearly\n"
            "well over forty characters and spans three\nphysical lines of prose",
            lines=[make_line(["This is a real multi-line body paragraph that is clearly"]),
                   make_line(["well over forty characters and spans three"]),
                   make_line(["physical lines of prose"])])
        assert not _is_empty_heading([self._h("Design"), prose, self._h("Next")], 0)
        # a non-heading section is never an "empty heading"
        assert not _is_empty_heading([self._para("x")], 0)

    def test_straggler_forward_references(self):
        # bidirectional containment: leaked line carries a trailing qualifier the
        # heading lacks; heading title is a substring of the straggler title.
        heading_titles = [(5, "appendix d standard wording for fixed expression structure")]
        strag = "appendix d standard wording for fixed expression structure (informative)"
        assert _straggler_forward_references(strag, 1, heading_titles)
        # unique prose: no later heading containment -> False
        assert not _straggler_forward_references(
            "c today offers two distinct endpoints for parallel reduction", 1,
            heading_titles)
        # target must be LATER (j > i): an earlier heading does not count
        assert not _straggler_forward_references(strag, 9, heading_titles)
        # below the minimum title length -> False
        assert not _straggler_forward_references("abc", 1, [(5, "abc")])

    def test_run_recurrence_density(self):
        assert _run_recurrence_density(6, 2) == 0.75
        assert _run_recurrence_density(3, 0) == 1.0
        assert _run_recurrence_density(3, 2) == 0.6
        assert _run_recurrence_density(0, 0) == 0.0

    def test_compute_body_start(self):
        h = self._h
        m3 = [make_line(["real body prose that is clearly over forty characters"]),
              make_line(["second line"]), make_line(["third line"])]
        secs = [
            h("Abstract"),
            self._para("single line title-like, recurs nowhere but one line only"),
            self._para("real body prose that is clearly over forty characters\n"
                       "second line\nthird line", lines=m3),
            h("Design"),
        ]
        recur = [False, False, False, False]
        # the first non-trivial, non-recurring, >= 2-line PARAGRAPH is index 2.
        assert _compute_body_start(secs, recur) == 2
        # a recurring paragraph does not start the body.
        assert _compute_body_start(secs, [False, False, True, False]) == len(secs)


class TestParagraphMerging:
    def test_merges_continuation(self):
        sections = [
            make_section("Some text without terminal"),
            make_section("continuation here"),
        ]
        _, result, _ = structure_sections(sections, has_title=True)
        paragraphs = [s for s in result if s.kind == SectionKind.PARAGRAPH]
        assert len(paragraphs) == 1
        assert "continuation" in paragraphs[0].text

    def test_no_merge_with_terminal(self):
        sections = [
            make_section("Some text with terminal."),
            make_section("Next paragraph."),
        ]
        _, result, _ = structure_sections(sections, has_title=True)
        paragraphs = [s for s in result if s.kind == SectionKind.PARAGRAPH]
        assert len(paragraphs) == 2

    def test_merge_preserves_original_input(self):
        s1 = make_section("Some text without terminal")
        s2 = make_section("continuation here")
        original_text = s1.text
        structure_sections([s1, s2], has_title=True)
        assert s1.text == original_text


class TestBodySizeDetection:
    def test_larger_font_detected_as_heading(self):
        sections = [
            make_section("body text", font_size=10.0),
            make_section("more body text", font_size=10.0),
            make_section("A Heading", font_size=14.0),
        ]
        _, result, _ = structure_sections(sections, has_title=True)
        headings = [s for s in result if s.kind == SectionKind.HEADING]
        assert len(headings) >= 1

    def test_uniform_font_no_headings(self):
        sections = [
            make_section("body text", font_size=10.0),
            make_section("more body text", font_size=10.0),
            make_section("still body text", font_size=10.0),
        ]
        _, result, _ = structure_sections(sections, has_title=True)
        headings = [s for s in result if s.kind == SectionKind.HEADING]
        assert len(headings) == 0


class TestHeadingStructureDefectsP4221R0:
    """End-to-end heading defects from issue #154 (P4221R0, PDF)."""

    def test_empty_elevated_font_section_not_a_heading(self):
        """A blank line with an elevated font (a TOC-page spacer) must not
        become an empty `#####` heading."""
        sections = [
            make_section("body text here", font_size=10.0),
            make_section("more body text", font_size=10.0),
            make_section("", font_size=16.0),
            make_section("Real Heading", font_size=16.0),
        ]
        _, result, _ = structure_sections(sections, has_title=True)
        headings = [s for s in result if s.kind == SectionKind.HEADING]
        assert all(s.text.strip() for s in headings), (
            f"empty heading emitted: {[s.text for s in headings]}"
        )

    def test_parent_not_rendered_deeper_than_child(self):
        """The non-known top-level section "Proposed Functions" (20pt) must
        not render deeper than its known child "Overview" (pinned to h2).
        The document title (26pt) pollutes the font-size ranking and demotes
        the genuine top-level size to rank 2."""
        sections = [
            make_section("Atomic Compare", font_size=26.0),
            make_section("intro body prose text that is clearly a paragraph",
                         font_size=11.0),
            make_section("Background", font_size=16.0),
            make_section("background body prose text goes here", font_size=11.0),
            make_section("Proposed Functions", font_size=20.0),
            make_section("Overview", font_size=16.0),
            make_section("overview body prose text goes here", font_size=11.0),
        ]
        _, result, _ = structure_sections(sections, has_title=False)
        headings = {s.text.strip(): s.heading_level
                    for s in result if s.kind == SectionKind.HEADING}
        assert "Proposed Functions" in headings and "Overview" in headings, (
            f"expected both headings; got {headings}"
        )
        assert headings["Proposed Functions"] <= headings["Overview"], (
            f"parent rendered deeper than child: {headings}"
        )


class TestHeadingLevelDefectsIssue300:
    """Heading levels derived from numbering depth (numbered) and the true
    heading font tier (unnumbered), per issue #300."""

    def test_numbered_subsection_keeps_depth_level(self):
        """A numbered subsection rendered at the SAME font size as its parent
        keeps its numbering-derived level. WG21 papers render `2.1` and `2.1.1`
        at one font; the shared-font sibling clamp must not collapse the deeper
        numbered heading up a level (p0957r8: `### 3.2.1` should be `#### 3.2.1`).
        """
        sections = [
            make_section("2 Widgets", font_size=16.0),
            make_section("body prose to anchor the body size baseline here",
                         font_size=10.0),
            make_section("2.1 Gadgets", font_size=13.0),
            make_section("more body prose text at the body size", font_size=10.0),
            make_section("2.1.1 Sprockets", font_size=13.0),  # same font as 2.1
            make_section("still more body prose at the body size", font_size=10.0),
        ]
        _, result, _ = structure_sections(sections, has_title=True)
        levels = {s.text.split()[0]: s.heading_level
                  for s in result if s.kind == SectionKind.HEADING}
        assert levels.get("2") == 2, levels
        assert levels.get("2.1") == 3, levels
        assert levels.get("2.1.1") == 4, (
            f"numbered subsection clamped off its numbering depth: {levels}")

    def test_title_font_not_counted_as_heading_tier(self):
        """The title's font must not occupy heading rank 1; otherwise every
        body heading ranks one tier too deep (p2040r0: top-level `Building
        blocks` at 14pt rendered `###` instead of `##`)."""
        sections = [
            make_section("The Paper Title Goes Here", font_size=20.0),
            make_section("Building blocks", font_size=14.0),   # top-level, unknown
            make_section("body prose text at the body size here", font_size=10.0),
            make_section("Reflection on expressions", font_size=12.0),  # subheading
            make_section("more body prose text at the body size", font_size=10.0),
        ]
        _, result, _ = structure_sections(sections, has_title=True)
        levels = {s.text: s.heading_level
                  for s in result if s.kind == SectionKind.HEADING}
        assert levels.get("Building blocks") == 2, (
            f"top-level heading not at H2 (title-font pollution): {levels}")
        assert levels.get("Reflection on expressions") == 3, (
            f"subheading not at H3: {levels}")

    def test_title_only_large_font_preserves_leading_paragraphs(self):
        """When the title is the ONLY heading-scale font, excluding it would
        empty the font ranking and destabilise the front-region passes,
        dropping leading body paragraphs (p4024r0). The empty-ranking guard
        keeps the title in, so the paragraphs survive."""
        sections = [
            make_section("Title: Guidance on Something", font_size=26.0),
            make_section("Motivation: the community thrives on diverse input "
                         "and this line is body prose", font_size=12.0),
            make_section("A second body paragraph that continues the prose here",
                         font_size=12.0),
        ]
        _, result, _ = structure_sections(sections, has_title=True)
        texts = "\n".join(s.text for s in result)
        assert "Motivation" in texts, "leading body paragraph dropped"
        assert "second body paragraph" in texts, "second paragraph dropped"

    def test_rank_font_sizes_skip_excludes_sole_holder(self):
        """Skipping the title drops a size only when the title is its sole
        holder; the remaining tiers renumber from rank 1."""
        title = make_section("Title", font_size=20.0)
        body = make_section("body prose here at the base size", font_size=10.0)
        h1 = make_section("Section A", font_size=14.0)
        h2 = make_section("Sub A", font_size=12.0)
        ranks = _rank_font_sizes([title, body, h1, h2], 10.0, skip=title)
        assert 20.0 not in ranks
        assert ranks[14.0] == 1
        assert ranks[12.0] == 2

    def test_rank_font_sizes_skip_keeps_shared_size(self):
        """A size shared by a real heading survives the title skip (only the
        title's own line contribution is dropped, not the size globally)."""
        title = make_section("Title", font_size=14.0)
        h1 = make_section("Section A", font_size=14.0)  # shares the title font
        body = make_section("body prose here", font_size=10.0)
        ranks = _rank_font_sizes([title, h1, body], 10.0, skip=title)
        assert ranks.get(14.0) == 1

    def test_rank_font_sizes_skip_empties_when_title_is_only_tier(self):
        """Documents the guard's trigger: skipping the sole large-font block
        leaves an empty ranking."""
        title = make_section("Title", font_size=26.0)
        p1 = make_section("body prose one at base size", font_size=12.0)
        assert _rank_font_sizes([title, p1], 12.0, skip=title) == {}

    def test_title_section_for_ranking_finds_leading_large_block(self):
        sections = [
            make_section("Some Grand Title", font_size=20.0),
            make_section("Abstract", font_size=14.0),
            make_section("body prose", font_size=10.0),
        ]
        t = _title_section_for_ranking(sections, 10.0)
        assert t is not None and t.text == "Some Grand Title"

    def test_title_section_for_ranking_none_when_numbered_first(self):
        sections = [
            make_section("1 Introduction", font_size=16.0),
            make_section("body prose", font_size=10.0),
        ]
        assert _title_section_for_ranking(sections, 10.0) is None

    def test_title_section_for_ranking_rejects_nonmatching_metadata_title(self):
        """When the metadata title is already known and the leading large-font
        block does not match it, that block is a body heading, not the title:
        it must NOT be returned for exclusion (reviewer sabriguenes on #300)."""
        sections = [
            make_section("Building blocks", font_size=14.0),
            make_section("body prose at the base size", font_size=10.0),
        ]
        t = _title_section_for_ranking(
            sections, 10.0, metadata_title="A Completely Different Title")
        assert t is None

    def test_title_section_for_ranking_accepts_matching_metadata_title(self):
        """A leading large-font block that matches the extracted metadata title
        IS the title and is returned for font-ranking exclusion."""
        sections = [
            make_section("Reflection for C++26", font_size=20.0),
            make_section("body prose at the base size", font_size=10.0),
        ]
        t = _title_section_for_ranking(
            sections, 10.0, metadata_title="Reflection for C++26")
        assert t is not None and t.text == "Reflection for C++26"

    def test_missing_title_block_does_not_steal_body_heading(self):
        """With the real title absent from the body (it came from metadata) and
        the leading large-font block being a body heading, that block must not
        be treated as the title. Otherwise it is excluded from font ranking and
        the hierarchy inverts: `Building blocks` (14pt) rendered H3 and the
        smaller `Reflection on expressions` (12pt) rendered H2 (reviewer
        sabriguenes on #300)."""
        def bold_heading(text, font_size):
            return make_section(
                text, font_size=font_size,
                lines=[make_line([text], font_size=font_size, bold=True)])

        sections = [
            bold_heading("Building blocks", 14.0),
            make_section("body prose text at the body size here", font_size=10.0),
            bold_heading("Reflection on expressions", 12.0),
            make_section("more body prose text at the body size", font_size=10.0),
        ]
        _, result, _ = structure_body(
            sections, has_title=True,
            metadata_title="A Completely Different Paper Title")
        levels = {s.text: s.heading_level
                  for s in result if s.kind == SectionKind.HEADING}
        assert levels.get("Building blocks") == 2, (
            f"leading body heading stolen as the title: {levels}")
        assert levels.get("Reflection on expressions") == 3, (
            f"subheading not at H3 (inverted hierarchy): {levels}")


class TestExtractMetadataKey:
    def test_document_number_produces_document_key(self):
        """Regression: _extract_metadata must write 'document', not 'doc-number'."""
        sections = [
            make_section("Document Number: P1234R0"),
            make_section("Some body text here."),
        ]
        meta, _, _ = structure_sections(sections, has_title=True)
        assert "document" in meta or meta == {}
        assert "doc-number" not in meta

    def test_document_key_not_doc_number(self):
        """The merged front matter must never contain the legacy doc-number key."""
        sec = make_section("Document Number: P9999R2")
        meta, _, _ = structure_sections([sec], has_title=True)
        assert "doc-number" not in meta


class TestExtractMetadataMutation:
    def test_does_not_mutate_input_sections(self):
        """Regression: _extract_metadata must not mutate its input Sections.

        Callers rely on helpers in this module producing new objects,
        consistent with _merge_paragraphs.
        """
        sec = make_section(
            "Document Number: P1234R0\nSome leftover\nBody content",
            kind=SectionKind.PARAGRAPH,
        )
        original_text = sec.text
        _extract_metadata([sec])
        assert sec.text == original_text

    def test_returns_stripped_section_copy(self):
        """The returned section has the metadata lines removed."""
        sec = make_section(
            "Document Number: P1234R0\nSome leftover",
            kind=SectionKind.PARAGRAPH,
        )
        meta, remaining = _extract_metadata([sec])
        assert meta.get("document") == "P1234R0"
        assert len(remaining) == 1
        assert "Document Number" not in remaining[0].text
        assert "Some leftover" in remaining[0].text


class TestCodeBlockUncertainMerge:
    """Uncertain sections that are all-monospace bridge consecutive code runs."""

    def _mono_section(self, text: str, kind=SectionKind.PARAGRAPH) -> Section:
        span = Span(text=text, monospace=True)
        line = Line(spans=[span])
        return Section(kind=kind, text=text, lines=[line],
                       confidence=Confidence.HIGH)

    def test_uncertain_mono_between_code_sections_merged(self):
        """An all-monospace UNCERTAIN section between two code runs is absorbed."""
        top = self._mono_section("void f() {")
        mid = self._mono_section("    return 0;", kind=SectionKind.UNCERTAIN)
        mid.confidence = Confidence.UNCERTAIN
        bot = self._mono_section("}")

        _, sections, _ = structure_sections([top, mid, bot], has_title=False)
        code = [s for s in sections if s.kind == SectionKind.CODE]
        assert len(code) == 1, "expected one merged code block"
        assert "void f()" in code[0].text
        assert "return 0" in code[0].text
        assert "}" in code[0].text

    def test_uncertain_non_mono_between_code_sections_not_merged(self):
        """An UNCERTAIN section with mixed content breaks the code run."""
        top = self._mono_section("void f() {")
        mid_span = Span(text="prose text", monospace=False)
        mid = Section(kind=SectionKind.UNCERTAIN, text="prose text",
                      lines=[Line(spans=[mid_span])],
                      confidence=Confidence.UNCERTAIN)
        bot = self._mono_section("}")

        _, sections, _ = structure_sections([top, mid, bot], has_title=False)
        code = [s for s in sections if s.kind == SectionKind.CODE]
        assert len(code) == 2, "mixed uncertain should not be absorbed"


class TestSplitMixedMonoSections:
    """A PARAGRAPH mixing a long monospace run with prose lines is split
    so the code joins the surrounding fence and the prose stays body text
    (P4231R0: synopsis crossing a page boundary arrived merged with the
    next prose paragraph)."""

    def _line(self, text: str, mono: bool, page_num: int = 0) -> Line:
        return Line(spans=[Span(text=text, monospace=mono)],
                    page_num=page_num)

    def _section(self, lines: list[Line], page_num: int = 0) -> Section:
        text = "\n".join(ln.text for ln in lines)
        return Section(kind=SectionKind.PARAGRAPH, text=text, lines=lines,
                       confidence=Confidence.HIGH, page_num=page_num)

    def test_prose_tail_split_out_of_code(self):
        mixed = self._section([
            self._line("struct rounded {", mono=True),
            self._line("  // a comment line", mono=True),
            self._line("  int member;", mono=True),
            self._line("};", mono=True),
            self._line(" ", mono=False),
            self._line("currently we do not provide literals.", mono=False),
        ])
        _, sections, _ = structure_sections([mixed], has_title=False)
        code = [s for s in sections if s.kind == SectionKind.CODE]
        assert len(code) == 1
        assert "struct rounded {" in code[0].text
        assert "literals" not in code[0].text
        paras = [s for s in sections if s.kind == SectionKind.PARAGRAPH]
        assert any("literals" in s.text for s in paras)

    def test_code_continuation_joins_previous_fence_across_pages(self):
        page2 = self._section([
            self._line("struct rounded {", mono=True),
            self._line("  // digits. It is implementation-defined", mono=True),
        ], page_num=2)
        page3 = self._section([
            self._line("  // constant strings representing", mono=True),
            self._line("  int make(string_view s) const;", mono=True),
            self._line("};", mono=True),
            self._line("currently we do not provide literals.", mono=False),
        ], page_num=3)
        _, sections, _ = structure_sections([page2, page3], has_title=False)
        code = [s for s in sections if s.kind == SectionKind.CODE]
        assert len(code) == 1, "one synopsis must yield one fence"
        assert "struct rounded {" in code[0].text
        assert "};" in code[0].text
        assert "literals" not in code[0].text

    def test_short_inline_mono_runs_do_not_split(self):
        mixed = self._section([
            self._line("the call to make here forces rounding", mono=False),
            self._line("cr_decimal_dig", mono=True),
            self._line("which reduces the surprise factor and", mono=False),
            self._line("round_toward_zero", mono=True),
            self._line("rounds fully as expected here.", mono=False),
        ])
        _, sections, _ = structure_sections([mixed], has_title=False)
        assert len(sections) == 1
        assert sections[0].kind == SectionKind.PARAGRAPH

    def test_interior_nonmono_lines_do_not_split_code(self):
        """Mixed-font code (p0533r9: italic `// see [library.c]` comments
        inside a declaration listing) must stay one section so the rescue
        pass can fence it whole."""
        mixed = self._section([
            self._line("float log2f(float x);", mono=True),
            self._line("long double log2l(long double x);", mono=True),
            self._line("constexpr", mono=True),
            self._line("float logb(float x); // see [library.c]", mono=False),
            self._line("constexpr", mono=True),
            self._line("double logb(double x);", mono=True),
            self._line("float logbf(float x);", mono=True),
        ])
        _, sections, _ = structure_sections([mixed], has_title=False)
        assert len(sections) == 1
        assert sections[0].kind == SectionKind.CODE, (
            "rescue pass should promote the whole listing")

    def test_leading_nonmono_comment_stays_in_code(self):
        """An italic/serif `// comment` line heading a code block
        (p0533r9: `// [c.math.lerp], linear interpolation`) is code in a
        different font, not prose, and must stay in the fence."""
        mixed = self._section([
            self._line("// [c.math.lerp], linear interpolation", mono=False),
            self._line("constexpr float lerp(float a, float b);", mono=True),
            self._line("constexpr double lerp(double a, double b);", mono=True),
            self._line("constexpr long double lerp(long double a);", mono=True),
        ])
        _, sections, _ = structure_sections([mixed], has_title=False)
        code = [s for s in sections if s.kind == SectionKind.CODE]
        assert len(code) == 1
        assert "[c.math.lerp]" in code[0].text

    def test_prose_lead_in_split_off_code(self):
        mixed = self._section([
            self._line("to compute an upper bound we may write:", mono=False),
            self._line("constexpr rounded round_up(x);", mono=True),
            self._line("constexpr rounded round_down(y);", mono=True),
            self._line("round_up.sub(round_down.add(x, y));", mono=True),
        ])
        _, sections, _ = structure_sections([mixed], has_title=False)
        code = [s for s in sections if s.kind == SectionKind.CODE]
        assert len(code) == 1
        assert "upper bound" not in code[0].text
        paras = [s for s in sections if s.kind == SectionKind.PARAGRAPH]
        assert any("upper bound" in s.text for s in paras)


class TestWordingSectionCodeGuard:
    """A syntax-highlighted code block must not be reclassified as wording.

    Some WG21 papers print appendix code listings with keyword syntax
    highlighting whose keyword color (e.g. green ``#008547``, hue ~152)
    falls inside the wording "ins" hue band, so ``classify_wording``
    stamps a stray ``ins`` role on the keyword. When the all-monospace
    listing has already been merged into a ``CODE`` section, a foreign
    chromatic color elsewhere in the section (cyan/olive syntax colors)
    proves it is syntax highlighting, not diff markup, so the section
    must stay ``CODE`` and render as a fenced block instead of collapsing
    into a single ``:::wording-add`` line.
    """

    _GREEN_INS = 0x008547   # ins green keyword, hue ~152
    _FOREIGN_CYAN = 0x006895  # syntax-highlight cyan, hue ~198 (not ins/del/link)
    _BLACK = 0x000000

    def _code_section(self, spans):
        line = Line(spans=spans)
        return Section(
            kind=SectionKind.CODE,
            text=" ".join(s.text for s in spans),
            lines=[line],
            confidence=Confidence.HIGH,
        )

    def test_syntax_highlighted_code_stays_code(self):
        keyword = Span(text="template", color=self._GREEN_INS,
                       monospace=True, wording_role="ins")
        cyan = Span(text="bool", color=self._FOREIGN_CYAN, monospace=True)
        sec = self._code_section([keyword, cyan])

        _classify_wording_sections([sec])

        assert sec.kind == SectionKind.CODE

    def test_green_only_wording_code_still_reclassified(self):
        # Control: no foreign chromatic color means genuine green-only
        # wording-as-code is still promoted, so the guard is targeted.
        keyword = Span(text="constexpr", color=self._GREEN_INS,
                       monospace=True, wording_role="ins")
        black = Span(text="void f();", color=self._BLACK, monospace=True)
        sec = self._code_section([keyword, black])

        _classify_wording_sections([sec])

        assert sec.kind == SectionKind.WORDING_ADD

    def test_deletion_amid_syntax_highlighting_stays_wording(self):
        # A genuine strikethrough deletion ("del") inside syntax-highlighted
        # monospace code (foreign chromatic spans present) is real WG21
        # wording and must NOT be suppressed by the ins-only code guard.
        deletion = Span(text="__j", color=self._BLACK,
                        monospace=True, wording_role="del")
        magenta = Span(text="__k", color=0xFF00FF, monospace=True)
        sec = self._code_section([deletion, magenta])

        _classify_wording_sections([sec])

        assert sec.kind == SectionKind.WORDING_REMOVE

    def test_bare_numeral_ins_stays_code(self):
        # Issue #305: a PDF that colors numeric literals for its own
        # syntax-highlighting reasons (no foreign chromatic companion, so
        # the color guard above does not fire) must not have an ordinary
        # code example ("gen(777)") wrapped in a fake ":::wording-add" with
        # "<ins>777</ins>" inside the fence.
        literal = Span(text="777", color=self._GREEN_INS,
                       monospace=True, wording_role="ins")
        black = Span(text="std::mt19937 gen();", color=self._BLACK,
                    monospace=True)
        sec = self._code_section([black, literal])

        _classify_wording_sections([sec])

        assert sec.kind == SectionKind.CODE

    def test_numeral_and_identifier_ins_mix_still_reclassified(self):
        # Control: the bare-numeral guard only fires when EVERY ins span is
        # a bare numeral. A section that also inserts a real identifier
        # (e.g. a genuine "constexpr" edit alongside a renumbered literal)
        # is still promoted, so the guard stays targeted.
        literal = Span(text="777", color=self._GREEN_INS,
                       monospace=True, wording_role="ins")
        keyword = Span(text="constexpr", color=self._GREEN_INS,
                       monospace=True, wording_role="ins")
        black = Span(text="void f();", color=self._BLACK, monospace=True)
        sec = self._code_section([keyword, literal, black])

        _classify_wording_sections([sec])

        assert sec.kind == SectionKind.WORDING_ADD


class TestBlockFontSize:
    def test_line_count_voting(self):
        """Block.font_size uses line-count voting, not character weighting."""
        from conftest import make_span
        block = Block(lines=[
            Line(spans=[make_span(
                "word word word word word word word word", font_size=11.0)]),
            Line(spans=[make_span("short", font_size=14.0)]),
            Line(spans=[make_span("short", font_size=14.0)]),
        ])
        # Lines: two at 14, one at 11 -> 14 wins by line count.
        # Character count would favor 11.
        assert block.font_size == 14.0


# ---------------------------------------------------------------------------
# Regression coverage for PR #9 fixes.
# ---------------------------------------------------------------------------


def _mk_section(text, *, font_size=10.0, monospace=False, bold=False,
                kind=SectionKind.PARAGRAPH,
                confidence=Confidence.HIGH, heading_level=0):
    """Build a Section whose single line carries explicit span attributes."""
    span = make_span(text, font_size=font_size,
                      monospace=monospace, bold=bold)
    line = Line(spans=[span])
    return Section(kind=kind, text=text, confidence=confidence,
                   heading_level=heading_level, lines=[line],
                   font_size=font_size)


class TestDetectBodySizeProsePreference:
    """`_detect_body_size` prefers prose over monospace on code-heavy papers."""

    def test_prose_wins_over_monospace_majority(self):
        """Prose beats a more frequent monospace size when it clears the floor."""
        prose = [_mk_section("prose line " + ("x" * 60), font_size=11.0)
                 for _ in range(10)]
        code = [_mk_section("code line " + ("y" * 60), font_size=9.0,
                             monospace=True) for _ in range(30)]
        body = _detect_body_size(prose + code)
        assert body == 11.0, (
            "prose font should be picked as body even when monospace spans "
            "hold more characters overall"
        )

    def test_fallback_to_all_when_prose_too_small(self):
        """When prose is scarce, the overall most-common size wins (wording papers)."""
        tiny_prose = [_mk_section("hi", font_size=11.0)]  # <<500 chars
        code = [_mk_section("code " + ("y" * 200), font_size=9.0,
                             monospace=True) for _ in range(10)]
        body = _detect_body_size(tiny_prose + code)
        assert body == 9.0, (
            "with insufficient prose, body falls back to the most common size"
        )

    def test_empty_sections_fall_back(self):
        """No data at all returns the FALLBACK_BODY_SIZE."""
        from tomd.lib.pdf.types import FALLBACK_BODY_SIZE
        assert _detect_body_size([]) == FALLBACK_BODY_SIZE


class TestHeadingProseLengthRejection:
    """Long numbered first lines don't become headings at LOW confidence."""

    def test_long_numbered_line_demoted(self):
        """A numbered prose line with >12 words and no font/bold signal is a paragraph."""
        long_line = ("1 A fiber is a single flow of control with a "
                     "private stack and an associated execution context.")
        sec = _mk_section(long_line, font_size=10.0)
        # Flank it with body text at the same size so `_detect_body_size`
        # agrees that 10.0 is body and no font-level signal fires.
        body_fill = [_mk_section("ordinary body " + ("x" * 80), font_size=10.0)
                     for _ in range(10)]
        _, result, _ = structure_sections(body_fill + [sec], has_title=True)
        demoted = [s for s in result if long_line in s.text]
        assert demoted, "expected the long numbered line to appear in output"
        assert all(s.kind != SectionKind.HEADING for s in demoted), (
            "prose-length first line should not become a heading at LOW conf"
        )

    def test_long_numbered_line_kept_with_font_signal(self):
        """A long numbered line at a heading font size is preserved as a heading."""
        long_title = ("1 A fiber is a single flow of control with a "
                      "private stack and an associated execution context")
        heading = _mk_section(long_title, font_size=14.0)
        body_fill = [_mk_section("plain body " + ("x" * 80), font_size=10.0)
                     for _ in range(10)]
        _, result, _ = structure_sections(body_fill + [heading], has_title=True)
        matches = [s for s in result if long_title in s.text]
        assert matches and any(s.kind == SectionKind.HEADING for s in matches), (
            "long numbered line at heading font size must stay a HEADING "
            "(MEDIUM or HIGH confidence survives the length cap)"
        )


class TestGlyphBulletPrefixLine:
    """Sections whose first line is a bullet character plus an injected
    glyph placeholder (canonical N5007 page 11 Profiles case) must stay
    candidates for list-item merging, not become headings, even when
    the synthetic sentinel span's bbox-derived font_size triggers
    ``heading_confidence``'s font-rank branch.
    """

    @staticmethod
    def _bullet_then_body_section(*, body_size=10.5, sentinel_size=12.75):
        """Two-line section: line 1 is "●" + sentinel "�", line 2 is body text.

        Mirrors N5007 page 11's Profiles bullets, where the PDF
        renders ``●`` as text and overlays a small raster emoji that
        the glyph pass replaces with ``UNKNOWN_GLYPH``. The sentinel
        carries a slightly larger ``font_size`` than body, which is
        what previously promoted the line to a heading.
        """
        from tomd.lib.pdf.glyphs import GLYPH_FONT_SENTINEL, UNKNOWN_GLYPH

        bullet_line = Line(spans=[
            make_span("●", font_size=body_size),
            make_span(UNKNOWN_GLYPH, font_size=sentinel_size,
                      font_name=GLYPH_FONT_SENTINEL),
        ])
        body_line = Line(spans=[
            make_span(" P3589 — C++ Profiles: The Framework",
                      font_size=body_size),
        ])
        text = "●" + UNKNOWN_GLYPH + "\n P3589 — C++ Profiles: The Framework"
        # font_size on Section is taken from the sentinel-bearing line in
        # the real pipeline (`_compute_section_font_size` uses span max);
        # match that here so the heading-detection font_level branch is
        # exercised.
        return Section(
            kind=SectionKind.PARAGRAPH, text=text,
            confidence=Confidence.HIGH, heading_level=0,
            lines=[bullet_line, body_line], font_size=sentinel_size,
        )

    def test_bullet_plus_sentinel_first_line_not_a_heading(self):
        """A bullet-then-sentinel first line keeps the section as a
        PARAGRAPH so downstream list detection can merge bullet + body.
        Without this guard, the synthetic span's larger font_size would
        trip heading_confidence and promote the section to a heading -
        the canonical N5007 Profiles regression.
        """
        # Body context big enough to compute body size and font ranks.
        body_fill = [_mk_section("ordinary body " + ("x" * 80), font_size=10.5)
                     for _ in range(10)]
        sec = self._bullet_then_body_section()
        _, result, _ = structure_sections(body_fill + [sec], has_title=True)
        # Find the section whose text starts with the bullet character.
        matches = [s for s in result if s.text.startswith("●")
                   or "P3589" in s.text]
        assert matches, "expected the bullet+body section in the output"
        assert all(s.kind != SectionKind.HEADING for s in matches), (
            "bullet+sentinel first line must not promote section to HEADING"
        )

    def test_bullet_plus_sentinel_keeps_body_text(self):
        """The paper-title body line must survive the structural pass,
        not be orphaned by a mis-classified heading dropping its tail.
        """
        body_fill = [_mk_section("ordinary body " + ("x" * 80), font_size=10.5)
                     for _ in range(10)]
        sec = self._bullet_then_body_section()
        _, result, _ = structure_sections(body_fill + [sec], has_title=True)
        joined = "\n".join(s.text for s in result)
        assert "P3589" in joined, (
            "paper-title body line must survive; was lost when bullet "
            "line was mis-classified as a heading"
        )


class TestMonospaceCodeSyntaxFirstLineNotAHeading:
    """A monospace first line with code-syntax characters is code, never
    a section heading.

    Canonical case: single-page extracts of P4012R0 skew the font
    distribution so the C++ code font ranks above body. Without an
    outer guard, ``heading_confidence``'s ``font_level`` branch returns
    ``level = font_level + 1`` and promotes lines like
    ``V f(int n, short m, ...)`` and ``V x = '\\1'; // OK`` to H2.
    ``_split_heading_body`` then drops the rest of the listing into a
    PARAGRAPH where ``emit.py`` renders each monospace span as inline
    code, splitting one CODE block into "fence + headings + backticked
    paragraph".

    The conjunction (monospace AND ``_CODE_CHARS`` overlap) is the
    discriminator: ``std::assert`` is monospace but carries no syntax
    punctuation and must stay a legitimate code-styled heading
    (golden: p2040r0).
    """

    _CODE_LINE = (
        "V f(int n, short m, std::reference_wrapper <int > l, "
        "std::reference_wrapper <float > f)"
    )

    @staticmethod
    def _mono_section(text, *, font_size, bold=False):
        return _mk_section(text, font_size=font_size,
                           monospace=True, bold=bold)

    def test_monospace_code_syntax_at_heading_font_stays_non_heading(self):
        """A monospace line with parens/semicolons at heading font is not H2."""
        body_fill = [_mk_section("ordinary body " + ("x" * 80), font_size=10.0)
                     for _ in range(10)]
        # 11.0 > 10.0 * _HEADING_SIZE_RATIO (1.05) so it ranks as a heading.
        sec = self._mono_section(self._CODE_LINE, font_size=11.0)
        _, result, _ = structure_sections(body_fill + [sec], has_title=True)
        matches = [s for s in result if self._CODE_LINE in s.text]
        assert matches, "expected the monospace code line in the output"
        assert all(s.kind != SectionKind.HEADING for s in matches), (
            "monospace first line with code-syntax chars must never be "
            "promoted to HEADING even when its font ranks as a heading size"
        )

    def test_monospace_bold_code_syntax_stays_non_heading(self):
        """Bold + monospace + code-syntax + heading font still isn't a heading."""
        body_fill = [_mk_section("ordinary body " + ("x" * 80), font_size=10.0)
                     for _ in range(10)]
        sec = self._mono_section(self._CODE_LINE, font_size=11.0, bold=True)
        _, result, _ = structure_sections(body_fill + [sec], has_title=True)
        matches = [s for s in result if self._CODE_LINE in s.text]
        assert matches
        assert all(s.kind != SectionKind.HEADING for s in matches)

    def test_monospace_run_collapses_into_one_code_block(self):
        """A run of monospace code-syntax sections becomes one CODE block.

        Mirrors the P4012R0 page-extract cascade: previously the first
        line split off as a heading and the rest became a backticked
        paragraph; now ``_detect_code_blocks`` folds the whole run into
        a single CODE section.
        """
        body_fill = [_mk_section("ordinary body " + ("x" * 80), font_size=10.0)
                     for _ in range(10)]
        code_lines = [
            self._CODE_LINE,
            "V x = '\\1'; // OK",
            "x = 1; // OK",
            "x = V(n); // ill-formed",
        ]
        code_secs = [self._mono_section(t, font_size=11.0) for t in code_lines]
        _, result, _ = structure_sections(body_fill + code_secs,
                                          has_title=True)
        code_kinds = [s.kind for s in result
                      if any(line in s.text for line in code_lines)]
        assert code_kinds, "expected at least one code section in the output"
        assert all(k == SectionKind.CODE for k in code_kinds), (
            "monospace run must collapse to CODE, not split into HEADING + "
            f"PARAGRAPH; got kinds={code_kinds}"
        )

    def test_monospace_styled_heading_without_code_syntax_stays_heading(self):
        """A monospace identifier-only heading like ``std::assert`` is kept.

        Pins the ``_CODE_CHARS`` half of the conjunction: an API-name
        heading rendered in monospace (no parens, no braces, no ``=``,
        no semicolon) must still be promoted to a HEADING. Without this
        guarantee the p2040r0 golden regresses: ``### `std::assert```
        gets demoted into the following code fence.
        """
        body_fill = [_mk_section("ordinary body " + ("x" * 80), font_size=10.0)
                     for _ in range(10)]
        sec = self._mono_section("std::assert", font_size=12.0, bold=True)
        _, result, _ = structure_sections(body_fill + [sec], has_title=True)
        matches = [s for s in result if s.text == "std::assert"]
        assert matches, "expected the code-styled heading in the output"
        assert any(s.kind == SectionKind.HEADING for s in matches), (
            "monospace identifier-only line at a heading font must stay "
            "a HEADING (no code-syntax characters means it's a styled name, "
            "not a code expression)"
        )


class TestDemoteRepeatedLowConfidenceNumbers:
    """Paragraph-number resets collapse to PARAGRAPH; TOC/body pairs do not."""

    def _heading(self, num, text, *, confidence=Confidence.LOW):
        return _mk_section(f"{num} {text}", font_size=10.0,
                            kind=SectionKind.HEADING,
                            confidence=confidence, heading_level=2)

    def test_three_repeats_demoted(self):
        """section_num repeating >=3 times at LOW confidence becomes PARAGRAPH."""
        sections = [
            self._heading("1", "Constraints: first"),
            self._heading("2", "Mandates: one"),
            self._heading("1", "Preconditions: second"),
            self._heading("1", "Effects: third"),
        ]
        _demote_repeated_low_confidence_numbers(sections)
        ones = [s for s in sections if s.text.startswith("1 ")]
        assert all(s.kind == SectionKind.PARAGRAPH for s in ones), (
            "three or more occurrences of number '1' at LOW conf should demote"
        )
        assert all(s.heading_level == 0 for s in ones)

    def test_two_repeats_preserved(self):
        """A TOC/body pair (count == 2) is NOT demoted."""
        sections = [
            self._heading("1", "Introduction"),
            self._heading("1", "Introduction"),  # second copy (body)
        ]
        _demote_repeated_low_confidence_numbers(sections)
        assert all(s.kind == SectionKind.HEADING for s in sections), (
            "pair-count (TOC + body) should be left alone"
        )

    def test_medium_confidence_not_demoted(self):
        """MEDIUM/HIGH confidence headings are never touched, even if they repeat."""
        sections = [
            self._heading("1", "a", confidence=Confidence.MEDIUM),
            self._heading("1", "b", confidence=Confidence.MEDIUM),
            self._heading("1", "c", confidence=Confidence.MEDIUM),
        ]
        _demote_repeated_low_confidence_numbers(sections)
        assert all(s.kind == SectionKind.HEADING for s in sections)

    def test_demoted_confidence_left_low(self):
        """Pins current behavior: demoted sections keep Confidence.LOW.

        Not currently observed as a problem; documented in
        issues/pr9-review.md. Any change to the demotion path should
        consciously revisit this pin.
        """
        sections = [
            self._heading("1", "first"),
            self._heading("1", "second"),
            self._heading("1", "third"),
        ]
        _demote_repeated_low_confidence_numbers(sections)
        assert all(s.confidence == Confidence.LOW for s in sections), (
            "demoted paragraphs currently retain their heading's LOW "
            "confidence; update issues/pr9-review.md if this changes"
        )


class TestValidateNestingSiblingClamp:
    """Same-font-size consecutive headings are treated as siblings."""

    def _h(self, text, *, level, fs):
        return _mk_section(text, font_size=fs,
                            kind=SectionKind.HEADING,
                            confidence=Confidence.HIGH,
                            heading_level=level)

    def test_sibling_run_stays_flat(self):
        """A long run of same-font revision headings doesn't cascade."""
        sections = [
            self._h("## Changes", level=2, fs=14.0),
            self._h("### Changes since P21", level=3, fs=12.0),
            # Each of the following originally got level = prev_clamped + 1.
            # Sibling logic pins them all to level 3.
            self._h("#### Changes since P20", level=4, fs=12.0),
            self._h("##### Changes since P19", level=5, fs=12.0),
            self._h("###### Changes since P18", level=6, fs=12.0),
        ]
        _validate_nesting(sections)
        levels = [s.heading_level for s in sections]
        assert levels == [2, 3, 3, 3, 3], (
            f"expected runs of same-font siblings at level 3; got {levels}"
        )

    def test_sibling_downgrades_high_to_medium(self):
        """When the sibling rule fires, HIGH confidence drops to MEDIUM."""
        sections = [
            self._h("## Root", level=2, fs=14.0),
            self._h("### Child", level=3, fs=12.0),
            self._h("#### Grandchild", level=4, fs=12.0),
        ]
        _validate_nesting(sections)
        gc = sections[-1]
        assert gc.heading_level == 3
        assert gc.confidence == Confidence.MEDIUM

    def test_different_font_allows_nesting(self):
        """Truly different font sizes still pass through the skip-level rule."""
        sections = [
            self._h("## Root", level=2, fs=14.0),
            self._h("### Child", level=3, fs=12.0),
            self._h("#### Grandchild", level=4, fs=10.0),
        ]
        _validate_nesting(sections)
        assert [s.heading_level for s in sections] == [2, 3, 4]

    def test_current_behavior_flattens_legit_nesting_same_font(self):
        """Pins the risk documented in issues/pr9-review.md.

        Papers that express depth through section numbering while using
        one font size for all sub-levels will have legitimate h4s clamped
        to h3. This test encodes the CURRENT behavior so that any future
        change (e.g. letting section-number depth veto the sibling rule)
        is noticed in review.
        """
        sections = [
            self._h("## 2 Motivation", level=2, fs=14.0),
            self._h("### 2.1 Background", level=3, fs=12.0),
            self._h("#### 2.1.1 History", level=4, fs=12.0),
        ]
        _validate_nesting(sections)
        assert sections[-1].heading_level == 3, (
            "currently flattens 2.1.1 to h3; update issues/pr9-review.md "
            "if section-number depth is made to veto the sibling rule"
        )

    def test_tight_font_tolerance_misses_fractional_variance(self):
        """Pins the risk documented in issues/pr9-review.md.

        `_SIBLING_FONT_TOL = 0.1` rejects sibling status between 11.7 and
        12.0 (diff 0.3), which is within the fractional variance common
        in LaTeX PDFs. Encodes CURRENT behavior.
        """
        sections = [
            self._h("## Root", level=2, fs=14.0),
            self._h("### Sibling A", level=3, fs=12.0),
            # fs = 11.7 is > 0.1 away from 12.0, so NOT a sibling;
            # skip-level rule clamps level 5 -> 4 (prev + 1).
            self._h("##### Sibling B", level=5, fs=11.7),
        ]
        _validate_nesting(sections)
        assert sections[-1].heading_level == 4, (
            "current absolute 0.1 tolerance treats 11.7 and 12.0 as "
            "different tiers; widening the tolerance would change this "
            "assertion — see issues/pr9-review.md"
        )

    def test_close_fractional_is_sibling(self):
        """Within the 0.1 tolerance, sizes like 11.95 vs 12.0 are siblings."""
        sections = [
            self._h("## Root", level=2, fs=14.0),
            self._h("### Sibling A", level=3, fs=12.0),
            self._h("#### Sibling B", level=4, fs=11.95),
        ]
        _validate_nesting(sections)
        assert sections[-1].heading_level == 3


class TestValidateNestingInversion:
    """A larger-font heading must not render deeper than the smaller-font
    heading before it (inverted nesting). Regression for issue #154
    (P4221R0): the non-known top-level section "Proposed Functions" (20pt)
    was rendered at h3, deeper than the known "Overview" (16pt) pinned to
    h2, so the parent sat below its child.
    """

    def _h(self, text, *, level, fs):
        return _mk_section(text, font_size=fs,
                            kind=SectionKind.HEADING,
                            confidence=Confidence.HIGH,
                            heading_level=level)

    def test_larger_font_heading_promoted_above_smaller_predecessor(self):
        sections = [
            self._h("Background", level=2, fs=16.0),
            self._h("Proposed Functions", level=3, fs=20.0),
            self._h("Overview", level=2, fs=16.0),
        ]
        _validate_nesting(sections)
        assert [s.heading_level for s in sections] == [2, 2, 2], (
            "the larger-font parent must not be deeper than its neighbours"
        )

    def test_inversion_repair_downgrades_high_to_medium(self):
        sections = [
            self._h("Background", level=2, fs=16.0),
            self._h("Proposed Functions", level=3, fs=20.0),
        ]
        _validate_nesting(sections)
        assert sections[1].heading_level == 2
        assert sections[1].confidence == Confidence.MEDIUM

    def test_smaller_font_deeper_heading_unchanged(self):
        """Normal nesting (smaller font, deeper level) is not touched."""
        sections = [
            self._h("Proposed Functions", level=2, fs=20.0),
            self._h("Overview", level=3, fs=16.0),
        ]
        _validate_nesting(sections)
        assert [s.heading_level for s in sections] == [2, 3]

    def test_numbered_deeper_heading_not_promoted_by_font(self):
        """A numbered subsection keeps its number-derived level even when
        the source styles it with a larger font than its parent. Font must
        never override section numbering."""
        sections = [
            self._h("2 Motivation", level=2, fs=14.0),
            self._h("2.1 Background", level=3, fs=16.0),
        ]
        _validate_nesting(sections)
        assert sections[1].heading_level == 3, (
            "numbered headings keep their number-derived level"
        )


def _block_at(y, texts, page_num=0, mono=False, x=0):
    """A Block whose lines carry real (x, y) positions, stacked from y down.

    conftest's make_block leaves line bbox at the default (0,0,0,0),
    which the reading-order sort cannot use, so these tests build
    Block/Line/Span directly. ``mono=True`` marks every span monospace
    so structure_sections' code-block detector treats the block as a
    code run. ``x`` is the left edge; lines span ``x``..``x+100`` so a
    second column at ``x=300`` is gutter-separated from one at ``x=0``.
    """
    lines = []
    for i, t in enumerate(texts):
        top = y + i * 10
        span = Span(text=t, monospace=mono, bbox=(x, top, x + 100, top + 8))
        lines.append(Line(spans=[span], bbox=(x, top, x + 100, top + 8),
                          page_num=page_num))
    return Block(lines=lines, page_num=page_num,
                 bbox=(x, y, x + 100, y + len(texts) * 10))


class TestReadingOrderRepair:
    """compare_extractions repairs a MuPDF stream that reports a code
    block out of order, but only when the reorder moves code alone."""

    def test_displaced_code_block_moved_among_prose(self):
        # MuPDF reports a monospace code block (y=200) last, after the
        # prose that physically follows it (y=360, y=500). The repair
        # moves the code to its y slot; the prose order is untouched.
        code = _block_at(200, ["do_read ( sock , buf );"], mono=True)
        prose1 = _block_at(360, ["The first body paragraph sits here."])
        prose2 = _block_at(500, ["The second body paragraph sits here."])
        mupdf = [prose1, prose2, code]            # code reported last
        sections = compare_extractions(mupdf, mupdf)
        first_lines = [s.text.split("\n")[0] for s in sections]
        assert first_lines == [
            "do_read ( sock , buf );",
            "The first body paragraph sits here.",
            "The second body paragraph sits here.",
        ]

    def test_displaced_monospace_not_merged_across_body(self):
        # Page layout in reading order: code A @200, prose @360 and @500,
        # code B @660. MuPDF supplies them mis-ordered (prose, prose, B,
        # A); leaving that order adjacent A and B and merges them into one
        # code block. The repair separates them by the intervening prose.
        code_a = _block_at(200, ["do_read ( sock , buf )",
                                 "  | then ([] { return; });"], mono=True)
        prose1 = _block_at(360, ["The consequence is that this travels "
                                 "together and nothing is lost here."])
        prose2 = _block_at(500, ["Andrzej observes the pipeline carries "
                                 "the program logic as follows:"])
        code_b = _block_at(660, ["Level: I/O Composed Classification",
                                 "success: [read] -> [process]"], mono=True)
        mupdf = [prose1, prose2, code_b, code_a]   # MuPDF's wrong order
        # Mirror the real pipeline: compare_extractions (where the repair
        # lives) then structure_sections. Identical m/s keeps the page
        # confident so blocks stay separate.
        sections_in = compare_extractions(mupdf, mupdf)
        _, sections, _ = structure_sections(sections_in, has_title=True)

        code = [s for s in sections if s.kind == SectionKind.CODE]
        assert len(code) == 2, "displaced code must not merge with code B"
        assert "do_read" in code[0].text and "Level: I/O" not in code[0].text
        assert "Level: I/O" in code[1].text
        # Assert the full reading order, not just "first CODE before
        # first PARAGRAPH" (which [CODE, CODE, PARA, PARA] would also
        # satisfy): the do_read block brackets the prose above, the
        # Level: I/O block brackets it below.
        order = [(s.kind.name, s.text[:24]) for s in sections]
        do_read_i = next(i for i, (k, t) in enumerate(order)
                         if k == "CODE" and "do_read" in t)
        level_i = next(i for i, (k, t) in enumerate(order)
                       if k == "CODE" and "Level: I/O" in t)
        prose_idx = [i for i, (k, _) in enumerate(order) if k == "PARAGRAPH"]
        assert prose_idx, "intervening prose must survive"
        assert do_read_i < min(prose_idx) < max(prose_idx) < level_i

    def test_prose_only_reorder_is_not_applied(self):
        # Two prose (non-monospace) blocks out of y-order. Reordering them
        # would move an anchor, so the repair is rejected and MuPDF order
        # stands. This is what protects footers and metadata blocks whose
        # MuPDF position downstream passes (TOC strip, dedup) rely on.
        late = _block_at(600, ["alpha beta gamma delta epsilon zeta"])
        early = _block_at(200, ["one two three four five six seven"])
        mupdf = [late, early]                      # prose out of y-order
        sections = compare_extractions(mupdf, mupdf)
        first_lines = [s.text.split("\n")[0] for s in sections]
        assert first_lines == [
            "alpha beta gamma delta epsilon zeta",   # MuPDF order kept
            "one two three four five six seven",
        ]

    def test_multicolumn_prose_preserves_mupdf_order(self):
        # Two-column prose page: MuPDF emits the whole left column, then
        # the whole right column. A y-sort would interleave them; the
        # column guard rejects the reorder so MuPDF's order stands.
        left_top = _block_at(100, ["left column top paragraph text",
                                    "wrapping onto a second line here"], x=50)
        left_bot = _block_at(300, ["left column bottom paragraph text",
                                   "also wrapping a second line"], x=50)
        right_top = _block_at(110, ["right column top paragraph text",
                                    "right wrapping second line"], x=300)
        right_bot = _block_at(320, ["right column bottom paragraph text",
                                    "right bottom second line"], x=300)
        mupdf = [left_top, left_bot, right_top, right_bot]   # column order
        sections = compare_extractions(mupdf, mupdf)
        first_lines = [s.text.split("\n")[0] for s in sections]
        assert first_lines == [
            "left column top paragraph text",
            "left column bottom paragraph text",
            "right column top paragraph text",
            "right column bottom paragraph text",
        ]

    def test_multicolumn_code_comparison_preserves_mupdf_order(self):
        # Side-by-side CODE comparison (p1112r4 shape): both columns are
        # monospace, so the anchor gate alone would accept interleaving
        # them. The column guard must reject the reorder. MuPDF emits the
        # left code column then the right.
        left = _block_at(100, ["struct cell {", "  int idx;", "};"],
                         x=90, mono=True)
        right = _block_at(110, ["struct layout(standard) cell {",
                                "  int idx;", "};"], x=311, mono=True)
        mupdf = [left, right]                      # column reading order
        sections = compare_extractions(mupdf, mupdf)
        first_lines = [s.text.split("\n")[0] for s in sections]
        assert first_lines == ["struct cell {",
                               "struct layout(standard) cell {"]


def _sec(block):
    """Wrap a _block_at Block in a PARAGRAPH Section (lines drive the gate)."""
    return Section(kind=SectionKind.PARAGRAPH, text=block.text,
                   lines=block.lines, page_num=block.page_num)


class TestReordersOnlyMonospace:
    def test_only_code_moved_is_accepted(self):
        code = _sec(_block_at(200, ["code();"], mono=True))
        prose1 = _sec(_block_at(360, ["first prose block"]))
        prose2 = _sec(_block_at(500, ["second prose block"]))
        page = [prose1, prose2, code]              # code reported last
        y_sorted = sorted(page, key=_section_top_y)
        assert _reorders_only_monospace(page, y_sorted) is True

    def test_moved_anchor_is_rejected(self):
        # Two prose anchors out of y-order: sorting moves an anchor.
        page = [_sec(_block_at(600, ["late prose"])),
                _sec(_block_at(200, ["early prose"]))]
        y_sorted = sorted(page, key=_section_top_y)
        assert _reorders_only_monospace(page, y_sorted) is False


class TestPageIsMulticolumn:
    def test_side_by_side_blocks_detected(self):
        left = _sec(_block_at(100, ["left text"], x=50))
        right = _sec(_block_at(105, ["right text"], x=300))  # overlap+gutter
        assert _page_is_multicolumn([left, right]) is True

    def test_stacked_single_column_not_detected(self):
        top = _sec(_block_at(100, ["first stacked block"], x=50))
        bot = _sec(_block_at(300, ["second stacked block"], x=50))
        assert _page_is_multicolumn([top, bot]) is False

    def test_full_width_stacked_not_multicolumn(self):
        # Title/metadata stacked vertically (no horizontal neighbor) are
        # single-column even when they start at different x.
        a = _sec(_block_at(100, ["wide title spanning"], x=200))
        b = _sec(_block_at(200, ["document metadata line"], x=80))
        assert _page_is_multicolumn([a, b]) is False


class TestSectionTopY:
    def test_min_over_positioned_lines(self):
        sec = Section(kind=SectionKind.PARAGRAPH, text="x", lines=[
            Line(spans=[Span(text="lower")], bbox=(0, 500, 10, 508)),
            Line(spans=[Span(text="upper")], bbox=(0, 100, 10, 108)),
        ])
        assert _section_top_y(sec) == 100        # min, not first

    def test_blank_and_zero_width_lines_ignored(self):
        zero_width = chr(0x200B) + chr(0xFEFF)   # ZWSP + BOM/ZWNBSP
        sec = Section(kind=SectionKind.PARAGRAPH, text="x", lines=[
            Line(spans=[Span(text="   ")], bbox=(0, 40, 10, 48)),
            Line(spans=[Span(text=zero_width)], bbox=(0, 50, 10, 58)),
            Line(spans=[Span(text="real")], bbox=(0, 300, 10, 308)),
        ])
        assert _section_top_y(sec) == 300        # @40 and @50 skipped

    def test_default_bbox_line_excluded(self):
        # A (0,0,0,0) bbox is truthy; it must NOT collapse the anchor to 0.
        sec = Section(kind=SectionKind.PARAGRAPH, text="x", lines=[
            Line(spans=[Span(text="floating")]),               # default bbox
            Line(spans=[Span(text="real")], bbox=(0, 220, 10, 228)),
        ])
        assert _section_top_y(sec) == 220

    def test_no_anchor_falls_back_to_inf(self):
        sec = Section(kind=SectionKind.PARAGRAPH, text="x", lines=[])
        assert _section_top_y(sec) == math.inf

    def test_cross_page_continuation_line_ignored(self):
        # The cross-page join appends a next-page line (small y) into the
        # last section of a page. The anchor must stay on the section's
        # own page, not jump to the continuation line's top-of-page y.
        sec = Section(kind=SectionKind.PARAGRAPH, text="x", page_num=6, lines=[
            Line(spans=[Span(text="own page tail")], bbox=(0, 700, 10, 710),
                 page_num=6),
            Line(spans=[Span(text="next page head")], bbox=(0, 55, 10, 65),
                 page_num=7),
        ])
        assert _section_top_y(sec) == 700


class TestSplitEmbeddedCode:
    """`_split_embedded_code` extracts code runs glued into prose."""

    @staticmethod
    def _line(text, *, mono):
        return Line(spans=[Span(text=text, monospace=mono)])

    def _paragraph(self, specs):
        lines = [self._line(t, mono=m) for t, m in specs]
        text = "\n".join(t for t, _ in specs)
        return Section(kind=SectionKind.PARAGRAPH, text=text, lines=lines)

    def test_code_run_between_prose_is_extracted(self):
        sec = self._paragraph([
            ("Some heading text", False),
            ("V f(V x) {", True),
            ("  return x + 1;", True),
            ("}", True),
            ("needs to use something else.", False),
        ])
        out = _split_embedded_code([sec])
        kinds = [s.kind for s in out]
        assert kinds == [
            SectionKind.PARAGRAPH, SectionKind.CODE, SectionKind.PARAGRAPH,
        ]
        assert out[1].text == "V f(V x) {\n  return x + 1;\n}"
        assert out[0].text == "Some heading text"
        assert out[2].text == "needs to use something else."

    def test_single_mono_line_not_split(self):
        # A lone inline monospace line is below _SPLIT_MIN_CODE_RUN.
        sec = self._paragraph([
            ("prose before", False),
            ("inline_ref", True),
            ("prose after", False),
        ])
        out = _split_embedded_code([sec])
        assert [s.kind for s in out] == [SectionKind.PARAGRAPH]

    def test_wording_section_untouched(self):
        sec = self._paragraph([
            ("template<class T> {", True),
            ("  body;", True),
        ])
        sec.kind = SectionKind.WORDING_ADD
        out = _split_embedded_code([sec])
        assert out == [sec]

    def test_already_code_section_untouched(self):
        sec = self._paragraph([
            ("// comment", False),
            ("V f(V x) {", True),
            ("}", True),
        ])
        sec.kind = SectionKind.CODE
        out = _split_embedded_code([sec])
        assert out == [sec]


class TestCoalesceCodeParagraphs:
    """`_coalesce_code_paragraphs` merges adjacent short code-like paragraphs.

    Regression guard for the text/lines desync (P3181R1): the merged
    section must carry the lines of every run member, not just run[0].
    Emit renders CODE from sec.lines, so a desync silently drops content.
    """

    @staticmethod
    def _para(*texts):
        lines = [Line(spans=[Span(text=t)]) for t in texts]
        return Section(
            kind=SectionKind.PARAGRAPH,
            text="\n".join(texts),
            lines=lines,
        )

    def test_merged_lines_match_merged_text(self):
        # Two short code-like paragraphs that satisfy _COALESCE_CODE_RE.
        a = self._para("fence(release);", "a1: a->store(1, relaxed);")
        b = self._para("b1: r1 = a->load(acquire);", "b2: delete a;")
        out = _coalesce_code_paragraphs([a, b])
        assert len(out) == 1
        merged = out[0]
        # text and lines must stay in sync: no silent content loss.
        assert len(merged.lines) == len(a.lines) + len(b.lines)
        assert [ln.text for ln in merged.lines] == merged.text.split("\n")
        # the run[1:] content survives in the rendered (lines) channel.
        rendered = "\n".join(ln.text for ln in merged.lines)
        assert "b2: delete a;" in rendered

    def test_single_section_run_not_merged(self):
        # A lone code-like paragraph (run length 1) is passed through.
        a = self._para("fence(release);", "a1: a->store(1, relaxed);")
        prose = Section(
            kind=SectionKind.PARAGRAPH,
            text="This is ordinary prose that ends with a period.",
            lines=[Line(spans=[Span(
                text="This is ordinary prose that ends with a period.")])],
        )
        out = _coalesce_code_paragraphs([a, prose])
        assert out[0] is a
        assert len(out[0].lines) == 2


class TestLineIsMonoCode:
    """`_line_is_mono_code` recognises the mixed-font ``code // comment``
    shape (P3181R1) while rejecting prose, section refs and URLs."""

    @staticmethod
    def _mixed(code_mono, comment_prop):
        # Monospace code span (incl. the "//" marker) + proportional comment.
        return Line(spans=[
            Span(text=code_mono, monospace=True),
            Span(text=comment_prop, monospace=False),
        ])

    def test_code_with_trailing_proportional_comment(self):
        # P3181R1 c1: line. The "//" sits in the monospace code span.
        line = self._mixed("c1: b = new atomic<int>(0);    //",
                           " gets the same location as a.")
        assert _line_is_mono_code(line) is True

    def test_pure_monospace_line_is_code(self):
        line = Line(spans=[Span(text="a1: a->store(1, relaxed);",
                                monospace=True)])
        assert _line_is_mono_code(line) is True

    def test_prose_line_is_not_code(self):
        line = Line(spans=[Span(text="According to the standard, this is fine.",
                                monospace=False)])
        assert _line_is_mono_code(line) is False

    def test_comment_only_line_not_code(self):
        # p0533r9-class: a // section-ref line that starts with the marker.
        # No code before "//" -> must stay outside the fence.
        line = self._mixed("//[c.math.abs],", " absolute values")
        assert _line_is_mono_code(line) is False

    def test_url_after_code_not_code(self):
        # Opus guard: a monospace URL ("https://...") leading a prose line
        # must not be misread as code-with-comment (the "//" is a scheme sep).
        line = self._mixed("https://wg21.link/p1234r0", " has the rationale.")
        assert _line_is_mono_code(line) is False


class TestAbsorbMonoCodeOrphans:
    """`_absorb_mono_code_orphans` moves leading mixed-font code lines into a
    preceding CODE block (P3181R1 Defect 2), keeping text/lines in sync."""

    @staticmethod
    def _code(*texts, page_num=1):
        lines = [Line(spans=[Span(text=t, monospace=True)]) for t in texts]
        return Section(kind=SectionKind.CODE, text="\n".join(texts),
                       lines=lines, page_num=page_num, confidence=Confidence.MEDIUM)

    @staticmethod
    def _mixed_line(code_mono, comment_prop):
        return Line(spans=[
            Span(text=code_mono, monospace=True),
            Span(text=comment_prop, monospace=False),
        ])

    def test_absorbs_leading_code_lines_into_prev_code(self):
        code = self._code("Reallocating thread C:")
        para = Section(
            kind=SectionKind.PARAGRAPH,
            text="",
            page_num=1,
            lines=[
                self._mixed_line("c1: b = new atomic<int>(0);    //",
                                 " gets the same location as a."),
                self._mixed_line("c2: r2 = b->load(relaxed);     //",
                                 " Should not see the 1 from thread A."),
                Line(spans=[Span(text=" ")]),
                Line(spans=[Span(text="[res.on.objects]p2 states:",
                                 monospace=False)]),
            ],
        )
        out = _absorb_mono_code_orphans([code, para])
        # CODE grew by the two c1/c2 lines; prose paragraph survives separately.
        merged = out[0]
        assert merged.kind == SectionKind.CODE
        assert len(merged.lines) == 3
        assert [ln.text for ln in merged.lines] == merged.text.split("\n")
        rendered = "\n".join(ln.text for ln in merged.lines)
        assert "c1: b = new atomic<int>(0);" in rendered
        assert "c2: r2 = b->load(relaxed);" in rendered
        # The remaining prose stays a PARAGRAPH (the c1/c2 are gone from it).
        assert out[1].kind == SectionKind.PARAGRAPH
        assert "[res.on.objects]p2 states:" in out[1].text
        assert "c1:" not in out[1].text

    def test_comment_ref_paragraph_not_absorbed(self):
        # p0533r9-class section-ref comment after CODE must stay prose.
        code = self._code("long double cbrtl(long double x);")
        para = Section(
            kind=SectionKind.PARAGRAPH,
            text="",
            page_num=1,
            lines=[self._mixed_line("//[c.math.abs],", " absolute values")],
        )
        out = _absorb_mono_code_orphans([code, para])
        assert len(out) == 2
        assert out[1].kind == SectionKind.PARAGRAPH

    def test_different_page_not_absorbed(self):
        code = self._code("a1: a->store(1, relaxed);", page_num=1)
        para = Section(
            kind=SectionKind.PARAGRAPH,
            text="",
            page_num=2,
            lines=[self._mixed_line("c1: b = new atomic<int>(0);    //",
                                    " comment.")],
        )
        out = _absorb_mono_code_orphans([code, para])
        assert len(out) == 2
        assert out[0].kind == SectionKind.CODE
        assert len(out[0].lines) == 1


class TestClassifyCodeLine:
    """`_classify_code_line` discriminates prose from code by symbol density
    and alphabetic-word ratio, NOT font (P3181R1 / P4174R0 Defect 3)."""

    @staticmethod
    def _line(text, *, mono=False):
        return make_line([text], monospace=mono)

    def test_blank(self):
        assert _classify_code_line(self._line("   ")) == "blank"

    def test_slash_comment_is_code(self):
        # A wrapped non-mono comment line must not read as prose.
        assert _classify_code_line(
            self._line("// gets the same location as a")) == "code"

    def test_short_trailing_colon_is_label(self):
        assert _classify_code_line(self._line("Thread A:")) == "label"

    def test_long_trailing_colon_not_label(self):
        # Too many words to be a structural anchor; falls through to prose.
        assert _classify_code_line(
            self._line("the following produces an ambiguity error rather than:")
        ) == "narrative"

    def test_monospace_sentence_still_code(self):
        # Font alone never demotes; mono is always code here.
        assert _classify_code_line(
            self._line("a1: a.store(1, relaxed);", mono=True)) == "code"

    def test_proportional_code_is_code_by_symbols(self):
        # P4174R0: dense symbols in a non-mono font are still code.
        assert _classify_code_line(
            self._line("concept is_number = is_natural<T> || is_real<T>;")
        ) == "code"

    def test_prose_is_narrative(self):
        assert _classify_code_line(self._line(
            "This paper proposes a library approach of type lists, meaning that"
        )) == "narrative"

    def test_short_low_alpha_line_is_code(self):
        assert _classify_code_line(self._line("foo(1u);")) == "code"


class TestNarrativeContinuation:
    """`_is_narrative_continuation` rejoins a short wrapped prose tail to its
    narrative run while leaving genuine code tails as code."""

    @staticmethod
    def _line(text, *, mono=False):
        return make_line([text], monospace=mono)

    def test_prose_tail_absorbed(self):
        assert _is_narrative_continuation(self._line("slate concept.")) is True

    def test_code_tail_not_absorbed(self):
        # Brace/terminator core is not alphabetic, stays code.
        assert _is_narrative_continuation(self._line("});")) is False

    def test_monospace_tail_not_absorbed(self):
        assert _is_narrative_continuation(
            self._line("value;", mono=True)) is False

    def test_too_long_not_absorbed(self):
        assert _is_narrative_continuation(self._line(
            "this tail has far too many plain words to be a wrap")) is False


class TestTrimNarrativeFromCode:
    """`_trim_narrative_from_code` splits prose runs out of CODE sections
    (P3181R1) without fragmenting cohesive code blocks."""

    @staticmethod
    def _code(*texts, mono=False, page_num=1):
        lines = [make_line([t], monospace=mono) for t in texts]
        return Section(kind=SectionKind.CODE, text="\n".join(texts),
                       lines=lines, page_num=page_num,
                       confidence=Confidence.MEDIUM)

    def test_non_code_section_passthrough(self):
        para = make_section("just prose", kind=SectionKind.PARAGRAPH)
        out = _trim_narrative_from_code([para])
        assert out == [para]

    def test_pure_code_unchanged(self):
        code = self._code("int x = foo(1);", "return x + y;", mono=True)
        out = _trim_narrative_from_code([code])
        assert len(out) == 1
        assert out[0].kind == SectionKind.CODE

    def test_leading_prose_split_out(self):
        code = self._code(
            "This paper proposes a library approach of type lists, so that",
            "subsumption is not feasible for the general unrelated overloads.",
            "concept is_number = is_natural<T> || is_real<T>;",
            "foo(1u);",
        )
        out = _trim_narrative_from_code([code])
        assert [s.kind for s in out] == [
            SectionKind.PARAGRAPH, SectionKind.CODE]
        assert "library approach" in out[0].text
        assert "concept is_number" in out[1].text
        assert "library approach" not in out[1].text

    def test_cohesion_guard_keeps_single_interior_prose(self):
        # One wrapped narrative line surrounded by code must stay fenced.
        code = self._code(
            "template<typename T> concept is_natural = requires { value; };",
            "the compiler sees two unrelated container value instantiations here",
            "foo(1u); // now unambiguous is_natural subsumes is_number",
        )
        out = _trim_narrative_from_code([code])
        assert len(out) == 1
        assert out[0].kind == SectionKind.CODE

    def test_continuation_tail_rejoins_prose(self):
        code = self._code(
            "The approach this paper proposes lets the user create a blank",
            "slate concept.",
            "concept is_number = is_natural<T> || is_real<T>;",
            "foo(1u);",
        )
        out = _trim_narrative_from_code([code])
        assert out[0].kind == SectionKind.PARAGRAPH
        assert "slate concept." in out[0].text
        assert any(s.kind == SectionKind.CODE for s in out)

    def test_prose_connector_label_joins_following_prose(self):
        # A short trailing-colon prose connector between narrative lines must
        # NOT emit as a lone label-only code fence; it joins the prose that
        # it introduces (label inherits its forward neighbour).
        code = self._code(
            "This resolves the case for every well-formed input given.",
            "For example:",
            "the predicate then holds for all inputs in the domain.",
        )
        out = _trim_narrative_from_code([code])
        assert all(s.kind == SectionKind.PARAGRAPH for s in out)
        assert not any(
            s.kind == SectionKind.CODE and s.text.strip() == "For example:"
            for s in out)

    def test_blank_between_label_and_code_keeps_one_fence(self):
        # P3181R1 "Stronger semantics": a blank line between a pseudocode
        # label and its code must not orphan the label into its own fence.
        # The blank must take the label's (code) side, not skip past it to
        # the prose above.
        code = self._code(
            "We can roughly model the preceding example as described here now.",
            "",
            "Thread A:",
            "",
            "a1: a.store(1, relaxed);",
            "b1: r1 = a.load(relaxed);",
        )
        out = _trim_narrative_from_code([code])
        code_secs = [s for s in out if s.kind == SectionKind.CODE]
        assert len(code_secs) == 1
        assert "Thread A:" in code_secs[0].text
        assert "a1: a.store" in code_secs[0].text

    def test_pseudocode_label_stays_with_following_code(self):
        # The P3181R1 motivation: "Thread A:" introduces the code beneath it
        # and must stay fenced with it, not get pulled into preceding prose.
        code = self._code(
            "Consider the following concurrent execution across three threads.",
            "Thread A:",
            "a1: a.store(1, relaxed);",
            "a2: b.store(2, release);",
        )
        out = _trim_narrative_from_code([code])
        code_secs = [s for s in out if s.kind == SectionKind.CODE]
        assert len(code_secs) == 1
        assert "Thread A:" in code_secs[0].text
        assert "a1: a.store" in code_secs[0].text


class TestAbsorbTrailingLabelIntoCode:
    """`_absorb_trailing_label_into_code` moves a listing label that wrapped
    onto the tail of the preceding prose into the code block it heads
    (P3181R1 "Detailed example": "Thread A:"), without tearing a prose
    sentence whose last word merely ends in a colon."""

    @staticmethod
    def _para(*texts, page_num=1):
        lines = [make_line([t], monospace=False) for t in texts]
        return Section(kind=SectionKind.PARAGRAPH, text="\n".join(texts),
                       lines=lines, page_num=page_num,
                       confidence=Confidence.MEDIUM)

    @staticmethod
    def _code(*texts, page_num=1):
        lines = [make_line([t], monospace=True) for t in texts]
        return Section(kind=SectionKind.CODE, text="\n".join(texts),
                       lines=lines, page_num=page_num,
                       confidence=Confidence.MEDIUM)

    def test_series_label_moved_into_code(self):
        para = self._para(
            "Here we include a third thread C and discuss the issues.",
            "Thread A:")
        code = self._code("fence(release);", "Thread B:", "b1: r1 = load();")
        out = _absorb_trailing_label_into_code([para, code])
        assert out[0].kind == SectionKind.PARAGRAPH
        assert "Thread A:" not in out[0].text
        assert out[1].kind == SectionKind.CODE
        assert out[1].lines[0].text.strip() == "Thread A:"
        assert [ln.text for ln in out[1].lines] == out[1].text.split("\n")

    def test_prose_tail_colon_not_moved(self):
        # "object:" is the last word of a prose sentence; no code label shares
        # its first word, so it stays in the prose.
        para = self._para(
            "The literal operator returns an appropriately populated object:")
        code = self._code("namespace std {", "template <int N>", "};")
        out = _absorb_trailing_label_into_code([para, code])
        assert out[0].kind == SectionKind.PARAGRAPH
        assert out[0].text.strip().endswith("object:")
        assert len(out[1].lines) == 3

    def test_citation_label_not_moved(self):
        # An editing instruction carrying a '[cite]' is never moved, even when
        # a code label shares its first word.
        para = self._para(
            "We adjust the grammar here. Modify [dcl.contract.func] as follows:")
        code = self._code("Modify [x] as follows:", "precondition-specifier:")
        out = _absorb_trailing_label_into_code([para, code])
        assert out[0].text.strip().endswith("as follows:")
        assert out[1].lines[0].text.strip() == "Modify [x] as follows:"

    def test_unmatched_first_word_not_moved(self):
        # Label classifies, but its first word matches no code label.
        para = self._para("This introduces the listing. Sketch:")
        code = self._code("Thread B:", "b1: store();")
        out = _absorb_trailing_label_into_code([para, code])
        assert out[0].text.strip().endswith("Sketch:")
        assert len(out[1].lines) == 2

    def test_label_only_paragraph_not_moved(self):
        # No real prose before the label: nothing to detach it from.
        para = self._para("Thread A:")
        code = self._code("Thread B:", "b1: store();")
        out = _absorb_trailing_label_into_code([para, code])
        assert out[0].kind == SectionKind.PARAGRAPH
        assert out[0].text.strip() == "Thread A:"

    def test_different_page_not_moved(self):
        para = self._para("Prose leading to the listing. Thread A:", page_num=1)
        code = self._code("Thread B:", "b1: store();", page_num=2)
        out = _absorb_trailing_label_into_code([para, code])
        assert out[0].text.strip().endswith("Thread A:")

    def test_duplicate_head_label_not_moved(self):
        # Code already opens with the same label: moving would duplicate it.
        para = self._para("Prose leading to the listing. Thread A:")
        code = self._code("Thread A:", "a1: store();", "Thread B:")
        out = _absorb_trailing_label_into_code([para, code])
        assert out[0].text.strip().endswith("Thread A:")
        assert [ln.text for ln in out[1].lines].count("Thread A:") == 1

    def test_narrative_head_not_moved(self):
        # Code opens with a narrative line: the moved label would be peeled
        # straight back out by the trim pass, so do not move it.
        para = self._para("Prose leading to the listing. Thread A:")
        code = self._code(
            "this opening line is plainly wrapped prose, not any code at all",
            "Thread B:", "b1: store();")
        out = _absorb_trailing_label_into_code([para, code])
        assert out[0].text.strip().endswith("Thread A:")


class TestIsTailProse:
    """`_is_tail_prose` recognises a sentence-like prose tail while rejecting
    code statements, short lines, and monospace."""

    @staticmethod
    def _line(text, *, mono=False):
        return make_line([text], monospace=mono)

    def test_sentence_is_tail_prose(self):
        assert _is_tail_prose(self._line(
            "For now, let's treat c2 as a relaxed store.")) is True

    def test_citation_sentence_is_tail_prose(self):
        # The bracketed citation is stripped before measuring, so the
        # remaining sentence reads as prose despite the brackets.
        assert _is_tail_prose(self._line(
            "If c2 follows a1 in the order, by [intro.races]p16, this can't "
            "happen, since b1")) is True

    def test_code_terminator_not_tail_prose(self):
        assert _is_tail_prose(self._line("c3 = a.load(some, value);")) is False

    def test_open_brace_not_tail_prose(self):
        assert _is_tail_prose(
            self._line("if (cond) some other words here {")) is False

    def test_monospace_not_tail_prose(self):
        assert _is_tail_prose(self._line(
            "for now let us treat this", mono=True)) is False

    def test_short_line_not_tail_prose(self):
        assert _is_tail_prose(self._line("too short here")) is False

    def test_comment_not_tail_prose(self):
        assert _is_tail_prose(
            self._line("// a wrapped comment goes here now")) is False


class TestPeelTrailingProseFromCode:
    """`_peel_trailing_prose_from_code` splits a trailing prose run off the end
    of a CODE block (P3181R1 "Stronger semantics") while a ``;{}``/monospace
    hard stop protects interior and wrapped code."""

    @staticmethod
    def _code(*lines, page_num=1):
        # lines: (text, mono) tuples.
        ls = [make_line([t], monospace=m) for t, m in lines]
        return Section(kind=SectionKind.CODE,
                       text="\n".join(t for t, _ in lines),
                       lines=ls, page_num=page_num,
                       confidence=Confidence.MEDIUM)

    def test_trailing_sentence_peeled(self):
        code = self._code(
            ("a1: a.store(1, relaxed);", True),
            ("c3: a.load();", True),
            ("", False),
            ("For now, let's treat c2 as a relaxed store.", False),
            ("If c2 follows a1 in the modification order this cannot happen.",
             False),
        )
        out = _peel_trailing_prose_from_code([code])
        assert [s.kind for s in out] == [
            SectionKind.CODE, SectionKind.PARAGRAPH]
        assert "c3: a.load();" in out[0].text
        assert "For now" in out[1].text
        assert "If c2 follows" in out[1].text
        assert "For now" not in out[0].text
        assert [ln.text for ln in out[0].lines] == out[0].text.split("\n")

    def test_terminator_line_protects_wrapped_code(self):
        # A type-list line ending in ';' is a hard stop: nothing is peeled.
        code = self._code(
            ("using ints = type_list<unsigned char, unsigned short,", False),
            ("unsigned long, unsigned long long>;", False),
        )
        out = _peel_trailing_prose_from_code([code])
        assert len(out) == 1
        assert out[0].kind == SectionKind.CODE

    def test_pure_code_unchanged(self):
        code = self._code(
            ("int x = foo(1);", True),
            ("return x + y;", True),
        )
        out = _peel_trailing_prose_from_code([code])
        assert len(out) == 1
        assert out[0].kind == SectionKind.CODE

    def test_non_code_section_passthrough(self):
        para = make_section("just prose here", kind=SectionKind.PARAGRAPH)
        out = _peel_trailing_prose_from_code([para])
        assert out == [para]


class TestWeakHeadingQualifies:
    """A LOW-confidence heading candidate must also *look* like a heading (#302).

    ``heading_confidence`` returns LOW when exactly one weak signal fired, so
    the text has to carry the claim by itself. These cases pin the three tells.
    """

    def test_short_label_qualifies(self):
        assert _weak_heading_qualifies("Rounding Mode", "", 1, False, False)

    def test_dotted_number_only_qualifies(self):
        """P4182R0's real subsection headings are number-only at body weight."""
        assert _weak_heading_qualifies(
            "3.1 Platform schema", "3.1", None, False, False)

    def test_question_heading_qualifies(self):
        """A trailing "?" is heading style in WG21 papers, not prose."""
        assert _weak_heading_qualifies(
            "Why not represent a proposed API as a C++20 range?", "",
            1, False, False)

    def test_trailing_dot_number_is_stripped_before_the_prose_test(self):
        """"2. History" must not read as an interior sentence boundary."""
        assert _weak_heading_qualifies(
            "2. History/Changes from Previous Release", "", 1, False, False)

    def test_bare_number_line_is_exempt(self):
        """A number alone has no text to judge; the orphan merge pairs it."""
        assert _weak_heading_qualifies("I.", "", 1, False, False)
        assert _weak_heading_qualifies("3.35", "", 1, False, False)

    def test_dotless_number_without_typography_is_paragraph_numbering(self):
        """P3556R0 quotes standardese whose paragraph numbers are bare."""
        assert not _weak_heading_qualifies(
            "3 A preprocessing directive of the form", "3",
            None, False, False)

    def test_dotless_number_with_font_support_still_qualifies(self):
        """The tell needs the *absence* of every typographic signal."""
        assert _weak_heading_qualifies(
            "3 Introduction", "3", 1, False, False)

    def test_sentence_opening_on_a_roman_numeral_is_rejected(self):
        """P2040R0: "I think ..." matches SECTION_NUM_RE as roman numeral I."""
        assert not _weak_heading_qualifies(
            "I think this general approach to the syntax at call site is best",
            "I", None, False, False)

    def test_terminal_period_is_prose(self):
        assert not _weak_heading_qualifies(
            "Your costs and results may vary.", "", 1, False, False)

    def test_interior_sentence_boundary_is_prose(self):
        assert not _weak_heading_qualifies(
            "Performance varies by use and other factors. Learn more on the",
            "", 1, False, False)

    def test_length_alone_is_not_a_tell(self):
        """The call site's _HEADING_MAX_WORDS cap owns length; this gate does not."""
        assert _weak_heading_qualifies(
            "Performance results are based on testing as of dates shown in "
            "configurations and", "", 1, False, False)


class TestFontOnlyFooterProseNotAHeading:
    """An Intel-style legal footer one point above body size is not a heading.

    Canonical case: P1068R11's "Notices & Disclaimers" page sets its
    disclaimer at 12pt against an 11pt body, so the font-size signal alone
    ranks every line as a heading and the outline gains a run of H3s (#302).
    """

    _FOOTER = [
        "Performance varies by use, configuration and other factors. "
        "Learn more on the",
        "No product or component can be absolutely secure.",
        "Your costs and results may vary.",
        "Intel technologies may require enabled hardware, software or "
        "service activation.",
    ]

    def test_footer_lines_stay_paragraphs(self):
        body_fill = [_mk_section("ordinary body " + ("x" * 80), font_size=11.0)
                     for _ in range(10)]
        footer = [_mk_section(t, font_size=12.0) for t in self._FOOTER]
        _, result, _ = structure_sections(body_fill + footer, has_title=True)
        promoted = [s.text for s in result
                    if s.kind == SectionKind.HEADING
                    and any(t in s.text for t in self._FOOTER)]
        assert not promoted, (
            f"footer prose promoted to headings on the font signal alone: "
            f"{promoted}"
        )

    def test_footer_text_survives(self):
        """Rejecting the heading must not drop the text."""
        body_fill = [_mk_section("ordinary body " + ("x" * 80), font_size=11.0)
                     for _ in range(10)]
        footer = [_mk_section(t, font_size=12.0) for t in self._FOOTER]
        _, result, _ = structure_sections(body_fill + footer, has_title=True)
        joined = "\n".join(s.text for s in result)
        for t in self._FOOTER:
            assert t in joined
