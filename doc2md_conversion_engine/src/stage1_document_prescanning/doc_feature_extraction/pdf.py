"""
PDF feature extraction for engine routing.

This module does not try to understand the clinical meaning of a PDF.  It only
collects factual evidence that is cheap to inspect:

1. Is there native text?
2. Are there table-shaped regions?
3. Are there embedded images?
4. Are there vector drawing-heavy pages?
5. Which visual elements are worth showing to routing or local Ollama/Qwen?

Thresholds come from ``settings.yaml`` via ``DocumentFeatureExtractionConfig``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from ...contracts.configurations.pipeline_config import (
    DocumentFeatureExtractionConfig,
    PDFFeatureExtractionConfig,
)
from ...contracts.exceptions import DocumentError
from .engine_format_support import get_engine_format_support
from .models import (
    DocumentFeatureProfile,
    FeatureDocumentType,
    TableEvidence,
    TextEvidence,
    VisualCandidate,
    VisualCandidateKind,
    VisualEvidence,
)
from .requirement_inference import infer_requirements
from .text_patterns import compact_text, contains_figure_caption, count_figure_caption_lines

if TYPE_CHECKING:
    import fitz

logger = logging.getLogger(__name__)


@dataclass
class PdfFeatureTotals:
    """Running totals collected while scanning all PDF pages."""

    total_text_characters: int = 0
    page_numbers_with_text: set[int] = field(default_factory=set)
    total_page_area: float = 0.0

    table_count: int = 0
    large_table_count: int = 0
    page_numbers_with_tables: set[int] = field(default_factory=set)

    embedded_image_count: int = 0
    large_embedded_image_count: int = 0
    vector_drawing_count: int = 0
    captioned_visual_count: int = 0
    page_numbers_with_visuals: set[int] = field(default_factory=set)

    visual_routing_candidates: list[VisualCandidate] = field(default_factory=list)


def extract_pdf_features(
    path: Path,
    config: DocumentFeatureExtractionConfig | None = None,
) -> DocumentFeatureProfile:
    """
    Extract deterministic feature evidence from one PDF.

    The flow is intentionally linear:
    open the PDF, visit each page, collect evidence, then build the final
    ``DocumentFeatureProfile`` consumed by the capability router.
    """
    pdf_settings = (config or DocumentFeatureExtractionConfig()).pdf
    pdf_document = open_pdf_with_pymupdf(path)
    total_pages = max(len(pdf_document), 1)
    feature_totals = PdfFeatureTotals()

    for page_number in range(1, total_pages + 1):
        scan_one_pdf_page(
            pdf_document=pdf_document,
            page_number=page_number,
            settings=pdf_settings,
            totals=feature_totals,
        )

    logger.debug(
        "PDF feature extraction complete: path=%s pages=%d chars=%d tables=%d images=%d",
        path.name,
        total_pages,
        feature_totals.total_text_characters,
        feature_totals.table_count,
        feature_totals.embedded_image_count,
    )

    return build_pdf_feature_profile(
        total_pages=total_pages,
        totals=feature_totals,
        settings=pdf_settings,
    )


def scan_one_pdf_page(
    *,
    pdf_document: fitz.Document,
    page_number: int,
    settings: PDFFeatureExtractionConfig,
    totals: PdfFeatureTotals,
) -> None:
    """
    Scan one PDF page in the same order a person would inspect it.

    Step 1: load the page.
    Step 2: read text and page size.
    Step 3: find nearby figure-caption context.
    Step 4: collect text evidence.
    Step 5: collect table evidence.
    Step 6: collect embedded-image evidence.
    Step 7: collect vector-drawing evidence.
    """
    page = load_pdf_page_by_number(pdf_document, page_number)
    page_text = read_page_text(page)
    page_area = get_page_area(page)
    nearby_figure_caption = find_first_figure_caption_line(page_text)

    totals.total_page_area += page_area

    collect_text_evidence_from_page(page_number, page_text, totals)
    collect_table_evidence_from_page(
        page_number=page_number,
        page=page,
        page_area=page_area,
        nearby_figure_caption=nearby_figure_caption,
        settings=settings,
        totals=totals,
    )
    collect_embedded_image_evidence_from_page(
        page_number=page_number,
        page=page,
        page_area=page_area,
        nearby_figure_caption=nearby_figure_caption,
        settings=settings,
        totals=totals,
    )
    collect_vector_drawing_evidence_from_page(
        page_number=page_number,
        page=page,
        nearby_figure_caption=nearby_figure_caption,
        settings=settings,
        totals=totals,
    )


def load_pdf_page_by_number(pdf_document: fitz.Document, page_number: int) -> fitz.Page:
    """Load a 1-based page number from PyMuPDF's 0-based document index."""
    return pdf_document[page_number - 1]


