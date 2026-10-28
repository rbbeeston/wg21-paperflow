#
# Copyright (c) 2026 Rob Beeston (rob@cppalliance.org)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
#

"""Drawing: rules, vertical lines, row shading and enclosing boxes in the area."""
from .base import Check
from ._layout import DRAWN, layout_features


def run(ctx) -> dict:
    x = layout_features(ctx)
    return {k: v for k, v in x.items() if k.startswith(DRAWN)}


CHECK = Check("drawn_lines", ("region",), "paths", 1, False, run)
