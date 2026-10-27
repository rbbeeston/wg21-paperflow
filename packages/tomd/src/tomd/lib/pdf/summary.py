#
# Copyright (c) 2026 Rob Beeston (rob@cppalliance.org)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
#

"""Paper-level summary: what tomd did with this paper's tables, and how unlike
the measured papers this one is.

The output feeds AI analysis of WG21 papers, where a trusted-but-wrong
conversion is the costly failure, so every conversion carries:
  - tables trusted (HIGH), flagged (UNCERTAIN) and marked (possible tables),
    with their pages; content removed on purpose and why; reader errors;
  - an unfamiliarity score: how unlike the measured papers this one is
    (generator not seen in the measured sets, rare layout classes, rotated
    text);
  - a paper-level confidence: the chance that the paper's tables hold no
    silent error. It is "not estimated" here: the calibrated model belongs to
    the conversion it was fitted on, and is refitted on this pipeline's output
    before a figure is published.

Machine-readable (``PipelineResult.summary``, persisted by the CLI beside the
Markdown), one ``tomd:summary`` comment after the front matter, and prompt
elements for the removed content, the reader errors and the summary.
"""

# Generators of the measured papers (the answer-key sets).
KNOWN_GENERATORS = {"LaTeX", "Word", "Google Docs", "ReportLab", "macOS", "Typst", "pypdf", "Chrome/Skia",
                    "LibreOffice", "Ghostscript", "unknown"}
COMMON_LAYOUTS = {"poll", "grid", "rule-per-row", "tagged", "booktabs"}
# Producer substrings (creator or producer metadata, lower case) -> generator family.
_GENERATOR_KEYS = (("reportlab", "ReportLab"), ("typst", "Typst"),
                   ("google docs", "Google Docs"), ("skia", "Chrome/Skia"),
                   ("microsoft", "Word"), ("pdfmaker", "Word"),
                   ("libreoffice", "LibreOffice"), ("writer", "LibreOffice"),
                   ("luatex", "LaTeX"), ("pdftex", "LaTeX"), ("xetex", "LaTeX"),
                   ("latex", "LaTeX"), ("xdvipdfmx", "LaTeX"),
                   ("quartz", "macOS"), ("pages", "macOS"), ("pypdf", "pypdf"),
                   ("chrome", "Chrome/Skia"), ("ghostscript", "Ghostscript"))
# Unfamiliarity contributions.
_UNKNOWN_GENERATOR = 0.4
_RARE_LAYOUT_EACH = 0.05
_RARE_LAYOUT_MAX = 0.2
_ROTATED = 0.1
_SKIPPED = 0.3


def generator(meta: dict) -> str:
    """The PDF producer's family, from the document metadata."""
    s = f"{meta.get('creator') or ''} {meta.get('producer') or ''}".lower()
    for key, name in _GENERATOR_KEYS:
        if key in s:
            return name
    return "other"


def unfamiliarity(generator_name: str, layouts: list[str], rotated: bool,
                  skipped: bool) -> tuple[float, list[str]]:
    """0 (like the measured papers) .. 1 (unlike them), with the reasons."""
    parts = []
    score = 0.0
    if generator_name not in KNOWN_GENERATORS:
        score += _UNKNOWN_GENERATOR
        parts.append(f"generator {generator_name!r} not among the measured papers")
    # "?" is a table no classifier placed: unknown, not rare
    rare = [x for x in layouts if x not in COMMON_LAYOUTS and x != "?"]
    if rare:
        score += min(_RARE_LAYOUT_MAX, _RARE_LAYOUT_EACH * len(rare))
        parts.append(f"rare layout classes: {sorted(set(rare))}")
    if rotated:
        score += _ROTATED
        parts.append("rotated text")
    if skipped:
        score += _SKIPPED
        parts.append("document skipped (slide deck or standards draft)")
    return min(score, 1.0), parts


