"""
stage2_page_extraction/conversion_engines/mineru_subprocess_engine.py
=====================================================================
Stage 2 · the MinerU conversion engine (runs as a separate process).

MinerU is the heavier, more capable engine, reached only when a document is
structurally hard (multi-column, complex tables, scans). Unlike Docling it does NOT
run inside this process: it starts its own ``mineru-api`` HTTP server in a child
process and we talk to it over localhost. That isolation is deliberate — MinerU
manages its own GPU memory (via vLLM), and keeping it out of our process avoids any
clash with Docling's CUDA context.

What this adapter does
----------------------
It hides the subprocess and HTTP details behind the ``AbstractConversionEngine``
interface:

  * ``start``  launches ``mineru-api`` and waits until ``GET /health`` is OK,
  * ``convert_window`` asks MinerU to parse the window's pages and yields one
    ``PageResult`` per page, and
  * ``stop``   shuts the subprocess down cleanly and frees its resources.

One request per page
--------------------
MinerU returns Markdown for a *range* of pages, not split per page. To honour the
pipeline's per-page contract we ask it for one page at a time (so each response maps
to exactly one ``PageResult``); the whole window still runs under a single GPU lease
and a single checkpoint.

Validation note
---------------
The subprocess lifecycle (launch, health-poll, terminate) is engine-agnostic and
solid. The shape of MinerU's ``/file_parse`` response is the one part that depends on
the deployed MinerU version; that mapping is isolated in ``_request_page_parse`` and
``_raw_page_from_response`` so it is the single place to adjust if the contract
differs. It targets MinerU's documented ``/file_parse`` JSON.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
import time
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from ...contracts.configurations.mineru_engine_config import MinerUEngineConfig
from ...contracts.conversion_engine_interface import AbstractConversionEngine
from ...contracts.exceptions import EngineError, EngineStartupError
from ...contracts.pipeline_domain_types import ExtractionEngine, PageResult
from ..page_result_builders import FIGURE_PLACEHOLDER_MARKER, RawFigure, RawPage, build_page_result

logger = logging.getLogger(__name__)

# MinerU renders embedded images as standard Markdown image syntax; we rewrite each
# to the shared figure placeholder so the builder can tokenise them uniformly.
_MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")

# How often to poll /health while waiting for the subprocess to come up.
_HEALTH_POLL_INTERVAL_SECONDS = 1.0


class MinerUSubprocessEngine(AbstractConversionEngine):
    """
    Convert documents with MinerU running as a managed ``mineru-api`` subprocess.

    Constructed per job so it can stamp the document's ``job_id`` into figure tokens.
    Always used as an async context manager so the subprocess is guaranteed to be
    shut down even on error.
    """

    def __init__(self, config: MinerUEngineConfig, job_id: str) -> None:
        self._config = config
        self._job_id = job_id
        self._process: asyncio.subprocess.Process | None = None

    @property
    def engine_type(self) -> ExtractionEngine:
        return ExtractionEngine.MINERU

    async def start(self) -> None:
        """
        Launch ``mineru-api`` and wait until it reports healthy.

        Raises ``EngineStartupError`` if the subprocess does not become healthy
        within ``startup_timeout_seconds`` — the subprocess is torn down first so a
        failed start never leaks a child process.
        """
        if self._process is not None:
            return
        self._process = await self._spawn_subprocess()
        try:
            await self._await_health()
        except Exception as exc:
            await self.stop()
            raise EngineStartupError(
                "MinerU subprocess did not become healthy within the startup timeout.",
                context={
                    "engine": ExtractionEngine.MINERU.value,
                    "api_base_url": self._config.api_base_url,
                    "startup_timeout_seconds": self._config.startup_timeout_seconds,
                },
            ) from exc

    async def stop(self) -> None:
        """Terminate the subprocess gracefully, then forcibly if it does not exit. Idempotent."""
        process = self._process
        if process is None:
            return
        self._process = None
        if process.returncode is not None:
            return
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=10.0)
        except (TimeoutError, asyncio.TimeoutError):
            logger.warning("mineru.subprocess.kill (did not exit on terminate)")
            process.kill()
            await process.wait()

    async def is_available(self) -> bool:
        """Lightweight readiness check: subprocess alive and ``/health`` returns OK."""
        if self._process is None or self._process.returncode is not None:
            return False
        return await self._health_ok()

    async def convert_window(
        self,
        page_numbers: list[int],
        document_path: str,
        output_dir: str,
    ) -> AsyncGenerator[PageResult, None]:
        """
        Parse each page in the window through MinerU and yield a ``PageResult`` each.

        Pages are requested one at a time so every response maps to exactly one page.
        """
        if self._process is None:
            raise EngineError(
                "MinerU convert_window called before start().",
                context={"engine": ExtractionEngine.MINERU.value},
            )

        window_output_dir = Path(output_dir)
        for page_number in page_numbers:
            started_at = time.perf_counter()
            raw_page = await self._parse_one_page(document_path, page_number, window_output_dir)
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            yield build_page_result(
                job_id=self._job_id,
                engine=ExtractionEngine.MINERU,
                raw_page=raw_page,
                window_output_dir=window_output_dir,
                duration_ms=duration_ms,
            )

    # ------------------------------------------------------------------
    # Subprocess lifecycle
    # ------------------------------------------------------------------

    async def _spawn_subprocess(self) -> asyncio.subprocess.Process:
        """Start the ``mineru-api`` server bound to the configured host/port."""
        try:
            return await asyncio.create_subprocess_exec(
                "mineru-api",
                "--host",
                self._config.api_host,
                "--port",
                str(self._config.api_port),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except FileNotFoundError as exc:
            raise EngineStartupError(
                "The 'mineru-api' executable was not found. Install MinerU with its API extra.",
                context={"engine": ExtractionEngine.MINERU.value},
            ) from exc

    async def _await_health(self) -> None:
        """Poll ``/health`` until it succeeds or the startup timeout elapses."""
        deadline = time.monotonic() + self._config.startup_timeout_seconds
        while time.monotonic() < deadline:
            if self._process is not None and self._process.returncode is not None:
                raise EngineStartupError(
                    "MinerU subprocess exited during startup.",
                    context={
                        "engine": ExtractionEngine.MINERU.value,
                        "returncode": self._process.returncode,
                    },
                )
            if await self._health_ok():
                return
            await asyncio.sleep(_HEALTH_POLL_INTERVAL_SECONDS)
        raise TimeoutError("MinerU /health did not become ready in time.")

    async def _health_ok(self) -> bool:
        """Return True when ``GET /health`` responds 200, False on any failure."""
        import httpx

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self._config.api_base_url}/health")
                return response.status_code == 200
        except Exception:
            return False

    # ------------------------------------------------------------------
    # MinerU /file_parse integration (the version-dependent boundary)
    # ------------------------------------------------------------------

    async def _parse_one_page(
        self,
        document_path: str,
        page_number: int,
        window_output_dir: Path,
    ) -> RawPage:
        """Send one page to MinerU and turn the response into a ``RawPage``."""
        response_json = await self._request_page_parse(document_path, page_number)
        return self._raw_page_from_response(response_json, page_number, window_output_dir)

    async def _request_page_parse(self, document_path: str, page_number: int) -> dict[str, Any]:
        """
        POST a single page to ``/file_parse`` and return the parsed JSON.

        MinerU uses 0-based page ids; the window timeout bounds how long one page may
        take before it is treated as an engine failure (so the resilient wrapper can
        fall back).
        """
        import httpx

        zero_based_page = page_number - 1
        form = {
            "backend": self._config.backend.value,
            "start_page_id": str(zero_based_page),
            "end_page_id": str(zero_based_page),
            "return_md": "true",
            "return_images": "true",
        }
        try:
            async with httpx.AsyncClient(timeout=self._config.window_timeout_seconds) as client:
                with Path(document_path).open("rb") as document_file:
                    response = await client.post(
                        f"{self._config.api_base_url}/file_parse",
                        data=form,
                        files={"files": (Path(document_path).name, document_file)},
                    )
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            raise EngineError(
                f"MinerU failed to parse page {page_number}.",
                context={
                    "engine": ExtractionEngine.MINERU.value,
                    "page_number": page_number,
                    "api_base_url": self._config.api_base_url,
                },
            ) from exc

    def _raw_page_from_response(
        self,
        response_json: dict[str, Any],
        page_number: int,
        window_output_dir: Path,
    ) -> RawPage:
        """
        Map MinerU's ``/file_parse`` JSON for one page into a ``RawPage``.

        MinerU returns the page's Markdown plus its images keyed by the relative path
        used in the Markdown's ``![](...)`` links. We swap each image link for the
        shared figure placeholder, in order, and decode the matching image bytes so
        the builder can tokenise them. This is the single MinerU-schema-dependent
        method; adjust the key names here if the deployed MinerU version differs.
        """
        markdown = _extract_markdown(response_json)
        images_by_reference = _extract_images_by_reference(response_json)

        ordered_image_bytes: list[bytes] = []

        def _swap_for_placeholder(match: re.Match[str]) -> str:
            reference = match.group(1)
            image_bytes = images_by_reference.get(reference) or images_by_reference.get(
                Path(reference).name
            )
            if image_bytes is None:
                # Image referenced but not returned: drop the broken link rather than
                # emit a placeholder with no figure behind it.
                return ""
            ordered_image_bytes.append(image_bytes)
            return FIGURE_PLACEHOLDER_MARKER

        markdown_with_markers = _MARKDOWN_IMAGE_PATTERN.sub(_swap_for_placeholder, markdown)
        figures = [RawFigure(image_png_bytes=image) for image in ordered_image_bytes]
        return RawPage(page_number=page_number, markdown=markdown_with_markers, figures=figures)


def _extract_markdown(response_json: dict[str, Any]) -> str:
    """Pull the page Markdown string out of MinerU's response, or '' if absent."""
    for key in ("md_content", "markdown", "md"):
        value = response_json.get(key)
        if isinstance(value, str):
            return value
    # Some MinerU versions nest results under a per-file list.
    results = response_json.get("results")
    if isinstance(results, list) and results:
        first = results[0]
        if isinstance(first, dict):
            return _extract_markdown(first)
    return ""


def _extract_images_by_reference(response_json: dict[str, Any]) -> dict[str, bytes]:
    """
    Build a {image-reference → PNG bytes} map from MinerU's response.

    Images arrive as base64 strings keyed by the relative path used in the Markdown
    image links. Unparseable entries are skipped rather than failing the page.
    """
    images_field = response_json.get("images")
    if not isinstance(images_field, dict):
        results = response_json.get("results")
        if isinstance(results, list) and results and isinstance(results[0], dict):
            images_field = results[0].get("images")
    if not isinstance(images_field, dict):
        return {}

    decoded: dict[str, bytes] = {}
    for reference, encoded in images_field.items():
        if not isinstance(encoded, str):
            continue
        try:
            # Tolerate data-URI prefixes (``data:image/png;base64,...``).
            payload = encoded.split(",", 1)[-1]
            decoded[reference] = base64.b64decode(payload)
        except (ValueError, TypeError):
            logger.debug("mineru.image_decode_skipped reference=%s", reference)
    return decoded
