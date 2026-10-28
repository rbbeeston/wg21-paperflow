#
# Copyright (c) 2026 Rob Beeston (rob@cppalliance.org)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
#

"""One rawdict extraction per page, shared by the readers that need characters.
The cache lives on the document object, so it goes away with it and is never
shared between conversions."""


def rawdict(page):
    doc = page.parent
    cache = getattr(doc, "_tomd_rawdict", None)
    if cache is None:
        cache = {}
        try:
            doc._tomd_rawdict = cache
        except AttributeError:          # an object that takes no attributes: no cache
            return page.get_text("rawdict", flags=0)
    raw = cache.get(page.number)
    if raw is None:
        raw = cache[page.number] = _dedup_raw(page.get_text("rawdict", flags=0))
    return raw


# A second copy of a character this close to the first is the same glyph printed twice.
_DUP_DX = 1.0
_DUP_DY = 1.5


def _dedup_raw(raw: dict) -> dict:
    """the text layer without a second copy of the same characters printed over the
    first (a header encoded twice, offset by under a point): the page shows it once"""
    seen: dict = {}
    dup = 0
    for blk in raw.get("blocks", []):
        for ln in blk.get("lines", []) if blk.get("type") == 0 else []:
            for sp in ln.get("spans", []):
                for ch in sp.get("chars", []):
                    if not ch.get("c", "").strip():
                        continue
                    b = ch["bbox"]
                    k = (ch["c"], round(b[0]), round(b[1] / 2))
                    if any((ch["c"], k[1] + i, k[2] + j) in seen for i in (-1, 0, 1) for j in (-1, 0, 1)
                           if abs(seen.get((ch["c"], k[1] + i, k[2] + j), (1e9, 1e9))[0] - b[0]) < _DUP_DX
                           and abs(seen.get((ch["c"], k[1] + i, k[2] + j), (1e9, 1e9))[1] - b[1]) < _DUP_DY):
                        ch["_dup"] = True
                        dup += 1
                    else:
                        seen[k] = (b[0], b[1])
    if not dup:
        return raw
    out = {**raw, "blocks": []}
    for blk in raw.get("blocks", []):
        if blk.get("type") != 0:
            out["blocks"].append(blk)
            continue
        lines = []
        for ln in blk.get("lines", []):
            sps = [{**sp, "chars": [c for c in sp.get("chars", []) if not c.get("_dup")]} for sp in ln.get("spans", [])]
            sps = [sp for sp in sps if sp["chars"]]
            if sps:
                lines.append({**ln, "spans": sps})
        if lines:
            out["blocks"].append({**blk, "lines": lines})
    return out


def _dedup_words(words: list) -> list:
    """page words without a second copy of the same word printed over the first"""
    out, seen = [], {}
    for w in words:
        k = (w[4], round(w[0]), round(w[1] / 2))
        if any(abs(v[0] - w[0]) < _DUP_DX and abs(v[1] - w[1]) < _DUP_DY
               for i in (-1, 0, 1) for j in (-1, 0, 1) for v in seen.get((w[4], k[1] + i, k[2] + j), [])):
            continue
        seen.setdefault(k, []).append((w[0], w[1]))
        out.append(w)
    return out


# A text line whose direction is this far from horizontal is rotated.
_ROTATED_DIR = 0.01
# A word centred this close inside a rotated line belongs to it.
_ROTATED_SLACK = 0.5


def words_in(page, bbox):
    """The page's words whose centre lies in bbox. Words are taken whole from the
    whole page: a clipped extraction drops glyphs whose ink falls outside the clip
    and splits the word there. Words of rotated lines (a column label set at 90
    degrees) are not words of the horizontal text and are left out."""
    doc = getattr(page, "parent", None)
    cache = getattr(doc, "_tomd_words", None) if doc is not None else None
    if cache is None and doc is not None:
        cache = {}
        try:
            doc._tomd_words = cache
        except AttributeError:
            cache = None
    words = cache.get(page.number) if cache is not None else None
    if words is None:
        words = _dedup_words(page.get_text("words"))
        if doc is not None:
            rot = [tuple(ln["bbox"]) for b in rawdict(page).get("blocks", []) if b.get("type") == 0
                   for ln in b.get("lines", []) if abs(ln.get("dir", (1, 0))[0] - 1) > _ROTATED_DIR]
            if rot:
                words = [w for w in words if not any(
                    r[0] - _ROTATED_SLACK <= (w[0] + w[2]) / 2 <= r[2] + _ROTATED_SLACK
                    and r[1] - _ROTATED_SLACK <= (w[1] + w[3]) / 2 <= r[3] + _ROTATED_SLACK for r in rot)]
        if cache is not None:
            cache[page.number] = words
    x0, y0, x1, y1 = tuple(bbox)
    return [w for w in words if x0 <= (w[0] + w[2]) / 2 <= x1 and y0 <= (w[1] + w[3]) / 2 <= y1]
