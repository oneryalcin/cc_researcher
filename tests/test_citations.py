import json
from pathlib import Path

from citations import CitationEngine


def write_findings(ws: Path, topic: str, quote: str):
    findings_dir = ws / "findings"
    findings_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "topic": topic,
        "agent_id": "research_subagent_001",
        "timestamp": "2024-01-15T10:30:00Z",
        "findings": "test findings",
        "sources": [
            {
                "url": "https://example.com/paper",
                "title": "Paper Title",
                "timestamp": "2024-01-15T10:30:00Z",
                "relevant_quotes": [quote],
                "credibility_score": 0.95,
                "source_type": "peer_reviewed",
                "access_date": "2024-01-15",
            }
        ],
        "confidence": 0.9,
    }
    (findings_dir / "findings_test.json").write_text(json.dumps(data))


def test_apply_and_validate_citations(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()

    quote = "Exact supporting quote for claim"
    write_findings(ws, "topic", quote)

    engine = CitationEngine(str(ws))
    text = f"This is a claim. {quote}. More text."
    cited = engine.apply_citations(text)

    assert "## References" in cited
    assert " [1]" in cited  # first citation added

    result = engine.validate_citations(cited)
    assert result.total_citations >= 1
    assert result.total_sources >= 1
    assert not result.errors

