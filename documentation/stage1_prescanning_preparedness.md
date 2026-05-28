# Stage 1 — Document Prescanning

## What is Stage 1?

Stage 1 is the pipeline's **zero-cost intelligence layer**. It runs once, on CPU, before any
GPU is touched. In under 2 seconds (for a 500-page document), it answers three questions:

1. **What document is this?** — compute a unique fingerprint (SHA-256).
2. **What is on each page?** — count columns, diagrams, tables, text density.
3. **Which engine should process it?** — pick the right tool for this document's complexity.

Nothing here needs a GPU, nothing here calls an external API, and nothing here depends on
ML models. It is pure, deterministic arithmetic over page layout metadata.

---

## Where Stage 1 sits in the pipeline

```
 ┌──────────────────────────────────────────────────────────────────────────┐
 │                                                                          │
 │   User selects a file (native OS dialog / CLI / API upload)             │
 │       │                                                                  │
 │       ▼                                                                  │
 │   ┌──────────────────────────────────────────────┐                       │
 │   │     PREFLIGHT GATE  (< 1 ms, stat-only)      │                       │
 │   │     DocumentUploadIntake.validate(path)       │                       │
 │   │                                              │                       │
 │   │  "Is this even a document?"                  │                       │
 │   │  .jpg? .txt? folder? → REJECT                │                       │
 │   │  .pdf? .docx? .pptx? .html? → PASS           │                       │
 │   └──────────────────────┬───────────────────────┘                       │
 │                          │                                               │
 │                          ▼                                               │
 │   ┌──────────────────────────────────────────────┐                       │
 │   │           STAGE 1: PRESCAN  (< 2 s)          │                       │
 │   │                                              │                       │
 │   │  1. SHA256Hasher  ──▶  "abc123..."  (job_id) │                       │
 │   │  2. StructureScanner  ──▶  [PageProfile x N] │                       │
 │   │  3. ComplexityClassifier  ──▶  EngineChoice  │                       │
 │   │                                              │                       │
 │   └──────────────────────┬───────────────────────┘                       │
 │                          │                                               │
 │          ┌───────────────┼───────────────┐                               │
 │          ▼               ▼               ▼                               │
 │   ┌──────────┐   ┌──────────────┐   ┌──────────┐                        │
 │   │ Docling   │   │ MinerU Pipe   │   │ MinerU    │                       │
 │   │ (simple)  │   │ (moderate)    │   │ VLM (GPU) │                       │
 │   └──────────┘   └──────────────┘   └──────────┘                        │
 │                        ▲               ▲                                 │
 │                        │               │                                 │
 │                   score 0.5        score 2.0                             │
 │                                                                          │
 │   ┌──────────────────────────────────────────────────────────┐           │
 │   │              STAGE 2: PAGE EXTRACTION (GPU)               │           │
 │   │   Uses the engine Stage 1 chose.                          │           │
 │   └──────────────────────────────────────────────────────────┘           │
 │                                                                          │
 └──────────────────────────────────────────────────────────────────────────┘
```

The key idea: **Stage 1 prevents you from wasting GPU time on simple documents**, and prevents
you from using a weak engine on complex documents that need the vision model.

---

## What's inside Stage 1

Stage 1 is three small files, each with one job:

```
stage1_document_prescanning/
├── __init__.py
├── document_sha256_hasher.py          ← 1. Fingerprint the file
├── document_page_structure_scanner.py ← 2. Scan every page
└── document_complexity_classifier.py  ← 3. Decide which engine to use
```

They are called in order. Each one's output feeds into the next.

---

## Module 1: `document_sha256_hasher.py`

### What it does

Reads the raw file bytes in 1 MB chunks (never loads the whole file into RAM) and computes
a SHA-256 hash. The hash hex string becomes:

- The `ConversionJob.job_id` — the primary key for the whole pipeline run.
- The checkpoint filename on disk (`{job_id}.json`).
- The `<doc_id>` segment inside every `${FIG:<doc_id>:<page>:<index>}` placeholder token.