def read_page_text(page: fitz.Page) -> str:
    """Read native text from a PDF page as a plain string."""
    return str(page.get_text("text") or "")


def collect_text_evidence_from_page(
    page_number: int,
    page_text: str,
    totals: PdfFeatureTotals,
) -> None:
    """Add native text and caption evidence from one page."""
    totals.total_text_characters += len(page_text)
    totals.captioned_visual_count += count_figure_caption_lines(page_text)
    if page_text.strip():
        totals.page_numbers_with_text.add(page_number)


def collect_table_evidence_from_page(
    *,
    page_number: int,
    page: fitz.Page,
    page_area: float,
    nearby_figure_caption: str | None,
    settings: PDFFeatureExtractionConfig,
    totals: PdfFeatureTotals,
) -> None:
    """Add table-box evidence from one page."""
    table_boxes = find_table_boxes_on_page(page)
    if not table_boxes:
        return

    totals.table_count += len(table_boxes)
    totals.page_numbers_with_tables.add(page_number)

    for table_box in table_boxes:
        page_area_fraction = calculate_page_area_fraction(table_box, page_area)
        if (
            page_area_fraction is not None
            and page_area_fraction >= settings.large_visual_area_ratio
        ):
            totals.large_table_count += 1

        totals.visual_routing_candidates.append(
            VisualCandidate(
                kind=VisualCandidateKind.TABLE,
                page_number=page_number,
                area_ratio=page_area_fraction,
                nearby_text=nearby_figure_caption,
                evidence=["table-shaped region detected by PyMuPDF page.find_tables()"],
            )
        )


def collect_embedded_image_evidence_from_page(
    *,
    page_number: int,
    page: fitz.Page,
    page_area: float,
    nearby_figure_caption: str | None,
    settings: PDFFeatureExtractionConfig,
    totals: PdfFeatureTotals,
) -> None:
    """Add embedded raster image evidence from one page."""
    embedded_image_references = page.get_images(full=True)
    if not embedded_image_references:
        return

    totals.embedded_image_count += len(embedded_image_references)
    totals.page_numbers_with_visuals.add(page_number)

    for embedded_image_reference in embedded_image_references:
        image_xref = embedded_image_reference[0]
        for image_box in page.get_image_rects(image_xref):
            page_area_fraction = calculate_page_area_fraction(image_box, page_area)
            if (
                page_area_fraction is None
                or page_area_fraction < settings.image_candidate_min_area_ratio
            ):
                continue

            if page_area_fraction >= settings.large_visual_area_ratio:
                totals.large_embedded_image_count += 1

            totals.visual_routing_candidates.append(
                VisualCandidate(
                    kind=VisualCandidateKind.EMBEDDED_IMAGE,
                    page_number=page_number,
                    area_ratio=page_area_fraction,
                    nearby_text=nearby_figure_caption,
                    evidence=["embedded raster image object in PDF"],
                )
            )


def collect_vector_drawing_evidence_from_page(
    *,
    page_number: int,
    page: fitz.Page,
    nearby_figure_caption: str | None,
    settings: PDFFeatureExtractionConfig,
    totals: PdfFeatureTotals,
) -> None:
    """Add vector drawing evidence from one page."""
    drawing_count_on_page = len(page.get_drawings())
    totals.vector_drawing_count += drawing_count_on_page

    if drawing_count_on_page == 0:
        return

    totals.page_numbers_with_visuals.add(page_number)

    if drawing_count_on_page >= settings.vector_graphics_page_min_drawings:
        totals.visual_routing_candidates.append(
            VisualCandidate(
                kind=VisualCandidateKind.VECTOR_GRAPHICS,
                page_number=page_number,
                area_ratio=None,
                nearby_text=nearby_figure_caption,
                evidence=[
                    f"{drawing_count_on_page} vector drawing primitive(s) on page; "
                    f"configured threshold is {settings.vector_graphics_page_min_drawings}"
                ],
            )
        )


def build_pdf_feature_profile(
    *,
    total_pages: int,
    totals: PdfFeatureTotals,
    settings: PDFFeatureExtractionConfig,
) -> DocumentFeatureProfile:
    """Build the public PDF feature profile from collected evidence."""
    text_evidence = build_text_evidence(totals)
    table_evidence = build_table_evidence(totals)
    visual_evidence = build_visual_evidence(totals)
    strongest_visual_candidates = choose_visual_candidates_for_routing(
        totals.visual_routing_candidates,
        max_candidates_to_keep=settings.max_visual_candidates,
    )
    requirements = infer_requirements(
        text=text_evidence,
        tables=table_evidence,
        visuals=visual_evidence,
        visual_candidates=strongest_visual_candidates,
    )
    return DocumentFeatureProfile(
        file_type=FeatureDocumentType.PDF,
        page_or_unit_count=total_pages,
        text=text_evidence,
        tables=table_evidence,
        visuals=visual_evidence,
        visual_candidates=strongest_visual_candidates,
        format_support=get_engine_format_support(FeatureDocumentType.PDF),
        requirements=requirements,
    )


