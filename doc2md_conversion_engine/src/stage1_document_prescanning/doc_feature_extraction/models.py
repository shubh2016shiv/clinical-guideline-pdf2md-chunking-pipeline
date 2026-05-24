"""
doc_feature_extraction/models.py
================================
Small value objects for deterministic document evidence extraction.

The extractor reports facts about a document.  It does not decide which
conversion engine is "best"; requirement inference and routing consume these
facts later.  Keeping those concerns separate makes Stage 1 easier to debug
and safer to extend to more formats.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class FeatureDocumentType(StrEnum):
    """Formats understood by the feature extraction layer."""

    PDF = "pdf"
    DOCX = "docx"
    PPTX = "pptx"
    HTML = "html"


class VisualCandidateKind(StrEnum):
    """Conservative visual candidate labels, not semantic claims."""

    EMBEDDED_IMAGE = "embedded_image"
    VECTOR_GRAPHICS = "vector_graphics"
    TABLE = "table"
    CHART = "chart"
    FIGURE_ELEMENT = "figure_element"
    SVG = "svg"
    SLIDE_VISUAL_CLUSTER = "slide_visual_cluster"


class TextEvidence(BaseModel):
    """Document-level text availability and density evidence."""

    model_config = ConfigDict(frozen=True)

    total_characters: int = Field(..., ge=0)
    pages_or_units_with_text: int = Field(..., ge=0)
    estimated_text_density: float = Field(..., ge=0.0)
    native_text_available: bool


class TableEvidence(BaseModel):
    """Factual table evidence collected from the source format."""

    model_config = ConfigDict(frozen=True)

    count: int = Field(..., ge=0)
    pages_or_units_with_tables: int = Field(..., ge=0)
    large_count: int = Field(default=0, ge=0)


class VisualEvidence(BaseModel):
    """Factual visual-object evidence collected from the source format."""

    model_config = ConfigDict(frozen=True)

    embedded_image_count: int = Field(..., ge=0)
    large_embedded_image_count: int = Field(default=0, ge=0)
    vector_graphics_count: int = Field(default=0, ge=0)
    chart_count: int = Field(default=0, ge=0)
    svg_count: int = Field(default=0, ge=0)
    pages_or_units_with_visuals: int = Field(..., ge=0)
    captioned_visual_count: int = Field(default=0, ge=0)


class VisualCandidate(BaseModel):
    """
    A selected object/page/slide that may need visual semantic explanation.

    ``page_number`` is 1-based when the source has pages/slides.  DOCX/HTML
    candidates may not have a true page location, so callers can use
    ``location_label`` instead.
    """

    model_config = ConfigDict(frozen=True)

    kind: VisualCandidateKind
    page_number: int | None = Field(default=None, ge=1)
    location_label: str | None = None
    area_ratio: float | None = Field(default=None, ge=0.0)
    caption_or_alt_text: str | None = None
    nearby_text: str | None = None
    evidence: list[str] = Field(default_factory=list)


class EngineFormatSupport(BaseModel):
    """Hard file-format support for candidate conversion engines."""

    model_config = ConfigDict(frozen=True)

    docling_supported: bool
    mineru_supported: bool
    notes: list[str] = Field(default_factory=list)


class DocumentRequirements(BaseModel):
    """Capabilities inferred from deterministic evidence."""

    model_config = ConfigDict(frozen=True)

    needs_text_extraction: bool = True
    needs_reading_order_reconstruction: bool = False
    needs_table_reconstruction: bool = False
    needs_visual_asset_extraction: bool = False
    needs_visual_semantic_explanation: bool = False
    needs_local_vlm_adjudication: bool = False
    rationale: list[str] = Field(default_factory=list)


class OllamaVisualRoutingPayload(BaseModel):
    """
    Compact payload intended for a local vision model such as Qwen via Ollama.

    The payload intentionally contains summary evidence plus selected visual
    candidates only.  The caller may render/attach the candidate pages or
    regions listed here; the whole document should not be sent.
    """

    model_config = ConfigDict(frozen=True)

    task: str
    required_output_schema: dict[str, object]
    document_summary: dict[str, object]
    candidates_to_inspect: list[dict[str, object]]
    prompt: str


class OllamaVisualRoutingDecision(BaseModel):
    """Parsed local-VLM decision for selected visual candidates."""

    model_config = ConfigDict(frozen=True)

    requires_visual_semantic_explanation: bool
    recommended_structure_engine: str = Field(pattern="^(docling|mineru|either)$")
    visual_candidates_requiring_explanation: list[dict[str, object]] = Field(
        default_factory=list
    )
    confidence: float = Field(..., ge=0.0, le=1.0)
    raw_response: str | None = None


class DocumentFeatureProfile(BaseModel):
    """Top-level deterministic feature profile for one source document."""

    model_config = ConfigDict(frozen=True)

    file_type: FeatureDocumentType
    page_or_unit_count: int = Field(..., ge=1)
    text: TextEvidence
    tables: TableEvidence
    visuals: VisualEvidence
    visual_candidates: list[VisualCandidate] = Field(default_factory=list)
    format_support: EngineFormatSupport
    requirements: DocumentRequirements

    def compact_summary(self) -> str:
        """One-line summary suitable for logs and CLI output."""
        bits = [
            f"{self.file_type.value}",
            f"units={self.page_or_unit_count}",
            f"text_chars={self.text.total_characters}",
            f"tables={self.tables.count}",
            f"images={self.visuals.embedded_image_count}",
            f"vectors={self.visuals.vector_graphics_count}",
            f"visual_candidates={len(self.visual_candidates)}",
        ]
        if self.requirements.needs_visual_semantic_explanation:
            bits.append("needs_visual_explanation")
        return ", ".join(bits)
