#
# Copyright (c) 2026 Rob Beeston (rob@cppalliance.org)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
#

"""Stage-2 gate: is a selected table really a table, and how is it built?

Every selected table is described by cheap geometric and font features of
its area (rules drawn, shaded bands, column-split text rows, monospace and
digit shares, which table readers found it, the generator) and passed to
two small decision trees learned from the answer keys (classify_trees.py;
the keys were built blind by AI agents from page images and the text
layer, under conventions decided by a person):

  - table or not: "table", "front-matter" or "not-a-table";
  - layout class: poll, grid, rule-per-row, booktabs, boxed, tagged, ...

The gate is sure only when the tree's leaf is pure enough (_TREE_SURE).
Before the trees, each table is checked against its page: its layout put
back onto the page's words (validate.verify_layout, with a targeted re-read
when that fails), rows no vertical rule crosses (fullwidth), its words
against the drawn cells (fit: "likely"), and every contradiction between
the table and the page by dimension (relations, plausibility, dimensions).

The gate never removes text. It can make a HIGH table UNCERTAIN (the
classifiers do not think it is a table, or images fill its cells), and it
can make a single-source poll HIGH when the gate is sure it is a table,
its layout class is poll, and the poll's own check passed
(select.class_check), and nothing else made it uncertain.
"""

import logging
import re
from collections import Counter

import fitz

from .checks.plausible import plausibility
from .classify_trees import LAYOUT_TREE, TABLE_TREE
from .dimensions import dimensions
from .fit import fit as _fit, fit_rows as _fit_rows
from .fullwidth import apply as _full_width
from .pagecache import words_in
from .relations import record_for
from .ruled import page_hrules
from .runctx import current
from .summary import generator
from tomd.domain.elements import Confidence
from .types import Section, SectionKind
from .repair import place_stray_words
from .validate import _newline_span, _with_columns, escalate, verify_layout, verify_pieces

_log = logging.getLogger(__name__)

_MONO = ("mono", "courier", "code", "tt1", "cmtt", "lmmono", "consol", "menlo")
_POLL = re.compile(r"^(SF\s+F\s+N\s+A\s+SA|F\s+N\s+A)$")
_ZW = dict.fromkeys(map(ord, "​‌‍﻿‪‫‬‭‮"), None)
_GAP = 10.0
_TREE_SURE = 0.9
_HEADER_BAND = 22.0      # points above a table searched for a lost header row
GENERATORS = ["LaTeX", "Word", "Google Docs", "ReportLab", "pypdf", "macOS", "Typst", "Chrome/Skia"]
SOURCES = ["tags", "poll", "grid", "rules", "tomd", "text"]
FLAGS = ["ragged-columns", "split-code", "numbered-list", "bullet-list", "toc-like",
         "reference-list", "single-cell-rows", "code-comment-column", "continuation-fragment"]
# layout class -> the source whose reading that class's check may make HIGH
# on its own. Measured on the tuning sets: the poll check was right on 270
# of 272 upgrades (the 2 are a neighbouring poll scored against a missed
# one); the grid check on only 33 of 45 and the tags check on 3 of 4, so
# grids and tagged tables still need a second source that agrees.
_CLASS_SOURCE = {"poll": "poll"}


def text_rows(page, rect):
    """Text rows in rect: [(top, bottom, [(x0, x1, text, mono)])], pieces split at wide gaps."""
    spans = []
    for b in page.get_text("dict", clip=rect).get("blocks", []):
        for ln in b.get("lines", []):
            for s in ln.get("spans", []):
                if s["text"].strip():
                    spans.append(s)
    spans.sort(key=lambda s: ((s["bbox"][1] + s["bbox"][3]) / 2, s["bbox"][0]))
    rows: list = []
    for s in spans:
        yc = (s["bbox"][1] + s["bbox"][3]) / 2
        if rows and abs(yc - rows[-1][0]) <= 0.4 * max(s["bbox"][3] - s["bbox"][1], 1):
            rows[-1][1].append(s)
        else:
            rows.append([yc, [s]])
    out = []
    for _, ss in rows:
        ss.sort(key=lambda s: s["bbox"][0])
        segs: list = []
        for s in ss:
            mono = any(k in s["font"].lower() for k in _MONO)
            if segs and s["bbox"][0] - segs[-1][1] < _GAP:
                x0, _, t, m = segs[-1]
                sep = " " if s["bbox"][0] - segs[-1][1] > 1.0 and not t.endswith(" ") else ""
                segs[-1] = (x0, max(segs[-1][1], s["bbox"][2]), t + sep + s["text"], m and mono)
            else:
                segs.append((s["bbox"][0], s["bbox"][2], s["text"], mono))
        out.append((min(s["bbox"][1] for s in ss), max(s["bbox"][3] for s in ss), segs))
    return out


