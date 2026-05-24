"""
stage1_document_prescanning/document_complexity_classifier.py
==============================================================
Module 3 of Stage 1: map page profiles to an engine routing decision.

Responsibility
--------------
Receive a list of ``PageProfile`` objects (one per page) and the engine-routing
configuration from ``settings.yaml``, and produce a single ``EngineClassification``
that tells Stage 2 which extraction engine to use and at what confidence level.

The complexity formula
----------------------
For each page, check four Boolean flags.  Sum the weighted counts, then divide
by the total page count to normalise (so a 10-page and 500-page document with
the same *proportion* of complex pages receive the same score):

    score = (
        count(is_multi_column)   × weight_multi_column_page
      + count(has_diagrams)      × weight_diagram_heavy_page
      + count(has_large_tables)  × weight_large_table_page
      + count(low_text_density)  × weight_low_text_density_page
    ) / total_pages

``low_text_density`` is a *derived* flag not stored on PageProfile — it is True
when ``page.text_density < LOW_TEXT_DENSITY_THRESHOLD`` (0.02 chars/mm² by default,
from the architecture spec).

Decision boundaries (configurable in settings.yaml)
----------------------------------------------------
    score >= complexity_threshold_complex  (default 2.0)  →  MinerU  + backend AUTO
    score >= complexity_threshold_moderate (default 0.5)  →  MinerU  + backend AUTO
    score <  complexity_threshold_moderate                 →  Docling + no backend

Confidence
----------
Confidence measures how far the score is from the nearest decision boundary,
normalised so that a score right at a boundary yields ≈ 0 and a score well
within its band yields → 1.

    For COMPLEX / SIMPLE zones:  normalised_distance = |score - nearest_boundary|
                                                        / nearest_boundary
    For MODERATE zone:           normalised_distance = distance_to_nearest_boundary
                                                        / half-band-width

    confidence = tanh(2 × normalised_distance)

This gives:
  score 3.25  (COMPLEX,   distance 1.25, threshold 2.0):  ≈ 0.85
  score 1.98  (borderline COMPLEX/MODERATE):               ≈ 0.05  (low — uncertain)
  score 0.10  (SIMPLE,    distance 0.40, threshold 0.5):  ≈ 0.92

Forced engine mode
------------------
When ``engine_routing.conversion_engine`` is not ``auto``, the classifier is
skipped.  It returns a fixed ``EngineClassification`` with ``complexity_score=0.0``,
``confidence=1.0``, and a reason that names the setting that forced the choice.
The orchestrator still resolves ``backend=AUTO`` at engine-startup time.
"""

from __future__ import annotations

import math

from ..contracts.configurations.pipeline_config import (
    ConversionEngineChoice,
    EngineRoutingConfig,
)
from ..contracts.exceptions import ConfigurationError
from ..contracts.pipeline_domain_types import (
    EngineClassification,
    ExtractionEngine,
    MinerUBackend,
    PageProfile,
)

# Pages whose text_density is below this threshold contribute the
# ``low_text_density_page`` weight to the complexity score.
# Expressed in chars/mm² — see document_page_structure_scanner.py for the
# definition and calibration of text_density.
_LOW_TEXT_DENSITY_THRESHOLD: float = 0.02


