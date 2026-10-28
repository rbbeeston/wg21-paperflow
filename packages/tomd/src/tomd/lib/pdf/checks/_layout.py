#
# Copyright (c) 2026 Rob Beeston (rob@cppalliance.org)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
#

"""Shared computation for the two layout checks (computed once per area)."""
from ..classify import region_features


def layout_features(ctx) -> dict:
    if "layout" not in ctx.cache:
        a = ctx.area
        srcs = [s for s in a["cues"] if s in ("tags", "poll", "grid", "rules", "tomd")]
        x, _ = region_features(ctx.page, a["bbox"], srcs, [], ctx.generator, ctx.doc_tagged)
        ctx.cache["layout"] = dict(x)
    return ctx.cache["layout"]


DRAWN = ("hrules", "vrules", "row_fills", "enclosing_fill")
