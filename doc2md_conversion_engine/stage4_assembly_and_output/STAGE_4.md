# Stage 4 — Assembly & Output (Implementation Plan)

> **One sentence:** Stage 4 consumes Stage 2's ordered stream of `PageResult`s,
> substitutes every `${FIG:...}` and `${TBL:...}` token in place with the
> resolved Markdown (from Stage 3 and from the page itself), normalises the
> stitched-together text, and streams the final document to disk atomically —
> producing a single `.md` file plus a `ConversionSummary` row of metrics.

This document is the **implementation companion** to the code in
[`doc2md_conversion_engine/stage4_assembly_and_output/`](.). Read it
before opening any file in this directory. It explains what the package
does, how the pieces are arranged, and which decisions are *load-bearing*
(changing them changes correctness, not just performance).

---

## 1. Where Stage 4 sits in the pipeline

```
   STAGE 2                          STAGE 3                          STAGE 4
   page extraction                  figure summarization             assembly & output
   ───────────────                  ────────────────────             ─────────────────
   yields PageResult                token → FigureSummary            consume PageResult stream
   (markdown_with_tokens,      ──▶  (persisted to             ──▶    substitute ${FIG:...}
    figures[], tables[])            .figure_summaries/)              substitute ${TBL:...}
                                                                     clean + flush <job>.md
                                                                     emit ConversionSummary
```

Stage 4 is the **terminal** stage. It is the only stage that writes the
caller-visible artefact (`<job_output_dir>/<job_id>.md`) and the only stage
that reports a `ConversionSummary`. Every upstream invariant collapses into
two physical outputs here:

* `<job_output_dir>/<job_id>.md` — the final assembled Markdown.
* `ConversionSummary` — page counts, figure counters, engines used, duration.

### 1.1 The two-token reading-order contract

> **One sentence:** position is encoded *exclusively* by the literal byte
> offset of the `${FIG:...}` / `${TBL:...}` token inside
> `PageResult.markdown_with_tokens`; Stage 4 does **not** know — and must
> not invent — any other notion of "where the figure / table goes".

`PageResult.markdown_with_tokens` is the **single source of truth** for the
page's reading order. Stage 2 wrote it inline at the figure's / table's
position; Stage 3 never touches it; Stage 4 performs `str.replace` against
it. Three rules fall out of this:

1. **Never reorder text around a token.** No AST round-trip, no
   Markdown re-renderer, no "tidy up the paragraph". `str.replace` only.
2. **Never invent a position.** If a token is missing from
   `markdown_with_tokens`, that is a Stage 2 bug — surface it, do not
   reorder downstream.
3. **Token string equality is sacred.** The string the resolver searches
   for is the same byte-for-byte string Stage 2 wrote and Stage 3 keyed
   on. Any escaping (filenames, log lines) happens *outside* the token
   value.

```
   PageResult.markdown_with_tokens                substituted Markdown
   ───────────────────────────────                ────────────────────
   "## Diagnosis of CKD\n\n                       "## Diagnosis of CKD
    Refer if any of the following...               Refer if any of the following...
    ${FIG:74a76…:140:0}\n                          ### Figure: Decision algorithm
    Figure 12. CKD referral decision               for CKD referral
    algorithm.\n\n                                 - eGFR < 30 mL/min/1.73 m² → …
    Adult patients with diabetes ..."              - ACR ≥ 300 mg/g → …
                                                   …
                                                   Figure 12. CKD referral decision
                                                   algorithm.

                                                   Adult patients with diabetes ..."
```

The figure caption (`Figure 12. …`) is **not** part of the token. It is
ordinary surrounding prose written by Stage 2 *after* the token. Stage 4
preserves it verbatim by construction.

---

## 2. What Stage 4 must actually do

Even though the headline is "substitute tokens", a real production
document — regardless of domain (research paper, slide deck, technical
spec, regulatory text, …) — forces Stage 4 to handle five concerns
simultaneously:

