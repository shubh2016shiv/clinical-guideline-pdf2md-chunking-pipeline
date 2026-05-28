"""
contracts/configurations/ollama_vision_client_config.py
========================================================
Configuration model for the **local** Ollama vision-language client used in
Stage 3 figure summarization.

Why a separate config (not reusing ``VisionLLMClientConfig``)?
---------------------------------------------------------------
``VisionLLMClientConfig`` was designed for *cloud* providers (DashScope, OpenAI,
Anthropic) and reasons in terms of API keys, request-per-minute rate limits,
and streaming flags.  The local Ollama path is fundamentally different:

* No API key — the model is served locally on the host.
* No RPM ceiling — the bottleneck is **VRAM / in-flight concurrency**.
* The endpoint is a localhost socket, not a regional URL.
* "Thinking" mode (Qwen3-VL ``think:true``) is a knob that does not exist in
  any cloud OpenAI-compatible API.

Keeping the two configurations distinct preserves provider-switching at the
``FigureSummarizationConfig`` level: callers can choose between a local Ollama
client and a cloud client without one config bleeding fields into the other.

Settings priority (highest → lowest)
-------------------------------------
1. Constructor keyword arguments (tests).
2. Environment variables prefixed with ``OLLAMA_VISION_``.
3. Values injected from ``settings.yaml``
   (``figure_summarization.ollama_vision_client.*``).
4. Field defaults defined below.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class OllamaVisionClientConfig(BaseSettings):
    """
    Settings for the local Ollama VLM client.

    Defaults are tuned for a quantized 4-billion-parameter Qwen3-VL tag (the
    smallest model that still reliably reads dense forest plots and small text
    in flowcharts).  Adjust ``model`` if a heavier tag is available on the host.

    Field roles
    -----------
    ``base_url``
        Ollama HTTP endpoint; ``None`` lets the ``ollama`` Python client use
        its default (``http://localhost:11434``).
    ``model``
        The Ollama model tag.  Must be a vision-capable model.
    ``request_timeout_seconds``
        Hard ceiling on a single image's inference call.  Independent of the
        per-stage ``TimeoutsConfig`` knob — kept here so operators can tune
        the client without touching pipeline-wide timeouts.
    ``temperature`` / ``top_p`` / ``seed``
        Deterministic generation — clinical numbers must not jitter between
        runs of the same figure.
    ``num_ctx`` / ``num_predict``
        Ollama context / output token caps.  4096 output tokens fits the
        ``summary_markdown`` field comfortably.
    ``enable_thinking``
        Request Ollama ``think: true`` reasoning mode.  Small quantized models
        sometimes return empty content when thinking is combined with strict
        ``format=<json schema>`` constraints, so callers may disable this on
        retry.
    ``image_max_side_pixels``
        Longest-side downscale limit for figures sent to the model.  768 px
        preserves legibility for most clinical diagrams while keeping VRAM
        usage predictable.
    ``image_cache_directory``
        Where the orientation-corrected, downscaled PNG cache lives.  A
        content-addressed cache avoids re-preprocessing the same image across
        retries / resumes.
    """

    model_config = SettingsConfigDict(
        env_prefix="OLLAMA_VISION_",
        extra="ignore",
    )

    base_url: str | None = Field(
        default=None,
        description=(
            "Ollama server URL.  None defers to the ollama client default "
            "(http://localhost:11434).  Override only when Ollama is reached "
            "through a non-default socket or a sidecar."
        ),
    )

    model: str = Field(
        default="qwen3-vl:4b",
        description=(
            "Vision-capable Ollama model tag.  Must be installed locally "
            "(``ollama pull <tag>``).  Examples: 'qwen3-vl:4b', 'qwen2.5vl:7b'."
        ),
    )

    request_timeout_seconds: float = Field(
        default=600.0,
        gt=0.0,
        description=(
            "Hard wall-clock ceiling on a single image's inference call.  "
            "Sized for the worst-case healthy figure on a quantized 4B VL "
            "model: empirically Qwen3-VL:4b generates ~8 tokens/sec on a "
            "5-6 GB VRAM budget, and ``num_predict`` 4096 is needed so the "
            "model has room to finish its (unsuppressable) internal thinking "
            "phase AND emit the Markdown answer.  4096 / 8 ≈ 512 s, plus "
            "headroom for cold-cache reads.  Pathological images (tiny "
            "banners that confuse the VL head) will exceed even this and "
            "poison-pill — by design, so the document still completes."
        ),
    )

    temperature: float = Field(
        default=0.0,
        ge=0.0,
        description="Sampling temperature.  0.0 = fully deterministic.",
    )

    top_p: float = Field(
        default=0.1,
        ge=0.0,
        le=1.0,
        description="Nucleus sampling cut-off.",
    )

    seed: int = Field(
        default=42,
        description="RNG seed for reproducible generation across runs.",
    )

    num_ctx: int = Field(
        default=8192,
        ge=512,
        description="Ollama context window size in tokens.",
    )

    num_predict: int = Field(
        default=4096,
        ge=64,
        description=(
            "Maximum output tokens per Ollama response.  4096 is the proven "
            "working value (matches ``ollama_qwen_image_summary_check.py``): "
            "Qwen3-VL emits internal ``<think>`` reasoning tokens that cannot "
            "be suppressed by ``think:false`` or ``/no_think`` on the 4B tag, "
            "and the model needs roughly 2-3k of those tokens before it "
            "produces the actual Markdown answer.  Setting this too low (e.g. "
            "1024) leaves the model trapped in the thinking phase and ``content`` "
            "comes back empty, which is interpreted as a failure and poisons "
            "the figure.  Reduce only if a stronger / non-thinking VL model "
            "is configured."
        ),
    )

    enable_thinking: bool = Field(
        default=False,
        description=(
            "Request Ollama ``think: true`` reasoning mode.  Often disabled on "
            "small quantized models because thinking + strict JSON schema "
            "constraints can produce empty content channels; the client falls "
            "back automatically when ``fallback_to_no_thinking_on_failure`` is set."
        ),
    )

    fallback_to_no_thinking_on_failure: bool = Field(
        default=True,
        description=(
            "If True and a thinking-enabled call returns empty / invalid JSON, "
            "the client disables thinking for the next attempt instead of "
            "failing immediately.  Pragmatic mitigation for small VLMs."
        ),
    )

    image_max_side_pixels: int = Field(
        default=768,
        ge=512,
        description=(
            "Downscale figures so the longest side is at most this many "
            "pixels before submitting to the model.  Preserves legibility "
            "while keeping VRAM bounded."
        ),
    )

    image_cache_directory: Path = Field(
        default=Path(".figure_analyzer_cache"),
        description=(
            "Directory for the content-addressed preprocessed-image cache. "
            "Repeated calls on the same image (retries / resumes) reuse the "
            "cached PNG instead of decoding + downscaling again."
        ),
    )
