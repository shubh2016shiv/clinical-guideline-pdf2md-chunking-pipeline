# Stage 2 — Page Extraction (Design Plan)

> **One sentence:** Stage 1 decided *which* engine to use; Stage 2 actually runs
> it — converting the document to per-page Markdown, one page at a time, while
> staying memory-bounded, resumable, and able to fall back to a second engine if
> the first one fails.

> **Status:** **Implemented.** This document began as the pre-implementation
> blueprint; the structure, names, and responsibilities below are now built and
> verified end-to-end (fresh run, resume-after-crash, and fault-tolerant fallback)
> against a fake engine. One file not in the original plan — `window_result_store.py`
> — was added during implementation because correct resume requires it (see §5.2);
> that is the one place the built code differs from the first draft. It deliberately
> mirrors the style of `STAGE_1_GUIDE.md` one folder up.

---

## 1. The idea in plain terms

Think back to the print-shop analogy from Stage 1. Stage 1 was the five-second
*glance* that decided which machine to use. **Stage 2 is feeding the document
through that machine and catching the printed pages as they come out.**

But a clinical guideline can be 500 pages. We cannot shove all 500 pages into the
machine at once (it would run out of memory), and we don't want to do them strictly
one-at-a-time (too slow). So we feed the document through in small **windows** —
say 8 pages at a time. After each window finishes, we write its results safely to
disk and remember how far we got, so that if the power is cut at page 240 we resume
at page 241 instead of starting over.

And machines jam. If the powerful-but-temperamental engine (MinerU) starts failing,
Stage 2 must not abandon the document — it quietly switches to the simpler, reliable
engine (Docling) and keeps going, marking those pages so we know they were handled
by the fallback.

That is the whole job of Stage 2, and it breaks into exactly three concerns:

| Concern | The question a debugging developer asks | Sub-package |
|--------|------------------------------------------|-------------|
| **WHO** converts | *"Did the right engine run, and did fallback work?"* | `conversion_engines/` |
| **HOW** pages flow | *"Did the windowing, GPU, and resume loop work?"* | `windowed_extraction/` |
| **WHAT** each page becomes | *"Is this one page's markdown / figure / table wrong?"* | `page_result_builders/` |

### Where Stage 2 sits in the pipeline

```
   STAGE 1                    STAGE 2                      STAGE 3 / 4
   prescanning                page extraction              figures / assembly
   ───────────                ───────────────              ──────────────────
   "which engine?"   ──▶      run that engine,      ──▶    summarise figures,
                              page by page,                stitch final Markdown
                              stream PageResults
        │                          │                            │
   EngineClassification      one PageResult per page       final .md on disk
   {engine, backend}         (markdown + figures + tables)
```

Stage 2 takes two things from Stage 1 — a **`ConversionJob`** (the document's
identity and where to write output) and an **`EngineClassification`** (the engine
to use) — and produces an ordered **stream of `PageResult` objects**, one per page,
handed downstream as each page finishes.

---

## 2. What already exists (the honest starting point)

Before designing anything, here is exactly what is built versus what is an empty
shell. This matters: Stage 2 is not built from scratch — most of its hard parts
(GPU locking, fault tolerance, the data shapes) already exist and just need wiring.

### Already implemented — Stage 2 *uses* these, does not rebuild them

```
contracts/
  conversion_engine_interface.py     ✅  the AbstractConversionEngine contract
                                          (start / stop / is_available / convert_window)
  pipeline_domain_types.py           ✅  PageResult, Figure, Table, ConversionJob,
                                          EngineClassification — the shapes we produce
  windowed_checkpoint_store_interface.py ✅ AbstractCheckpointStore + CheckpointState,
                                          WindowRecord, EngineSnapshot (resume contract)

gpu_resource_management/
  exclusive_gpu_context_manager.py   ✅  one-engine-at-a-time GPU lock
  gpu_vram_usage_monitor.py          ✅  VRAM budget check

fault_tolerance/
  circuit_breaker.py                 ✅  trips primary → fallback after N failures
  retry_policy.py                    ✅  exponential backoff
  timeout_guard.py                   ✅  per-window / per-acquire timeouts

observability/
  per_page_conversion_event_logger.py ✅ one audit event per completed page

contracts/configurations/
  WindowedExtractionConfig           ✅  window_size, max_concurrent_windows,
                                          checkpoint_interval_pages
  GPUConfig, FaultToleranceConfig    ✅  all knobs already in settings.yaml
  MinerUEngineConfig, DoclingEngineConfig ✅
```

