#!/usr/bin/env python3
"""Structure-aware parent/child chunking engine for Markdown documents."""

from __future__ import annotations
import os
import re
import uuid
import hashlib
from dataclasses import dataclass
from typing import List, Tuple, Dict, Any, Optional

from ..schema.document_chunks import ChunkMetadata, Document
from ..exceptions import ChunkingError
from ..utilities.progress_tracking import ProgressManager

# Optional: tiktoken for accurate token counting
try:
    import tiktoken
    _ENC = tiktoken.get_encoding("cl100k_base")
    def _count_tokens(s: str) -> int:
        return len(_ENC.encode(s))
except Exception:
    def _count_tokens(s: str) -> int:
        # Fast proxy (≈ 4 chars/token)
        return max(1, len(s) // 4)


# ----------------------- parsing primitives -----------------------

_HDR_RE = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<title>.+?)\s*$")
_CODE_FENCE_RE = re.compile(r"^```")
_TABLE_LINE_RE = re.compile(r"^\s*\|")  # simple & robust for GitHub tables
_TABLE_SEP_RE  = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")
_BLOCKQUOTE_RE = re.compile(r"^\s*>\s")  # treats any contiguous blockquotes as atomic


@dataclass
class AtomicBlock:
    """An atomic block of content that should not be split."""
    kind: str              # "paragraph", "list", "table", "code", "blockquote", "other"
    text: str
    start_line: int
    end_line: int


@dataclass
class Section:
    """A section defined by a header."""
    title: str
    level: int
    start_line: int
    content_lines: List[str]
    parent_titles: List[str]  # breadcrumb titles