| Concern                                | What goes wrong if Stage 4 ignores it                                            |
|----------------------------------------|----------------------------------------------------------------------------------|
| **Stream order**                       | Pages emitted out-of-order (multi-window engines) → final doc has scrambled pages |
| **Async resolution timing**            | Stage 3 worker hasn't produced a summary yet when a page arrives                  |
| **Cross-page tables**                  | Header on p.41, body continues on p.42 — substituting fragments breaks the table  |
| **Drop decoratives**                   | Pasting "the model says this is a stock photo" into the output → phantom prose    |
| **Atomic on-disk output**              | A mid-write crash leaves a half-written `.md` indistinguishable from a good one   |

Stage 4 separates each concern into its **own collaborator** so unit tests
can replace any of them without touching the others. That decomposition is
the spine of the module layout in §6.

---

## 3. Data flow at runtime

```
 ┌──────────────────────────────────────────────────────────────────────────────┐
 │  PipelineOrchestrator.start_conversion(...) → DocumentConversionStream       │
 │     stream.page_results      ── async generator of PageResult                │
 │     stream.figure_summarization ── FigureSummarizationOrchestrator           │
 └──────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
 ┌──────────────────────────────────────────────────────────────────────────────┐
 │  StreamingDocumentAssembler        ◄── composition root + public surface     │
 │                                                                              │
 │   async def assemble(stream) -> ConversionSummary:                           │
 │       async for page in OrderedPageStreamConsumer(stream.page_results):      │
 │           page_md  = await TokenSubstitutionPipeline.resolve(page)           │
 │           cleaned  = AssembledMarkdownOutputCleaner.clean_page(page_md)      │
 │           await AtomicMarkdownOutputFlusher.append(cleaned)                  │
 │       await AtomicMarkdownOutputFlusher.finalize()                           │
 │       return ConversionSummaryBuilder.build(...)                             │
 └──────────────────────────────────────────────────────────────────────────────┘
                                  │
       ┌──────────────────────────┼──────────────────────────────┐
       ▼                          ▼                              ▼
 ┌──────────────┐    ┌──────────────────────────┐    ┌──────────────────────┐
 │ Ordered      │    │ TokenSubstitution        │    │ AtomicMarkdown       │
 │ PageStream   │    │   Pipeline               │    │   OutputFlusher      │
 │ Consumer     │    │                          │    │                      │
 │              │    │  ┌────────────────────┐  │    │ in-mem buffer        │
 │ reorder by   │    │  │ FigureToken        │  │    │ ≥ flush_threshold    │
 │ page_number, │    │  │   Resolver         │  │    │   → fsync + rename   │
 │ small        │    │  │ (Stage 3 lookup    │  │    │ finalize:            │
 │ priority-    │    │  │  + timeout +       │  │    │   atomic rename of   │
 │ queue        │    │  │  drop decorative + │  │    │   tmp → <job>.md     │
 │              │    │  │  degraded fallback)│  │    │                      │
 │              │    │  └────────────────────┘  │    │                      │
 │              │    │  ┌────────────────────┐  │    │                      │
 │              │    │  │ TableToken         │  │    │                      │
 │              │    │  │   Resolver         │  │    │                      │
 │              │    │  │  + TableFragment   │  │    │                      │
 │              │    │  │    Buffer (multi-  │  │    │                      │
 │              │    │  │    page merge)     │  │    │                      │
 │              │    │  └────────────────────┘  │    │                      │
 │              │    └──────────────────────────┘    │                      │
 └──────────────┘                                    └──────────────────────┘
                                  │
                                  ▼
                ┌─────────────────────────────────────┐
                │  AssembledMarkdownOutputCleaner      │
                │   - collapse triple blank lines      │
                │   - normalise heading levels         │
                │   - strip orphan token leftovers     │
                │     (logged as a hard error)         │
                └─────────────────────────────────────┘
                                  │
                                  ▼
                ┌─────────────────────────────────────┐
                │  ConversionSummaryBuilder            │
                │  output_markdown_path, page count,   │
                │  figures_summarized / _deduplicated  │
                │  / _failed (from Stage 3 counters),  │
                │  engines_used, total_duration_s      │
                └─────────────────────────────────────┘
```

