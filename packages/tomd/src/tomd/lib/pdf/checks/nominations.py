#
# Copyright (c) 2026 Rob Beeston (rob@cppalliance.org)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
#

"""Which scans nominated the area and which rules excluded it (the evidence
record), with the number of independent information types among them."""
from .base import Check

SOURCE_INFO = {"rules": "paths", "grid": "paths", "tags": "tree", "poll": "meaning", "tomd": "words",
               "codepair": "words", "content": "words", "mark": "words"}


def run(ctx) -> dict:
    a = ctx.area
    x = {}
    for s, n in a["cues"].items():
        x[f"cue_{SOURCE_INFO.get(s, 'words')}_{s}"] = float(n)
    for (s, fam), n in a["excl"].items():
        x[f"excl_{SOURCE_INFO.get(s, 'words')}_{fam}"] = float(n)
    x["n_info_types"] = float(len({SOURCE_INFO.get(s, "words") for s in a["cues"]}))
    return x


CHECK = Check("nominations", ("region",), "record", 0, False, run)
