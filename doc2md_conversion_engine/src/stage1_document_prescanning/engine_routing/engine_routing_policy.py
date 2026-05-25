"""
stage1_document_prescanning/engine_routing/engine_routing_policy.py
===================================================================
Stage 1 · Step 3 of 3 — the final engine decision.

This is the last thing Stage 1 does. Everything before it gathered facts; this
file turns those facts into a single answer: "convert this document with Docling,
or with MinerU?" It returns that answer together with a plain-English reason and
a confidence number for the logs.

The rule it follows, in plain terms
-----------------------------------
Docling is the default choice. It is cheaper and faster, and it already
understands documents that carry their structure inside them (Word styles, HTML
tags, a real text layer). So a document stays with Docling UNLESS we can prove it
has structure Docling would get wrong. We only switch to the heavier MinerU when
the evidence shows one of three concrete problems:

    - the text does not flow in one straight column   → reading order is hard
      (multiple columns, or free-floating text boxes)
    - the tables are genuinely complicated             → the grid is hard
      (merged cells, tables inside tables, very wide)
    - there is no real text to read at all             → it must be recovered
      (a scanned document, so OCR/layout work is needed)

A key idea: "no evidence of a problem" is treated as a vote FOR Docling, not as
uncertainty. We never drift to MinerU just because we are unsure.

Why there is no AI model here
-----------------------------
The decision is computed entirely from the structural facts measured earlier, so
the same document always lands on the same engine, the reason always names the
exact signal that triggered the switch, and no document content is ever sent off
to a model to decide.
"""

from __future__ import annotations

from ...contracts.configurations.pipeline_config import (
    ConversionEngineChoice,
    EngineRoutingConfig,
)
from ...contracts.exceptions import ConfigurationError
from ...contracts.pipeline_domain_types import (
    EngineClassification,
    ExtractionEngine,
    MinerUBackend,
)
from ..feature_extraction.feature_evidence_models import DocumentFeatureProfile

# Confidence = how reliable this routing decision is, for logging/observability.
# Rule-based routing computes no probability, so these are fixed and ordered by
# how directly the decision follows from evidence:
#   forced override            certain — the operator dictated it.
#   single-engine format       a hard fact — only one engine supports the format.
#   structural promotion       a concrete positive signal was detected.
#   Docling default            the fallback — no promotion signal fired, so it is
#                              an absence of evidence and ranks below a positive
#                              detection (it must never read as MORE reliable than
#                              a hard structural promotion).
_CONFIDENCE_FORCED = 1.0
_CONFIDENCE_FORMAT_EXCLUSIVE = 0.98
_CONFIDENCE_STRUCTURAL_PROMOTION = 0.90
_CONFIDENCE_DOCLING_DEFAULT = 0.85


