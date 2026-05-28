# Stage 3 — Figure Summarization (Implementation Notes)

> **One sentence:** Stage 2 leaves a `${FIG:...}` token wherever a figure belongs
> and writes the figure's image to disk; Stage 3 looks at each image with a
> **local vision-language model (Qwen-VL via Ollama)** and produces a faithful,
> insertion-ready Markdown summary, keyed by token so Stage 4 substitutes it
> deterministically.

This document explains what the package actually does, why the pieces are
arranged the way they are, and which architectural decisions are *load-bearing*
(changing them changes correctness, not just performance). It is the
implementation companion to the code in this directory.

---

## 1. Where Stage 3 sits in the pipeline

```
   STAGE 2                          STAGE 3                          STAGE 4
   page extraction                  figure summarization             assembly
   ───────────────                  ────────────────────             ────────
   writes figure PNGs to disk       look at each image with          replace every
   leaves ${FIG:job:pg:idx}   ──▶   Qwen-VL (Ollama, local)    ──▶   ${FIG:...} token
   tokens in the page markdown      → faithful Markdown                with its summary;
        │                                summary keyed by token        drop decoratives
   Figure{token, image_path,        token → FigureSummary
          sha256, page, index}      (persisted under <job>/.figure_summaries/)
```

Stage 3 consumes the `Figure` objects Stage 2 produced (each carrying
`token`, `image_path`, `sha256`, `page_number`, `index_on_page`) and produces,
for each, a `FigureSummary` stored under that figure's **token**. It runs
concurrently with Stage 2 and never blocks the GPU extraction path — figures
are enqueued as pages come out of Stage 2 and summarised by a small worker
pool in the background.

The contract is fixed by:

* `Figure` — `contracts/pipeline_domain_types.py` (Stage 2 output)
* `FigureSummary` — `contracts/figure_summarization_types.py` (Stage 3 output)
* The four abstract interfaces — `contracts/figure_summarization_interfaces.py`

No Stage 3 internal type leaks outside of `contracts/`.

---

## 2. What clinical figures actually look like

A shallow "describe this image" prompt would fail most of them, because
clinical figures fall into clearly different *kinds* and each kind needs a
different rendering strategy:

| Kind (observed)               | Real example                                                       | What a good summary must capture                                                          |
|-------------------------------|--------------------------------------------------------------------|-------------------------------------------------------------------------------------------|
| **Decision algorithm**        | p140 "Diagnosis of CKD": category → criteria → action, with arrows | branching structure, reading order, **every threshold** (eGFR <30, ACR ≥300 mg/g …)       |
| **Statistical plot**          | p104 forest plot: subgroups, point estimates, 95 % CIs, axis labels | each subgroup's value + CI, the axis labels, **direction of effect**                      |
| **Conceptual / framework**    | p148 nested framework, colour-coded to CKD G1-G2 / G3-G4 / G5      | hierarchy / nesting *and* the colour semantics (colour maps to disease stage)             |
| **Decorative image**          | p171 stock photo of a doctor                                       | recognise that it carries **no clinical content** and say so — do **not** invent meaning  |

Three design truths fall straight out of these samples and are visible
throughout the code:

1. **One prompt must adapt to many figure types** → the prompt first
   *classifies*, then extracts in a way appropriate to that type. See
   `figure_summarization_prompt.py`.
2. **Decoration is mixed in with real figures** → the model is *required* to
   say "this is decorative" so Stage 4 can drop the token instead of
   substituting a hallucinated paragraph. Encoded in
   `FigureType.DECORATIVE` + `is_informative=False` cross-field validation
   in `contracts/figure_summarization_types.py`.
3. **Faithfulness beats fluency** → clinical numbers change patient care.
   The prompt forbids guessing and demands `illegible` rather than
   invention; `legibility` / `confidence` ride along on every summary so a
   reviewer can spot low-trust outputs.

---

## 3. Two-pillar prompt design

The prompt is the *heart* of Stage 3. Small wording changes have visible
quality effects. Its construction is isolated in
`figure_summarization_prompt.py` so a prompt engineer can iterate without
touching client, queue, or orchestrator code.

```
   image ──▶  [ THINK: what kind of figure? what are its parts?
                trace the structure, read the numbers, note what's
                unreadable ]                       (Ollama think:true)
                        │
                        ▼
              [ ANSWER: structured JSON matching the figure-summary
                schema — the only thing we keep ]
```

