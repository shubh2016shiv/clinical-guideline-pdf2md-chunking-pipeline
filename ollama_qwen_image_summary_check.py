"""
figure_markdown_analyzer.py

Universal figure-to-Markdown analyzer for PDF documents of any domain and type.

Converts figure images extracted from any PDF into high-fidelity, insertion-ready
Markdown using a local vision-language model via Ollama. Output format mirrors the
figure's native structure — not a prose description of it:

  Code / pseudocode        →  Fenced code block  (```python, ```sql, ```text …)
  Flowchart / decision     →  Mermaid or ASCII diagram in fenced block
  UML diagram              →  Mermaid (classDiagram, sequenceDiagram, …)
  Mathematical equation    →  LaTeX display math  ($$…$$)
  Data table               →  Markdown table with all rows and columns
  Chart / graph            →  Values extracted into a Markdown table + commentary
  Statistical plot         →  Subgroups, point estimates, CIs, p-values extracted
  Step-by-step process     →  Numbered Markdown list
  Timeline / Gantt         →  Date-keyed Markdown table
  Conceptual hierarchy     →  Indented bullet structure
  Venn / set diagram       →  Set members and overlaps enumerated
  Illustration             →  Visible labels and annotations listed
  UI screenshot            →  Panel/control hierarchy as indented bullets

Design principles
-----------------
- Structural fidelity:  output mirrors the figure's native representation.
- Domain-agnostic:      works across clinical, software, scientific, financial,
                        engineering, legal, and educational documents out of the box.
- Deterministic metadata:
                        figure names, file paths, and SHA-256 digests are computed
                        by the pipeline, never hallucinated by the model.
- Typed contract enforcement:
                        Pydantic validates every model response; mismatches trigger
                        corrective retries with the exact error messages attached.
- Enterprise patterns:  frozen config, injected dependencies, explicit error hierarchy,
                        single-responsibility classes, no magic globals.

Output record per figure (JSON emitted to stdout and optionally written to disk)
--------------------------------------------------------------------------------
{
  "figure_name":        "figure_p42_0",
  "figure_type":        "code_or_pseudocode",
  "rendering_strategy": "fenced_code_block",
  "is_informative":     true,
  "markdown_result":    "### Figure: BFS Algorithm\\n\\n```python\\n...",
  "legibility":         "clear",
  "confidence":         0.94,
  "document_domain":    "software"
}

Usage
-----
  uv run python figure_markdown_analyzer.py path/to/figure.png
  uv run python figure_markdown_analyzer.py fig.png --domain software
  uv run python figure_markdown_analyzer.py fig.png --output-dir out/ --emit-markdown
  uv run python figure_markdown_analyzer.py fig.png --model llava:13b --think --verbose

Install
-------
  uv add ollama pillow pydantic
  # or:
  pip install ollama pillow pydantic
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import re
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar, Final, Iterable

import ollama
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


LOGGER: Final[logging.Logger] = logging.getLogger("figure_markdown_analyzer")


# =============================================================================
# Section 1 — Domain vocabulary: enums defining the complete type system
# =============================================================================


class FigureType(str, Enum):
    """
    All structural figure types that may appear in a PDF of any domain.

    Grouped by broad category for readability; the groupings carry no
    semantic weight in validation.
    """

    # --- Algorithmic and formal notation ---
    DECISION_ALGORITHM   = "decision_algorithm"    # Branching flowchart with yes/no paths
    CODE_OR_PSEUDOCODE   = "code_or_pseudocode"    # Code listing, pseudocode, shell session
    UML_DIAGRAM          = "uml_diagram"            # Class, sequence, state, activity, …
    ARCHITECTURE_DIAGRAM = "architecture_diagram"  # System/network topology, DFD, ERD

    # --- Data and quantitative ---
    DATA_TABLE              = "data_table"              # Tabular data rendered as image
    STATISTICAL_PLOT        = "statistical_plot"        # Forest plot, KM curve, CI/HR/OR plots
    CHART                   = "chart"                   # Bar, line, scatter, pie, radar, histogram
    MATHEMATICAL_EXPRESSION = "mathematical_expression" # Equation, matrix, formula, proof

    # --- Process and structure ---
    PROCESS_OR_WORKFLOW = "process_or_workflow"  # Sequential steps / swim-lane (no branching)
    TIMELINE            = "timeline"             # Gantt, roadmap, chronological events
    CONCEPTUAL_DIAGRAM  = "conceptual_diagram"   # Taxonomy, framework, nested groupings
    MIND_MAP            = "mind_map"             # Radial or tree topic map
    VENN_OR_SET_DIAGRAM = "venn_or_set_diagram"  # Overlapping shapes showing set relationships

    # --- Domain-enriched and visual ---
    CLINICAL_ACTION_MAP = "clinical_action_map"  # Criteria → management actions lookup
    INFOGRAPHIC         = "infographic"          # Mixed icons, text, layout; no single form
    ILLUSTRATION        = "illustration"         # Anatomical, device, or technical drawing
    SCREENSHOT_OR_UI    = "screenshot_or_ui"     # App screenshot, dashboard, UI wireframe
    MAP                 = "map"                  # Geographical, geospatial, spatial heat-map

    # --- Non-informative ---
    DECORATIVE = "decorative"  # Stock photo, logo, watermark, background
    OTHER      = "other"       # Anything not matched above


class RenderingStrategy(str, Enum):
    """
    The Markdown rendering approach that most faithfully preserves a figure's
    native structure.

    Each value is associated with one or more FigureType values via
    ALLOWED_RENDERING_STRATEGIES_BY_FIGURE_TYPE; the validator enforces this
    mapping on every model response.
    """

    # --- Code and formal notation ---
    FENCED_CODE_BLOCK             = "fenced_code_block"
    LATEX_MATH_WITH_EXPLANATION   = "latex_math_with_explanation"
    MERMAID_DIAGRAM_WITH_EXPLANATION = "mermaid_diagram_with_explanation"

    # --- Flow and structural hierarchy ---
    ASCII_FLOW_DIAGRAM_WITH_EXPLANATION      = "ascii_flow_diagram_with_explanation"
    HIERARCHICAL_BULLETS_WITH_EXPLANATION   = "hierarchical_bullets_with_explanation"
    NUMBERED_STEPS_WITH_EXPLANATION         = "numbered_steps_with_explanation"
    SET_OVERLAP_WITH_EXPLANATION            = "set_overlap_with_explanation"

    # --- Table-based ---
    MARKDOWN_TABLE                  = "markdown_table"
    MARKDOWN_TABLE_WITH_EXPLANATION = "markdown_table_with_explanation"
    TIMELINE_TABLE                  = "timeline_table"

    # --- Data extraction ---
    CHART_VALUES_WITH_EXPLANATION = "chart_values_with_explanation"
    STATISTICAL_PLOT_EXTRACTION   = "statistical_plot_extraction"

    # --- Visual annotation ---
    ILLUSTRATION_LABELS_WITH_EXPLANATION = "illustration_labels_with_explanation"
    UI_STRUCTURE_WITH_EXPLANATION        = "ui_structure_with_explanation"

    # --- Fallbacks (use only when no structural strategy applies) ---
    PLAIN_TEXT_EXPLANATION = "plain_text_explanation"
    DECORATIVE_NOTE        = "decorative_note"


class LegibilityLevel(str, Enum):
    """How clearly the figure content is readable in the supplied image."""

    CLEAR   = "clear"
    PARTIAL = "partial"
    POOR    = "poor"


class DocumentDomain(str, Enum):
    """
    The domain of the source PDF document.

    AUTO is a CLI-level directive that instructs the pipeline to let the model
    infer the domain from visual context alone. It is never emitted in model output.
    """

    AUTO        = "auto"
    CLINICAL    = "clinical"
    SOFTWARE    = "software"
    SCIENTIFIC  = "scientific"
    FINANCIAL   = "financial"
    ENGINEERING = "engineering"
    LEGAL       = "legal"
    EDUCATIONAL = "educational"


# =============================================================================
# Section 2 — Validation matrix and JSON schema constants
# =============================================================================


ALLOWED_RENDERING_STRATEGIES_BY_FIGURE_TYPE: Final[dict[FigureType, frozenset[RenderingStrategy]]] = {
    FigureType.DECISION_ALGORITHM: frozenset({
        RenderingStrategy.ASCII_FLOW_DIAGRAM_WITH_EXPLANATION,
        RenderingStrategy.MERMAID_DIAGRAM_WITH_EXPLANATION,
        RenderingStrategy.HIERARCHICAL_BULLETS_WITH_EXPLANATION,
        RenderingStrategy.MARKDOWN_TABLE_WITH_EXPLANATION,
    }),
    FigureType.CODE_OR_PSEUDOCODE: frozenset({
        RenderingStrategy.FENCED_CODE_BLOCK,
    }),
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
    FigureType.DECORATIVE: frozenset({
        RenderingStrategy.DECORATIVE_NOTE,
    }),
    FigureType.OTHER: frozenset({
        RenderingStrategy.PLAIN_TEXT_EXPLANATION,
        RenderingStrategy.HIERARCHICAL_BULLETS_WITH_EXPLANATION,
        RenderingStrategy.MARKDOWN_TABLE_WITH_EXPLANATION,
        RenderingStrategy.FENCED_CODE_BLOCK,
    }),
}

# Domains the model is allowed to output — excludes the pipeline-only AUTO sentinel.
_MODEL_INFERRABLE_DOCUMENT_DOMAINS: Final[list[str]] = [
    domain.value for domain in DocumentDomain if domain != DocumentDomain.AUTO
]

# JSON Schema passed to Ollama's structured-output constraint engine.
MODEL_OUTPUT_JSON_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "figure_type": {
            "type": "string",
            "enum": [figure_type.value for figure_type in FigureType],
            "description": "The structural category of the figure.",
        },
        "rendering_strategy": {
            "type": "string",
            "enum": [strategy.value for strategy in RenderingStrategy],
            "description": "The Markdown rendering approach applied to markdown_result.",
        },
        "is_informative": {
            "type": "boolean",
            "description": "False only for decorative figures that carry no content.",
        },
        "markdown_result": {
            "type": "string",
            "description": (
                "Insertion-ready Markdown that structurally represents the figure. "
                "Must not be empty and must not contain JSON or pipeline metadata."
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
            "description": "Model's self-assessed confidence in the classification and extraction.",
        },
        "document_domain": {
            "type": "string",
            "enum": _MODEL_INFERRABLE_DOCUMENT_DOMAINS,
            "description": "The domain inferred or confirmed from the figure's visual context.",
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


# =============================================================================
# Section 3 — Pydantic contracts
# =============================================================================


class ModelAnalysisOutput(BaseModel):
    """
    The structured output contract that the vision model must satisfy.

    Owns only what the VLM is responsible for generating. Pipeline metadata
    (figure_name, source path, sha256) is attached by the Python layer and must
    never be generated by the model.

    Validation enforces:
    - confidence is a finite float in [0, 1].
    - decorative figures have is_informative=False and rendering_strategy=DECORATIVE_NOTE.
    - non-decorative figures have is_informative=True.
    - rendering_strategy is legal for the chosen figure_type.
    - document_domain is a concrete domain, not the pipeline-level AUTO sentinel.
    """

    model_config = ConfigDict(extra="forbid")

    figure_type:        FigureType
    rendering_strategy: RenderingStrategy
    is_informative:     bool
    markdown_result:    str
    legibility:         LegibilityLevel
    confidence:         float = Field(ge=0.0, le=1.0)
    document_domain:    DocumentDomain

    # ------------------------------------------------------------------
    # Field-level validators
    # ------------------------------------------------------------------

    @field_validator("document_domain")
    @classmethod
    def document_domain_must_not_be_auto_sentinel(cls, value: DocumentDomain) -> DocumentDomain:
        if value == DocumentDomain.AUTO:
            raise ValueError(
                "The model must infer and output a specific document domain "
                "(e.g. 'software', 'clinical'). "
                "The value 'auto' is a pipeline-level placeholder and must never "
                "appear in model output."
            )
        return value

    @field_validator("markdown_result")
    @classmethod
    def markdown_result_must_be_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError(
                "markdown_result must not be empty or whitespace-only. "
                "Even decorative figures require a brief descriptive note."
            )
        return stripped

    # ------------------------------------------------------------------
    # Cross-field model validator
    # ------------------------------------------------------------------

    @model_validator(mode="after")
    def validate_cross_field_consistency(self) -> "ModelAnalysisOutput":
        self._assert_confidence_is_finite()
        self._assert_decorative_figure_constraints()
        self._assert_non_decorative_figure_is_informative()
        self._assert_rendering_strategy_is_valid_for_figure_type()
        return self

    def _assert_confidence_is_finite(self) -> None:
        if not math.isfinite(self.confidence):
            raise ValueError(
                f"confidence must be a finite number between 0.0 and 1.0, "
                f"received {self.confidence!r}."
            )

    def _assert_decorative_figure_constraints(self) -> None:
        if self.figure_type != FigureType.DECORATIVE:
            return
        if self.is_informative:
            raise ValueError(
                "A decorative figure carries no content, so is_informative must be false."
            )
        if self.rendering_strategy != RenderingStrategy.DECORATIVE_NOTE:
            raise ValueError(
                "A decorative figure must use rendering_strategy='decorative_note'."
            )

    def _assert_non_decorative_figure_is_informative(self) -> None:
        if self.figure_type == FigureType.DECORATIVE:
            return
        if not self.is_informative:
            raise ValueError(
                f"figure_type='{self.figure_type.value}' is not decorative, "
                "so is_informative must be true."
            )

    def _assert_rendering_strategy_is_valid_for_figure_type(self) -> None:
        if (
            self.rendering_strategy == RenderingStrategy.DECORATIVE_NOTE
            and self.figure_type != FigureType.DECORATIVE
        ):
            raise ValueError(
                "rendering_strategy='decorative_note' is reserved for figure_type='decorative'."
            )

        allowed_strategies = ALLOWED_RENDERING_STRATEGIES_BY_FIGURE_TYPE.get(self.figure_type)
        if allowed_strategies is None:
            return

        if self.rendering_strategy not in allowed_strategies:
            sorted_allowed = ", ".join(sorted(s.value for s in allowed_strategies))
            raise ValueError(
                f"rendering_strategy='{self.rendering_strategy.value}' is not valid for "
                f"figure_type='{self.figure_type.value}'. "
                f"Allowed strategies for this type: {sorted_allowed}."
            )


class FigureAnalysisRecord(BaseModel):
    """
    The final pipeline output record for one figure image.

    Combines the model-generated ModelAnalysisOutput with the deterministic
    figure_name added by the Python pipeline.
    """

    model_config = ConfigDict(extra="forbid")

    figure_name:        str
    figure_type:        FigureType
    rendering_strategy: RenderingStrategy
    is_informative:     bool
    markdown_result:    str
    legibility:         LegibilityLevel
    confidence:         float = Field(ge=0.0, le=1.0)
    document_domain:    DocumentDomain


# =============================================================================
# Section 4 — Immutable configuration
# =============================================================================


@dataclass(frozen=True)
class AnalyzerConfig:
    """
    Immutable configuration for FigureMarkdownAnalyzer and its collaborators.

    Frozen to prevent accidental mutation after construction. Defaults are tuned
    for a quantized 4-billion-parameter vision model running locally.
    """

    ollama_model_name:                str            = "qwen3-vl:4b"
    ollama_host_url:                  str | None     = None
    document_domain:                  DocumentDomain = DocumentDomain.AUTO
    image_max_side_pixels:            int            = 2048
    max_structured_output_retries:    int            = 2
    generation_temperature:           float          = 0.0
    generation_top_p:                 float          = 0.1
    generation_seed:                  int            = 42
    context_window_tokens:            int            = 8192
    max_output_tokens:                int            = 4096
    enable_model_thinking:            bool           = False
    fallback_to_no_thinking_on_failure: bool         = True
    image_cache_directory:            Path           = Path(".figure_analyzer_cache")


# =============================================================================
# Section 5 — Explicit error hierarchy
# =============================================================================


class FigureAnalyzerError(RuntimeError):
    """Base class for all figure analysis pipeline failures."""


class ImagePreparationError(FigureAnalyzerError):
    """Raised when a figure image cannot be opened, decoded, or preprocessed."""


class StructuredOutputError(FigureAnalyzerError):
    """
    Raised when the vision model fails to produce schema-valid JSON after all retries.

    Attributes
    ----------
    image_path:
        Path of the image that triggered the failure (may point to the
        preprocessed cache copy or a synthetic path for parse failures).
    accumulated_errors:
        All validation error messages collected across every retry attempt,
        in chronological order.
    """

    def __init__(self, image_path: Path, accumulated_errors: list[str]) -> None:
        self.image_path          = image_path
        self.accumulated_errors  = accumulated_errors
        formatted_errors = "\n".join(f"  • {error}" for error in accumulated_errors)
        super().__init__(
            f"Structured output validation failed for {image_path} "
            f"after all attempts:\n{formatted_errors}"
        )


# =============================================================================
# Section 6 — Image preprocessing
# =============================================================================


class ImagePreprocessor:
    """
    Normalises figure images for submission to the Ollama vision model.

    Responsibilities:
    - Validates file existence and format support.
    - Corrects EXIF orientation.
    - Normalises colour mode to RGB (compositing any alpha channel onto white).
    - Downscales images whose longest side exceeds image_max_side_pixels.
    - Writes the result to a content-addressed cache, avoiding redundant
      preprocessing across repeated runs on the same source file.
    """

    _MINIMUM_ACCEPTABLE_MAX_SIDE_PIXELS: Final[int] = 512

    def __init__(self, max_side_pixels: int, cache_directory: Path) -> None:
        if max_side_pixels < self._MINIMUM_ACCEPTABLE_MAX_SIDE_PIXELS:
            raise ValueError(
                f"max_side_pixels must be at least {self._MINIMUM_ACCEPTABLE_MAX_SIDE_PIXELS} "
                f"to preserve figure legibility; received {max_side_pixels}."
            )
        self._max_side_pixels  = max_side_pixels
        self._cache_directory  = cache_directory

    def prepare(self, source_image_path: Path) -> Path:
        """
        Preprocess the image at source_image_path and return a path to the prepared copy.

        Subsequent calls with identical inputs return the cached file without
        re-processing.

        Raises
        ------
        ImagePreparationError
            If the file does not exist, is not a regular file, is corrupt,
            or cannot be read.
        """
        resolved_path = source_image_path.expanduser().resolve()
        self._assert_file_exists_and_is_regular(resolved_path)

        try:
            with Image.open(resolved_path) as raw_image:
                orientation_corrected = ImageOps.exif_transpose(raw_image)
                rgb_normalised        = self._normalise_colour_mode_to_rgb(orientation_corrected)
                downscaled            = self._downscale_if_longest_side_exceeds_limit(rgb_normalised)
                return self._write_to_content_addressed_cache(resolved_path, downscaled)

        except UnidentifiedImageError as error:
            raise ImagePreparationError(
                f"Unsupported or corrupt image: {resolved_path}"
            ) from error
        except OSError as error:
            raise ImagePreparationError(
                f"Could not read image {resolved_path}: {error}"
            ) from error

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _assert_file_exists_and_is_regular(path: Path) -> None:
        if not path.exists():
            raise ImagePreparationError(f"Image file not found: {path}")
        if not path.is_file():
            raise ImagePreparationError(f"Path is not a regular file: {path}")

    @staticmethod
    def _normalise_colour_mode_to_rgb(image: Image.Image) -> Image.Image:
        if image.mode in {"RGB", "L"}:
            return image.copy()
        if image.mode in {"RGBA", "LA"}:
            white_background = Image.new("RGB", image.size, "white")
            alpha_channel    = image.getchannel("A")
            white_background.paste(image.convert("RGB"), mask=alpha_channel)
            return white_background
        return image.convert("RGB")

    def _downscale_if_longest_side_exceeds_limit(self, image: Image.Image) -> Image.Image:
        width, height = image.size
        longest_side  = max(width, height)
        if longest_side <= self._max_side_pixels:
            return image.copy()

        scale_factor = self._max_side_pixels / longest_side
        target_width  = max(1, int(width  * scale_factor))
        target_height = max(1, int(height * scale_factor))

        LOGGER.info(
            "Downscaling image from %dx%d to %dx%d (max_side_pixels=%d).",
            width, height, target_width, target_height, self._max_side_pixels,
        )
        return image.resize((target_width, target_height), Image.Resampling.LANCZOS)

    def _write_to_content_addressed_cache(
        self,
        source_path: Path,
        prepared_image: Image.Image,
    ) -> Path:
        self._cache_directory.mkdir(parents=True, exist_ok=True)

        source_stat     = source_path.stat()
        cache_key_input = (
            f"{source_path}:{source_stat.st_size}"
            f":{source_stat.st_mtime_ns}:{self._max_side_pixels}"
        )
        cache_key_digest  = hashlib.sha256(cache_key_input.encode("utf-8")).hexdigest()[:16]
        cached_file_path  = self._cache_directory / f"{source_path.stem}_{cache_key_digest}.png"

        prepared_image.save(cached_file_path, format="PNG", optimize=True)
        return cached_file_path.resolve()


# =============================================================================
# Section 7 — Prompt construction
# =============================================================================

# Module-level constant so the multi-hundred-line prompt string is defined once
# and referenced by PromptBuilder without duplication.
_FIGURE_ANALYSIS_BASE_SYSTEM_PROMPT: Final[str] = """\
You are a universal figure-to-Markdown converter for PDF documents of any domain.

