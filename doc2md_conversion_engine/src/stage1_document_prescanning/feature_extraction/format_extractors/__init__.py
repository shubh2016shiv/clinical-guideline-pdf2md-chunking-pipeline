"""
format_extractors
=================
The per-format readers that do the actual looking-inside-the-document work.

Each module here handles exactly one file format and knows nothing about the
others. They all expose the same single function shape so the dispatcher in
``document_feature_extractor.py`` can call any of them the same way:

    extract_<format>_features(path, config) -> DocumentFeatureProfile

Keeping one reader per file makes the "where do I fix PDF behaviour?" question
trivial to answer, and lets a new format be added by dropping in one more module
without touching the existing four.

    pdf_feature_extractor.py    PDFs — text layers, table geometry, multi-column
                                detection, embedded images and vector drawings.
    docx_feature_extractor.py   Word documents — read from the underlying XML
                                (columns, merged cells, text boxes).
    pptx_feature_extractor.py   PowerPoint — slides as units, table grids, shapes.
    html_feature_extractor.py   HTML — table row/column spans, nested tables.
"""

from .docx_feature_extractor import extract_docx_features
from .html_feature_extractor import extract_html_features
from .pdf_feature_extractor import extract_pdf_features
from .pptx_feature_extractor import extract_pptx_features

__all__ = [
    "extract_pdf_features",
    "extract_docx_features",
    "extract_pptx_features",
    "extract_html_features",
]
