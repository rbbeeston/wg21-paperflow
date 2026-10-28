#
# Copyright (c) 2026 Rob Beeston (rob@cppalliance.org)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
#

"""Document: a "Table N" caption just above or below the area."""
import re

import fitz

from .base import Check

_CAPTION = re.compile(r"^\s*(Table|Tab\.)\s*\d", re.I)


def has_caption(text_above: str, text_below: str) -> bool:
    return any(_CAPTION.match(ln) for ln in (text_above + "\n" + text_below).splitlines())


def run(ctx) -> dict:
    b = ctx.area["bbox"]
    above = ctx.page.get_text("text", clip=fitz.Rect(b[0] - 40, b[1] - 36, b[2] + 40, b[1] + 2))
    below = ctx.page.get_text("text", clip=fitz.Rect(b[0] - 40, b[3] - 2, b[2] + 40, b[3] + 36))
    return {"d_caption_near": 1.0 if has_caption(above, below) else 0.0}


CHECK = Check("caption", ("region",), "document", 1, False, run, tier=2)
