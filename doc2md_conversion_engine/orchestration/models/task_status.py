#!/usr/bin/env python3
"""
Task Status Enum Module

This module defines the ProcessingStatus enum which represents the possible
states of a document processing task within the orchestration system.

Purpose:
    - Provide standardized status values for task state tracking
    - Enable consistent status reporting across the system
    - Support workflow transitions and decision making
"""

from enum import Enum


class ProcessingStatus(Enum):
    """
    Represents the current status of a document processing task.
    
    These statuses track the lifecycle of a task from creation through
    processing to completion or failure.
    """
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"


