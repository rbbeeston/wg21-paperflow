#
# Copyright (c) 2026 Rob Beeston (rob@cppalliance.org)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
#

"""The scan's region checks, in a fixed order (cheapest and most decisive first)."""
from typing import Callable

from . import caption, coherence, data_or_format, drawn_lines, footprint, nominations, same_code, \
    text_alignment, wordgap
from .base import AreaContext, Check

# The ledger's order; every check is on (the ledger's off-switch is not ported).
REGISTRY = [nominations.CHECK, drawn_lines.CHECK, text_alignment.CHECK, wordgap.CHECK, footprint.CHECK,
            caption.CHECK, coherence.CHECK, same_code.CHECK, data_or_format.CHECK]


# Per-generator tiers (the ledger computed within each generator family on the development
# sets, work/ledger_gen_*.txt): a last-resort check is effective for a family - unique AUC
# >= 0.005 and more decisions fixed than harmed, in a family of 200+ areas - and runs in
# tier 1 there. Families not listed use the global tiers.
GENERATOR_TIER = {
    "LibreOffice": {"wordgap": 1},          # unique +0.0218, fixes 3 / harms 0 (225 areas)
    "ReportLab": {"wordgap": 1},            # unique +0.0141, fixes 10 / harms 4 (789 areas)
    "Chrome/Skia": {"wordgap": 1},          # unique +0.0062, fixes 2 / harms 0 (210 areas)
    "other": {"footprint": 1},              # unique +0.0083, fixes 4 / harms 2 (908 areas)
}


def _tier(check: Check, generator: str) -> int:
    g = generator or "unknown"
    fam = "other" if g.startswith("other") or g in ("unknown", "pypdf") else g
    return GENERATOR_TIER.get(fam, {}).get(check.name, check.tier)


def run_region_checks(ctx: AreaContext, decided: Callable[[dict], bool] | None = None) -> dict:
    """Tier 1 first; the last-resort tier only while decided(features) is False
    . Tiers per generator family where the family's ledger says so.
    Returns the features; "_skipped" lists the checks not run."""
    out: dict = {}
    checks = [c for c in REGISTRY if "region" in c.levels]
    gen = getattr(ctx, "generator", "unknown")
    for check in (c for c in checks if _tier(c, gen) == 1):
        out.update(check.run(ctx))
    rest = [c for c in checks if _tier(c, gen) > 1]
    if rest and decided is not None and decided(out):
        out["_skipped"] = [c.name for c in rest]
        return out
    for check in rest:
        out.update(check.run(ctx))
    return out