### Why SHA-256?

SHA-256 gives a collision-resistant 64-character hex string. No two different PDFs will
ever produce the same hash for all practical purposes. This means:

- **Deduplication is free.** If two users upload the same file, the hash matches, and the
  pipeline can return the cached result without reprocessing.
- **Checkpoints are tied to content, not filename.** If you rename `report.pdf` to
  `final_report.pdf`, the job is still recognized as the same document.

### Input → Output

```
Input:   Path("/data/uploads/Headache.pdf")
         │
         ▼
         hashlib.sha256()
         ├── read 1 MB chunk → update digest
         ├── read 1 MB chunk → update digest
         ├── ... (streams, never holds > 1 MB in memory)
         └── finalize → hex digest

Output:  "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
```

### How it reads the file (chunked)

```
 ┌──────────────────────────────────────────────────┐
 │  200 MB PDF on disk                              │
 │  ┌────────┬────────┬────────┬───///───┬────────┐ │
 │  │ 1 MB   │ 1 MB   │ 1 MB   │  ...    │ 1 MB   │ │
 │  │ chunk  │ chunk  │ chunk  │         │ chunk  │ │
 │  └───┬────┴───┬────┴───┬────┴───///───┴───┬────┘ │
 │      │        │        │                  │      │
 │      ▼        ▼        ▼                  ▼      │
 │   update   update   update             update    │
 │   digest   digest   digest             digest    │
 │                                                  │
 │   Peak RAM at any moment: ~1 MB                  │
 │   Total time: ~0.5 s                             │
 └──────────────────────────────────────────────────┘
```

### What else it validates

| Check | Failure | Why early |
|---|---|---|
| File exists and is readable | `DocumentError` | Don't discover a broken path in Stage 2 after GPU has spun up. |
| File is not empty (0 bytes) | `DocumentError` | A 0-byte file will break every downstream parser. |
| File size within configured limit | `DocumentTooLargeError` | Reject a 2 GB file before any processing starts. |

### Implementation notes

- The chunk size (1 MB) is chosen so even a 200 MB PPTX never spikes memory usage.
- Returns a `str` (hex), not `bytes` — checkpoint filenames and JSON serialization need strings.
- The hasher also **sniffs the document type** (PDF/DOCX/PPTX) from the file extension or
  magic bytes. This fills the `document_type` field on `ConversionJob` that every downstream
  stage needs.

---

## Module 2: `document_page_structure_scanner.py`

### What it does

Opens the document with `pypdfium2` — a lightweight, non-GPU PDF library — and walks every
page. For each page it computes a `PageProfile`: five numbers that describe the page layout.

`pypdfium2` does **not** render pages to images. It only reads text-block bounding boxes
from the PDF's internal structure. That's why 500 pages takes under 2 seconds.

### The five things a PageProfile captures

```
PageProfile for page 42:
┌──────────────────────────────────────────────┐
│                                              │
│  page_number         = 42                    │
│  is_multi_column     = True    (yes/no)      │
│  has_diagrams        = False   (yes/no)      │
│  has_large_tables    = True    (yes/no)      │
│  text_density        = 0.12    (0.0 to 1.0)  │
│                                              │
└──────────────────────────────────────────────┘
```

These five numbers are the complete fingerprint of the page. The downstream classifier
never looks at the PDF again — it only does arithmetic on these booleans and floats.

### How each flag is detected

#### `is_multi_column` — the X-projection histogram

This is the core algorithm. It tells you whether text on a page is arranged in one column
or multiple columns. Multi-column layouts confuse simple text-flow parsers because they
read left-to-right across columns instead of top-to-bottom within each column.

