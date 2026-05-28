"""
engine_bootstrap/mineru_backend_ladder.py
==========================================
Work out which MinerU backends are actually reachable on this machine.

MinerU can run several ways — a local GPU VLM, a remote VLM server, a CPU pipeline —
ranked highest-quality-first in ``MinerUEngineConfig.backend_ladder``. But not every
rung is usable everywhere: the GPU VLM needs enough VRAM, the remote rung needs a
server URL. This module is the single, pure place that filters the configured ladder
down to the rungs this hardware/config can reach, in order.

Why it lives here, and why it is shared
---------------------------------------
Two very different components need the *same* answer and must never disagree:

  * the **bootstrap** layer, to decide which model families to download ahead of time
    (no point fetching multi-GB VLM weights on a card that can't run the VLM), and
  * the **MinerU engine**, to pick its starting rung and its step-down order at run
    time.

Putting the rule here — in the preparedness layer, depending only on config and a VRAM
number — lets both call it without depending on each other, and guarantees the engine
never tries a rung whose models bootstrap didn't fetch.

This module is pure: it takes a VRAM figure as input rather than reading the GPU
itself, so it is trivial to reason about and the caller owns the hardware query.
"""

from __future__ import annotations

from ..contracts.configurations.mineru_engine_config import BackendRung, MinerUEngineConfig
from ..contracts.pipeline_domain_types import MinerUBackend

# Maps a rung's backend name to the model family ``mineru-models-download -m`` fetches.
# Remote rungs (``*-http-client``) run the model elsewhere, so they need no local
# weights and map to None.
_VLM_MODEL_FAMILY = "vlm"
_PIPELINE_MODEL_FAMILY = "pipeline"


def configured_ladder(config: MinerUEngineConfig) -> list[BackendRung]:
    """
    Return the ladder to walk for this config: the full ladder, or a pinned single rung.

    ``backend: auto`` walks ``backend_ladder``. A pinned ``backend`` (vlm / pipeline) is
    an explicit operator override, so it becomes a one-rung ladder with no VRAM gate —
    the operator's choice is honoured even on small hardware (a failure then surfaces
    reactively rather than being silently filtered away).
    """
    if config.backend == MinerUBackend.AUTO:
        return list(config.backend_ladder)
    if config.backend == MinerUBackend.PIPELINE:
        return [BackendRung(backend="pipeline", min_vram_mb=0)]
    # MinerUBackend.VLM pinned — min_vram_mb 0 so the proactive gate never drops it.
    return [BackendRung(backend="vlm-auto-engine", min_vram_mb=0)]


def resolve_reachable_rungs(
    ladder: list[BackendRung],
    *,
    free_vram_mb: int,
    max_vram_mb: int,
    server_url: str | None,
) -> list[BackendRung]:
    """
    Filter the ordered ladder to the rungs usable on this hardware/config, in order.

    A rung is kept when:
      * the **usable VRAM** — the smaller of the GPU's free VRAM and the operator's
        configured ``max_vram_mb`` budget — is at least the rung's ``min_vram_mb``, and
      * the rung does not require a ``server_url`` that is missing.

    Capping free VRAM by the budget means an operator can hold the VLM back even on a
    big card (by lowering ``max_vram_mb``), and a CPU-capable rung (``min_vram_mb`` 0)
    is always kept — so the result is never empty as long as the ladder has a floor.
    """
    usable_vram_mb = min(free_vram_mb, max_vram_mb)
    reachable: list[BackendRung] = []
    for rung in ladder:
        if rung.requires_server_url and not server_url:
            continue
        if rung.min_vram_mb > usable_vram_mb:
            continue
        reachable.append(rung)
    return reachable


def rung_model_family(backend: str) -> str | None:
    """
    Return the downloadable model family a backend needs, or None if it needs none.

    ``vlm-*`` (local) → the VLM family; ``pipeline`` → the pipeline family;
    ``*-http-client`` → None (the model lives on the remote server).
    """
    if backend.endswith("-http-client"):
        return None
    if backend.startswith("vlm-"):
        return _VLM_MODEL_FAMILY
    if backend == "pipeline" or backend.startswith("hybrid-"):
        return _PIPELINE_MODEL_FAMILY
    return None


def model_families_for_rungs(rungs: list[BackendRung]) -> list[str]:
    """
    The de-duplicated model families to download so every given rung can run.

    Order-preserving (highest rung's family first) so bootstrap logs read top-down.
    """
    families: list[str] = []
    for rung in rungs:
        family = rung_model_family(rung.backend)
        if family is not None and family not in families:
            families.append(family)
    return families
