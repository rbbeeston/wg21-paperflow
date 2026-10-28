#
# Copyright (c) 2026 Rob Beeston (rob@cppalliance.org)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
#

"""Text the PDF holds but the page does not show.

A PDF's text layer can carry text a reader never sees: invisible render mode,
zero opacity, text clipped away, text outside the page, text under something
drawn over it, text the colour of what is behind it, text too small to see.
Most of it is accidental (LaTeXiT base64 blobs, slide builds, clipped figure
labels); some could be deliberate (instructions aimed at the model that reads
the Markdown). Either way it is not the paper as people read it.

Each page is classified once, from the paint trace (get_texttrace: render mode,
colour, opacity, size, drawing order) and the paint log (get_bboxlog: what was
drawn when). Text of a removable class is redacted from the in-memory page
before any reader sees it, and every region is listed - page, box, why, and its
text - at the end of the summary and the prompts, so nothing is lost and
nothing hidden is presented as the paper's words. The rules are the cheap,
deterministic classes of work/hidden_text/scan.py (HIDDEN_TEXT.md), kept to the
ones whose precision on the corpus allows removal:

  invisible-render-mode  render mode 3/7, not over an image (an image under it is
                         a scan's OCR layer: the only text of the page, kept)
  opacity-0              fill opacity <= 0.05, not over an image (macOS emoji are
                         images under a transparent copy of the character: kept)
  clipped                kept by get_text(flags=0), dropped by TEXT_CLIP
  tiny                   size < 1 pt and glyph box < 1.5 pt high, on a page with
                         no Type3 font (old Type3 text reports 0.24 pt sizes)
  under-image            every character under an opaque image drawn later
  same-colour            the colour of a known background under every character
                         (the page, or an opaque rectangle; anything else under it
                         - an image, a shading, a curved path - is unknown: kept)
                         These two guess at what is under the text, so each is
                         confirmed by the picture: the region is rendered as is and
                         with the text redacted, and the text is kept if it shows
                         (white text on a black glyph drawn first; an image drawn
                         with a blend mode: p2988r6, n5024, p3389r0)
  under-box              under an opaque rectangle drawn later; removed by
                         pagecache.remove_covered_text, only listed here
  off-page               outside the page box; MuPDF drops it, only listed here

A hidden run that duplicates visible text at the same place (an invisible copy
of a visible line) is kept: the page shows that text. 
"""
import unicodedata

import fitz

from ._fitz_lock import _FITZ_LOCK
from .runctx import current

_TEXT_CAP = 200          # characters of a region's text listed
_SUMMARY_REGIONS = 50    # regions listed in the summary
_MERGE_GAP = 12.0        # points between runs of one class merged into a region

WHY_TEXT = {
    "invisible-render-mode": "text in the invisible render mode",
    "opacity-0": "fully transparent text",
    "clipped": "text clipped away by a clip path",
    "tiny": "text under 1 pt high",
    "under-image": "text under an image drawn over it",
    "same-colour": "text the colour of its background",
    "under-box": "text under a box drawn over it",
    "off-page": "text outside the page",
}
_REDACT = {"invisible-render-mode", "opacity-0", "clipped", "tiny", "under-image", "same-colour"}


def _rgb(c):
    if c is None:
        return None
    if isinstance(c, (int, float)):
        return (float(c),) * 3
    if len(c) == 1:
        return (c[0],) * 3
    if len(c) == 4:      # cmyk
        return tuple((1 - x) * (1 - c[3]) for x in c[:3])
    return tuple(c[:3])


def _inside(r, x, y):
    return r[0] <= x <= r[2] and r[1] <= y <= r[3]


def _centre(b):
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def _clipped_origins(page) -> set:
    """origins of the characters MuPDF drops with clipping on but keeps with flags=0"""
    on = page.get_text("text", flags=fitz.TEXT_CLIP | fitz.TEXT_MEDIABOX_CLIP)
    off = page.get_text("text", flags=0)
    if len("".join(on.split())) >= len("".join(off.split())):
        return set()

    def origins(flags):
        out = []
        for b in page.get_text("rawdict", flags=flags).get("blocks", []):
            for ln in b.get("lines", []) if b.get("type") == 0 else []:
                for sp in ln.get("spans", []):
                    for ch in sp.get("chars", []):
                        out.append((ch["c"], round(ch["origin"][0], 1), round(ch["origin"][1], 1)))
        return out
    kept = set(origins(fitz.TEXT_CLIP | fitz.TEXT_MEDIABOX_CLIP))
    return {k for k in origins(0) if k not in kept}