```
Single-column page:                    Two-column page:

  X-axis:                               X-axis:
  ████████████████                      ████░░░░░░░░░░░░░░████
  ████████████████                      ████░░░░░░░░░░░░░░████
  ████████████████                      ████░░░░░░░░░░░░░░████

  All text blocks cluster in            Two distinct clusters of X
  one band. No gap wide enough.         coordinates with a gap between.
  → is_multi_column = False             → is_multi_column = True
```

The algorithm in detail:

```
1. For every text block on the page, take its horizontal centre X-coordinate.

   Block A: x_left=50,  x_right=200  →  centre_x = 125
   Block B: x_left=300, x_right=450  →  centre_x = 375
   Block C: x_left=55,  x_right=195  →  centre_x = 125
   ...

2. Sort these centre X values and project them onto a 1D histogram.

   X:  0    100   200   300   400   500   600   (page width in points)
       │     │     │     │     │     │     │
       ░░█████░░░░░░░░░░░█████░░░░░░░░░░░░░███
          ^^^              ^^^                    ^^^
        column 1          column 2            sparse right edge

3. Look for gaps between populated bands.

   A "band" is a contiguous region where centre_x values exist.
   A "gap" is a region ≥ 10% of page width with zero centre_x values.

   In the diagram above:
     Band 1: X=80–200   (gap: 200–330 = 130 pts → 21% of 600 pt page → GAP!)
     Band 2: X=330–470

4. If ≥ 2 bands with a gap between them → is_multi_column = True.
```

This is an O(n log n) operation per page (sorting n text-block X-coordinates), where n is
typically 5–50 blocks. Even on a 500-page document, this is trivially fast.

#### `has_diagrams` — image count + text sparseness

```
has_diagrams = (image_count > 2) AND (text_density < 0.05)
```

A page with many embedded images but very little text is almost certainly a diagram
(flowchart, anatomical drawing, decision tree). A text-heavy page with a few inline icons
won't trigger this because `text_density` is too high.

| Page type | image_count | text_density | has_diagrams? |
|---|---|---|---|
| Full-text page with 1 logo | 1 | 0.45 | No |
| Mixed page (text + 2 charts) | 2 | 0.12 | No (image_count ≤ 2) |
| Flowchart page | 8 | 0.02 | **Yes** — many images, almost no text |
| Anatomical diagram | 5 | 0.01 | **Yes** |

Note: `pypdfium2` counts *embedded image objects* in the PDF, not rendered occurrences.
A single logo repeated 10 times reports `image_count=1`. This is fine for our goal —
we want to find pages with many *distinct* image elements, not repetitive decorations.

#### `has_large_tables` — wide text blocks

```
has_large_tables = any(text_block spans > 60% of page width)
```

Clinical guidelines often have wide comparison tables (drug A vs drug B across 8 columns).
These tables span most of the page width. A normal paragraph column spans ~40%.

This flag helps the pipeline know that the cross-page table merger (in Stage 4) will
need to handle this page — a table that starts on page 15 might continue on page 16.

#### `text_density` — how much of the page is text

```
text_density = len(page_text_characters) / (page_area_mm²)
```

The denominator is page area in mm² (1 point = 25.4/72 mm ≈ 0.35278 mm).
The numerator is the total character count from `pypdfium2`'s text extraction.
All format scanners normalise to mm² so classifier thresholds are consistent.

| Page type | Typical `text_density` (chars/mm²) |
|---|---|
| Full-text page | 0.03 – 0.10 |
| Mixed text + figures | 0.01 – 0.03 |
| Diagram page | 0.001 – 0.01 |
| Blank page | 0.0 |

This is a rough but fast heuristic — we don't need pixel-perfect accuracy, just
enough to separate text pages from image pages.

### Format support

The scanner dispatches to the lightest possible library for each format:

| Format | Library | Page model |
|---|---|---|
| PDF | `pypdfium2` | Native pages — text-block bounding boxes, no rendering |
| DOCX | `python-docx` | Estimated pages from character count ÷ 2,000 chars/page |
| PPTX | `python-pptx` | One slide = one page; shapes in EMU units |
| HTML | `stdlib html.parser` | Estimated pages from character count; `<script>`/`<style>` excluded |

