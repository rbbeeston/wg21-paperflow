"""
Distributed under the Boost Software License, Version 1.0. (See accompanying

file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)

Official repository: https://github.com/cppalliance/wg21-paperflow
"""

from __future__ import annotations

import logging
import re
from typing import Any

from tomd.lib.metadata_yaml.format import (
    FRONT_MATTER_RE,
    format_front_matter,
    parse_front_matter,
    sanitize_metadata,
    strip_front_matter,
)
from tomd.lib.shared import EMAIL_RE

logger = logging.getLogger(__name__)

_TOC_MAX_LINES = 300
_TOC_RE = re.compile(
    r"(?m)^(?:#{1,6}\s*)?(?:Table of )?Contents[ \t]*$\r?\n?"
    r"(.*?)"
    r"(?=\r?\n#{1,6}\s|\Z)",
    re.DOTALL | re.IGNORECASE,
)

_FALLBACK_KEY_MAP = {
    "title": "title",
    "paper_id": "document",
    "document_date": "date",
    "subgroup": "audience",
    "target_group": "audience",
    "authors": "reply-to",
}

_OVERRIDE_KEYS = {"document"}

_METADATA_TABLE_LINE_RE = re.compile(
    r"^\|\s*(?:Doc(?:ument)?\.?\s*(?:No\.?|Number|#)|Date|Reply[- ]?to|"
    r"Audience|Author|Editor|Project|Email|Subgroup)\s*",
    re.IGNORECASE,
)
_PIPE_TABLE_ROW_RE = re.compile(r"^\|.*\|$")
_PIPE_SEPARATOR_RE = re.compile(r"^\|[\s\-:|]+\|$")
_METADATA_TABLE_SCAN_DEPTH = 30
_MIN_LABEL_ROWS_FOR_TABLE_STRIP = 2


def _strip_toc_replace(m: re.Match[str]) -> str:
    span = m.group(0)
    if span.count("\n") > _TOC_MAX_LINES:
        return span
    return "\n"


def strip_toc(text: str) -> str:
    """Remove Table of Contents block from Markdown string."""
    return _TOC_RE.sub(_strip_toc_replace, text)


def normalize_front_matter(md: str, mailing_meta: dict[str, Any] | None) -> str:
    """Parse front matter once, sanitize, apply mailing fallback, and re-emit."""
    parsed = parse_front_matter(md)
    rest = strip_front_matter(md)

    if not parsed and not mailing_meta:
        return md

    parsed = sanitize_metadata(parsed)

    if mailing_meta:
        present = set(parsed)
        rt = parsed.get("reply-to")
        if isinstance(rt, list) and rt and not any(EMAIL_RE.search(e) for e in rt):
            present.discard("reply-to")
        added_yaml_keys: set[str] = set()
        for src_key, yaml_key in _FALLBACK_KEY_MAP.items():
            if yaml_key in added_yaml_keys:
                continue
            is_override = yaml_key in _OVERRIDE_KEYS
            if yaml_key in present and not is_override:
                continue
            val = (
                mailing_meta.get(src_key)
                if isinstance(mailing_meta, dict) and src_key in mailing_meta
                else (
                    mailing_meta.get(yaml_key)
                    if isinstance(mailing_meta, dict)
                    else getattr(
                        mailing_meta,
                        src_key,
                        getattr(mailing_meta, yaml_key, None),
                    )
                )
            )
            if val in (None, "", []):
                continue
            if yaml_key == "date":
                logger.debug(
                    "Date fallback from mailing (%s=%r): source had no date",
                    src_key,
                    val,
                )
            parsed[yaml_key] = val
            added_yaml_keys.add(yaml_key)

    if not parsed:
        return md

    new_block = format_front_matter(parsed)
    if not new_block:
        return md

    return f"{new_block}\n\n{rest.lstrip()}"


def strip_body_metadata_text(md: str) -> str:
    """Remove redundant metadata pipe tables from body text after front matter."""
    match = FRONT_MATTER_RE.match(md)
    if not match:
        return md

    front = md[: match.end()]
    body = md[match.end() :]

    lines = body.split("\n")
    to_remove: set[int] = set()
    i = 0
    scan_limit = min(len(lines), _METADATA_TABLE_SCAN_DEPTH)

    while i < scan_limit:
        if not lines[i].strip():
            i += 1
            continue

        if _PIPE_TABLE_ROW_RE.match(lines[i].strip()):
            table_start = i
            table_end = i
            label_count = 0

            while table_end < len(lines) and (
                _PIPE_TABLE_ROW_RE.match(lines[table_end].strip())
                or _PIPE_SEPARATOR_RE.match(lines[table_end].strip())
            ):
                if _METADATA_TABLE_LINE_RE.match(lines[table_end].strip()):
                    label_count += 1
                table_end += 1

            if label_count >= _MIN_LABEL_ROWS_FOR_TABLE_STRIP:
                for j in range(table_start, table_end):
                    to_remove.add(j)
                i = table_end
                continue

        if lines[i].strip().startswith("#"):
            break

        i += 1

    if not to_remove:
        return md

    new_lines = [ln for j, ln in enumerate(lines) if j not in to_remove]
    return front + "\n".join(new_lines)
