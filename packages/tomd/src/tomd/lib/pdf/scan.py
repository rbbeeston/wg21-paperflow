#
# Copyright (c) 2026 Rob Beeston (rob@cppalliance.org)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
#

"""The region scan: check every piece that makes a table, then decide.

1. Areas: every place any scan nominated or excluded (the evidence record),
   merged per page. Nominating is not deciding; nothing nominated is lost.
2. Features per area, each with its information type (words, paths, tree,
   meaning, document): the classifier's layout features, which scans saw it
   and which rules excluded it, content checks on the best reading in the
   area (items per cell, fragments, header vs body, column shapes, first
   column as keys, shared code), and document cues (a caption nearby).
3. Likelihood that the area is a table: a logistic model fitted on the
   existing truth (scan_model.py), so it is fast and explainable; the top
   supporting and opposing features are recorded with the decision.
4. Bands: high (and two independent information types) -> may be trusted;
   middle -> build, UNCERTAIN; low -> possible-table mark; none -> recorded.
"""
from collections import Counter

import fitz

from ._fitz_lock import _FITZ_LOCK
from .checks.data_or_format import likelihood_data
from .checks.registry import AreaContext, run_region_checks
from .scan_model import MODEL, likelihood
from .summary import generator as _generator
from tomd.domain.elements import Confidence
from .visibility import hide_recorded



# information type of each feature family (stage 0: same-type features do not
# stack like independent witnesses)
# document priors: what the whole document is (tagged at all, which generator made it, how its
# prose is set) describes the document, not this area; they shape the likelihood but never
# count as an independent witness for an area
DOC_PRIOR = "document prior"


def info_of(name: str) -> str:
    if name.startswith(("doc_tagged", "gen_", "f_justified_doc")):
        return DOC_PRIOR
    if name.startswith(("cue_paths", "excl_paths", "hrules", "vrules", "row_fills", "enclosing_fill")):
        return "paths"
    if name.startswith(("cue_tree", "excl_tree", "doc_tagged", "src_tags")):
        return "tree"
    if name.startswith(("c_", "cue_meaning", "excl_meaning", "poll_header", "same_code")):
        return "meaning"
    if name.startswith(("d_", "page0")):
        return "document"
    return "words"


_RULE_FAMILY = (("prose", "prose"), ("split-code", "split_code"), ("ragged", "ragged"), ("outranked", "outranked"),
                ("one column", "one_col"), ("too few", "too_few"), ("sections than rows", "box_words"),
                ("heading", "crosses"), ("share their code", "no_same_code"), ("comment", "comments"),
                ("furniture", "furniture"), ("sparse", "sparse"), ("toc", "toc"), ("list", "list"))
_SOURCE_INFO = {"rules": "paths", "grid": "paths", "tags": "tree", "poll": "meaning", "tomd": "words",
                "codepair": "words", "content": "words", "mark": "words"}


def _inter(a, b) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return max(w, 0) * max(h, 0)


def _area(a) -> float:
    return max(a[2] - a[0], 0.1) * max(a[3] - a[1], 0.1)


def areas(record) -> list[dict]:
    """Nominated and excluded places, merged per page (half the smaller one overlapping)."""
    out: list[dict] = []
    for e in sorted((e for e in record.entries if e.kind in ("nominated", "excluded")),
                    key=lambda e: (e.page, e.bbox[1])):
        for a in out:
            if a["page"] == e.page and _inter(a["bbox"], e.bbox) >= 0.5 * min(_area(a["bbox"]), _area(e.bbox)):
                a["bbox"] = (min(a["bbox"][0], e.bbox[0]), min(a["bbox"][1], e.bbox[1]),
                             max(a["bbox"][2], e.bbox[2]), max(a["bbox"][3], e.bbox[3]))
                break
        else:
            a = {"page": e.page, "bbox": tuple(e.bbox), "cues": Counter(), "excl": Counter(), "scans": set()}
            out.append(a)
        if e.kind == "nominated":
            a["cues"][e.scan] += 1
            a["scans"].add(e.scan)
        else:
            fam = next((k for pat, k in _RULE_FAMILY if pat in e.rule), "other")
            a["excl"][(e.scan, fam)] += 1
    for a in out:
        a["readings"] = [r for r in record.readings if r[1] == a["page"]
                         and _inter(r[2], a["bbox"]) >= 0.5 * _area(r[2])]
        a["same_code"] = max((e.value for e in record.entries if e.kind == "feature" and e.rule == "same-code"
                              and e.page == a["page"] and _inter(e.bbox, a["bbox"]) > 0
                              and isinstance(e.value, (int, float))), default=0.0)
    return out


def area_features(page, a, generator: str, doc_tagged: bool, measure=None, decided=None) -> dict:
    """Every enabled region-level check's evidence for one area (checks/); the
    last-resort tier only while decided(features) is False."""
    return run_region_checks(AreaContext(page, a, generator, doc_tagged, measure), decided)


# early stop (ledger ordering): an area whose likelihood without the last-resort
# tier is below this is not a table whatever that tier says. Measured on the
# 4991 tuning areas: below 0.02 (24% of areas) the full likelihood never
# exceeded 0.043 (LOW is 0.3); at 0.05 one area reached 0.26, too close.
EARLY_NONE = 0.02


def _at_mean(x: dict, model: dict) -> dict:
    """Features the skipped checks would have given, held at their training mean."""
    y = dict(x)
    for name, (mean, _, _) in model["weights"].items():
        y.setdefault(name, mean)
    return y