class EngineRoutingPolicy:
    """
    Choose the cheapest sufficient structure engine from explicit capabilities.

    The router is conservative and deterministic.  It honours a forced config
    override, removes unsupported engines, promotes to MinerU only on hard
    structural evidence, and otherwise confirms Docling.
    """

    def __init__(self, routing_config: EngineRoutingConfig | None = None) -> None:
        self._routing_config = routing_config

    def route(self, profile: DocumentFeatureProfile) -> EngineClassification:
        """
        Decide which engine converts this document, and say why.

        The decision is made by asking four questions in order and stopping at
        the first one that answers. Order matters — each question is more
        specific than the one below it:

            1. Did an operator force a specific engine in the config? If so, use
               it (after checking that engine can actually open this format).
            2. Does only ONE engine even support this file format? If so, there
               is nothing to decide — use that one.
            3. Is there hard structural evidence the document is hard to read?
               If so, promote to MinerU and name the exact reason.
            4. Otherwise, confirm Docling — nothing demands a heavier engine.

        Returns an ``EngineClassification`` carrying the chosen engine, a
        confidence value for the logs, and a human-readable reason.
        """
        # Step 1: forced config override, with format compatibility validation.
        forced_classification = self._resolve_forced_classification_from_config()
        if forced_classification is not None:
            # Forced routing bypasses scoring, not hard format compatibility.
            self._validate_forced_engine_format_compatibility(forced_classification, profile)
            return forced_classification

        # Step 2: single-engine format exclusivity.
        format_support = profile.format_support
        if format_support.docling_supported and not format_support.mineru_supported:
            return _build_capability_routing_classification(
                engine=ExtractionEngine.DOCLING,
                backend=None,
                confidence=_CONFIDENCE_FORMAT_EXCLUSIVE,
                reason="Docling selected because it is the only declared engine for this format.",
            )
        if format_support.mineru_supported and not format_support.docling_supported:
            return _build_capability_routing_classification(
                engine=ExtractionEngine.MINERU,
                backend=MinerUBackend.AUTO,
                confidence=_CONFIDENCE_FORMAT_EXCLUSIVE,
                reason="MinerU selected because it is the only declared engine for this format.",
            )

        # Step 3: structural promotion to MinerU on hard, deterministic evidence.
        promotion_reason = _structural_promotion_reason(profile)
        if promotion_reason is not None and format_support.mineru_supported:
            return _build_capability_routing_classification(
                engine=ExtractionEngine.MINERU,
                backend=MinerUBackend.AUTO,
                confidence=_CONFIDENCE_STRUCTURAL_PROMOTION,
                reason=f"MinerU selected: {promotion_reason}",
            )

        # Step 4: Docling confirmed — no structural evidence demands a heavier engine.
        return _build_capability_routing_classification(
            engine=ExtractionEngine.DOCLING,
            backend=None,
            confidence=_CONFIDENCE_DOCLING_DEFAULT,
            reason="Docling confirmed: no multi-column layout, complex tables, or missing text layer detected.",
        )

    def _resolve_forced_classification_from_config(self) -> EngineClassification | None:
        """
        Check whether the operator has pinned an engine in ``settings.yaml``.

        Sometimes a human wants to override the automatic choice (for testing, or
        because they know something the signals don't). If ``conversion_engine``
        is set to ``docling`` or ``mineru``, this returns that choice with full
        confidence. If it is left on ``auto``, this returns ``None`` and the
        normal evidence-based steps take over.
        """
        if self._routing_config is None:
            return None
        forced = self._routing_config.conversion_engine
        if forced == ConversionEngineChoice.DOCLING:
            return _build_capability_routing_classification(
                engine=ExtractionEngine.DOCLING,
                backend=None,
                confidence=_CONFIDENCE_FORCED,
                reason="forced by configuration (conversion_engine = docling)",
            )
        if forced == ConversionEngineChoice.MINERU:
            return _build_capability_routing_classification(
                engine=ExtractionEngine.MINERU,
                backend=MinerUBackend.AUTO,
                confidence=_CONFIDENCE_FORCED,
                reason="forced by configuration (conversion_engine = mineru)",
            )
        return None

    def _validate_forced_engine_format_compatibility(
        self,
        forced_classification: EngineClassification,
        profile: DocumentFeatureProfile,
    ) -> None:
        """
        Make sure a forced engine can actually open this document's format.

        Forcing an engine skips the automatic choice, but it must not let someone
        send, say, an HTML file to MinerU (which cannot read HTML). If the forced
        engine does not support this format, we stop with a clear configuration
        error instead of failing deep inside conversion later.
        """
        format_support = profile.format_support
        if (
            forced_classification.engine == ExtractionEngine.DOCLING
            and format_support.docling_supported
        ):
            return
        if (
            forced_classification.engine == ExtractionEngine.MINERU
            and format_support.mineru_supported
        ):
            return

        raise ConfigurationError(
            (
                f"Configured conversion_engine='{forced_classification.engine.value}' is not "
                f"supported for document type '{profile.file_type.value}'. "
                "Use conversion_engine='auto' or a supported engine for this format."
            ),
            context={
                "forced_engine": forced_classification.engine.value,
                "document_type": profile.file_type.value,
                "docling_supported": format_support.docling_supported,
                "mineru_supported": format_support.mineru_supported,
            },
        )


def _structural_promotion_reason(profile: DocumentFeatureProfile) -> str | None:
    """
    Look for a concrete reason to upgrade from Docling to MinerU.

    This checks the three "is it hard?" needs that were worked out earlier, in
    order of how strongly they justify the heavier engine. It returns the first
    matching reason as a sentence (which becomes the routing reason in the logs),
    or ``None`` when none apply — meaning Docling is fine.

    Note what is deliberately NOT here: having figures or charts does not promote
    to MinerU. Explaining a figure is a later stage's job (Stage 3), not a reason
    to pick a heavier layout engine now.
    """
    requirements = profile.requirements
    if requirements.needs_reading_order_reconstruction:
        return (
            "non-linear layout (multi-column or floating text boxes) requires "
            "reading-order reconstruction"
        )
    if requirements.needs_complex_table_reconstruction:
        return "structurally complex tables (merged, nested, or very wide) require grid reconstruction"
    if requirements.needs_ocr_text_recovery:
        return "no usable native text layer; scanned/layout content requires recovery"
    return None


def _build_capability_routing_classification(
    *,
    engine: ExtractionEngine,
    backend: MinerUBackend | None,
    confidence: float,
    reason: str,
) -> EngineClassification:
    """
    Package a routing decision into the standard result object.

    A small helper so every one of the four decision branches above produces a
    result the same way and cannot accidentally disagree on shape. The
    ``complexity_score`` is fixed at zero on purpose: this policy decides by
    rules, not by computing a numeric difficulty score.
    """
    return EngineClassification(
        engine=engine,
        backend=backend,
        # Capability routing is rule-based; it does not compute a numeric score.
        complexity_score=0.0,
        confidence=confidence,
        reason=reason,
    )