def _image_masks(page) -> list:
    """(bbox, may be transparent) for the page's images"""
    out = []
    doc = page.parent
    for info in page.get_image_info(xrefs=True):
        x = info.get("xref", 0)
        m = bool(info.get("has-mask"))
        if x and not m:
            m = doc.xref_get_key(x, "SMask")[0] != "null" or doc.xref_get_key(x, "Mask")[0] != "null"
        out.append((tuple(info["bbox"]), m or not x))      # an inline image: unknown, treated as transparent
    return out


def classify(page) -> list[dict]:
    """The page's text that the page does not show, as regions:
    {page, bbox, why, chars, text, action, points}; points are the character
    centres to redact (empty when the text is kept or already gone)."""
    pr = page.rect
    trace = page.get_texttrace()
    if not trace:
        return []
    log = page.get_bboxlog()
    fills = [(i, r) for i, (k, r) in enumerate(log) if k == "fill-path"]
    imgs = [(i, r, k) for i, (k, r) in enumerate(log) if k in ("fill-image", "fill-imgmask", "fill-shade")]
    has_type3 = any(f[2] == "Type3" for f in page.get_fonts())
    clipped = _clipped_origins(page)
    masks = None
    drawings = None

    def by_seq():
        nonlocal drawings
        if drawings is None:
            drawings = {d.get("seqno", -1): d for d in page.get_drawings() if d.get("fill") is not None}
        return drawings

    def opaque_image(r):
        nonlocal masks
        if masks is None:
            masks = _image_masks(page)
        for bb, m in masks:
            if all(abs(a - b) < 1 for a, b in zip(bb, r)):
                return not m
        return False

    def opaque_rects(i, x, y):
        d = by_seq().get(i)
        if d is None or (d.get("fill_opacity") is not None and d["fill_opacity"] < 0.99):
            return None
        return [it[1] for it in d["items"] if it[0] == "re" and it[1].width > 4 and it[1].height > 4
                and _inside(it[1], x, y)]

    def background(seq, x, y):
        """the colour behind a point, or None when it is not known for certain"""
        under = [(i, "f") for i, r in fills if i < seq and _inside(r, x, y)]
        under += [(i, "i") for i, r, _ in imgs if i < seq and _inside(r, x, y)]
        if not under:
            return (1.0, 1.0, 1.0)              # nothing drawn there: the page
        i, k = max(under)
        if k == "i":
            return None
        d = by_seq().get(i)
        rects = opaque_rects(i, x, y)
        if not rects:                            # a path that is not a rectangle there
            return None
        return _rgb(d["fill"])

    pieces = []            # (seq, why, chars[(c, origin, bbox)])
    visible = []           # (c, origin) of the characters the page shows
    for s in trace:
        # spaces kept for the listed text; format and combining characters (zero-width
        # spaces, a keycap's combining mark) count as spaces: they show nothing of their
        # own, and redacting one at its zero-width box would take the letter beside it
        chars = [(" " if unicodedata.category(chr(c[0]))[0] in "MC" else chr(c[0]), c[2], c[3]) for c in s["chars"]]
        if not any(ch[0].strip() for ch in chars):
            continue
        seq = s["seqno"]
        cx, cy = _centre(s["bbox"])
        if not (pr.x0 - 1 <= cx <= pr.x1 + 1 and pr.y0 - 1 <= cy <= pr.y1 + 1):
            pieces.append((seq, "off-page", chars))
            continue
        if s["type"] in (3, 7):
            if not any(_inside(r, cx, cy) for _, r, _ in imgs):
                pieces.append((seq, "invisible-render-mode", chars))
            continue                                # over an image: an OCR layer, the page's text
        if s.get("opacity", 1) <= 0.05:
            # over an image, it is the picture's text: macOS draws emoji as images with
            # a transparent copy of the character over each (the table cells of p3784r1)
            bare = [ch for ch in chars if ch[0].strip()
                    and not any(_inside(r, *_centre(ch[2])) for _, r, _ in imgs)]
            if bare:
                pieces.append((seq, "opacity-0", [ch for ch in chars if ch in bare or not ch[0].strip()]))
            continue
        if clipped:
            cut = [ch for ch in chars if (ch[0], round(ch[1][0], 1), round(ch[1][1], 1)) in clipped]
            if cut:
                pieces.append((seq, "clipped", cut))
                chars = [ch for ch in chars if ch not in cut]
                if not any(ch[0].strip() for ch in chars):
                    continue
        b = s["bbox"]
        if not has_type3 and s.get("size", 10) < 1.0 and (b[3] - b[1]) < 1.5:
            pieces.append((seq, "tiny", chars))
            continue
        cents = [_centre(ch[2]) for ch in chars if ch[0].strip()]
        later = [r for i, r, k in imgs if i > seq and k == "fill-image"]
        if later and all(any(_inside(r, x, y) for r in later) for x, y in cents):
            cover = [r for r in later if _inside(r, cx, cy)]
            if cover and all(opaque_image(r) for r in cover):
                pieces.append((seq, "under-image", chars))
                continue
        later_f = [i for i, r in fills if i > seq and fitz.Rect(r).intersects(fitz.Rect(b))]
        if later_f and all(any(opaque_rects(i, x, y) for i in later_f) for x, y in cents):
            pieces.append((seq, "under-box", chars))
            continue
        col = _rgb(s.get("color")) if s["type"] == 0 else None
        if col is not None:
            bgs = [background(seq, x, y) for x, y in cents]
            if all(bg is not None and max(abs(a - c) for a, c in zip(col, bg)) <= 0.06 for bg in bgs):
                pieces.append((seq, "same-colour", chars))
                continue
        visible.extend((ch[0], ch[1]) for ch in chars if ch[0].strip())

    def duplicate(chars):
        """an invisible copy of visible text at the same place"""
        ink = [(c, o) for c, o, _ in chars if c.strip()]
        hit = sum(1 for c, o in ink
                  if any(v == c and abs(vo[0] - o[0]) < 1.5 and abs(vo[1] - o[1]) < 1.5 for v, vo in visible))
        return hit >= 0.9 * len(ink)

    regions: list[dict] = []
    for seq, why, chars in pieces:
        ink = [ch for ch in chars if ch[0].strip()]
        if not ink:                     # only spaces (clipped at the end of a line)
            continue
        bb = [min(ch[2][0] for ch in ink), min(ch[2][1] for ch in ink),
              max(ch[2][2] for ch in ink), max(ch[2][3] for ch in ink)]
        last = regions[-1] if regions else None
        if (last and last["why"] == why and bb[1] - last["bbox"][3] <= _MERGE_GAP
                and last["bbox"][1] - bb[3] <= _MERGE_GAP):
            last["bbox"] = [min(last["bbox"][0], bb[0]), min(last["bbox"][1], bb[1]),
                            max(last["bbox"][2], bb[2]), max(last["bbox"][3], bb[3])]
            last["_chars"].extend(chars)
            continue
        regions.append({"page": page.number + 1, "bbox": bb, "why": why, "_chars": list(chars)})
    out = []
    for r in regions:
        chars = r.pop("_chars")
        if r["why"] in ("invisible-render-mode", "opacity-0") and visible and duplicate(chars):
            continue                    # the page shows this text: nothing hidden
        r["chars"] = sum(1 for ch in chars if ch[0].strip())
        r["text"] = _text(chars)
        r["bbox"] = [round(x) for x in r["bbox"]]
        r["action"] = "dropped" if r["why"] == "off-page" else "removed"
        r["points"] = [_centre(ch[2]) for ch in chars if ch[0].strip()] if r["why"] in _REDACT else []
        out.append(r)
    if any(r["why"] in _RENDER_CHECKED for r in out):
        out = [r for r in out if r["why"] not in _RENDER_CHECKED or not _shows(page, r, out)]
    return sorted(out, key=lambda r: (r["bbox"][1], r["bbox"][0]))


