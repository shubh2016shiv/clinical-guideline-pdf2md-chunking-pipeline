"""
checkpointing
=============
Crash-safe persistence and resume for the windowed page-extraction loop.

The pipeline saves a small progress record after each completed window so an
interrupted run (power cut, OOM, Ctrl-C) resumes from the last finished window
instead of page 1. See ``CHECKPOINTING_DESIGN.md`` for the system design and the
decision to use a local file store for the current single-process pipeline.

Two collaborators, with a clean split of responsibility:

    WindowedCheckpointFileStore   — WHERE progress is written (atomic file I/O,
                                     integrity on read). Satisfies the
                                     ``AbstractCheckpointStore`` contract.

    CheckpointResumeStateLoader   — WHAT to do at startup: load the checkpoint,
                                     validate it against results actually on disk,
                                     and return a ``ResumePlan`` (fresh vs resume,
                                     and from which page).

Callers import from this package and never reach into the modules directly.
"""

from .checkpoint_resume_state_loader import CheckpointResumeStateLoader, ResumePlan
from .windowed_checkpoint_file_store import WindowedCheckpointFileStore

__all__ = [
    "WindowedCheckpointFileStore",
    "CheckpointResumeStateLoader",
    "ResumePlan",
]
