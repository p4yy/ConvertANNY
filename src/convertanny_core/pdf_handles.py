"""Keeps track of the PDF documents a worker thread opens, so they can all be closed when its job ends.

Windows will not rename or delete a file that is still open, so a leaked PDF handle would block
the user from tidying up. Each thread sees only its own documents.
"""
from __future__ import annotations

import threading

_store = threading.local()


def _mine() -> list:
    if not hasattr(_store, "documents"):
        _store.documents = []
    return _store.documents


class TrackedPyMuPDF:
    """Behaves like the pymupdf module, except documents opened through it are remembered."""

    def __getattr__(self, name):
        import pymupdf
        return getattr(pymupdf, name)

    def open(self, *args, **kwargs):
        import pymupdf
        document = pymupdf.open(*args, **kwargs)
        _mine().append(document)
        return document

    Document = open


def close_all() -> int:
    """Close every document this thread opened and forget them. Returns how many were closed cleanly."""
    pending, _store.documents = _mine(), []
    closed = 0
    for document in pending:
        try:
            if not document.is_closed:
                document.close()
                closed += 1
        except Exception:
            continue            # one stubborn document must not leave the rest open
    return closed
