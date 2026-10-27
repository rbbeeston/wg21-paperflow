#
# Copyright (c) 2026 Rob Beeston (rob@cppalliance.org)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
#

"""The evidence record: what every table reader saw, nominated and rejected, and why.

A reader that looks at an area and decides "not a table" records the area, the
rule that decided, and the kind of information the rule used. Later steps (the
region scan, the prompts, the paper summary) read the record instead of each
reader's private verdict, so nothing is dropped without a trace.

One record per conversion, held by the run's context (``runctx.RunContext``).

Information types: "words" (text positions), "paths" (drawn lines, boxes,
shading), "tree" (tagged structure), "meaning" (content kinds, poll
vocabulary, code similarity), "document" (captions, counts, generator).
"""

from dataclasses import dataclass, field

Box = tuple[float, float, float, float]

# Exceptions that mean the code is wrong, not the PDF: the release gate fails on any of them.
CODE_ERRORS = (NameError, AttributeError, TypeError, ImportError, AssertionError, SyntaxError)


@dataclass
class Entry:
    kind: str                  # "nominated" | "excluded" | "feature"
    scan: str                  # which reader or check wrote it
    page: int
    bbox: Box
    rule: str                  # the rule that decided (or the feature's name)
    info: str                  # information type the rule used
    value: object = None       # a feature's value, or extra detail
    observed: bool = True      # observed on the page, or inferred


@dataclass
class Record:
    entries: list[Entry] = field(default_factory=list)
    # every candidate reading: (source, page, bbox, rows of cell text)
    readings: list[tuple] = field(default_factory=list)
    # readers, checks and specialists that raised: never swallowed silently
    errors: list[dict] = field(default_factory=list)

    def nominate(self, scan: str, page: int, bbox: Box, cue: str, info: str, value=None) -> None:
        self.entries.append(Entry("nominated", scan, page, tuple(bbox), cue, info, value))

    def exclude(self, scan: str, page: int, bbox: Box, rule: str, info: str, value=None) -> None:
        self.entries.append(Entry("excluded", scan, page, tuple(bbox), rule, info, value))

    def feature(self, scan: str, page: int, bbox: Box, name: str, info: str, value,
                observed: bool = True) -> None:
        self.entries.append(Entry("feature", scan, page, tuple(bbox), name, info, value, observed))

    def on_page(self, page: int, kind: str | None = None) -> list[Entry]:
        return [e for e in self.entries if e.page == page and (kind is None or e.kind == kind)]
