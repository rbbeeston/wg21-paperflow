# Copyright (c) 2026 Rob Beeston (rob@cppalliance.org)
# Distributed under the Boost Software License, Version 1.0.
# https://www.boost.org/LICENSE_1_0.txt

"""Table levels, table marks and marker renumbering."""

from tomd.lib.pdf.emit import emit_markdown, renumber_uncertain_markers
from tomd.lib.pdf.levels import assign, comment
from tomd.lib.pdf.types import Confidence, Section, SectionKind, Span


def _table(confidence=Confidence.UNCERTAIN, **meta):
    sec = Section(kind=SectionKind.TABLE, text="a | b", confidence=confidence,
                  columns=[[[Span("a")], [Span("b")]], [[Span("1")], [Span("2")]]])
    sec.metadata.update(meta)
    return sec


def test_trusted_table_is_level_0():
    assert assign(_table(Confidence.HIGH))["level"] == 0


def test_single_source_table_is_level_2():
    info = assign(_table(uncertain_reasons=["single-source"]))
    assert (info["level"], info["why"]) == (2, ["one source"])
    assert comment(info) == "<!-- tomd:level L2 minor: one source -->"


def test_duplicated_text_is_level_4_and_missing_text_incomplete():
    dup = assign(_table(uncertain_reasons=["single-source", "conservation"], table_note=(
        "Text conservation failed: 0 characters on the page are not in any cell and 3 appear")))
    assert dup["level"] == 4 and not dup["incomplete"]
    lost = assign(_table(uncertain_reasons=["single-source", "conservation"], table_note=(
        "Text conservation failed: 5 characters on the page are not in any cell and 0 appear")))
    assert lost["level"] == 4 and lost["incomplete"]
    assert comment(lost).startswith("<!-- tomd:level L4 content-at-risk (incomplete): 5 characters")


def test_readers_disagreeing_is_level_3():
    assert assign(_table(uncertain_reasons=["disagree"]))["level"] == 3


def test_flagged_table_gets_level_comment_and_marker_touching_it():
    sec = _table(uncertain_reasons=["single-source"])
    sec.metadata["level"] = assign(sec)
    md = emit_markdown({}, [sec])
    lines = md.split("\n")
    i = lines.index("<!-- tomd:level L2 minor: one source -->")
    assert lines[i + 2].startswith("<!-- tomd:uncertain:L")
    start = int(lines[i + 2].split(":L")[1].split("-")[0])
    assert lines[start - 1].startswith("| a | b |")


def test_trusted_table_is_not_marked():
    sec = _table(Confidence.HIGH)
    sec.metadata["level"] = assign(sec)
    assert "tomd:" not in emit_markdown({}, [sec])


def test_possible_table_mark_has_no_level_comment():
    sec = Section(kind=SectionKind.PARAGRAPH, text="1 Intro ........ 3",
                  metadata={"possible_table": "a table with dot leaders, demoted as contents"})
    md = emit_markdown({}, [sec])
    assert "tomd:uncertain:L" in md and "tomd:level" not in md


def test_markers_are_renumbered_from_their_position():
    md = "x\n\n<!-- tomd:uncertain:L9-L10 -->\n\none\ntwo\n"
    assert renumber_uncertain_markers(md) == "x\n\n<!-- tomd:uncertain:L5-L6 -->\n\none\ntwo\n"