Four ideas, all visible in the prompt text:

1. **Think before answering.** Qwen3-VL's reasoning mode is requested
   (`think: true`); the client discards the reasoning channel and keeps only
   the structured answer.
2. **Classify first, then extract.** The prompt instructs the model to
   choose a `figure_type` and then a `rendering_strategy` appropriate for
   that type. The `ALLOWED_RENDERING_STRATEGIES_BY_FIGURE_TYPE` matrix in
   `contracts/figure_summarization_types.py` validates the pair so the model
   cannot return "forest plot + fenced code block".
3. **Anti-hallucination rules.** Hard rules in the prompt: describe only
   what is visibly present; transcribe numbers and units verbatim; mark
   anything unreadable as `illegible`; never infer clinical recommendations
   not shown.
4. **Structured output.** Ollama is called with `format=<json schema>` so
   schema conformance is enforced *during decoding* — an entire class of
   parsing failures simply cannot occur. The schema lives once in
   `contracts/figure_summarization_types.py` (`FIGURE_SUMMARY_JSON_SCHEMA`)
   and is reused by both the client and the Pydantic contract, so the two
   cannot drift.

---

## 4. Data flow at runtime

```
  Stage 2 yields PageResult ──┐
                              │  for each Figure on the page:
                              │       orchestrator.enqueue_figure(figure)
                              ▼
      ┌──────────────────────────────────────────────────────────────┐
      │  AsyncBoundedFigureQueue       (backpressure: a bounded queue │
      │     so extraction can't outrun summarization, memory stays    │
      │     flat instead of buffering hundreds of pending images)     │
      └─────────────────────────┬────────────────────────────────────┘
                                │  N workers pull
        ┌───────────────────────▼─────────────────────────────────────┐
        │  FigureSummarizationWorkerPool   (bounded async workers)    │
        │                                                             │
        │  per Figure:                                                │
        │    1. summary_store.contains(token)?  ── yes ─▶ resume skip │
        │           │ no                                              │
        │    2. dedup_cache.get(sha256)?       ── hit ─▶ rebind token │
        │           │ miss                            and persist     │
        │    3. limiter.acquire()                                     │
        │       └─ [optional] ExclusiveGPUContextManager              │
        │    4. timeout → breaker → retry → vision_client.summarize() │
        │    5. summary_store.put(summary)                            │
        │    6. dedup_cache.put(sha256, summary)                      │
        │    7. counters.figures_summarized += 1                      │
        │                                                             │
        │  on N failures: write degraded placeholder, count failed    │
        └─────────────────────────────────────────────────────────────┘
                                │
                       token → FigureSummary  (persisted JSON, one file each)
                                │
                                ▼
              Stage 4: orchestrator.get_summary(token) → FigureSummary
                       (or None ⇒ degraded placeholder)
```

`drain_and_close` is the orchestrator's commit point: once Stage 2 has
finished producing, the orchestrator closes the queue (each worker receives
a sentinel and exits), `gather`s the worker tasks, and returns the final
counters straight into `ConversionSummary`.

---

## 5. The two keys, and why both exist

Every figure carries two identifiers, and they do different jobs:

```
   ┌──────────────────────────────────┐         ┌──────────────────────────────────┐
   │  token = ${FIG:job:page:index}   │         │  sha256 = SHA-256 of image bytes │
   │                                  │         │                                  │
   │  POSITION identity               │         │  CONTENT identity                │
   │  Unique per slot in the document │         │  Same image → same hash          │
   │  Drives Stage 4 substitution     │         │  Drives skip-the-model dedup     │
   │  → FigureSummaryStore key        │         │  → FigureDedupCache key          │
   └──────────────────────────────────┘         └──────────────────────────────────┘
                       ▲                                          ▲
                       │                                          │
                       │   five tokens, one image:                │
                       │     ${FIG:job:040:0} ┐                   │
                       │     ${FIG:job:091:0} ┼──── all share ────┘  model runs ONCE
                       │     ${FIG:job:142:0} ┘     sha256=abc…       summary copied
                       │                                              to all 3 tokens
                       └── used by Stage 4 to substitute each token verbatim
```

* The **summary store is keyed by token** — that is what Stage 4 substitutes,
  so this is the load-bearing association. `JsonFigureSummaryStore` persists
  one JSON file per token under `<job_output_dir>/.figure_summaries/`.
