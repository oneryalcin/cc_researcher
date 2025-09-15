import json
import os
from pathlib import Path

from citations import CitationEngine


def _seed(ws: Path):
    d = ws / "findings"
    d.mkdir(parents=True, exist_ok=True)
    data = {
        "topic": "t",
        "agent_id": "research_subagent_001",
        "timestamp": "2024-01-15T10:30:00Z",
        "findings": "...",
        "sources": [
            {
                "url": "https://example.com/paper",
                "title": "Example Paper",
                "timestamp": "2024-01-15T10:30:00Z",
                "relevant_quotes": [
                    "A specific claim is supported by this example paper"
                ],
                "credibility_score": 0.95,
                "source_type": "peer_reviewed",
                "access_date": "2024-01-20",
            }
        ],
        "confidence": 0.9,
    }
    (d / "findings_test.json").write_text(json.dumps(data))


def test_apa_style(tmp_path: Path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    _seed(ws)
    monkeypatch.setenv("CITATION_STYLE", "apa")
    engine = CitationEngine(str(ws))
    text = "A specific claim is supported by this example paper"
    out = engine.apply_citations(text)
    assert "## References" in out
    # Check APA-like components
    assert "(2024, January" in out
    assert "example.com" in out
    assert "Accessed January 20, 2024" in out


def test_chicago_style(tmp_path: Path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    _seed(ws)
    monkeypatch.setenv("CITATION_STYLE", "chicago")
    engine = CitationEngine(str(ws))
    text = "A specific claim is supported by this example paper"
    out = engine.apply_citations(text)
    assert "## References" in out
    # Check Chicago-like components
    assert "January 15, 2024" in out
    assert "example.com" in out
    assert "Accessed January 20, 2024" in out

