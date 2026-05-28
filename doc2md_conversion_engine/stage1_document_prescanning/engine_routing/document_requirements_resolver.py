"""
stage1_document_prescanning/engine_routing/document_requirements_resolver.py
============================================================================
Stage 1 · Step 3 of 3 (part 1) — turn raw evidence into plain yes/no needs.

The routing policy does not want to reason about raw numbers like "135 tables"
or "column_count = 2". It wants simple answers: "does this document need its
reading order rebuilt? yes/no". This file is the translator that produces those
answers.

Measured evidence goes in (text, tables, layout, visuals). A
``DocumentRequirements`` object comes out — a small set of true/false flags. This
is NOT the final engine choice; it just makes the document's needs explicit so
the policy in ``engine_routing_policy.py`` can act on them.

Which needs actually affect the engine choice
----------------------------------------------
Only three of the flags can push a document toward MinerU, and each one
describes structure that a simple, flow-by-flow reader would reconstruct wrongly:

    needs_reading_order_reconstruction   text is not in one simple column
    needs_complex_table_reconstruction   tables are merged / nested / very wide
    needs_ocr_text_recovery              there is no real text layer to read

Two more flags are computed here but deliberately do NOT affect routing:
``needs_visual_asset_extraction`` and ``needs_visual_semantic_explanation``.
A figure that should later get a written summary is a job for Stage 3, not a
reason to choose a heavier conversion engine now. They are recorded so later
stages can use them.
"""

from __future__ import annotations

from ...contracts.configurations.pipeline_config import EngineNeedsEvaluatorConfig
from ..feature_extraction.feature_evidence_models import (
    DocumentRequirements,
    LayoutEvidence,
    TableEvidence,
    TextEvidence,
    VisualCandidate,
    VisualCandidateKind,
    VisualEvidence,
)
from ..feature_extraction.visual_caption_detector import contains_figure_caption


def resolve_document_requirements(
    *,
    text: TextEvidence,
    tables: TableEvidence,
    layout: LayoutEvidence,
    visuals: VisualEvidence,
    visual_candidates: list[VisualCandidate],
    settings: EngineNeedsEvaluatorConfig | None = None,
) -> DocumentRequirements:
    """
    Work out what the conversion engine will need to handle this document.

    Reads each kind of evidence and sets one plain true/false flag per need,
    while also collecting a short human-readable note for every flag that turns
    true (the ``rationale`` list), so the decision can be explained later.

    The thresholds that decide "how wide is too wide for a table?" and similar
    come from the ``engine_needs_evaluator`` section of ``settings.yaml``; sane
    defaults are used when no config is passed in.
    """
    evaluator_settings = settings or EngineNeedsEvaluatorConfig()
    rationale: list[str] = []

    # -- Routing signal: native text layer ---------------------------------
    needs_ocr_text_recovery = not text.native_text_available
    if needs_ocr_text_recovery:
        rationale.append("no usable native text layer — OCR/layout recovery required")

    # -- Routing signal: reading order -------------------------------------
    needs_reading_order_reconstruction = (
        layout.column_count >= 2 or layout.has_floating_text_boxes
    )
    if needs_reading_order_reconstruction:
        rationale.append(
            f"non-linear layout (columns={layout.column_count}, "
            f"floating_text_boxes={layout.has_floating_text_boxes})"
        )

    # -- Routing signal: table structure -----------------------------------
    needs_table_reconstruction = tables.count > 0
    if needs_table_reconstruction:
        rationale.append(f"{tables.count} table candidate(s) detected")

    needs_complex_table_reconstruction = (
        tables.has_merged_cells
        or tables.has_nested_tables
        or tables.max_column_count > evaluator_settings.wide_table_max_simple_columns
    )
    if needs_complex_table_reconstruction:
        rationale.append(
            f"structurally complex table(s) (merged={tables.has_merged_cells}, "
            f"nested={tables.has_nested_tables}, max_columns={tables.max_column_count})"
        )

    # -- Downstream signal: visual asset extraction (not routing) ----------
    needs_visual_asset_extraction = (
        visuals.embedded_image_count
        + visuals.vector_graphics_count
        + visuals.chart_count
        + visuals.svg_count
    ) > 0
    if needs_visual_asset_extraction:
        rationale.append("non-text visual objects detected")

    # -- Downstream signal: figure summarization (Stage 3, not routing) ----
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
        rationale.append("candidate visuals may carry meaning beyond extracted text (Stage 3)")

    return DocumentRequirements(
        # Every document needs its text extracted — this is always True.  Whether
        # a native text layer exists or OCR is required is a separate concern,
        # carried by needs_ocr_text_recovery; conflating the two here previously
        # flipped this flag to False exactly when text recovery mattered most.
        needs_text_extraction=True,
        needs_ocr_text_recovery=needs_ocr_text_recovery,
        needs_reading_order_reconstruction=needs_reading_order_reconstruction,
        needs_table_reconstruction=needs_table_reconstruction,
        needs_complex_table_reconstruction=needs_complex_table_reconstruction,
        needs_visual_asset_extraction=needs_visual_asset_extraction,
        needs_visual_semantic_explanation=needs_visual_semantic_explanation,
        rationale=rationale,
    )


def _is_meaningful_visual_candidate(
    candidate: VisualCandidate,
    settings: EngineNeedsEvaluatorConfig,
) -> bool:
    """
    Return True when a visual candidate is worth flagging for Stage 3 review.

    The filter has two thresholds from ``settings.yaml``:

    ``meaningful_visual_area_ratio`` — anything below this fraction of page/slide
    area is considered "small".  Small visuals are often logos, bullet icons, or
    decorative dividers that do not carry clinical meaning.

    ``decorative_image_terms`` — words in the candidate's alt text or nearby
    caption that strongly suggest decoration.  Examples: "logo", "icon", "footer".

    A candidate is skipped only when BOTH conditions are met: it is small AND its
    label contains a decorative term.  Either condition alone is not enough — a
    large image labelled "company logo" may still carry a clinical figure inside
    it, and a tiny uncaptioned image is still passed through conservatively.

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