class DocumentComplexityClassifier:
    """
    Maps a list of ``PageProfile`` objects to an ``EngineClassification``.

    Instantiate with the engine-routing section of the pipeline config::

        classifier = DocumentComplexityClassifier(config.engine_routing)
        decision = classifier.classify(profiles)
        # decision.engine           → ExtractionEngine.MINERU
        # decision.complexity_score → 3.25
        # decision.confidence       → 0.85
        # decision.reason           → "40 % multi-column, 25 % diagram-heavy → MinerU VLM"
    """

    def __init__(self, routing_config: EngineRoutingConfig) -> None:
        self._config = routing_config
        self._validate_config()

    def classify(self, profiles: list[PageProfile]) -> EngineClassification:
        """
        Produce a routing decision for the document described by *profiles*.

        Args:
            profiles: Output of ``DocumentPageStructureScanner.scan()``.
                      May be empty (zero-page document).

        Returns:
            ``EngineClassification`` ready to be stored in the checkpoint and
            handed to the Stage 2 orchestrator.

        Raises:
            ConfigurationError: Threshold values in settings.yaml are invalid
                                 (caught earlier by _validate_config, but
                                  kept here as a safety net).
        """
        # Forced engine: skip classification entirely.
        forced = self._config.conversion_engine
        if forced == ConversionEngineChoice.DOCLING:
            return EngineClassification(
                engine=ExtractionEngine.DOCLING,
                backend=None,
                complexity_score=0.0,
                confidence=1.0,
                reason="forced by configuration (conversion_engine = docling)",
            )
        if forced == ConversionEngineChoice.MINERU:
            return EngineClassification(
                engine=ExtractionEngine.MINERU,
                backend=MinerUBackend.AUTO,
                complexity_score=0.0,
                confidence=1.0,
                reason="forced by configuration (conversion_engine = mineru)",
            )

        # Auto mode: run the heuristic classifier.
        if not profiles:
            # Zero-page document — route to Docling (fast, safe fallback).
            return EngineClassification(
                engine=ExtractionEngine.DOCLING,
                backend=None,
                complexity_score=0.0,
                confidence=0.0,
                reason="empty document — zero pages detected; defaulting to Docling",
            )

        return self._classify_from_profiles(profiles)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _classify_from_profiles(self, profiles: list[PageProfile]) -> EngineClassification:
        """Compute score, pick engine, compute confidence, build reason string."""
        weights = self._config.complexity_weights
        total = len(profiles)

        # Tally flag counts across all pages.
        n_multi_column = sum(1 for p in profiles if p.is_multi_column)
        n_diagram = sum(1 for p in profiles if p.has_diagrams)
        n_large_table = sum(1 for p in profiles if p.has_large_tables)
        n_low_density = sum(1 for p in profiles if p.text_density < _LOW_TEXT_DENSITY_THRESHOLD)

        raw_score = (
            n_multi_column * weights.multi_column_page
            + n_diagram * weights.diagram_heavy_page
            + n_large_table * weights.large_table_page
            + n_low_density * weights.low_text_density_page
        )
        complexity_score = raw_score / total

        threshold_complex = self._config.complexity_threshold_complex
        threshold_moderate = self._config.complexity_threshold_moderate

        # Engine + backend selection.
        if complexity_score >= threshold_complex:
            engine = ExtractionEngine.MINERU
            backend = MinerUBackend.AUTO  # orchestrator resolves to VLM if GPU available
        elif complexity_score >= threshold_moderate:
            engine = ExtractionEngine.MINERU
            backend = MinerUBackend.AUTO  # orchestrator resolves to PIPELINE (CPU)
        else:
            engine = ExtractionEngine.DOCLING
            backend = None

        confidence = _compute_confidence(complexity_score, threshold_moderate, threshold_complex)
        reason = _build_reason(
            complexity_score=complexity_score,
            total_pages=total,
            n_multi_column=n_multi_column,
            n_diagram=n_diagram,
            n_large_table=n_large_table,
            n_low_density=n_low_density,
            engine=engine,
            threshold_complex=threshold_complex,
            threshold_moderate=threshold_moderate,
        )

        return EngineClassification(
            engine=engine,
            backend=backend,
            complexity_score=complexity_score,
            confidence=confidence,
            reason=reason,
        )

    def _validate_config(self) -> None:
        """
        Catch impossible threshold configurations early.

        The model_validator on PipelineConfig already checks this, but if the
        classifier is ever constructed with a standalone EngineRoutingConfig
        (e.g., in a unit test), this guard provides a safety net.
        """
        er = self._config
        if er.complexity_threshold_complex <= er.complexity_threshold_moderate:
            raise ConfigurationError(
                f"complexity_threshold_complex ({er.complexity_threshold_complex}) "
                f"must be strictly greater than complexity_threshold_moderate "
                f"({er.complexity_threshold_moderate})",
                context={
                    "complexity_threshold_complex": er.complexity_threshold_complex,
                    "complexity_threshold_moderate": er.complexity_threshold_moderate,
                },
            )