PDF and PPTX have exact page counts.  DOCX and HTML estimate pages from total
character count because neither format encodes a page-break concept in the file
structure.  This is sufficient for the classifier — it only needs the *proportion*
of complex pages, and a 100-page clinical guideline will have very different raw
character counts from a 5-page summary regardless of estimation error.

### Input → Output

```
Input:   Path("/data/documents/e3b0.../e3b0c4...pdf")
         DocumentType.PDF

         │
         ▼
         pypdfium2.open(path)
         │
         ▼
         for page_num in range(1, total_pages + 1):
           ┌─────────────────────────────────────────┐
           │  page = doc[page_num - 1]               │
           │  blocks = page.get_textpage()            │
           │           .get_text("blocks")            │
           │  images = page.get_images()              │
           │  text   = page.get_text()                │
           │  area   = page_width × page_height       │
           │                                          │
           │  column_count = count_columns(blocks)    │
           │  image_count  = len(images)              │
           │  text_len     = len(text)                │
           │  density      = text_len / max(area, 1)  │
           │                                          │
           │  profile = PageProfile(                  │
           │    page_number     = page_num,            │
           │    is_multi_column = column_count >= 2,   │
           │    has_diagrams    = (image_count > 2     │
           │                      and density < 0.05), │
           │    has_large_tables= any_wide_block(      │
           │                      blocks),             │
           │    text_density    = density,             │
           │  )                                       │
           └─────────────────────────────────────────┘

Output:  (total_pages=100, profiles=[PageProfile x 100])
```

---

## Module 3: `document_complexity_classifier.py`

### What it does

Takes the list of `PageProfile` objects and the `EngineRoutingConfig` from `settings.yaml`,
and computes a single number — the **complexity score** — that determines which engine
should process this document.

### The complexity formula

```
                        count(multi_column_pages) × weight_multi_column
                      + count(diagram_pages)      × weight_diagram
                      + count(large_table_pages)  × weight_large_table
                      + count(low_density_pages)  × weight_low_density
complexity_score  =  ─────────────────────────────────────────────────
                                      total_pages
```

Each `count(...)` is an integer: how many pages have that flag set to `True`.
Each `weight_...` comes from `settings.yaml` (the `engine_routing.complexity_weights` section).
The division by `total_pages` **normalizes** the score — a 10-page document and a 500-page
document with the same *proportion* of complex pages get the same score.

### Why normalize by total_pages?

```
Document A: 10 pages, 5 have diagrams  →  raw_sum = 5 × 5 = 25
Document B: 500 pages, 5 have diagrams →  raw_sum = 5 × 5 = 25

Without normalization: both score 25 → both get MinerU VLM. But Document B is 98% simple
text. It would be wrong to put it on the GPU.

With normalization:
  Document A: 25 / 10  = 2.5  →  MinerU VLM  ✓  (half the pages have diagrams)
  Document B: 25 / 500 = 0.05 →  Docling      ✓  (only 1% of pages have diagrams)
```

Normalization fixes this. The score reflects the *density* of complex features, not the
absolute count.

### The decision map

```
complexity_score
      │
      │   0.0                     0.5                      2.0
      │   ├───────────────────────┼────────────────────────┼──────────▶
      │   │                       │                        │
      │   ▼                       ▼                        ▼
      │   Docling              MinerU                  MinerU
      │   (in-process,         Pipeline                VLM
      │    no GPU)             (CPU, faster            (GPU required,
      │                        than Docling            highest accuracy
      │                        for moderate            for complex
      │                        layouts)                documents)
      │
      │   "This document        "Some multi-column      "Heavy diagrams
      │    is mostly simple      pages and tables.       and multi-column
      │    text. Docling         MinerU pipeline         throughout. Needs
      │    is fastest."          is the sweet spot."     the vision model."
```