### Empty placeholders — the work to be done

```
stage2_page_extraction/                 ← ALL 8 files are 0 bytes
  conversion_engines/
    conversion_engine_router.py         ❌
    docling_inprocess_engine.py         ❌
    mineru_subprocess_engine.py         ❌
  gpu_engine_resource_coordinator.py               ❌
  windowed_extraction_orchestrator.py   ❌
  page_element_extractors/
    cross_page_table_merger.py          ❌
    figure_placeholder_token_injector.py ❌
    markdown_text_extractor.py          ❌

checkpointing/                          ← concrete persistence, also empty
  windowed_checkpoint_file_store.py     ❌  (implements AbstractCheckpointStore)
  checkpoint_resume_state_loader.py     ❌
```

### Two things to be aware of

- **Stale contract leftovers.** `PageProfile` and the *"complexity_score ≥ 2.0 →
  MinerU VLM"* wording in `pipeline_domain_types.py` describe the *old probabilistic*
  router that the Stage 1 refactor replaced with deterministic routing. Stage 2 only
  reads `EngineClassification.engine` and `.backend`, so it is unaffected — but those
  docs will mislead whoever implements Stage 2 and deserve a separate cleanup.
- **First async code in the pipeline.** The engine interface is `async` (engines
  start subprocesses, await HTTP health checks, stream pages). The orchestrator today
  is synchronous (`run_stage1`). Stage 2 introduces the pipeline's first `async` path.

---

## 3. Design principles (carried over from Stage 1)

The same contract that shaped the Stage 1 refactor applies here:

- **Sub-packages map onto the questions a debugger asks**, not onto technical layers.
- **Facts, not opinions** — a page-builder records "this table continues on the next
  page"; it does not decide how to merge it.
- **Names you understand without reading the code** — at folder, file, and function
  level.
- **One front door per concern** — callers import the orchestrator, never reach into
  an engine's internals.
- **No overprivileged modules** — the GPU lock knows nothing about figures; the
  figure-token injector knows nothing about windows.

---

## 4. Proposed structure

```
stage2_page_extraction/
│
├── __init__.py            # re-exports the orchestrator (the one public entry point)
│
├── conversion_engines/                    ──▶  WHO converts
│   │                                            engine strategies + resilient composition
│   ├── docling_inprocess_engine.py        # (keep)   in-process engine, implements the interface
│   ├── mineru_subprocess_engine.py        # (keep)   subprocess + HTTP engine, implements the interface
│   ├── resilient_conversion_engine.py     # (rename) fault-tolerant wrapper: primary + Docling fallback
│   └── conversion_engine_factory.py       # (new)    builds engines from EngineClassification + config
│
├── windowed_extraction/                   ──▶  HOW pages flow
│   │                                            windowing, GPU scheduling, checkpoint/resume loop
│   ├── windowed_page_extraction_orchestrator.py  # (rename) Stage 2 entry: drives the loop, streams PageResults
│   ├── page_window_planner.py             # (new)    pure logic: pages + window_size + resume point → windows to run
│   ├── gpu_engine_resource_coordinator.py            # (keep)   lifecycle exclusive GPU lease; CPU-mode no-op; VRAM observability
│   └── window_result_store.py             # (added)  persist each window's PageResults; replay them on resume
│
└── page_result_builders/                  ──▶  WHAT each page becomes
    │                                            shared helpers BOTH engines call so PageResults are identical
    ├── page_result_builder.py             # (new)    coordinator → returns one PageResult
    ├── page_markdown_reader.py            # (rename) read the per-page markdown the engine wrote to disk
    ├── figure_token_injector.py           # (rename) figure → PNG + sha256 + ${FIG:..} token
    └── table_token_injector.py            # (rename) lift tables out to ${TBL:..} tokens; flag fragments
```

