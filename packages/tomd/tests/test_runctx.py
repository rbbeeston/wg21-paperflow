# Copyright (c) 2026 Rob Beeston (rob@cppalliance.org)
# Distributed under the Boost Software License, Version 1.0.
# https://www.boost.org/LICENSE_1_0.txt

"""Per-run context: reader errors are recorded, runs are isolated, output is seed-stable."""

import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from tomd.lib.pdf import pipeline as pipeline_mod
from tomd.lib.pdf import run_pipeline
from tomd.lib.pdf.runctx import RunContext, current, run_scope
from tomd.lib.pdf.types import Section, SectionKind

_GOLDEN = Path(__file__).resolve().parent / "fixtures" / "golden"
# Two small golden papers: one with tables, one without.
_SMALL = (_GOLDEN / "p4012r0-page-6.pdf", _GOLDEN / "p4012r0-page-10.pdf")


def test_reader_error_is_recorded_with_kind_and_table_mark():
    ctx = RunContext()
    sec = Section(kind=SectionKind.TABLE, text="")
    ctx.reader_error("ruled", 2, TypeError("bad arg"), table=sec)
    ctx.reader_error("tagged", None, ValueError("broken tree"))
    assert [(e["stage"], e["page"], e["kind"], e["table"]) for e in ctx.record.errors] == [
        ("ruled", 2, "code", True), ("tagged", None, "data", False)]
    assert sec.metadata["reader_errors"] == ["ruled"]


def test_strict_context_reraises():
    with pytest.raises(ValueError):
        RunContext(strict=True).reader_error("ruled", 0, ValueError("x"))


def test_scope_is_fresh_and_restored():
    outside = current()
    with run_scope() as ctx:
        assert current() is ctx
        ctx.record.errors.append({"stage": "x"})
        with run_scope() as inner:
            assert current() is inner and not inner.record.errors
        assert current() is ctx
    assert current() is not ctx and current() is not outside


def test_threads_see_only_their_own_context():
    seen = {}
    barrier = threading.Barrier(2)

    def run(name):
        with run_scope() as ctx:
            ctx.record.errors.append({"stage": name})
            barrier.wait()
            seen[name] = [e["stage"] for e in current().record.errors]

    threads = [threading.Thread(target=run, args=(n,)) for n in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert seen == {"a": ["a"], "b": ["b"]}


def test_failing_table_reader_is_recorded_not_fatal(monkeypatch):
    pdf = _SMALL[0]
    if not pdf.is_file():
        pytest.skip(f"missing PDF fixture: {pdf.name}")

    def broken(*args, **kwargs):
        raise RuntimeError("reader broke")

    monkeypatch.setattr(pipeline_mod, "detect_tables", broken)
    result = run_pipeline(pdf)
    assert not result.skipped and result.md.strip()
    assert [(e["stage"], e["type"], e["kind"]) for e in result.reader_errors] == [
        ("detect_tables", "RuntimeError", "data")]
    # other readers may still find tables; none comes from the reader that broke
    assert not any(s.kind == SectionKind.TABLE and s.metadata.get("table_source") == "tomd"
                   for s in result.sections)


def test_clean_run_has_no_reader_errors():
    pdf = _SMALL[0]
    if not pdf.is_file():
        pytest.skip(f"missing PDF fixture: {pdf.name}")
    assert run_pipeline(pdf).reader_errors == []


def test_two_threads_match_serial_output():
    if not all(p.is_file() for p in _SMALL):
        pytest.skip("missing PDF fixtures")
    serial = [run_pipeline(p).md for p in _SMALL]
    results = [None, None]

    def run(i):
        results[i] = run_pipeline(_SMALL[i]).md

    threads = [threading.Thread(target=run, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results == serial


_HASH_SCRIPT = (
    "import hashlib, json, sys\n"
    "from tomd.lib.pdf import run_pipeline\n"
    "out = [hashlib.sha256((r.md + json.dumps(r.prompts)).encode()).hexdigest()\n"
    "       for r in (run_pipeline(p) for p in sys.argv[1:])]\n"
    "print(json.dumps(out))\n"
)


def test_output_does_not_depend_on_the_hash_seed():
    if not all(p.is_file() for p in _SMALL):
        pytest.skip("missing PDF fixtures")
    runs = []
    for seed in ("0", "12345"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        out = subprocess.run([sys.executable, "-c", _HASH_SCRIPT, *map(str, _SMALL)],
                             env=env, capture_output=True, text=True, check=True)
        runs.append(out.stdout.strip().splitlines()[-1])
    assert runs[0] == runs[1]
