"""
contracts/configurations/vision_llm_client_config.py
=====================================================
Configuration model for the vision LLM client used in Stage 3.

Stage 3 sends extracted figure images to a multimodal (vision-capable) LLM
and receives natural-language summaries in return.  The summaries are then
substituted back into the document markdown where the ``${FIG:...}`` tokens
appear.

Currently configured for Qwen QVQ-Max via Alibaba Cloud's DashScope platform
using the OpenAI-compatible API.  The provider can be changed by editing
``settings.yaml`` — no code changes required.

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

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..exceptions import ConfigurationError


class VisionLLMProvider(str, Enum):
    """
    Hosting provider for the vision LLM.

    Controls which default ``api_base_url`` is used and any provider-specific
    behaviour (e.g. DashScope requires streaming output for QVQ-Max).

    DASHSCOPE
        Alibaba Cloud's DashScope platform.  OpenAI-compatible endpoint.
        Hosts Qwen models (QVQ-Max, Qwen3-VL-Flash) with multi-image support.

    OPENAI
        OpenAI API (e.g. GPT-4o).  Standard OpenAI endpoint.

    ANTHROPIC
        Anthropic API (Claude vision models).  Uses the Anthropic SDK format,
        not the OpenAI-compatible endpoint.
    """

    DASHSCOPE = "dashscope"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


# Default base URLs per provider — used when ``api_base_url`` is not
# explicitly set in settings.yaml or environment.
_PROVIDER_DEFAULT_URLS: dict[VisionLLMProvider, str] = {
    VisionLLMProvider.DASHSCOPE: "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    VisionLLMProvider.OPENAI: "https://api.openai.com/v1",
    VisionLLMProvider.ANTHROPIC: "https://api.anthropic.com",
}


class VisionLLMClientConfig(BaseSettings):
    """
    Settings for the OpenAI-compatible vision LLM client.

    ``BaseSettings`` reads values in this priority order:
      1. Constructor keyword arguments.
      2. Environment variables prefixed with ``VISION_LLM_``.
      3. The ``figure_summarization.vision_llm`` section of ``settings.yaml``
         (injected by PipelineConfig).
      4. Field defaults.

    Usage example::

        config = VisionLLMClientConfig()
        client = openai.AsyncOpenAI(
            api_key=config.api_key,           # reads from env var at call time
            base_url=config.api_base_url,
        )
        response = await client.chat.completions.create(
            model=config.model,
            stream=config.streaming,
            messages=[...],
        )
    """

    model_config = SettingsConfigDict(
        env_prefix="VISION_LLM_",
        extra="ignore",
    )

    provider: VisionLLMProvider = Field(
        default=VisionLLMProvider.DASHSCOPE,
        description="Hosting provider — determines the default API base URL.",
    )

    model: str = Field(
        default="qvq-max",
        description=(
            "Model identifier passed to the API.  "
            "DashScope examples: 'qvq-max', 'qwen3-vl-flash-2026-01-22'.  "
            "QVQ-Max uses chain-of-thought visual reasoning for higher accuracy "
            "on complex clinical diagrams; Qwen3-VL-Flash is faster."
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
        default="DASHSCOPE_API_KEY",
        description=(
            "Name of the environment variable that holds the API key.  "
            "The key itself is NEVER stored here — only the variable name."
        ),
    )

    streaming: bool = Field(
        default=True,
        description=(
            "Enable streaming responses.  Required for QVQ-Max (DashScope only "
            "supports streaming output for this model)."
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