### Rename rationale (placeholder → proposed, and why)

| Current placeholder | Proposed name | Why the change |
|---|---|---|
| `conversion_engines/conversion_engine_router.py` | `resilient_conversion_engine.py` | "Router" **collides** with Stage 1's `engine_routing`, which picks the engine *per document*. This component does something different: it *runs* the chosen engine and *degrades to Docling on failure*. It is cleanest modeled as a decorator that **itself implements `AbstractConversionEngine`**, so the orchestrator just sees "an engine" and never knows a fallback happened. |
| *(none)* | `conversion_engine_factory.py` *(new)* | Separates **construction** (which class, which config) from **execution**. Keeps the orchestrator from importing concrete engine classes — dependency inversion, trivial to stub in tests. |
| `windowed_extraction_orchestrator.py` *(loose)* | `windowed_extraction/windowed_page_extraction_orchestrator.py` | Grouped with its two collaborators into one sub-package. |
| `gpu_engine_resource_coordinator.py` *(loose)* | `windowed_extraction/gpu_engine_resource_coordinator.py` | It is part of the loop, not a standalone top-level concern. |
| *(none)* | `windowed_extraction/page_window_planner.py` *(new)* | **Pure, synchronous, no I/O.** Given total pages, window size, and the checkpoint's `last_completed_page`, it returns the windows still to run. Splitting this out makes resume logic unit-testable *without a GPU or an engine* — a major debuggability win. |
| `page_element_extractors/` | `page_result_builders/` | "Extractors" overlaps with the engines (which also extract). These helpers don't touch the document — they *shape* raw engine artifacts into the canonical `PageResult`. |
| `markdown_text_extractor.py` | `page_markdown_reader.py` | It *reads* the markdown the engine already wrote; "reader" says exactly that. |
| `figure_placeholder_token_injector.py` | `figure_token_injector.py` | Shorter, same meaning. |
| `cross_page_table_merger.py` | `table_token_injector.py` | **Boundary correction** — see §6. In Stage 2 we lift each table out of the Markdown to a `${TBL:..}` token (symmetric with figures) and *flag* fragments; the actual *merge* belongs to Stage 4's assembler. |

---

## 5. The three sub-packages explained

### 5.1 `conversion_engines/` — WHO converts

This holds the two real engines plus the machinery that picks between them and keeps
them resilient.

**`docling_inprocess_engine.py`** and **`mineru_subprocess_engine.py`** are the two
*Strategy* implementations of `AbstractConversionEngine`. They are interchangeable:
the rest of Stage 2 calls the same four methods (`start`, `stop`, `is_available`,
`convert_window`) and never knows which one is running.

- *Docling* runs **in-process** — its models load directly into this Python process.
  Faster to start, simpler to debug, but it shares the GPU with nothing else.
- *MinerU* runs as a **subprocess** — it launches its own `mineru-api` server and we
  talk to it over HTTP on localhost. Heavier, but isolated so its GPU memory
  management can't collide with ours.

**`resilient_conversion_engine.py`** is the clever piece. It also implements
`AbstractConversionEngine`, but instead of converting anything itself it **wraps a
primary engine and a fallback engine**. Every call to `convert_window` is guarded by
the already-built fault-tolerance primitives (circuit breaker, retry, timeout). If
the primary engine keeps failing, the circuit breaker *trips* and subsequent windows
are sent to Docling instead — and those pages are marked `is_degraded=True` so we can
measure the accuracy impact later. Because this wrapper *is* an engine, the
orchestrator above it stays blissfully unaware that any of this happened.

