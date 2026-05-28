"""
stage3_figure_summarization/ollama_vision_client.py
====================================================
Concrete :class:`AbstractVisionFigureClient` for the local Ollama VLM.

Output shape: **plain Markdown** (not schema-constrained JSON)
------------------------------------------------------------
An earlier iteration of this module asked Ollama for JSON via
``format=<json schema>`` and ran Pydantic validation retries against the
result.  On small quantized VLMs (``qwen3-vl:4b`` being our default) the
combination of structured-output decoding + thinking mode regularly
empties the content channel and adds tens of seconds of latency per
attempt — pushing every figure past the worker-pool timeout and
poison-pilling the whole document.

The proven-working approach (mirrored from
``ollama_qwen_image_summary_check.py``) is to ask for **plain Markdown**
and accept whatever the model emits.  The Markdown is exactly what Stage 4
needs to splice into the document; the only routing decision Stage 4
still depends on — *"is this decorative?"* — is recovered here from a
small content heuristic on the model's response.

Separation of concerns retained:

* The prompt is the only place wording lives — :mod:`figure_summarization_prompt`.
* Image preprocessing, the Ollama call, and the FigureSummary assembly
  are this module's concerns.
* Retries (transport), timeout, breaker, GPU lock, concurrency: still
  owned by the orchestrator / worker pool above.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from pathlib import Path
from typing import Any

import ollama
from PIL import Image, ImageOps, UnidentifiedImageError

from ..contracts import (
    AbstractVisionFigureClient,
    DocumentDomain,
    FigureSummarizationError,
    FigureSummary,
    LegibilityLevel,
    OllamaVisionClientConfig,
    RenderingStrategy,
)
from ..contracts.figure_summarization_types import FigureType
from .figure_summarization_prompt import FigureSummarizationPromptBuilder

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Image preprocessing
# ---------------------------------------------------------------------------


class _FigureImagePreprocessor:
    """
    Prepares figure PNGs for submission to the Ollama VLM.

    Operations (in order):
    1. Resolve and validate the source path.
    2. Open with Pillow; correct EXIF orientation.
    3. Normalise colour mode to RGB (composite alpha onto white).
    4. Downscale so the longest side is ≤ ``max_side_pixels``.
    5. Persist the result to a content-addressed PNG cache so repeated
       calls (resumes / dedup misses) skip the work.
    """

    _MIN_MAX_SIDE_PIXELS = 512  # below this, small clinical text is unreadable

    def __init__(self, *, max_side_pixels: int, cache_directory: Path) -> None:
        if max_side_pixels < self._MIN_MAX_SIDE_PIXELS:
            raise ValueError(
                f"max_side_pixels must be ≥ {self._MIN_MAX_SIDE_PIXELS} to "
                f"preserve legibility; got {max_side_pixels}."
            )
        self._max_side_pixels = max_side_pixels
        self._cache_directory = cache_directory

    def prepare(self, source_image_path: Path) -> Path:
        resolved = source_image_path.expanduser().resolve()
        if not resolved.exists():
            raise FigureSummarizationError(
                f"Figure image not found: {resolved}",
                context={"image_path": str(resolved)},
            )
        if not resolved.is_file():
            raise FigureSummarizationError(
                f"Figure image path is not a regular file: {resolved}",
                context={"image_path": str(resolved)},
            )
        try:
            with Image.open(resolved) as raw:
                oriented = ImageOps.exif_transpose(raw)
                rgb = self._to_rgb(oriented)
                downscaled = self._downscale(rgb)
                return self._write_cached(resolved, downscaled)
        except UnidentifiedImageError as exc:
            raise FigureSummarizationError(
                f"Unsupported or corrupt image: {resolved}",
                context={"image_path": str(resolved)},
            ) from exc
        except OSError as exc:
            raise FigureSummarizationError(
                f"Could not read image {resolved}: {exc}",
                context={"image_path": str(resolved)},
            ) from exc

    @staticmethod
    def _to_rgb(image: Image.Image) -> Image.Image:
        if image.mode in {"RGB", "L"}:
            return image.copy()
        if image.mode in {"RGBA", "LA"}:
            white = Image.new("RGB", image.size, "white")
            alpha = image.getchannel("A")
            white.paste(image.convert("RGB"), mask=alpha)
            return white
        return image.convert("RGB")

    def _downscale(self, image: Image.Image) -> Image.Image:
        width, height = image.size
        longest = max(width, height)
        if longest <= self._max_side_pixels:
            return image.copy()
        scale = self._max_side_pixels / longest
        new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
        logger.debug(
            "stage3.image.downscaled from=%dx%d to=%dx%d limit=%d",
            width, height, new_size[0], new_size[1], self._max_side_pixels,
        )
        return image.resize(new_size, Image.Resampling.LANCZOS)

    def _write_cached(self, source_path: Path, prepared: Image.Image) -> Path:
        self._cache_directory.mkdir(parents=True, exist_ok=True)
        stat = source_path.stat()
        key_input = (
            f"{source_path}:{stat.st_size}:{stat.st_mtime_ns}:{self._max_side_pixels}"
        )
        digest = hashlib.sha256(key_input.encode("utf-8")).hexdigest()[:16]
        cached_path = self._cache_directory / f"{source_path.stem}_{digest}.png"
        prepared.save(cached_path, format="PNG", optimize=True)
        return cached_path.resolve()


# ---------------------------------------------------------------------------
# Decorative-content heuristic
# ---------------------------------------------------------------------------


# Phrases the prompt asks the model to emit for non-informative figures.
# Matching is case-insensitive and only requires presence near the start of
# the response (the model has been told to lead with "Decorative figure").
# Kept conservative so a forest plot that *mentions* the word "logo" in an
# axis label is not mis-flagged as decorative.
_DECORATIVE_LEAD_PHRASES = (
    "decorative figure",
    "decorative image",
    "no clinical content",
    "stock photo",
    "this is a logo",
    "company logo",
    "watermark",
)


def _looks_decorative(markdown_text: str) -> bool:
    head = markdown_text.lower()[:240]
    # Strip the header line — the prompt asks for `### Figure` first and we
    # don't want to scan only that one line.
    head = re.sub(r"^###[^\n]*\n", "", head)
    return any(phrase in head for phrase in _DECORATIVE_LEAD_PHRASES)


# ---------------------------------------------------------------------------
# The vision client
# ---------------------------------------------------------------------------


class OllamaVisionFigureClient(AbstractVisionFigureClient):
    """
    Local Ollama VLM client.  Produces one :class:`FigureSummary` per call
    whose ``markdown_result`` is exactly the model's Markdown output.

    Stateless after construction — safe to share across worker tasks.  All
    concurrency control (in-flight semaphore, GPU lock) lives in the
    orchestrator, not here.

    Timeout
    -------
    Ollama is wrapped in :func:`asyncio.wait_for` using
    ``OllamaVisionClientConfig.request_timeout_seconds`` so a stuck call
    cannot burn a worker forever.  This is the *only* timeout that applies
    to the model call — the orchestrator no longer wraps the call in the
    cloud-sized ``llm_batch_call`` timeout, which was tuned for batched
    cloud APIs and routinely fires on a local 4B model that needs ~30 s
    per figure.
    """

    def __init__(
        self,
        *,
        config: OllamaVisionClientConfig,
        prompt_builder: FigureSummarizationPromptBuilder,
        document_domain: DocumentDomain = DocumentDomain.AUTO,
    ) -> None:
        self._config = config
        self._prompt_builder = prompt_builder
        self._document_domain = document_domain
        # ``ollama.AsyncClient`` reuses an httpx connection pool, so a
        # single client instance is the right shape for a long-running
        # worker pool.
        self._ollama = (
            ollama.AsyncClient(host=config.base_url)
            if config.base_url
            else ollama.AsyncClient()
        )
        self._preprocessor = _FigureImagePreprocessor(
            max_side_pixels=config.image_max_side_pixels,
            cache_directory=config.image_cache_directory,
        )

    # ------------------------------------------------------------------
    # AbstractVisionFigureClient
    # ------------------------------------------------------------------

    async def summarize(self, *, image_path: Path, token: str) -> FigureSummary:
        prepared_path = self._preprocessor.prepare(image_path)
        system_prompt = self._prompt_builder.build_system_prompt(self._document_domain)
        user_prompt = self._prompt_builder.build_user_prompt(attempt_number=1)

        markdown = await self._invoke_model(
            prepared_path=prepared_path,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            enable_thinking=self._config.enable_thinking,
        )

        # Empty-content guard.  This is rare without ``format=<schema>`` but
        # can still happen if Ollama hits an internal error.  Raise so the
        # worker pool's transport retry can have another go.
        if not markdown.strip():
            raise FigureSummarizationError(
                "Vision model returned an empty Markdown response.",
                context={"token": token, "image_path": str(image_path)},
            )

        return self._assemble_summary(markdown=markdown.strip(), token=token)

    # ------------------------------------------------------------------
    # Private — model invocation
    # ------------------------------------------------------------------

    async def _invoke_model(
        self,
        *,
        prepared_path: Path,
        system_prompt: str,
        user_prompt: str,
        enable_thinking: bool,
    ) -> str:
        """
        One round-trip to Ollama; returns the raw assistant content string.

        Calling pattern mirrors ``ollama_qwen_image_summary_check.py``
        exactly — same options, same message shape, no ``format=`` — so
        any divergence between our pipeline and the reference is purely
        in the prompt text (which is centralised in
        :mod:`figure_summarization_prompt`).
        """
        generation_options: dict[str, Any] = {
            "temperature": self._config.temperature,
            "top_p": self._config.top_p,
            "seed": self._config.seed,
            "num_ctx": self._config.num_ctx,
            "num_predict": self._config.num_predict,
        }
        call_kwargs: dict[str, Any] = {
            "model": self._config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": user_prompt,
                    "images": [str(prepared_path)],
                },
            ],
            "options": generation_options,
            "think": enable_thinking,
        }

        # Hard ceiling on this single call.  Sourced from the client config
        # (default 120 s) — long enough for a 4B model on a CPU-shared GPU,
        # but bounded so a hung Ollama daemon cannot stall a worker forever.
        try:
            response = await asyncio.wait_for(
                self._ollama.chat(**call_kwargs),
                timeout=self._config.request_timeout_seconds,
            )
        except TimeoutError as exc:
            raise FigureSummarizationError(
                f"Ollama call exceeded request_timeout_seconds="
                f"{self._config.request_timeout_seconds:.0f}s.",
                context={
                    "model": self._config.model,
                    "timeout_seconds": self._config.request_timeout_seconds,
                },
            ) from exc

        return self._extract_message_content(response)

    @staticmethod
    def _extract_message_content(response: Any) -> str:
        # Ollama python client may return a typed object or a dict
        # depending on version; handle both.
        message = (
            response.get("message")
            if isinstance(response, dict)
            else getattr(response, "message", None)
        )
        if message is None:
            return ""
        if isinstance(message, dict):
            return str(message.get("content") or "")
        return str(getattr(message, "content", "") or "")

    # ------------------------------------------------------------------
    # Private — assemble FigureSummary from raw Markdown
    # ------------------------------------------------------------------

    def _assemble_summary(self, *, markdown: str, token: str) -> FigureSummary:
        """
        Build a :class:`FigureSummary` from the raw Markdown response.

        Routing-critical fields:

        * ``markdown_result`` — exactly the model's text; this is what
          Stage 4 substitutes for the ``${FIG:...}`` token.
        * ``is_informative`` / ``figure_type`` / ``rendering_strategy`` —
          derived from a small content heuristic.  Decoratives are routed
          to :attr:`FigureType.DECORATIVE` + ``DECORATIVE_NOTE`` so Stage 4
          drops the token entirely; everything else uses safe defaults
          (``OTHER`` + ``PLAIN_TEXT_EXPLANATION``) that pass the contract's
          cross-field validators without committing to a category we
          cannot reliably classify without a second model call.

        Trust / observability fields:

        * ``legibility`` defaults to ``CLEAR``; ``confidence`` defaults to
          0.8.  Future work: have the model emit a confidence line we can
          parse, or run a tiny follow-up classifier.  For now Stage 4 only
          uses these for diagnostics.
        """
        if _looks_decorative(markdown):
            return FigureSummary(
                token=token,
                figure_type=FigureType.DECORATIVE,
                rendering_strategy=RenderingStrategy.DECORATIVE_NOTE,
                is_informative=False,
                markdown_result=markdown,
                legibility=LegibilityLevel.CLEAR,
                confidence=0.9,
                document_domain=self._effective_document_domain(),
            )

        return FigureSummary(
            token=token,
            figure_type=FigureType.OTHER,
            rendering_strategy=RenderingStrategy.PLAIN_TEXT_EXPLANATION,
            is_informative=True,
            markdown_result=markdown,
            legibility=LegibilityLevel.CLEAR,
            confidence=0.8,
            document_domain=self._effective_document_domain(),
        )

    def _effective_document_domain(self) -> DocumentDomain:
        # ``DocumentDomain.AUTO`` is a pipeline-level sentinel; the
        # FigureSummary contract forbids it in stored summaries.  When the
        # caller didn't pick a concrete domain we default to EDUCATIONAL
        # (the maximally-neutral concrete domain in the enum) so the
        # contract is satisfied without claiming a domain we cannot
        # actually verify from one figure.
        if self._document_domain == DocumentDomain.AUTO:
            return DocumentDomain.EDUCATIONAL
        return self._document_domain
