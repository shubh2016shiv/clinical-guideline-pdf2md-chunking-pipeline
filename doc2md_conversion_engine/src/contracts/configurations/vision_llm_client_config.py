"""
contracts/configurations/vision_llm_client_config.py
=====================================================
Configuration model for the **cloud** vision LLM client used in Stage 3.

This is the API-based path (OpenAI / DashScope / Anthropic).  It is the
**default** Stage 3 provider because cloud vision endpoints are reliable,
fast (tens of seconds per figure vs. ~8 minutes for a local 4B VLM), and
do not require a powerful local GPU.  Users with a beefy on-box GPU can
opt into the local Ollama path by flipping
``figure_summarization.provider`` to ``local_ollama``.

GPT-5-style knobs (``reasoning_effort``, ``verbosity``, ``detail``,
``max_output_tokens``) and image-prep knobs (``image_budget``,
``image_cache_directory``) live here too, so the same OpenAI-compatible
client can target ``gpt-5-nano`` (default), ``qvq-max`` on DashScope,
or any other compatible endpoint without code changes.

Security note
-------------
The actual API key is NEVER stored in ``settings.yaml``.  Only the name of
the environment variable that holds the key is stored there.  The ``api_key``
property reads the variable at call time so the secret stays in the
environment, not in any file that might be committed to version control.

All values are read from the ``figure_summarization.vision_llm`` section of
``settings.yaml`` and can be overridden via environment variables prefixed
with ``VISION_LLM_``.
"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..exceptions import ConfigurationError


class VisionLLMProvider(str, Enum):
    """
    Hosting provider for the vision LLM.

    Controls which default ``api_base_url`` is used and any provider-specific
    behaviour (e.g. DashScope requires streaming output for QVQ-Max).

    OPENAI
        OpenAI API (e.g. ``gpt-5-nano``, ``gpt-4o``).  The reference path —
        ``gpt-5-nano`` via the Responses API with ``reasoning_effort=low``
        and ``verbosity=high`` produces high-quality figure Markdown at a
        few cents per image.

    DASHSCOPE
        Alibaba Cloud's DashScope platform.  OpenAI-compatible endpoint.
        Hosts Qwen models (QVQ-Max, Qwen3-VL-Flash) with multi-image support.

    ANTHROPIC
        Anthropic API (Claude vision models).  Uses the Anthropic SDK format,
        not the OpenAI-compatible endpoint.
    """

    OPENAI = "openai"
    DASHSCOPE = "dashscope"
    ANTHROPIC = "anthropic"


class VisionLLMApiType(str, Enum):
    """
    Which OpenAI-compatible endpoint shape to call.

    RESPONSES
        The Responses API (``client.responses.create``).  Required to access
        the GPT-5 reasoning/verbosity controls cleanly.  Default.

    CHAT
        Classic Chat Completions (``client.chat.completions.create``).
        Used for providers / models that do not implement Responses
        (e.g. ``qvq-max`` on DashScope).
    """

    RESPONSES = "responses"
    CHAT = "chat"


class VisionLLMImageBudget(str, Enum):
    """
    Pre-upload image normalisation preset (see :mod:`openai_vision_client`).

    ``careful`` is the default because clinical figures often contain tiny
    legible text (forest-plot CIs, axis tick labels, table cells); the
    higher resolution / quality keeps that text readable to the model.
    """

    AGGRESSIVE = "aggressive"
    BALANCED = "balanced"
    CAREFUL = "careful"


# Default base URLs per provider — used when ``api_base_url`` is not
# explicitly set in settings.yaml or environment.
_PROVIDER_DEFAULT_URLS: dict[VisionLLMProvider, str] = {
    VisionLLMProvider.OPENAI: "https://api.openai.com/v1",
    VisionLLMProvider.DASHSCOPE: "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    VisionLLMProvider.ANTHROPIC: "https://api.anthropic.com",
}


class VisionLLMClientConfig(BaseSettings):
    """
    Settings for the OpenAI-compatible cloud vision LLM client.

    ``BaseSettings`` reads values in this priority order:
      1. Constructor keyword arguments.
      2. Environment variables prefixed with ``VISION_LLM_``.
      3. The ``figure_summarization.vision_llm`` section of ``settings.yaml``
         (injected by PipelineConfig).
      4. Field defaults.
    """

    model_config = SettingsConfigDict(
        env_prefix="VISION_LLM_",
        extra="ignore",
    )

    provider: VisionLLMProvider = Field(
        default=VisionLLMProvider.OPENAI,
        description="Hosting provider — determines the default API base URL.",
    )

    model: str = Field(
        default="gpt-5-nano",
        description=(
            "Model identifier passed to the API.  "
            "OpenAI: 'gpt-5-nano' (cheap, reliable, reasoning-capable).  "
            "DashScope: 'qvq-max' (chain-of-thought) or 'qwen3-vl-flash-...' (faster)."
        ),
    )

    api_type: VisionLLMApiType = Field(
        default=VisionLLMApiType.RESPONSES,
        description=(
            "Which endpoint shape to call.  RESPONSES gives access to GPT-5 "
            "reasoning / verbosity controls; CHAT is the fallback for providers "
            "that only implement Chat Completions (e.g. DashScope QVQ-Max)."
        ),
    )

    api_base_url: str | None = Field(
        default=None,
        description=(
            "Override the provider's default base URL.  "
            "When None the default for the selected ``provider`` is used automatically."
        ),
    )

    api_key_env_var: str = Field(
        default="OPENAI_API_KEY",
        description=(
            "Name of the environment variable that holds the API key.  "
            "The key itself is NEVER stored here — only the variable name."
        ),
    )

    streaming: bool = Field(
        default=False,
        description=(
            "Enable streaming responses.  Required for QVQ-Max on DashScope; "
            "ignored on the Responses API path."
        ),
    )

    # --- GPT-5 reasoning / verbosity controls ----------------------------

    reasoning_effort: str = Field(
        default="low",
        description=(
            "GPT-5 reasoning effort: minimal | low | medium | high.  "
            "Higher = better explanations but more hidden reasoning tokens "
            "(which eat into ``max_output_tokens``).  'low' is the proven "
            "default from the reference script — strong output without "
            "blowing the token budget."
        ),
    )

    verbosity: str = Field(
        default="high",
        description=(
            "GPT-5 Responses API text verbosity: low | medium | high.  "
            "'high' yields long, detailed Markdown explanations — what we want."
        ),
    )

    max_output_tokens: int = Field(
        default=5000,
        ge=512,
        description=(
            "Cap on total generated tokens, INCLUDING hidden GPT-5 reasoning "
            "tokens.  5000 leaves comfortable headroom for low-effort reasoning "
            "+ a full Markdown answer.  Raise to 8000 if you switch to "
            "reasoning_effort=medium/high."
        ),
    )

    # --- Image preprocessing knobs ---------------------------------------

    image_detail: str = Field(
        default="high",
        description=(
            "OpenAI image detail hint: auto | low | high.  'high' is needed "
            "to read tiny clinical labels (forest-plot CIs, axis ticks)."
        ),
    )

    image_budget: VisionLLMImageBudget = Field(
        default=VisionLLMImageBudget.CAREFUL,
        description=(
            "Pre-upload image resize/JPEG preset.  CAREFUL preserves small "
            "clinical text (longest edge ≤ 2400 px, quality 90).  Reduce to "
            "BALANCED if you need to cut upload bytes by ~60 %."
        ),
    )

    image_cache_directory: Path = Field(
        default=Path(".figure_analyzer_cache"),
        description=(
            "Directory for the content-addressed preprocessed-JPEG cache.  "
            "Repeated calls on the same image (retries / resumes) reuse the "
            "cached upload payload instead of re-encoding."
        ),
    )

    # --- Reliability knobs -----------------------------------------------

    request_timeout_seconds: float = Field(
        default=120.0,
        gt=0.0,
        description=(
            "Hard wall-clock ceiling on a single API call.  Cloud GPT-5-nano "
            "typically responds in 5-30 s; 120 s leaves headroom for tail "
            "latency without letting a stuck call hang a worker."
        ),
    )

    retry_empty_response: bool = Field(
        default=True,
        description=(
            "If the model returns empty visible text, retry once with "
            "reasoning_effort=minimal and a 2× output budget.  This is the "
            "exact mitigation the reference script uses for GPT-5 reasoning "
            "consuming the whole budget on a hard figure."
        ),
    )

    @model_validator(mode="after")
    def _resolve_api_base_url(self) -> VisionLLMClientConfig:
        """
        If ``api_base_url`` was not explicitly set, fall back to the
        provider's default URL.
        """
        if self.api_base_url is None:
            self.api_base_url = _PROVIDER_DEFAULT_URLS[self.provider]
        return self

    @property
    def api_key(self) -> str:
        """
        Read the actual API key from the environment at call time.

        Raises
        ------
        ConfigurationError
            If the environment variable named in ``api_key_env_var`` is not set
            or is empty.  Raised as ``ConfigurationError`` (not a generic
            ``EnvironmentError``) so the pipeline's exception hierarchy handles it.
        """
        key = os.environ.get(self.api_key_env_var, "").strip()
        if not key:
            raise ConfigurationError(
                f"Environment variable '{self.api_key_env_var}' is not set or empty.  "
                f"Export it before running the pipeline:  "
                f"export {self.api_key_env_var}=<your-key>",
                context={"env_var": self.api_key_env_var, "provider": self.provider},
            )
        return key
