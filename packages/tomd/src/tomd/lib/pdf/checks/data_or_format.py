#
# Copyright (c) 2026 Rob Beeston (rob@cppalliance.org)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
#

"""Meaning: tabular data or formatting? In data a cell's meaning depends on its
row and its column (look a value up by row key and column header); in
formatting the grid only places content (front matter, label: value
entries, callouts, slide layouts). Features follow the web-table literature
(cell length and type consistency down columns, rows x columns, single
record, label: value pattern, large prose cells, borders), measured on the
existing keys before use (train_dvf.py: cross-validated AUC 0.99)."""
import re
import statistics

from ..dvf_model import MODEL
from ..scan_model import likelihood
from .base import Check

_LABEL = re.compile(r"^[A-Za-z][\w ./()#-]{0,40}:$")


def features(rows, f) -> dict | None:
    if not rows:
        return None
    nr, nc = len(rows), max(len(r) for r in rows)
    cells = [c.strip() for r in rows for c in r if c.strip()]
    words = [len(c.split()) for c in cells] or [0]
    x = {"d_rows": float(nr), "d_cols": float(nc), "d_single_record": 1.0 if nr <= 2 else 0.0,
         "d_label_colon": sum(bool(_LABEL.match(r[0].strip())) for r in rows if r) / nr,
         "d_mean_words": statistics.mean(words), "d_large_cells": sum(w >= 25 for w in words) / len(words)}
    disp = []
    for c in range(nc):
        col = [len(r[c].split()) for r in rows[1:] if c < len(r) and r[c].strip()]
        if len(col) >= 2:
            disp.append(statistics.pstdev(col) / max(statistics.mean(col), 1))
    x["d_len_dispersion"] = statistics.mean(disp) if disp else -1.0
    for k in ("c_items_per_cell", "c_fragments", "c_header_vs_body", "c_min_coherence", "c_first_col_keys",
              "hrules", "vrules", "row_fills", "enclosing_fill", "mono_share", "page0", "width_share", "height"):
        x[k] = float(f.get(k, 0.0))
    return x


def likelihood_data(rows, f) -> float | None:
    """P(tabular data) for a reading, or None without one."""
    x = features(rows, f)
    return None if x is None else likelihood(x, MODEL)[0]


def run(ctx) -> dict:
    return {}       # a second output of the scan (scan.run_scan), not a table-likelihood feature


CHECK = Check("data_or_format", ("region", "content"), "meaning", 0, False, run)
