#
# Copyright (c) 2026 Rob Beeston (rob@cppalliance.org)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
#

"""Graded table levels (L0-L5) and cell markers, from the table's own evidence.

HIGH / UNCERTAIN says only whether to trust a table; a reader of the output
(an agent evaluating the paper) also needs to know how a flagged table may be
wrong, so it can tell a nearly-right reading from a misattributed one:

  L0 trusted               HIGH: independent sources agree
  L1 likely                flagged, but the words fit the drawn cells evenly
  L2 minor                 flagged on one source only; every check on content passed
  L3 structure uncertain   readers disagree, the fit or layout check failed, relational
                           violations, the extent is open (a table may continue)
  L4 content at risk       text duplicated or misattributed (conservation surplus),
                           damaged text, cells read out of order, a reader error, repaired
     L4 incomplete         text of the area missing from the cells, nothing duplicated or
                           out of order: content missing, what is there is not contradicted
  L5 mark only             a possible table that was not produced (a mark, not a table)

The most severe level that applies is the table's level. Cell markers list the
cells where the table's alternative readings (same shape) disagree. Levels are
metadata: the table's content is unchanged.
"""

import re

from .types import Confidence, Section

NAMES = {0: "trusted", 1: "likely", 2: "minor", 3: "structure-uncertain", 4: "content-at-risk", 5: "mark-only"}
# First level shown in the Markdown: L0 and L1 carry no level comment.
SHOWN_FROM = 2
_CONS = re.compile(r"(\d+) characters on the page are not in any cell and (\d+) appear")
_WHY_CHARS = 300           # longest reason text in a level comment
_CELLS_SHOWN = 40          # most cell markers in a level comment

_L4 = {"damaged": "damaged text", "glyph-order": "cells read out of order", "reader error": "a reader error",
       "repaired": "repaired", "llm-repaired": "repaired by the language model"}
_L3 = {"disagree": "readers disagree", "cross-reader": "joined from two readers' pieces",
       "extent": "the table may continue on the adjacent page",
       "rule-check": "the reading fails the rule checks"}
# Agreement found, but the page checks could not run: shown as minor (L2).
_L2 = {"unverified": "not checked against its page (a rotated page)",
       "paperflow-reader": "agreed with paperflow's own reader only; that agreement is not yet measured",
       "rendering": "readings agree; written by a renderer the agreement does not check"}


def _rows(md: str) -> list[list[str]]:
    rows = []
    for ln in (md or "").splitlines():
        ln = ln.strip()
        if ln.startswith("|") and not set(ln.replace("|", "").strip()) <= set("-: "):
            rows.append([c.strip() for c in ln.strip("|").split("|")])
    return rows


def cell_markers(sec: Section) -> list[tuple[int, int]]:
    """Cells where an alternative reading of the same shape disagrees with the table."""
    versions = sec.metadata.get("table_versions") or []
    if len(versions) < 2:
        return []
    primary = _rows(versions[0][1])
    out = set()
    for _, md in versions[1:]:
        alt = _rows(md)
        if len(alt) != len(primary) or any(len(a) != len(b) for a, b in zip(alt, primary)):
            continue
        for r, (a, b) in enumerate(zip(primary, alt)):
            for c, (x, y) in enumerate(zip(a, b)):
                if " ".join(x.split()) != " ".join(y.split()):
                    out.add((r, c))
    return sorted(out)


def assign(sec: Section) -> dict:
    """{"level", "name", "why", "incomplete", "cells"} for a table section."""
    m = sec.metadata
    reasons = set(m.get("uncertain_reasons") or [])
    why4, why3 = [], []
    note = m.get("table_note") or ""
    lost = extra = 0
    g = _CONS.search(note)
    if g:
        lost, extra = int(g.group(1)), int(g.group(2))
    if extra:
        why4.append(f"{extra} characters in cells more often than on the page (duplicated or misattributed)")
    why4 += [v for k, v in _L4.items() if k in reasons]
    if str(m.get("verified", "ok")).startswith("ok after"):
        why4.append("repaired: " + str(m["verified"])[len("ok after "):])
    why3 += [v for k, v in _L3.items() if k in reasons]
    v = m.get("verified")
    if v and v != "ok" and not str(v).startswith("ok"):
        why3.append(f"layout check: {v}")
    rel = (m.get("relations") or {}).get("by_dimension") or {}
    if sum(rel.values()):
        why3.append("relational violations: " + ", ".join(f"{k} {n}" for k, n in sorted(rel.items()) if n))
    incomplete = bool(lost) and not why4
    if incomplete:
        why4.append(f"{lost} characters of the area are not in any cell (incomplete)")
    if sec.confidence == Confidence.HIGH:
        level, why = 0, ["independent sources agree"]
    elif why4:
        level, why = 4, why4
    elif why3:
        level, why = 3, why3
    elif m.get("likely"):
        level, why = 1, ["the words fit the drawn cells evenly"]
    else:
        level, why = 2, ([v for k, v in _L2.items() if k in reasons]
                         or ["one source" if "single-source" in reasons else "flagged"])
    cells = cell_markers(sec) if level >= SHOWN_FROM else []
    return {"level": level, "name": NAMES[level], "why": why, "incomplete": incomplete and level == 4,
            "cells": [list(c) for c in cells]}


def comment(info: dict) -> str:
    """The ``tomd:level`` comment written above a flagged table."""
    name = info["name"] + (" (incomplete)" if info["incomplete"] else "")
    cells = (" cells=" + ",".join(f"r{r + 1}c{c + 1}" for r, c in info["cells"][:_CELLS_SHOWN])
             if info["cells"] else "")
    return f"<!-- tomd:level L{info['level']} {name}: {'; '.join(info['why'])[:_WHY_CHARS]}{cells} -->"
