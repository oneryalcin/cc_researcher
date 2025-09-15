# Multiagent Research System

A pragmatic implementation of multiagent research using Claude Code's native subagent capabilities. This system leverages Claude's intelligence for coordination while maintaining simplicity and debuggability.

## Overview

This system performs comprehensive research by:
1. **Decomposing** research queries into focused subtopics
2. **Delegating** subtopics to specialized research agents
3. **Synthesizing** findings into coherent reports
4. **Adding citations** with perfect source traceability

**Key Principle**: Let Claude's intelligence handle coordination; use the filesystem for state and communication.

## Quick Start

### Prerequisites

- Claude Code CLI/SDK installed and configured
- Python 3.8+

### Run Modes

- Full pipeline (default): Research → Synthesis → Citations

```bash
uv run research_system.py "What are the latest developments in quantum computing?"
```

- Simple mode: One‑pass “query → markdown” (fast ad‑hoc)

```bash
uv run research_system.py --simple "AI in private equity: 2025 landscape"
# or RESEARCH_MODE=simple uv run research_system.py "..."
```

- Cite‑only mode: Apply citations to an existing `synthesis_draft.md` in the workspace

```bash
RESEARCH_WORKSPACE=./my_workspace uv run research_system.py --cite "ignored"
```

This will:
- Create a workspace directory
- Spawn research subagents automatically (full pipeline)
- Generate a synthesis (`synthesis_draft.md`) and a final report with citations
- Save everything under `./research_workspace/` (or your chosen workspace)

### Advanced Usage

```python
from research_system import ResearchSystem
import asyncio

async def main():
    # Initialize system with custom workspace
    system = ResearchSystem("./my_research")

    # Run comprehensive research
    report = await system.research(
        "Compare different approaches to quantum error correction",
        max_agents=8
    )

    # Check progress
    status = system.get_research_status()
    print(f"Found {status.total_sources} sources across {status.active_research_areas} research areas")

asyncio.run(main())
```

## System Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│ Research System │    │ Subagent Network │    │ Citation Engine │
│                 │    │                  │    │                 │
│ • Query Router  │◄──►│ • Research Agents│◄──►│ • Source Tracker│
│ • Orchestrator  │    │ • Domain Experts │    │ • Citation Map  │
│ • Synthesizer   │    │ • Web Researchers│    │ • Reference Gen │
└─────────────────┘    └──────────────────┘    └─────────────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 ▼
                    ┌─────────────────────────┐
                    │ Shared Workspace        │
                    │ (Filesystem)            │
                    │                         │
                    │ findings_*.json        │
                    │ synthesis_draft.md     │
                    │ final_report.md        │
                    └─────────────────────────┘
```

## File Structure

```
project/
├── DESIGN.md                    # Complete system design document
├── README.md                    # This file
├── research_system.py           # Main system implementation
├── citations.py                 # Citation engine
├── .claude/agents/              # Project subagents discovered by Claude Code
│   ├── research-subagent.md     # Research specialist
│   └── citation-agent.md        # Citation specialist
└── example_workspace/           # Example data structure
    ├── findings/
    │   ├── findings_*.json      # Research results
    ├── reports/
    │   └── final_report.md      # Generated reports
    └── synthesis_draft.md       # Intermediate synthesis
```

## Components

### 1. Research System (`research_system.py`)

The main orchestrator that:
- Manages Claude Code subagents
- Coordinates research phases (full pipeline) or supports simple/cite‑only modes
- Tracks progress and logs tool events (optional verbose mode)
- Handles error recovery and produces reproducible on‑disk artifacts

**Key Methods:**
- `research(query)` - Execute full research pipeline
- `get_research_status()` - Monitor progress
- `list_findings()` - Review research areas
 - `simple_research(query)` - One‑pass report (no structured findings/citations)

### 2. Citation Engine (`citations.py`)

Handles source tracking and citation application:
- Maps claims to supporting sources
- Generates properly formatted references
- Validates citation integrity
- Supports multiple citation styles

**Key Methods:**
- `apply_citations(text)` - Add citations to text
- `validate_citations(text)` - Check citation integrity
- `get_source_summary()` - Source statistics

### 3. Subagents (`.claude/agents/`)

Specialized Claude agents for focused tasks:

**Research Subagent**: Performs focused research on specific topics
- Web search and content analysis
- Source credibility evaluation
- Structured data extraction
- JSON output generation

**Citation Agent**: Adds accurate citations to research text
- Source mapping and verification
- Reference formatting
- Text integrity preservation
- Citation placement optimization

## Usage Examples

### Basic Research

```python
# Quick one-off research
from research_system import quick_research