Two things to notice:

* The **only** I/O sink is `AtomicMarkdownOutputFlusher`. Every other
  collaborator returns strings. This keeps the cleaner, the resolvers, and
  the substitution pipeline trivially unit-testable with no temp files.
* The Stage 3 handle (`stream.figure_summarization`) is injected
  **as an abstract interface**, not the concrete orchestrator. Stage 4
  depends on `AbstractFigureSummaryProvider` (one method: `get_summary`),
  not on `FigureSummarizationOrchestrator`. The two stages stay
  swappable.

---

## 4. The token-resolution sub-pipeline

The substitution step is small in code but the most decision-dense part of
the stage. Each token type has its own resolver because their semantics
differ.

### 4.1 Figure tokens (`${FIG:...}`)

```
   for each ${FIG:job:page:idx} match in markdown_with_tokens:

       summary = poll_with_timeout(                                ──┐
            getter   = figure_summary_provider.get_summary(token),   │ resilience layer:
            timeout  = fault_tolerance.timeouts                      │ AsyncOperationTimeoutGuard
                       .figure_token_resolution_seconds,             │ around polling, NOT
            interval = small, e.g. 100 ms,                           │ around resolver as a whole
       )                                                           ──┘

       case summary:
         ── None (timed out) ──▶  substitute  assembly.degraded_mode_placeholder
                                  counters.figures_failed += 1
                                  log AssemblyError(token, "TokenResolutionTimeoutError")

         ── is_informative=False ──▶  drop the token   (replace with empty string,
                                       collapse the now-orphan blank line)
                                       counters.figures_dropped_decorative += 1

         ── informative ──▶  substitute  summary.markdown_result
                              counters.figures_substituted += 1
```

Two load-bearing choices:

1. **Polling, not awaiting.** Stage 3 has its own bounded timeout. Stage 4
   is the *consumer-side* clock: if Stage 3 is wedged, Stage 4 still must
   finish the document. Polling with a wall-clock budget guarantees
   liveness on the assembly side independently of Stage 3's health.
2. **Drop, do not stub, on `is_informative=False`.** Substituting a
   placeholder for a decorative image creates a phantom paragraph in the
   final Markdown. The token *and* its surrounding blank line are
   removed; the caption (if any) is left untouched because it is
   surrounding prose, not part of the token.

### 4.2 Table tokens (`${TBL:...}`) and cross-page merging

Stage 2 emits a `Table` with `is_fragment=True` when a table continues onto
the next page. The Markdown carried by the fragment is *partial* — the
substitution resolver must merge before substituting.

```
   for each page in stream order:
       for each table in page.tables:
           if table.is_fragment:
               TableFragmentBuffer.append_open_fragment(start_page=table.start_page,
                                                       markdown=table.markdown,
                                                       token=table.token)
               # leave the token in place; resolution deferred
               continue

           merged_markdown = TableFragmentBuffer.close_and_merge(
               start_page = table.start_page,
               final_token = table.token,
               final_markdown = table.markdown,
           )

           # substitute the *final* token with merged markdown.
           # earlier-page tokens were marked for deletion at append-time
           # (their text rows are now part of merged_markdown under the
           # final-page token's position).
```

Why anchor the merged result on the **closing-page** token?
Because earlier pages have already been streamed to disk by the time the
closing fragment arrives — anchoring on an earlier page would force the
assembler to buffer every page that contains an open fragment and edit
already-written bytes, breaking the streaming contract. The closing-page
anchor lets each page publish as it arrives: intermediate-page fragment
tokens are erased *on the page they appear* (substituted with the empty
string), and the merged Markdown lands at the closing token's position
on the closing page. Reading-order-wise the table appears "where it
ends" in the source document, which is also where the natural
"continued on page N" caption typically sits.

> **Failure containment:** a never-closed fragment (Stage 2 bug: header
> with no terminating fragment) is detected on stream exhaustion. The
> buffered Markdown is emitted as a footer block (one entry per
> start-page) with a log-warning, and `assembly.degraded_mode_placeholder`
> stands in for any orphan token. The document still completes; the
> rows are never silently lost.

