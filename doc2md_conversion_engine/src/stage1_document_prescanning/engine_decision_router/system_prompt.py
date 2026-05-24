"""
system_prompt.py
================
Static instructions that tell the local Ollama model what it is, what it must
decide, and the exact JSON shape it must return.

Nothing in this file changes between documents.  Every detail that is specific
to the document being routed goes into the *user* message, built in
``feature_message_builder.py``.

Why separate?
-------------
In any LLM-based system the system message is the "standing order" — it is
sent once per session and defines the model's role and output contract.  The
user message is the "current case" — it is filled in fresh for every document.
Keeping them in separate files makes it obvious which parts of the prompt are
fixed policy and which parts vary at runtime.

REQUIRED_OUTPUT_SCHEMA
----------------------
Describes the JSON the model must return.  It is embedded in the user message
(not here) so the model sees it immediately before the document evidence it
must reason about.  Defined here so it is co-located with the system message
that constrains the model's behaviour.

The schema fields:
- ``requires_visual_semantic_explanation`` — true if any candidate visual
  (chart, diagram, clinical pathway, etc.) needs prose explanation that plain
  OCR text cannot provide.
- ``recommended_structure_engine`` — which conversion engine to use:
    docling  → simple native text, HTML, or basic DOCX/PPTX
    mineru   → complex layout, large tables, chart-heavy PDF/PPTX
    either   → no strong reason to prefer one over the other
- ``visual_candidates_requiring_explanation`` — per-candidate verdict list.
  Each entry names the candidate index (same numbering as in the user message),
  whether it needs explanation, what type of visual it is, and a short reason
  grounded in what the model actually observed.
- ``confidence`` — the model's self-reported certainty from 0.0 (guessing) to
  1.0 (certain).  Used downstream to decide whether to accept or re-route.
"""

REQUIRED_OUTPUT_SCHEMA: dict[str, object] = {
    "requires_visual_semantic_explanation": "boolean",
    "recommended_structure_engine": "docling | mineru | either",
    "visual_candidates_requiring_explanation": [
        {
            "candidate_index": "integer",
            "needs_explanation": "boolean",
            "visual_type": "figure | chart | flow_diagram | table | decorative | unknown",
            "reason": "short string grounded in visible evidence",
        }
    ],
    "confidence": "number from 0.0 to 1.0",
}

SYSTEM_MESSAGE: str = (
    "You are a document conversion router. "
    "Your sole job is to inspect the document evidence provided in the user message "
    "and decide which conversion engine is most appropriate.\n"
    "\n"
    "Decision rules:\n"
    "- Use 'docling' for documents that are predominantly native text, "
    "simple HTML, or basic DOCX/PPTX with no meaningful visuals.\n"
    "- Use 'mineru' for complex PDF or PPTX layout, large multi-column tables, "
    "chart-heavy pages, clinical pathways, flow diagrams, or research figures "
    "where plain OCR text would lose essential meaning.\n"
    "- Use 'either' when there is no strong reason to prefer one engine.\n"
    "\n"
    "Visual classification rules:\n"
    "- Small logos, icons, headers, footers, and purely decorative images do NOT "
    "require visual semantic explanation unless the document text explicitly "
    "discusses them.\n"
    "- Charts, flow diagrams, clinical pathway diagrams, research figures, and "
    "technical diagrams DO require visual semantic explanation because OCR text "
    "alone cannot convey their meaning.\n"
    "\n"
    "Output rules:\n"
    "- Return ONLY a single JSON object matching the required_output_schema "
    "provided in the user message.\n"
    "- Do not include any text outside the JSON object.\n"
    "- Do not hallucinate visual content — base every reason on the evidence "
    "fields supplied for each candidate."
)
