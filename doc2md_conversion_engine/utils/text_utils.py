#!/usr/bin/env python3
"""Text utility functions for the guideline processor module."""

import re
from typing import List, Set, Optional


def indent_bullets(text: str, indent_char: str = "> ") -> str:
    """
    Add indentation to bullet points in text.
    
    Args:
        text: Text containing bullet points
        indent_char: Character(s) to use for indentation
        
    Returns:
        Text with indented bullet points
    """
    if not text:
        return ""
    
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("- "):
            lines.append(f"{indent_char}{line}")
        else:
            lines.append(f"{indent_char}{line}")
    
    return "\n".join(lines)


def normalize_tokens(text: str) -> List[str]:
    """
    Extract and normalize tokens from text.
    
    Args:
        text: Text to tokenize
        
    Returns:
        List of normalized tokens
    """
    if not text:
        return []
    
    # Extract alphanumeric tokens with hyphens
    tokens = re.findall(r"[A-Za-z][A-Za-z\-]{1,}", text.lower())
    return tokens


def contains_forbidden_tokens(text: str, forbidden_tokens: Set[str]) -> bool:
    """
    Check if text contains any forbidden tokens.
    
    Args:
        text: Text to check
        forbidden_tokens: Set of forbidden tokens
        
    Returns:
        True if forbidden tokens are found, False otherwise
    """
    if not text or not forbidden_tokens:
        return False
    
    text_tokens = set(normalize_tokens(text))
    return any(token in text_tokens for token in forbidden_tokens)


def extract_module_from_anchor(anchor: str) -> Optional[str]:
    """
    Extract module identifier from anchor text.
    
    Args:
        anchor: Anchor text to parse
        
    Returns:
        Module identifier (e.g., "A", "B") or None if not found
    """
    if not anchor:
        return None
    
    # Pattern 1: "Module A" or "Module B"
    match = re.search(r"\bModule\s+([A-Z])\b", anchor, flags=re.IGNORECASE)
    if match:
        return match.group(1).upper()
    
    # Pattern 2: "A. Module" or "B. Module"
    match = re.match(r"^([A-Z])\.\s+Module\b", anchor, flags=re.IGNORECASE)
    if match:
        return match.group(1).upper()
    
    return None


def clean_text(text: str) -> str:
    """
    Clean and normalize text content.
    
    Args:
        text: Text to clean
        
    Returns:
        Cleaned text
    """
    if not text:
        return ""
    
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text)
    
    # Remove leading/trailing whitespace
    text = text.strip()
    
    # Normalize line endings
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    
    return text


def extract_section_number(text: str) -> Optional[str]:
    """
    Extract section number from text.
    
    Args:
        text: Text to parse
        
    Returns:
        Section number (e.g., "1.2", "3.4.1") or None if not found
    """
    if not text:
        return None
    
    # Pattern for section numbers: 1.2, 3.4.1, etc.
    match = re.search(r'^(\d+(?:\.\d+)*)', text.strip())
    if match:
        return match.group(1)
    
    return None


def is_likely_header(text: str, min_length: int = 3, max_length: int = 100) -> bool:
    """
    Determine if text is likely a header.
    
    Args:
        text: Text to analyze
        min_length: Minimum length for a header
        max_length: Maximum length for a header
        
    Returns:
        True if text is likely a header, False otherwise
    """
    if not text:
        return False
    
    text = text.strip()
    
    # Check length
    if len(text) < min_length or len(text) > max_length:
        return False
    
    # Check if it's all uppercase (common for headers)
    if text.isupper() and len(text) > 3:
        return True
    
    # Check if it starts with a number (section headers)
    if re.match(r'^\d+\.', text):
        return True
    
    # Check if it's a short, capitalized phrase
    words = text.split()
    if len(words) <= 8 and text[0].isupper():
        return True
    
    return False


def normalize_section_title(title: str) -> str:
    """
    Normalize section title for consistent formatting.
    
    Args:
        title: Original title
        
    Returns:
        Normalized title
    """
    if not title:
        return ""
    
    # Remove extra whitespace
    title = re.sub(r'\s+', ' ', title.strip())
    
    # Ensure proper capitalization (first letter of each word)
    title = title.title()
    
    # Handle special cases
    title = re.sub(r'\b(And|Or|The|A|An|In|On|At|To|For|Of|With|By)\b', 
                   lambda m: m.group(1).lower(), title, flags=re.IGNORECASE)
    
    return title
