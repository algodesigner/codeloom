"""codeloom: Local-first code graph builder with 5-signal hybrid search
for AI coding agents.
"""

import os

# Suppress duplicate libomp.dylib abort at import time.
# PyTorch and FAISS each bundle their own OpenMP runtime; when both are
# loaded in the same process the second initialisation calls abort().
# This env var allows both copies to coexist safely.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

__version__ = "0.1.10"

__all__ = ["__version__", "core", "query", "storage", "cli"]