```
            orchestrator sees ONE engine
                       │
                       ▼
        ┌──────────────────────────────────┐
        │   resilient_conversion_engine     │
        │   (implements the interface)      │
        │                                    │
        │   try primary  ──fails N times──┐  │
        │      │                          │  │
        │      ▼                          ▼  │
        │  ┌─────────┐   breaker trips  ┌────────┐
        │  │ MinerU  │ ───────────────▶ │ Docling │  (fallback)
        │  └─────────┘                  └────────┘
        └──────────────────────────────────┘
```

**`conversion_engine_factory.py`** builds the right engine objects from the
`EngineClassification` and config, then wraps them in the resilient engine. This is
the *only* place that imports the concrete engine classes — everything else depends
on the interface.

### 5.2 `windowed_extraction/` — HOW pages flow

This is the loop that drives the whole stage.

**`page_window_planner.py`** is deliberately tiny and pure. It answers one question
with no side effects: *given a 500-page document, a window size of 8, and a checkpoint
saying page 240 is done, which windows still need running?* (Answer:
`[241..248], [249..256], …`.) Keeping this free of GPU, async, and I/O means the
resume math can be tested in milliseconds — and resume math is exactly the kind of
off-by-one logic that is miserable to debug if it's tangled into the async loop.

**`gpu_engine_resource_coordinator.py`** wraps the engine lifecycle in the exclusive GPU context (so only
one live engine owns VRAM), and records VRAM before startup and each window. It is
the gatekeeper between "we want to run this engine" and "the GPU is actually ours to
use right now."

**`window_result_store.py`** persists each window's `PageResult`s to its result
folder (one JSON per page) and reads them back. This earns its place because correct
resume demands it: on restart, the pages from already-finished windows still have to
reach Stage 4, but they must *not* be re-extracted (that is the GPU time the
checkpoint exists to save). So they are replayed from disk. (This file was added
during implementation — the original plan assumed figure PNGs alone would make a
window folder non-empty, but a text-only page writes no figures, so the page results
themselves must be persisted.)

**`windowed_page_extraction_orchestrator.py`** is the Stage 2 entry point and the
conductor. It resolves the resume plan, **replays completed windows from disk** so the
downstream stream is whole, asks the planner for the remaining windows and the factory
for the engine, then walks those windows: lease GPU → convert → persist + build each
`PageResult` → yield it downstream → checkpoint. It is the one class the rest of the
pipeline imports.

### 5.3 `page_result_builders/` — WHAT each page becomes

> **Why is this a separate sub-package and not just code inside each engine?**
> Because the figure-token *format*, the image *sha256* scheme, and the table-fragment
> *heuristic* must be **byte-for-byte identical** whether Docling or MinerU produced
> the page. Stage 3's figure deduplication and Stage 4's token resolution both depend
> on that consistency. Put this logic in one shared place that both engines call, and
> there is exactly one spot to debug a malformed token — not two copies that can drift
> apart.

**`page_markdown_reader.py`** reads the raw per-page Markdown an engine wrote to disk.

**`figure_token_injector.py`** takes each figure an engine extracted, writes its PNG,
computes the SHA-256 of the image bytes, and replaces the figure's spot in the page
Markdown with a placeholder token like `${FIG:<job_id>:042:0}`. Stage 3 later swaps
that token for a real vision-LLM summary. (Writing a token now instead of blocking on
the LLM is what keeps GPU extraction running at full speed.)

**`table_token_injector.py`** lifts each table out of the page Markdown, leaving a
`${TBL:<job_id>:042:0}` token in its place (symmetric with figures) and carrying the
table's Markdown in a structured `Table` record. It also flags a table `is_fragment`
when it reaches the bottom of the page and may run onto the next. The token is what
lets Stage 4 reassemble — including merging cross-page tables — by **token lookup**
rather than fragile string-matching of table text inside the page. It does **not**
merge — see §6.

**`page_result_builder.py`** is the small coordinator that calls the helpers above
and returns one finished `PageResult { page_number, engine_used, effective_backend,
is_degraded, markdown_with_tokens, figures[], tables[], duration_ms }`. The
`markdown_with_tokens` is the page as a *template*: prose plus `${FIG:...}` and
`${TBL:...}` anchors that Stage 4 resolves into the final document.

---

