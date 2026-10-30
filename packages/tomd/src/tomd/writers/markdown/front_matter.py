"""
Distributed under the Boost Software License, Version 1.0. (See accompanying

file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)

Official repository: https://github.com/cppalliance/wg21-paperflow
"""

from __future__ import annotations

from typing import Any

from tomd.domain.metadata import PaperMetadata
from tomd.lib.metadata_yaml.format import format_front_matter


def _drop_blanks(data: dict[str, Any]) -> dict[str, Any]:
    """Return ``data`` without blank values; blank items are dropped from list values."""
    cleaned: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, (list, tuple)):
            items = [v for v in value if str(v).strip()]
            if items:
                cleaned[key] = items
        elif value is not None and str(value).strip():
            cleaned[key] = value
    return cleaned


def write_front_matter(metadata: PaperMetadata | dict[str, Any] | None) -> str:
    """Format metadata as YAML front matter via the canonical ``format_front_matter``."""
    if isinstance(metadata, PaperMetadata):
        data = metadata.to_dict()
    elif isinstance(metadata, dict):
        data = dict(metadata)
    else:
        return ""

    return format_front_matter(_drop_blanks(data))