HIGH, LOW = 0.8, 0.3


def band(p: float, info_types: int) -> str:
    if p >= HIGH and info_types >= 2:
        return "trust"
    if p >= LOW + (HIGH - LOW) / 2 or (p >= HIGH):
        return "build"
    if p >= LOW:
        return "mark"
    return "none"



def _table_boxes(t):
    """Every page piece of a table: a stitched table covers its continuation pages too."""
    boxes = list((t.metadata.get("page_bboxes") or {}).items())
    if t.metadata.get("region_bbox"):
        boxes.append(tuple(t.metadata["region_bbox"]))
    return boxes


def run_scan(path, record, tables, builds: list | None = None) -> list:
    """Score every area in the evidence record and decide by band.

    Emitted tables get their likelihood and top features in metadata; a HIGH
    table the scan rates below LOW is downgraded (reason recorded). Areas
    without a table come back as possible-table regions (page, bbox, reason,
    rows) for the build and mark bands; the rest are only recorded."""
    out = []
    pending: list = []
    with _FITZ_LOCK, fitz.open(str(path)) as doc:  # see _fitz_lock.py for why this lock is required
        hide_recorded(doc)
        generator = _generator(doc.metadata or {})
        doc_tagged = doc.xref_get_key(doc.pdf_catalog(), "StructTreeRoot")[0] != "null"
        all_areas = areas(record)
        # locality: a table takes the one area that best covers its own box (an
        # area best for two tables is a union holding a neighbour: its evidence is neither's)
        own = {}
        for t in tables:
            best = None
            for i, a in enumerate(all_areas):
                cov = max((_inter(bb, a["bbox"]) / _area(bb) for pg, bb in _table_boxes(t) if pg == a["page"]),
                          default=0.0)
                # both ways: the area covers the table, and the table fills a fair share of the
                # area (as the earlier rule asked); a much larger area holding more than this
                # table stays table-less, so the scan can still build what else is in it
                fill = max((_inter(bb, a["bbox"]) / _area(a["bbox"]) for pg, bb in _table_boxes(t) if pg == a["page"]),
                           default=0.0)
                if cov >= 0.3 and fill >= 0.3 and (best is None or (cov, -_area(a["bbox"])) > best[0]):
                    best = ((cov, -_area(a["bbox"])), i)
            if best is not None:
                own[id(t)] = best[1]
        shared = Counter(own.values())
        own = {k: v for k, v in own.items() if shared[v] == 1}
        for ai, a in enumerate(all_areas):
            page = doc[a["page"]]
            mine = [t for t in tables if own.get(id(t)) == ai]
            near = [t for t in tables if any(
                pg == a["page"] and _inter(bb, a["bbox"]) >= 0.3 * _area(a["bbox"]) for pg, bb in _table_boxes(t))]
            if near and not mine:
                continue          # an area over a table that is not its own: not a table-less area either
            # an emitted table gets every check (its data-vs-formatting score and doubt need them)
            decided = None if mine else (lambda f: likelihood(_at_mean(f, MODEL), MODEL)[0] < EARLY_NONE)
            x = area_features(page, a, generator, doc_tagged, getattr(record, "doc_measure", None), decided)
            if x.pop("_skipped", None):
                x = _at_mean(x, MODEL)
                record.feature("scan", a["page"], a["bbox"], "early-stop", "record", 1.0)
            p, top = likelihood(x, MODEL)
            info = len(({info_of(n) for n, c in top if c > 0} - {DOC_PRIOR})
                       | {_SOURCE_INFO.get(s_, "words") for s_ in a["cues"]})
            bnd = band(p, info)
            record.feature("scan", a["page"], a["bbox"], "likelihood", "model", round(p, 3))
            why = ", ".join(f"{n}{'+' if c > 0 else '-'}" for n, c in top[:4])
            for t in mine:
                t.metadata["scan"] = {"p": round(p, 3), "band": bnd, "top": why,
                                      "area": [round(v, 1) for v in a["bbox"]], "cues": sorted(a["scans"])}
                # second output: tabular data or formatting (rendering unchanged; a comment marks it)
                rows = [[" ".join(sp.text for sp in c if sp.text != "\n").strip() for c in r] for r in t.columns]
                pd = likelihood_data(rows, x)
                if pd is not None:
                    t.metadata["data_vs_format"] = round(pd, 3)
                    record.feature("data_or_format", a["page"], a["bbox"], "p_data", "meaning", round(pd, 3))
                if t.confidence == Confidence.HIGH and p < LOW:
                    t.confidence = Confidence.UNCERTAIN
                    t.metadata.setdefault("uncertain_reasons", []).append("scan")
                    t.metadata["table_note"] = (t.metadata.get("table_note", "") +
                                                f" The region scan rates this area unlikely to be a table "
                                                f"(p={p:.2f}; {why}).").strip()
            if not mine:
                pending.append((a, p, why, bnd, max(int(x.get("nrows", 2)), 2)))
    for a, p, why, bnd, nrows in pending:
        if bnd in ("trust", "build") and builds is not None:
            # likely a table no reader kept: the caller builds it (content-first), flagged
            builds.append((a["page"], a["bbox"], round(p, 3), why, nrows))
            continue
        if bnd in ("build", "mark"):
            out.append((a["page"], a["bbox"], f"the region scan rates this area a likely table "
                        f"(p={p:.2f}; {why})", nrows))
    return out
