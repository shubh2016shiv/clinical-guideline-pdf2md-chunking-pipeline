"""
context_assembly.py
===================
Assembles the model's entire view of a document before the routing decision.

Context assembly is the step where deterministic feature evidence is gathered,
structured, and formatted into the input window the local Ollama model reasons
over.  The quality of the routing decision is directly proportional to how well
this context is assembled.

Why Markdown and not raw JSON?
-------------------------------
LLMs are trained on Markdown — GitHub, documentation, Stack Overflow, blog
posts.  When the model sees a section heading (``##``) followed by a table, it
has billions of training examples telling it exactly what that structure means.
When it sees raw JSON it burns attention tokens parsing syntax (``{``, ``"``,
``:``, ``}``) before it can reason about the content.

Concretely:
- ``## Visual Candidates`` as a heading signals "these are the items to
  examine" far more strongly than ``"candidates_to_inspect": [...]`` buried in
  a nested object.
- A Markdown table collapses label-value relationships into a format the model
  already associates with structured comparison.
- The required output schema in a fenced code block signals "this is a
  technical contract" in the same way a developer reading a README would
  understand it.

Why tabulate?
-------------
``tabulate`` with ``tablefmt="github"`` produces GitHub-flavored Markdown
tables (``| col | col |`` with a ``|---|---|`` separator row).  This is the
most common table format in the model's training data.  Writing it by hand
would be fragile and unreadable; tabulate handles alignment and escaping.

What goes into the user message
--------------------------------
1. **Document overview** — one table: file type, page count, native text flag,
   total characters.
2. **Table evidence** — one table: count, pages with tables, large tables.
3. **Visual evidence** — one table: image/SVG/vector/chart counts and pages.
4. **Format support** — one table: which engines natively support this format.
5. **Pre-computed requirements** — one table: the deterministic capability
   flags already inferred before the model is called.  This tells the model
   what the rule-based layer already decided so it can focus on the edge cases
   that rules cannot resolve.
6. **Visual candidates** — one table per candidate, showing kind, location,
   size, caption, and the evidence chain that caused it to be flagged.
7. **Required output schema** — fenced JSON code block immediately before the
   end so the model sees the contract it must satisfy right after all the
   evidence.
"""

from __future__ import annotations

import json

from tabulate import tabulate

from ..doc_feature_extraction.models import DocumentFeatureProfile, VisualCandidate
from .system_prompt import REQUIRED_OUTPUT_SCHEMA


def build_routing_user_message(
    profile: DocumentFeatureProfile,
    *,
    max_candidates: int = 5,
) -> str:
    """
    Translate a ``DocumentFeatureProfile`` into a Markdown user message.

    Returns a single Markdown string ready to be appended after the system
    message and sent to the Ollama ``/api/generate`` endpoint.

    ``max_candidates`` caps how many visual candidates are included.  The
    candidates were already ranked by the feature extractor (size, label
    presence, evidence count), so the first N are always the most relevant.
    """
    selected_candidates = profile.visual_candidates[:max_candidates]

    sections: list[str] = [
        _build_document_overview_section(profile),
        _build_table_evidence_section(profile),
        _build_visual_evidence_section(profile),
        _build_format_support_section(profile),
        _build_requirements_section(profile),
        _build_candidates_section(selected_candidates),
        _build_output_schema_section(),
    ]
    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Section builders — one per logical block in the user message
# ---------------------------------------------------------------------------


def _build_document_overview_section(profile: DocumentFeatureProfile) -> str:
    rows = [
        ["File type", profile.file_type.value],
        ["Pages / units", profile.page_or_unit_count],
        ["Native text available", _yes_no(profile.text.native_text_available)],
        ["Total characters", f"{profile.text.total_characters:,}"],
        ["Estimated text density", f"{profile.text.estimated_text_density:.1f} chars/page"],
    ]
    return "## Document Overview\n\n" + tabulate(rows, headers=["Property", "Value"], tablefmt="github")


def _build_table_evidence_section(profile: DocumentFeatureProfile) -> str:
    t = profile.tables
    rows = [
        ["Total tables found", t.count],
        ["Pages with tables", t.pages_or_units_with_tables],
        ["Large tables", t.large_count],
    ]
    return "## Table Evidence\n\n" + tabulate(rows, headers=["Metric", "Value"], tablefmt="github")


def _build_visual_evidence_section(profile: DocumentFeatureProfile) -> str:
    v = profile.visuals
    rows = [
        ["Embedded images", v.embedded_image_count],
        ["Large embedded images", v.large_embedded_image_count],
        ["Vector graphics / drawings", v.vector_graphics_count],
        ["Charts", v.chart_count],
        ["SVG elements", v.svg_count],
        ["Pages with visuals", v.pages_or_units_with_visuals],
        ["Captioned visuals", v.captioned_visual_count],
    ]
    return "## Visual Evidence\n\n" + tabulate(rows, headers=["Metric", "Value"], tablefmt="github")


def _build_format_support_section(profile: DocumentFeatureProfile) -> str:
    fs = profile.format_support
    rows = [
        ["Docling", _yes_no(fs.docling_supported)],
        ["MinerU", _yes_no(fs.mineru_supported)],
    ]
    return "## Engine Format Support\n\n" + tabulate(rows, headers=["Engine", "Supports this format"], tablefmt="github")


def _build_requirements_section(profile: DocumentFeatureProfile) -> str:
    r = profile.requirements
    rows = [
        ["Needs text extraction", _yes_no(r.needs_text_extraction)],
        ["Needs reading order reconstruction", _yes_no(r.needs_reading_order_reconstruction)],
        ["Needs table reconstruction", _yes_no(r.needs_table_reconstruction)],
        ["Needs visual asset extraction", _yes_no(r.needs_visual_asset_extraction)],
        ["Needs visual semantic explanation", _yes_no(r.needs_visual_semantic_explanation)],
        ["Needs local VLM adjudication", _yes_no(r.needs_local_vlm_adjudication)],
    ]
    return (
        "## Pre-computed Requirements\n\n"
        "_These flags were inferred deterministically before you were called. "
        "Use them as a starting point, not a final answer._\n\n"
        + tabulate(rows, headers=["Requirement", "Flagged"], tablefmt="github")
    )


def _build_candidates_section(candidates: list[VisualCandidate]) -> str:
    if not candidates:
        return "## Visual Candidates\n\n_No visual candidates were flagged for this document._"

    blocks: list[str] = ["## Visual Candidates\n"]
    for index, candidate in enumerate(candidates):
        rows = [
            ["Kind", candidate.kind.value],
            ["Page / location", candidate.page_number or candidate.location_label or "—"],
            ["Area (fraction of page)", f"{candidate.area_ratio:.1%}" if candidate.area_ratio is not None else "unknown"],
            ["Caption / alt text", candidate.caption_or_alt_text or "—"],
            ["Nearby text", candidate.nearby_text or "—"],
            ["Evidence", " | ".join(candidate.evidence) if candidate.evidence else "—"],
        ]
        block = (
            f"### Candidate {index}\n\n"
            + tabulate(rows, headers=["Field", "Value"], tablefmt="github")
        )
        blocks.append(block)

    return "\n\n".join(blocks)


def _build_output_schema_section() -> str:
    schema_json = json.dumps(REQUIRED_OUTPUT_SCHEMA, indent=2)
    return (
        "## Required Output Schema\n\n"
        "Return **only** a JSON object with this exact structure. "
        "No explanation, no preamble, no trailing text.\n\n"
        f"```json\n{schema_json}\n```"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"
