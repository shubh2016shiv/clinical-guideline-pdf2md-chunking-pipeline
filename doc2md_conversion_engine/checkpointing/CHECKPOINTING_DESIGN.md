# Checkpointing & Resume — System Design

> **One sentence:** If a long conversion is interrupted (power cut, OOM, Ctrl-C,
> crash), checkpointing lets the pipeline resume from the last finished window
> instead of restarting from page 1.

> **Status:** Design + decision document. The two files in this package
> (`windowed_checkpoint_file_store.py`, `checkpoint_resume_state_loader.py`) are
> empty placeholders. This document decides *how* checkpointing should work before
> any code is written, and answers the specific question raised: **"should we use
> Redis, and how do we do it reliably?"**
>
> **Decision (settled):** **Single-process execution, local atomic file store.**
> Redis is deferred to a documented upgrade path (§8) and adopted only if the
> deployment ever becomes distributed. Rationale recorded in §7.

---

## 1. The single most important fact

Before debating Redis vs. files, understand what a checkpoint actually *is* here.

**The checkpoint is a tiny pointer. The real data is already on disk.**

When Stage 2 finishes a window, it writes that window's extracted page Markdown and
figure PNGs straight to the job's `output_dir` on the local filesystem. Those files
are the heavy, valuable output. The **`CheckpointState`** is just a few kilobytes of
JSON that *describes* them:

```
   output_dir/                                  ← the REAL data (megabytes)
   ├── window_000/  page_001.md … page_008.md, fig_*.png
   ├── window_001/  page_009.md … page_016.md, fig_*.png
   ├── window_002/  …
   └── .checkpoints/
         └── <job_id>.json   ← the CHECKPOINT (kilobytes): "windows 0–2 done,
                                engine=mineru, 0 failures, last_page=24"
```

`CheckpointState` (already defined in
`contracts/windowed_checkpoint_store_interface.py`) holds:

