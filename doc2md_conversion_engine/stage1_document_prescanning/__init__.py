"""
stage1_document_prescanning
===========================
STAGE 1 of 4 in the doc2md conversion pipeline — "Look before you leap."

The whole job of Stage 1 is to learn enough about a document to make one smart,
cheap decision before any expensive conversion work begins: which engine should
convert it. It runs fast, calls no AI model, and sends no data over the network.

It answers three questions in order, and the three sub-packages below map one to
one onto those questions:

    1. document_identity   — "What document is this?"
                             Fingerprint the file (SHA-256, streamed), turn that
                             into a stable job id, detect its type, and reject
                             files that are too large.

    2. feature_extraction  — "What is actually inside it?"
                             Read structural evidence directly from the file:
                             real text vs. scanned images, table count and
                             complexity, multi-column layout, figures. The result
                             is one DocumentFeatureProfile.

    3. engine_routing      — "Which engine should process it?"
                             From that profile, deterministically pick Docling
                             (the cheap default) or MinerU (only when the
                             evidence proves the document is structurally hard).

Why deterministic instead of asking a model?
    Every routing choice is computed from structural facts, so the same document
    always routes the same way, the reason always names the exact signal that
    fired, and no patient data ever leaves the process for an inference call.
    The signals (XML structure, table geometry, text-block layout) are cheap to
    read in the same pass that already gathers the feature evidence.

What happens next:
    Stage 2 (page extraction) takes the chosen engine and does the real
    conversion to Markdown, page by page.

This file re-exports the few classes the rest of the pipeline needs, so callers
import from ``stage1_document_prescanning`` and never reach into its internals.
"""

from .document_identity import DocumentHashResult, DocumentSHA256Hasher
from .engine_routing import EngineRoutingPolicy
from .feature_extraction import DocumentFeatureExtractor, DocumentFeatureProfile

__all__ = [
    # Step 1 — identity
    "DocumentSHA256Hasher",
    "DocumentHashResult",
    # Step 2 — feature extraction
    "DocumentFeatureExtractor",
    "DocumentFeatureProfile",
    # Step 3 — engine routing
    "EngineRoutingPolicy",
]
