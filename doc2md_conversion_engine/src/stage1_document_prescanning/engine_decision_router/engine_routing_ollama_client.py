"""
engine_routing_ollama_client.py
========================
Pure HTTP client for a local Ollama model.

This module is infrastructure only.  It knows nothing about documents,
routing decisions, or feature profiles.  Its only job is:

    1. Accept a prompt string.
    2. POST it to the Ollama ``/api/generate`` endpoint.
    3. Unpack the response envelope.
    4. Return the model's raw text output.

What belongs here
-----------------
- The HTTP call.
- Envelope unpacking (``response`` / ``thinking`` field extraction).
- Network error wrapping into ``DocumentError``.
- The config class that names the Ollama server and model — sourced from
  ``contracts/configurations/pipeline_config.OllamaClientConfig`` so that
  connection settings live in ``settings.yaml`` alongside every other
  pipeline setting, not hardcoded in application code.

What does NOT belong here
--------------------------
- Prompt construction.          → ``system_prompt.py``
- Feature evidence packaging.   → ``feature_message_builder.py``
- Decision parsing/validation.  → ``engine_routing_agent.py``

Why stdlib HTTP?
----------------
``urllib`` ships with Python everywhere.  The Ollama endpoint is local so
there is no need for connection pooling, async I/O, or retry middleware.
If the project later adopts ``httpx``, this is the one file to change.
"""

from __future__ import annotations

import json
from urllib.error import URLError
from urllib.request import Request, urlopen

from ...contracts.configurations.pipeline_config import OllamaClientConfig
from ...contracts.exceptions import DocumentError


class OllamaClient:
    """
    Thin HTTP client for a local Ollama ``/api/generate`` endpoint.

    Parameters
    ----------
    config:
        Connection and model settings.  When omitted, defaults come from
        ``OllamaClientConfig`` which reads ``engine_routing.ollama_client``
        in ``settings.yaml``.

    Usage
    -----
    ::

        client = OllamaClient()
        raw_text = client.generate(prompt="Decide which engine to use...")
    """

    def __init__(self, config: OllamaClientConfig | None = None) -> None:
        self._config = config or OllamaClientConfig()

    def generate(self, prompt: str) -> str:
        """
        Send ``prompt`` to Ollama and return the model's raw text response.

        The caller is responsible for constructing a complete, self-contained
        prompt string.  This method adds no framing, no schema, no document
        evidence — it only wraps the prompt in the Ollama API envelope.

        Raises
        ------
        DocumentError:
            If Ollama is unreachable, returns a non-JSON envelope, or the
            envelope contains no text response.
        """
        raw_envelope = self._post_to_ollama(prompt)
        return self._extract_response_text(raw_envelope)

    def _post_to_ollama(self, prompt: str) -> str:
        """POST the request body to Ollama and return the raw API response."""
        request_body = json.dumps(
            {
                "model": self._config.model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "think": False,
                "options": {"temperature": 0},
            }
        ).encode("utf-8")
        request = Request(
            f"{self._config.base_url.rstrip('/')}/api/generate",
            data=request_body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._config.timeout_seconds) as response:
                return response.read().decode("utf-8")
        except URLError as exc:
            raise DocumentError(
                "Failed to reach local Ollama.",
                context={
                    "base_url": self._config.base_url,
                    "model": self._config.model,
                },
            ) from exc

    def _extract_response_text(self, raw_envelope: str) -> str:
        """Unpack Ollama's JSON envelope and return the model's text."""
        try:
            envelope = json.loads(raw_envelope)
        except json.JSONDecodeError as exc:
            raise DocumentError(
                "Ollama returned a non-JSON API envelope.",
                context={"response": raw_envelope},
            ) from exc

        response_text = envelope.get("response") or envelope.get("thinking")
        if not isinstance(response_text, str) or not response_text.strip():
            raise DocumentError(
                "Ollama response envelope did not contain a text response.",
                context={"response": raw_envelope},
            )
        return response_text