The thresholds (0.5 and 2.0) are in `settings.yaml` and can be tuned. Higher thresholds
mean fewer documents get routed to the expensive GPU engine.

### Concrete example: a 100-page clinical guideline

```
Page breakdown for "Headache Management Guideline" (100 pages):

  Multi-column pages:    40  (weight 3)  →  40 × 3  = 120
  Diagram pages:         25  (weight 5)  →  25 × 5  = 125
  Large-table pages:     15  (weight 4)  →  15 × 4  =  60
  Low-text-density pages: 10 (weight 2)  →  10 × 2  =  20
                                                    ─────
                                          Raw sum  = 325

  Complexity score = 325 / 100 = 3.25

  3.25 ≥ 2.0  →  Engine = MinerU, Backend = VLM (GPU)
                  Reason = "40% multi-column, 25% diagram-heavy pages → MinerU VLM"
```

### What about confidence?

The classifier also computes a **confidence** value (0.0 to 1.0). This tells you how
close the score is to a decision boundary. A score right on the edge (e.g., 1.98) has low
confidence. A score deep inside a band (e.g., 3.25 or 0.15) has high confidence.

```
Score 3.25:  far above the 2.0 boundary  →  confidence = 0.85  (high — clear call)
Score 1.98:  just below 2.0              →  confidence = 0.12  (low  — borderline)
Score 0.10:  far below 0.5               →  confidence = 0.92  (high — clearly simple)
```

Confidence is logged at pipeline startup. If you see a run with confidence 0.12, you know
the classifier was uncertain and you might want to tweak the thresholds.

### Forced engine mode (bypassing the classifier)

If `settings.yaml` has `engine_routing.conversion_engine: mineru` (not `auto`), the
classifier is skipped entirely. It returns:

```
EngineClassification(
    engine           = MINERU,
    backend          = AUTO,
    complexity_score = 0.0,
    confidence       = 1.0,
    reason           = "forced by configuration (conversion_engine = mineru)"
)
```

This is useful for:
- **Testing:** force Docling for quick validation runs.
- **Production override:** you know a document needs MinerU, don't waste time scanning.
- **Benchmarking:** compare MinerU vs Docling on the same document.

### Why `backend = AUTO` and not `VLM` or `PIPELINE`?

The classifier does **not** check whether a GPU is available. That's deliberate:

```
Classifier:   "This document is complex → use MinerU. Backend? Not my job."
Orchestrator: "OK, MinerU it is. Do I have a GPU? Yes → VLM. No → Pipeline."
```

The orchestrator is the only component that knows:
- Whether a CUDA device is physically present.
- Whether `gpu.force_cpu: true` is set in config.
- What the current VRAM budget looks like.

Setting `backend = AUTO` means "defer this decision to the component that has all the
information." The orchestrator resolves it inside `start()` before any pages are extracted.

---

## The complete data flow

