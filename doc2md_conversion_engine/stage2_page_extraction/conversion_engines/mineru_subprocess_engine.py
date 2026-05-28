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

Choosing the backend (and why this matters for the GPU)
-------------------------------------------------------
MinerU only accepts a fixed set of backend names — ``pipeline``, ``vlm-auto-engine``,
``vlm-http-client``, ``hybrid-auto-engine``, ``hybrid-http-client``. If it receives an
unrecognised name it *silently skips the file* and returns empty content, doing no GPU
work at all. So this adapter maps the configured ``MinerUBackend`` to a real MinerU
name: ``pipeline`` stays ``pipeline`` (CPU), and ``vlm`` / ``auto`` resolve to
``vlm-auto-engine`` (local GPU compute) when a GPU is available, else ``pipeline``.

Loading the VLM model up front
------------------------------
When a VLM backend is used, the model load is forced at subprocess startup
(``--enable-vlm-preload``) so it happens during ``start()`` while we poll ``/health`` —
not inside a timed extraction window. This is the same warmup discipline the Docling
engine follows: one-time model loading must not count against the per-window timeout.

One request per page
--------------------
MinerU returns Markdown for a *range* of pages, not split per page. To honour the
pipeline's per-page contract we ask it for one page at a time (so each response maps
to exactly one ``PageResult``).

Response shape (validated against the installed MinerU ``/file_parse``)
-----------------------------------------------------------------------
``/file_parse`` returns ``{"results": {"<pdf_name>": {"md_content": str,
"images": {"<basename>": "data:<mime>;base64,<...>"}}}}``. We send a single file, so we
read the one entry under ``results``. The mapping lives in ``_raw_page_from_response``.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
import tempfile
import time
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import IO, Any

from ...contracts.configurations.mineru_engine_config import BackendRung, MinerUEngineConfig
from ...contracts.configurations.pipeline_config import GPUConfig
from ...contracts.conversion_engine_interface import AbstractConversionEngine
from ...contracts.exceptions import EngineError, EngineStartupError
from ...contracts.pipeline_domain_types import ExtractionEngine, PageResult
from ...engine_bootstrap import configured_ladder, resolve_reachable_rungs
from ...gpu_resource_management import GPUVRAMUsageMonitor
from ..page_result_builders import FIGURE_PLACEHOLDER_MARKER, RawFigure, RawPage, build_page_result

logger = logging.getLogger(__name__)

# MinerU renders embedded images as standard Markdown image syntax; we rewrite each
# to the shared figure placeholder so the builder can tokenise them uniformly.
_MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")

# How often to poll /health while waiting for the subprocess to come up.
_HEALTH_POLL_INTERVAL_SECONDS = 1.0

# Lowercased substrings that mark a GPU resource-exhaustion failure. These are the only
# failures that trigger a step DOWN the capability ladder (a smaller backend may still
# succeed); any other failure propagates to the resilient layer unchanged.
_RESOURCE_EXHAUSTION_SIGNATURES = ("out of memory", "oom", "cuda error")


