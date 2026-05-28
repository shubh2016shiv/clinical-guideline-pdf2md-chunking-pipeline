"""
stage3_figure_summarization/figure_summarization_prompt.py
===========================================================
Single source of truth for the Stage 3 system prompt.

The prompt asks the local Qwen-VL VLM for **plain insertion-ready Markdown**
(no JSON wrapping, no schema-constrained decode). This is the empirically-
proven approach in ``ollama_qwen_image_summary_check.py``: small quantized
VLMs handle plain-text generation reliably, but combining
``format=<json schema>`` with thinking mode on a 4B model regularly empties
the content channel and forces useless retries.

Trade-off, taken consciously
----------------------------
Asking for Markdown gives up *model-side classification*: the response is no
longer a structured ``{figure_type, rendering_strategy, ...}`` payload. We
recover the small amount of metadata Stage 4 actually needs (the
"is this decorative?" routing decision) from a content-side heuristic in
:mod:`ollama_vision_client`. The other enum fields on :class:`FigureSummary`
are filled with safe defaults (``FigureType.OTHER`` +
``RenderingStrategy.PLAIN_TEXT_EXPLANATION``) because Stage 4 does not
branch on them today — they exist for diagnostics, and a future revision
can recover them via a second classification call without touching this
file.

What the prompt still enforces (verbatim from the reference, kept tight):

* Output mirrors the figure's native structure — table → Markdown table,
  flowchart → ASCII diagram in a fenced block, code → fenced code block,
  chart → values extracted into a Markdown table, etc.
* Preserve every visible number, label, threshold, and unit *exactly*.
* Mark unreadable text as ``illegible`` — never guess.
* Recognise decoratives (logos / stock photos) and say so explicitly so the
  client's heuristic can flag them for Stage 4 to drop.
"""

from __future__ import annotations

from typing import ClassVar, Final

from ..contracts import DocumentDomain


# Module-level constant — defined once, referenced by ``PromptBuilder``.
# Wording is intentionally close to the reference script because that wording
# has been validated against real clinical samples to produce well-formed
# Markdown for tables, flowcharts, forest plots, and decoratives.
_BASE_SYSTEM_PROMPT: Final[str] = """\
You are a figure-to-Markdown converter for high-fidelity document conversion.

You will be shown EXACTLY ONE figure image extracted from a PDF.  You will
receive NO surrounding page text and NO caption — work from the pixels alone.

Produce only insertion-ready Markdown.  NO JSON.  NO preamble.  NO explanation
of what you are doing.  Your entire response IS the Markdown that will be
spliced into the document where the figure was.

Rules — pick the shape that matches the figure:
  * If it is a table → produce a Markdown table with all rows and columns.
  * If it is a flowchart, decision tree, or process diagram → produce an
    ASCII diagram inside a fenced ```text block.
  * If it is a chart or graph → extract all visible values into a Markdown
    table, then a one-line interpretation.
  * If it is code or pseudocode → produce a fenced code block with the
    correct language tag.
  * If it is a process or numbered steps → produce a numbered Markdown list.
  * If it is a conceptual diagram, hierarchy, or framework → produce indented
    bullet points; preserve any colour / shape semantics.
  * If it is a statistical plot (forest plot, KM curve, …) → report each
    subgroup / series with its point estimate, interval, and the axis
    direction-of-effect.
  * If it is a mathematical expression → use LaTeX display math ($$ … $$).
  * If it is a stock photo, logo, watermark, or other decorative element →
    write EXACTLY one short line beginning with "Decorative figure" and
    describe what it shows in plain text (e.g.
    "Decorative figure: stock photo of a clinician; no clinical content.").
  * For anything else → describe the visible content in plain Markdown prose.

Header:
  * Start the response with `### Figure: <visible title>` when a title is
    visible in the image, otherwise just `### Figure`.

Faithfulness (HARD RULES — these are clinical numbers):
  * Transcribe numbers, units, thresholds, and labels EXACTLY as shown.
  * If a value is too small or blurred to read, write `illegible` — do NOT
    guess and do NOT invent values.
  * Do NOT add clinical recommendations, conclusions, or knowledge that is
    not visually present in the image.
"""


class FigureSummarizationPromptBuilder:
    """
    Builds the system and user prompts for the Ollama vision client.

    Two construction-time inputs (document-domain hint, optional retry
    error history) are folded into a tiny builder class so the client
    can stay agnostic of prompt shape.
    """

    # Domain-specific addenda appended to the system prompt when the caller
    # has a domain hint.  Kept short — long addenda dilute the rules above.
    _DOMAIN_ADDENDA: ClassVar[dict[DocumentDomain, str]] = {
        DocumentDomain.CLINICAL: (
            "Domain context: clinical / medical document (guidelines, trial "
            "reports, textbooks).  Statistical plots may include Kaplan-Meier "
            "curves and forest plots; algorithm boxes often map criteria to "
            "management actions."
        ),
        DocumentDomain.SOFTWARE: (
            "Domain context: software / computer-science document.  Code, "
            "UML and architecture diagrams are especially common."
        ),
        DocumentDomain.SCIENTIFIC: (
            "Domain context: scientific research document.  Statistical "
            "plots, charts, and data tables are common; mathematical "
            "expressions appear often."
        ),
        DocumentDomain.FINANCIAL: (
            "Domain context: financial / business document.  Charts, data "
            "tables, and timelines are common."
        ),
        DocumentDomain.ENGINEERING: (
            "Domain context: engineering document.  Architecture diagrams, "
            "technical illustrations, and data tables are common."
        ),
        DocumentDomain.LEGAL: (
            "Domain context: legal document.  Tables, timelines, and "
            "workflow diagrams are common."
        ),
        DocumentDomain.EDUCATIONAL: (
            "Domain context: educational document.  All figure shapes are "
            "plausible; prioritise structural fidelity."
        ),
    }

    _INITIAL_USER_PROMPT: ClassVar[str] = "Convert this figure to Markdown now."

    def build_system_prompt(self, domain: DocumentDomain) -> str:
        """
        Return the full system prompt for the given document domain.

        ``DocumentDomain.AUTO`` returns the base prompt unchanged so the
        model infers domain from visual context.
        """
        addendum = self._DOMAIN_ADDENDA.get(domain, "")
        if not addendum:
            return _BASE_SYSTEM_PROMPT
        return _BASE_SYSTEM_PROMPT + "\n---\n" + addendum + "\n"

    def build_user_prompt(
        self,
        *,
        attempt_number: int = 1,
        previous_validation_errors: list[str] | None = None,
    ) -> str:
        """
        Build the user-turn message.

        Kept simple by design: the empty-content failure mode that
        prompt-feedback was meant to fix only appeared with
        ``format=<json schema>``.  Without it the model returns Markdown
        directly and "retry with the same prompt" is the correct response
        to a transient empty channel.
        """
        if attempt_number > 1:
            # Minor nudge on the very rare retry — keeps the user turn
            # idempotent without confusing a working model with verbose
            # error feedback.
            return (
                "The previous response was empty.  "
                "Convert this figure to Markdown now.  "
                "Return ONLY the Markdown — no preamble, no JSON."
            )
        return self._INITIAL_USER_PROMPT


__all__ = ["FigureSummarizationPromptBuilder"]