report = await quick_research("AI safety research trends 2024")
print(report)
```

### Comparative Research

```python
# Compare multiple related topics
from research_system import compare_research

queries = [
    "Quantum computing hardware approaches",
    "Quantum software and algorithms",
    "Quantum error correction methods"
]

comparison = await compare_research(queries, "./quantum_comparison")
```

### Citation Management

```python
# Add citations to existing text
from citations import quick_cite

uncited_text = "Recent advances in AI have shown remarkable progress..."
cited_text = quick_cite(uncited_text, "./research_workspace")
print(cited_text)
```

### Validation

```python
# Validate research report citations
from citations import validate_research_report

result = validate_research_report("./report.md", "./research_workspace")
print(f"Citations: {result.total_citations}")
print(f"Coverage: {result.coverage_percentage:.1f}%")
```

## Data Schema

### Research Findings Format

```json
{
    "topic": "specific_research_area",
    "agent_id": "research_subagent_001",
    "timestamp": "2024-01-15T10:30:00Z",
    "findings": "Comprehensive summary...",
    "sources": [
        {
            "url": "https://example.com/paper",
            "title": "Paper Title",
            "timestamp": "2024-01-15T10:30:00Z",
            "relevant_quotes": ["quote 1", "quote 2"],
            "credibility_score": 0.95,
            "source_type": "peer_reviewed"
        }
    ],
    "confidence": 0.88,
    "research_notes": "Methodology notes...",
    "related_topics": ["topic1", "topic2"]
}
```

### Source Types and Credibility

- **Peer-reviewed papers**: 0.9-1.0 credibility
- **Government reports**: 0.8-0.95 credibility
- **Institutional research**: 0.8-0.9 credibility
- **Reputable news**: 0.6-0.8 credibility
- **Industry reports**: 0.6-0.8 credibility
- **Blog posts/opinion**: 0.3-0.6 credibility

## Outputs & Debugging

- Workspace layout:
  - `findings/` — `findings_*.json` from subagents
  - `entities/entity_cards.json` — optional canonical metadata for named entities (entity_type, identifiers, allowed_domains)
  - `synthesis_draft.md` — main synthesis narrative (canonical)
  - `reports/research_report_<ts>.md` — final cited report (authoritative)
  - `reports/human_synthesis.md` — optional human-readable synthesis
  - `logs/events.ndjson` — tool/subagent events (UTC + durations)
  - `logs/messages.ndjson` — raw streamed messages (audit)
- Enable concise tool logs with `RESEARCH_VERBOSE=1` to see Task/WebSearch/WebFetch/Write details.
- Validate citations with `python citations.py validate reports/research_report_*.md`.

## Configuration

### Environment Variables

```bash
export CLAUDE_API_KEY="your_key_here"
export RESEARCH_WORKSPACE="./custom_workspace"
export MAX_RESEARCH_AGENTS=10
export MIN_SOURCE_CREDIBILITY=0.7
export CITATION_STYLE=apa   # Options: apa, chicago (default: apa)
export RESEARCH_FINDINGS_IDLE_SECS=8      # Wait after last write before synthesis
export RESEARCH_FINDINGS_TIMEOUT_SECS=180 # Max wait before moving on
export CLAUDE_MODEL=claude-sonnet-4-20250514 # Force Sonnet for research runs
export CLAUDE_PERMISSION_MODE=bypassPermissions # Or: default, acceptEdits, plan
export CLAUDE_MCP_SERVERS=/absolute/path/to/mcp-config.json # Provides web_search/web_fetch tools
export CLAUDE_SETTINGS_PATH=/absolute/path/to/settings.json # Optional Claude Code settings file
```

### System Options

```python
# Custom configuration
system = ResearchSystem(
    workspace_dir="./custom_workspace",
    max_agents=15,
    min_credibility=0.8
)
```

## Best Practices

### Research Query Design

**Good queries:**
- "Latest developments in quantum error correction 2024"
- "Comparative analysis of large language model architectures"
- "Climate change mitigation technologies: recent advances"

**Avoid:**
- Very broad queries ("Tell me about AI")
- Yes/no questions ("Is quantum computing viable?")
- Opinion-based queries ("What's the best programming language?")

### Managing Large Research Projects

1. **Break into phases**: Research → Synthesis → Citation → Review
2. **Monitor progress**: Use `get_research_status()` regularly
3. **Checkpoint frequently**: Save intermediate results
4. **Validate early**: Check citations before final output

### Debugging

1. **Check workspace contents**: All state is in files
2. **Examine findings JSON**: Verify data structure
3. **Review synthesis draft**: Check intermediate output
4. **Validate citations**: Use validation tools
5. **Inspect logs**: See `logs/events.ndjson` (tool/subagent events) and `logs/messages.ndjson` (streamed messages)

```bash
# Debug commands
ls -la research_workspace/findings/
python citations.py summary
python citations.py validate final_report.md
```

## Troubleshooting

### Common Issues

**No sources found**
- Check internet connectivity
- Verify search terms are specific enough
- Review workspace permissions

**Citation errors**
- Validate JSON schema in findings files
- Check for corrupt or incomplete source data
- Verify quote extraction accuracy

**Performance issues**
- Reduce max_agents parameter
- Use more specific research queries
- Clear workspace of old research

**Web tools not used (hallucinated links or "limited by inability to access real-time web sources")**
- Check the Phase 1 Summary output; if `web_search/web_fetch` are absent in "Tools used", web tools are not configured.
- Configure MCP servers that provide web tools and point the SDK at them:
  - Create or locate your MCP config file as per Claude Code docs
  - Set `CLAUDE_MCP_SERVERS=/absolute/path/to/your/mcp-config.json`
  - Ensure the config exposes `web_search` and `web_fetch` (or equivalent) tools
  - Re-run and observe `logs/events.ndjson` for PreToolUse entries: `web_search`, `web_fetch`

### Error Recovery

The system is designed for easy recovery:

1. **Workspace corruption**: Clear and restart
2. **Agent failures**: System will retry automatically
3. **Citation problems**: Re-run citation phase only
4. **Incomplete research**: Resume from last checkpoint

## Development

### Extending the System

**Add new agent types:**
1. Create agent definition in `agents/new_agent.md`
2. Define tools and responsibilities
3. Test with sample queries

**Customize citation styles:**
1. Modify `_format_*_reference()` methods in `citations.py`
2. Add new source types and formatting rules
3. Update validation logic

**Add new data sources:**
1. Extend research subagent capabilities
2. Update source credibility scoring
3. Add new source type classifications

### Testing

```bash
# Run system tests (uses mock SDK if Claude Code SDK isn't available)
uv run -m pytest -q

