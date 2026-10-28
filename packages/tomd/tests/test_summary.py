# Copyright (c) 2026 Rob Beeston (rob@cppalliance.org)
# Distributed under the Boost Software License, Version 1.0.
# https://www.boost.org/LICENSE_1_0.txt

"""Paper summary, removed-content records and the table prompt elements."""

import json
from pathlib import Path

import pytest

from tomd.lib.pdf import run_pipeline
from tomd.lib.pdf.emit import emit_prompts
from tomd.lib.pdf.summary import build, generator, header_comment, prompt_elements
from tomd.lib.pdf.types import Confidence, Section, SectionKind, Span

_GOLDEN = Path(__file__).resolve().parent / "fixtures" / "golden"
_WITH_TABLE = _GOLDEN / "p4012r0-page-6.pdf"


def _table(conf=Confidence.UNCERTAIN, page=2):
    sec = Section(kind=SectionKind.TABLE, text="a | b", confidence=conf, page_num=page,
                  columns=[[[Span("a")], [Span("b")]], [[Span("1")], [Span("2")]]])
    sec.metadata["level"] = {"level": 2}
    return sec


def test_generator_family_from_producer():
    assert generator({"producer": "pdfTeX-1.40.25"}) == "LaTeX"
    assert generator({"creator": "Microsoft Word"}) == "Word"
    assert generator({}) == "other"


def test_build_counts_tables_marks_and_removed():
    mark = Section(kind=SectionKind.PARAGRAPH, text="x", page_num=4,
                   metadata={"possible_table": "demoted"})
    s = build([_table(), _table(Confidence.HIGH, page=0), mark],
              [("headers", "2 repeating header/footer pattern(s) removed", "")], [], "LaTeX")
    assert s["tables"]["total"] == 2 and s["tables"]["trusted"] == 1 and s["tables"]["flagged"] == 1
    assert s["tables"]["flagged_pages"] == [3] and s["tables"]["levels"] == {"L2": 2}
    assert s["marks"] == 1 and s["marked_pages"] == [5]
    assert s["removed"] == [{"what": "headers", "why": "2 repeating header/footer pattern(s) removed"}]
    assert s["confidence"] is None
    json.dumps(s)                                          # serializable without default=str


def test_header_comment_and_prompt_elements():
    s = build([_table()], [("hidden", "text under 1 covered region(s) on 1 page(s) removed", "")],
              [{"stage": "detect_tables", "page": None, "type": "ValueError", "message": "x",
                "kind": "data", "table": False}], "other")
    assert header_comment(s) == ("<!-- tomd:summary tables=1 trusted=0 flagged=1 likely=0 marked=0 "
                                 "confidence=n/a unfamiliarity=0.40 -->")
    removed, errors, summary = prompt_elements(s, [("hidden", "text removed", "")], s["reader_errors"])
    assert "- hidden: text removed" in removed
    assert "- detect_tables: ValueError: x" in errors
    assert summary.startswith("Summary of the tables")


def test_flagged_table_gets_a_prompt_element():
    prompts = emit_prompts([_table()])
    assert prompts and "This is a table no second kind of evidence confirmed" in prompts[0]
    assert emit_prompts([_table(Confidence.HIGH)]) is None


def test_pipeline_returns_summary_comment_and_prompts():
    if not _WITH_TABLE.is_file():
        pytest.skip(f"missing PDF fixture: {_WITH_TABLE.name}")
    r = run_pipeline(_WITH_TABLE)
    assert r.summary["tables"]["total"] >= 1
    body = r.md.split("\n---\n", 1)[1]
    assert body.lstrip("\n").startswith("<!-- tomd:summary ")
    assert any(p.startswith("Summary of the tables") for p in r.prompts)
    json.dumps(r.summary)
