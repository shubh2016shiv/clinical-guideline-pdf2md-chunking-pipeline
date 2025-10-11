#!/usr/bin/env python3
"""AI-powered document analysis using Gemini for figure interpretation with OCR fallback."""

import logging
import re
from typing import Optional, List, Tuple, Dict, Any
from dataclasses import dataclass

from PIL import Image
import pytesseract

# Gemini AI imports with graceful degradation
try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    genai = None
    GEMINI_AVAILABLE = False

from doc2md_conversion_engine.models.config import DocumentProcessingConfig
from doc2md_conversion_engine.exceptions import ConfigurationError, ProcessingError


@dataclass
class FigureAnalysisResult:
    """Result of AI-powered figure analysis."""
    
    summary: str
    analysis_method: str  # "gemini", "ocr", or "unavailable"
    confidence: str  # "high", "medium", "low"
    extracted_elements: Dict[str, List[str]]  # nodes, edges, labels
    error_message: Optional[str] = None


class AIDocumentAnalyzer:
    """
    AI-powered analyzer for document figures using Gemini with OCR fallback.
    
    Provides intelligent figure interpretation with fault tolerance and
    automatic fallback mechanisms for resilient processing.
    """

    def __init__(self, config: DocumentProcessingConfig):
        """
        Initialize the AI document analyzer.
        
        Args:
            config: Processing configuration with AI settings
            
        Raises:
            ConfigurationError: If AI is enabled but configuration is invalid
        """
        self.config = config
        self.logger = logging.getLogger(f"document_processing_engine.engine.figure_summarization_agent.{self.__class__.__name__}")
        
        # Initialize AI components
        self._gemini_model = None
        self._gemini_available = False
        
        if self.config.enable_gemini:
            self._initialize_gemini()
        else:
            self.logger.info("AI analysis disabled in configuration")

    def _initialize_gemini(self) -> None:
        """
        Initialize Gemini AI model with configuration validation.
        
        Raises:
            ConfigurationError: If Gemini configuration is invalid
        """
        if not GEMINI_AVAILABLE:
            self.logger.warning(
                "Gemini AI not available. Install with: pip install google-generativeai"
            )
            return
        
        # Validate API key
        from doc2md_conversion_engine.exceptions import APIKeyError
        
        if not self.config.gemini_api_key:
            raise APIKeyError(
                api_name="Gemini",
                message="Gemini API key required when enable_gemini=True. "
                       "Set GEMINI_API_KEY environment variable or provide in config."
            )
        
        try:

            # Configure Gemini with API Key
            genai.configure(api_key=self.config.gemini_api_key)
            
            # Initialize model with safety settings
            model_name = self.config.gemini_model_name
            self._gemini_model = genai.GenerativeModel(
                model_name=model_name,
                generation_config={
                    "temperature": self.config.gemini_temperature,
                    "top_p": 0.95,  # TODO: // Add the top_p, top_k, max_output_tokens parameter in the config
                    "top_k": 40,
                    "max_output_tokens": 1024,
                }
            )
            
            self._gemini_available = True
            self.logger.info(f"Gemini AI initialized successfully (model: {model_name})")
            
        except Exception as e:
            self.logger.error(f"Gemini initialization failed: {str(e)}")
            raise ConfigurationError(
                f"Failed to initialize Gemini AI: {str(e)}"
            ) from e

    def analyze(self, extracted_content: Any) -> Any:
        """
        Analyze extracted content and enrich figures with AI-generated summaries.
        
        Args:
            extracted_content: ExtractedContent object from ContentExtractor
            
        Returns:
            Enhanced ExtractedContent with AI analysis added to figures
        """
        if not extracted_content.figures:
            self.logger.debug("No figures to analyze")
            return extracted_content
        
        self.logger.info(f"Analyzing {len(extracted_content.figures)} figures with AI")
        
        for i, figure in enumerate(extracted_content.figures):
            figure_id = figure.get("figure_id", f"unknown_{i}")
            
            # Log figure details
            self.logger.info(f"Processing figure {i+1}/{len(extracted_content.figures)}: {figure_id}")
            
            # Check if image is valid
            if not figure.get("image"):
                self.logger.warning(f"Figure {figure_id}: No image data available")
                figure["summary"] = "Figure present; image unavailable for analysis."
                figure["analysis_method"] = "unavailable"
                continue
            
            # Log image properties
            img = figure["image"]
            if hasattr(img, 'width') and hasattr(img, 'height'):
                self.logger.info(f"Figure {figure_id}: Image is valid (size: {img.width}x{img.height}, mode: {getattr(img, 'mode', 'unknown')})")
            else:
                self.logger.warning(f"Figure {figure_id}: Image object may be invalid")
            
            # Perform AI analysis
            self.logger.info(f"Starting analysis for figure {figure_id}")
            analysis_result = self.analyze_figure(
                image=figure["image"],
                caption=figure.get("caption", "")
            )
            
            # Update figure with analysis results
            figure["summary"] = analysis_result.summary
            figure["analysis_method"] = analysis_result.analysis_method
            figure["confidence"] = analysis_result.confidence
            figure["extracted_elements"] = analysis_result.extracted_elements
            
            # Log analysis result
            self.logger.info(f"Figure {figure_id}: Analysis completed with method: {analysis_result.analysis_method}, confidence: {analysis_result.confidence}")
            
            # Remove PIL image from result to save memory
            if "image" in figure:
                del figure["image"]
        
        return extracted_content

    def analyze_figure(
        self,
        image: Image.Image,
        caption: str = ""
    ) -> FigureAnalysisResult:
        """
        Analyze a single figure using AI with automatic fallback.
        
        Args:
            image: PIL Image of the figure
            caption: Optional caption text for context
            
        Returns:
            FigureAnalysisResult with analysis summary and metadata
        """
        # Try Gemini first if available
        if self._gemini_available and self._gemini_model:
            try:
                return self._analyze_with_gemini(image, caption)
            except Exception as e:
                self.logger.warning(
                    f"Gemini analysis failed, falling back to OCR: {str(e)}"
                )
        
        # Fallback to OCR-based analysis
        try:
            return self._analyze_with_ocr(image, caption)
        except Exception as e:
            self.logger.warning(f"OCR analysis failed: {str(e)}")
            
            # Return minimal fallback result if all methods fail
            return FigureAnalysisResult(
                summary="- Figure detected (analysis unavailable)",
                analysis_method="unavailable",
                confidence="low",
                extracted_elements={"nodes": [], "edges": [], "labels": []},
                error_message=f"Analysis failed: {str(e)}"
            )

    def _analyze_with_gemini(
        self,
        image: Image.Image,
        caption: str
    ) -> FigureAnalysisResult:
        """
        Analyze figure using Gemini AI vision model.
        
        Args:
            image: PIL Image to analyze
            caption: Figure caption for context
            
        Returns:
            FigureAnalysisResult with AI-generated analysis
            
        Raises:
            ProcessingError: If Gemini API call fails
        """
        # Construct analysis prompt
        prompt = self._build_gemini_prompt(caption)
        
        try:
            # Call Gemini API with retry logic
            response = self._call_gemini_with_retry(prompt, image)
            
            # Extract and validate response
            summary_text = self._extract_gemini_response(response)
            
            # Parse structured elements from response
            extracted_elements = self._parse_analysis_elements(summary_text)
            
            # Determine confidence level
            confidence = "high"
            if "analysis unavailable" in summary_text.lower():
                confidence = "low"
            
            return FigureAnalysisResult(
                summary=summary_text,
                analysis_method="gemini",
                confidence=confidence,
                extracted_elements=extracted_elements,
                error_message=None
            )
            
        except Exception as e:
            self.logger.error(f"Gemini analysis error: {str(e)}")
            
            # Instead of raising an exception, return a fallback result
            return FigureAnalysisResult(
                summary="- Figure detected (analysis unavailable)\n- Gemini API error occurred",
                analysis_method="gemini_failed",
                confidence="low",
                extracted_elements={"nodes": [], "edges": [], "labels": []},
                error_message=str(e)
            )

    def _build_gemini_prompt(self, caption: str) -> str:
        """
        Build optimized prompt for Gemini figure analysis.
        
        Args:
            caption: Figure caption text
            
        Returns:
            Formatted prompt string
        """
        base_prompt = (
            "Analyze this document figure and provide a concise, factual description.\n\n"
            "Instructions:\n"
            "- Provide 3-7 bullet points describing key elements\n"
            "- Focus on visual content: diagrams, charts, graphs, flowcharts\n"
            "- Identify relationships and connections (use 'Edge: A → B' format for arrows)\n"
            "- Extract text labels and nodes (use 'Node: [text]' format)\n"
            "- Be precise and avoid speculation\n"
            "- Prefix all bullets with '- '\n\n"
        )
        
        if caption:
            base_prompt += f"Figure Caption: {caption}\n\n"
        
        base_prompt += "Provide your analysis:"
        
        return base_prompt

    def _call_gemini_with_retry(
        self,
        prompt: str,
        image: Image.Image,
        max_retries: int = 3
    ) -> Any:
        """
        Call Gemini API with exponential backoff retry logic.
        
        Args:
            prompt: Analysis prompt
            image: PIL Image to analyze
            max_retries: Maximum retry attempts
            
        Returns:
            Gemini API response
            
        Raises:
            ProcessingError: If all retries fail
        """
        import time
        
        # Log image details
        self.logger.info(f"Calling Gemini API with image: size={image.width}x{image.height}, mode={image.mode}")
        
        last_error = None
        
        for attempt in range(max_retries):
            try:
                self.logger.info(f"Gemini API attempt {attempt + 1}/{max_retries}")
                
                # Make the API call
                response = self._gemini_model.generate_content(
                    [prompt, image],
                    safety_settings={
                        "HARASSMENT": "BLOCK_NONE",
                        "HATE": "BLOCK_NONE",
                        "SEXUAL": "BLOCK_NONE",
                        "DANGEROUS": "BLOCK_NONE",
                    }
                )
                
                # Log response details
                self.logger.info(f"Gemini API response received: {type(response)}")
                
                # Check response attributes
                if hasattr(response, 'candidates'):
                    candidates_count = len(response.candidates) if response.candidates else 0
                    self.logger.info(f"Response has {candidates_count} candidates")
                    
                    if candidates_count > 0 and hasattr(response.candidates[0], 'finish_reason'):
                        self.logger.info(f"Finish reason: {response.candidates[0].finish_reason}")
                
                # Check for blocked content
                if hasattr(response, 'prompt_feedback'):
                    if response.prompt_feedback.block_reason:
                        error_msg = f"Content blocked: {response.prompt_feedback.block_reason}"
                        self.logger.warning(error_msg)
                        raise ProcessingError(error_msg)
                
                return response
                
            except Exception as e:
                last_error = e
                error_message = str(e)
                
                # Check for API key errors
                if "API key not valid" in error_message or "API_KEY_INVALID" in error_message:
                    from doc2md_conversion_engine.exceptions import APIKeyError
                    self.logger.error("Invalid Gemini API key detected")
                    raise APIKeyError(
                        api_name="Gemini",
                        message="Gemini API key is invalid. Please check your API key and try again."
                    )
                
                if attempt < max_retries - 1:
                    wait_time = (2 ** attempt) * 1  # Exponential backoff: 1s, 2s, 4s
                    self.logger.warning(
                        f"Gemini API attempt {attempt + 1} failed, "
                        f"retrying in {wait_time}s: {error_message}"
                    )
                    time.sleep(wait_time)
                else:
                    self.logger.error(f"All Gemini API retries exhausted: {error_message}")
        
        # Wrap the ProcessingError with more context
        from doc2md_conversion_engine.exceptions import ProcessingError, APIKeyError
        
        # Check if it's an API key error
        if isinstance(last_error, APIKeyError):
            raise last_error
        
        # Otherwise raise processing error
        raise ProcessingError(
            f"Gemini API failed after {max_retries} attempts: {str(last_error)}",
            context={'max_retries': max_retries, 'last_error_type': type(last_error).__name__}
        )

    def _extract_gemini_response(self, response: Any) -> str:
        """
        Extract and validate text from Gemini response.
        
        Args:
            response: Gemini API response object
            
        Returns:
            Extracted text content
            
        Raises:
            ProcessingError: If response is invalid or empty
        """
        try:
            # Check for finish reason (1 = STOP/success, 2+ = issues like MAX_TOKENS, SAFETY, etc.)
            if hasattr(response, 'candidates') and response.candidates:
                candidate = response.candidates[0]
                if hasattr(candidate, 'finish_reason'):
                    finish_reason = candidate.finish_reason
                    # finish_reason 1 = STOP (successful), 2+ = potential issues
                    if finish_reason != 1 and finish_reason != 0:
                        self.logger.warning(f"Non-successful finish_reason: {finish_reason}")
                        return "- Figure detected (analysis unavailable)\n- Gemini API returned non-successful response"
            
            # First try the simple text accessor (like in obsolete code)
            try:
                text = response.text.strip()
                if text:
                    return text
            except (AttributeError, ValueError) as e:
                self.logger.debug(f"Could not access response.text directly: {e}")
            
            # Try to extract from candidates
            if hasattr(response, 'candidates') and response.candidates:
                candidate = response.candidates[0]
                if hasattr(candidate, 'content') and candidate.content:
                    if hasattr(candidate.content, 'parts') and candidate.content.parts:
                        for part in candidate.content.parts:
                            if hasattr(part, 'text') and part.text:
                                return part.text.strip()
            
            # If we get here, we couldn't extract text
            self.logger.warning("Could not extract text from Gemini response, using fallback")
            return "- Figure detected (analysis unavailable)\n- Unable to extract text from Gemini response"
            
        except Exception as e:
            self.logger.error(f"Error extracting Gemini response: {str(e)}")
            return "- Figure detected (analysis unavailable)\n- Error processing Gemini response"

    def _parse_analysis_elements(self, analysis_text: str) -> Dict[str, List[str]]:
        """
        Parse structured elements from analysis text.
        
        Args:
            analysis_text: AI-generated analysis text
            
        Returns:
            Dictionary with categorized elements (nodes, edges, labels)
        """
        elements = {
            "nodes": [],
            "edges": [],
            "labels": []
        }
        
        lines = [line.strip() for line in analysis_text.split('\n') if line.strip()]
        
        for line in lines:
            # Extract nodes
            if "Node:" in line or "node:" in line.lower():
                node_text = re.sub(r'^-?\s*Node:\s*', '', line, flags=re.IGNORECASE)
                elements["nodes"].append(node_text.strip())
            
            # Extract edges/relationships
            elif "Edge:" in line or "edge:" in line.lower():
                edge_text = re.sub(r'^-?\s*Edge:\s*', '', line, flags=re.IGNORECASE)
                elements["edges"].append(edge_text.strip())
            
            # Extract general labels
            elif line.startswith('-'):
                label_text = line.lstrip('- ').strip()
                if label_text and not any(kw in label_text.lower() for kw in ['node:', 'edge:']):
                    elements["labels"].append(label_text)
        
        return elements

    def _analyze_with_ocr(
        self,
        image: Image.Image,
        caption: str
    ) -> FigureAnalysisResult:
        """
        Analyze figure using OCR as fallback method.
        
        Args:
            image: PIL Image to analyze
            caption: Figure caption for context
            
        Returns:
            FigureAnalysisResult with OCR-based analysis
        """
        try:
            # Extract text using Tesseract OCR
            ocr_language = self.config.ocr_lang
            extracted_text = pytesseract.image_to_string(
                image,
                lang=ocr_language
            ).strip()
            
            # Parse OCR results
            analysis_result = self._parse_ocr_text(extracted_text, caption)
            
            return analysis_result
            
        except Exception as e:
            self.logger.warning(f"OCR analysis failed: {str(e)}")
            
            # Return minimal result if OCR fails
            return FigureAnalysisResult(
                summary=self._create_fallback_summary(caption),
                analysis_method="unavailable",
                confidence="low",
                extracted_elements={"nodes": [], "edges": [], "labels": []},
                error_message=str(e)
            )

    def _parse_ocr_text(
        self,
        ocr_text: str,
        caption: str
    ) -> FigureAnalysisResult:
        """
        Parse OCR text and extract structured information.
        
        Args:
            ocr_text: Raw OCR extracted text
            caption: Figure caption
            
        Returns:
            FigureAnalysisResult with parsed OCR data
        """
        lines = [line.strip() for line in ocr_text.split('\n') if line.strip()]
        
        # Pattern for detecting arrows/relationships
        arrow_pattern = re.compile(r"(.+?)\s*(?:->|→|⇒|➡|=>)\s*(.+)")
        
        nodes = []
        edges = []
        labels = []
        
        for line in lines:
            # Check for arrow relationships
            arrow_match = arrow_pattern.search(line)
            if arrow_match:
                source = arrow_match.group(1).strip()
                target = arrow_match.group(2).strip()
                edges.append(f"{source} → {target}")
            # Extract potential labels (reasonable word count)
            elif 2 <= len(line.split()) <= 12:
                labels.append(line)
        
        # Build summary bullets
        summary_bullets = []
        
        if caption:
            summary_bullets.append(f"- Caption: {caption}")
        
        # Add nodes (limit to prevent overflow)
        for label in labels[:12]:
            summary_bullets.append(f"- Node: {label}")
        
        # Add edges
        for edge in edges[:12]:
            summary_bullets.append(f"- Edge: {edge}")
        
        # Default message if nothing extracted
        if not summary_bullets:
            summary_bullets.append(
                "- Diagram detected; OCR could not extract labels confidently."
            )
        
        summary = "\n".join(summary_bullets)
        confidence = "medium" if (labels or edges) else "low"
        
        return FigureAnalysisResult(
            summary=summary,
            analysis_method="ocr",
            confidence=confidence,
            extracted_elements={
                "nodes": labels,
                "edges": edges,
                "labels": labels
            },
            error_message=None
        )

    def _create_fallback_summary(self, caption: str) -> str:
        """
        Create minimal fallback summary when analysis fails.
        
        Args:
            caption: Figure caption
            
        Returns:
            Basic summary string
        """
        if caption:
            return f"- Figure present with caption: {caption}\n- Detailed analysis unavailable."
        return "- Figure present; analysis unavailable."

    def cleanup(self) -> None:
        """Clean up AI analyzer resources and connections."""
        self.logger.debug("Cleaning up AI analyzer resources")
        
        # Clear Gemini model reference
        self._gemini_model = None
        self._gemini_available = False
        
        # Additional cleanup if needed
        self.logger.info("AI analyzer cleanup completed")

    def get_analysis_stats(self) -> Dict[str, Any]:
        """
        Get statistics about analyzer configuration and availability.
        
        Returns:
            Dictionary with analyzer status information
        """
        return {
            "gemini_available": self._gemini_available,
            "gemini_enabled": self.config.enable_gemini,
            "model_name": self.config.gemini_model_name if self._gemini_available else None,
            "ocr_language": self.config.ocr_lang,
            "fallback_mode": "ocr" if not self._gemini_available else "none"
        }
