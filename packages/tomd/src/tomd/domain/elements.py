"""
Block-level AST nodes for WG21 paper documents.

Code diffs are represented on ``CodeBlock`` via its optional ``lines`` field
(per-line span sequences carrying ``InsertedSpan`` / ``DeletedSpan`` role runs)
rather than a separate element class, keeping one code block type across the
AST and writer.

Distributed under the Boost Software License, Version 1.0. (See accompanying

file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)

Official repository: https://github.com/cppalliance/wg21-paperflow
"""
from dataclasses import asdict, dataclass, field, replace
from enum import StrEnum
from typing import Literal, Self

from tomd.domain.span import Span, TextSpan
from tomd.prompts import render_prompt

WordingRole = Literal["wording", "wording-add", "wording-remove"]


class Confidence(StrEnum):
    """Confidence level for structural classification decisions."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class Provenance:
    """Source page and confidence metadata for a block element."""

    page: int
    confidence: Confidence


class ElementKind(StrEnum):
    """Enumeration of block element kinds."""

    HEADING = "heading"
    PARAGRAPH = "paragraph"
    CODE_BLOCK = "code_block"
    TABLE = "table"
    LIST = "list"
    BLOCKQUOTE = "blockquote"
    WORDING = "wording"
    THEMATIC_BREAK = "thematic_break"
    IMAGE = "image"
    UNCERTAIN = "uncertain"


@dataclass
class BlockElement:
    """Base class for all document-level block AST nodes."""

    provenance: Provenance | None = field(default=None, kw_only=True)

    @property
    def text(self) -> str:
        """Return recursive unformatted plain text of this block."""
        return ""

    def role_text(self, target_type: type[Span]) -> str:
        """Return concatenated plain text of inline spans matching ``target_type``."""
        return ""

    def unwrap_spans(self, target_type: type[Span]) -> Self:
        """Return a copy of this block with ``target_type`` spans unwrapped."""
        return self


@dataclass
class Heading(BlockElement):
    """Section heading with depth level."""

    level: int
    spans: list[Span] = field(default_factory=list)

    @classmethod
    def from_text(cls, level: int, text: str) -> Self:
        return cls(level=level, spans=[TextSpan(text)])

    @property
    def text(self) -> str:
        return "".join(s.text for s in self.spans)

    def role_text(self, target_type: type[Span]) -> str:
        return "".join(s.role_text(target_type) for s in self.spans)

    def unwrap_spans(self, target_type: type[Span]) -> Self:
        return replace(self, spans=[u for s in self.spans for u in s.unwrap(target_type)])


@dataclass
class Paragraph(BlockElement):
    """Prose paragraph containing inline text spans."""

    spans: list[Span] = field(default_factory=list)

    @classmethod
    def from_text(cls, text: str) -> Self:
        return cls(spans=[TextSpan(text)])

    @property
    def text(self) -> str:
        return "".join(s.text for s in self.spans)

    def role_text(self, target_type: type[Span]) -> str:
        return "".join(s.role_text(target_type) for s in self.spans)

    def unwrap_spans(self, target_type: type[Span]) -> Self:
        return replace(self, spans=[u for s in self.spans for u in s.unwrap(target_type)])


@dataclass
class CodeBlock(BlockElement):
    """Multi-line code block; ``lines`` carries inline role spans for code diffs."""

    code: str = ""
    language: str = "cpp"
    title: str | None = None
    lines: list[list[Span]] | None = None

    @property
    def text(self) -> str:
        if self.lines is not None:
            return "\n".join("".join(s.text for s in line) for line in self.lines)
        return self.code


@dataclass
class ListItem:
    """Individual list item: an inline label plus optional continuation blocks."""

    spans: list[Span] = field(default_factory=list)
    children: list[BlockElement] = field(default_factory=list)
    marker: str | None = None

    @classmethod
    def from_text(cls, text: str) -> Self:
        return cls(spans=[TextSpan(text)])

    @property
    def text(self) -> str:
        label = "".join(s.text for s in self.spans)
        parts = [label, *(child.text for child in self.children)]
        return "\n".join(part for part in parts if part)

    def role_text(self, target_type: type[Span]) -> str:
        spans_text = "".join(s.role_text(target_type) for s in self.spans)
        children_text = "".join(c.role_text(target_type) for c in self.children)
        return spans_text + children_text

    def unwrap_spans(self, target_type: type[Span]) -> Self:
        return replace(
            self,
            spans=[u for s in self.spans for u in s.unwrap(target_type)],
            children=[c.unwrap_spans(target_type) for c in self.children],
        )


@dataclass
class ListBlock(BlockElement):
    """Ordered or unordered list; ``start`` numbers the first ordered item."""

    items: list[ListItem] = field(default_factory=list)
    ordered: bool = False
    start: int = 1

    @property
    def text(self) -> str:
        return "\n".join(item.text for item in self.items)

    def role_text(self, target_type: type[Span]) -> str:
        return "".join(item.role_text(target_type) for item in self.items)

    def unwrap_spans(self, target_type: type[Span]) -> Self:
        return replace(self, items=[item.unwrap_spans(target_type) for item in self.items])


@dataclass
class Blockquote(BlockElement):
    """Indented quotation or note block."""

    children: list[BlockElement] = field(default_factory=list)
    role: str | None = None

    @classmethod
    def from_text(cls, content: str, role: str | None = None) -> Self:
        return cls(children=[Paragraph.from_text(content)] if content else [], role=role)

    @property
    def text(self) -> str:
        return "\n".join(child.text for child in self.children if child.text)

    def role_text(self, target_type: type[Span]) -> str:
        return "".join(c.role_text(target_type) for c in self.children)

    def unwrap_spans(self, target_type: type[Span]) -> Self:
        return replace(self, children=[c.unwrap_spans(target_type) for c in self.children])


@dataclass
class WordingBlock(BlockElement):
    """Proposed standard wording modification block."""

    role: WordingRole = "wording"
    children: list[BlockElement] = field(default_factory=list)

    @classmethod
    def from_text(cls, text: str, role: WordingRole = "wording") -> Self:
        return cls(role=role, children=[Paragraph.from_text(text)] if text else [])

    @property
    def text(self) -> str:
        return "\n".join(child.text for child in self.children if child.text)

    def role_text(self, target_type: type[Span]) -> str:
        return "".join(c.role_text(target_type) for c in self.children)

    def unwrap_spans(self, target_type: type[Span]) -> Self:
        return replace(self, children=[c.unwrap_spans(target_type) for c in self.children])


@dataclass
class ThematicBreak(BlockElement):
    """Horizontal divider / thematic break."""

    pass


@dataclass
class ImageElement(BlockElement):
    """Block image reference with caption and alt text."""

    caption: str
    alt: str = ""
    stored_filename: str = ""

    @property
    def text(self) -> str:
        return self.caption or self.alt


@dataclass
class UncertainElement(BlockElement):
    """Region where dual-path PDF extraction disagreed."""

    mupdf_text: str
    spatial_text: str
    page: int
    # Body text emitted under the uncertain marker in Markdown (starts as
    # mupdf_text, potentially trimmed by downstream passes such as abstract
    # extraction); also used as a fallback if either extraction is empty.
    text: str = ""
    context_before: str = ""
    context_after: str = ""

    def get_reconciliation_prompt(self) -> str:
        """Build the self-contained LLM reconciliation prompt for this region."""
        return render_prompt("uncertain_element.md.j2", **asdict(self))
