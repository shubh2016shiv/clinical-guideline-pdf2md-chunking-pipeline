# Stage 1 — Document Prescanning

> **One sentence:** Before we spend any real effort converting a document, Stage 1
> takes a quick, cheap look at it and makes one smart decision — *which conversion
> engine should handle this file*.

This guide is meant to be read top to bottom by any developer who has never seen
this code before. By the end you should be able to picture, in your head, exactly
what happens to a document when it enters Stage 1 and why. No deep knowledge of
the codebase is assumed.

---

## 1. The idea in plain terms

Imagine you run a print shop. Someone drops a stack of documents on your counter.
Before you send each one to a machine, you glance at it: *Is this a clean typed
page, or a messy scanned photocopy? Is it a simple one-column letter, or a
two-column journal article with complicated tables?* That five-second glance tells
you which machine will do the best job.

Stage 1 is that glance. It does **not** convert anything. It does not try to
understand the medical meaning of the document. It just gathers a handful of cheap,
factual clues about the document's *structure* and uses them to route the document
to the right converter in Stage 2.

We have two converters available downstream:

- **Docling** — the cheap, fast default. Great at documents that already carry
  their structure inside them (Word files with real headings, HTML with real tags,
  PDFs with a genuine text layer).
- **MinerU** — the heavier, slower, more powerful engine. Needed only when a
  document is structurally *hard*: multiple columns, complicated tables, or no real
  text at all (a scan).

The entire job of Stage 1 is to pick between these two — **leaning toward Docling**
and only upgrading to MinerU when there is hard proof the document needs it.

### The big picture

```
                         ┌──────────────────────────────────────────┐
   A document file        │                STAGE 1                    │
   (PDF / DOCX /          │           Document Prescanning            │
    PPTX / HTML)          │                                          │
        │                 │   "Look before you leap" — fast, local,   │
        │                 │    no AI model, no network calls.         │
        ▼                 │                                          │
   ┌─────────┐            │   ┌──────────┐  ┌──────────┐  ┌────────┐ │
   │  file   │───────────▶│   │ Step 1   │─▶│ Step 2   │─▶│ Step 3 │ │
   │ on disk │            │   │ Identity │  │ Features │  │ Routing│ │
   └─────────┘            │   └──────────┘  └──────────┘  └────────┘ │
                          │     "what?"      "what's       "which    │
                          │                  inside?"      engine?"  │
                          └──────────────────────────┬───────────────┘
                                                     │
                                          One decision: Docling OR MinerU
                                                     │
                                                     ▼
                          ┌──────────────────────────────────────────┐
                          │   STAGE 2 — actually convert to Markdown  │
                          │   using the engine Stage 1 chose.         │
                          └──────────────────────────────────────────┘
```

Three small steps, run in order, each feeding the next. They map one-to-one onto
the three sub-folders in this package:

| Step | Folder | Question it answers |
|------|--------|---------------------|
| 1 | `document_identity/` | *What document is this?* |
| 2 | `feature_extraction/` | *What is actually inside it?* |
| 3 | `engine_routing/` | *Which engine should process it?* |

---

## 2. Why no AI model? (the deterministic promise)

You might expect us to show the document to a vision model and ask "is this
complex?" We deliberately do **not**. Every decision in Stage 1 is computed from
plain structural facts we read directly out of the file. This buys us three things
that matter a lot in a clinical pipeline:

- **Same input, same output, every time.** The same document always routes to the
  same engine. There is no randomness and no model drift.
