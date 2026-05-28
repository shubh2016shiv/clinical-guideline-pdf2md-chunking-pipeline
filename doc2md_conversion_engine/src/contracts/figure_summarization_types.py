"""
contracts/figure_summarization_types.py
========================================
Domain value objects produced by Stage 3 (figure summarization).

These types are the **shared language** between Stage 3 (which produces
summaries) and Stage 4 (which substitutes them back into the document).  They
live in ``contracts`` so neither stage imports the other — both depend only on
this stable contract.

What ``FigureSummary`` is
-------------------------
A faithful, insertion-ready piece of Markdown that stands in for a figure
image, plus the metadata Stage 4 needs to make routing decisions:

* ``markdown_result``     — the text Stage 4 splices into the document.
* ``figure_type`` / ``rendering_strategy`` — the structural read of the
  figure (forest plot, flowchart, decision algorithm, ...); useful for
  selecting downstream rendering and for diagnostics.
* ``is_informative``      — ``False`` for stock photos / logos.  Stage 4
  drops the token entirely instead of pasting noise.
* ``legibility`` + ``confidence`` — trust signals.  Low-confidence /
  poor-legibility summaries are kept but flagged in metrics so a reviewer
  can spot figures the VLM struggled with.

Why an enum hierarchy (not free-text)?
--------------------------------------
Free-text categories make routing logic in Stage 4 brittle.  Constraining
``figure_type`` to a closed enum + validating ``rendering_strategy`` against
``ALLOWED_RENDERING_STRATEGIES_BY_FIGURE_TYPE`` means an invalid model
response is caught at the Stage 3 boundary, never propagates downstream, and
triggers a corrective retry with the validation error attached to the prompt.

The validation matrix here is the same one developed against real clinical
PDF samples in ``ollama_qwen_image_summary_check.py`` — kept identical so the
prompt-driven retry loop, the JSON schema, and Stage 4's consumers all speak
exactly one vocabulary.
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enums — the closed vocabulary
# ---------------------------------------------------------------------------


class FigureType(str, Enum):
    """
    Structural categories of figures that can appear in any PDF.

    Grouped by broad category for readability; groupings have no semantic
    weight in validation.  ``DECORATIVE`` is special — it signals the figure
    carries no informational content (logos, stock photos) and must be paired
    with ``is_informative=False``.
    """

    # --- Algorithmic / formal notation ---
    DECISION_ALGORITHM = "decision_algorithm"
    CODE_OR_PSEUDOCODE = "code_or_pseudocode"
    UML_DIAGRAM = "uml_diagram"
    ARCHITECTURE_DIAGRAM = "architecture_diagram"

    # --- Data / quantitative ---
    DATA_TABLE = "data_table"
    STATISTICAL_PLOT = "statistical_plot"
    CHART = "chart"
    MATHEMATICAL_EXPRESSION = "mathematical_expression"

    # --- Process / structure ---
    PROCESS_OR_WORKFLOW = "process_or_workflow"
    TIMELINE = "timeline"
    CONCEPTUAL_DIAGRAM = "conceptual_diagram"
    MIND_MAP = "mind_map"
    VENN_OR_SET_DIAGRAM = "venn_or_set_diagram"

    # --- Domain-enriched / visual ---
    CLINICAL_ACTION_MAP = "clinical_action_map"
    INFOGRAPHIC = "infographic"
    ILLUSTRATION = "illustration"
    SCREENSHOT_OR_UI = "screenshot_or_ui"
    MAP = "map"

    # --- Non-informative ---
    DECORATIVE = "decorative"
    OTHER = "other"


class RenderingStrategy(str, Enum):
    """
    Markdown rendering approach used in ``markdown_result``.

    Each strategy must be paired with a ``FigureType`` it is appropriate for;
    the mapping is enforced by ``ALLOWED_RENDERING_STRATEGIES_BY_FIGURE_TYPE``.
    A forest plot rendered as a fenced code block is not a valid combination.
    """

    FENCED_CODE_BLOCK = "fenced_code_block"
    LATEX_MATH_WITH_EXPLANATION = "latex_math_with_explanation"
    MERMAID_DIAGRAM_WITH_EXPLANATION = "mermaid_diagram_with_explanation"

    ASCII_FLOW_DIAGRAM_WITH_EXPLANATION = "ascii_flow_diagram_with_explanation"
    HIERARCHICAL_BULLETS_WITH_EXPLANATION = "hierarchical_bullets_with_explanation"
    NUMBERED_STEPS_WITH_EXPLANATION = "numbered_steps_with_explanation"
    SET_OVERLAP_WITH_EXPLANATION = "set_overlap_with_explanation"

    MARKDOWN_TABLE = "markdown_table"
    MARKDOWN_TABLE_WITH_EXPLANATION = "markdown_table_with_explanation"
    TIMELINE_TABLE = "timeline_table"

    CHART_VALUES_WITH_EXPLANATION = "chart_values_with_explanation"
    STATISTICAL_PLOT_EXTRACTION = "statistical_plot_extraction"

    ILLUSTRATION_LABELS_WITH_EXPLANATION = "illustration_labels_with_explanation"
    UI_STRUCTURE_WITH_EXPLANATION = "ui_structure_with_explanation"

    PLAIN_TEXT_EXPLANATION = "plain_text_explanation"
    DECORATIVE_NOTE = "decorative_note"


class LegibilityLevel(str, Enum):
    """How clearly the figure content is readable in the supplied image."""

    CLEAR = "clear"
    PARTIAL = "partial"
    POOR = "poor"


class DocumentDomain(str, Enum):
    """
    Domain hint for the source PDF.

    ``AUTO`` is a *pipeline-level* sentinel: it tells the prompt builder to
    let the model infer the domain from visual context.  ``AUTO`` must never
    appear in model output — only the concrete domains may — which is
    enforced by ``FigureSummary.document_domain``'s field validator.
    """

    AUTO = "auto"
    CLINICAL = "clinical"
    SOFTWARE = "software"
    SCIENTIFIC = "scientific"
    FINANCIAL = "financial"
    ENGINEERING = "engineering"
    LEGAL = "legal"
    EDUCATIONAL = "educational"


# ---------------------------------------------------------------------------
# Validation matrix — which rendering strategies are valid for which type
# ---------------------------------------------------------------------------


ALLOWED_RENDERING_STRATEGIES_BY_FIGURE_TYPE: Final[
    dict[FigureType, frozenset[RenderingStrategy]]
] = {
    FigureType.DECISION_ALGORITHM: frozenset({
        RenderingStrategy.ASCII_FLOW_DIAGRAM_WITH_EXPLANATION,
        RenderingStrategy.MERMAID_DIAGRAM_WITH_EXPLANATION,
        RenderingStrategy.HIERARCHICAL_BULLETS_WITH_EXPLANATION,
        RenderingStrategy.MARKDOWN_TABLE_WITH_EXPLANATION,
    }),
    FigureType.CODE_OR_PSEUDOCODE: frozenset({RenderingStrategy.FENCED_CODE_BLOCK}),
    FigureType.UML_DIAGRAM: frozenset({
        RenderingStrategy.MERMAID_DIAGRAM_WITH_EXPLANATION,
        RenderingStrategy.ASCII_FLOW_DIAGRAM_WITH_EXPLANATION,
        RenderingStrategy.PLAIN_TEXT_EXPLANATION,
    }),
    FigureType.ARCHITECTURE_DIAGRAM: frozenset({
        RenderingStrategy.ASCII_FLOW_DIAGRAM_WITH_EXPLANATION,
        RenderingStrategy.MERMAID_DIAGRAM_WITH_EXPLANATION,
        RenderingStrategy.HIERARCHICAL_BULLETS_WITH_EXPLANATION,
        RenderingStrategy.PLAIN_TEXT_EXPLANATION,
    }),
    FigureType.DATA_TABLE: frozenset({
        RenderingStrategy.MARKDOWN_TABLE,
        RenderingStrategy.MARKDOWN_TABLE_WITH_EXPLANATION,
    }),
    FigureType.STATISTICAL_PLOT: frozenset({
        RenderingStrategy.STATISTICAL_PLOT_EXTRACTION,
        RenderingStrategy.CHART_VALUES_WITH_EXPLANATION,
    }),
    FigureType.CHART: frozenset({
        RenderingStrategy.CHART_VALUES_WITH_EXPLANATION,
        RenderingStrategy.MARKDOWN_TABLE_WITH_EXPLANATION,
        RenderingStrategy.PLAIN_TEXT_EXPLANATION,
    }),
    FigureType.MATHEMATICAL_EXPRESSION: frozenset({
        RenderingStrategy.LATEX_MATH_WITH_EXPLANATION,
        RenderingStrategy.PLAIN_TEXT_EXPLANATION,
    }),
    FigureType.PROCESS_OR_WORKFLOW: frozenset({
        RenderingStrategy.NUMBERED_STEPS_WITH_EXPLANATION,
        RenderingStrategy.ASCII_FLOW_DIAGRAM_WITH_EXPLANATION,
        RenderingStrategy.MERMAID_DIAGRAM_WITH_EXPLANATION,
        RenderingStrategy.MARKDOWN_TABLE_WITH_EXPLANATION,
    }),
    FigureType.TIMELINE: frozenset({
        RenderingStrategy.TIMELINE_TABLE,
        RenderingStrategy.NUMBERED_STEPS_WITH_EXPLANATION,
        RenderingStrategy.MARKDOWN_TABLE_WITH_EXPLANATION,
    }),
    FigureType.CONCEPTUAL_DIAGRAM: frozenset({
        RenderingStrategy.HIERARCHICAL_BULLETS_WITH_EXPLANATION,
        RenderingStrategy.ASCII_FLOW_DIAGRAM_WITH_EXPLANATION,
        RenderingStrategy.PLAIN_TEXT_EXPLANATION,
    }),
    FigureType.MIND_MAP: frozenset({
        RenderingStrategy.HIERARCHICAL_BULLETS_WITH_EXPLANATION,
        RenderingStrategy.PLAIN_TEXT_EXPLANATION,
    }),
    FigureType.VENN_OR_SET_DIAGRAM: frozenset({
        RenderingStrategy.SET_OVERLAP_WITH_EXPLANATION,
        RenderingStrategy.HIERARCHICAL_BULLETS_WITH_EXPLANATION,
        RenderingStrategy.PLAIN_TEXT_EXPLANATION,
    }),
    FigureType.CLINICAL_ACTION_MAP: frozenset({
        RenderingStrategy.MARKDOWN_TABLE_WITH_EXPLANATION,
        RenderingStrategy.HIERARCHICAL_BULLETS_WITH_EXPLANATION,
        RenderingStrategy.ASCII_FLOW_DIAGRAM_WITH_EXPLANATION,
    }),
    FigureType.INFOGRAPHIC: frozenset({
        RenderingStrategy.HIERARCHICAL_BULLETS_WITH_EXPLANATION,
        RenderingStrategy.MARKDOWN_TABLE_WITH_EXPLANATION,
        RenderingStrategy.PLAIN_TEXT_EXPLANATION,
    }),
    FigureType.ILLUSTRATION: frozenset({
        RenderingStrategy.ILLUSTRATION_LABELS_WITH_EXPLANATION,
        RenderingStrategy.PLAIN_TEXT_EXPLANATION,
    }),
    FigureType.SCREENSHOT_OR_UI: frozenset({
        RenderingStrategy.UI_STRUCTURE_WITH_EXPLANATION,
        RenderingStrategy.PLAIN_TEXT_EXPLANATION,
    }),
    FigureType.MAP: frozenset({
        RenderingStrategy.PLAIN_TEXT_EXPLANATION,
        RenderingStrategy.HIERARCHICAL_BULLETS_WITH_EXPLANATION,
    }),
    FigureType.DECORATIVE: frozenset({RenderingStrategy.DECORATIVE_NOTE}),
    FigureType.OTHER: frozenset({
        RenderingStrategy.PLAIN_TEXT_EXPLANATION,
        RenderingStrategy.HIERARCHICAL_BULLETS_WITH_EXPLANATION,
        RenderingStrategy.MARKDOWN_TABLE_WITH_EXPLANATION,
        RenderingStrategy.FENCED_CODE_BLOCK,
    }),
}


# Domains the model is allowed to output (excludes the pipeline-only ``AUTO``).
_MODEL_INFERRABLE_DOCUMENT_DOMAINS: Final[list[str]] = [
    domain.value for domain in DocumentDomain if domain != DocumentDomain.AUTO
]


# JSON Schema passed to Ollama's structured-output engine via ``format=``.
# Defined once, here, so the schema and the Pydantic contract cannot drift.
FIGURE_SUMMARY_JSON_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "figure_type": {
            "type": "string",
            "enum": [t.value for t in FigureType],
            "description": "Structural category of the figure.",
        },
        "rendering_strategy": {
            "type": "string",
            "enum": [s.value for s in RenderingStrategy],
            "description": "Markdown rendering approach used in markdown_result.",
        },
        "is_informative": {
            "type": "boolean",
            "description": "False only for decorative figures that carry no content.",
        },
        "markdown_result": {
            "type": "string",
            "description": (
                "Insertion-ready Markdown that structurally represents the figure. "
                "Must not be empty.  Must not contain JSON or pipeline metadata."
            ),
        },
        "legibility": {
            "type": "string",
            "enum": [level.value for level in LegibilityLevel],
            "description": "How clearly the figure content is readable in the image.",
        },
        "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "description": "Model self-assessed confidence in [0,1].",
        },
        "document_domain": {
            "type": "string",
            "enum": _MODEL_INFERRABLE_DOCUMENT_DOMAINS,
            "description": "Domain inferred or confirmed from visual context.",
        },
    },
    "required": [
        "figure_type",
        "rendering_strategy",
        "is_informative",
        "markdown_result",
        "legibility",
        "confidence",
        "document_domain",
    ],
}


# ---------------------------------------------------------------------------
# FigureSummary — the Stage 3 output contract
# ---------------------------------------------------------------------------


class FigureSummary(BaseModel):
    """
    The validated structured output of one VLM call, plus the token it belongs to.

    The vision model emits the seven core fields (see JSON schema above).  The
    Stage 3 orchestrator attaches ``token`` — the deterministic position
    identity from Stage 2 — and persists the result under that key.  Stage 4
    looks up ``${FIG:...}`` placeholders against the persisted store.

    Frozen so a summary, once produced, cannot be mutated by downstream code.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    token: str = Field(
        ...,
        description=(
            "The ``${FIG:<job>:<page>:<index>}`` placeholder this summary "
            "resolves.  Attached by the Stage 3 orchestrator after the VLM "
            "returns — the model itself never generates this field."
        ),
    )

    figure_type: FigureType
    rendering_strategy: RenderingStrategy
    is_informative: bool
    markdown_result: str = Field(
        ...,
        min_length=1,
        description=(
            "Insertion-ready Markdown.  Substituted verbatim by Stage 4 in "
            "place of the token (unless ``is_informative`` is False, in "
            "which case Stage 4 drops the token)."
        ),
    )
    legibility: LegibilityLevel
    confidence: float = Field(..., ge=0.0, le=1.0)
    document_domain: DocumentDomain

    # ------------------------------------------------------------------
    # Validators — cross-field consistency the JSON schema cannot express
    # ------------------------------------------------------------------

    @field_validator("token")
    @classmethod
    def _validate_token_format(cls, value: str) -> str:
        # Match the Stage 2 contract for figure tokens.  Reject malformed
        # tokens here so the summary store never accumulates orphan keys.
        if not (value.startswith("${FIG:") and value.endswith("}")):
            raise ValueError(
                f"FigureSummary.token must look like ${{FIG:<doc>:<page>:<index>}}, got {value!r}"
            )
        return value

    @field_validator("document_domain")
    @classmethod
    def _reject_auto_sentinel(cls, value: DocumentDomain) -> DocumentDomain:
        if value == DocumentDomain.AUTO:
            raise ValueError(
                "document_domain='auto' is a pipeline-only sentinel and must "
                "not appear in model output — the model must infer a concrete "
                "domain (e.g. 'clinical', 'software')."
            )
        return value

    @field_validator("markdown_result")
    @classmethod
    def _strip_and_require_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError(
                "markdown_result must not be empty or whitespace-only."
            )
        return stripped

    @model_validator(mode="after")
    def _validate_cross_field_consistency(self) -> FigureSummary:
        self._assert_finite_confidence()
        self._assert_decorative_constraints()
        self._assert_informative_for_non_decorative()
        self._assert_strategy_valid_for_type()
        return self

    def _assert_finite_confidence(self) -> None:
        if not math.isfinite(self.confidence):
            raise ValueError(f"confidence must be finite, got {self.confidence!r}.")

    def _assert_decorative_constraints(self) -> None:
        # A decorative figure carries no content — flag explicitly so Stage 4
        # can drop the token cleanly instead of inserting a paragraph.
        if self.figure_type != FigureType.DECORATIVE:
            return
        if self.is_informative:
            raise ValueError(
                "figure_type='decorative' requires is_informative=False."
            )
        if self.rendering_strategy != RenderingStrategy.DECORATIVE_NOTE:
            raise ValueError(
                "figure_type='decorative' must use rendering_strategy='decorative_note'."
            )

    def _assert_informative_for_non_decorative(self) -> None:
        if self.figure_type == FigureType.DECORATIVE:
            return
        if not self.is_informative:
            raise ValueError(
                f"figure_type={self.figure_type.value!r} is not decorative; "
                "is_informative must be True."
            )

    def _assert_strategy_valid_for_type(self) -> None:
        if (
            self.rendering_strategy == RenderingStrategy.DECORATIVE_NOTE
            and self.figure_type != FigureType.DECORATIVE
        ):
            raise ValueError(
                "rendering_strategy='decorative_note' is reserved for "
                "figure_type='decorative'."
            )
        allowed = ALLOWED_RENDERING_STRATEGIES_BY_FIGURE_TYPE.get(self.figure_type)
        if allowed and self.rendering_strategy not in allowed:
            allowed_csv = ", ".join(sorted(s.value for s in allowed))
            raise ValueError(
                f"rendering_strategy={self.rendering_strategy.value!r} is not "
                f"valid for figure_type={self.figure_type.value!r}. Allowed: {allowed_csv}."
            )