## 5.5 The capability ladder: degrade *within* an engine before crossing engines

> **The rule:** a timeout must bound only *work*; an engine must exhaust *its own*
> capability modes before the pipeline abandons it for a different engine.

Stage 1 routes a hard document to MinerU for a reason. MinerU itself can run several
ways — ranked highest-quality-first in `mineru_engine.backend_ladder` (config, so the
**order is a stability contract**, fixed before deploy):

| Rung | Accuracy | Needs | Model family |
|------|---------:|-------|--------------|
| `vlm-auto-engine` (local GPU) | 95+ | ~8 GB VRAM | vlm |
| `vlm-http-client` (remote VLM) | 95+ | 2 GB local + `server_url` | none (remote) |
| `pipeline` | 85+ | CPU ✅ or 4 GB GPU | pipeline |

### Two levels of fallback

```
   MinerU (routed)
        │
        ▼
   ┌──────────── INTRA-ENGINE ladder (inside MinerUSubprocessEngine) ───────────┐
   │  start():  reachable = rungs this hardware can run        ← PROACTIVE        │
   │            current = reachable[0]                                            │
   │            preload VLM only if current is a vlm rung                         │
   │                                                                              │
   │  per page: try current rung                                                  │
   │            └─ "CUDA out of memory" ─▶ step DOWN, commit, retry  ← REACTIVE   │
   │               (vlm-auto-engine → pipeline; never steps back up)              │
   └────────────────────────────────────┬─────────────────────────────────────────┘
                       all reachable rungs exhausted (non-OOM error, or OOM at floor)
                                         │
                                         ▼
   ┌──────────── CROSS-ENGINE fallback (resilient_conversion_engine) ────────────┐
   │  MinerU → Docling                                                            │
   └────────────────────────────────────────────────────────────────────────────┘
```

- **Proactive** (`engine_bootstrap.resolve_reachable_rungs`): the starting rung is the
  highest the hardware can actually run — `usable VRAM = min(free VRAM, max_vram_mb)`
  vs. each rung's `min_vram_mb`, using MinerU's documented 8 GB VLM floor. A 6 GB box
  starts at `pipeline`; a 12 GB box starts at `vlm`. **Same code, right choice per box
  — no hardware hardcoding.** This eliminates the predictable failures (model load +
  inference + retries that were always going to OOM).
- **Reactive** (`_parse_page_walking_ladder`): even when the proactive check passed, a
  runtime `CUDA out of memory` (stale VRAM snapshot, contention) steps the engine down
  one rung and retries the page. Only resource-exhaustion triggers a step-down; other
  failures propagate so a lower rung isn't pointlessly tried for a problem it shares.
- **Per-document commit, no step-back:** once stepped down, the engine stays on the
  lower rung for the rest of the document (VRAM pressure won't clear mid-document, and
  uniform per-document accuracy is a clean downstream contract). The MinerU engine is
  built per-document, so the next document starts fresh with a new VRAM check.

### What downstream sees

Each `PageResult` carries `effective_backend` (the rung that ran — `vlm-auto-engine` /
`pipeline` / `None` for Docling) and `is_degraded` (**True when the page ran below the
routed engine's top rung** — covering both a MinerU `vlm→pipeline` step-down *and* a
cross-engine fall to Docling). So `engine_used=mineru, effective_backend=pipeline,
is_degraded=True` is the clean signal that a document got 85+ MinerU instead of 95+.

### Where bootstrap fits

`engine_bootstrap` (untimed, runs before the timed lifecycle) provisions the model
families for **every reachable rung**, so the runtime step-down never blocks on a
download. On a 6 GB box it fetches only the `pipeline` family; on a 12 GB box it
fetches `vlm` + `pipeline`. The starting rung and the bootstrap download set are
computed by the *same* `resolve_reachable_rungs`, so the engine never tries a rung
whose weights bootstrap skipped. Docling has the same shape internally (CUDA→CPU via
its accelerator device), so the pattern — *exhaust an engine's own modes first* — is
uniform, not MinerU-specific plumbing.

---

