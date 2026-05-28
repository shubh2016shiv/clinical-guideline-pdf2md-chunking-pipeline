"""
stage4_assembly_and_output/
===========================
Stage 4 — final Markdown assembly and atomic on-disk publication.

Public surface
--------------
Only the orchestrator-equivalent entry point is exported:

* :class:`StreamingDocumentAssembler` — consume the Stage 2 page stream,
  resolve every ``${FIG:...}`` and ``${TBL:...}`` token, clean the
  Markdown, and publish the final ``<job_id>.md`` atomically.

Anyone needing to swap out an internal collaborator (cleaner, flusher,
resolver) should implement the relevant abstract interface from
``contracts.assembly_interfaces`` and inject it into the assembler's
constructor rather than importing one of the concretes below.
"""

from .streaming_document_assembler import StreamingDocumentAssembler

__all__ = ["StreamingDocumentAssembler"]