* The **dedup cache is keyed by sha256** — so the model is invoked **once**
  per unique image even when that image appears under five different tokens.
  `JsonFigureSha256DeduplicationCache` persists under
  `<job_output_dir>/.figure_cache/`. A cache hit still writes a fresh
  `token → summary` row (with the token rebound) so every position is filled.

Both stores persist atomically (`tmp + replace`) so a crash mid-write cannot
leave a half-written file visible to Stage 4 or to a subsequent resume.

---

## 6. Why a bounded queue + small worker pool (not "fire 100 requests")

Ollama runs **one local model**; for vision + thinking it effectively
serializes heavy requests. The architectural choices fall out of that fact:

* **Concurrency is capped low.**
  `LocalVisionConcurrencyLimiter` is a semaphore (not a RPM limiter — there
  is no API rate limit on localhost). Default cap of 1 in-flight call;
  raise to 2 only on large GPUs / small models. Oversubscribing thrashes
  VRAM and slows everything down.
* **The queue is bounded.** `AsyncBoundedFigureQueue` applies backpressure
  when summarization is slower than extraction (which it usually is, because
  thinking is slow). Stage 2 simply waits on `put`, keeping memory flat.
* **Dedup first.** The cheapest call is the one we don't make. Checking
  `sha256` before talking to the model can materially cut calls on
  diagram-reusing guidelines (~30 % observed in the corpus).

```
   one local Ollama daemon, one GPU, one model in VRAM
            ▲           ▲           ▲
            │           │           │
       worker #1    worker #2    worker #N        ← async workers (small N)
            │           │           │
            └───────────┴───────────┘
                        │
                  LocalVisionConcurrencyLimiter
                  (asyncio.Semaphore, bound=in_flight_limit)
                        │
                  ExclusiveGPUContextManager      ← only when gpu.enabled
                  (process-wide async lock, also
                  used by Stage 2's GPU engine)
                        │
                AsyncOperationTimeoutGuard         ← hard wall-clock ceiling
                        │
                  EngineCircuitBreaker             ← trips on repeated failures
                        │
                  ExponentialBackoffRetry          ← transport-level retries
                        │
                  OllamaVisionFigureClient         ← image → JSON via Ollama
```

The lock-acquisition order is intentional: the **timeout is outermost** so
a stuck call cannot live forever even if a downstream library has a bug;
the breaker is next so it observes timeouts as failures; retry is
innermost-of-resilience so each attempt resets the timeout / breaker check.

---

## 7. Failure handling — no half-answers in a clinical document

| Failure mode                          | What happens                                                          |
|---------------------------------------|-----------------------------------------------------------------------|
| Transient HTTP / socket error         | `ExponentialBackoffRetry` retries with jitter (stamina)               |
| Repeated component-level failure      | `EngineCircuitBreaker` trips, future calls fail fast for the cooldown |
| Wall-clock stuck call                 | `AsyncOperationTimeoutGuard` raises `FigureSummarizationError`        |
| Schema-invalid JSON from the model    | In-client *validation retry* re-prompts with the validation errors    |
| Thinking-mode empties the response    | Client falls back to `think: false` for the remaining retries         |
| Persistently failing figure           | After `figure_retries` attempts: write a **degraded placeholder**     |
|                                       | summary so Stage 4 can complete; raise `FigurePoisonPillError`,       |
|                                       | increment `figures_failed`                                            |
| Model says "decorative / no content"  | `is_informative=False` → Stage 4 drops the token entirely             |
| Model returns `legibility: poor`      | Kept as-is, surfaced in metrics so a reviewer can audit               |

Two retry layers, **on purpose**:

* *Validation retries* live inside the client. They feed the prior error
  back to the model so it can self-correct — pure prompt engineering.
* *Transport retries* live in the orchestrator (`ExponentialBackoffRetry`).
  They handle network / socket failures with exponential backoff.

Conflating the two would either burn cycles retrying network failures with
ever-bigger prompts or fail prompt-engineering retries on slow networks.

The three counters Stage 3 surfaces (`figures_summarized`,
`figures_deduplicated`, `figures_failed`) feed directly into
`ConversionSummary` without further bookkeeping.

---

## 8. Module map

