#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Citation Engine for Multiagent Research System

Handles citation mapping and reference generation with focus on
accuracy, simplicity, and debuggability.

Philosophy: Keep it simple. Use exact string matching first,
then fall back to semantic matching only if needed.

Author: Design Document Implementation
Version: 1.0
"""

import json
import re
import hashlib
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from datetime import datetime
import os


@dataclass
class Source:
    """Simple data structure for source information."""
    url: str
    title: str
    timestamp: str
    relevant_quotes: List[str]
    credibility_score: float
    source_type: str = "unknown"
    access_date: str = ""

    def get_citation_key(self) -> str:
        """Generate unique citation key from URL."""
        return hashlib.md5(self.url.encode()).hexdigest()[:8]


@dataclass
class CitationMatch:
    """Represents a successful citation match."""
    source_id: str
    quote: str
    position: int
    citation_number: int


@dataclass
class ValidationResult:
    """Results of citation validation process."""
    total_citations: int
    total_sources: int
    coverage_percentage: float
    errors: List[str]
    warnings: List[str]


class CitationEngine:
    """
    Handles citation mapping and reference generation.

    Core principles:
    1. Exact quote matching before semantic matching
    2. Highest credibility source wins conflicts
    3. Every citation must map to source material
    4. Perfect text fidelity except for citation additions
    """

    def __init__(self, workspace_dir: str = "./research_workspace", style: Optional[str] = None):
        """
        Initialize citation engine.

        Args:
            workspace_dir: Directory containing research findings
        """
        self.workspace = Path(workspace_dir)
        self.findings_dir = self.workspace / "findings"
        # Reference style: 'apa', 'chicago', or 'generic' (fallback)
        env_style = os.getenv("CITATION_STYLE", "").strip().lower()
        self.style = (style or env_style or "apa").lower()
        if self.style not in {"apa", "chicago", "generic"}:
            self.style = "apa"

        if not self.findings_dir.exists():
            raise FileNotFoundError(f"Findings directory not found: {self.findings_dir}")

    def extract_all_sources(self) -> Dict[str, Source]:
        """
        Build comprehensive source map from all findings files.

        Returns:
            Dictionary mapping source_id -> Source object
        """
        sources = {}

        for findings_file in self.findings_dir.glob("findings_*.json"):
            try:
                data = json.loads(findings_file.read_text())

                for source_data in data.get("sources", []):
                    # Create unique source ID from URL
                    source_id = hashlib.md5(
                        source_data["url"].encode()
                    ).hexdigest()[:8]

                    # Skip if we already have this source (avoid duplicates)
                    if source_id in sources:
                        # Merge quotes if different findings reference same source
                        existing_quotes = set(sources[source_id].relevant_quotes)
                        new_quotes = set(source_data.get("relevant_quotes", []))
                        all_quotes = list(existing_quotes | new_quotes)
                        sources[source_id].relevant_quotes = all_quotes
                        continue

                    # Create new source entry
                    sources[source_id] = Source(
                        url=source_data["url"],
                        title=source_data["title"],
                        timestamp=source_data["timestamp"],
                        relevant_quotes=source_data.get("relevant_quotes", []),
                        credibility_score=source_data.get("credibility_score", 0.5),
                        source_type=source_data.get("source_type", "unknown"),
                        access_date=source_data.get("access_date", "")
                    )

            except (json.JSONDecodeError, KeyError) as e:
                print(f"Warning: Could not process {findings_file}: {e}")
                continue

        print(f"📚 Loaded {len(sources)} unique sources from {len(list(self.findings_dir.glob('findings_*.json')))} finding files")
        return sources

    def apply_citations(self, text: str, min_credibility: float = 0.5) -> str:
        """
        Add citations to text using exact quote matching.

        Args:
            text: The research text to add citations to
            min_credibility: Minimum credibility score for sources to be cited

        Returns:
            Text with citations added
        """
        sources = self.extract_all_sources()

        # Filter sources by credibility
        filtered_sources = {
            sid: source for sid, source in sources.items()
            if source.credibility_score >= min_credibility
        }

        if not filtered_sources:
            print(f"⚠️  No sources meet minimum credibility threshold ({min_credibility})")
            return text

        cited_sources = {}  # source_id -> citation_number
        citation_counter = 1

        # Sort sources by credibility for consistent citation order
        sorted_sources = sorted(
            filtered_sources.items(),
            key=lambda x: x[1].credibility_score,
            reverse=True
        )

        modified_text = text
        citations_added = []

        print(f"🔍 Processing {len(sorted_sources)} sources for citation matching...")

        for source_id, source in sorted_sources:
            for quote in source.relevant_quotes:
                if len(quote.strip()) < 10:  # Skip very short quotes
                    continue

                # Check if this exact quote appears in the text
                if quote in modified_text and source_id not in cited_sources:
                    # Add citation number after the quote
                    cited_sources[source_id] = citation_counter

                    # Apply citation
                    citation_text = f" [{citation_counter}]"
                    modified_text = modified_text.replace(
                        quote,
                        f"{quote}{citation_text}",
                        1  # Only replace first occurrence
                    )

                    citations_added.append(CitationMatch(
                        source_id=source_id,
                        quote=quote[:50] + "..." if len(quote) > 50 else quote,
                        position=modified_text.find(quote),
                        citation_number=citation_counter
                    ))

                    citation_counter += 1
                    break  # Only cite each source once

        # Generate references section
        if cited_sources:
            references = self._generate_references(filtered_sources, cited_sources)
            modified_text += f"\n\n## References\n\n{references}"

            print(f"✅ Added {len(cited_sources)} citations from {len(citations_added)} quote matches")
        else:
            print("⚠️  No exact quote matches found for citation")

        return modified_text

    def apply_semantic_citations(self, text: str, sources: Dict[str, Source] = None) -> str:
        """
        Apply citations using semantic matching (fallback method).

        This is more complex and should only be used when exact matching fails.

        Args:
            text: Text to add citations to
            sources: Optional pre-loaded sources

        Returns:
            Text with semantically-matched citations
        """
        if sources is None:
            sources = self.extract_all_sources()

        # This is a placeholder for more sophisticated semantic matching
        # For now, we'll use keyword matching as a simple semantic approach

        cited_sources = {}
        citation_counter = 1
        modified_text = text

        # Extract sentences that might need citations
        sentences = re.split(r'[.!?]+', text)

        for sentence in sentences:
            if len(sentence.strip()) < 20:  # Skip very short sentences
                continue

            # Look for sentences that contain factual claims (heuristic)
            factual_indicators = [
                'research shows', 'studies indicate', 'according to',
                'data reveals', 'findings suggest', 'results show',
                'researchers found', 'analysis reveals', 'evidence suggests'
            ]

            is_factual = any(indicator in sentence.lower() for indicator in factual_indicators)

            if is_factual:
                # Try to find supporting source
                best_source = self._find_best_supporting_source(sentence, sources)
                if best_source and best_source not in cited_sources:
                    cited_sources[best_source] = citation_counter
                    # Add citation at end of sentence
                    sentence_with_citation = sentence + f" [{citation_counter}]"
                    modified_text = modified_text.replace(sentence, sentence_with_citation)
                    citation_counter += 1

        # Generate references if citations were added
        if cited_sources:
            references = self._generate_references(sources, cited_sources)
            modified_text += f"\n\n## References\n\n{references}"

        return modified_text

    def _find_best_supporting_source(self, sentence: str, sources: Dict[str, Source]) -> Optional[str]:
        """
        Find the best source to support a given sentence using keyword matching.

        Args:
            sentence: Sentence to find support for
            sources: Available sources

        Returns:
            Source ID of best supporting source, or None
        """
        sentence_words = set(sentence.lower().split())

        best_source_id = None
        best_score = 0

        for source_id, source in sources.items():
            score = 0

            # Check title keywords
            title_words = set(source.title.lower().split())
            score += len(sentence_words & title_words) * 2

            # Check quote keywords
            for quote in source.relevant_quotes:
                quote_words = set(quote.lower().split())
                score += len(sentence_words & quote_words)

            # Weight by credibility
            weighted_score = score * source.credibility_score

            if weighted_score > best_score:
                best_score = weighted_score
                best_source_id = source_id

        # Only return if we found a reasonably good match
        return best_source_id if best_score > 3 else None

    def _generate_references(self, sources: Dict[str, Source],
                           cited_sources: Dict[str, int]) -> str:
        """
        Generate formatted reference list.

        Args:
            sources: All available sources
            cited_sources: Sources that were actually cited (source_id -> citation_number)

        Returns:
            Formatted reference string
        """
        references = []

        # Sort by citation number
        sorted_citations = sorted(cited_sources.items(), key=lambda x: x[1])

        for source_id, citation_num in sorted_citations:
            source = sources[source_id]
            references.append(self._format_reference(source, citation_num))

        return "\n".join(references)

    def _format_reference(self, source: Source, citation_num: int) -> str:
        if self.style == "apa":
            return self._format_reference_apa(source, citation_num)
        if self.style == "chicago":
            return self._format_reference_chicago(source, citation_num)
        # Fallback to generic
        return self._format_generic_reference(source, citation_num)

    def _format_reference_apa(self, source: Source, citation_num: int) -> str:
        """APA-like format without authors (data often unavailable)."""
        date = self._fmt_date(source.timestamp, order="ymd", style="apa")  # e.g., 2024, January 15
        site = self._site_name(source)
        accessed = self._fmt_accessed(source, style="apa")
        parts = [f"[{citation_num}] {source.title}. ({date}).", site + "." if site else None, source.url + ".", accessed]
        return " ".join(p for p in parts if p)

    def _format_reference_chicago(self, source: Source, citation_num: int) -> str:
        """Chicago-like format without authors (best effort with available fields)."""
        date = self._fmt_date(source.timestamp, order="mdy", style="chicago")  # e.g., January 15, 2024
        site = self._site_name(source)
        accessed = self._fmt_accessed(source, style="chicago")
        parts = [f"[{citation_num}] {source.title}.", (site + ".") if site else None, f"{date}.", source.url + ".", accessed]
        return " ".join(p for p in parts if p)

    # Legacy generic fallbacks

    def _format_generic_reference(self, source: Source, citation_num: int) -> str:
        """Format generic web reference."""
        try:
            year = datetime.fromisoformat(source.timestamp.replace('Z', '+00:00')).year
        except:
            year = "n.d."

        return f"[{citation_num}] {source.title} ({year}). {source.url}"

    # Helpers
    def _site_name(self, source: Source) -> Optional[str]:
        try:
            host = source.url.split('/')[2]
            return host
        except Exception:
            return None

    def _fmt_date(self, iso: str, order: str = "ymd", style: str = "apa") -> str:
        try:
            dt = datetime.fromisoformat(iso.replace('Z', '+00:00'))
        except Exception:
            return "n.d."
        month = dt.strftime('%B')
        if order == "ymd":
            # APA: 2024, January 15
            return f"{dt.year}, {month} {dt.day}"
        # Chicago: January 15, 2024
        return f"{month} {dt.day}, {dt.year}"

    def _fmt_accessed(self, source: Source, style: str = "apa") -> Optional[str]:
        if not source.access_date:
            return None
        try:
            ad = datetime.fromisoformat(source.access_date)
        except Exception:
            # Try YYYY-MM-DD without time
            try:
                ad = datetime.strptime(source.access_date, '%Y-%m-%d')
            except Exception:
                return None
        month = ad.strftime('%B')
        if style == "apa":
            return f"Accessed {month} {ad.day}, {ad.year}"
        if style == "chicago":
            return f"Accessed {month} {ad.day}, {ad.year}"
        return None

    def validate_citations(self, text: str) -> ValidationResult:
        """
        Validate that all citations have corresponding references and vice versa.

        Args:
            text: Text with citations to validate

        Returns:
            ValidationResult with validation details
        """
        errors = []
        warnings = []

        # Extract citation numbers from text
        citation_pattern = r'\[(\d+)\]'
        citations = re.findall(citation_pattern, text)
        citation_numbers = set(int(c) for c in citations)

        # Extract reference numbers from references section
        ref_pattern = r'^\[(\d+)\]'
        references = re.findall(ref_pattern, text, re.MULTILINE)
        reference_numbers = set(int(r) for r in references)

        # Check for citations without references
        missing_refs = citation_numbers - reference_numbers
        for citation in missing_refs:
            errors.append(f"Citation [{citation}] has no corresponding reference")

        # Check for references without citations
        unused_refs = reference_numbers - citation_numbers
        for ref in unused_refs:
            warnings.append(f"Reference [{ref}] is not cited in text")

        # Check for duplicate citation numbers
        if len(citations) != len(set(citations)):
            duplicates = [c for c in set(citations) if citations.count(c) > 1]
            for dup in duplicates:
                warnings.append(f"Citation [{dup}] appears multiple times")

        # Calculate coverage metrics
        total_sentences = len(re.split(r'[.!?]+', text))
        sentences_with_citations = len(re.findall(r'[.!?][^.!?]*\[\d+\]', text))
        coverage = (sentences_with_citations / total_sentences * 100) if total_sentences > 0 else 0

        return ValidationResult(
            total_citations=len(citation_numbers),
            total_sources=len(reference_numbers),
            coverage_percentage=coverage,
            errors=errors,
            warnings=warnings
        )

    def get_source_summary(self) -> Dict[str, any]:
        """
        Get summary statistics about available sources.

        Returns:
            Dictionary with source statistics
        """
        sources = self.extract_all_sources()

        if not sources:
            return {"error": "No sources found"}

        # Calculate statistics
        credibility_scores = [s.credibility_score for s in sources.values()]
        source_types = {}
        total_quotes = 0

        for source in sources.values():
            source_type = source.source_type
            source_types[source_type] = source_types.get(source_type, 0) + 1
            total_quotes += len(source.relevant_quotes)

        return {
            "total_sources": len(sources),
            "average_credibility": sum(credibility_scores) / len(credibility_scores),
            "min_credibility": min(credibility_scores),
            "max_credibility": max(credibility_scores),
            "source_types": source_types,
            "total_quotes": total_quotes,
            "average_quotes_per_source": total_quotes / len(sources)
        }


# Utility functions for common operations
def quick_cite(text: str, workspace_dir: str = "./research_workspace") -> str:
    """
    Convenience function for adding citations to text.

    Args:
        text: Text to add citations to
        workspace_dir: Research workspace directory

    Returns:
        Text with citations added
    """
    engine = CitationEngine(workspace_dir)
    return engine.apply_citations(text)


def validate_research_report(file_path: str, workspace_dir: str = "./research_workspace") -> ValidationResult:
    """
    Validate citations in a research report file.

    Args:
        file_path: Path to the research report file
        workspace_dir: Research workspace directory

    Returns:
        ValidationResult with validation details
    """
    engine = CitationEngine(workspace_dir)
    text = Path(file_path).read_text()
    return engine.validate_citations(text)


if __name__ == "__main__":
    import sys

    def main():
        if len(sys.argv) < 2:
            print("Citation Engine - Usage:")
            print("  python citations.py cite 'text to cite'")
            print("  python citations.py validate report.md")
            print("  python citations.py summary")
            return

        command = sys.argv[1]

        if command == "cite" and len(sys.argv) > 2:
            text = " ".join(sys.argv[2:])
            result = quick_cite(text)
            print("CITED TEXT:")
            print("=" * 50)
            print(result)

        elif command == "validate" and len(sys.argv) > 2:
            file_path = sys.argv[2]
            result = validate_research_report(file_path)
            print("VALIDATION RESULT:")
            print("=" * 50)
            print(f"Citations: {result.total_citations}")
            print(f"Sources: {result.total_sources}")
            print(f"Coverage: {result.coverage_percentage:.1f}%")
            if result.errors:
                print("Errors:")
                for error in result.errors:
                    print(f"  - {error}")
            if result.warnings:
                print("Warnings:")
                for warning in result.warnings:
                    print(f"  - {warning}")

        elif command == "summary":
            engine = CitationEngine()
            summary = engine.get_source_summary()
            print("SOURCE SUMMARY:")
            print("=" * 50)
            for key, value in summary.items():
                print(f"{key}: {value}")

        else:
            print("Unknown command or missing arguments")

    main()