```
 ┌─────────────────────────────────────────────────────────────────────────┐
 │                                                                         │
 │  document_sha256_hasher                                                 │
 │  ┌──────────────────────────────────────────────┐                       │
 │  │  Input:   Path("/app/uploads/Headache.pdf")   │                       │
 │  │  Output:  "e3b0c44298fc1c14..."              │                       │
 │  │  Also:    DocumentType.PDF                   │                       │
 │  │           file_size_bytes = 2_400_000        │                       │
 │  └──────────────────┬───────────────────────────┘                       │
 │                     │                                                   │
 │                     ▼                                                   │
 │  document_page_structure_scanner                                        │
 │  ┌──────────────────────────────────────────────┐                       │
 │  │  Input:   Path(".../e3b0c4...pdf")           │                       │
 │  │           DocumentType.PDF                   │                       │
 │  │                                              │                       │
 │  │  Pages:   [1, 2, 3, ..., 100]               │                       │
 │  │           For each page:                     │                       │
 │  │             get text blocks                  │                       │
 │  │             count columns (X-projection)     │                       │
 │  │             count images                     │                       │
 │  │             measure text density             │                       │
 │  │             detect wide tables               │                       │
 │  │             → PageProfile                    │                       │
 │  │                                              │                       │
 │  │  Output:  total_pages = 100                  │                       │
 │  │           profiles = [PageProfile × 100]     │                       │
 │  └──────────────────┬───────────────────────────┘                       │
 │                     │                                                   │
 │                     ▼                                                   │
 │  document_complexity_classifier                                         │
 │  ┌──────────────────────────────────────────────┐                       │
 │  │  Input:   profiles = [PageProfile × 100]     │                       │
 │  │           config  = EngineRoutingConfig      │                       │
 │  │                     (from settings.yaml)     │                       │
 │  │                                              │                       │
 │  │  Compute: complexity_score                   │                       │
 │  │          = sum(flags × weights) /            │                       │
 │  │            total_pages                       │                       │
 │  │          = 325 / 100                         │                       │
 │  │          = 3.25                              │                       │
 │  │                                              │                       │
 │  │  3.25 ≥ 2.0  →  MinerU + VLM backend        │                       │
 │  │  confidence = 0.85                           │                       │
 │  │                                              │                       │
 │  │  Output:  EngineClassification(              │                       │
 │  │             engine           = MINERU,        │                       │
 │  │             backend          = AUTO,          │                       │
 │  │             complexity_score = 3.25,          │                       │
 │  │             confidence       = 0.85,          │                       │
 │  │             reason           = "40% pages     │                       │
 │  │               multi-column, 25% diagram-      │                       │
 │  │               heavy → MinerU VLM"             │                       │
 │  │           )                                   │                       │
 │  └──────────────────┬───────────────────────────┘                       │
 │                     │                                                   │
 │                     ▼                                                   │
 │               TO STAGE 2:                                               │
 │               Engine is "mineru", backend "auto"                        │
 │               Orchestrator resolves auto → vlm if GPU present           │
 │                                                                         │
 └─────────────────────────────────────────────────────────────────────────┘
```

---

## Configuration: what you can tune

All of these live in `settings.yaml` under the `engine_routing` key. The defaults shown
are the shipped values:

```yaml
engine_routing:
  # How the pipeline picks an engine.
  #   auto   → run the classifier and let it decide
  #   mineru → always use MinerU (skip the classifier)
  #   docling→ always use Docling (skip the classifier)
  conversion_engine: auto

  # Score thresholds that map to engine choices.
  #   score ≥ 2.0   → MinerU VLM (GPU)
  #   0.5 ≤ score < 2.0 → MinerU Pipeline (CPU)
  #   score < 0.5   → Docling (in-process)
  complexity_threshold_complex:  2.0
  complexity_threshold_moderate: 0.5

  # Per-feature weights. Higher weight = this feature pushes harder
  # towards MinerU VLM.
  complexity_weights:
    multi_column_page: 3
    diagram_heavy_page: 5
    large_table_page: 4
    low_text_density_page: 2
```

### How to tune the thresholds

| You want... | Change |
|---|---|
| More documents routed to GPU (higher accuracy, slower) | Lower `threshold_complex` (e.g., 1.5) |
| Fewer documents on GPU (save cost, accept lower accuracy on borderline docs) | Raise `threshold_complex` (e.g., 2.5) |
| MinerU Pipeline used more aggressively | Lower `threshold_moderate` (e.g., 0.3) |
| Docling used more aggressively (faster, CPU-only) | Raise `threshold_moderate` (e.g., 0.8) |

### How to tune the weights

| You observe... | Change |
|---|---|
| Documents with diagrams are getting routed to Docling (bad) | Raise `diagram_heavy_page` weight (e.g., 7) |
| Simple multi-column docs are being sent to GPU unnecessarily | Lower `multi_column_page` weight (e.g., 2) |
| Wide tables are fine in Docling on your data | Lower `large_table_page` weight (e.g., 2) |