The source PDF may come from any field: software engineering, clinical medicine,
scientific research, finance, engineering, law, education, or any other domain.
Unless a domain context note appears at the end of this prompt, make no assumptions
about the subject matter and classify what you actually see in the image.

═══════════════════════════════════════════════════════════
OUTPUT PHILOSOPHY — STRUCTURAL FIDELITY, NOT PROSE SUMMARY
═══════════════════════════════════════════════════════════

Your primary obligation is to produce a structural Markdown representation that
mirrors the figure's native form. A prose description is a last resort.

  Code / pseudocode           → Fenced code block  (```python, ```java, ```text …)
  Decision flowchart          → Mermaid or ASCII diagram in fenced block
  UML diagram                 → Mermaid diagram  (classDiagram, sequenceDiagram …)
  Mathematical content        → LaTeX display math  ($$…$$)
  Data table                  → Markdown table with all rows and columns
  Chart / graph               → Extracted values in a Markdown table + explanation
  Statistical plot            → Subgroups, point estimates, CIs, p-values extracted
  Sequential process          → Numbered Markdown list
  Timeline / Gantt            → Date-keyed Markdown table
  Hierarchy / framework       → Indented bullet structure
  Venn / set diagram          → Set members and overlaps enumerated
  Illustration                → Visible labels and annotations listed
  UI / screenshot             → Panel-and-control hierarchy as indented bullets

Plain-text explanation is the strategy of last resort — use it only when absolutely
no structural representation is possible.

═══════════════════════════════════════════════════════════
STEP 1 — CLASSIFY THE FIGURE TYPE
═══════════════════════════════════════════════════════════

Select the single best figure_type:

decision_algorithm
  A flowchart or branching decision tree. Defining feature: conditional yes/no
  branches with arrows leading to different actions or further conditions.

code_or_pseudocode
  A figure showing computer code, pseudocode, an algorithm listing, shell commands,
  configuration syntax, a formal grammar, or a regular expression pattern.

uml_diagram
  Formal UML notation: class diagram, sequence diagram, activity diagram, state
  machine, use-case diagram, component diagram, or deployment diagram.

architecture_diagram
  A system architecture, network topology, data-flow diagram, entity-relationship
  diagram, infrastructure map, or software component map without formal UML notation.

data_table
  Tabular data rendered as an image, with identifiable rows, columns, and headers.

statistical_plot
  A plot carrying formal statistical inference: forest plot, Kaplan-Meier curve,
  plot with confidence intervals, hazard/odds/risk ratios, p-values, or reference
  lines. The defining feature is visible inference markings.

chart
  A bar chart, line chart, scatter plot, pie chart, radar chart, histogram, or
  similar quantitative graph without formal statistical inference markings.

mathematical_expression
  A standalone equation, formula, matrix, proof, theorem, or system of equations
  presented as a figure or rendered image block.

process_or_workflow
  A step-by-step process, procedure, or swim-lane diagram. Defining feature:
  sequential ordering without conditional branching.

timeline
  A chronological display: events on a line, milestones, project phases, a roadmap,
  or a Gantt chart.

conceptual_diagram
  A framework, taxonomy, hierarchy, nested structure, pathway overview, or
  colour/shape-coded grouping illustrating relationships without strict process flow.

mind_map
  A radial or tree diagram branching outward from a central concept.

venn_or_set_diagram
  Overlapping shapes (circles or other) showing set membership, intersection, or
  exclusion relationships.

clinical_action_map
  A figure mapping patient categories, risk levels, or clinical criteria to
  management actions or treatment decisions — without complex branching logic.

infographic
  A mixed-media figure combining icons, short text blocks, and layout to summarise
  a topic. No single structural element dominates.

illustration
  An anatomical drawing, technical device illustration, labelled photograph, or
  figure where visual structure and label positions convey the meaning.

screenshot_or_ui
  A screenshot of an application, dashboard, browser, or terminal; or a UI
  mockup/wireframe showing interface structure.

map
  A geographical, geospatial, heat-map, or spatial distribution figure.

decorative
  A stock photograph, logo, watermark, icon set, or background with no
  domain-relevant information.

other
  Anything not matching the descriptions above.

═══════════════════════════════════════════════════════════
STEP 2 — SELECT THE RENDERING STRATEGY
═══════════════════════════════════════════════════════════

Apply exactly the rule that matches the figure type you selected:

fenced_code_block
  Required for: code_or_pseudocode
  Extract all visible code or pseudocode into a fenced block. Choose the language
  identifier that best matches the syntax (python, java, c, cpp, sql, bash, r, scala,
  haskell, text, …). Use `text` when the language is ambiguous. Preserve indentation
  and line structure exactly as shown. Do not summarise; transcribe.

latex_math_with_explanation
  Required for: mathematical_expression
  Render every equation in display LaTeX: $$…$$ . Follow with a brief plain-language
  gloss of each visible symbol or term if labels are present.

mermaid_diagram_with_explanation
  For: uml_diagram, decision_algorithm, architecture_diagram, process_or_workflow
  Render in a fenced ```mermaid block. Choose the appropriate diagram type:
  flowchart TD, sequenceDiagram, classDiagram, stateDiagram-v2, gantt, erDiagram, …
  Follow with a concise explanation of the diagram's purpose and key relationships.
  If the diagram is too complex to represent accurately in Mermaid, fall back to
  ascii_flow_diagram_with_explanation.

ascii_flow_diagram_with_explanation
  For: decision_algorithm, architecture_diagram, process_or_workflow, uml_diagram
  Render in a fenced ```text block using box-and-arrow ASCII art. Follow with a
  concise explanation of the flow and key decision points.

markdown_table
  Required for: data_table
  Reproduce the table exactly: every column header, row label, and cell value.
  Use <br> inside cells for multi-line content. Do not omit rows or columns.

markdown_table_with_explanation
  For: clinical_action_map, chart, process_or_workflow, timeline, infographic
  Provide a short heading, a Markdown table capturing the key structure, then a
  brief explanation of what the table represents.

hierarchical_bullets_with_explanation
  For: conceptual_diagram, mind_map, infographic, architecture_diagram
  Reconstruct the hierarchy level by level using indented Markdown bullet lists.
  Follow with a brief explanation of the overall structure and its purpose.

numbered_steps_with_explanation
  For: process_or_workflow, timeline
  List each step or phase as a numbered Markdown item. Preserve visible labels,
  durations, icons, and transitions. Follow with a brief explanation.

timeline_table
  For: timeline
  Render as a two-column Markdown table: Date or Phase | Event or Description.
  Follow with a brief explanation.

chart_values_with_explanation
  For: chart, statistical_plot
  Identify axes, units, series labels, and legend entries. Extract readable or
  approximate values into a Markdown table. Label all approximated values explicitly
  (e.g., "approximately 42"). Follow with a brief explanation.

statistical_plot_extraction
  For: statistical_plot
  Extract — only where legible — comparison type, axes and units, reference line
  value, subgroup labels, point estimates, confidence intervals, p-values, and
  direction of effect. Present as a Markdown table followed by an explanation.

illustration_labels_with_explanation
  For: illustration
  List all visible structural labels, annotations, and callouts using bullet points.
  Describe the overall subject. Do not infer unlabelled structures.

ui_structure_with_explanation
  For: screenshot_or_ui
  Describe the UI hierarchy: panels, sections, controls, labels, and visible data.
  Use indented bullets to represent nesting. Follow with a brief explanation.

set_overlap_with_explanation
  For: venn_or_set_diagram
  Identify each set or circle. List the items or labels visible in each exclusive
  region and in each overlapping region. Use a table or bullets. Follow with a brief
  explanation.

plain_text_explanation
  Fallback only. Use when no structural strategy above can faithfully represent
  the figure.

decorative_note
  Required for: decorative
  Write a single sentence stating that the figure is decorative and carries no
  domain-relevant information.

═══════════════════════════════════════════════════════════
STEP 3 — PRODUCE THE markdown_result FIELD
═══════════════════════════════════════════════════════════

markdown_result must be self-contained and insertion-ready as a Markdown section.

Structure rules:
  1. Open with a level-3 heading:
       • `### Figure: <visible title>` when a title is visible in the image.
       • `### Figure analysis` when no title is visible.
  2. Apply the selected rendering strategy as the main body content.
  3. Explanatory prose, if any, follows the structural representation.

Content-preservation rules:
  • Preserve all visible numbers, thresholds, units, axis labels, legends,
    abbreviations, annotations, and text exactly as they appear.
  • Inside Markdown table cells, use `<br>` for multi-line items.
  • ASCII diagrams and Mermaid diagrams must be inside fenced code blocks.
  • Code must use a fenced block with the correct language identifier.
  • Mathematical expressions must use display LaTeX ($$…$$), not inline ($…$).
  • Do not embed JSON, YAML, metadata, source image path, page number, or
    SHA-256 anywhere inside markdown_result.

Anti-hallucination rules:
  • Describe only what is directly visible in the image.
  • Do not add domain knowledge, recommendations, or inferences not shown.
  • Write `illegible` for any text, value, or label that cannot be read clearly.
  • Write `approximately <value>` for numeric values read from a chart axis.
  • If the figure is only partially legible, state that limitation explicitly in
    the Markdown.

═══════════════════════════════════════════════════════════
OUTPUT FORMAT
═══════════════════════════════════════════════════════════

Return exactly one JSON object conforming to the provided schema.
  • No Markdown fences around the JSON output.
  • No prose, commentary, or explanation before or after the JSON.
  • No reasoning or scratchpad content in the assistant content channel.
  • Do not include properties absent from the schema.
"""


class PromptBuilder:
    """
    Constructs system and user prompts for the Ollama vision model.

    The base system prompt is fully domain-agnostic. A domain-specific addendum
    is appended when the caller specifies a concrete DocumentDomain. On retry
    attempts, the user prompt is augmented with the validation errors from all
    prior attempts so the model can self-correct.
    """

    _DOMAIN_CONTEXT_ADDENDA: ClassVar[dict[DocumentDomain, str]] = {
        DocumentDomain.CLINICAL: (
            "Domain context: This figure is from a clinical or medical document "
            "(e.g., clinical guidelines, trial reports, medical textbooks). "
            "The clinical_action_map type is particularly relevant. Statistical plots "
            "may include Kaplan-Meier curves, forest plots, and hazard/odds ratio diagrams."
        ),
        DocumentDomain.SOFTWARE: (
            "Domain context: This figure is from a software engineering or computer "
            "science document (e.g., API docs, architecture specs, research papers, "
            "textbooks). The types code_or_pseudocode, uml_diagram, and "
            "architecture_diagram are especially common here."
        ),
        DocumentDomain.SCIENTIFIC: (
            "Domain context: This figure is from a scientific research document "
            "(e.g., journal articles, theses, lab reports). The types statistical_plot, "
            "chart, data_table, and mathematical_expression are especially common."
        ),
        DocumentDomain.FINANCIAL: (
            "Domain context: This figure is from a financial or business document "
            "(e.g., annual reports, investment analyses, business plans). The types "
            "chart, data_table, and timeline are especially common."
        ),
        DocumentDomain.ENGINEERING: (
            "Domain context: This figure is from an engineering document "
            "(e.g., technical specifications, design documents, standards). The types "
            "illustration, architecture_diagram, data_table, and mathematical_expression "
            "are especially common."
        ),
        DocumentDomain.LEGAL: (
            "Domain context: This figure is from a legal document "
            "(e.g., contracts, regulatory filings, court documents). The types "
            "data_table, timeline, and process_or_workflow are especially common."
        ),
        DocumentDomain.EDUCATIONAL: (
            "Domain context: This figure is from an educational document "
            "(e.g., textbooks, course slides, curricula). All figure types are equally "
            "plausible; prioritise structural fidelity above all else."
        ),
    }

    _INITIAL_USER_PROMPT: ClassVar[str] = (
        "Convert this figure into a validated JSON object with the schema provided. "
        "The markdown_result field must contain a high-fidelity, insertion-ready Markdown "
        "representation that structurally mirrors the figure — not a prose description."
    )

    def build_system_prompt(self, document_domain: DocumentDomain) -> str:
        """
        Return the full system prompt for the given document domain.

        When document_domain is AUTO, returns the base prompt unchanged so the
        model infers the domain from visual context alone. Otherwise, appends
        a domain-specific context addendum.
        """
        domain_addendum = self._DOMAIN_CONTEXT_ADDENDA.get(document_domain, "")
        if not domain_addendum:
            return _FIGURE_ANALYSIS_BASE_SYSTEM_PROMPT

        separator = "\n" + "═" * 59 + "\n"
        return (
            _FIGURE_ANALYSIS_BASE_SYSTEM_PROMPT
            + separator
            + "DOCUMENT DOMAIN CONTEXT\n"
            + "═" * 59
            + f"\n{domain_addendum}\n"
        )

    def build_user_prompt(
        self,
        attempt_number: int,
        previous_validation_errors: list[str],
    ) -> str:
        """
        Build the user-turn prompt for a given attempt number.

        On the first attempt, returns the standard conversion instruction.
        On retry attempts, prepends the validation errors from all prior attempts
        so the model can identify and correct exactly what was wrong.
        """
        if attempt_number == 1 or not previous_validation_errors:
            return self._INITIAL_USER_PROMPT

        recent_errors      = previous_validation_errors[-5:]
        formatted_errors   = "\n".join(f"  • {error}" for error in recent_errors)

        return (
            f"{self._INITIAL_USER_PROMPT}\n\n"
            "⚠ The previous attempt failed JSON schema validation. Correct the output.\n"
            "Requirements:\n"
            "  • Return exactly one JSON object — no fences or prose around it.\n"
            "  • All Markdown content must be inside the markdown_result field.\n"
            "  • Do not add fields absent from the schema.\n"
            "  • rendering_strategy must be valid for the chosen figure_type.\n"
            f"Validation errors from the previous attempt:\n{formatted_errors}"
        )


# =============================================================================
# Section 8 — Ollama model gateway
# =============================================================================


class OllamaModelGateway:
    """
    Thin adapter around the Ollama Python client for vision model inference.

    Encapsulates connection management, generation option assembly, and
    think-mode toggling. Raises StructuredOutputError when the model returns
    an empty assistant content channel.
    """

    def __init__(self, config: AnalyzerConfig) -> None:
        self._config = config
        self._ollama_client = (
            ollama.Client(host=config.ollama_host_url)
            if config.ollama_host_url
            else ollama.Client()
        )

    def invoke(
        self,
        prepared_image_path: Path,
        system_prompt: str,
        user_prompt: str,
        enable_thinking: bool,
    ) -> str:
        """
        Submit the image and prompts to the vision model and return the raw
        assistant content string.

        The content is expected to be a JSON object matching MODEL_OUTPUT_JSON_SCHEMA.
        Raises StructuredOutputError if the content channel is empty.
        """
        generation_options: dict[str, Any] = {
            "temperature": self._config.generation_temperature,
            "top_p":       self._config.generation_top_p,
            "seed":        self._config.generation_seed,
            "num_ctx":     self._config.context_window_tokens,
            "num_predict": self._config.max_output_tokens,
        }

        call_kwargs: dict[str, Any] = {
            "model": self._config.ollama_model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role":    "user",
                    "content": user_prompt,
                    "images":  [str(prepared_image_path)],
                },
            ],
            "format":  MODEL_OUTPUT_JSON_SCHEMA,
            "options": generation_options,
        }

        if enable_thinking:
            call_kwargs["think"] = True

        response     = self._ollama_client.chat(**call_kwargs)
        raw_content  = self._extract_content_from_response(response).strip()

        if not raw_content:
            raise StructuredOutputError(
                prepared_image_path,
                ["The model returned an empty assistant content channel."],
            )

        return raw_content

    @staticmethod
    def _extract_content_from_response(response: Any) -> str:
        message = (
            response.get("message")
            if isinstance(response, dict)
            else getattr(response, "message", None)
        )
        if message is None:
            return ""
        if isinstance(message, dict):
            return str(message.get("content") or "")
        return str(getattr(message, "content", "") or "")


# =============================================================================
# Section 9 — Model response parsing and validation
# =============================================================================


class ModelResponseParser:
    """
    Deserialises and validates the raw string response from the vision model.

    All methods are static; this class is a namespace for parsing logic and
    carries no mutable state.
    """

    @staticmethod
    def parse_and_validate(raw_model_response: str) -> ModelAnalysisOutput:
        """
        Parse raw_model_response as JSON and validate it against ModelAnalysisOutput.

        Raises
        ------
        StructuredOutputError
            If the string is not valid JSON, or if the parsed payload does not
            satisfy the ModelAnalysisOutput contract.
        """
        parsed_payload = ModelResponseParser._deserialise_json_or_raise(raw_model_response)
        return ModelResponseParser._validate_payload_or_raise(parsed_payload)

    @staticmethod
    def _deserialise_json_or_raise(raw_text: str) -> dict[str, Any]:
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError as error:
            raise StructuredOutputError(
                Path("<model-response>"),
                [f"Response is not valid JSON: {error}"],
            ) from error

    @staticmethod
    def _validate_payload_or_raise(payload: dict[str, Any]) -> ModelAnalysisOutput:
        try:
            return ModelAnalysisOutput.model_validate(payload)
        except ValidationError as error:
            human_readable_errors = json.dumps(
                error.errors(include_url=False),
                ensure_ascii=False,
            )
            raise StructuredOutputError(
                Path("<model-response>"),
                [human_readable_errors],
            ) from error


# =============================================================================
# Section 10 — Analysis orchestrator
# =============================================================================


class FigureMarkdownAnalyzer:
    """
    Orchestrates the end-to-end pipeline for analysing a single figure image.

    Pipeline stages
    ---------------
    1. ImagePreprocessor  — Normalise and cache the source image.
    2. PromptBuilder      — Construct system and user prompts for the current attempt.
    3. OllamaModelGateway — Submit image + prompts to the vision model.
    4. ModelResponseParser — Deserialise and validate the JSON response.
    5. Record assembly    — Attach deterministic metadata to produce FigureAnalysisRecord.

    Think-mode retry behaviour
    --------------------------
    If enable_model_thinking=True and structured output validation fails, the next
    retry disables thinking (when fallback_to_no_thinking_on_failure=True). Small
    quantized models frequently produce empty content channels when thinking mode
    is combined with structured-output constraints.
    """

    def __init__(self, config: AnalyzerConfig) -> None:
        self._config           = config
        self._image_preprocessor = ImagePreprocessor(
            max_side_pixels  = config.image_max_side_pixels,
            cache_directory  = config.image_cache_directory,
        )
        self._prompt_builder   = PromptBuilder()
        self._model_gateway    = OllamaModelGateway(config)

    def analyze(self, image_path: Path) -> FigureAnalysisRecord:
        """
        Analyse the figure at image_path and return a validated FigureAnalysisRecord.

        Raises
        ------
        ImagePreparationError
            If the image cannot be opened or preprocessed.
        StructuredOutputError
            If the model fails to produce valid structured output after all retries.
        """
        resolved_image_path  = image_path.expanduser().resolve()
        prepared_image_path  = self._image_preprocessor.prepare(resolved_image_path)
        system_prompt        = self._prompt_builder.build_system_prompt(self._config.document_domain)

        accumulated_errors:  list[str] = []
        thinking_enabled:    bool      = self._config.enable_model_thinking
        total_attempts:      int       = self._config.max_structured_output_retries + 1

        for attempt_number in range(1, total_attempts + 1):
            user_prompt = self._prompt_builder.build_user_prompt(
                attempt_number           = attempt_number,
                previous_validation_errors = accumulated_errors,
            )
            try:
                raw_model_response = self._model_gateway.invoke(
                    prepared_image_path = prepared_image_path,
                    system_prompt       = system_prompt,
                    user_prompt         = user_prompt,
                    enable_thinking     = thinking_enabled,
                )
                model_output = ModelResponseParser.parse_and_validate(raw_model_response)
                return self._assemble_analysis_record(resolved_image_path, model_output)

            except StructuredOutputError as error:
                accumulated_errors.extend(error.accumulated_errors)
                LOGGER.warning(
                    "Attempt %d/%d failed for %s: %s",
                    attempt_number,
                    total_attempts,
                    resolved_image_path.name,
                    error.accumulated_errors[-1] if error.accumulated_errors else "unknown",
                )

                if thinking_enabled and self._config.fallback_to_no_thinking_on_failure:
                    LOGGER.info(
                        "Disabling think mode for remaining retries — "
                        "thinking and structured output constraints can conflict on small models."
                    )
                    thinking_enabled = False

                if attempt_number >= total_attempts:
                    break

        raise StructuredOutputError(prepared_image_path, accumulated_errors)

    @staticmethod
    def _assemble_analysis_record(
        original_image_path: Path,
        model_output: ModelAnalysisOutput,
    ) -> FigureAnalysisRecord:
        record_payload = {
            "figure_name": derive_figure_name_from_path(original_image_path),
            **model_output.model_dump(mode="json"),
        }
        return FigureAnalysisRecord.model_validate(record_payload)


# =============================================================================
# Section 11 — Output writing
# =============================================================================


class AnalysisOutputWriter:
    """
    Writes FigureAnalysisRecord results to disk as JSON and/or Markdown files.

    The output directory is created on demand. File names are derived from the
    figure_name field of the record, ensuring deterministic and collision-free
    output across batches.
    """

    _JSON_FILE_SUFFIX:     Final[str] = ".figure_analysis.json"
    _MARKDOWN_FILE_SUFFIX: Final[str] = ".md"

    def __init__(self, output_directory: Path) -> None:
        self._output_directory = output_directory

    def write_json(
        self,
        analysis_record: FigureAnalysisRecord,
        debug_metadata:  dict[str, Any] | None = None,
    ) -> Path:
        """
        Serialise the analysis record to a JSON file in the output directory.

        If debug_metadata is provided, it is attached under a "debug_metadata"
        key without modifying the record object.
        """
        self._output_directory.mkdir(parents=True, exist_ok=True)
        output_file_path = (
            self._output_directory
            / f"{analysis_record.figure_name}{self._JSON_FILE_SUFFIX}"
        )

        record_payload: dict[str, Any] = analysis_record.model_dump(mode="json")
        if debug_metadata:
            record_payload["debug_metadata"] = debug_metadata

        output_file_path.write_text(
            json.dumps(record_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return output_file_path

    def write_markdown(self, analysis_record: FigureAnalysisRecord) -> Path:
        """Write the markdown_result field to a standalone Markdown file."""
        self._output_directory.mkdir(parents=True, exist_ok=True)
        output_file_path = (
            self._output_directory
            / f"{analysis_record.figure_name}{self._MARKDOWN_FILE_SUFFIX}"
        )
        output_file_path.write_text(
            analysis_record.markdown_result.rstrip() + "\n",
            encoding="utf-8",
        )
        return output_file_path

    @staticmethod
    def build_debug_metadata(
        source_image_path: Path,
        config: AnalyzerConfig,
    ) -> dict[str, Any]:
        """
        Build a deterministic debug metadata dict for optional inclusion in JSON output.

        This is the only place where SHA-256 hashing and absolute paths are attached
        to output; they must never appear inside model-generated content.
        """
        resolved_path = source_image_path.expanduser().resolve()
        return {
            "source_image_path":   str(resolved_path),
            "source_sha256":       compute_file_sha256(resolved_path),
            "ollama_model_name":   config.ollama_model_name,
            "image_max_side_pixels": config.image_max_side_pixels,
            "document_domain_hint": config.document_domain.value,
        }


# =============================================================================
# Section 12 — Utility functions
# =============================================================================


def derive_figure_name_from_path(image_path: Path) -> str:
    """
    Derive a clean, filesystem-safe figure name from an image file path.

    Uses only the filename stem, replacing any character that is not
    alphanumeric, a hyphen, or an underscore with an underscore. The result
    is deterministic and free of path or metadata components.

    Examples
    --------
    /reports/figure_p140_0.png  →  figure_p140_0
    /reports/Figure 49.png      →  Figure_49
    /reports/fig-3b.png         →  fig-3b
    /reports/.hidden.png        →  hidden
    """
    stem      = Path(image_path).expanduser().stem
    sanitised = re.sub(r"[^0-9A-Za-z_-]+", "_", stem).strip("_")
    return sanitised or "figure"


def compute_file_sha256(file_path: Path) -> str:
    """Compute the SHA-256 hex digest of a file for debug metadata purposes."""
    digest = hashlib.sha256()
    with file_path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_image_paths(raw_path_strings: Iterable[str]) -> list[Path]:
    """Resolve a sequence of raw path strings into a list of Path objects."""
    return [Path(raw_path).expanduser() for raw_path in raw_path_strings]


# =============================================================================
# Section 13 — CLI
# =============================================================================


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="figure_markdown_analyzer",
        description=(
            "Convert figure images extracted from any PDF into high-fidelity, "
            "insertion-ready Markdown using a local Ollama vision-language model."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # Positional
    parser.add_argument(
        "image_paths",
        nargs="+",
        metavar="IMAGE",
        help="One or more figure image paths (PNG, JPEG, or WebP).",
    )

    # Model and connection
    model_group = parser.add_argument_group("Model and connection")
    model_group.add_argument(
        "--model",
        dest="ollama_model_name",
        default="qwen3-vl:4b",
        metavar="MODEL",
        help="Vision-capable Ollama model name (e.g., qwen3-vl:4b, llava:13b).",
    )
    model_group.add_argument(
        "--host",
        dest="ollama_host_url",
        default=None,
        metavar="URL",
        help="Ollama server URL. Defaults to http://localhost:11434.",
    )
    model_group.add_argument(
        "--think",
        dest="enable_model_thinking",
        action="store_true",
        help=(
            "Enable model thinking/reasoning if supported. "
            "Automatically disabled on retry if structured output validation fails."
        ),
    )

    # Domain and content
    content_group = parser.add_argument_group("Document domain")
    content_group.add_argument(
        "--domain",
        dest="document_domain",
        default=DocumentDomain.AUTO.value,
        choices=[domain.value for domain in DocumentDomain],
        metavar="DOMAIN",
        help=(
            "Document domain hint for the model "
            f"({', '.join(d.value for d in DocumentDomain)}). "
            "'auto' lets the model infer the domain from the figure itself."
        ),
    )

    # Generation parameters
    generation_group = parser.add_argument_group("Generation parameters")
    generation_group.add_argument(
        "--temperature",
        dest="generation_temperature",
        type=float,
        default=0.0,
        metavar="T",
        help="Sampling temperature (0.0 = fully deterministic).",
    )
    generation_group.add_argument(
        "--top-p",
        dest="generation_top_p",
        type=float,
        default=0.1,
        metavar="P",
        help="Top-p nucleus sampling value.",
    )
    generation_group.add_argument(
        "--seed",
        dest="generation_seed",
        type=int,
        default=42,
        metavar="SEED",
        help="Random seed for deterministic generation.",
    )
    generation_group.add_argument(
        "--num-ctx",
        dest="context_window_tokens",
        type=int,
        default=8192,
        metavar="TOKENS",
        help="Ollama context window size in tokens.",
    )
    generation_group.add_argument(
        "--num-predict",
        dest="max_output_tokens",
        type=int,
        default=4096,
        metavar="TOKENS",
        help="Maximum number of output tokens to generate.",
    )

    # Image preprocessing
    image_group = parser.add_argument_group("Image preprocessing")
    image_group.add_argument(
        "--max-side",
        dest="image_max_side_pixels",
        type=int,
        default=2048,
        metavar="PIXELS",
        help="Maximum image side length in pixels after preprocessing.",
    )
    image_group.add_argument(
        "--cache-dir",
        dest="image_cache_directory",
        type=Path,
        default=Path(".figure_analyzer_cache"),
        metavar="DIR",
        help="Directory for preprocessed image cache files.",
    )

    # Retry behaviour
    retry_group = parser.add_argument_group("Retry behaviour")
    retry_group.add_argument(
        "--retries",
        dest="max_structured_output_retries",
        type=int,
        default=2,
        metavar="N",
        help="Maximum number of structured-output validation retry attempts.",
    )

    # Output
    output_group = parser.add_argument_group("Output")
    output_group.add_argument(
        "--output-dir",
        dest="output_directory",
        type=Path,
        default=None,
        metavar="DIR",
        help="Directory for JSON (and optionally Markdown) output files.",
    )
    output_group.add_argument(
        "--emit-markdown",
        action="store_true",
        help="Also write markdown_result to a .md file. Requires --output-dir.",
    )
    output_group.add_argument(
        "--include-debug-metadata",
        action="store_true",
        help=(
            "Attach source image path, SHA-256, model name, and max_side_pixels "
            "under a 'debug_metadata' key in JSON output."
        ),
    )

    # Execution control
    execution_group = parser.add_argument_group("Execution control")
    execution_group.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop processing immediately after the first failed image.",
    )
    execution_group.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG-level logging.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    argument_parser = build_argument_parser()
    parsed_args     = argument_parser.parse_args(argv)

    if parsed_args.emit_markdown and not parsed_args.output_directory:
        argument_parser.error("--emit-markdown requires --output-dir to be specified.")

    logging.basicConfig(
        level   = logging.DEBUG if parsed_args.verbose else logging.INFO,
        format  = "%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
        datefmt = "%Y-%m-%d %H:%M:%S",
    )

    analyzer_config = AnalyzerConfig(
        ollama_model_name              = parsed_args.ollama_model_name,
        ollama_host_url                = parsed_args.ollama_host_url,
        document_domain                = DocumentDomain(parsed_args.document_domain),
        image_max_side_pixels          = parsed_args.image_max_side_pixels,
        max_structured_output_retries  = parsed_args.max_structured_output_retries,
        generation_temperature         = parsed_args.generation_temperature,
        generation_top_p               = parsed_args.generation_top_p,
        generation_seed                = parsed_args.generation_seed,
        context_window_tokens          = parsed_args.context_window_tokens,
        max_output_tokens              = parsed_args.max_output_tokens,
        enable_model_thinking          = parsed_args.enable_model_thinking,
        image_cache_directory          = parsed_args.image_cache_directory,
    )

    analyzer = FigureMarkdownAnalyzer(config=analyzer_config)

    output_writer: AnalysisOutputWriter | None = (
        AnalysisOutputWriter(parsed_args.output_directory)
        if parsed_args.output_directory
        else None
    )

    image_paths   = collect_image_paths(parsed_args.image_paths)
    failure_count = 0

    for image_path in image_paths:
        try:
            analysis_record = analyzer.analyze(image_path)
            record_payload: dict[str, Any] = analysis_record.model_dump(mode="json")

            debug_metadata: dict[str, Any] | None = None
            if parsed_args.include_debug_metadata:
                debug_metadata = AnalysisOutputWriter.build_debug_metadata(
                    image_path, analyzer_config
                )
                record_payload["debug_metadata"] = debug_metadata

            print(json.dumps(record_payload, ensure_ascii=False, indent=2))

            if output_writer is not None:
                written_json_path = output_writer.write_json(analysis_record, debug_metadata)
                LOGGER.info("JSON output  → %s", written_json_path)

                if parsed_args.emit_markdown:
                    written_md_path = output_writer.write_markdown(analysis_record)
                    LOGGER.info("Markdown output → %s", written_md_path)

        except FigureAnalyzerError as error:
            failure_count += 1
            error_record = {
                "figure_name":   derive_figure_name_from_path(image_path),
                "error_type":    type(error).__name__,
                "error_message": str(error),
            }
            print(json.dumps(error_record, ensure_ascii=False, indent=2), file=sys.stderr)
            LOGGER.error("Failed to analyse %s: %s", image_path.name, error)

            if parsed_args.fail_fast:
                LOGGER.info("--fail-fast is set; stopping after first failure.")
                return 2

    return 0 if failure_count == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())