### 4.3 The generic token scanner

Both resolvers share a single low-level utility:
`TokenSubstitutionEngine.replace_all(page_markdown, token_to_resolution)`.
It is purely mechanical (string scan + replace) — no policy. Policy lives
in the resolvers. This keeps the scanner reusable for any future token
type (e.g. `${EQN:...}` for equations) with no policy duplication.

---

## 5. Output writing — atomicity, buffering, resume

### 5.1 `AtomicMarkdownOutputFlusher`

```
              ┌─────────────────────────────────────────────┐
              │  in-memory bytes buffer  (UTF-8)            │
              └─────────────────────────────────────────────┘
                              │
                              │ when len(buffer) >= flush_threshold_bytes
                              ▼
              ┌─────────────────────────────────────────────┐
              │  append to <job_output_dir>/<job_id>.md.tmp │
              │  fsync(file)                                │
              │  clear buffer                               │
              └─────────────────────────────────────────────┘
                              │
                              │ finalize() (after last page)
                              ▼
              ┌─────────────────────────────────────────────┐
              │  flush remaining buffer + fsync             │
              │  os.replace(<tmp>, <job_id>.md)             │
              │  fsync(parent_dir)                          │
              └─────────────────────────────────────────────┘
```

Properties:

* **No partial file is ever published.** The reader-visible `.md` is
  produced by `os.replace` from a fully-fsynced `.tmp`. Either nothing
  exists, or the whole document exists.
* **RAM stays flat.** `flush_threshold_bytes` (default 1 MB, from
  `AssemblyConfig`) bounds the in-memory buffer regardless of document
  length.
* **Crash semantics are clean.** If the pipeline dies before
  `finalize()`, the `.tmp` is left for forensics and the next resume
  starts fresh — there is no "half a document" to reconcile.

### 5.2 Resume coordination

Stage 4 does *not* keep its own checkpoint. Resume correctness is delegated
to the windowed checkpoint store that already exists for Stage 2:

* If the page stream resumes mid-document, the assembler simply restarts
  with a fresh `.tmp`. Re-running Stage 4 from scratch is cheap (string
  ops + already-cached Stage 3 lookups).
* This is a deliberate trade. Adding an assembly checkpoint would create a
  second source of truth about "what has been written" that could drift
  from Stage 2's source-of-truth about "what was produced". One truth.

---

## 6. Module map

```
stage4_assembly_and_output/
├── __init__.py                              # exports StreamingDocumentAssembler + counters only
├── STAGE_4.md                               # this document
│
├── streaming_document_assembler.py          # composition root + public surface
├── ordered_page_stream_consumer.py          # re-orders PageResults by page_number (priority heap)
│
│   ── token resolution (policy lives here) ──
├── token_substitution_pipeline.py           # per-page: figure resolver + table resolver + scanner
├── figure_token_resolver.py                 # ${FIG:...}: poll Stage 3, timeout, drop, degrade
├── table_token_resolver.py                  # ${TBL:...}: merge fragments, substitute
├── table_fragment_buffer.py                 # cross-page open-fragment state
├── token_substitution_engine.py             # pure scanner: (page_md, token→text) → page_md
│
│   ── output (the only I/O sink) ──
├── assembled_markdown_output_cleaner.py     # whitespace, heading normalisation, orphan-token sweep
├── atomic_markdown_output_flusher.py        # buffered append, tmp + fsync + os.replace
└── conversion_summary_builder.py            # PageResult counts + Stage 3 counters → ConversionSummary
```

The `__init__.py` deliberately re-exports only `StreamingDocumentAssembler`
and the assembly-side counters. The concretes
(`AtomicMarkdownOutputFlusher`, `TableFragmentBuffer`, …) remain private —
anyone needing to swap one out should implement the relevant abstract
interface from `contracts/` (see §7) and inject it into the assembler's
constructor.

Module-name discipline (same rules as Stage 3):

