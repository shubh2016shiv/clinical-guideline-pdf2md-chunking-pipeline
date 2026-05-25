"""
engine_decision_router
======================
Decides which conversion engine to use for a given document.

Flow
----
1. ``context_assembly``      — takes a ``DocumentFeatureProfile`` and assembles
   the model's entire view of the document as structured Markdown tables.

2. ``system_prompt``         — static system message and required output schema
   that tells the local LLM its role, constraints, and response format.

3. ``ollama_routing_client`` — pure HTTP client that sends a prompt to the local
   Ollama server and returns the model's raw text response.

4. ``engine_routing_agent``  — orchestrates steps 1–3: given a feature profile,
   it assembles the context, calls the client, and returns a validated
   ``OllamaVisualRoutingDecision``.

Typical usage
-------------
::

    from engine_decision_router import EngineRoutingAgent

    agent = EngineRoutingAgent()          # config from settings.yaml
    decision = agent.decide(profile)      # profile from doc_feature_extraction
    print(decision.recommended_structure_engine)
"""

from .context_assembly import build_routing_user_message
from .routing_agent import EngineRoutingAgent
from .ollama_client import OllamaClient
from .system_prompt import REQUIRED_OUTPUT_SCHEMA, SYSTEM_MESSAGE

__all__ = [
    "EngineRoutingAgent",
    "OllamaClient",
    "REQUIRED_OUTPUT_SCHEMA",
    "SYSTEM_MESSAGE",
    "build_routing_user_message",
]
