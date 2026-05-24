"""
doc_feature_extraction/capability_router.py
===========================================
Capability-based engine routing from deterministic feature evidence.
"""

from __future__ import annotations

from ...contracts.configurations.pipeline_config import (
    ConversionEngineChoice,
    EngineRoutingConfig,
)
from ...contracts.pipeline_domain_types import (
    EngineClassification,
    ExtractionEngine,
    MinerUBackend,
)
from .models import DocumentFeatureProfile, OllamaVisualRoutingDecision

_VLM_CONFIDENCE_FLOOR = 0.65


class CapabilityBasedEngineRouter:
    """
    Choose the cheapest sufficient structure engine from explicit capabilities.

    This router is intentionally conservative.  It removes unsupported engines
    first, then promotes to MinerU only when deterministic evidence or a local
    VLM decision says the document likely needs layout/visual handling beyond a
    simple multi-format text extractor.
    """

    def __init__(self, routing_config: EngineRoutingConfig | None = None) -> None:
        self._routing_config = routing_config

    def route(
        self,
        profile: DocumentFeatureProfile,
        *,
        visual_decision: OllamaVisualRoutingDecision | None = None,
    ) -> EngineClassification:
        """Return an EngineClassification based on feature and capability evidence."""
        forced = self._forced_engine_classification()
        if forced is not None:
            return forced

        support = profile.format_support
        if support.docling_supported and not support.mineru_supported:
            return _classification(
                engine=ExtractionEngine.DOCLING,
                backend=None,
                confidence=0.95,
                reason="Docling selected because it is the only declared engine for this format.",
            )
        if support.mineru_supported and not support.docling_supported:
            return _classification(
                engine=ExtractionEngine.MINERU,
                backend=MinerUBackend.AUTO,
                confidence=0.95,
                reason="MinerU selected because it is the only declared engine for this format.",
            )

        if visual_decision is not None and visual_decision.confidence >= _VLM_CONFIDENCE_FLOOR:
            if (
                visual_decision.requires_visual_semantic_explanation
                or visual_decision.recommended_structure_engine == "mineru"
            ):
                return _classification(
                    engine=ExtractionEngine.MINERU,
                    backend=MinerUBackend.AUTO,
                    confidence=visual_decision.confidence,
                    reason=(
                        "MinerU selected from local Qwen/Ollama adjudication: "
                        "visual semantic explanation or stronger layout handling required."
                    ),
                )
            if visual_decision.recommended_structure_engine == "docling":
                return _classification(
                    engine=ExtractionEngine.DOCLING,
                    backend=None,
                    confidence=visual_decision.confidence,
                    reason="Docling selected from local Qwen/Ollama adjudication.",
                )

        req = profile.requirements
        if req.needs_visual_semantic_explanation and support.mineru_supported:
            return _classification(
                engine=ExtractionEngine.MINERU,
                backend=MinerUBackend.AUTO,
                confidence=0.70,
                reason=(
                    "MinerU selected because deterministic feature extraction found "
                    "meaningful visual candidates requiring semantic explanation."
                ),
            )
        if req.needs_table_reconstruction and profile.tables.large_count > 0 and support.mineru_supported:
            return _classification(
                engine=ExtractionEngine.MINERU,
                backend=MinerUBackend.AUTO,
                confidence=0.68,
                reason="MinerU selected because large table candidates were detected.",
            )

        return _classification(
            engine=ExtractionEngine.DOCLING,
            backend=None,
            confidence=0.80,
            reason="Docling selected as the cheapest declared engine satisfying extracted requirements.",
        )

    def _forced_engine_classification(self) -> EngineClassification | None:
        """Honor explicit conversion_engine overrides from settings.yaml."""
        if self._routing_config is None:
            return None
        forced = self._routing_config.conversion_engine
        if forced == ConversionEngineChoice.DOCLING:
            return _classification(
                engine=ExtractionEngine.DOCLING,
                backend=None,
                confidence=1.0,
                reason="forced by configuration (conversion_engine = docling)",
            )
        if forced == ConversionEngineChoice.MINERU:
            return _classification(
                engine=ExtractionEngine.MINERU,
                backend=MinerUBackend.AUTO,
                confidence=1.0,
                reason="forced by configuration (conversion_engine = mineru)",
            )
        return None


def _classification(
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
        complexity_score=0.0,
        confidence=confidence,
        reason=reason,
    )