* file name `==` the principal class name (snake → CamelCase).
* one file `==` one responsibility. No "utils" buckets.
* nothing imports a concrete from another stage. Cross-stage talk goes
  through `contracts/`.

---

## 7. Contracts (the seams Stage 4 ships with)

All of these live (or will live) under `contracts/` so Stage 4 can be
unit-tested against fakes and so other stages — and future pipelines —
can reuse them.

| Interface (new, in `contracts/assembly_interfaces.py`) | Purpose                                                                                              |
|--------------------------------------------------------|------------------------------------------------------------------------------------------------------|
| `AbstractFigureSummaryProvider`                        | Read-side view of Stage 3. **One method:** `async get_summary(token) -> FigureSummary \| None`.       |
|                                                        | `FigureSummarizationOrchestrator` already satisfies this shape — formalising the interface lets       |
|                                                        | Stage 4 take a mock for tests without importing Stage 3.                                              |
| `AbstractTokenResolver`                                | Common contract for figure / table / future-equation resolvers: `async resolve(page) -> dict[token, str]`. |
| `AbstractAssembledMarkdownCleaner`                     | Pure-string transform `clean_page(markdown) -> markdown`. No I/O.                                     |
| `AbstractMarkdownOutputSink`                           | `append(text)` + `finalize() -> Path`. The flusher's contract — lets a future S3 / object-store sink slot in. |

Existing contracts Stage 4 consumes unchanged:

* `PageResult`, `Figure`, `Table`, `ConversionJob`, `ConversionSummary` —
  `contracts/pipeline_domain_types.py`
* `FigureSummary`, `FigureType`, `RenderingStrategy` —
  `contracts/figure_summarization_types.py`
* `AssemblyConfig`, `FaultToleranceConfig`, `TimeoutsConfig` —
  `contracts/configurations/pipeline_config.py`
* `AssemblyError`, `TokenResolutionTimeoutError` — `contracts/exceptions.py`

Nothing inside `stage4_assembly_and_output` is allowed to leak outside this
directory except through one of the above. That is the test of whether a
new helper belongs here or in `contracts/`.

---

## 8. Configuration map

`settings.yaml` → `contracts/configurations/pipeline_config.py` →
Stage 4 modules:

```
assembly:
  output_flush_threshold_bytes      → AtomicMarkdownOutputFlusher  (RAM cap)
  degraded_mode_placeholder         → FigureTokenResolver / TableTokenResolver
                                       (substituted on timeout / orphan / poison-pill)

fault_tolerance:
  timeouts.figure_token_resolution_seconds  → FigureTokenResolver
                                              (per-token wall-clock budget)
  # the cleaner + flusher have no fault knobs — they are pure transforms.
```

Defaults are deliberately conservative: 1 MB flush buffer, 300 s per-token
budget, a degraded placeholder whose wording makes it unmistakably an
out-of-band pipeline notice rather than authored prose
(`[Figure: processing failed — see original document]`). A human reader,
in any domain, must *never* mistake the placeholder for content from the
source document; that is the only requirement on its wording.

---

## 9. Failure handling — the document always finishes

Stage 4's prime directive: **the assembled `.md` is always produced**, even
when upstream stages partially failed. The only acceptable terminal
states are "complete document" or "no file at all" — never a half-file.

| Failure mode                                  | What Stage 4 does                                                                            |
|-----------------------------------------------|----------------------------------------------------------------------------------------------|
| Page arrives out of order (multi-window)      | `OrderedPageStreamConsumer` buffers ahead pages and emits in `page_number` order              |
| `${FIG:...}` token still unresolved at budget | Substitute `assembly.degraded_mode_placeholder`; increment `figures_failed`; log              |
| `is_informative=False` summary                | Drop the token + its blank line; increment `figures_dropped_decorative`                       |
| Orphan table fragment (no close)              | Emit buffered Markdown at start-page token; degrade later orphan tokens; log warning          |
| Unknown token left in output after substitution | Cleaner sweeps it, replaces with degraded placeholder, raises an `AssemblyError` *as a metric* |
|                                               | (the run completes; the metric tells the operator a Stage 2 token never appeared in Stage 3)  |
| Disk full mid-flush                           | `AtomicMarkdownOutputFlusher` raises; the `.tmp` is left for forensics; no `.md` published    |
| Crash before `finalize()`                     | No `.md` exists. Re-running the job starts the assembler fresh                                |

