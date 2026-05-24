"""
doc_feature_extraction/engine_needs_evaluator.py
=================================================
Translate extracted document evidence into the processing capabilities the
conversion engine must provide.

Evidence (counts, candidate lists) goes in.  A ``DocumentRequirements`` object
— boolean flags that tell the router what the document needs — comes out.  This
is not the final routing decision; it only makes needs visible so the capability
router can filter and score engines accordingly.
"""

from __future__ import annotations

from ...contracts.configurations.pipeline_config import EngineNeedsEvaluatorConfig
from .models import (
    DocumentRequirements,
    TableEvidence,
    TextEvidence,
    VisualCandidate,
    VisualCandidateKind,
    VisualEvidence,
)
from .text_patterns import contains_figure_caption


def infer_requirements(
    *,
    text: TextEvidence,
    tables: TableEvidence,
    visuals: VisualEvidence,
    visual_candidates: list[VisualCandidate],
    settings: EngineNeedsEvaluatorConfig | None = None,
) -> DocumentRequirements:
    """
    Evaluate what processing capabilities the conversion engine must provide.

    Thresholds are intentionally low and conservative — this is not the final
    engine classifier.  The goal is to expose requirements and make visual
    semantic needs visible *before* routing, so the capability router can filter
    and score engines with full information.

    ``settings`` comes from
    ``document_feature_extraction.engine_needs_evaluator`` in ``settings.yaml``.
    Defaults are used when no config is supplied (e.g. in tests).
    """
    evaluator_settings = settings or EngineNeedsEvaluatorConfig()
    rationale: list[str] = []

    needs_table_reconstruction = tables.count > 0
    if needs_table_reconstruction:
        rationale.append(f"{tables.count} table candidate(s) detected")

    needs_visual_asset_extraction = (
        visuals.embedded_image_count
        + visuals.vector_graphics_count
        + visuals.chart_count
        + visuals.svg_count
    ) > 0
    if needs_visual_asset_extraction:
        rationale.append("non-text visual objects detected")

    needs_visual_semantic_explanation = (
        visuals.large_embedded_image_count > 0
        or visuals.chart_count > 0
        or visuals.svg_count > 0
        or any(
            _is_meaningful_visual_candidate(candidate, evaluator_settings)
            for candidate in visual_candidates
        )
    )
    if needs_visual_semantic_explanation:
        rationale.append("candidate visuals may carry document meaning beyond OCR text")

    needs_local_vlm_adjudication = bool(visual_candidates) and needs_visual_semantic_explanation
    if needs_local_vlm_adjudication:
        rationale.append("send selected visual candidates to local Qwen/Ollama for adjudication")

    return DocumentRequirements(
        needs_text_extraction=text.native_text_available,
        needs_table_reconstruction=needs_table_reconstruction,
        needs_visual_asset_extraction=needs_visual_asset_extraction,
        needs_visual_semantic_explanation=needs_visual_semantic_explanation,
        needs_local_vlm_adjudication=needs_local_vlm_adjudication,
        rationale=rationale,
    )


def _is_meaningful_visual_candidate(
    candidate: VisualCandidate,
    settings: EngineNeedsEvaluatorConfig,
) -> bool:
    """
    Return True when a visual candidate is worth routing to a vision model.

    The filter has two thresholds from ``settings.yaml``:

    ``meaningful_visual_area_ratio`` — anything below this fraction of page/slide
    area is considered "small".  Small visuals are often logos, bullet icons, or
    decorative dividers that do not carry clinical meaning.

    ``decorative_image_terms`` — words in the candidate's alt text or nearby
    caption that strongly suggest decoration.  Examples: "logo", "icon", "footer".

    The filter skips a candidate only when BOTH conditions are met: it is small
    AND its label contains a decorative term.  Either condition alone is not
    enough — a large image labelled "company logo" may still carry a clinical
    figure inside it, and a tiny uncaptioned image is still passed through
    conservatively.

    Structural kinds (CHART, SVG, SLIDE_VISUAL_CLUSTER) always pass — they are
    never decorative by nature.
    """
    text_hint = " ".join(
        part for part in (candidate.caption_or_alt_text, candidate.nearby_text) if part
    ).lower()

    is_small = (
        candidate.area_ratio is not None
        and candidate.area_ratio < settings.meaningful_visual_area_ratio
    )

    # Small + explicitly decorative label → skip to avoid routing noise.
    if is_small and any(term in text_hint for term in settings.decorative_image_terms):
        return False

    if contains_figure_caption(text_hint):
        return True
    if candidate.nearby_text and not is_small:
        return True
    if candidate.area_ratio is not None and candidate.area_ratio >= settings.meaningful_visual_area_ratio:
        return True

    # These structural kinds are never decorative — always worth inspecting.
    return candidate.kind in {
        VisualCandidateKind.CHART,
        VisualCandidateKind.SVG,
        VisualCandidateKind.SLIDE_VISUAL_CLUSTER,
    }