## 6. The cross-page-table boundary (a deliberate decision)

A table whose header is on page 9 and whose rows continue on page 10 **cannot be
merged inside Stage 2.** Stage 2 streams pages and is memory-bounded — it cannot hold
page 9 in memory waiting to see page 10. So Stage 2 does the part it *can* do
reliably: it anchors every table with a `${TBL:...}` token and flags likely
fragments; Stage 4, which has the whole document in view, merges fragments and
resolves the tokens.

The anchor is the key idea, and it generalises the figure mechanism: **anything that
gets assembled later must leave a stable token in the Markdown during Stage 2**, so the
later stage plugs its result back by token lookup rather than by searching the page
text. Figures (resolved by Stage 3→4) and cross-page tables (merged by Stage 4) are
the two such elements in this pipeline; both now use tokens.

So the boundary is:

```
   STAGE 2  (streaming, bounded memory)        STAGE 4  (assembly, has full view)
   ────────────────────────────────────        ─────────────────────────────────
   table_token_injector                         streaming_document_assembler
   "anchor each table with a ${TBL}     ──▶      "merge fragment + continuation,
    token; flag likely fragments"                 substitute the token with the
                                                   final (merged) table Markdown"
```

This is why the placeholder `cross_page_table_merger.py` is renamed to
`table_token_injector.py`. The *merge* lives in Stage 4, where the whole document is in
view; Stage 2 only anchors and flags. (If you would rather merge tables fully contained
within a single window right here in Stage 2, that role can be added — flag it and the
plan adjusts.)

---

## 7. End-to-end runtime flow

```
 Stage 1 result  ──▶  ConversionJob {job_id, path, type, output_dir, total_pages}
                       EngineClassification {engine, backend}
                                  │
                                  ▼
 ┌──────────────── windowed_page_extraction_orchestrator ────────────────┐
 │                                                                        │
 │  1. load checkpoint  (checkpointing/ store) ── exists? ── resume point │
 │       ├─ none → CheckpointState.fresh(job, classification)             │
 │       └─ resume → replay completed windows' PageResults from disk      │
 │                   (downstream gets every page; no GPU re-extraction)   │
 │                                                                        │
 │  2. conversion_engine_factory                                          │
 │       └─ build primary (from classification) + Docling fallback,       │
 │          wrap both → resilient_conversion_engine                       │
 │             (circuit breaker · retry · timeout — already built)        │
 │                                                                        │
 │  3. page_window_planner(total_pages, window_size, last_completed_page) │
 │       └─ [ [9..16], [17..24], … ]   (already-done windows skipped)     │
 │                                                                        │
 │  4. async with gpu_engine_resource_coordinator.engine_lifecycle():     │
 │       async with engine:        # start adapter / spawn subprocess     │
 │        for window in windows:                                          │
 │         ├─ gpu_engine_resource_coordinator.observe_window_start()      │
 │         ├─ async for raw_page in engine.convert_window(...):           │
 │         │     page_result_builder →                                    │
 │         │        page_markdown_reader · figure_token_injector ·        │
 │         │        table_token_injector      →  PageResult               │
 │         │     yield PageResult  ──▶  Stage 3/4 + PerPageEventLogger     │
 │         └─ write WindowRecord + checkpoint  (atomic write-then-rename)  │
 │       # primary failure mid-run → breaker trips → later windows run on  │
 │       #   Docling; those PageResults carry is_degraded=True            │
 │                                                                        │
 │  5. on exit: engine.stop()  → free GPU / kill subprocess               │
 └────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
              ordered stream of PageResult  ──▶  Stage 3 (figures) / Stage 4 (assembly)
```

The key properties this flow guarantees, and where each comes from:

| Property | Guaranteed by |
|---|---|
| **Memory-bounded** | windows of `window_size` pages; results streamed and released, never all held at once |
| **Resumable** | checkpoint written after each window; `page_window_planner` skips completed windows on restart |
| **Fault-tolerant** | `resilient_conversion_engine` + circuit breaker → Docling fallback, with `is_degraded` flagged |
| **GPU-safe** | `gpu_engine_resource_coordinator` acquires the exclusive GPU context for the engine lifecycle |
| **Consistent output** | both engines build `PageResult` through the *same* `page_result_builders/` |
| **Observable** | one `PerPageConversionEventLogger` event per completed page |

