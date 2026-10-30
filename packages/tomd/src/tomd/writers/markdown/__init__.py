"""
Distributed under the Boost Software License, Version 1.0. (See accompanying

file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)

Official repository: https://github.com/cppalliance/wg21-paperflow
"""

from tomd.writers.markdown.markers import append_trailer_markers
from tomd.writers.markdown.writer import MarkdownWriter

__all__ = [
    "MarkdownWriter",
    "append_trailer_markers",
]
