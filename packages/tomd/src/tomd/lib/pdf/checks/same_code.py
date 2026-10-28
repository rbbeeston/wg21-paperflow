#
# Copyright (c) 2026 Rob Beeston (rob@cppalliance.org)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
#

"""Meaning: the largest code-pair similarity recorded in the area (weighted
by size where it was computed; one-line blocks abstain upstream)."""
from .base import Check


def run(ctx) -> dict:
    return {"same_code": float(ctx.area.get("same_code") or 0.0)}


CHECK = Check("same_code", ("region", "content"), "meaning", 0, False, run)