class StructureAwareChunker:
    """
    Structure-aware parent/child chunking for Markdown:
      - Parents = header sections
      - Children = concatenations of atomic blocks within a section, capped by token budget
      - Atomic blocks: blockquotes (incl. Auto-extracted assets / figure bundles), tables, code fences, lists, paragraphs
    """

    def __init__(
        self,
        child_token_limit: int = 450,
        child_overlap_tokens: int = 40,
        min_chunk_tokens: int = 60,
        progress_manager: Optional[ProgressManager] = None
    ):
        """
        Initialize the chunker.
        
        Args:
            child_token_limit: Maximum tokens per child chunk
            child_overlap_tokens: Token overlap between consecutive chunks
            min_chunk_tokens: Minimum tokens required for a chunk
            progress_manager: Progress manager for chunking operations
        """
        self.child_token_limit = child_token_limit
        self.child_overlap_tokens = child_overlap_tokens
        self.min_chunk_tokens = min_chunk_tokens
        self.progress_manager = progress_manager or ProgressManager()

    # ---------- top-level API ----------

    def chunk_markdown(
        self,
        md_text: str,
        *,
        source_path: Optional[str] = None,
        pdf_stem: Optional[str] = None
    ) -> Tuple[List[Document], List[Document]]:
        """
        Chunk markdown text into parent and child chunks.
        
        Args:
            md_text: Markdown text to chunk
            source_path: Path to the source file
            pdf_stem: PDF filename stem for identification
            
        Returns:
            Tuple of (parent_chunks, child_chunks) with stable parent->child linkage
            Each chunk is a Document object with page_content and metadata
        """
        try:
            # ========================================
            # STEP 1: MARKDOWN TEXT PREPROCESSING
            # ========================================
            # Split markdown text into lines for processing
            lines = md_text.splitlines()  # ← MARKDOWN INPUT: Text split into lines
            
            # Parse markdown structure into sections (headers + content)
            sections = self._split_into_sections(lines)
            
            # Progress bar for sections
            progress_bar = self.progress_manager.create_progress_bar(
                len(sections), "Chunking sections"
            )
            
            # ========================================
            # STEP 2: CHUNK CREATION
            # ========================================
            # Initialize containers for the final output
            parents: List[Document] = []      # ← PARENT CHUNKS container
            children: List[Document] = []     # ← CHILD CHUNKS container

            # Create a source document ID for the entire document (for linking)
            source_doc_id = str(uuid.uuid4())
            
            # Process each section to create parent and child chunks
            for sec in sections:
                parent_id = str(uuid.uuid4())
                
                # ========================================
                # STEP 3: PARENT CHUNK CREATION
                # ========================================
                # Create parent chunk with actual content (full section)
                parent_text = "\n".join(sec.content_lines).strip()
                parent_meta = {
                    "chunk_id": parent_id,
                    "parent_doc_id": source_doc_id,  # Reference to source document
                    "doc_level": "parent",
                    "header": sec.title,
                    "header_level": sec.level,
                    "section_path": self._make_section_path(sec.parent_titles + [sec.title]),
                    "start_line": sec.start_line,
                    "end_line": sec.start_line + len(sec.content_lines) - 1,
                    "source_path": source_path,
                    "pdf_stem": pdf_stem,
                    "chunking_strategy": "structure_aware_md_v1",
                    "token_count": _count_tokens(parent_text)
                }
                # Create Document object with page_content and metadata
                parents.append(Document(page_content=parent_text, metadata=parent_meta))

                # ========================================
                # STEP 4: CHILD CHUNK CREATION
                # ========================================
                # Break section into atomic blocks (paragraphs, lists, tables, etc.)
                blocks = self._atomize_section(sec.content_lines, sec.start_line)
                
                # Pack blocks into child chunks based on token budget
                child_docs = self._pack_blocks_into_children(
                    blocks, parent_id, sec, source_path, pdf_stem, source_doc_id
                )
                children.extend(child_docs)
                
                progress_bar.update(1)

            progress_bar.close()
            
            # ========================================
            # STEP 5: TUPLE OUTPUT CREATION
            # ========================================
            # This is the final output - the tuple that gets returned!
            return parents, children  # ← TUPLE OUTPUT: (parent_chunks, child_chunks)
            
        except Exception as e:
            raise ChunkingError(
                f"Failed to chunk markdown: {e}",
                document_path=source_path,
                original_error=str(e)
            )

    # ---------- sectioning ----------

    def _split_into_sections(self, lines: List[str]) -> List[Section]:
        """
        Split markdown lines into sections based on headers.
        Maintains breadcrumb of ancestor titles.
        """
        sections: List[Section] = []
        stack: List[Tuple[int, str]] = []  # (level, title)
        curr: Optional[Section] = None

        for idx, raw in enumerate(lines):
            m = _HDR_RE.match(raw)
            if m:
                # Flush current section
                if curr:
                    sections.append(curr)
                    
                level = len(m.group("hashes"))
                title = m.group("title").strip()
                
                # Maintain breadcrumb hierarchy
                while stack and stack[-1][0] >= level:
                    stack.pop()
                parent_titles = [t for _, t in stack]
                
                curr = Section(
                    title=title, 
                    level=level, 
                    start_line=idx+1,
                    content_lines=[], 
                    parent_titles=parent_titles
                )
                stack.append((level, title))
            else:
                if curr is None:
                    # Preamble (no header yet) -> treat as H1 "Document"
                    curr = Section(
                        title="Document", 
                        level=1, 
                        start_line=1,
                        content_lines=[], 
                        parent_titles=[]
                    )
                    stack = [(1, "Document")]
                curr.content_lines.append(raw)
                
        if curr:
            sections.append(curr)
            
        return sections

    # ---------- block atomization ----------

    def _atomize_section(self, content_lines: List[str], abs_start_line: int) -> List[AtomicBlock]:
        """
        Turn a section's raw lines into atomic blocks.
        """
        blocks: List[AtomicBlock] = []
        i = 0
        N = len(content_lines)
        in_code = False
        code_start = 0

        def flush(kind: str, buf: List[str], s: int, e: int):
            if not buf:
                return
            text = "\n".join(buf).rstrip()
            if text.strip():
                blocks.append(AtomicBlock(
                    kind=kind, 
                    text=text,
                    start_line=abs_start_line + s,
                    end_line=abs_start_line + e
                ))

        while i < N:
            line = content_lines[i]
            
            # Code fences
            if _CODE_FENCE_RE.match(line):
                if not in_code:
                    in_code = True
                    code_start = i
                    i += 1
                    continue
                else:
                    # Closing fence
                    in_code = False
                    flush("code", content_lines[code_start:i+1], code_start, i)
                    i += 1
                    continue

            if in_code:
                i += 1
                continue

            # Blockquotes (contiguous) — keeps "Auto-extracted assets" & figures atomic
            if _BLOCKQUOTE_RE.match(line):
                j = i + 1
                while j < N and _BLOCKQUOTE_RE.match(content_lines[j]):
                    j += 1
                flush("blockquote", content_lines[i:j], i, j-1)
                i = j
                continue

            # Tables — capture header + sep + data rows
            if _TABLE_LINE_RE.match(line):
                j = i + 1
                seen_sep = False
                if j < N and _TABLE_SEP_RE.match(content_lines[j]):
                    seen_sep = True
                    j += 1
                # Continue while line starts with '|' (keeps ragged tables too)
                while j < N and _TABLE_LINE_RE.match(content_lines[j]):
                    j += 1
                # If it looked like a table (header + sep), or at least 2 rows starting with |
                if seen_sep or (j - i) >= 2:
                    flush("table", content_lines[i:j], i, j-1)
                    i = j
                    continue
                # Fall through (was just a pipey line)

            # Lists — group contiguous list items as one atomic block
            if line.lstrip().startswith(("- ", "* ", "+ ", "1. ")):
                j = i + 1
                while j < N and content_lines[j].strip() and \
                      (content_lines[j].lstrip().startswith(("- ", "* ", "+ ", "1. ")) or
                       content_lines[j].startswith("  ")):
                    j += 1
                flush("list", content_lines[i:j], i, j-1)
                i = j
                continue

            # Blank line: extend paragraphs until blank-blank boundary
            if line.strip() == "":
                i += 1
                continue

            # Paragraph/other: extend until blank or structural start
            j = i + 1
            while j < N and content_lines[j].strip() and \
                  not _BLOCKQUOTE_RE.match(content_lines[j]) and \
                  not _TABLE_LINE_RE.match(content_lines[j]) and \
                  not _CODE_FENCE_RE.match(content_lines[j]) and \
                  not content_lines[j].lstrip().startswith(("- ", "* ", "+ ", "1. ")):
                j += 1
            flush("paragraph", content_lines[i:j], i, j-1)
            i = j

        return blocks

    # ---------- packing into children ----------

    def _pack_blocks_into_children(
        self,
        blocks: List[AtomicBlock],
        parent_id: str,
        sec: Section,
        source_path: Optional[str],
        pdf_stem: Optional[str],
        source_doc_id: str
    ) -> List[Document]:
        """Pack atomic blocks into child chunks based on token budget."""
        children: List[Document] = []
        buf: List[AtomicBlock] = []
        buf_tokens = 0
        chunk_index = 0

        def emit():
            nonlocal buf, buf_tokens, chunk_index, children
            if not buf:
                return
                
            text = "\n\n".join(b.text for b in buf).strip()
            if not text:
                buf, buf_tokens = [], 0
                return
                
            kinds = list({b.kind for b in buf})
            meta = {
                "chunk_id": str(uuid.uuid4()),
                "parent_doc_id": source_doc_id,  # Reference to source document
                "parent_chunk_id": parent_id,    # Reference to parent chunk
                "doc_level": "child",
                "chunk_index": chunk_index,
                "header": sec.title,
                "header_level": sec.level,
                "section_path": self._make_section_path(sec.parent_titles + [sec.title]),
                "block_types": kinds,
                "start_line": buf[0].start_line,
                "end_line": buf[-1].end_line,
                "source_path": source_path,
                "pdf_stem": pdf_stem,
                "chunking_strategy": "structure_aware_md_v1",
                "token_count": buf_tokens
            }
            # Create Document object with page_content and metadata
            children.append(Document(page_content=text, metadata=meta))
            chunk_index += 1
            buf, buf_tokens = [], 0

        for b in blocks:
            t = _count_tokens(b.text)
            
            # If single atomic block is too big, hard-split by sentences to fit budget
            if t > self.child_token_limit:
                # Flush prior buffer
                if buf_tokens >= self.min_chunk_tokens:
                    emit()
                    
                # Split b.text greedily by sentences/paragraphs
                for piece in self._greedy_sentence_split(b.text, self.child_token_limit):
                    piece_tokens = _count_tokens(piece)
                    meta = {
                        "chunk_id": str(uuid.uuid4()),
                        "parent_doc_id": source_doc_id,  # Reference to source document
                        "parent_chunk_id": parent_id,    # Reference to parent chunk
                        "doc_level": "child",
                        "chunk_index": chunk_index,
                        "header": sec.title,
                        "header_level": sec.level,
                        "section_path": self._make_section_path(sec.parent_titles + [sec.title]),
                        "block_types": [b.kind],
                        "start_line": b.start_line,  # coarse (we split inside)
                        "end_line": b.end_line,
                        "source_path": source_path,
                        "pdf_stem": pdf_stem,
                        "chunking_strategy": "structure_aware_md_v1_split_atomic",
                        "token_count": piece_tokens
                    }
                    # Create Document object with page_content and metadata
                    children.append(Document(page_content=piece, metadata=meta))
                    chunk_index += 1
                continue

            # Fits budget — try to add to buffer
            next_tokens = buf_tokens + (2 if buf else 0) + t  # couple tokens for spacing
            if next_tokens <= self.child_token_limit:
                buf.append(b)
                buf_tokens = next_tokens
            else:
                # Emit current, then start new with overlap
                if buf:
                    emit()
                buf.append(b)
                buf_tokens = t

        if buf_tokens >= self.min_chunk_tokens or not children:
            emit()
        elif buf:
            # Tiny tail; append into previous child if present
            if children:
                prev = children[-1]
                # Update metadata to reflect merged content
                prev.metadata["end_line"] = buf[-1].end_line
                prev.metadata["block_types"] = list({*prev.metadata["block_types"], *[b.kind for b in buf]})
                prev.metadata["token_count"] = (prev.metadata["token_count"] or 0) + buf_tokens

        return children

    # ---------- helpers ----------

    @staticmethod
    def _make_section_path(titles: List[str]) -> str:
        """Create a section path from title hierarchy."""
        return " > ".join(titles)

    @staticmethod
    def _greedy_sentence_split(text: str, token_budget: int) -> List[str]:
        """Lightweight sentence-ish split to fit token budget."""
        # Split on sentence boundaries
        parts = re.split(r'(?<=[\.\!\?])\s+(?=[A-Z0-9>])', text)
        out: List[str] = []
        buf: List[str] = []
        buf_tokens = 0
        
        for p in parts:
            t = _count_tokens(p)
            if buf_tokens + t <= token_budget or not buf:
                buf.append(p)
                buf_tokens += t
            else:
                out.append(" ".join(buf).strip())
                buf, buf_tokens = [p], t
                
        if buf:
            out.append(" ".join(buf).strip())
            
        return out
