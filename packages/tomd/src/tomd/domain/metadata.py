"""
Distributed under the Boost Software License, Version 1.0. (See accompanying

file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)

Official repository: https://github.com/cppalliance/wg21-paperflow
"""

from dataclasses import dataclass, field
from typing import Any

from tomd.lib.metadata_yaml.format import FRONT_MATTER_ORDER


@dataclass
class PaperMetadata:
    """Structured metadata for a WG21 paper."""

    title: str = ""
    document: str = ""
    date: str = ""
    intent: str = ""
    audience: list[str] | str = field(default_factory=list)
    reply_to: list[str] | str = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "PaperMetadata":
        """Construct PaperMetadata from a dictionary of front matter keys."""
        if not data:
            return cls()

        known = {"title", "document", "date", "intent", "audience", "reply-to", "reply_to"}
        extra = {k: v for k, v in data.items() if k not in known}

        audience_val = data.get("audience")
        if audience_val is None:
            audience: list[str] | str = []
        elif isinstance(audience_val, (list, str)):
            audience = audience_val
        else:
            audience = str(audience_val)

        reply_to_val = data.get("reply-to", data.get("reply_to"))
        if reply_to_val is None:
            reply_to: list[str] | str = []
        elif isinstance(reply_to_val, (list, str)):
            reply_to = reply_to_val
        else:
            reply_to = str(reply_to_val)

        return cls(
            title=str(data.get("title") or ""),
            document=str(data.get("document") or ""),
            date=str(data.get("date") or ""),
            intent=str(data.get("intent") or ""),
            audience=audience,
            reply_to=reply_to,
            extra=extra,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize metadata into a dict ordered by canonical FRONT_MATTER_ORDER."""
        d: dict[str, Any] = {}
        for key in FRONT_MATTER_ORDER:
            if key == "title" and self.title:
                d["title"] = self.title
            elif key == "document" and self.document:
                d["document"] = self.document
            elif key == "date" and self.date:
                d["date"] = self.date
            elif key == "intent" and self.intent:
                d["intent"] = self.intent
            elif key == "audience" and self.audience:
                d["audience"] = self.audience
            elif key == "reply-to" and self.reply_to:
                d["reply-to"] = self.reply_to

        for k, v in self.extra.items():
            if k not in d:
                d[k] = v

        return d
