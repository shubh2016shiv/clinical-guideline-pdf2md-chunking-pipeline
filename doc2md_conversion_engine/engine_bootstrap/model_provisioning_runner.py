"""
engine_bootstrap/model_provisioning_runner.py
==============================================
Run a model-download command to completion, untimed, with its progress visible.

Both engines acquire their models by invoking a small command-line tool
(``mineru-models-download`` for MinerU, ``docling-tools models download`` for Docling).
This shared helper runs such a command the right way for a *provisioning* step:

  * **No timeout.** Downloading gigabytes is allowed to take as long as the network
    needs. Putting a deadline here would recreate the very problem bootstrap exists to
    solve.
  * **Progress is logged.** The tool's output is streamed line by line to the logger,
    so a long download shows movement instead of looking hung.
  * **Failures are explicit.** A missing tool or a non-zero exit becomes an
    ``EngineBootstrapError`` with an actionable message, never a silent partial state.

Idempotency is the caller's concern: the download tools skip files already present, so
re-running a provisioning command is a cheap no-op once the cache is warm.
"""

from __future__ import annotations

import asyncio
import logging

from .engine_bootstrap_interface import EngineBootstrapError

logger = logging.getLogger(__name__)


async def run_provisioning_command(command: list[str], *, description: str) -> None:
    """
    Execute a provisioning command, streaming output, and wait for it to finish.

    Args:
        command: The argv list to run (e.g. ``["mineru-models-download", "-m", "vlm"]``).
        description: Short human label used in logs (e.g. "MinerU VLM model download").

    Raises:
        EngineBootstrapError: The command's executable is not installed, or it exited
            with a non-zero status.
    """
    logger.info("bootstrap.provision.start %s :: %s", description, " ".join(command))
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except FileNotFoundError as exc:
        raise EngineBootstrapError(
            f"Cannot provision: the tool {command[0]!r} is not installed or not on PATH.",
            context={"description": description, "command": command},
        ) from exc

    await _stream_output_to_log(process, description)
    return_code = await process.wait()
    if return_code != 0:
        raise EngineBootstrapError(
            f"{description} failed (exit code {return_code}).",
            context={"description": description, "command": command, "exit_code": return_code},
        )
    logger.info("bootstrap.provision.done %s", description)


async def _stream_output_to_log(
    process: asyncio.subprocess.Process,
    description: str,
) -> None:
    """Forward the subprocess's combined output to the logger, one line at a time."""
    if process.stdout is None:
        return
    async for raw_line in process.stdout:
        line = raw_line.decode("utf-8", errors="replace").rstrip()
        if line:
            logger.info("bootstrap.provision %s | %s", description, line)
