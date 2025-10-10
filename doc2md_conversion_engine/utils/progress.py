#!/usr/bin/env python3
"""Progress management utilities for the guideline processor module."""

from typing import Optional, Any
from abc import ABC, abstractmethod

# Try to import tqdm, fallback to null implementation if not available
try:
    from tqdm.auto import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False


class ProgressBar(ABC):
    """Abstract base class for progress bars."""
    
    @abstractmethod
    def update(self, n: int = 1) -> None:
        """Update progress by n steps."""
        pass
    
    @abstractmethod
    def close(self) -> None:
        """Close the progress bar."""
        pass
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()


class NullProgressBar(ProgressBar):
    """No-op progress bar implementation."""
    
    def __init__(self, total: Optional[int] = None, desc: Optional[str] = None, 
                 leave: bool = False) -> None:
        """Initialize null progress bar."""
        pass
    
    def update(self, n: int = 1) -> None:
        """No-op update."""
        pass
    
    def close(self) -> None:
        """No-op close."""
        pass


class TqdmProgressBar(ProgressBar):
    """TQDM-based progress bar implementation."""
    
    def __init__(self, total: Optional[int] = None, desc: Optional[str] = None, 
                 leave: bool = False) -> None:
        """Initialize TQDM progress bar."""
        if not TQDM_AVAILABLE:
            raise RuntimeError("tqdm is not available")
        
        self._pbar = tqdm(total=total, desc=desc, leave=leave)
    
    def update(self, n: int = 1) -> None:
        """Update progress by n steps."""
        self._pbar.update(n)
    
    def close(self) -> None:
        """Close the progress bar."""
        self._pbar.close()


class ProgressManager:
    """Manager for progress bars with fallback support."""
    
    def __init__(self, enabled: bool = True) -> None:
        """
        Initialize progress manager.
        
        Args:
            enabled: Whether progress bars are enabled
        """
        self.enabled = enabled and TQDM_AVAILABLE
    
    def create_progress_bar(self, total: Optional[int] = None, 
                           desc: Optional[str] = None, 
                           leave: bool = False) -> ProgressBar:
        """
        Create a progress bar.
        
        Args:
            total: Total number of steps
            desc: Description for the progress bar
            leave: Whether to leave the progress bar after completion
            
        Returns:
            Progress bar instance
        """
        if self.enabled:
            return TqdmProgressBar(total=total, desc=desc, leave=leave)
        else:
            return NullProgressBar(total=total, desc=desc, leave=leave)
    
    def create_main_pipeline_bar(self, stages: int = 5) -> ProgressBar:
        """
        Create main pipeline progress bar.
        
        Args:
            stages: Number of processing stages
            
        Returns:
            Progress bar for main pipeline
        """
        return self.create_progress_bar(
            total=stages,
            desc="Pipeline",
            leave=False
        )
    
    def create_figures_bar(self, total_figures: int) -> ProgressBar:
        """
        Create figures processing progress bar.
        
        Args:
            total_figures: Total number of figures to process
            
        Returns:
            Progress bar for figures processing
        """
        return self.create_progress_bar(
            total=total_figures,
            desc="Figures",
            leave=False
        )
    
    def create_tables_bar(self, total_tables: int) -> ProgressBar:
        """
        Create tables processing progress bar.
        
        Args:
            total_tables: Total number of tables to process
            
        Returns:
            Progress bar for tables processing
        """
        return self.create_progress_bar(
            total=total_tables,
            desc="Tables",
            leave=False
        )


def create_progress_bar(total: Optional[int] = None, desc: Optional[str] = None, 
                       leave: bool = False, enabled: bool = True) -> ProgressBar:
    """
    Convenience function to create a progress bar.
    
    Args:
        total: Total number of steps
        desc: Description for the progress bar
        leave: Whether to leave the progress bar after completion
        enabled: Whether progress bars are enabled
        
    Returns:
        Progress bar instance
    """
    manager = ProgressManager(enabled=enabled)
    return manager.create_progress_bar(total=total, desc=desc, leave=leave)
