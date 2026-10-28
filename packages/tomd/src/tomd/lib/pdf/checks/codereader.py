#
# Copyright (c) 2026 Rob Beeston (rob@cppalliance.org)
#
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
#

"""A lightweight reader for C++-like code lines (user, 2026-10-21): not a parser.

Fed one line at a time per text stream (a column of code), it says for each line:

  depth_before / depth_after   bracket depth ({}, and () [] for open constructs)
  unit_start                   the line starts a top-level unit: a function, struct,
                               class, union, enum, namespace or template block,
                               concept, or a top-level declaration at depth 0
  unit_name                    the unit's declared name (identifier), if any
  unit_end                     a closing brace brings the depth back to 0
  label                        a comment-only line ("// This paper:")
  stmt_end                     the line ends a statement at depth 0 (';')
  continues                    an open construct carries on: unbalanced brackets, or a
                               trailing operator, comma or backslash
  preproc                      a preprocessor line (#include, #define, ...)
  not_cpp                      the line reads as another language or notation (Rust, Swift,
                               assembly, grammar productions): the reader then keeps only the
                               bracket balance and claims no unit (it never vetoes anything)

C++ only (user): declarations, templates, attributes, requires-clauses, lambdas,
contracts syntax (pre / post / contract_assert), preprocessor lines and comments.

String and character literals and comments are stripped before counting.
Deterministic, no dependency. Used as features of the line-boundary decision.
"""
import re

_KEYWORDS = {"if", "for", "while", "switch", "return", "sizeof", "decltype", "alignof", "noexcept",
             "static_assert", "catch", "requires", "operator", "co_await", "co_return", "co_yield",
             "else", "do", "new", "delete", "case", "default", "throw", "using", "typedef",
             "pre", "post", "contract_assert", "assert", "explicit", "constexpr", "consteval"}
_ATTR = re.compile(r"\[\[.*?\]\]")
_LAMBDA = re.compile(r"\[[^\]]*\]\s*(\(|\{|mutable|->)")
_NOT_CPP = re.compile(r"^\s*(?:fn\s+\w|let\s+(?:mut\s+)?\w|impl\b|pub\s+fn|func\s+\w|var\s+\w+\s*[:=]|"
                      r"(?:mov|lea|add|sub|xor|cmp|jmp|jne|je|jl|jle|call|ret|push|pop|test|movzx|movabs|seto)\b(?:\s|$)|"
                      r"\.?L\d+:|[\w-]+\s*::=|[a-z-]+:\s*$)")
_UNIT_KW = re.compile(r"^\s*(?:export\s+)?(?:inline\s+)?(template\s*<|struct|class|union|enum(?:\s+class|\s+struct)?|"
                      r"namespace|concept)\b")
_NAME_AFTER = re.compile(r"\b(?:struct|class|union|enum(?:\s+class|\s+struct)?|namespace|concept)\s+"
                         r"(?:\[\[[^\]]*\]\]\s*)?([A-Za-z_]\w*)")
_FUNC = re.compile(r"([A-Za-z_~][\w:~]*)\s*\(")
_TRAIL_OP = re.compile(r"(?:[,(\[{+\-*/%&|^=<>?:\\]|&&|\|\||->|::)\s*$")
_COMMENT_ONLY = re.compile(r"^\s*(//|/\*|\*(?!\w)|\*/)")


def _strip(line: str, in_block: bool) -> tuple[str, bool]:
    """the line without string/char literals and comments; whether a /* */ comment stays open"""
    out = []
    i, n = 0, len(line)
    while i < n:
        if in_block:
            j = line.find("*/", i)
            if j < 0:
                return "".join(out), True
            i, in_block = j + 2, False
            continue
        c = line[i]
        if line.startswith("//", i):
            break
        if line.startswith("/*", i):
            in_block = True
            i += 2
            continue
        if c in "\"'":
            j = i + 1
            while j < n and line[j] != c:
                j += 2 if line[j] == "\\" else 1
            i = j + 1
            out.append(" ")
            continue
        out.append(c)
        i += 1
    return "".join(out), in_block


class CodeStream:
    """the state of one column of code"""

    def __init__(self):
        self.depth = 0          # braces
        self.paren = 0          # () and []
        self.in_block = False
        self.pending_template = False

    def feed(self, line: str) -> dict:
        info = {"depth_before": self.depth, "unit_start": False, "unit_name": "", "unit_end": False,
                "label": False, "stmt_end": False, "continues": False, "preproc": False, "not_cpp": False}
        code, self.in_block = _strip(line, self.in_block)
        info["label"] = bool(_COMMENT_ONLY.match(line)) and not code.strip()
        info["preproc"] = line.lstrip().startswith("#")
        info["not_cpp"] = bool(_NOT_CPP.match(line))
        s = _ATTR.sub(" ", code).strip()
        top = self.depth == 0 and self.paren == 0
        if info["preproc"]:
            s = ""                      # a preprocessor line opens nothing
        if s and top and not info["not_cpp"] and not _LAMBDA.search(s) and not s.startswith("requires"):
            if self.pending_template:
                info["unit_start"] = False      # the declaration a template line introduced
                self.pending_template = False
            elif _UNIT_KW.match(s):
                info["unit_start"] = True
                if s.startswith("template"):
                    self.pending_template = not ("{" in s or ";" in s)
            elif _FUNC.search(s) and not s.startswith(("}", ")", "]")):
                name = _FUNC.search(s).group(1).split("::")[-1]
                if name not in _KEYWORDS:
                    info["unit_start"] = True
            m = _NAME_AFTER.search(s)
            if m:
                info["unit_name"] = m.group(1)
            elif info["unit_start"]:
                fm = _FUNC.search(s)
                if fm:
                    info["unit_name"] = fm.group(1).split("::")[-1]
        for ch in s:
            if ch == "{":
                self.depth += 1
            elif ch == "}":
                self.depth = max(0, self.depth - 1)
                if self.depth == 0 and info["depth_before"] > 0:
                    info["unit_end"] = True
            elif ch in "([":
                self.paren += 1
            elif ch in ")]":
                self.paren = max(0, self.paren - 1)
        info["depth_after"] = self.depth
        info["stmt_end"] = self.depth == 0 and self.paren == 0 and s.endswith(";")
        info["continues"] = self.paren > 0 or bool(_TRAIL_OP.search(s)) or self.in_block
        return info


def read_lines(lines: list[str]) -> list[dict]:
    """per-line facts for one stream of code lines"""
    st = CodeStream()
    return [st.feed(x) for x in lines]


_CPP_TOKEN = re.compile(r"::|->|\w<[\w:,\s*&<>]*>|\w\([^)]*\)|[{};]|==|!=|&&|\|\||\+\+|--|<<|>>|"
                        r"^(?:std|const|constexpr|auto|template|typename|noexcept|nullptr|static_cast|decltype)\b")


def looks_like_cpp(text: str) -> bool:
    """C++ by its content (any font): a token pattern only code has - scope '::', member
    '->', a template argument list, a call, braces or semicolons, C++ operators, or a
    leading C++ keyword. Abstains (False) on plain words, numbers and math."""
    t = text.strip()
    return bool(t) and not _NOT_CPP.match(t) and bool(_CPP_TOKEN.search(t))
