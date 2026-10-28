#
# Copyright (c) 2026 Rob Beeston (rob@cppalliance.org)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
#

"""Stage 2 (relationship plan): confidence per dimension.

A table can be right in some respects and wrong in others. Each dimension
gets a level from what tomd recorded about the table:

  rows     row boundaries        weak: a drawn rule with text on both sides
                                 inside one row, one baseline in several
                                 rows, stacked or overlapping rows
  columns  column boundaries     weak: a recurring gutter inside one cell,
                                 a hidden or overlapping column
  header   the header row        weak: an aligned row just above the table
                                 may be its header
  cells    membership, extent    weak: a page word in no cell or in two,
                                 overlapping cells, a table that may
                                 continue on the next page, too small

strong: at least two independent information types back the dimension
(words, paths, tree) and nothing marks it weak; ok otherwise.

Measured on the answer keys (dims_measure.py): each signal goes to the
dimension it describes, and signals that fire mostly on correct tables
(cell order, conservation) are left out. Switching a flagged table to
another reading by its weak dimension fixed none and broke 15 on the
tuning sets, so the levels are diagnosis: metadata, and the prompts name
the weak dimension so a reader checks that first. They never change a
table's confidence.
"""
_PROPS = {"rows": "rows", "columns": "cols", "cells": "members"}

_WEAK = {
    "rows": {"rel": ("rows merged", "row split"), "verify": ("stacked-rows", "rows-overlap")},
    "columns": {"rel": ("column merged", "column split"), "verify": ("hidden-column", "columns-overlap")},
    "header": {"rel": (), "verify": ("header-above",)},
    "cells": {"rel": ("word outside every cell", "word in two cells"),
              "verify": ("word-outside-cells", "overlapping-cells", "too-small")},
}


def dimensions(meta: dict) -> dict:
    """{dimension: {"level": strong|ok|weak, "why": [...]}} from a table's metadata."""
    kinds = ((meta.get("relations") or {}).get("kinds")) or []
    verified = str(meta.get("verified") or "ok").split(": ")[-1]
    witness = meta.get("witness") or {}
    props = witness.get("props") or {}
    out = {}
    for dim, sig in _WEAK.items():
        why = [k for k in kinds if k.startswith(sig["rel"])] if sig["rel"] else []
        if verified in sig["verify"]:
            why.append("verify: " + verified)
        if dim == "cells" and witness.get("extent") == "open":
            why.append("may continue on the next page")
        if why:
            out[dim] = {"level": "weak", "why": sorted(set(why))}
        elif dim in _PROPS and len(props.get(_PROPS[dim], [])) >= 2:
            out[dim] = {"level": "strong", "why": props[_PROPS[dim]]}
        elif dim == "header" and "tree" in props.get("rows", []):
            out[dim] = {"level": "strong", "why": ["tree"]}
        else:
            out[dim] = {"level": "ok", "why": []}
    return out


def weak_note(dims: dict) -> str:
    """One line for the prompts: the weak dimensions and why, or ""."""
    weak = [f"{d} ({'; '.join(v['why'])})" for d, v in dims.items() if v["level"] == "weak"]
    return ("Check first: " + ", ".join(weak) + ".") if weak else ""