- `job_id` — which document this is (the SHA-256 hash — see §6)
- `last_completed_page` — how far we got
- `completed_windows[]` — each `WindowRecord` points at a `result_dir` **on disk**
- `engine_snapshot` — which engine + the circuit-breaker failure count (so resume
  doesn't reset fault-tolerance state — this is the link to `circuit_breaker.py`)
- `header_tree_snapshot` — heading hierarchy, so Stage 4 keeps cross-window structure

This one fact — *the checkpoint is metadata pointing at local files* — drives the
entire reliability analysis below.

---

## 2. The reliability question, stated precisely

The failure we are protecting against is **the process dying.** So the only question
that matters is: *after the process dies and restarts, can we trust the checkpoint
and does it agree with the data on disk?*

There are two independent properties a checkpoint store must have:

1. **Durability** — does the checkpoint survive the crash at all?
2. **Consistency with the data it describes** — after the crash, does the checkpoint
   point only at window results that actually finished writing to disk?

Property #2 is the subtle one, and it is where the Redis-vs-file decision is really
made.

---

## 3. Why co-location beats Redis *for a single-node pipeline*

### File store: checkpoint lives next to the data it describes

```
        ┌─────────────── ONE filesystem ───────────────┐
        │                                                │
        │   window_002/page_*.md   ── fsync ──▶ on disk  │   (1) flush the data
        │                                                │
        │   .checkpoints/<job>.json ── atomic ──▶ on disk│   (2) THEN flush the pointer
        │        (write temp, fsync, rename)             │
        └────────────────────────────────────────────────┘

   Because both live on the same filesystem, we control the ORDER:
   data first, pointer second.  After any crash the checkpoint can
   never reference a window whose data didn't finish writing.
```

The checkpoint and the files it points at are in **one storage system**, so a single
ordering discipline (flush data → then atomically write checkpoint) guarantees they
never disagree. The classic `write-temp → fsync → rename` makes the checkpoint write
atomic: a `kill -9` mid-write leaves the *previous* checkpoint fully intact, never a
half-written one. No server, no network, no new dependency.

### Redis store: the one fact is split across two systems

```
   ┌── local filesystem ──┐         ┌──── Redis (separate process / host) ────┐
   │  window_002/page_*.md │   ✗     │  checkpoint:<job> = {last_page: 24 …}    │
   └───────────────────────┘  no     └──────────────────────────────────────────┘
                              transaction
                              between them

   After a crash these two can DISAGREE:
   • Redis says "window 2 done" but the page files didn't fsync → resume trusts a
     window whose data is missing.
   • Or Redis lost the last write (see §4) → we redo work we actually finished.
```

The valuable data is on the **filesystem**; the pointer would be in **Redis**. There
is no transaction spanning a filesystem write and a Redis write, so a crash between
them leaves the two inconsistent. You can mitigate this (validate on resume — §5), but
you are now adding machinery to fix a problem the file store doesn't have.

---

## 4. Redis is in-memory: its durability is opt-in and bounded

This is the part most people miss. Redis keeps data **in RAM**. Persistence to disk is
a configuration choice, and each option has a different data-loss window:

| Redis persistence mode | Data-loss window on crash | Cost |
|---|---|---|
| **RDB** (default) — periodic snapshots | **minutes** of writes can vanish | cheap |
| **AOF, `appendfsync everysec`** | ~**1 second** of writes | moderate |
| **AOF, `appendfsync always`** | ~zero | an fsync on **every** checkpoint write |
| no persistence | **everything** on restart | — |

So "use Redis for reliable checkpointing" is only true if you **explicitly enable
AOF** — otherwise a crash (exactly the event we're protecting against) can lose the
checkpoints you wrote in the last few minutes.

**Two more Redis footguns for this use case:**

- **Eviction.** If Redis runs with `maxmemory` + an eviction policy like
  `allkeys-lru`, your checkpoint key can be **silently evicted** under memory pressure.
  A checkpoint store on Redis must run with `noeviction` (or guarantee checkpoints are
  never eligible for eviction). Easy to get wrong.
- **Availability on the hot path.** A checkpoint is written after *every* window. If
  Redis is unreachable at that moment, the write fails — now you must decide whether to
  fail the window or silently degrade. The file store has no such liveness dependency.

---

## 5. Resume validation — required for *either* backend

Regardless of backend, **never blindly trust `last_completed_page` on resume.** The
loader (`checkpoint_resume_state_loader.py`) reconciles the checkpoint against reality
on disk and keeps only the **longest leading run of windows that are actually there**:

```
   load checkpoint(job_id)
        │
        ▼
   for each completed_window (oldest → newest):
        is its result_dir present on disk AND non-empty?
            yes → keep it, continue
            no  → STOP. discard this window and every window after it.
        │
        ▼
   resume from the end of the last VERIFIED window
   (a contiguous page range — never with a hole in the middle)
```

We stop at the *first* gap rather than skipping it: resume must continue from an
unbroken range of completed pages, so a missing window 5 invalidates 5-onward even if
window 6's folder happens to exist. The loader returns a single explicit `ResumePlan`
(reconciled state · resume-or-fresh · resume-from page · how many windows were
discarded).

**Presence, not per-page completeness.** The loader checks that each window's result
folder *exists and is non-empty* — not that every page file is present. It cannot do
the latter without hard-coding Stage 2's page-file naming (coupling it to Stage 2's
internals), and it does not need to: the orchestrator writes a window's data first and
the checkpoint *after*, so any window recorded in a loaded checkpoint had its pages
fully written before the record existed. Presence-on-disk is therefore the right and
sufficient check.

This single step reconciles the "pointer" with the "data" and makes the **file store
effectively bulletproof** — and it is the *mandatory* practice that makes a Redis store
safe despite §3 and §4. (The loader also discards a checkpoint whose stored `job_id`
does not match the document being processed, and recovers from
`CheckpointCorruptedError` by deleting the bad file and starting fresh — both
implemented.)

---

## 6. Job ID and document identity (your point #3)

**Good news: this is already designed and you don't need to invent anything.**

Stage 1's `DocumentSHA256Hasher` computes a **SHA-256 hash of the document's raw
bytes**, and that becomes `ConversionJob.job_id`. It is *content-addressed*: the id is
derived from the file's contents, not assigned randomly. This one id already serves
every purpose:

```
   SHA-256(document bytes)
        │
        ├──▶ ConversionJob.job_id          (the document's identity)
        ├──▶ checkpoint key  <job_id>.json / "checkpoint:<job_id>"   (resume lookup)
        ├──▶ figure-token segment  ${FIG:<job_id>:<page>:<index>}    (Stage 3/4)
        └──▶ deduplication cache key        (skip re-processing identical uploads)
```

**Why content-addressing is exactly right for resume:** re-running the *same* file
produces the *same* `job_id`, which finds the *same* checkpoint — so resume "just
works", and a renamed file does not look like a new job. A random UUID would break
this: every restart would mint a new id and never find its own checkpoint.

**Do you also need a separate `run_id` / `attempt_id`?** For *resume*, no — you *want*
re-runs to collide on the same key so they find prior progress. Add a separate
`run_id` only if you later need to *audit distinct attempts* (telemetry: "this document
was attempted 3 times"). Even then, keep `job_id` as the checkpoint key; let `run_id`
live in logs/metrics, not in the resume path.

---

## 7. Decision: single-process, local atomic file store

**This is decided, not merely recommended.** Stage 2 runs as a **single process,
one document at a time, on one GPU**, and checkpoints to a **local atomic file store**.
Redis is deferred (see §8 for the design to use *if* that ever changes).

### The execution model, stated precisely

> **One document at a time, one process, one GPU — with async overlap *inside* a
> document allowed. No multi-worker, no shared cross-process state.**

"Single-process" rules out multiple *workers/documents* sharing state — it does **not**
forbid concurrency *within* one document. The async windowed orchestrator may still
overlap GPU compute with CPU/I-O (while the GPU extracts window N, the CPU writes
window N−1's markdown, hashes figures, and checkpoints), and bounded intra-document
window concurrency (`max_concurrent_windows`) remains available. Those are pipelining
wins that cost none of the fault isolation below.

### Why single-process (the rationale, recorded)

1. **Fault isolation / blast radius — the decisive reason.** Sequentially, exactly one
   document is in flight at any instant, so a crash leaves *at most one* partially
   processed file, and resume is trivially "redo that one." Running N documents in
   parallel would, on a crash, leave up to N files half-done at once, with their
   partial states and shared GPU/circuit-breaker state entangled — far harder to
   resume reliably. Each document stays an **independent, isolated unit of work**.
2. **One GPU makes parallelism pointless or harmful.** GPU access is already
   serialized (`ExclusiveGPUContextManager`), so parallel workers would serialize on
   the GPU lock anyway while each holding model weights in VRAM — 2× VRAM pressure
   (may not even fit) plus model-reload thrash, for **zero throughput gain** and often
   a net slowdown.
3. **Reliability now, scalability later.** Correctness matters more than throughput for
   a clinical pipeline, and there is no current load that needs horizontal scaling.

### Why the file store follows directly

- The checkpoint **describes local files**, so co-locating it on the same filesystem
  gives crash-consistency for free (§3) and avoids Redis's in-memory durability
  caveats (§4).
- It adds **zero new infrastructure** — no server to run, keep alive, secure, or
  configure for AOF/eviction.
- **This is not a one-way door.** Because everything goes through
  `AbstractCheckpointStore`, swapping in a `RedisCheckpointStore` later changes **zero
  lines of Stage 2 code.** Starting simple does not lock us in.

### When to actually reach for Redis

Adopt the Redis backend when the deployment shape changes to any of these:

- **Multiple worker processes / machines** converting many documents in parallel and
  needing a *shared* view of which jobs are in progress.
- **A central dashboard or scheduler** that must query job progress without
  filesystem access to each worker.
- **A job queue** (Redis Streams / a broker) dispatching documents to a worker pool.

At that point the *results* still live on shared/object storage, and Redis becomes the
**fast shared index** of progress — which is its real strength.

---

## 8. If/when you choose Redis: the reliable design

Here is how to do it correctly, so it's ready when needed.

### 8.1 Data model — one key per job, whole-object value

`CheckpointState` is saved and loaded as a *whole object* (the interface is
`save(state)` / `load(job_id)`), which maps perfectly onto a single Redis string key:

```
   KEY:    checkpoint:<job_id>
   VALUE:  CheckpointState serialized as JSON  (the same pydantic .model_dump_json())

   save(state)   →  SET   checkpoint:<job_id>  <json>        (atomic: one command)
   load(job_id)  →  GET   checkpoint:<job_id>
   delete(id)    →  DEL   checkpoint:<job_id>                (idempotent)
   exists(id)    →  EXISTS checkpoint:<job_id>
```

A single `SET` is atomic, so you get the "no half-written checkpoint" property for
free — no `MULTI`/Lua needed. (Avoid splitting the state into a Redis hash + list:
that buys granularity you don't use and *loses* the atomic whole-object write.)

### 8.2 Mandatory server configuration

```
   appendonly yes                 # enable AOF — without this a crash loses recent writes
   appendfsync everysec           # ~1s loss window (or `always` for zero-loss, slower)
   maxmemory-policy noeviction     # NEVER evict checkpoints under memory pressure
```

### 8.3 TTL for self-cleanup (optional)

Set a TTL on the key (`SET … EX <seconds>`) so abandoned jobs expire instead of
accumulating — e.g. 7 days. A *completed* job still calls `delete()` explicitly; TTL
only catches jobs that were never finished or cleaned up.

### 8.4 Failure handling on the hot path

```
   save() during window loop:
       try   SET checkpoint:<job> …
       fail (Redis down / timeout):
           • log + metric, AND
           • fall back to writing the local file checkpoint  ← belt & suspenders
           (never let a checkpoint-store outage kill an in-flight conversion)
```

### 8.5 The hybrid pattern (best of both, if you need the dashboard)

```
   ┌─────────────── DUAL-WRITE on save() ───────────────┐
   │                                                     │
   │   1. write local file   (SOURCE OF TRUTH,           │
   │      co-located with the window data)               │
   │   2. mirror to Redis    (fast SHARED INDEX for a     │
   │      dashboard / scheduler to read)                 │
   │                                                     │
   │   on load(): prefer the local file; use Redis only   │
   │   for cross-process visibility, never as the only    │
   │   copy.                                              │
   └──────────────────────────────────────────────────────┘
```

This keeps crash-consistency (file is authoritative, validated per §5) while giving
other processes a central place to *read* progress. Cost: every save writes twice.
Only adopt it when something actually needs to read progress remotely.

---

## 9. Decision matrix

| Factor | Local file store | Redis store |
|---|---|---|
| Fits today's single-process pipeline | ✅ ideal | ⚠️ overkill |
| New infrastructure to run | none | Redis server + AOF + monitoring |
| Crash durability | ✅ inherent (fsync) | ⚠️ only with AOF enabled |
| Consistency with on-disk results | ✅ co-located, ordered | ⚠️ split system; needs §5 validation |
| Liveness dependency on hot path | none | Redis must be up at every window |
| Shared state across workers/machines | ❌ no | ✅ yes — its real strength |
| Central progress dashboard | ❌ awkward | ✅ natural |
| Swappable later (interface) | ✅ yes | ✅ yes — same interface |

---

## 10. Build status

Both files are **implemented** against the existing `AbstractCheckpointStore` —
nothing in Stage 2 needs to know which backend is active.

```
checkpointing/
├── windowed_checkpoint_file_store.py   ✅ AbstractCheckpointStore via atomic
│                                         #   write-temp → fsync → rename; integrity +
│                                         #   schema-version check on read;
│                                         #   one <job_id>.json under output_dir/.checkpoints
├── checkpoint_resume_state_loader.py   ✅ loads + VALIDATES against on-disk window
│                                         #   results (§5); returns a ResumePlan;
│                                         #   recovers from corruption / job-id mismatch
└── (future) redis_checkpoint_store.py   ⏸ same interface; added only when the
                                          #   deployment goes distributed (§7, §8)
```

Verified end-to-end: fresh start, atomic save, disk-validated resume (discards a
claimed-but-missing window and resumes from the right page), full resume,
corruption recovery, and idempotent delete. Still **to wire**: the Stage 2
orchestrator must call `save()` after each window and `resolve_resume_plan()` at
startup. `redis_checkpoint_store.py` stays deferred until a distributed need is real.

> Cross-reference: this is the "checkpointing prerequisite" called out in
> `stage2_page_extraction/STAGE_2_PLAN.md` §8, and open decision #3 there.

---

## 11. Glossary

- **Checkpoint** — a small saved record of "how far we got", written after each window
  so an interrupted run can resume.
- **Content-addressed id** — an identifier derived from the data's bytes (here SHA-256),
  so identical input always yields the same id. Enables resume and dedup.
- **Atomic write (temp + rename)** — write to a temporary file, flush it, then rename
  over the target. Rename is atomic on POSIX filesystems, so a reader never sees a
  half-written file.
- **fsync** — force the OS to flush file data from cache to physical disk; without it,
  "written" data can still be lost in a crash.
- **AOF (Append-Only File)** — Redis's durable persistence mode that logs every write;
  required for Redis to survive a crash without losing recent data.
- **`appendfsync`** — how often Redis flushes its AOF to disk: `always` (every write,
  safest/slowest), `everysec` (~1s loss window), `no` (OS decides, riskiest).
- **Eviction** — Redis discarding keys when it hits its memory limit; must be disabled
  (`noeviction`) for checkpoints.
- **Idempotent** — safe to call more than once with the same effect (e.g. deleting a
  checkpoint that's already gone must not error).
- **Source of truth** — the one authoritative copy of data; other copies are caches or
  indexes that can be rebuilt from it.
```