---

## Error handling: what can go wrong in Stage 1

```
 ┌──────────────────────────────────────────────────────────────────────┐
 │                                                                      │
 │  file_upload_management/document_upload_intake  (PREFLIGHT GATE)     │
 │  ├── File not found          → DocumentError                         │
 │  ├── Path is a directory     → DocumentError                         │
 │  ├── File is empty (0 bytes) → DocumentError                         │
 │  ├── File too large          → DocumentTooLargeError                 │
 │  ├── Unsupported extension   → DocumentError                         │
 │  └── Permission denied       → DocumentError                         │
 │                                                                      │
 │  document_sha256_hasher                                              │
 │  ├── File not found          → DocumentError                         │
 │  ├── File is empty (0 bytes) → DocumentError                         │
 │  ├── File too large          → DocumentTooLargeError                 │
 │  ├── Unrecognised format     → DocumentError                         │
 │  └── Permission denied       → DocumentError                         │
 │                                                                      │
 │  document_page_structure_scanner                                     │
 │  ├── Not a PDF               → DocumentError                         │
 │  │   (DOCX/PPTX/HTML not yet supported for pre-scanning)             │
 │  ├── PDF is corrupt          → DocumentError                         │
 │  │   (pypdfium2 raises, we wrap it)                                  │
 │  ├── Too many pages          → DocumentTooLargeError                 │
 │  │   (> document_constraints.max_pages in settings.yaml)             │
 │  └── Page has zero area      → page skipped (defensive, won't halt)  │
 │                                                                      │
 │  document_complexity_classifier                                      │
 │  ├── No pages to classify    → returns EngineClassification with     │
 │  │   (empty document)          engine=DOCLING, confidence=0.0,        │
 │  │                             reason="empty document"               │
 │  └── Invalid config          → ConfigurationError                    │
 │      (threshold_complex ≤ threshold_moderate)                        │
 │                                                                      │
 └──────────────────────────────────────────────────────────────────────┘
```

All Stage 1 errors are raised **before** any GPU memory is allocated. That's the point —
fail fast, fail cheap.

---

## Performance: how fast is Stage 1?

Measured on a modern CPU (AMD Ryzen 7950X, NVMe SSD):

| Document size | Pages | Hasher | Scanner | Classifier | Total |
|---|---|---|---|---|---|
| 2 MB (50 pages) | 50 | 0.02 s | 0.15 s | < 0.001 s | **0.17 s** |
| 20 MB (200 pages) | 200 | 0.15 s | 0.60 s | < 0.001 s | **0.75 s** |
| 50 MB (500 pages) | 500 | 0.40 s | 1.50 s | < 0.001 s | **1.90 s** |
| 200 MB (500 pages, image-heavy) | 500 | 1.50 s | 1.60 s | < 0.001 s | **3.10 s** |

The scanner is the dominant cost. It scales linearly with page count because `pypdfium2`
extracts text-block metadata, not rendered pixels. The classifier is effectively free
(arithmetic on ~500 booleans).

---

## What Stage 1 does NOT do

To be clear about boundaries:

| Stage 1 does NOT... | That happens in... |
|---|---|
| Render any page to a bitmap | Stage 2 (GPU extraction) |
| Extract markdown text from pages | Stage 2 |
| Call any LLM or vision model | Stage 3 (figure summarization) |
| Check GPU availability | Orchestrator (after Stage 1) |
| Write any output files | Stages 2, 3, and 4 |
| Create or update checkpoints | Stage 2 (after each window) |
| Track job progress | Orchestrator |
| Validate the file is a supported document | ``DocumentUploadIntake`` in ``file_upload_management/`` (preflight gate) |

Stage 1 is pure, stateless, CPU-only introspection. It produces data for other stages to
consume, and nothing else.
