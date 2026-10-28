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