def region_features(page, bbox, sources, flags, gen: str, doc_tagged: bool):
    """(features, text lines) of one table area. Shared with the PoC's training."""
    rect = fitz.Rect(bbox)
    pad = fitz.Rect(rect.x0 - 2, rect.y0 - 8, rect.x1 + 2, rect.y1 + 8)
    f = Counter()
    vcover: dict = {}
    for d in page.get_drawings():
        for it in d["items"]:
            if it[0] == "l":
                a, b = it[1], it[2]
                if not (min(a.x, b.x) <= pad.x1 and max(a.x, b.x) >= pad.x0
                        and min(a.y, b.y) <= pad.y1 and max(a.y, b.y) >= pad.y0):
                    continue
                if abs(a.x - b.x) < 1 and abs(a.y - b.y) >= 8:
                    vcover[round(a.x / 2)] = vcover.get(round(a.x / 2), 0) + abs(a.y - b.y)
                elif abs(a.y - b.y) < 1 and abs(a.x - b.x) >= 0.3 * rect.width:
                    f["hrules"] += 1
            elif it[0] == "re":
                r = it[1]
                if not (r.x0 <= pad.x1 and r.x1 >= pad.x0 and r.y0 <= pad.y1 and r.y1 >= pad.y0):
                    continue
                if r.width <= 2.5 and r.height >= 8:
                    vcover[round(r.x0 / 2)] = vcover.get(round(r.x0 / 2), 0) + r.height
                elif r.height <= 2.5 and r.width >= 0.3 * rect.width:
                    f["hrules"] += 1
                elif d.get("fill") is not None and r.width >= 0.5 * rect.width:
                    if r.contains(rect + (4, 4, -4, -4)):
                        f["enclosing_fill"] += 1
                    elif r.height <= 90:
                        f["row_fills"] += 1
    f["vrules"] = sum(1 for v in vcover.values() if v >= 0.5 * rect.height)
    rows = text_rows(page, rect)
    nrows = len(rows)
    segs = [len(r[2]) for r in rows]
    chars = mono = digits = 0
    words_per_seg = []
    aligned = 0
    prev = None
    for _, _, ss in rows:
        for _, _, t, m in ss:
            n = sum(1 for c in t if not c.isspace())
            chars += n
            mono += n if m else 0
            digits += sum(c.isdigit() for c in t)
            words_per_seg.append(len(t.split()))
        starts = [s[0] for s in ss]
        if prev is not None and sum(1 for x in starts for y in prev if abs(x - y) <= 3) >= 2:
            aligned += 1
        prev = starts
    text = [" | ".join(" ".join(s[2].split()) for s in r[2]).strip() for r in rows]
    x = {
        "doc_tagged": float(doc_tagged), "n_sources": float(len(set(sources))),
        "hrules": f["hrules"], "vrules": f["vrules"], "row_fills": f["row_fills"],
        "enclosing_fill": f["enclosing_fill"],
        "nrows": nrows, "max_segs": max(segs, default=0),
        "median_segs": sorted(segs)[len(segs) // 2] if segs else 0,
        "multi_seg_share": sum(1 for s in segs if s >= 2) / max(nrows, 1),
        "aligned_share": aligned / max(nrows - 1, 1),
        "mono_share": mono / max(chars, 1), "digit_share": digits / max(chars, 1),
        "words_per_seg": sum(words_per_seg) / max(len(words_per_seg), 1),
        "poll_header": float(any(_POLL.match(" ".join(t.translate(_ZW).replace("|", " ").split()))
                                 for t in text)),
        "bullet_rows": sum(1 for t in text if t[:1] in "•●▪■-–*") / max(nrows, 1),
        "comment_rows": sum(1 for t in text if "//" in t) / max(nrows, 1),
        "height": rect.height, "width": rect.width, "width_share": rect.width / page.rect.width,
        "page0": float(page.number == 0),
        "rejected_only": float(all(s in ("tomd", "text") for s in sources)),
    }
    for s in SOURCES:
        x["src_" + s] = float(s in sources)
    for fl in FLAGS:
        x["flag_" + fl] = float(fl in flags)
    for g in GENERATORS:
        x["gen_" + g] = float(gen == g)
    return {k: float(v) for k, v in x.items()}, text


def predict(tree: dict, x: dict):
    """(label, confidence) from a tree exported by cart.Tree.export()."""
    n = tree
    while "f" in n:
        n = n["l"] if x.get(n["f"], 0.0) <= n["t"] else n["r"]
    return n["label"], n["p"]


IMAGE_GRID_SHARE = 0.5      # images covering half a table's area: a figure grid, not data


def image_share(page, bbox) -> float:
    """The share of bbox covered by images drawn on the page (union approximated by the sum,
    capped at 1; overlapping images are rare inside a table)."""
    x0, y0, x1, y1 = bbox
    area = max((x1 - x0) * (y1 - y0), 1e-6)
    covered = 0.0
    try:
        pr = page.rect
        page_area = max(pr.width * pr.height, 1e-6)
        infos = page.get_image_info()
    except Exception:  # a page without image geometry gives no image evidence: nothing demoted
        return 0.0
    for im in infos:
        bx0, by0, bx1, by1 = im.get("bbox", (0, 0, 0, 0))
        im_area = max((bx1 - bx0) * (by1 - by0), 1e-6)
        if im_area >= 0.8 * page_area:
            continue                  # a page background (slides): behind everything, not in the cells
        w, h = min(x1, bx1) - max(x0, bx0), min(y1, by1) - max(y0, by0)
        if w > 0 and h > 0 and w * h >= 0.5 * im_area:
            covered += w * h          # only images that sit mostly inside the table
    return min(covered / area, 1.0)


def gate_tables(doc, pages, sections: list[Section]) -> dict:
    """Check and classify every selected table, adjusting its confidence (see module doc).

    `pages` maps page numbers to the pages the tables were read from; a table
    whose page is not there is not checked and cannot stay HIGH. Returns a
    summary for logging.
    """
    tables = [s for s in sections if s.kind == SectionKind.TABLE and "region_bbox" in s.metadata]
    if not tables:
        return {}
    gen = generator(doc.metadata or {})
    tagged = doc.xref_get_key(doc.pdf_catalog(), "StructTreeRoot")[0] != "null"
    summary = {"tables": len(tables)}
    for sec in tables:
        pg, bbox = sec.metadata["region_bbox"]
        if pg not in pages:
            if sec.confidence == Confidence.HIGH:
                sec.confidence = Confidence.UNCERTAIN
                sec.metadata.setdefault("uncertain_reasons", []).append("unverified")
            continue
        x, _ = region_features(pages[pg], bbox, sec.metadata.get("region_sources", []),
                               sec.metadata.get("region_flags", []), gen, tagged)
        words = words_in(pages[pg], bbox)
        reason = verify_layout(sec, words)
        if reason == "multi-page" and sec.metadata.get("pieces"):
            def words_on(p, b):
                return words_in(pages[p], b) if (b and p in pages) else []
            reason = verify_pieces(sec, words_on)
        if not reason and "conservation" in sec.metadata.get("uncertain_reasons", []):
            # an aligned row just above the table may be its header (checked by content contrast)
            above = words_in(pages[pg], (bbox[0] - 2, bbox[1] - _HEADER_BAND, bbox[2] + 2, bbox[1] - 0.5))
            if above:
                sec.metadata["_above_words"] = above
                reason = "header-above"
        sec.metadata["verified"] = reason or "ok"
        if not sec.metadata.get("page_bboxes"):
            # rows no internal vertical rule crosses: titles and spanning rows (fullwidth.py)
            try:
                _full_width(sec, pages[pg], bbox)
            except Exception as e:  # a layout refinement only; never fail on it, never silently
                current().reader_error("full-width rows", pg, e, table=sec)
            # the fit witness: words against the drawn cells (fit.py) - recorded
            try:
                f = _fit(pages[pg], bbox, words, sec.columns)
                if f.get("pass") and (sec.metadata.get("witness") or {}).get("extent") == "open":
                    f = {**f, "pass": False, "why": "the table may continue on the next page"}
                if not f.get("ruled"):
                    fr = _fit_rows(pages[pg], bbox, words, sec.columns)
                    if fr.get("pass") and (sec.metadata.get("witness") or {}).get("extent") == "open":
                        fr = {**fr, "pass": False, "why": "the table may continue on the next page"}
                    f = {**f, "rows": fr}
                sec.metadata["fit"] = f
                if f.get("pass"):
                    # LIKELY: flagged, but the words fit the drawn cells evenly - probably
                    # right, never HIGH (not yet proven out of sample)
                    sec.metadata["likely"] = {"reason": "fit", "cells": f.get("cells")}
            except Exception as e:  # the fit is a witness only; never fail on it, never silently
                current().reader_error("fit", pg, e, table=sec)
        # every contradiction between the table and the page, by dimension
        try:
            rules = [(y, x0, x1) for y, x0, x1 in page_hrules(pages[pg]) if x0 <= bbox[2] and x1 >= bbox[0]]
            rel = record_for(sec, words, rules)
            sec.metadata["relations"] = {"by_dimension": rel.by_dimension(),
                                         "kinds": sorted({v.kind for v in rel.violations})}
            if sec.confidence != Confidence.HIGH and "word outside every cell" in sec.metadata["relations"]["kinds"]:
                _repair_stray_words(sec, words, rules, rel)
        except Exception as e:  # the record is diagnosis only; never fail on it, never silently
            current().reader_error("relations", pg, e, table=sec)
        # content plausibility - diagnosis only: measured, a violation is right about a
        # wrong table 34% of the time (12% recall)
        rows_text = [[" ".join(sp.text for sp in c if sp.text != "\n").strip() for c in r] for r in sec.columns]
        sec.metadata["plausibility"] = [d for _, d in plausibility(rows_text)]
        # a level per dimension (rows, columns, header, cells) - diagnosis only
        sec.metadata["dimensions"] = dimensions(sec.metadata)
        if reason and sec.confidence != Confidence.HIGH:
            # escalate: a targeted re-read for what failed; kept only if it verifies
            new, moves = escalate(sec, words, reason)
            if new is not None:
                sec.columns, sec.text = new.columns, new.text
                sec.metadata["table_source"] = new.metadata.get("table_source")
                sec.metadata["escalated"] = moves
                sec.metadata.pop("likely", None)      # a new reading: the fit was for the old one
                sec.metadata["verified"] = "ok after " + "+".join(moves)
        kind, kp = predict(TABLE_TREE, x)
        layout, _ = predict(LAYOUT_TREE, x)
        sure_table = kind == "table" and kp >= _TREE_SURE
        sure_not = kind != "table" and kp >= _TREE_SURE
        sec.metadata["gate"] = {"tree": kind, "tree_p": round(kp, 3), "layout": layout,
                                "sure_table": sure_table}
        reasons = sec.metadata.get("uncertain_reasons", [])
        if sec.confidence == Confidence.HIGH and not sure_table:
            sec.confidence = Confidence.UNCERTAIN
            why = (f"The classifiers think this is {'front matter' if kind == 'front-matter' else 'not a table'}."
                   if sure_not else "The classifiers are not sure this is a table.")
            sec.metadata["table_note"] = (sec.metadata.get("table_note", "") + " " + why).strip()
        elif (sec.confidence == Confidence.UNCERTAIN and sure_table and reasons == ["single-source"]
              and sec.metadata.get("class_check") and
              _CLASS_SOURCE.get(layout) == sec.metadata.get("table_source")
              and sec.metadata["class_check"] == layout):
            sec.confidence = Confidence.HIGH
            sec.metadata["table_agreement"] = "class:" + layout
            sec.metadata.pop("table_note", None)
    # a grid whose cells are mostly images is a figure laid out in a table: its text is
    # only the captions, so agreeing readers prove nothing about the content. It only demotes.
    for sec in tables:
        pg, bbox = sec.metadata["region_bbox"]
        if sec.confidence != Confidence.HIGH or pg not in pages:
            continue
        share = image_share(pages[pg], bbox)
        if share >= IMAGE_GRID_SHARE:
            sec.confidence = Confidence.UNCERTAIN
            sec.metadata.setdefault("uncertain_reasons", []).append("image grid")
            sec.metadata["image_grid"] = round(share, 3)
            sec.metadata["table_note"] = (sec.metadata.get("table_note", "") +
                                          f" Images cover {share:.0%} of this table's area: the cells "
                                          "hold pictures, the text is only their captions.").strip()
    return summary


# Notes for the port's sequencing guards (select.TRUST_EXCLUDES_PAPERFLOW_READER,
# select.TRUST_ONLY_PIPE_RENDERING), set by selection and applied after the gate.
_WITHHELD_NOTES = {
    "paperflow-reader": "Paperflow's own reader agrees with this table; that agreement is not yet "
                        "measured as independent evidence.",
    "rendering": "The cells agree, but this table is written by a renderer the agreement does not check.",
}


def withhold_trust(tables: list[Section]) -> None:
    """Lower a HIGH table whose trust a port sequencing guard withholds (demotion only)."""
    for sec in tables:
        withheld = sec.metadata.get("trust_withheld") or []
        if sec.confidence != Confidence.HIGH or not withheld:
            continue
        sec.confidence = Confidence.UNCERTAIN
        reasons = sec.metadata.setdefault("uncertain_reasons", [])
        reasons.extend(w for w in withheld if w not in reasons)
        sec.metadata["table_note"] = (sec.metadata.get("table_note", "") + " " +
                                      " ".join(_WITHHELD_NOTES[w] for w in withheld)).strip()


def _repair_stray_words(sec, words, rules, rel) -> None:
    """Stage 3: page words in no cell placed by the table's own rows and
    columns (repair.py), kept only when the relational check improves with no
    new kind of violation. The table stays flagged; the first reading and the
    repair are kept in the metadata, the inferred cells are marked."""
    got = place_stray_words(sec.columns, words, _newline_span(sec))
    if not got:
        return
    columns, inferred, stray = got
    trial = _with_columns(sec, columns)
    after = record_for(trial, words, rules)
    kinds = {v.kind for v in rel.violations}
    if len(after.violations) >= len(rel.violations) or not {v.kind for v in after.violations} <= kinds:
        return
    sec.metadata["repair"] = {"what": "stray words placed by the table's rows and columns",
                              "stray": stray, "inferred_cells": inferred, "first_reading": sec.text,
                              "violations_before": rel.by_dimension(), "violations_after": after.by_dimension()}
    sec.columns, sec.text = trial.columns, trial.text
    sec.metadata["inferred_cells"] = inferred
    sec.metadata.pop("likely", None)                         # repaired: the fit was for the first reading
    sec.metadata["relations"] = {"by_dimension": after.by_dimension(),
                                 "kinds": sorted({v.kind for v in after.violations})}
    reasons = sec.metadata.setdefault("uncertain_reasons", [])
    if "repaired" not in reasons:
        reasons.append("repaired")
    sec.confidence = Confidence.UNCERTAIN
