import json
from pathlib import Path

from research_system import ResearchSystem


def test_get_research_status_counts(tmp_path: Path):
    ws = tmp_path / "ws"
    (ws / "findings").mkdir(parents=True, exist_ok=True)
    (ws / "reports").mkdir(parents=True, exist_ok=True)

    # Seed a minimal findings file
    data = {
        "topic": "t1",
        "agent_id": "research_subagent_001",
        "timestamp": "2024-01-10T00:00:00Z",
        "findings": "...",
        "sources": [
            {"url": "https://a", "title": "A", "timestamp": "2024-01-10T00:00:00Z", "relevant_quotes": ["q"], "credibility_score": 0.8},
            {"url": "https://b", "title": "B", "timestamp": "2024-01-10T00:00:00Z", "relevant_quotes": ["q2"], "credibility_score": 0.9},
        ],
        "confidence": 0.75,
    }
    (ws / "findings" / "findings_t1.json").write_text(json.dumps(data))

    system = ResearchSystem(str(ws))
    metrics = system.get_research_status()

    assert metrics.active_research_areas == 1
    assert metrics.total_sources == 2
    assert metrics.confidence_avg > 0