The counters Stage 4 surfaces feed `ConversionSummary` exactly once and
need no further bookkeeping: `figures_summarized` and `figures_failed`
come from Stage 3 directly; `figures_dropped_decorative` is computed by
Stage 4; `total_pages` is the count of `PageResult`s assembled.

---

## 10. Public surface (one paragraph)

```python
from stage4_assembly_and_output import StreamingDocumentAssembler

assembler = StreamingDocumentAssembler.build(
    assembly_config         = cfg.assembly,
    fault_tolerance_config  = cfg.fault_tolerance,
    figure_summary_provider = stream.figure_summarization,   # AbstractFigureSummaryProvider
    job                     = stream.job,
)

summary: ConversionSummary = await assembler.assemble(stream)
# → wrote <job.output_dir>/<job.job_id>.md atomically
# → summary.output_markdown_path, .total_pages, .figures_*, .total_duration_seconds
```

The `pipeline_orchestrator.PipelineOrchestrator` wires this together: it
constructs the assembler with the running Stage 3 handle, drives
`assemble(stream)`, then calls `stream.finalize()` to close Stage 3 and
copies the figure counters into `ConversionSummary`. Stage 4 itself does
not call `stream.finalize()` — that ordering belongs to the orchestrator.

Everything below this surface is replaceable through the abstract
interfaces in `contracts/`. The `StreamingDocumentAssembler` is the only
place where the concretes are wired together.

---

## 11. Why this shape (vs. simpler alternatives)

A new developer will ask: "why not just `''.join(page.markdown_with_tokens for page in stream)` then `str.replace` per token?" The decomposition pays for itself precisely at the points where the simple version breaks:

* **Multi-window engines emit pages out-of-order** → an unordered join silently scrambles the document. `OrderedPageStreamConsumer` is non-negotiable the moment Stage 2 can produce pages from parallel windows.
* **Stage 3 is asynchronous and best-effort** → a naive `await orchestrator.get_summary(token)` deadlocks if the worker pool drops the figure. The polling + timeout + degraded-placeholder logic *must* live somewhere; isolating it in `FigureTokenResolver` keeps the assembler readable.
* **Tables span pages** → in-line substitution corrupts tables every time. `TableFragmentBuffer` is the only place that knows about cross-page state, which keeps the rest of the pipeline blissfully unaware of it.
* **Atomicity matters for downstream consumers** → a chunker / indexer that watches `<job_id>.md` for new files must never see a half-written file. The `tmp + fsync + os.replace` discipline is the smallest correct implementation of "publish on completion".

Each module exists because deleting it would re-introduce a specific, named bug. That is the test for whether a new file belongs in this directory.

---

## 12. Glossary

* **Token (`${FIG:...}` / `${TBL:...}`)** — the deterministic placeholder
  Stage 2 splices into the page Markdown at a figure's or table's
  reading-order position; Stage 4's substitution key.
* **Degraded placeholder** — `assembly.degraded_mode_placeholder`; the
  visible substitute text Stage 4 writes whenever a token cannot be
  resolved. Never silently drop; always make the gap auditable.
* **Atomic publication** — `tmp + fsync + os.replace`. Either the file
  exists in full, or it does not exist at all.
* **Fragment** — a `Table` with `is_fragment=True`: a table whose Markdown
  is partial because the table continues onto the next page.
* **Orphan token** — a `${FIG:...}` / `${TBL:...}` that remains in the
  Markdown after substitution. Indicates an upstream contract break;
  swept by the cleaner and surfaced as a metric.
* **Polling-with-budget** — Stage 4's pattern for asking Stage 3 for a
  summary without coupling to its internal scheduling: poll
  `get_summary`, time out at the configured wall-clock budget, then
  degrade.
