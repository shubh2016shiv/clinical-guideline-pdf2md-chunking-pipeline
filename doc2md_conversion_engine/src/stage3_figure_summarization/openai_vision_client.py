"""
stage3_figure_summarization/openai_vision_client.py
====================================================
Concrete :class:`AbstractVisionFigureClient` for OpenAI-compatible **cloud**
vision endpoints.  Default Stage 3 path.

Why this is the default
-----------------------
Cloud vision endpoints (OpenAI ``gpt-5-nano`` via the Responses API,
DashScope ``qvq-max`` via Chat Completions) typically return a complete
figure-to-Markdown response in 5-30 seconds at a few cents per call.
The local Ollama path needs a capable on-box GPU and an 8-minute budget
per figure on a quantised 4B VLM, so cloud is the right default for the
vast majority of operators.

Behavioural parity with ``deepseek_image_explanation_check_enhanced.py``
------------------------------------------------------------------------
The reference script is the empirically-validated configuration.  This
client mirrors it 1:1:

* Image normalisation pipeline (``aggressive``/``balanced``/``careful``
  preset) — EXIF transpose, resize under a max-edge + max-pixel budget,
  progressive JPEG re-encode under a target byte ceiling.
* Responses API call with ``reasoning.effort``, ``text.verbosity``,
  ``max_output_tokens``, plus an OpenAI image-detail hint.
* Chat-Completions fallback API for providers that do not implement
  Responses (DashScope, older OpenAI-compatible servers).
* Empty-content retry: on an empty assistant text channel, drop to
  ``reasoning_effort=minimal`` and double the output budget.
* Plain Markdown output (no schema-constrained decode).

What is *not* shared with the reference script
-----------------------------------------------
* The reference is a CLI; this is an async adapter that returns a fully
  populated :class:`FigureSummary` for the worker pool to persist.
* The decorative routing decision is recovered from the same content
  heuristic used by ``ollama_vision_client`` so Stage 4 routing stays
  consistent across providers.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError

from ..contracts import (
    AbstractVisionFigureClient,
    DocumentDomain,
    FigureSummarizationError,
    FigureSummary,
    LegibilityLevel,
    RenderingStrategy,
    VisionLLMApiType,
    VisionLLMClientConfig,
    VisionLLMImageBudget,
)
from ..contracts.figure_summarization_types import FigureType
from .figure_summarization_prompt import FigureSummarizationPromptBuilder
from .ollama_vision_client import _looks_decorative

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Image budgets — verbatim from the reference script
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ImageBudget:
    """Pre-upload normalisation parameters."""

    max_edge_pixels: int
    max_pixels: int
    jpeg_quality: int
    min_jpeg_quality: int
    max_image_bytes: int


_IMAGE_BUDGETS: dict[VisionLLMImageBudget, _ImageBudget] = {
    VisionLLMImageBudget.AGGRESSIVE: _ImageBudget(
        max_edge_pixels=960,
        max_pixels=900_000,
        jpeg_quality=72,
        min_jpeg_quality=48,
        max_image_bytes=450_000,
    ),
    VisionLLMImageBudget.BALANCED: _ImageBudget(
        max_edge_pixels=1600,
        max_pixels=2_200_000,
        jpeg_quality=84,
        min_jpeg_quality=60,
        max_image_bytes=950_000,
    ),
    VisionLLMImageBudget.CAREFUL: _ImageBudget(
        max_edge_pixels=2400,
        max_pixels=5_000_000,
        jpeg_quality=90,
        min_jpeg_quality=70,
        max_image_bytes=2_200_000,
    ),
}


@dataclass(frozen=True)
class _PreparedImage:
    data_url: str
    source_sha256: str
    figure_name: str
    upload_bytes: int


# ---------------------------------------------------------------------------
# Image preprocessor
# ---------------------------------------------------------------------------


class _CloudFigureImagePreprocessor:
    """
    Normalise a PNG for cloud upload: EXIF transpose, RGB composite,
    budget-bounded resize, progressive JPEG re-encode, ``data:`` URL.

    Caches the encoded JPEG bytes on disk keyed by (path, size, mtime,
    budget) so retries / resumes don't pay the encoding cost twice.
    """

    def __init__(self, *, budget: _ImageBudget, cache_directory: Path) -> None:
        self._budget = budget
        self._cache_directory = cache_directory

    def prepare(self, source_image_path: Path) -> _PreparedImage:
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

        source_sha256 = self._sha256_file(resolved)
        figure_name = self._figure_name(resolved, source_sha256)
        cached_jpeg = self._cache_path(resolved, source_sha256)

        if cached_jpeg.exists():
            jpeg_bytes = cached_jpeg.read_bytes()
        else:
            try:
                with Image.open(resolved) as raw:
                    oriented = ImageOps.exif_transpose(raw)
                    rgb = self._to_rgb(oriented)
                    resized = self._resize(rgb)
                    jpeg_bytes = self._encode_jpeg_under_limit(resized)
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
            cached_jpeg.parent.mkdir(parents=True, exist_ok=True)
            cached_jpeg.write_bytes(jpeg_bytes)

        data_url = "data:image/jpeg;base64," + base64.b64encode(jpeg_bytes).decode("ascii")
        return _PreparedImage(
            data_url=data_url,
            source_sha256=source_sha256,
            figure_name=figure_name,
            upload_bytes=len(jpeg_bytes),
        )

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as image_file:
            for chunk in iter(lambda: image_file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _figure_name(path: Path, source_sha256: str) -> str:
        safe_stem = "".join(
            ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in path.stem
        ).strip("_")
        if not safe_stem:
            safe_stem = "figure"
        return f"{safe_stem}_{source_sha256[:10]}"

    def _cache_path(self, source_path: Path, source_sha256: str) -> Path:
        stat = source_path.stat()
        key = (
            f"{source_sha256}:{stat.st_size}:{stat.st_mtime_ns}:"
            f"{self._budget.max_edge_pixels}:{self._budget.jpeg_quality}"
        )
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
        return self._cache_directory / f"{source_path.stem}_{digest}.jpg"

    @staticmethod
    def _to_rgb(image: Image.Image) -> Image.Image:
        if image.mode in {"RGBA", "LA", "P"}:
            image = image.convert("RGBA")
            background = Image.new("RGBA", image.size, "WHITE")
            background.alpha_composite(image)
            return background.convert("RGB")
        if image.mode != "RGB":
            return image.convert("RGB")
        return image

    def _resize(self, image: Image.Image) -> Image.Image:
        width, height = image.size
        budget = self._budget
        scale_by_edge = min(1.0, budget.max_edge_pixels / max(width, height))
        scale_by_area = min(
            1.0, (budget.max_pixels / max(width * height, 1)) ** 0.5
        )
        scale = min(scale_by_edge, scale_by_area)
        if scale >= 1.0:
            return image
        new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
        return image.resize(new_size, Image.Resampling.LANCZOS)

    def _encode_jpeg_under_limit(self, image: Image.Image) -> bytes:
        budget = self._budget
        best_bytes = b""
        with tempfile.SpooledTemporaryFile(max_size=budget.max_image_bytes * 2) as buffer:
            for quality in range(budget.jpeg_quality, budget.min_jpeg_quality - 1, -5):
                buffer.seek(0)
                buffer.truncate(0)
                image.save(buffer, format="JPEG", quality=quality, optimize=True, progressive=True)
                candidate_size = buffer.tell()
                buffer.seek(0)
                best_bytes = buffer.read()
                if candidate_size <= budget.max_image_bytes:
                    break
        return best_bytes


# ---------------------------------------------------------------------------
# Empty-retry settings
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _CallSettings:
    """Per-call mutable knobs — copied so the retry path can lower them."""

    reasoning_effort: str
    verbosity: str
    max_output_tokens: int
    image_detail: str


def _retry_settings(initial: _CallSettings) -> _CallSettings:
    """
    Mirror ``with_retry_settings`` from the reference script: drop reasoning
    effort to minimal, force image detail high, double output budget.
    """
    return _CallSettings(
        reasoning_effort="minimal",
        verbosity="high",
        max_output_tokens=max(initial.max_output_tokens * 2, 8000),
        image_detail="high" if initial.image_detail == "auto" else initial.image_detail,
    )


# ---------------------------------------------------------------------------
# The vision client
# ---------------------------------------------------------------------------


class OpenAIVisionFigureClient(AbstractVisionFigureClient):
    """
    Cloud OpenAI-compatible vision client.  Default Stage 3 vision adapter.

    Concurrency
    -----------
    Stateless after construction.  The underlying ``openai.OpenAI`` client
    is thread/async-safe; we wrap each call in ``asyncio.to_thread`` so
    the synchronous SDK does not block the event loop.

    Timeout
    -------
    Owned here via ``asyncio.wait_for(request_timeout_seconds)`` so a stuck
    call cannot burn a worker forever.  The orchestrator does **not** add
    a second timeout wrapper.
    """

    def __init__(
        self,
        *,
        config: VisionLLMClientConfig,
        prompt_builder: FigureSummarizationPromptBuilder,
        document_domain: DocumentDomain = DocumentDomain.AUTO,
    ) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise FigureSummarizationError(
                "openai package is required for the cloud vision provider.  "
                "Install with `uv add openai` or switch provider to local_ollama.",
            ) from exc

        self._config = config
        self._prompt_builder = prompt_builder
        self._document_domain = document_domain
        self._client = OpenAI(api_key=config.api_key, base_url=config.api_base_url)
        self._preprocessor = _CloudFigureImagePreprocessor(
            budget=_IMAGE_BUDGETS[config.image_budget],
            cache_directory=config.image_cache_directory,
        )

    # ------------------------------------------------------------------
    # AbstractVisionFigureClient
    # ------------------------------------------------------------------

    async def summarize(self, *, image_path: Path, token: str) -> FigureSummary:
        prepared = self._preprocessor.prepare(image_path)
        system_prompt = self._prompt_builder.build_system_prompt(self._document_domain)
        user_prompt = self._prompt_builder.build_user_prompt(attempt_number=1)

        initial = _CallSettings(
            reasoning_effort=self._config.reasoning_effort,
            verbosity=self._config.verbosity,
            max_output_tokens=self._config.max_output_tokens,
            image_detail=self._config.image_detail,
        )

        markdown = await self._invoke_with_empty_retry(
            prepared=prepared,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            settings=initial,
        )

        if not markdown.strip():
            raise FigureSummarizationError(
                "Cloud vision model returned an empty Markdown response.",
                context={"token": token, "image_path": str(image_path)},
            )

        return self._assemble_summary(markdown=markdown.strip(), token=token)

    # ------------------------------------------------------------------
    # Private — invocation w/ empty-retry
    # ------------------------------------------------------------------

    async def _invoke_with_empty_retry(
        self,
        *,
        prepared: _PreparedImage,
        system_prompt: str,
        user_prompt: str,
        settings: _CallSettings,
    ) -> str:
        markdown = await self._call(
            prepared=prepared,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            settings=settings,
        )
        if markdown.strip() or not self._config.retry_empty_response:
            return markdown

        logger.warning(
            "stage3.openai.empty_content retrying with reasoning_effort=minimal "
            "and doubled output budget."
        )
        retry = _retry_settings(settings)
        return await self._call(
            prepared=prepared,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            settings=retry,
        )

    async def _call(
        self,
        *,
        prepared: _PreparedImage,
        system_prompt: str,
        user_prompt: str,
        settings: _CallSettings,
    ) -> str:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(
                    self._call_sync,
                    prepared,
                    system_prompt,
                    user_prompt,
                    settings,
                ),
                timeout=self._config.request_timeout_seconds,
            )
        except TimeoutError as exc:
            raise FigureSummarizationError(
                f"OpenAI vision call exceeded request_timeout_seconds="
                f"{self._config.request_timeout_seconds:.0f}s.",
                context={
                    "model": self._config.model,
                    "timeout_seconds": self._config.request_timeout_seconds,
                },
            ) from exc

    def _call_sync(
        self,
        prepared: _PreparedImage,
        system_prompt: str,
        user_prompt: str,
        settings: _CallSettings,
    ) -> str:
        if self._config.api_type == VisionLLMApiType.RESPONSES:
            return self._call_responses(prepared, system_prompt, user_prompt, settings)
        return self._call_chat(prepared, system_prompt, user_prompt, settings)

    # ------------------------------------------------------------------
    # Responses API
    # ------------------------------------------------------------------

    def _call_responses(
        self,
        prepared: _PreparedImage,
        system_prompt: str,
        user_prompt: str,
        settings: _CallSettings,
    ) -> str:
        input_text = (
            f"{user_prompt}\n\n"
            f"figure_name: {prepared.figure_name}\n"
            "Use this figure_name in the heading if no visible title exists.\n"
            "Infer the domain yourself from the image."
        )
        image_payload: dict[str, str] = {
            "type": "input_image",
            "image_url": prepared.data_url,
        }
        if settings.image_detail != "auto":
            image_payload["detail"] = settings.image_detail

        response = self._client.responses.create(
            model=self._config.model,
            instructions=system_prompt,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": input_text},
                        image_payload,
                    ],
                }
            ],
            reasoning={"effort": settings.reasoning_effort},
            text={"verbosity": settings.verbosity},
            max_output_tokens=settings.max_output_tokens,
        )
        return self._extract_responses_output_text(response)

    @staticmethod
    def _extract_responses_output_text(response: Any) -> str:
        direct_text = getattr(response, "output_text", None)
        if isinstance(direct_text, str) and direct_text.strip():
            return direct_text.strip()
        chunks: list[str] = []
        for item in getattr(response, "output", []) or []:
            for content in getattr(item, "content", []) or []:
                text = getattr(content, "text", None)
                if isinstance(text, str):
                    chunks.append(text)
        return "".join(chunks).strip()

    # ------------------------------------------------------------------
    # Chat Completions API (DashScope / non-Responses providers)
    # ------------------------------------------------------------------

    def _call_chat(
        self,
        prepared: _PreparedImage,
        system_prompt: str,
        user_prompt: str,
        settings: _CallSettings,
    ) -> str:
        user_text = (
            f"{user_prompt}\n\n"
            f"figure_name: {prepared.figure_name}\n"
            "Use this figure_name in the heading if no visible title exists.\n"
            "Infer the domain yourself from the image."
        )
        image_url: dict[str, str] = {"url": prepared.data_url}
        if settings.image_detail != "auto":
            image_url["detail"] = settings.image_detail

        request_kwargs: dict[str, Any] = {
            "model": self._config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {"type": "image_url", "image_url": image_url},
                    ],
                },
            ],
            "max_completion_tokens": settings.max_output_tokens,
            "reasoning_effort": settings.reasoning_effort,
        }
        if self._config.streaming:
            request_kwargs["stream"] = True

        response = self._client.chat.completions.create(**request_kwargs)
        if self._config.streaming:
            return self._consume_chat_stream(response)
        choice = response.choices[0]
        return (choice.message.content or "").strip()

    @staticmethod
    def _consume_chat_stream(stream: Any) -> str:
        chunks: list[str] = []
        for event in stream:
            for choice in getattr(event, "choices", []) or []:
                delta = getattr(choice, "delta", None)
                text = getattr(delta, "content", None) if delta is not None else None
                if isinstance(text, str):
                    chunks.append(text)
        return "".join(chunks).strip()

    # ------------------------------------------------------------------
    # Private — assemble FigureSummary from raw Markdown
    # ------------------------------------------------------------------

    def _assemble_summary(self, *, markdown: str, token: str) -> FigureSummary:
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
            confidence=0.85,
            document_domain=self._effective_document_domain(),
        )

    def _effective_document_domain(self) -> DocumentDomain:
        if self._document_domain == DocumentDomain.AUTO:
            return DocumentDomain.EDUCATIONAL
        return self._document_domain


__all__ = ["OpenAIVisionFigureClient"]