- **A reason you can read.** Every decision comes with a plain-English explanation
  naming the exact clue that triggered it ("two-column layout detected", "tables
  with merged cells", and so on).
- **Privacy.** No document content is ever sent over the network to an inference
  service. Everything happens locally, in-process.

A key principle that follows from this: **"no evidence of a problem" counts as a
vote *for* Docling, never as uncertainty.** We never drift to the expensive engine
just because we are unsure — we drift only when we have proof.

---

## 3. Step 1 — Document Identity (`document_identity/`)

> **Question:** What document is this, and can we even handle it?

This is the very first thing that happens. Before we look inside the document or
decide anything, we give it a stable name and confirm we can process it. Three
things happen here, in order:

**It validates the file.** Does it exist? Is it a real file (not a folder)? Can we
read it? Is it non-empty? Is it within the configured size limit? If any of these
fail, we stop immediately with a clear error — there is no point reading a file we
cannot process.

**It detects the document type.** It first looks at the file extension (`.pdf`,
`.docx`, etc.) because that is cheap and almost always correct. If the extension is
missing or misleading, it falls back to reading the first few bytes of the file —
the *magic bytes* — which are a short, distinctive signature that reveals the true
format. (For example, every PDF file starts with the characters `%PDF`.)

**It computes a SHA-256 fingerprint.** It streams the file through a hashing
function in 1-megabyte chunks, producing a 64-character fingerprint of its exact
contents. Streaming in chunks means we never hold more than ~1 MB in memory at once,
even for a 200 MB PowerPoint.

### Why fingerprint the file?

That fingerprint becomes the document's **`job_id`** — the primary key for the
entire pipeline run. Because the fingerprint is computed from the file's *contents*,
two uploads of the exact same file produce the exact same `job_id`. This gives us:

- **Caching:** if we've already processed this file, we can return the saved result
  instead of redoing the work.
- **Stable names on disk:** checkpoints, figure tokens, and cache lookups all key
  off this one id.
- **Rename-proof identity:** renaming the file on disk does not create a "new" job,
  because the contents (and therefore the fingerprint) are unchanged.

---

## 4. Step 2 — Feature Extraction (`feature_extraction/`)

> **Question:** What is actually inside this document?

This step opens the document and reads cheap, factual structural clues out of it.
It is the most code-heavy step, but the idea is simple: **gather facts, not
opinions.**

A crucial design rule lives here: the things we measure record *facts*, never
*judgements*. A measurement says "this table has 8 columns" — it never says "this
document is hard." Deciding what's hard is Step 3's job. Keeping the two separate
means the facts can be trusted and reused, and the routing logic stays in one place.

### One front door, four readers

Every format is read by a different specialist, because a PDF, a Word file, a
PowerPoint, and an HTML page are completely different on the inside. But callers
don't need to know that. They call **one** class — `DocumentFeatureExtractor` —
which looks at the document type, picks the matching reader, runs it, and hands back
a single, uniform result. Adding a new format later means writing one reader and
adding one line to a lookup table.

```
                       DocumentFeatureExtractor.extract(file, type)
                                       │
              picks the reader that matches the document type
                                       │
         ┌──────────────┬──────────────┼──────────────┬──────────────┐
         ▼              ▼              ▼              ▼              ▼
    ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐
    │   PDF   │    │  DOCX   │    │  PPTX   │    │  HTML   │
    │ reader  │    │ reader  │    │ reader  │    │ reader  │
    └────┬────┘    └────┬────┘    └────┬────┘    └────┬────┘
         └──────────────┴──────────────┴──────────────┘
                                │
                                ▼
              one uniform result: DocumentFeatureProfile
              (text · tables · layout · visuals · needs)
```

### The four kinds of evidence we collect

Whatever the format, every reader fills in the same four "boxes" of evidence:

- **Text evidence** — *Is there real, selectable text, or just pictures of text?*
  The single most important field here is whether **native text** exists. A normal
  PDF has a real text layer we can read directly; a scanned PDF is just photographs
  of pages and would need OCR (optical character recognition — turning pictures of
  text back into actual text) to recover anything.

- **Table evidence** — *How many tables, and how complicated are they?* We count
  tables, but more importantly we look at their *structure*: how many columns the
  widest one has, and whether any have **merged cells** (one cell spanning several
  rows or columns) or **nested tables** (a table inside another table's cell). A
  simple grid is easy; merged and nested geometry is exactly what trips up a naive
  parser.

- **Layout evidence** — *How is the text arranged on the page?* The big question is
  **how many columns**. Text that flows in a single column is easy to read in order.
  Text in two columns (like a journal article) is a *reading-order* problem: a naive
  reader marches straight across the page and scrambles the two columns together.

- **Visual evidence** — *How many non-text things are there?* Embedded images,
  vector drawings, charts. Importantly, **a document full of pictures is not, by
  itself, harder to convert** — it just has more for a *later* stage to describe.
  These counts deliberately do not affect engine choice.

### Turning evidence into "needs"

Raw numbers like "135 tables" or "column_count = 2" are awkward to make decisions
from. So at the end of Step 2 a small translator
(`document_requirements_resolver`) converts the raw evidence into plain yes/no
**needs** — for example, *does this document need its reading order rebuilt?
yes/no*. This is still not the engine choice; it just makes the document's needs
explicit so Step 3 can act on them cleanly.

Only **three** of these needs can push a document toward the heavier engine, and
each one describes structure a simple reader would get wrong:

| Need | Plain meaning |
|------|---------------|
| `needs_reading_order_reconstruction` | Text isn't in one simple column (multi-column or floating text boxes). |
| `needs_complex_table_reconstruction` | Tables are merged, nested, or very wide. |
| `needs_ocr_text_recovery` | There's no real text layer — it's a scan. |

Other needs (like "this figure should get a written summary later") are recorded
too, but they deliberately **do not** affect routing — that's a job for a later
stage, not a reason to pick a heavier engine now.

---

## 5. Step 3 — Engine Routing (`engine_routing/`)

> **Question:** Which engine should convert this document — Docling or MinerU?

This is the final thing Stage 1 does. Everything before it gathered facts; this step
turns those facts into a single answer, plus a plain-English reason and a confidence
number for the logs.

The rule, stated simply: **Docling is the default. A document stays with Docling
unless we can prove it has structure Docling would get wrong.** We switch to MinerU
only when one of the three "hard" needs from Step 2 is present.

### The decision: four questions, asked in order

The router asks four questions and stops at the first one that answers. The order
matters — each question is more specific than the one below it.

```
   ┌─────────────────────────────────────────────────────────────────┐
   │  Q1.  Did an operator FORCE an engine in settings.yaml?           │
   │       (a human override, e.g. for testing)                        │
   │                                                                   │
   │       YES ──▶ use it  (but first check that engine can even       │
   │               open this format — else stop with a clear error)    │
   │       NO  ──▶ ▼                                                    │
   ├─────────────────────────────────────────────────────────────────┤
   │  Q2.  Does only ONE engine support this file format at all?       │
   │       (e.g. MinerU cannot read HTML)                              │
   │                                                                   │
   │       YES ──▶ use that one — there is nothing to decide           │
   │       NO  ──▶ ▼                                                    │
   ├─────────────────────────────────────────────────────────────────┤
   │  Q3.  Is there HARD structural evidence the document is hard?     │
   │       • multi-column / floating text  (reading order)            │
   │       • merged / nested / very wide tables  (grid)               │
   │       • no real text layer  (a scan → needs OCR)                 │
   │                                                                   │
   │       YES ──▶ promote to MinerU, and name the exact reason        │
   │       NO  ──▶ ▼                                                    │
   ├─────────────────────────────────────────────────────────────────┤
   │  Q4.  Otherwise…                                                  │
   │       ──▶ confirm DOCLING.  Nothing demands a heavier engine.     │
   └─────────────────────────────────────────────────────────────────┘
```

### The confidence number

Every decision carries a confidence value, purely for the logs. It is **not** a
probability — a rule-based system computes no probability. It is a fixed ranking
that reflects how directly the decision follows from evidence:

| Confidence | When | Why it ranks here |
|-----------:|------|-------------------|
| **1.00** | A human forced the engine | Certain — the operator dictated it. |
| **0.98** | Only one engine supports the format | A hard fact — there was no real choice. |
| **0.90** | Promoted to MinerU on structural evidence | A concrete positive signal fired. |
| **0.85** | Docling default | The fallback — an *absence* of evidence, so it must rank just below a positive detection. |

The ordering is the point: a Docling default (an absence of any problem signal)
must never read as *more* reliable than a hard structural promotion.

---

## 6. The whole journey, end to end

Putting all three steps together, here is the complete path of one document through
Stage 1:

```
   file on disk
        │
        ▼
 ┌─────────────────────── STEP 1: IDENTITY ───────────────────────┐
 │  validate (exists? readable? non-empty? within size limit?)    │
 │  detect type  (extension → magic bytes fallback)               │
 │  hash         (stream in 1 MB chunks → SHA-256 → job_id)       │
 └───────────────────────────────┬────────────────────────────────┘
                                  │  (document_type, job_id)
                                  ▼
 ┌─────────────────────── STEP 2: FEATURES ───────────────────────┐
 │  pick the matching reader  (PDF / DOCX / PPTX / HTML)           │
 │  read evidence:                                                │
 │      • text     → native text? OR a scan?                      │
 │      • tables   → how many? merged/nested? how wide?           │
 │      • layout   → one column or two? floating text boxes?      │
 │      • visuals  → images / charts / drawings (counts only)     │
 │  enforce page-count limit (first point page count is known)    │
 │  translate evidence → plain yes/no NEEDS                       │
 └───────────────────────────────┬────────────────────────────────┘
                                  │  DocumentFeatureProfile
                                  ▼
 ┌─────────────────────── STEP 3: ROUTING ────────────────────────┐
 │  Q1 forced override?      → use it (validate format first)     │
 │  Q2 only one engine fits? → use it                             │
 │  Q3 hard structure?       → MinerU  (+ reason)                 │
 │  Q4 otherwise             → Docling (the default)              │
 └───────────────────────────────┬────────────────────────────────┘
                                  │
                                  ▼
              EngineClassification { engine, confidence, reason }
                                  │
                                  ▼
                      handed to STAGE 2 for conversion
```

---

## 7. How each format gives up its secrets (quick reference)

Each reader works differently because each format stores things differently. You
don't need this to understand the flow, but it's handy when you dive into a specific
reader.

- **PDF** (via PyMuPDF) — the richest reader. It walks the document one page at a
  time, reading the real text layer, detecting table-shaped regions, counting
  embedded images and vector drawings. **Multi-column detection** is clever and
  worth knowing: rather than trusting any single page, it looks at where text blocks
  *start* across all readable pages, and only calls the document "multi-column" if a
  meaningful *fraction* of pages show two columns — so one stray two-column appendix
  page can't flip the whole document's routing.

- **DOCX** (Word) — a `.docx` is secretly a ZIP archive full of XML files. The text
  lives in `word/document.xml`; images are separate files connected by a manifest.
  Word stores **no page numbers** (pages are computed by the renderer at display
  time), so page count is *estimated* from character count.

- **PPTX** (PowerPoint) — also a ZIP of XML, one file per slide. Each slide is a flat
  list of *shapes* (text boxes, images, charts, tables, drawn lines). Shape sizes are
  in EMUs (English Metric Units, where 914,400 EMUs = 1 inch); we convert them to a
  fraction of slide area so comparisons work regardless of 16:9 vs 4:3 slides.

- **HTML** — read with an *event-driven* parser: instead of loading the whole page
  into a tree, the parser reads through the markup and calls a method each time it
  meets a tag (`handle_starttag`), a closing tag (`handle_endtag`), or text
  (`handle_data`). Our scanner listens to those callouts and tallies `<img>`,
  `<table>`, `<svg>`, `<figure>`, and caption elements.

---

## 8. Glossary (jargon, explained)

- **Routing / engine routing** — choosing which downstream converter (Docling or
  MinerU) will process the document.
- **Deterministic** — given the same input, always produces the same output. No
  randomness, no model guesses.
- **SHA-256 / hash / fingerprint** — a function that turns a file's exact bytes into
  a fixed 64-character string. Same bytes → same string; one byte changed → a
  completely different string.
- **`job_id`** — the document's fingerprint, used as the unique key for the whole
  pipeline run.
- **Magic bytes** — the first few bytes of a file, which act as a signature of its
  true format (e.g. a PDF begins with `%PDF`). Used when the extension is missing or
  wrong.
- **Native text** — real, selectable, machine-readable text inside a document, as
  opposed to a picture of text.
- **OCR** (Optical Character Recognition) — turning pictures of text (like a scan)
  back into actual machine-readable text.
- **Reading order** — the sequence in which text should be read. Multi-column pages
  make this non-obvious; a naive reader scrambles the columns together.
- **Merged cells** — one table cell that spans several rows or columns.
- **Nested table** — a table placed inside a cell of another table.
- **Floating text box** — a text box that sits anywhere on the page rather than in
  the normal top-to-bottom text flow; it breaks linear reading order.
- **Confidence** — a fixed number attached to a routing decision for the logs,
  reflecting *how directly* the decision followed from evidence. Not a probability.
- **Docling** — the cheap, fast default conversion engine.
- **MinerU** — the heavier, layout-aware conversion engine, used only when the
  document is provably hard.

---

## 9. What happens after Stage 1

Stage 1 hands Stage 2 a single decision: the chosen engine, a confidence value, and
a human-readable reason. **Stage 2 (page extraction)** then does the real work —
converting the document to Markdown, page by page, using exactly the engine Stage 1
selected. Stage 1 never converts anything itself; its whole value is making that one
decision well, cheaply, and explainably.
