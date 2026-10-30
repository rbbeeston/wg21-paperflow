"""
Distributed under the Boost Software License, Version 1.0. (See accompanying

file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)

Official repository: https://github.com/cppalliance/wg21-paperflow
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import singledispatch
import re

from tomd.domain.span import (
    CodeSpan,
    DeletedSpan,
    EmphasisSpan,
    InsertedSpan,
    LineBreakSpan,
    LinkSpan,
    Span,
    StrongSpan,
    SubscriptSpan,
    SuperscriptSpan,
    TextSpan,
)


def _wrap_delimiters(inner: str, delim: str) -> str:
    """Wrap content with Markdown delimiters while keeping leading/trailing whitespace outside."""
    leading_ws = inner[: len(inner) - len(inner.lstrip())]
    trailing_ws = inner[len(inner.rstrip()) :]
    stripped = inner.strip()
    if not stripped:
        return inner
    return f"{leading_ws}{delim}{stripped}{delim}{trailing_ws}"


def format_code_span(code: str) -> str:
    """Format an inline code span handling embedded backticks."""
    if "`" not in code:
        return f"`{code}`"

    # Find longest run of backticks to choose fence length
    backtick_runs = re.findall(r"`+", code)
    max_run = max(len(r) for r in backtick_runs) if backtick_runs else 1
    fence = "`" * (max_run + 1)

    # Pad with space if code starts or ends with a backtick
    if code.startswith("`") or code.endswith("`"):
        return f"{fence} {code} {fence}"
    return f"{fence}{code}{fence}"


@singledispatch
def write_span(span: Span) -> str:
    """Recursively format a domain Span AST node into Markdown/HTML text."""
    return getattr(span, "text", "")


@write_span.register
def _write_text_span(span: TextSpan) -> str:
    return span.content


@write_span.register
def _write_code_span(span: CodeSpan) -> str:
    return format_code_span(span.code)


@write_span.register
def _write_line_break_span(_span: LineBreakSpan) -> str:
    return "<br>"


@write_span.register
def _write_strong_span(span: StrongSpan) -> str:
    inner = write_spans(span.children)
    if not inner:
        return ""
    return _wrap_delimiters(inner, "**")


@write_span.register
def _write_emphasis_span(span: EmphasisSpan) -> str:
    inner = write_spans(span.children)
    if not inner:
        return ""
    return _wrap_delimiters(inner, "*")


@write_span.register
def _write_deleted_span(span: DeletedSpan) -> str:
    inner = write_spans(span.children)
    if not inner:
        return ""
    return f"<del>{inner}</del>"


@write_span.register
def _write_inserted_span(span: InsertedSpan) -> str:
    inner = write_spans(span.children)
    if not inner:
        return ""
    return f"<ins>{inner}</ins>"


@write_span.register
def _write_subscript_span(span: SubscriptSpan) -> str:
    inner = write_spans(span.children)
    if not inner:
        return ""
    return f"<sub>{inner}</sub>"


@write_span.register
def _write_superscript_span(span: SuperscriptSpan) -> str:
    inner = write_spans(span.children)
    if not inner:
        return ""
    return f"<sup>{inner}</sup>"


@write_span.register
def _write_link_span(span: LinkSpan) -> str:
    inner = write_spans(span.children)
    title_suffix = f' "{span.title}"' if span.title else ""
    return f"[{inner}]({span.url}{title_suffix})"


def write_spans(spans: Sequence[Span]) -> str:
    """Format a sequence of Spans into concatenated Markdown text."""
    return "".join(write_span(s) for s in spans)
