"""
engine_routing
==============
Stage 1 · Step 3 of 3 — "Which conversion engine should process this document?"

This sub-package reads the evidence gathered in ``feature_extraction`` and makes
the final, single decision of Stage 1: send this document to Docling, or to
MinerU. The decision is deterministic — it is computed purely from structural
facts, never from a model guess — so the same document always routes the same
way and the chosen reason always names the exact signal that triggered it.

The guiding rule is "Docling by default, MinerU only on proof". Docling is
cheaper and faster, so a document stays with Docling unless the evidence proves
it has structure Docling cannot reconstruct correctly (multi-column reading
order, complex merged/nested tables, or no usable text layer at all).

Three modules, read in this order:

    engine_format_compatibility.py     The hard facts: which engines can even
                                       open this file format at all. Anything an
                                       engine can't open is removed first.

    document_requirements_resolver.py  Turns raw evidence into plain yes/no needs
                                       ("needs reading-order reconstruction",
                                       "needs complex-table reconstruction",
                                       "needs OCR text recovery").

    engine_routing_policy.py           Applies the rules in order and returns the
                                       final engine choice with its reason.
"""

from .document_requirements_resolver import resolve_document_requirements
from .engine_format_compatibility import get_engine_format_compatibility
from .engine_routing_policy import EngineRoutingPolicy

__all__ = [
    "EngineRoutingPolicy",
    "get_engine_format_compatibility",
    "resolve_document_requirements",
]
