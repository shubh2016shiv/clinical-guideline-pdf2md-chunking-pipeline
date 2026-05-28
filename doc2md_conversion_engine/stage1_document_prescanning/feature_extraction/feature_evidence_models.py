"""
stage1_document_prescanning/feature_extraction/feature_evidence_models.py
=========================================================================
Stage 1 · Step 2 of 3 — the shared vocabulary for everything we measure.

This file defines the data shapes used to record what a document contains: how
much text, what kind of tables, how the page is laid out, which visuals appear,
and the final summary that bundles it all together. Think of it as the set of
labelled boxes the readers fill in and the routing step reads out of.

Two important properties of these boxes:

  * They hold FACTS, not opinions. A box says "this table has 8 columns", never
    "this document is hard" — judging difficulty is the routing step's job.
  * They are frozen (read-only) once created, so a fact measured by a reader
    cannot be quietly changed somewhere downstream.

When a particular format genuinely cannot measure something cheaply, the
corresponding box is left at its honest default (for example column_count = 1,
or has_merged_cells = False) rather than filled in with a guess.
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
    """
    What we found out about the document's text.

    The most important field is ``native_text_available``: is there real,
    selectable text we can read directly, or is the document just pictures of
    text (a scan) that would need OCR? The character counts and density give a
    rough sense of how text-heavy the document is.
    """

    model_config = ConfigDict(frozen=True)

    total_characters: int = Field(..., ge=0)
    pages_or_units_with_text: int = Field(..., ge=0)
    estimated_text_density: float = Field(..., ge=0.0)
    native_text_available: bool


class TableEvidence(BaseModel):
    """
    Factual table evidence collected from the source format.

    ``count``, ``large_count``, and ``pages_or_units_with_tables`` measure *how
    many* and *how big* — area, not structure.  The structural fields below
    measure *how complex*, which is what actually decides whether a table needs
    a layout-reconstruction engine: a wide or merged-cell table degrades in a
    grid-naive parser, while a small simple table does not.

    Structural fields default to a "no complexity detected" value.  A format
    that cannot read a given signal cheaply leaves it at the default rather than
    guessing — the same honesty contract used by ``large_count`` for formats
    that carry no size metadata.
    """

    model_config = ConfigDict(frozen=True)

    count: int = Field(..., ge=0)
    pages_or_units_with_tables: int = Field(..., ge=0)
    large_count: int = Field(default=0, ge=0)

    max_column_count: int = Field(
        default=0,
        ge=0,
        description="Widest table in the document, in columns. 0 when not determinable.",
    )
    has_merged_cells: bool = Field(
        default=False,
        description="Any rowspan/colspan (merged-cell) geometry detected in any table.",
    )
    has_nested_tables: bool = Field(
        default=False,
        description="A table nested inside another table's cell (flattened silently by grid-naive parsers).",
    )


class VisualEvidence(BaseModel):
    """
    A count of the non-text things in the document.

    Embedded images, vector drawings, charts, and so on. These counts feed the
    "is there a figure worth summarising later?" signal — they do NOT affect
    which engine is chosen. A document full of pictures is not, by itself, harder
    to convert; it just has more for a later stage to describe.
    """

    model_config = ConfigDict(frozen=True)

    embedded_image_count: int = Field(..., ge=0)
    large_embedded_image_count: int = Field(default=0, ge=0)
    vector_graphics_count: int = Field(default=0, ge=0)
    chart_count: int = Field(default=0, ge=0)
    svg_count: int = Field(default=0, ge=0)
    pages_or_units_with_visuals: int = Field(..., ge=0)
    captioned_visual_count: int = Field(default=0, ge=0)


class LayoutEvidence(BaseModel):
    """
    Page/section layout evidence that decides reading-order difficulty.

    Multi-column text and floating text boxes are layout-reconstruction
    problems: a linear text-flow parser reads them out of order.  These are the
    canonical signals for promoting to a layout-aware engine, and they are
    independent of how many visuals or tables the document contains.

    ``column_count`` is 1 (single column) when no multi-column layout is
    detected or when the format cannot express columns (e.g. PPTX slides, HTML
    whose columns live in CSS that is not rendered here).
    """

    model_config = ConfigDict(frozen=True)

    column_count: int = Field(
        default=1,
        ge=1,
        description="Detected text-column count. 1 = single-column / linear reading order.",
    )
    has_floating_text_boxes: bool = Field(
        default=False,
        description="Floating/anchored text boxes that break linear text flow (DOCX txbxContent, PPTX non-placeholder shapes).",
    )


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
    """
    Which engines can open this document's format at all.

    Two plain yes/no answers — can Docling read it, can MinerU read it — plus
    optional notes. This is basic compatibility, not a quality judgement.
    """

    model_config = ConfigDict(frozen=True)

    docling_supported: bool
    mineru_supported: bool
    notes: list[str] = Field(default_factory=list)


class DocumentRequirements(BaseModel):
    """
    Processing capabilities inferred from deterministic evidence.

    Two groups, with different consumers:

    *Routing signals* — read by the capability router to choose the Stage 2
    engine.  These promote to a layout-reconstruction engine only when the
    document has structural complexity a grid/flow-naive parser cannot handle:
    ``needs_reading_order_reconstruction``, ``needs_complex_table_reconstruction``,
    ``needs_ocr_text_recovery``.

    *Downstream signals* — describe work for later stages, NOT engine choice.
    ``needs_visual_asset_extraction`` (both engines extract assets) and
    ``needs_visual_semantic_explanation`` (a Stage 3 figure-summarization signal)
    deliberately do not influence routing: a single figure on an otherwise
    linear page needs figure summarization later, not a heavier extraction
    engine now.
    """

    model_config = ConfigDict(frozen=True)

    needs_text_extraction: bool = True
    needs_ocr_text_recovery: bool = False
    needs_reading_order_reconstruction: bool = False
    needs_table_reconstruction: bool = False
    needs_complex_table_reconstruction: bool = False
    needs_visual_asset_extraction: bool = False
    needs_visual_semantic_explanation: bool = False
    rationale: list[str] = Field(default_factory=list)


class DocumentFeatureProfile(BaseModel):
    """
    The complete picture of one document — the output of Step 2.

    This is the single object a reader produces and the routing step consumes.
    It gathers every other evidence box (text, tables, layout, visuals), the list
    of visual candidates, which engines can open the format, and the resolved
    needs, all in one place. If you want to know "what did Stage 1 learn about
    this file?", this object is the answer.
    """

    model_config = ConfigDict(frozen=True)

    file_type: FeatureDocumentType
    page_or_unit_count: int = Field(..., ge=1)
    text: TextEvidence
    tables: TableEvidence
    layout: LayoutEvidence
    visuals: VisualEvidence
    visual_candidates: list[VisualCandidate] = Field(default_factory=list)
    format_support: EngineFormatSupport
    requirements: DocumentRequirements

    def compact_summary(self) -> str:
        """
        Condense the whole profile into one readable line for logs and the CLI.

        Lists the headline counts (pages, characters, tables, columns, images)
        and tacks on short flags like ``complex_layout`` or ``complex_tables``
        only when those conditions are actually present, so a human scanning the
        output can see at a glance why a document might have been promoted.
        """
        bits = [
            f"{self.file_type.value}",
            f"units={self.page_or_unit_count}",
            f"text_chars={self.text.total_characters}",
            f"tables={self.tables.count}",
            f"columns={self.layout.column_count}",
            f"images={self.visuals.embedded_image_count}",
            f"vectors={self.visuals.vector_graphics_count}",
            f"visual_candidates={len(self.visual_candidates)}",
        ]
        if self.layout.column_count >= 2 or self.layout.has_floating_text_boxes:
            bits.append("complex_layout")
        if self.tables.has_merged_cells or self.tables.has_nested_tables:
            bits.append("complex_tables")
        if self.requirements.needs_visual_semantic_explanation:
            bits.append("needs_visual_explanation")
        return ", ".join(bits)
