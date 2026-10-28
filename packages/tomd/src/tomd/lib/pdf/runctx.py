#
# Copyright (c) 2026 Rob Beeston (rob@cppalliance.org)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
#

"""Per-run context: the state one ``run_pipeline`` call owns.

Table readers and checks record what they saw (the evidence record) and what
raised (reader errors). That state belongs to one conversion, so it lives in a
``RunContext`` opened by ``run_pipeline`` with ``run_scope()``, never in module
globals: two papers converted on two threads each see only their own context
(``contextvars`` gives every thread its own value).
"""

import contextlib
import contextvars
import logging
from collections import Counter
from dataclasses import dataclass, field

from .evidence import CODE_ERRORS, Record

_log = logging.getLogger(__name__)

# Longest exception message kept in a reader-error entry.
ERROR_MESSAGE_LIMIT = 300


@dataclass
class RunContext:
    record: Record = field(default_factory=Record)
    # content removed on purpose: (what, why, an example); listed in the summary and prompts
    discards: list[tuple[str, str, str]] = field(default_factory=list)
    # drawn grids the rule reader excluded (failed checks): rejected readings for the marks
    excluded_grids: list = field(default_factory=list)
    # the paper's running-text words (lower case), counted: a line-end hyphen in a
    # table cell is decided by how the paper itself writes the word (emit.py)
    lexicon: Counter = field(default_factory=Counter)
    # does this document's maker hyphenate words at line ends (docmeasure.hyphenates)?
    hyphenates: bool = True
    # text the page does not show, per page (visibility.py): classified once, removed
    # from every copy of the document a reader opens
    hidden: dict[int, list[dict]] = field(default_factory=dict)
    # re-raise reader errors instead of recording them (tests of a reader's own failures)
    strict: bool = False

    def reader_error(self, stage: str, page: int | None, exc: BaseException, table=None) -> None:
        """Record a reader, check or specialist that raised: stage, page (None for the
        whole paper), exception type and message, and whether it is a code error. A table
        the failure touched carries the stage in ``metadata["reader_errors"]``, so the
        mark survives the section being copied."""
        kind = "code" if isinstance(exc, CODE_ERRORS) else "data"
        self.record.errors.append({"stage": stage, "page": page, "type": type(exc).__name__,
                                   "message": str(exc)[:ERROR_MESSAGE_LIMIT], "kind": kind,
                                   "table": table is not None})
        if table is not None:
            table.metadata.setdefault("reader_errors", []).append(stage)
        _log.warning("Reader error in %s%s: %s: %s", stage,
                     "" if page is None else f" (page {page + 1})", type(exc).__name__, exc)
        if self.strict:
            raise exc


_CURRENT: contextvars.ContextVar[RunContext | None] = contextvars.ContextVar(
    "tomd_run_context", default=None)


@contextlib.contextmanager
def run_scope():
    """Open a fresh context for one conversion; restore the previous one on exit."""
    ctx = RunContext()
    token = _CURRENT.set(ctx)
    try:
        yield ctx
    finally:
        _CURRENT.reset(token)


def current() -> RunContext:
    """The active run's context. Outside ``run_pipeline`` (a reader called directly,
    as in unit tests) a detached context is returned, so recording never fails."""
    ctx = _CURRENT.get()
    return ctx if ctx is not None else RunContext()