class MinerUSubprocessEngine(AbstractConversionEngine):
    """
    Convert documents with MinerU running as a managed ``mineru-api`` subprocess.

    Constructed per job so it can stamp the document's ``job_id`` into figure tokens.
    Always used as an async context manager so the subprocess is guaranteed to be
    shut down even on error.
    """

    def __init__(self, config: MinerUEngineConfig, gpu_config: GPUConfig, job_id: str) -> None:
        self._config = config
        self._gpu_config = gpu_config
        self._job_id = job_id
        self._vram_monitor = GPUVRAMUsageMonitor(gpu_config)
        # The full configured ladder (top rung first). Its top rung defines what "not
        # degraded" means for this document.
        self._configured_ladder = configured_ladder(config)
        # The rungs actually reachable on this hardware/config, resolved at start().
        # The engine starts at the top of this list and steps DOWN (committing, never
        # back) as rungs prove unusable — see ``_parse_page_walking_ladder``.
        self._reachable_rungs: list[BackendRung] = []
        self._current_rung_index = 0
        self._process: asyncio.subprocess.Process | None = None
        # The mineru-api subprocess's own output is captured to this file so its
        # internal failures (a failed parse, an OOM, a traceback) are inspectable
        # rather than lost to /dev/null.
        self._server_log_handle: IO[bytes] | None = None

    @property
    def engine_type(self) -> ExtractionEngine:
        return ExtractionEngine.MINERU

    # ------------------------------------------------------------------
    # Capability ladder state
    # ------------------------------------------------------------------

    def _current_rung(self) -> BackendRung:
        """The rung currently in use (the backend sent on each ``/file_parse``)."""
        return self._reachable_rungs[self._current_rung_index]

    def _step_down_rung(self) -> bool:
        """
        Commit to the next lower reachable rung; return False if already at the floor.

        The step is permanent for the rest of the document (no step-back): the
        condition that forced it — insufficient VRAM, GPU contention — will not have
        cleared by the next page, and per-document uniform accuracy is a cleaner
        downstream contract than mixed-mode output.
        """
        if self._current_rung_index + 1 < len(self._reachable_rungs):
            self._current_rung_index += 1
            return True
        return False

    def _is_below_top_capability(self) -> bool:
        """True when the current rung is not the routed engine's top rung (→ degraded)."""
        return self._current_rung().backend != self._configured_ladder[0].backend

    def _uses_local_vlm(self) -> bool:
        """Whether the current rung loads a local VLM model (and so the GPU)."""
        return self._current_rung().backend.startswith(("vlm-", "hybrid-"))

    async def start(self) -> None:
        """
        Resolve the reachable ladder, launch ``mineru-api``, and wait until it is healthy.

        The reachable rungs are computed here (against live free VRAM), the engine
        starts at the top reachable rung, and the subprocess preloads the VLM only when
        that starting rung needs it. Raises ``EngineStartupError`` if no rung is
        reachable, or if the subprocess does not become healthy within the startup
        timeout — the subprocess is torn down first so a failed start never leaks a
        child process.
        """
        if self._process is not None:
            return

        self._reachable_rungs = resolve_reachable_rungs(
            self._configured_ladder,
            free_vram_mb=self._vram_monitor.current_free_mb(),
            max_vram_mb=self._gpu_config.max_vram_mb,
            server_url=self._config.server_url,
        )
        if not self._reachable_rungs:
            raise EngineStartupError(
                "No MinerU backend rung is reachable on this hardware/configuration.",
                context={
                    "engine": ExtractionEngine.MINERU.value,
                    "configured_ladder": [rung.backend for rung in self._configured_ladder],
                },
            )
        self._current_rung_index = 0
        logger.info(
            "mineru.ladder reachable=%s starting=%s",
            [rung.backend for rung in self._reachable_rungs],
            self._current_rung().backend,
        )

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
        self._process = None
        try:
            if process is not None and process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=10.0)
                except (TimeoutError, asyncio.TimeoutError):
                    logger.warning("mineru.subprocess.kill (did not exit on terminate)")
                    process.kill()
                    await process.wait()
        finally:
            self._close_server_log()

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
            raw_page = await self._parse_page_walking_ladder(
                document_path, page_number, window_output_dir
            )
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            yield build_page_result(
                job_id=self._job_id,
                engine=ExtractionEngine.MINERU,
                raw_page=raw_page,
                window_output_dir=window_output_dir,
                duration_ms=duration_ms,
                effective_backend=self._current_rung().backend,
                is_degraded=self._is_below_top_capability(),
            )

    async def _parse_page_walking_ladder(
        self,
        document_path: str,
        page_number: int,
        window_output_dir: Path,
    ) -> RawPage:
        """
        Parse one page, stepping DOWN the capability ladder on resource exhaustion.

        Try the current rung. On a resource-exhaustion failure (e.g. VLM out of memory)
        commit to the next lower rung and retry the same page — this is the reactive
        half of the fallback, catching what the proactive VRAM check could not predict
        (a stale snapshot, GPU contention). Once no lower rung remains, or the failure
        is *not* resource exhaustion (a malformed page, a transport error), the error
        propagates to the resilient layer, which decides on cross-engine fallback.
        """
        while True:
            backend = self._current_rung().backend
            try:
                return await self._parse_one_page_on(backend, document_path, page_number, window_output_dir)
            except EngineError as exc:
                if not _is_resource_exhaustion(exc):
                    raise  # not a step-down trigger — let the resilient layer handle it
                if not self._step_down_rung():
                    raise  # already at the floor rung — nothing lighter to try
                logger.warning(
                    "mineru.rung.stepdown reason=resource_exhaustion from=%s to=%s page=%s",
                    backend,
                    self._current_rung().backend,
                    page_number,
                )

    # ------------------------------------------------------------------
    # Subprocess lifecycle
    # ------------------------------------------------------------------

    async def _spawn_subprocess(self) -> asyncio.subprocess.Process:
        """
        Start the ``mineru-api`` server bound to the configured host/port.

        When a local VLM backend is in use, ask the server to preload the VLM model so
        the (slow, one-time) model load completes during startup health-polling rather
        than inside a timed extraction window.
        """
        args = [
            "mineru-api",
            "--host",
            self._config.api_host,
            "--port",
            str(self._config.api_port),
        ]
        if self._uses_local_vlm():
            args += ["--enable-vlm-preload", "true"]

        log_path = Path(tempfile.gettempdir()) / f"mineru-api-{self._job_id}.log"
        self._server_log_handle = log_path.open("wb")
        logger.info("mineru.subprocess.starting log=%s :: %s", log_path, " ".join(args))
        try:
            return await asyncio.create_subprocess_exec(
                *args,
                stdout=self._server_log_handle,
                stderr=asyncio.subprocess.STDOUT,
            )
        except FileNotFoundError as exc:
            self._close_server_log()
            raise EngineStartupError(
                "The 'mineru-api' executable was not found. Install MinerU with its API extra.",
                context={"engine": ExtractionEngine.MINERU.value},
            ) from exc

    def _close_server_log(self) -> None:
        """Close the subprocess log file handle if open. Safe to call repeatedly."""
        if self._server_log_handle is not None:
            self._server_log_handle.close()
            self._server_log_handle = None

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

    async def _parse_one_page_on(
        self,
        backend: str,
        document_path: str,
        page_number: int,
        window_output_dir: Path,
    ) -> RawPage:
        """Send one page to MinerU on a specific backend and build a ``RawPage``."""
        response_json = await self._request_page_parse(document_path, page_number, backend)
        return self._raw_page_from_response(response_json, page_number, window_output_dir)

    async def _request_page_parse(
        self,
        document_path: str,
        page_number: int,
        backend: str,
    ) -> dict[str, Any]:
        """
        POST a single page to ``/file_parse`` on ``backend`` and return the parsed JSON.

        MinerU uses 0-based page ids; the window timeout bounds how long one page may
        take before it is treated as an engine failure (so the ladder/resilient layers
        can fall back).
        """
        import httpx

        zero_based_page = page_number - 1
        form = {
            "backend": backend,
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
        except httpx.HTTPError as exc:
            # Transport-level failure (connection dropped, read timeout) — no body to read.
            raise EngineError(
                f"MinerU request failed for page {page_number}: {exc}",
                context={
                    "engine": ExtractionEngine.MINERU.value,
                    "page_number": page_number,
                    "api_base_url": self._config.api_base_url,
                },
            ) from exc

        if response.status_code >= 400:
            # MinerU answered, but its parse task failed (e.g. 409). The response body
            # carries the actual reason — surface it instead of a generic message, and
            # point at the subprocess log for the full traceback.
            mineru_detail = _extract_mineru_error(response)
            raise EngineError(
                f"MinerU failed to parse page {page_number} "
                f"(HTTP {response.status_code}): {mineru_detail}",
                context={
                    "engine": ExtractionEngine.MINERU.value,
                    "page_number": page_number,
                    "status_code": response.status_code,
                    "mineru_detail": mineru_detail,
                    "backend": backend,
                    "server_log": str(
                        Path(tempfile.gettempdir()) / f"mineru-api-{self._job_id}.log"
                    ),
                },
            )

        try:
            return response.json()
        except ValueError as exc:
            raise EngineError(
                f"MinerU returned a non-JSON response for page {page_number}.",
                context={
                    "engine": ExtractionEngine.MINERU.value,
                    "page_number": page_number,
                    "body_preview": response.text[:500],
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

        MinerU returns the page's Markdown plus its images keyed by the image's
        basename. We swap each image link in the Markdown for the shared figure
        placeholder, in order, and decode the matching image bytes so the builder can
        tokenise them. This is the single MinerU-schema-dependent method.
        """
        file_result = _single_file_result(response_json)
        markdown = file_result.get("md_content") or ""
        images_by_reference = _decode_images(file_result.get("images"))

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


def _is_resource_exhaustion(error: EngineError) -> bool:
    """
    Decide whether a MinerU failure is GPU resource exhaustion (→ step down the ladder).

    Looks for the tell-tale signatures (e.g. "CUDA out of memory") in the failure's
    surfaced detail and message. Only these trigger a step-down; every other failure
    (a malformed page, a transport error) propagates so a lower rung is not pointlessly
    tried for a problem it would hit too.
    """
    haystack = str(error).lower()
    detail = error.context.get("mineru_detail")
    if isinstance(detail, str):
        haystack = f"{haystack} {detail.lower()}"
    return any(signature in haystack for signature in _RESOURCE_EXHAUSTION_SIGNATURES)


def _extract_mineru_error(response: Any) -> str:
    """
    Pull the human-readable failure reason out of a non-2xx ``/file_parse`` response.

    MinerU's failed-task responses carry the reason in JSON fields (``error`` and/or
    ``message``); when the body is not JSON we fall back to a trimmed raw text preview.
    Either way the caller gets *something* actionable instead of a bare status code.
    """
    try:
        body = response.json()
    except ValueError:
        return response.text[:500].strip() or f"HTTP {response.status_code}"
    if isinstance(body, dict):
        reason = " | ".join(
            str(body[key]) for key in ("error", "message") if body.get(key)
        )
        return reason or str(body)[:500]
    return str(body)[:500]


def _single_file_result(response_json: dict[str, Any]) -> dict[str, Any]:
    """
    Return the per-file result dict from MinerU's ``{"results": {name: {...}}}``.

    We upload exactly one file per request, so there is a single entry under
    ``results``; return it, or an empty dict when the response carries no results
    (e.g. MinerU skipped the file). Reading the value by position keeps us independent
    of the (sanitised) filename MinerU echoes back as the key.
    """
    results = response_json.get("results")
    if isinstance(results, dict) and results:
        first_value = next(iter(results.values()))
        if isinstance(first_value, dict):
            return first_value
    return {}


def _decode_images(images_field: Any) -> dict[str, bytes]:
    """
    Decode MinerU's ``{basename: "data:<mime>;base64,<...>"}`` image map to bytes.

    Unparseable entries are skipped rather than failing the page.
    """
    if not isinstance(images_field, dict):
        return {}
    decoded: dict[str, bytes] = {}
    for reference, encoded in images_field.items():
        if not isinstance(encoded, str):
            continue
        try:
            # Strip the ``data:image/...;base64,`` prefix before decoding.
            payload = encoded.split(",", 1)[-1]
            decoded[reference] = base64.b64decode(payload)
        except (ValueError, TypeError):
            logger.debug("mineru.image_decode_skipped reference=%s", reference)
    return decoded
