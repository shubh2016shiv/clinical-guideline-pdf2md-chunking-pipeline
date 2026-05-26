"""
contracts/pipeline_domain_types.py
===================================
Immutable value objects (Pydantic models) that flow between pipeline stages.

These types are the shared language of the pipeline — every stage produces
or consumes them.  A new developer can understand the full data model by
reading this one file without opening any stage-specific code.

Data flow at a glance
---------------------
Stage 1  →  PageProfile, EngineClassification
Stage 2  →  Figure, Table, PageResult          (one PageResult per page)
Stage 3  →  consumes Figure; LLM summaries stored in the result cache
Stage 4  →  ConversionSummary                  (final output metadata)

Why Pydantic models (not plain dataclasses)?
--------------------------------------------
  - Runtime field validation catches bad data at stage boundaries early.
  - Built-in JSON serialisation is required for checkpoint persistence.
  - ``ConfigDict(frozen=True)`` makes instances immutable so one stage
    cannot accidentally mutate data that belongs to another stage.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ExtractionEngine(str, Enum):
    """
    The two supported conversion engines.

    Inheriting from ``str`` means enum values serialise as plain strings
    (``"mineru"`` / ``"docling"``) in JSON and YAML rather than the Python
    repr ``ExtractionEngine.MINERU``.
    """

    MINERU = "mineru"
    DOCLING = "docling"


class MinerUBackend(str, Enum):
    """
    Processing backend used when MinerU is the active engine.

    VLM
        Vision-Language Model running on GPU via vLLM or LMDeploy.
        Highest accuracy for complex diagrams and multi-column layouts.
        Requires a CUDA-capable GPU.

    PIPELINE
        Rule-based PDF pipeline, CPU-only.
        Slower but works without a GPU (OmniDocBench score: 86.2 / 100).

    Jargon — VLM (Vision-Language Model): a neural network that jointly
    understands images and text.  MinerU uses it to accurately read complex
    page layouts (multi-column, flowcharts) that confuse rule-based parsers.
    """

    AUTO = "auto"      # Resolved at engine startup: VLM if GPU available, PIPELINE otherwise.
    VLM = "vlm"
    PIPELINE = "pipeline"


class DocumentType(str, Enum):
    """Source document formats that the pipeline accepts."""

    PDF = "pdf"
    DOCX = "docx"
    PPTX = "pptx"
    HTML = "html"


# ---------------------------------------------------------------------------
# Stage 1 outputs
# ---------------------------------------------------------------------------


class PageProfile(BaseModel):
    """
    Lightweight structural fingerprint of a single page, produced by the
    pre-scan stage (pypdfium2, CPU-only, < 2 s total for an entire document).

    These profiles feed the complexity classifier which decides which engine
    to use.  No GPU work happens until after all profiles are collected.
    """

    model_config = ConfigDict(frozen=True)

    page_number: int = Field(..., ge=1, description="1-based page index.")

    is_multi_column: bool = Field(
        ...,
        description=(
            "True when the X-axis projection of text blocks shows two or more "
            "distinct column bands.  Multi-column layouts confuse simple "
            "text-flow parsers; MinerU handles them natively."
        ),
    )

    has_diagrams: bool = Field(
        ...,
        description=(
            "True when image_count > 2 AND text_density < 0.05.  "
            "Diagrams need the vision LLM in Stage 3 — text-only engines "
            "can only extract a bounding box without semantic understanding."
        ),
    )

    has_large_tables: bool = Field(
        ...,
        description=(
            "True when wide text blocks spanning more than 60 % of page width "
            "are detected.  Large tables often span pages and need the "
            "cross-page table merger in the assembler."
        ),
    )

    text_density: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description=(
            "Ratio of character count to page area (pts²).  "
            "Values below 0.02 indicate the page is mostly images or whitespace."
        ),
    )


class EngineClassification(BaseModel):
    """
    Routing decision produced by the complexity classifier after analysing
    all ``PageProfile`` instances for a document.

    The classifier computes a weighted complexity score and maps it to an
    engine + backend pair.  Both the score and the human-readable reason are
    persisted in the checkpoint so they can be replayed on resume.
    """

    model_config = ConfigDict(frozen=True)

    engine: ExtractionEngine = Field(
        ...,
        description="Engine selected for Stage 2 extraction.",
    )

    backend: MinerUBackend | None = Field(
        default=None,
        description=(
            "MinerU processing backend.  None when engine is Docling because "
            "Docling has no backend concept."
        ),
    )

    complexity_score: float = Field(
        ...,
        ge=0.0,
        description=(
            "Weighted aggregate score computed from PageProfile flags.  "
            "score >= 2.0  →  MinerU VLM  |  "
            "0.5 <= score < 2.0  →  MinerU pipeline  |  "
            "score < 0.5  →  Docling"
        ),
    )

    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Classifier confidence in this routing decision, in the range 0–1.",
    )

    reason: str = Field(
        ...,
        description=(
            "Human-readable explanation logged at pipeline startup.  "
            "Example: '42% of pages are multi-column with diagrams → MinerU VLM'."
        ),
    )


# ---------------------------------------------------------------------------
# Stage 2 outputs  (one PageResult per page)
# ---------------------------------------------------------------------------


class Figure(BaseModel):
    """
    A non-text visual element (diagram, flowchart, anatomical illustration)
    extracted from a single page during Stage 2.

    When a figure is found the raw image is written to disk and a short
    placeholder token is embedded in the page markdown.  Stage 3 resolves
    that token asynchronously by sending the image to the vision LLM.

    Token format
    ------------
    ``${FIG:<document_id>:<page_number>:<index_on_page>}``

    Example: ``${FIG:sha256abc:042:0}``

    Jargon — deferred token resolution
        Instead of blocking extraction to wait for the LLM, we write a
        short placeholder string (token) immediately and let the LLM work
        concurrently in the background.  The assembler substitutes real
        summaries once they are available, keeping GPU extraction at full
        speed.
    """

    model_config = ConfigDict(frozen=True)

    token: str = Field(
        ...,
        description=(
            "Unique placeholder string embedded in the page markdown.  "
            "Stage 4 replaces it with the vision LLM summary."
        ),
    )

    page_number: int = Field(..., ge=1)

    index_on_page: int = Field(
        ...,
        ge=0,
        description="0-based position of this figure among all figures on the page.",
    )

    image_path: Path = Field(
        ...,
        description="Absolute path to the extracted PNG written to disk in Stage 2.",
    )

    sha256: str = Field(
        ...,
        description=(
            "SHA-256 hash of the raw image bytes.  "
            "Stage 3 uses this to skip LLM calls for figures that were already "
            "summarised in a previous run (deduplication cache hit)."
        ),
    )

    @field_validator("token")
    @classmethod
    def _validate_token_format(cls, v: str) -> str:
        if not (v.startswith("${FIG:") and v.endswith("}")):
            raise ValueError(
                f"Figure token must match ${{FIG:<doc_id>:<page>:<index>}}, got: {v!r}"
            )
        return v


class Table(BaseModel):
    """
    A tabular element extracted from a single page.

    Clinical guidelines frequently have tables that span multiple pages —
    the header row appears on page N and data rows continue on page N+1.
    The ``is_fragment`` flag tells the assembler to buffer this table and
    wait for its continuation before emitting the merged result.

    Deferred assembly via a token
    -----------------------------
    Like figures, a table is lifted out of the page Markdown during Stage 2 and
    replaced by a ``token`` placeholder; the table's own Markdown is carried here.
    Stage 4 substitutes the token with the table's final Markdown — merged first
    when the table spans pages. Anchoring the position with a token (rather than
    leaving the table inline) means Stage 4 reassembles by token lookup, never by
    fragile string-matching of table text inside the page.

    Token format
    ------------
    ``${TBL:<document_id>:<page_number>:<index_on_page>}``

    Example: ``${TBL:sha256abc:042:0}``
    """

    model_config = ConfigDict(frozen=True)

    token: str = Field(
        ...,
        description=(
            "Unique placeholder string embedded in the page Markdown in place of "
            "this table.  Stage 4 replaces it with the table's (possibly merged) "
            "Markdown."
        ),
    )

    page_number: int = Field(..., ge=1)

    markdown: str = Field(
        ...,
        description="Partial or complete table rendered as GitHub-flavoured Markdown.",
    )

    is_fragment: bool = Field(
        default=False,
        description=(
            "True when this table continues on the next page.  "
            "The assembler buffers it and waits for the continuation "
            "(the next page starts with a header-less table row)."
        ),
    )

    start_page: int = Field(
        ...,
        ge=1,
        description=(
            "The page on which this table began.  May differ from ``page_number`` "
            "when this is a continuation fragment of a multi-page table."
        ),
    )

    @field_validator("token")
    @classmethod
    def _validate_token_format(cls, v: str) -> str:
        if not (v.startswith("${TBL:") and v.endswith("}")):
            raise ValueError(
                f"Table token must match ${{TBL:<doc_id>:<page>:<index>}}, got: {v!r}"
            )
        return v


class PageResult(BaseModel):
    """
    Everything the pipeline knows about a single extracted page after Stage 2.

    Produced by whichever engine processed the page and yielded downstream
    to Stage 4 via an async generator.  Stage 4 consumes an ordered stream
    of these to build the final document.

    The ``markdown_with_tokens`` field contains the raw page content with
    ``${FIG:...}`` placeholders where figures were found.  Stage 4 waits
    for every token on a page to resolve before writing that page's output.
    """

    model_config = ConfigDict(frozen=True)

    page_number: int = Field(..., ge=1)

    engine_used: ExtractionEngine = Field(
        ...,
        description="The engine that processed this page.",
    )

    is_degraded: bool = Field(
        default=False,
        description=(
            "True when the fallback engine (Docling) was used instead of the "
            "primary engine (MinerU).  Emitted as a pipeline metric so operators "
            "can quantify accuracy impact on a per-document basis."
        ),
    )

    markdown_with_tokens: str = Field(
        ...,
        description=(
            "Page content as Markdown with ``${FIG:...}`` tokens where figures appear.  "
            "Intermediate form — the assembler replaces every token with the "
            "vision LLM summary before writing the final output."
        ),
    )

    figures: list[Figure] = Field(
        default_factory=list,
        description="All figures extracted from this page, in document order.",
    )

    tables: list[Table] = Field(
        default_factory=list,
        description="All tables (or table fragments) found on this page.",
    )

    duration_ms: int = Field(
        ...,
        ge=0,
        description="Wall-clock extraction time in milliseconds for this page.",
    )


# ---------------------------------------------------------------------------
# Top-level job descriptor
# ---------------------------------------------------------------------------


class ConversionJob(BaseModel):
    """
    Describes a single document conversion request.

    Created at pipeline startup and passed through the orchestrator to all
    stages so every component has access to job identity and output location
    without relying on global state.

    ``total_pages`` starts as ``None`` because the page count is not known
    until the Stage 1 prescan actually opens the document.
    """

    # Not frozen — the orchestrator sets ``total_pages`` after prescan.
    model_config = ConfigDict(frozen=False)

    job_id: str = Field(
        ...,
        description=(
            "SHA-256 hash of the document's raw bytes.  Used as the checkpoint "
            "filename key and as the document_id segment inside figure tokens."
        ),
    )

    document_path: Path = Field(
        ...,
        description="Absolute path to the source document.",
    )

    document_type: DocumentType = Field(
        ...,
        description="Format of the source document (pdf, docx, pptx, html).",
    )

    output_dir: Path = Field(
        ...,
        description=(
            "Directory where all outputs are written: page markdown files, "
            "extracted figure PNGs, and the final assembled Markdown."
        ),
    )

    total_pages: int | None = Field(
        default=None,
        description="Set by the orchestrator after Stage 1 prescan.  None until then.",
    )

    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp when the job was created.",
    )


# ---------------------------------------------------------------------------
# Final output metadata  (produced by Stage 4)
# ---------------------------------------------------------------------------


class ConversionSummary(BaseModel):
    """
    Metadata about a completed conversion job, produced at the end of Stage 4.

    This is not the full Markdown content (that is streamed incrementally to
    disk) — only the numbers and paths an operator or automated test needs
    to verify the run succeeded and measure its quality.
    """

    model_config = ConfigDict(frozen=True)

    job_id: str

    output_markdown_path: Path = Field(
        ...,
        description="Absolute path to the final assembled Markdown file on disk.",
    )

    total_pages: int

    figures_summarized: int = Field(
        ...,
        description="Figures that received a vision LLM summary successfully.",
    )

    figures_deduplicated: int = Field(
        ...,
        description=(
            "Figures skipped because their SHA-256 was already in the "
            "deduplication cache from a previous run or an earlier page in "
            "this run."
        ),
    )

    figures_failed: int = Field(
        ...,
        description=(
            "Figures replaced with the degraded placeholder because they timed "
            "out or hit the poison-pill retry limit."
        ),
    )

    engines_used: list[ExtractionEngine] = Field(
        ...,
        description=(
            "All engines that processed at least one page.  Normally a single "
            "entry; both engines appear if the circuit breaker tripped and "
            "Docling handled the remaining windows."
        ),
    )

    total_duration_seconds: float

    completed_at: datetime = Field(default_factory=datetime.utcnow)