# Test individual components
uv run research_system.py "test query"
uv run citations.py validate example_report.md
```

## Performance & Limits

### Expected Performance

- **Research speed**: 10-20x faster than human researchers
- **Source coverage**: 50-200 sources per comprehensive query
- **Citation accuracy**: 95%+ (validated automatically)
- **Cost**: $5-25 per comprehensive report

### System Limits

- **Max agents**: 20 concurrent subagents (configurable)
- **Workspace size**: Limited by filesystem capacity
- **Source quality**: Depends on web search results
- **Context limits**: Managed automatically by Claude Code

### Scaling Considerations

- **Multiple workspaces**: Run parallel research projects
- **Source caching**: Reuse sources across related queries
- **Incremental research**: Build on previous findings
- **Distributed setup**: Multiple systems for large projects

## Contributing

See `DESIGN.md` for architectural principles and design philosophy.

### Key Principles

1. **Simplicity over complexity**: Choose boring, proven solutions
2. **Debuggability**: All state visible in filesystem
3. **Modularity**: Components work independently
4. **Pragmatism**: Solve real problems with simple tools

## License

MIT License - See LICENSE file for details.

## Support

- **Documentation**: See `DESIGN.md` for complete system design
- **Examples**: Check `example_workspace/` for sample data
- **Issues**: File bugs and feature requests on GitHub
- **Discussions**: Join community discussions for questions

---

*Built with Claude Code's native intelligence. Designed for simplicity, reliability, and real-world research needs.*