def build(sections, discards: list[tuple[str, str, str]], reader_errors: list[dict],
          generator_name: str) -> dict:
    """The paper summary (JSON-serializable)."""
    tables = [s for s in sections if s.kind.value == "table"]
    trusted = [s for s in tables if s.confidence.value == "high"]
    flagged = [s for s in tables if s.confidence.value != "high"]
    likely = [s for s in flagged if s.metadata.get("likely")]
    marks = [s for s in sections if (s.metadata or {}).get("possible_table")]
    layouts = [((s.metadata or {}).get("gate") or {}).get("layout", "?") for s in tables]
    levels: dict[str, int] = {}
    for s in tables:
        lv = (s.metadata or {}).get("level")
        if lv:
            key = f"L{lv['level']}"
            levels[key] = levels.get(key, 0) + 1
    rotated = any("rotated" in str((s.metadata or {}).get("relations", "")) for s in tables)
    skipped = any(d[0] == "document" for d in discards)
    uf, why = unfamiliarity(generator_name, layouts, rotated, skipped)
    return {
        "tables": {"total": len(tables), "trusted": len(trusted), "flagged": len(flagged),
                   "likely": len(likely), "likely_pages": sorted({t.page_num + 1 for t in likely}),
                   "trusted_pages": sorted({t.page_num + 1 for t in trusted}),
                   "flagged_pages": sorted({t.page_num + 1 for t in flagged}),
                   "levels": dict(sorted(levels.items())),
                   "types": dict(sorted({x: layouts.count(x) for x in set(layouts)}.items())),
                   "with_violations": sum(1 for t in tables if sum(((t.metadata or {}).get("relations") or {})
                                                                    .get("by_dimension", {}).values()))},
        "marks": len(marks), "marked_pages": sorted({m.page_num + 1 for m in marks}),
        "removed": [{"what": w, "why": y} for w, y, _ in discards],
        "reader_errors": [dict(e) for e in reader_errors],
        "unfamiliarity": {"score": round(uf, 2), "reasons": why},
        "generator": generator_name,
        "confidence": None,
    }


def header_comment(s: dict) -> str:
    """The one-line ``tomd:summary`` comment written after the front matter."""
    t = s["tables"]
    c = s["confidence"]
    conf = "n/a" if c is None else f"{c['value']:.2f}"
    return (f"<!-- tomd:summary tables={t['total']} trusted={t['trusted']} flagged={t['flagged']} "
            f"likely={t.get('likely', 0)} "
            f"marked={s['marks']} confidence={conf} unfamiliarity={s['unfamiliarity']['score']:.2f} -->")


def prompt_elements(s: dict, discards: list[tuple[str, str, str]], reader_errors: list[dict]) -> list[str]:
    """Self-contained prompt elements: removed content, reader errors, the summary."""
    out = []
    if discards:
        lines = ["tomd removed this content from the PDF's Markdown on purpose; check it if "
                 "something is missing.", ""]
        lines += [f"- {what}: {why}" + (f" (e.g. \"{detail}\")" if detail else "")
                  for what, why, detail in discards]
        out.append("\n".join(lines))
    if reader_errors:
        lines = ["These table readers or checks raised while converting the PDF; the paper "
                 "was converted without them.", ""]
        lines += [f"- {e['stage']}" + ("" if e["page"] is None else f" (page {e['page'] + 1})")
                  + f": {e['type']}: {e['message']}" for e in reader_errors]
        out.append("\n".join(lines))
    t = s["tables"]
    lines = [
        "Summary of the tables in this PDF's Markdown conversion.", "",
        f"- Tables: {t['total']} ({t['trusted']} trusted on pages {t['trusted_pages'] or '-'}, "
        f"{t['flagged']} flagged on pages {t['flagged_pages'] or '-'}); possible tables marked: {s['marks']}"
        + (f" (pages {s['marked_pages']})" if s["marked_pages"] else ""),
        f"- Levels: {t['levels'] or '-'}",
        f"- Table types: {t['types'] or '-'}",
        "- Confidence that no table error is silent: not estimated",
        f"- Unfamiliarity: {s['unfamiliarity']['score']:.2f}"
        + (f" ({'; '.join(s['unfamiliarity']['reasons'])})" if s["unfamiliarity"]["reasons"] else ""),
    ]
    out.append("\n".join(lines))
    return out