_RENDER_CHECKED = {"same-colour", "under-image"}
_RENDER_DPI = 100
_INK_DIFF = 24           # a pixel changes visibly when a channel moves by more than this (of 255)
_INK_SHARE = 0.01        # ...and the text shows when this share of its box's pixels does


def _shows(page, region, regions) -> bool:
    """whether the page as drawn shows the region's text: the region rendered
    as is, and again from a copy of the page with the candidates' characters
    redacted. The rules behind these classes guess at what is under the text (a
    colour, an image); the picture settles it (text over a glyph drawn first,
    an image drawn with a blend mode or a soft-masked graphics state)."""
    doc = page.parent
    cache = getattr(doc, "_tomd_vis_render", None)
    if cache is None or cache[0] != page.number:
        # a scratch one-page copy, opened inside the caller's session: the caller
        # holds _FITZ_LOCK (a plain lock; acquiring it again here would deadlock)
        assert _FITZ_LOCK.locked(), "visibility checks run inside a _FITZ_LOCK session"
        tmp = fitz.open()
        tmp.insert_pdf(doc, from_page=page.number, to_page=page.number)
        cp = tmp[0]
        for r in regions:
            if r["why"] in _RENDER_CHECKED:
                for x, y in r["points"]:
                    cp.add_redact_annot(fitz.Rect(x - 0.5, y - 0.5, x + 0.5, y + 0.5))
        cp.apply_redactions(images=0, graphics=0, text=0)
        cache = (page.number, tmp)
        try:
            doc._tomd_vis_render = cache
        except AttributeError:
            pass
    clip = fitz.Rect(region["bbox"]) + (-1, -1, 1, 1)
    a = page.get_pixmap(dpi=_RENDER_DPI, clip=clip, colorspace=fitz.csRGB, alpha=False, annots=False)
    b = cache[1][0].get_pixmap(dpi=_RENDER_DPI, clip=clip, colorspace=fitz.csRGB, alpha=False, annots=False)
    if (a.width, a.height) != (b.width, b.height):
        return True
    sa, sb = a.samples, b.samples
    changed = sum(1 for i in range(0, len(sa), 3)
                  if max(abs(sa[i] - sb[i]), abs(sa[i + 1] - sb[i + 1]), abs(sa[i + 2] - sb[i + 2])) > _INK_DIFF)
    return changed > max(2, _INK_SHARE * a.width * a.height)