def build_text_evidence(totals: PdfFeatureTotals) -> TextEvidence:
    """Summarize native text evidence across the PDF."""
    return TextEvidence(
        total_characters=totals.total_text_characters,
        pages_or_units_with_text=len(totals.page_numbers_with_text),
        estimated_text_density=totals.total_text_characters / max(totals.total_page_area, 1.0),
        native_text_available=totals.total_text_characters > 0,
    )


def build_table_evidence(totals: PdfFeatureTotals) -> TableEvidence:
    """Summarize table evidence across the PDF."""
    return TableEvidence(
        count=totals.table_count,
        pages_or_units_with_tables=len(totals.page_numbers_with_tables),
        large_count=totals.large_table_count,
    )


def build_visual_evidence(totals: PdfFeatureTotals) -> VisualEvidence:
    """Summarize image, vector drawing, and caption evidence across the PDF."""
    return VisualEvidence(
        embedded_image_count=totals.embedded_image_count,
        large_embedded_image_count=totals.large_embedded_image_count,
        vector_graphics_count=totals.vector_drawing_count,
        chart_count=0,
        svg_count=0,
        pages_or_units_with_visuals=len(totals.page_numbers_with_visuals),
        captioned_visual_count=totals.captioned_visual_count,
    )


def choose_visual_candidates_for_routing(
    visual_candidates: list[VisualCandidate],
    *,
    max_candidates_to_keep: int,
) -> list[VisualCandidate]:
    """
    Keep the visual elements most useful for engine routing.

    The list may contain many table boxes, embedded images, and vector-heavy
    pages.  The router only needs the strongest examples.
    """
    ranked_candidates = sorted(
        visual_candidates,
        key=visual_candidate_routing_priority,
        reverse=True,
    )
    return ranked_candidates[:max_candidates_to_keep]


def visual_candidate_routing_priority(candidate: VisualCandidate) -> tuple[int, float]:
    """Score a visual candidate for routing relevance."""
    caption_bonus = 1 if candidate.nearby_text or candidate.caption_or_alt_text else 0
    evidence_count = len(candidate.evidence)
    page_area_fraction = candidate.area_ratio or 0.0
    return (caption_bonus + evidence_count, page_area_fraction)


def find_first_figure_caption_line(page_text: str) -> str | None:
    """
    Return the first line that looks like a figure/chart/diagram caption.

    This gives visual candidates nearby text context without asking a model to
    inspect the whole page.
    """
    for line in page_text.splitlines():
        if contains_figure_caption(line):
            return compact_text(line)
    return None


def find_table_boxes_on_page(page: fitz.Page) -> list[object]:
    """Return table bounding boxes found by PyMuPDF, or an empty list."""
    try:
        table_detection_result = page.find_tables()
    except Exception:
        logger.debug("page.find_tables() failed or is unavailable; skipping table detection")
        return []

    detected_tables = getattr(table_detection_result, "tables", []) or []
    return [
        detected_table.bbox
        for detected_table in detected_tables
        if getattr(detected_table, "bbox", None) is not None
    ]


def open_pdf_with_pymupdf(path: Path) -> fitz.Document:
    """Open a PDF with PyMuPDF and wrap library failures as DocumentError."""
    try:
        import fitz  # noqa: PLC0415
    except ImportError as exc:
        raise DocumentError(
            "PyMuPDF is required for PDF feature extraction. Install it with: pip install pymupdf",
            context={"path": str(path)},
        ) from exc

    try:
        return fitz.open(str(path))
    except Exception as exc:
        raise DocumentError(
            f"Failed to open PDF for feature extraction: {path.name}",
            context={"path": str(path)},
        ) from exc


def get_page_area(page: fitz.Page) -> float:
    """Return page area in PDF coordinate units, never below 1.0."""
    page_box = page.rect
    return max(float(page_box.width * page_box.height), 1.0)


def calculate_page_area_fraction(box: object, page_area: float) -> float | None:
    """Return how much of the page a rectangle-like box occupies."""
    try:
        if hasattr(box, "width") and hasattr(box, "height"):
            box_with_size = cast(Any, box)
            box_area = float(box_with_size.width * box_with_size.height)
        else:
            left, top, right, bottom = cast(tuple[float, float, float, float], box)
            box_area = max(float(right - left), 0.0) * max(float(bottom - top), 0.0)
    except Exception:
        logger.debug("Could not compute page area fraction for box %r", box)
        return None

    return box_area / max(page_area, 1.0)
