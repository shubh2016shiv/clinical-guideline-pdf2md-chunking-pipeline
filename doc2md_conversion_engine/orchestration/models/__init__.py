#!/usr/bin/env python3
"""
Orchestration Models Package

This package contains data models and enums used throughout the
orchestration system for representing processing tasks and their states.

Exported Classes:
    - ProcessingTask: Represents a single document processing task
    - ProcessingStatus: Enum of possible task states

Usage:
    from doc2md_conversion_engine.orchestration.models import (
        ProcessingTask,
        ProcessingStatus
    )
    
    task = ProcessingTask(pdf_path="/data/doc.pdf", max_retries=3)
    task.status = ProcessingStatus.PROCESSING
"""

from .processing_task import ProcessingTask
from .task_status import ProcessingStatus

__all__ = [
    "ProcessingTask",
    "ProcessingStatus",
]


