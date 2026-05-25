"""
doc_feature_extraction/capability_router.py
===========================================
Capability-based engine routing from deterministic feature evidence.

Routing philosophy
------------------
Docling is the default.  It is cheaper, faster, and sufficient for the majority
of documents, and it reads semantically-encoded structure (DOCX styles, HTML
tags, native text layers) directly.  MinerU is promoted only when deterministic
evidence proves the document has structural complexity Docling cannot
reconstruct correctly:

    - multi-column layout or floating text boxes  (reading order)
    - merged / nested / very wide tables          (grid reconstruction)
    - no usable native text layer                 (scanned pages → OCR/layout)

Absence of MinerU evidence is not ambiguity — it is a Docling confirmation.
There is no probabilistic adjudicator in this path: every decision is a function
of structural facts extracted in Stage 1, so the same document always routes the
same way and the reason string names the exact signal that fired.
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
from .models import DocumentFeatureProfile

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


class CapabilityBasedEngineRouter:
    """
    Choose the cheapest sufficient structure engine from explicit capabilities.

    The router is conservative and deterministic.  It honours a forced config
    override, removes unsupported engines, promotes to MinerU only on hard
    structural evidence, and otherwise confirms Docling.
    """

    def __init__(self, routing_config: EngineRoutingConfig | None = None) -> None:
        self._routing_config = routing_config

    def route(self, profile: DocumentFeatureProfile) -> EngineClassification:
        """Return an EngineClassification based on feature and capability evidence."""
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
        """Honor explicit conversion_engine overrides from settings.yaml."""
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
        """Raise when a forced engine cannot process this document format."""
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
    Return a human-readable reason to promote to MinerU, or None for Docling.

    Only structural complexity promotes.  Visual/figure signals are intentionally
    excluded — they are a Stage 3 concern, not an engine-choice signal.
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
    """Build an EngineClassification for capability-based routing."""
    return EngineClassification(
        engine=engine,
        backend=backend,
        # Capability routing is rule-based; it does not compute a numeric score.
        complexity_score=0.0,
        confidence=confidence,
        reason=reason,
    )
