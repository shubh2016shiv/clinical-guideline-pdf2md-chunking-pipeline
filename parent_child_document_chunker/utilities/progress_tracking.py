#!/usr/bin/env python3
"""Progress management utilities for the document chunker module."""

import sys
from typing import Optional, Union
from contextlib import contextmanager


class ProgressManager:
    """Manages progress bars for chunking operations."""
    
    def __init__(self, enable_progress: bool = True):
        """
        Initialize the progress manager.
        
        Args:
            enable_progress: Whether to enable progress bars
        """
        self.enable_progress = enable_progress
        self._tqdm_available = self._check_tqdm_available()
    
    def _check_tqdm_available(self) -> bool:
        """Check if tqdm is available for progress bars."""
        try:
            import tqdm
            return True
        except ImportError:
            return False
    
    def create_progress_bar(
        self,
        total: int,
        description: str = "Processing",
        unit: str = "items"
    ) -> Union['ProgressBar', 'DummyProgressBar']:
        """
        Create a progress bar.
        
        Args:
            total: Total number of items to process
            description: Description for the progress bar
            unit: Unit of measurement
            
        Returns:
            Progress bar object
        """
        if not self.enable_progress:
            return DummyProgressBar(total, description, unit)
        
        if self._tqdm_available:
            return TQDMProgressBar(total, description, unit)
        else:
            return SimpleProgressBar(total, description, unit)


class ProgressBar:
    """Base class for progress bars."""
    
    def __init__(self, total: int, description: str, unit: str):
        self.total = total
        self.description = description
        self.unit = unit
        self.current = 0
    
    def update(self, n: int = 1) -> None:
        """Update the progress bar."""
        self.current += n
    
    def close(self) -> None:
        """Close the progress bar."""
        pass


class DummyProgressBar(ProgressBar):
    """Dummy progress bar that does nothing."""
    
    def __init__(self, total: int, description: str, unit: str):
        super().__init__(total, description, unit)
    
    def update(self, n: int = 1) -> None:
        pass


class SimpleProgressBar(ProgressBar):
    """Simple text-based progress bar."""
    
    def __init__(self, total: int, description: str, unit: str):
        super().__init__(total, description, unit)
        self._print_progress()
    
    def update(self, n: int = 1) -> None:
        super().update(n)
        self._print_progress()
    
    def _print_progress(self) -> None:
        """Print current progress."""
        percentage = (self.current / self.total) * 100 if self.total > 0 else 0
        bar_length = 30
        filled_length = int(bar_length * self.current // self.total)
        bar = '█' * filled_length + '-' * (bar_length - filled_length)
        
        sys.stdout.write(f'\r{self.description}: |{bar}| {percentage:5.1f}% ({self.current}/{self.total} {self.unit})')
        sys.stdout.flush()
        
        if self.current >= self.total:
            print()  # New line when complete
    
    def close(self) -> None:
        """Close the progress bar."""
        if self.current < self.total:
            print()  # Ensure new line


class TQDMProgressBar(ProgressBar):
    """TQDM-based progress bar."""
    
    def __init__(self, total: int, description: str, unit: str):
        super().__init__(total, description, unit)
        import tqdm
        self._tqdm = tqdm.tqdm(
            total=total,
            desc=description,
            unit=unit,
            leave=False
        )
    
    def update(self, n: int = 1) -> None:
        super().update(n)
        self._tqdm.update(n)
    
    def close(self) -> None:
        """Close the progress bar."""
        self._tqdm.close()
