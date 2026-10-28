# Copyright (c) 2026 Dmitriy Chukhin (dmitriy@lincolnloop.com)
# Distributed under the Boost Software License, Version 1.0.
# https://www.boost.org/LICENSE_1_0.txt

"""Shared process-wide lock that must be held for all PyMuPDF (fitz) sessions."""

import threading

# PyMuPDF (fitz) is not thread-safe. MuPDF's C-level global state (font store,
# glyph caches, warning buffer fitz.JM_mupdf_warnings_store) is shared across
# all fitz.Document objects in a process, and fitz releases the GIL for C-level
# calls so threads genuinely run MuPDF code in parallel. All code that opens or
# drives a fitz.Document must acquire this lock for the full duration of the
# open/close session.
# Current fitz sites: pipeline.py (run_pipeline: the main session and the table
# checks' session), docling_backend.py (_extract_docling_tables).
# Update this list when adding a new fitz caller.
_FITZ_LOCK = threading.Lock()
