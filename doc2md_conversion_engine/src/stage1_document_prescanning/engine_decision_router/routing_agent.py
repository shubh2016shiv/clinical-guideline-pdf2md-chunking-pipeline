"""
engine_routing_agent.py
=======================
Orchestrates the full engine routing decision for one document.

This is the top-level entry point for Stage 1 engine selection.  It wires
together the three pieces of the routing pipeline:

    DocumentFeatureProfile
        ↓  feature_message_builder.build_routing_user_message()
    user message dict  +  system_prompt.SYSTEM_MESSAGE
        ↓  OllamaClient.generate()
    raw LLM text
        ↓  _parse_routing_decision()
    OllamaVisualRoutingDecision

Why this is separate from ``OllamaClient``
------------------------------------------
``OllamaClient`` is infrastructure — it sends a prompt and gets back text.
It has no opinion about what the prompt contains or what the response means.

``EngineRoutingAgent`` is business logic — it knows about ``DocumentFeatureProfile``,
it knows to call ``build_routing_user_message``, it knows the response must
validate against ``OllamaVisualRoutingDecision``.

Keeping them separate means:
- The client can be swapped (e.g. different endpoint, different model) without
  touching routing logic.
- The routing logic can be unit-tested with a fake client that returns canned
  JSON without making any HTTP calls.
"""

from __future__ import annotations

import json

from ...contracts.configurations.pipeline_config import OllamaClientConfig
from ...contracts.exceptions import DocumentError
from ..doc_feature_extraction.models import (
    DocumentFeatureProfile,
    OllamaVisualRoutingDecision,
)
from .context_assembly import build_routing_user_message
from .engine_routing_ollama_client import OllamaClient
from .system_prompt import SYSTEM_MESSAGE


class EngineRoutingAgent:
    """
    Ask a local Ollama model to choose the best conversion engine for a document.

    Usage
    -----
    ::

        from engine_decision_router import EngineRoutingAgent

        agent = EngineRoutingAgent()
        decision = agent.decide(profile)
        print(decision.recommended_structure_engine)   # "docling" | "mineru" | "either"
    """

    def __init__(self, config: OllamaClientConfig | None = None) -> None:
        self._client = OllamaClient(config)
        self._max_candidates = (config or OllamaClientConfig()).max_candidates

    def decide(self, profile: DocumentFeatureProfile) -> OllamaVisualRoutingDecision:
        """
        Run the full routing pipeline for one document and return the decision.

        Step 1: Package the feature evidence into a structured user message.
        Step 2: Combine with the static system message and send to Ollama.
        Step 3: Parse and validate the raw text response into a typed decision.

        Raises
        ------
        DocumentError:
            If Ollama is unreachable, the response is malformed, or the JSON
            does not match the expected schema.
        """
        assembled_context = build_routing_user_message(
            profile,
            max_candidates=self._max_candidates,
        )
        prompt = _assemble_prompt(SYSTEM_MESSAGE, assembled_context)
        raw_response = self._client.generate(prompt)
        return _parse_routing_decision(raw_response)


def _assemble_prompt(system_message: str, assembled_context: str) -> str:
    """
    Combine the static system message and the assembled document context
    into a single prompt string for Ollama's ``/api/generate`` endpoint.

    ``/api/generate`` does not have a native system/user turn separation
    (unlike ``/api/chat``).  The system message is placed first so the model
    reads its standing orders before seeing the document evidence.
    """
    return f"{system_message}\n\n{assembled_context}"


def _parse_routing_decision(raw_response: str) -> OllamaVisualRoutingDecision:
    """
    Parse the model's raw text into a validated ``OllamaVisualRoutingDecision``.

    Tolerates accidental text before or after the JSON object — some models
    emit a brief preamble or trailing newline even when ``format: json`` is set.
    """
    try:
        parsed = json.loads(raw_response)
    except json.JSONDecodeError:
        start = raw_response.find("{")
        end = raw_response.rfind("}")
        if start < 0 or end <= start:
            raise DocumentError(
                "Ollama routing response contained no JSON object.",
                context={"response": raw_response},
            ) from None
        parsed = json.loads(raw_response[start : end + 1])

    if not isinstance(parsed, dict):
        raise DocumentError(
            "Ollama routing response was not a JSON object.",
            context={"response": raw_response},
        )

    try:
        return OllamaVisualRoutingDecision.model_validate(
            {**parsed, "raw_response": raw_response}
        )
    except Exception as exc:
        raise DocumentError(
            "Ollama routing response did not match the expected schema.",
            context={"response": raw_response},
        ) from exc