```
stage3_figure_summarization/
├── __init__.py                            # exports orchestrator + counters only
├── figure_summarization_orchestrator.py   # composition root + public surface
├── figure_summarization_worker_pool.py    # per-figure pipeline + resilience stack
├── figure_summarization_prompt.py         # system prompt + JSON schema (single source)
├── ollama_vision_client.py                # AbstractVisionFigureClient impl (local Ollama)
├── async_bounded_figure_queue.py          # AbstractFigureWorkQueue impl (backpressure)
├── local_vision_concurrency_limiter.py    # in-flight semaphore (not RPM)
├── figure_sha256_deduplication_cache.py   # AbstractFigureDedupCache impl (JSON)
├── figure_summary_store.py                # AbstractFigureSummaryStore impl (JSON)
└── STAGE_3.md                             # this document
```

The `__init__.py` deliberately re-exports only the orchestrator and the
counters dataclass. The concretes (`OllamaVisionFigureClient`,
`JsonFigureSummaryStore`, …) stay private — anyone who needs to swap one
out should implement the relevant abstract interface from `contracts/` and
inject it into the orchestrator's constructor, not import the concrete
class name.

---

## 9. Configuration map

`settings.yaml` → `contracts/configurations/pipeline_config.py` →
Stage 3 modules:

```
figure_summarization:
  enabled                        → orchestrator no-op switch
  provider                       → local_ollama (default) | cloud
  worker_pool_size               → number of async workers (small for local)
  max_queue_size                 → backpressure depth
  local_vision_in_flight_limit   → semaphore bound (1–2 for local)
  summary_store_dir              → <job_output_dir>/<this>/  (Stage 4 reads)
  deduplication_cache_dir        → <job_output_dir>/<this>/
  figure_retries                 → poison-pill threshold

  ollama_vision_client:          ← OllamaVisionClientConfig (provider=local_ollama)
    model                        → 'qwen3-vl:4b' or another vision-capable tag
    enable_thinking              → request `think: true`
    fallback_to_no_thinking_on_failure
    image_max_side_pixels        → downscale ceiling
    request_timeout_seconds      → per-call hard ceiling
    temperature / top_p / seed   → determinism (0 / 0.1 / 42)

  vision_llm:                    ← VisionLLMClientConfig (provider=cloud, reserved)
    provider / model / api_base_url / api_key_env_var / streaming
```

`provider=cloud` is reserved (no cloud adapter is built in this revision);
selecting it raises `NotImplementedError` rather than silently degrading,
because clinical workloads must not be re-routed to a different vendor
without explicit configuration.

---

## 10. Public surface (one paragraph)

The Stage 3 orchestrator exposes three async methods:

```python
orch = FigureSummarizationOrchestrator.build(
    figure_summarization_config=cfg.figure_summarization,
    fault_tolerance_config=cfg.fault_tolerance,
    gpu_config=cfg.gpu,
    assembly_config=cfg.assembly,
    job_output_dir=job.output_dir,
    document_domain=DocumentDomain.CLINICAL,
)
orch.start()

# Producer side (called by the pipeline as Stage 2 emits PageResults):
await orch.enqueue_figure(figure)    # backpressure-bounded

# Stage 2 has finished:
counters = await orch.drain_and_close()

# Consumer side (called by Stage 4's token resolver):
summary = await orch.get_summary(token)   # None until ready
```

The `pipeline_orchestrator.PipelineOrchestrator` is responsible for the
producer-side wiring: it builds one Stage 3 orchestrator per job, enqueues
figures from each `PageResult` as Stage 2 yields it, and calls
`drain_and_close` once the page stream ends. Stage 4 receives the same
orchestrator instance and calls `get_summary` while assembling.

Everything below this surface is replaceable through the abstract
interfaces in `contracts/`. The orchestrator is the only place where the
concretes are wired together.

---

## 11. Glossary

* **VLM (vision-language model)** — a model that takes images + text and
  reasons over both. Here: a local Qwen-VL served by Ollama.
* **Thinking / reasoning mode** — the model produces private step-by-step
  reasoning before its answer; only the answer is kept.
* **Token (`${FIG:...}`)** — the placeholder Stage 2 left in the page
  Markdown marking a figure's exact position; the summary store's key.
* **sha256 dedup** — summarising one image once even when it recurs,
  keyed by a hash of its bytes.
* **Backpressure** — when the bounded queue is full, the producer waits,
  keeping memory flat instead of buffering everything.
* **Poison pill** — a figure that fails repeatedly; recorded as failed and
  replaced by a degraded placeholder instead of retried forever.
* **Degraded placeholder** — the substitute text for a figure that could
  not be summarised, so assembly never blocks on it.