def _text(chars) -> str:
    """the characters in drawing order, one line of text; a space where a new line starts"""
    out = []
    prev = None
    for c, o, _ in chars:
        if prev is not None and abs(o[1] - prev[1]) > 2 and out and out[-1] != " ":
            out.append(" ")
        out.append(" " if not c.strip() else c)
        prev = o
    return " ".join("".join(out).split())


def remove_hidden_text(page, regions) -> bool:
    """redact (in memory) the characters of the removable regions; True if any"""
    pts = [p for r in regions for p in r.get("points", [])]
    if not pts:
        return False
    for x, y in pts:
        page.add_redact_annot(fitz.Rect(x - 0.5, y - 0.5, x + 0.5, y + 0.5))
    page.apply_redactions(images=0, graphics=0, text=0)
    return True


def check_page(page) -> list[dict]:
    """Classify the page once per run, record its regions on the run context
    and return them (before any redaction: the caller removes them)."""
    cache = current().hidden
    if page.number in cache:
        return cache[page.number]
    try:
        regions = classify(page)
    except Exception as e:  # a page that cannot be checked keeps its text; never silently
        current().reader_error("visibility check", page.number, e)
        regions = []
    cache[page.number] = regions
    return regions


def hide_recorded(doc) -> None:
    """Remove the recorded hidden text from a reopened copy of the document, so
    every reader of every session sees the page as shown."""
    for pg, regions in current().hidden.items():
        if pg < doc.page_count:
            try:
                remove_hidden_text(doc[pg], regions)
            except Exception as e:  # a page that cannot be redacted keeps its text; never silently
                current().reader_error("hidden-text removal", pg, e)


def recorded_regions() -> list[dict]:
    """Every region recorded in this run, in page order."""
    cache = current().hidden
    return [r for p in sorted(cache) for r in cache[p]]


def summary(regions: list[dict]) -> dict:
    """the summary's `visibility` object"""
    by_why: dict = {}
    for r in regions:
        w = by_why.setdefault(r["why"], {"regions": 0, "chars": 0, "pages": []})
        w["regions"] += 1
        w["chars"] += r["chars"]
        if r["page"] not in w["pages"]:
            w["pages"].append(r["page"])
    return {"checked": "cheap", "regions": len(regions), "chars": sum(r["chars"] for r in regions),
            "by_why": dict(sorted(by_why.items())),
            "hidden": [{"page": r["page"], "bbox": r["bbox"], "why": r["why"], "chars": r["chars"],
                        "action": r["action"], "text": r["text"][:_TEXT_CAP]} for r in regions[:_SUMMARY_REGIONS]],
            "truncated": len(regions) > _SUMMARY_REGIONS}


def discards(regions: list[dict]) -> list[tuple]:
    """the Removed-content lines: one per reason, with its pages"""
    out = []
    for why, w in summary(regions)["by_why"].items():
        ps = w["pages"]
        where = ", ".join(str(p) for p in ps[:20]) + (" ..." if len(ps) > 20 else "")
        verb = "dropped" if why == "off-page" else "removed"
        out.append(("hidden", f"{WHY_TEXT[why]}: {w['regions']} region(s), {w['chars']} characters {verb} "
                    f"on page(s) {where}; listed in the summary", ""))
    return out
