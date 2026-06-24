"""Make rag-backend importable from tests (parity test imports models/enums).

The smoke test talks HTTP only, but unit-style tests need the backend on the
import path without installing it as a package.
"""
import os
import sys

_RAG_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "rag-backend"))
if _RAG_BACKEND not in sys.path:
    sys.path.insert(0, _RAG_BACKEND)