# ---------------------------------------------------------------------------
# Pure functions — no external state
# ---------------------------------------------------------------------------


def _compute_confidence(
    score: float,
    threshold_moderate: float,
    threshold_complex: float,
) -> float:
    """
    Map a complexity score to a classifier confidence in [0, 1].

    Confidence represents how far the score is from the nearest decision
    boundary.  A score right at a boundary has confidence ≈ 0 (the decision
    could go either way).  A score deep inside its band has confidence → 1.

    Formula:
        normalised_distance = |score - nearest_boundary| / reference_distance
        confidence = tanh(2 × normalised_distance)

    The reference distance is chosen per zone so that confidence scales
    intuitively relative to the band it is in.

    Args:
        score: Computed complexity score (≥ 0).
        threshold_moderate: Lower boundary between SIMPLE and MODERATE bands.
        threshold_complex:  Lower boundary between MODERATE and COMPLEX bands.

    Returns:
        Float in [0.0, 1.0].
    """
    if score >= threshold_complex:
        # COMPLEX zone: distance from the complex threshold, normalised by the
        # threshold value itself so that a 2× score gives high confidence.
        norm_dist = (score - threshold_complex) / max(threshold_complex, 1e-9)

    elif score >= threshold_moderate:
        # MODERATE zone: distance from the nearest boundary, normalised by
        # half the band width so that the midpoint of the band gives ≈ 0.76.
        half_band = (threshold_complex - threshold_moderate) / 2.0
        dist_to_nearest = min(score - threshold_moderate, threshold_complex - score)
        norm_dist = dist_to_nearest / max(half_band, 1e-9)

    else:
        # SIMPLE zone: distance below the moderate threshold, normalised by
        # the threshold value so that score=0 gives maximum confidence.
        norm_dist = (threshold_moderate - score) / max(threshold_moderate, 1e-9)

    return float(min(max(math.tanh(2.0 * norm_dist), 0.0), 1.0))


def _build_reason(
    *,
    complexity_score: float,
    total_pages: int,
    n_multi_column: int,
    n_diagram: int,
    n_large_table: int,
    n_low_density: int,
    engine: ExtractionEngine,
    threshold_complex: float,
    threshold_moderate: float,
) -> str:
    """
    Build a human-readable explanation for the routing decision.

    The reason is logged at pipeline startup and stored in the checkpoint.
    It is designed to be actionable: a developer reading the logs can see
    exactly which page features drove the score and why.
    """
    def pct(count: int) -> str:
        return f"{count / max(total_pages, 1) * 100:.0f}%"

    # Collect the dominant features (those that scored any weight points).
    features: list[str] = []
    if n_multi_column:
        features.append(f"{pct(n_multi_column)} multi-column pages")
    if n_diagram:
        features.append(f"{pct(n_diagram)} diagram-heavy pages")
    if n_large_table:
        features.append(f"{pct(n_large_table)} large-table pages")
    if n_low_density:
        features.append(f"{pct(n_low_density)} low-density pages")

    feature_summary = ", ".join(features) if features else "no complex features detected"

    if engine == ExtractionEngine.MINERU:
        if complexity_score >= threshold_complex:
            engine_label = "MinerU (VLM backend if GPU available)"
        else:
            engine_label = "MinerU (pipeline backend, CPU)"
    else:
        engine_label = "Docling"

    return (
        f"complexity_score={complexity_score:.2f} "
        f"(threshold_complex={threshold_complex}, threshold_moderate={threshold_moderate}); "
        f"{feature_summary} → {engine_label}"
    )