---

## 8. Integration points outside this package

- **`checkpointing/` (empty today).** `windowed_checkpoint_file_store.py` (the concrete
  `AbstractCheckpointStore`, written atomically as write-temp-then-rename) and
  `checkpoint_resume_state_loader.py` must be implemented for resume to work. They
  stay in their own top-level package — checkpointing is a generic persistence concern,
  reusable beyond Stage 2 — but they are a **hard prerequisite** for Stage 2's resume
  feature.
- **`pipeline_orchestrator.py`.** Add an `async run_stage2(...)` (or a unifying
  `async run(...)`) that turns the Stage 1 result into a `ConversionJob` and drives the
  Stage 2 orchestrator. Small and additive — it does not change Stage 1's path.

---

## 9. Suggested build order

Each step is independently testable, so problems surface early and in isolation:

1. **Checkpoint file-store** — prerequisite; unblocks resume and is testable on its own
   with no GPU.
2. **`page_result_builders/` + `page_window_planner`** — pure / near-pure logic; fast to
   unit-test before any engine exists.
3. **`docling_inprocess_engine`** first — in-process is the simplest to debug; prove one
   simple PDF end-to-end through the orchestrator *with* checkpointing.
4. **`mineru_subprocess_engine`** — subprocess lifecycle, health-check polling, HTTP.
5. **`resilient_conversion_engine`** — wire circuit breaker / retry / timeout; *force* a
   trip to prove Docling fallback and `is_degraded`.
6. **`gpu_engine_resource_coordinator`** — exclusivity + VRAM budget under real load.
7. **Orchestrator `run_stage2`** + a `STAGE_2_GUIDE.md` written in the same plain-English
   style as Stage 1, once the behavior is real and verified.

---

## 10. Open decisions to confirm before coding

These are the choices baked into this plan as *recommended defaults*. Confirm or
adjust them and the plan settles:

1. **Sub-package names** — `conversion_engines` / `windowed_extraction` /
   `page_result_builders`. Good, or tweak?
2. **Table boundary** — Stage 2 *detects* fragments, Stage 4 *merges* (recommended), or
   merge within a window here in Stage 2?
3. **Checkpoint store scope** — treat the empty `checkpointing/` files as part of this
   Stage 2 effort, or as a separate task to schedule first?

---

## 11. Glossary (jargon, explained)

- **Window / windowed extraction** — processing the document in fixed-size batches of
  pages (e.g. 8) instead of all-at-once (memory blow-up) or one-at-a-time (too slow).
- **Strategy pattern** — a family of interchangeable algorithms (here: the two engines)
  behind one common interface, so the caller can swap them without changing its own code.
- **Decorator** — an object that wraps another object of the *same* interface to add
  behavior; here, `resilient_conversion_engine` wraps the real engines to add fallback.
- **Circuit breaker** — after N consecutive failures it "trips" and stops calling the
  failing engine, routing to the fallback instead — like an electrical breaker.
- **Checkpoint / resume** — saving "how far we got" to disk after each window so an
  interrupted run continues from there instead of page 1.
- **In-process vs subprocess** — Docling runs *inside* this Python process; MinerU runs
  as a *separate* program we talk to over HTTP. The split keeps their GPU memory apart.
- **`PageResult`** — the canonical per-page output: markdown (with figure tokens),
  figures, tables, which engine produced it, and whether it was degraded.
- **Figure token** — a short placeholder like `${FIG:<job_id>:<page>:<index>}` written
  in place of a figure now, swapped for a real vision-LLM summary by Stage 4.
- **`is_degraded`** — marks a page that the fallback engine produced after the primary
  tripped, so accuracy impact can be measured.
- **VRAM** — the GPU's onboard memory; the budget check makes sure we don't exceed it.
```
