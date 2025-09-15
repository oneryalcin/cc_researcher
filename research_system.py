#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "claude-code-sdk",
# ]
# ///
"""
Multiagent Research System

A pragmatic implementation leveraging Claude Code's native subagent capabilities
for comprehensive research with proper citation tracking.

Author: Design Document Implementation
Version: 1.0
"""

import json
import asyncio
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import hashlib
import time
import contextlib
import os

try:
    # Preferred import based on official SDK docs
    from claude_code_sdk import ClaudeCodeOptions, ClaudeSDKClient
    # Optional types for hooks (if available)
    try:
        from claude_code_sdk import HookMatcher, HookContext  # type: ignore
    except Exception:  # pragma: no cover
        HookMatcher = None  # type: ignore
        HookContext = None  # type: ignore
except ImportError:
    print(f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} Warning: claude_code_sdk not available. Using mock implementation for demo.")

    class ClaudeCodeOptions:
        def __init__(self, **kwargs):
            self.options = kwargs

    class ClaudeSDKClient:
        def __init__(self, options=None):
            self.options = options

        async def query(self, prompt: str) -> str:
            return f"Mock response to: {prompt[:120]}..."

        async def __aenter__(self):  # allow async with for mock
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def receive_response(self):
            # Yield a single mock message
            yield "Mock streamed response."

@dataclass
class ResearchMetrics:
    """Track research progress and quality metrics."""
    active_research_areas: int
    total_sources: int
    last_updated: Optional[str]
    confidence_avg: float
    research_duration_seconds: float


class ResearchSystem:
    """
    The core research orchestrator.

    Leverages Claude Code's native subagent system rather than
    building complex coordination layers.

    Philosophy:
    - Let Claude's intelligence handle coordination
    - Use filesystem as database and communication layer
    - Keep everything debuggable and transparent
    """

    def __init__(self, workspace_dir: str = "./research_workspace"):
        """
        Initialize the research system.

        Args:
            workspace_dir: Directory for storing research state and outputs
        """
        self.workspace = Path(workspace_dir)
        self.start_time: Optional[datetime] = None
        self.workspace.mkdir(exist_ok=True)

        # Initialize required subdirectories
        (self.workspace / "findings").mkdir(exist_ok=True)
        (self.workspace / "reports").mkdir(exist_ok=True)

        # Ensure subagents are available relative to cwd by mirroring project agents
        try:
            project_agents_dir = Path.cwd() / ".claude" / "agents"
            if project_agents_dir.exists():
                ws_agents_dir = self.workspace / ".claude" / "agents"
                ws_agents_dir.mkdir(parents=True, exist_ok=True)
                for f in project_agents_dir.glob("*.md"):
                    tgt = ws_agents_dir / f.name
                    if not tgt.exists():
                        tgt.write_text(f.read_text())
        except Exception as _e:
            # Non-fatal; SDK can still operate without custom agents
            pass

        # Env-configurable thresholds for findings readiness
        self.findings_idle_secs = self._env_float("RESEARCH_FINDINGS_IDLE_SECS", 8.0)
        self.findings_timeout_secs = self._env_float("RESEARCH_FINDINGS_TIMEOUT_SECS", 180.0)

    @staticmethod
    def _utc_ts() -> str:
        return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    def _ensure_logs_dir(self) -> Path:
        logs = self.workspace / "logs"
        logs.mkdir(exist_ok=True)
        return logs

    def _env_float(self, name: str, default: float) -> float:
        try:
            v = os.getenv(name)
            return float(v) if v is not None and v != "" else default
        except Exception:
            return default

    def _env_str(self, name: str, default: str) -> str:
        v = os.getenv(name)
        return v if v not in (None, "") else default

    def _build_client_options(self) -> "ClaudeCodeOptions":
        """Create ClaudeCodeOptions with cwd, allowed tools, and optional logging hooks."""
        hooks_cfg = None
        verbose = os.getenv("RESEARCH_VERBOSE", "").lower() in ("1", "true", "yes")
        # Only configure hooks if SDK provides HookMatcher and verbose logging enabled
        if verbose and 'HookMatcher' in globals() and HookMatcher is not None:
            logs_dir = self._ensure_logs_dir()

            def _trunc(val, n=400):
                try:
                    s = val if isinstance(val, str) else json.dumps(val, default=str)
                except Exception:
                    s = str(val)
                return (s[:n] + "…") if len(s) > n else s

            start_times: Dict[str, float] = {}

            async def _pre_hook(input_data: dict, tool_use_id, context):  # type: ignore
                try:
                    if tool_use_id:
                        start_times[tool_use_id] = time.time()
                    tool_name = input_data.get('tool_name') or input_data.get('toolName') or 'Unknown'
                    # Decode tool_input for readable logging
                    ti = input_data.get('tool_input') or input_data.get('input')
                    if isinstance(ti, str):
                        try:
                            ti_parsed = json.loads(ti)
                        except Exception:
                            ti_parsed = {"raw": ti[:200] + ("…" if len(ti) > 200 else "")}
                    else:
                        ti_parsed = ti or {}
                    # Build a concise detail string per tool
                    detail = None
                    try:
                        if tool_name.lower() == 'task':
                            desc = ti_parsed.get('description') if isinstance(ti_parsed, dict) else None
                            sub = ti_parsed.get('subagent_type') if isinstance(ti_parsed, dict) else None
                            if desc or sub:
                                detail = f"desc='{(desc or '')[:64]}', subagent='{sub or ''}'"
                        elif tool_name.lower() in ('web_search', 'websearch'):
                            q = ti_parsed.get('query') if isinstance(ti_parsed, dict) else None
                            if q:
                                detail = f"query='{q[:96]}'"
                        elif tool_name.lower() in ('web_fetch', 'webfetch'):
                            url = ti_parsed.get('url') if isinstance(ti_parsed, dict) else None
                            if url:
                                host = url.split('/')[2] if '://' in url and len(url.split('/')) > 2 else url[:96]
                                detail = f"url_host='{host}'"
                        elif tool_name.lower() == 'write':
                            fp = ti_parsed.get('file_path') if isinstance(ti_parsed, dict) else None
                            if fp:
                                try:
                                    rel = str(Path(fp).resolve())
                                except Exception:
                                    rel = fp
                                detail = f"file='{rel}'"
                        elif tool_name.lower() == 'read':
                            fp = ti_parsed.get('file_path') if isinstance(ti_parsed, dict) else None
                            if fp:
                                detail = f"file='{fp}'"
                        elif tool_name.lower() == 'glob':
                            pat = ti_parsed.get('pattern') if isinstance(ti_parsed, dict) else None
                            if pat:
                                detail = f"pattern='{pat}'"
                    except Exception:
                        pass
                    payload = {
                        'event': 'PreToolUse',
                        'tool': tool_name,
                        'tool_input': _trunc(input_data.get('tool_input') or input_data.get('input')),
                        'tool_use_id': tool_use_id,
                        'ts': time.time(),
                    }
                    (logs_dir / "events.ndjson").open("a").write(json.dumps(payload) + "\n")
                    if detail:
                        print(f"{ResearchSystem._utc_ts()} 🛠️  Start {tool_name} :: {detail}")
                    else:
                        print(f"{ResearchSystem._utc_ts()} 🛠️  Start {tool_name}")
                except Exception:
                    pass
                return {}

            async def _post_hook(input_data: dict, tool_use_id, context):  # type: ignore
                try:
                    dur_ms = None
                    if tool_use_id and tool_use_id in start_times:
                        dur_ms = int((time.time() - start_times.pop(tool_use_id)) * 1000)
                    tool_name = input_data.get('tool_name') or input_data.get('toolName') or 'Unknown'
                    payload = {
                        'event': 'PostToolUse',
                        'tool': tool_name,
                        'tool_output': _trunc(input_data.get('tool_output')) if 'tool_output' in input_data else None,
                        'tool_use_id': tool_use_id,
                        'duration_ms': dur_ms,
                        'ts': time.time(),
                    }
                    (logs_dir / "events.ndjson").open("a").write(json.dumps(payload) + "\n")
                    if dur_ms is not None:
                        print(f"{ResearchSystem._utc_ts()} ✅  Done {tool_name} in {dur_ms}ms")
                    else:
                        print(f"{ResearchSystem._utc_ts()} ✅  Done {tool_name}")
                except Exception:
                    pass
                return {}

            async def _subagent_hook(input_data: dict, tool_use_id, context):  # type: ignore
                try:
                    payload = {
                        'event': 'SubagentStop',
                        'subagent': input_data.get('subagent_type') or input_data.get('subagent'),
                        'ts': time.time(),
                    }
                    (logs_dir / "events.ndjson").open("a").write(json.dumps(payload) + "\n")
                    label = payload.get('subagent') or 'unknown'
                    print(f"{ResearchSystem._utc_ts()} 🧩 Subagent finished: {label}")
                except Exception:
                    pass
                return {}

            hooks_cfg = {
                'PreToolUse': [HookMatcher(hooks=[_pre_hook])],
                'PostToolUse': [HookMatcher(hooks=[_post_hook])],
                'SubagentStop': [HookMatcher(hooks=[_subagent_hook])],
            }

        # Allow essential tools; Task enables subagent delegation
        allowed = [
            'Task', 'Read', 'Write', 'Glob', 'Grep', 'Bash',
            'web_search', 'web_fetch', 'WebSearch', 'WebFetch',
            'TodoWrite'
        ]
        mcp_cfg = os.getenv("CLAUDE_MCP_SERVERS")
        settings_path = os.getenv("CLAUDE_SETTINGS_PATH")
        # Ensure project and workspace dirs are visible
        add_dirs = [str(Path.cwd()), str(self.workspace)]
        # Stable session per workspace to preserve context across phases
        session_id = f"session::{self.workspace.resolve()}"
        return ClaudeCodeOptions(
            cwd=str(self.workspace),
            allowed_tools=allowed,
            hooks=hooks_cfg,
            model=self._env_str("CLAUDE_MODEL", "claude-sonnet-4-20250514"),
            permission_mode=self._env_str("CLAUDE_PERMISSION_MODE", "bypassPermissions"),
            mcp_servers=mcp_cfg if mcp_cfg else None,
            settings=settings_path if settings_path else None,
            add_dirs=add_dirs,
            continue_conversation=True,
            resume=session_id,
        )

    async def research(self, query: str, max_agents: int = 10) -> str:
        """
        Execute comprehensive research using subagent delegation.

        This is where Claude's intelligence takes over - it decides
        what subagents to spawn, how to break down the problem,
        and how to coordinate the research effort.

        Args:
            query: The research question to investigate
            max_agents: Maximum number of subagents to spawn (safety limit)

        Returns:
            Final research report with citations
        """
        self.start_time = datetime.now()

        print(f"{self._utc_ts()} 🔬 Starting research: {query}")
        print(f"{self._utc_ts()} 📁 Workspace: {self.workspace}")

        try:
            # Preflight: check tool availability
            tool_status = await self._check_tooling()
            print(f"{self._utc_ts()} 🔧 Tools — web_search: {tool_status.get('web_search')}, web_fetch: {tool_status.get('web_fetch')}, bash: {tool_status.get('Bash')}")

            # Phase 1: Research Planning & Execution
            print("\n" + f"{self._utc_ts()} 📋 Phase 1: Research Planning & Execution")
            # Use an SDK client session bound to the workspace
            async with ClaudeSDKClient(options=self._build_client_options()) as client:
                await self._execute_research_phase(client, query, max_agents)

            # Wait for findings to be produced and settle before synthesis
            await self._await_findings(min_files=1, idle_secs=self.findings_idle_secs, timeout_secs=self.findings_timeout_secs)
            # Post-process findings to fix obvious issues and file hygiene
            self._postprocess_findings()
            # Emit compact Phase 1 summary
            self._emit_phase1_summary()

            # Phase 2: Synthesis
            print("\n" + f"{self._utc_ts()} 🔄 Phase 2: Synthesis")
            async with ClaudeSDKClient(options=self._build_client_options()) as client:
                synthesis = await self._execute_synthesis_phase(client)

            # Phase 3: Citation Application
            print("\n" + f"{self._utc_ts()} 📚 Phase 3: Citation Application")
            async with ClaudeSDKClient(options=self._build_client_options()) as client:
                final_report = await self._execute_citation_phase(client, synthesis)
            # Remove any leaked transcript artifacts before saving
            final_report = self._sanitize_text(final_report)

            # Save final output with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = self.workspace / "reports" / f"research_report_{timestamp}.md"
            output_path.write_text(final_report)

            print(f"\n{self._utc_ts()} ✅ Research complete! Report saved to: {output_path}")

            # Print summary metrics
            metrics = self.get_research_status()
            print(f"{self._utc_ts()} 📊 Research areas: {metrics.active_research_areas}")
            print(f"{self._utc_ts()} 📄 Total sources: {metrics.total_sources}")
            print(f"{self._utc_ts()} ⏱️  Duration: {metrics.research_duration_seconds:.1f}s")

            return final_report

        except Exception as e:
            error_msg = f"Research failed: {str(e)}"
            print(f"{self._utc_ts()} ❌ {error_msg}")

            # Save error state for debugging
            error_path = self.workspace / f"error_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            error_path.write_text(f"Query: {query}\nError: {error_msg}\nWorkspace state:\n{self._debug_workspace()}")

            raise

    async def _execute_research_phase(self, client: "ClaudeSDKClient", query: str, max_agents: int) -> None:
        """Execute the parallel research phase using subagents."""
        research_prompt = f"""
Research this topic comprehensively using subagents: {query}

Use project subagents if available (e.g., research-subagent). Keep the lead thread focused on coordination and synthesis; delegate web research to subagents by explicitly invoking the Task tool with `subagent_type: research-subagent`.

Instructions:
1. Break the query into up to {min(max_agents, 8)} focused, non-overlapping subtopics.
2. For each subtopic, spawn a subagent via the Task tool:
   - description: short summary of the subtopic
   - subagent_type: research-subagent
   - prompt: clear instructions with deliverables
3. Each subagent MUST use the Write tool to save findings to findings/findings_{{topic_hash}}.json relative to the working directory.
   - Include `entity_key` (normalized company identifier) at the top level.
   - For each source, include `source_domain` (domain extracted from URL).
4. Maintain an entity registry in `entities/entity_cards.json` (only for named entities in scope). Entry example:
   {{
     "entity_key": "normalized_key",
     "entity_type": "organization|person|product|paper|dataset|standard|event|other",
     "canonical_label": "Canonical Label",
     "variants": ["Alias A", "Alias B"],
     "identifiers": {{"doi": "10.1234/abcd", "orcid": "...", "wikidata_qid": "Q..."}},
     "allowed_domains": ["example.com", "news-site.com"],
     "disallowed_domains": [],
     "evidence_links": ["https://example.com/about"]
   }}
   - When working on an entity, add or merge its card (create `entities/` if missing). Derive allowed_domains from verified sources.
   - For broad topical queries (no specific entities), do NOT create entity cards. Optionally write `entities/topic_policy.json`:
     {{
       "topic_key": "topic_identifier",
       "allowed_source_types": ["peer_reviewed","standards","official_docs"],
       "domain_whitelist": ["doi.org","w3.org"],
       "criteria": ["requires DOI for quantitative claims"]
     }}
4. Preferred tools for web research: web_search for discovery, web_fetch for full content.
   - If these tools are unavailable, use Bash with curl (e.g., `curl -L <url>`) to fetch content to a temp file,
     then extract exact quotes and proceed.
4. Coordinate to avoid duplicate work. Prefer recent sources (last 2 years) unless historical context is essential.

STRICT VALIDATION:
- Do NOT fabricate URLs under any circumstances. Every URL must be fetched (via web_fetch or curl) before being recorded.
- Include exact quotes only from fetched content; omit a source if it cannot be fetched.
- If web tools and curl are both unavailable, set `sources: []` and write `research_notes` explaining offline limitations. Do not invent citations.

ENTITY DISAMBIGUATION:
- For named entities, define an `entity_key`, collect identifiers and allowed domains from verified sources.
- Drop any source whose domain conflicts with the entity being researched, or whose identifiers do not match.

Findings JSON schema (exact):
{{
  "topic": "specific_subtopic_name",
  "agent_id": "research_subagent_{{unique_id}}",
  "timestamp": "{{ISO_8601_timestamp}}",
  "entity_key": "normalized_entity_identifier",
  "findings": "Comprehensive summary of discoveries",
  "sources": [
    {{
      "url": "source_url",
      "title": "Source title",
      "timestamp": "access_timestamp",
      "relevant_quotes": ["specific quote 1", "specific quote 2"],
      "credibility_score": 0.95,
      "source_type": "peer_reviewed|government|institutional|news|blog|other",
      "source_domain": "example.com",
      "access_date": "YYYY-MM-DD"
    }}
  ],
  "confidence": 0.88
}}

Quality:
- Prioritize peer-reviewed and authoritative sources
- Include exact quotes for major claims
- Provide credibility scores and access dates

Begin coordination now.
"""
        # Progress monitor runs while research is ongoing
        stop_evt = asyncio.Event()
        monitor = asyncio.create_task(self._progress_monitor(stop_evt))
        try:
            # Trigger planning/delegation and drain the response stream
            await self._query_text(client, research_prompt)
        finally:
            stop_evt.set()
            with contextlib.suppress(Exception):
                await monitor
        # Print final summary
        fcount, scount = self._count_progress()
        print(f"{self._utc_ts()} 🗂️  Findings: {fcount} files | Sources: {scount}")

    async def _execute_synthesis_phase(self, client: "ClaudeSDKClient") -> str:
        """Synthesize all research findings into a coherent narrative."""
        synthesis_prompt = """
Synthesize all research findings from the workspace into a comprehensive report.

Process:
1. Read ALL findings/findings_*.json files
2. If present, read entities/entity_cards.json and only consider sources whose `source_domain` is in the entity's `allowed_domains` OR that match entity `identifiers`
3. If entity cards are absent and entities/topic_policy.json exists, prefer sources matching `allowed_source_types` and `domain_whitelist` and meeting `criteria`.
4. Analyze the research landscape and identify key themes
3. Create a coherent narrative that integrates all findings
4. Structure the report with clear sections and logical flow
5. Include specific claims that reference the research (but don't add citations yet)
6. Add a one-line summary: "Sources Used: N unique sources" computed by counting unique URLs across all findings.

Writing rules:
- Write the main synthesis to `synthesis_draft.md` (overwrite if exists).
- Optionally write one human-readable version to `reports/human_synthesis.md`.
- Do NOT write narrative .md files into `findings/`.

Report Structure:
- Executive Summary
- Key Findings (organized by theme/subtopic)
- Detailed Analysis
- Implications and Future Directions
- [Citations will be added in next phase]

Requirements:
- Maintain scientific accuracy and precision
- Use clear, engaging prose suitable for domain experts
- Flag any conflicting findings between sources
- Note areas where research is incomplete or uncertain
- Include specific claims that will need citation support

Create a comprehensive synthesis now.
"""

        synthesis = await self._query_text(client, synthesis_prompt)

        # Save synthesis for debugging/review
        synthesis_path = self.workspace / "synthesis_draft.md"
        synthesis_path.write_text(synthesis)

        return synthesis

    async def _execute_citation_phase(self, client: "ClaudeSDKClient", synthesis_text: str) -> str:
        """
        Apply citations using the local CitationEngine for exact-quote grounding.
        If no matches are found, fall back to a citations subagent pattern.
        """
        from citations import CitationEngine

        engine = CitationEngine(str(self.workspace))
        programmatic = engine.apply_citations(synthesis_text)

        if "## References" in programmatic:
            validated = self._normalize_references(programmatic)
            summary = engine.validate_citations(validated)
            validated += (
                f"\n\n---\n\nCitation Summary:\n"
                f"- Total citations added: {summary.total_citations}\n"
                f"- Total sources referenced: {summary.total_sources}\n"
                f"- Coverage (sentences with citations): {summary.coverage_percentage:.1f}%\n"
            )
            return validated

        # Fallback to a citations agent compatible prompt
        citation_prompt = f"""
You are the citations agent. Add citations to the synthesis text using the source data in findings/findings_*.json.

<synthesized_text>
{synthesis_text}
</synthesized_text>

Requirements:
- Insert inline citations [1], [2], etc. at appropriate places.
- Append a '## References' section listing full references in order of citation numbers.
- Do not modify text other than adding citations.

Output:
- Wrap the complete, cited text (including the References section) in <exact_text_with_citation> ... </exact_text_with_citation> tags.
"""
        agent_result = await self._query_text(client, citation_prompt)

        import re as _re
        m = _re.search(r"<exact_text_with_citation>([\s\S]*?)</exact_text_with_citation>", agent_result)
        if m:
            text = self._normalize_references(m.group(1))
            # Validate and append summary
            res = engine.validate_citations(text)
            text += (
                f"\n\n---\n\nCitation Summary:\n"
                f"- Total citations added: {res.total_citations}\n"
                f"- Total sources referenced: {res.total_sources}\n"
                f"- Coverage (sentences with citations): {res.coverage_percentage:.1f}%\n"
            )
            return text

        # Last resort
        return synthesis_text

    def _normalize_references(self, text: str) -> str:
        """Normalize References section to a consistent bullet list for readability."""
        try:
            if "## References" not in text:
                return text
            parts = text.split("## References", 1)
            head, tail = parts[0], parts[1]
            lines = tail.splitlines()
            new_lines: List[str] = []
            started = False
            for ln in lines:
                if not started and ln.strip() == "":
                    new_lines.append(ln)
                    continue
                started = True
                s = ln.rstrip()
                if s.startswith("[") and "]" in s and not s.lstrip().startswith("- "):
                    new_lines.append("- " + s)
                else:
                    new_lines.append(s)
            return head + "## References\n" + "\n".join(new_lines)
        except Exception:
            return text

    async def _query_text(self, client: "ClaudeSDKClient", prompt: str) -> str:
        """Send a prompt and collect assistant text content only (simple, robust)."""
        await client.query(prompt)
        parts: List[str] = []
        logs = self._ensure_logs_dir() / "messages.ndjson"
        async for msg in client.receive_response():
            # Always log raw message for audit
            try:
                logs.open("a").write(json.dumps(self._safe_json(msg), default=str) + "\n")
            except Exception:
                pass
            # Extract text in a minimal, safe way
            txt = self._extract_text_from_msg(msg)
            if txt:
                parts.append(txt)
        return "\n".join(parts).strip()

    def _extract_text_from_msg(self, msg: object) -> Optional[str]:
        """Extract assistant-visible text from SDK messages without complex branching."""
        # Plain string (skip repr of SDK objects)
        if isinstance(msg, str):
            if any(tok in msg for tok in ("SystemMessage(", "ToolUseBlock(", "ResultMessage(", "UserMessage(")):
                return None
            return msg
        # Objects with .text
        try:
            val = getattr(msg, "text")
            if isinstance(val, str):
                return val
        except Exception:
            pass
        # Objects with .content: list of blocks (TextBlock.text)
        try:
            content = getattr(msg, "content")
            if isinstance(content, list):
                texts = []
                for b in content:
                    t = getattr(b, "text", None)
                    if isinstance(t, str) and t:
                        texts.append(t)
                if texts:
                    return "\n".join(texts)
            elif isinstance(content, str):
                return content
        except Exception:
            pass
        # Dict-like
        if isinstance(msg, dict):
            if isinstance(msg.get("text"), str):
                return msg["text"]
            if isinstance(msg.get("content"), str):
                return msg["content"]
        return None

    def _safe_json(self, obj: object) -> dict:
        try:
            if isinstance(obj, dict):
                return obj
            # Best-effort serialization of SDK message types
            out = {"type": type(obj).__name__}
            for attr in ("text", "content", "name"):
                try:
                    v = getattr(obj, attr)
                    if isinstance(v, (str, list, dict)):
                        out[attr] = v
                except Exception:
                    continue
            return out
        except Exception:
            return {"repr": str(obj)}

    async def _check_tooling(self) -> Dict[str, bool]:
        """Send /tools and detect basic tool availability for visibility."""
        status = {"web_search": False, "web_fetch": False, "Bash": False}
        async with ClaudeSDKClient(options=self._build_client_options()) as client:
            txt = await self._query_text(client, "/tools")
            lower = txt.lower()
            status["web_search"] = ("web_search" in lower) or ("websearch" in lower)
            status["web_fetch"] = ("web_fetch" in lower) or ("webfetch" in lower)
            status["Bash"] = ("bash" in lower)
        # Record in logs
        try:
            (self._ensure_logs_dir() / "tooling.json").write_text(json.dumps(status, indent=2))
        except Exception:
            pass
        return status

    def _count_progress(self) -> Tuple[int, int]:
        fcount = 0
        scount = 0
        for file in (self.workspace / "findings").glob("findings_*.json"):
            fcount += 1
            try:
                data = json.loads(file.read_text())
                scount += len(data.get("sources", []))
            except Exception:
                pass
        return fcount, scount

    async def _progress_monitor(self, stop_evt: asyncio.Event, interval: float = 2.0) -> None:
        """Periodically print progress: findings and sources counts."""
        last = (-1, -1)
        while not stop_evt.is_set():
            fcount, scount = self._count_progress()
            if (fcount, scount) != last:
                print(f"{self._utc_ts()} ⏳ Progress — Findings: {fcount}, Sources: {scount}")
                last = (fcount, scount)
            try:
                await asyncio.wait_for(stop_evt.wait(), timeout=interval)
            except asyncio.TimeoutError:
                continue

    async def _await_findings(self, min_files: int = 1, idle_secs: float = 8.0, timeout_secs: float = 180.0) -> None:
        """Wait until findings exist and the directory is idle for a period, or timeout."""
        start = time.time()
        last_count = -1
        last_change = time.time()
        while True:
            fcount, _ = self._count_progress()
            now = time.time()
            if fcount != last_count:
                print(f"{self._utc_ts()} ⏳ Waiting for findings… current: {fcount}")
                last_change = now
                last_count = fcount
            if fcount >= min_files and (now - last_change) >= idle_secs:
                print(f"{self._utc_ts()} ✅ Findings ready: {fcount} files (idle {int(now - last_change)}s)")
                return
            if (now - start) > timeout_secs:
                print(f"{self._utc_ts()} ⚠️  Timed out waiting for findings after {int(now-start)}s; proceeding with what we have ({fcount}).")
                return
            await asyncio.sleep(1.5)

    def _postprocess_findings(self) -> None:
        """Clean up findings directory and disambiguate obvious entity/domain conflicts."""
        findings_dir = self.workspace / "findings"
        if not findings_dir.exists():
            return
        # Move any stray markdown files out of findings/
        for md in findings_dir.glob("*.md"):
            try:
                (self.workspace / md.name).write_text(md.read_text())
                md.unlink()
            except Exception:
                continue
        # Build a simple entity registry from findings (if fields are present)
        cards = {}
        for jf in findings_dir.glob("findings_*.json"):
            try:
                data = json.loads(jf.read_text())
                ek = data.get("entity_key")
                if not ek:
                    continue
                # Collect domains and sample links from sources
                domains = set()
                links = []
                for src in data.get("sources", []) or []:
                    dom = src.get("source_domain")
                    if not dom:
                        # Fallback derive domain from URL
                        url = src.get("url", "")
                        if "://" in url:
                            parts = url.split("/")
                            if len(parts) > 2:
                                dom = parts[2]
                    if dom:
                        domains.add(dom)
                    url = src.get("url")
                    if url and len(links) < 5:
                        links.append(url)
                if ek not in cards:
                    cards[ek] = {
                        "entity_key": ek,
                        "entity_type": data.get("entity_type"),
                        "canonical_label": data.get("canonical_label") or ek.replace("_", " ").title(),
                        "variants": data.get("variants") or [],
                        "identifiers": data.get("identifiers") or {},
                        "allowed_domains": sorted(list(domains)),
                        "disallowed_domains": [],
                        "evidence_links": links,
                    }
                else:
                    # Merge domains and evidence
                    cur = set(cards[ek].get("allowed_domains", []))
                    cards[ek]["allowed_domains"] = sorted(list(cur | domains))
                    # Merge identifiers if present
                    id_cur = cards[ek].get("identifiers") or {}
                    id_new = data.get("identifiers") or {}
                    id_cur.update({k: v for k, v in id_new.items() if v})
                    cards[ek]["identifiers"] = id_cur
                    cur_links = cards[ek].get("evidence_links", [])
                    for u in links:
                        if u not in cur_links and len(cur_links) < 10:
                            cur_links.append(u)
                    cards[ek]["evidence_links"] = cur_links
            except Exception:
                continue
        if cards:
            entities_dir = self.workspace / "entities"
            entities_dir.mkdir(exist_ok=True)
            out = {"entities": list(cards.values())}
            try:
                (entities_dir / "entity_cards.json").write_text(json.dumps(out, indent=2))
            except Exception:
                pass

    def _sanitize_text(self, text: str) -> str:
        """Drop any transcript artifacts that might have leaked into the report."""
        forbidden = ("SystemMessage(", "AssistantMessage(", "ToolUseBlock(", "ResultMessage(", "UserMessage(")
        out_lines: List[str] = []
        for ln in text.splitlines():
            if any(tok in ln for tok in forbidden):
                continue
            out_lines.append(ln)
        return "\n".join(out_lines)

    def _emit_phase1_summary(self) -> None:
        """Print a compact summary of Phase 1 with findings/sources, tool usage, and Task durations."""
        fcount, scount = self._count_progress()
        events_path = self._ensure_logs_dir() / "events.ndjson"
        task_durations: List[int] = []
        tool_counts: Dict[str, int] = {}
        if events_path.exists():
            for line in events_path.read_text().splitlines():
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                if ev.get("event") == "PreToolUse":
                    t = ev.get("tool") or "Unknown"
                    tool_counts[t] = tool_counts.get(t, 0) + 1
                if ev.get("event") == "PostToolUse" and ev.get("tool") == "Task":
                    d = ev.get("duration_ms")
                    if isinstance(d, int):
                        task_durations.append(d)

        print("\n" + f"{self._utc_ts()} — Phase 1 Summary —")
        print(f"{self._utc_ts()} Findings: {fcount}, Sources: {scount}")
        if task_durations:
            task_durations.sort()
            n = len(task_durations)
            avg = sum(task_durations) / n
            p95 = task_durations[max(0, int(n * 0.95) - 1)]
            top = list(reversed(sorted(task_durations)))[:3]
            print(f"{self._utc_ts()} Subagents (Task): {n} runs | avg {avg:.0f}ms | p95 {p95}ms | top {top}")
        else:
            print(f"{self._utc_ts()} Subagents (Task): no duration events captured")
        if tool_counts:
            top_tools = sorted(tool_counts.items(), key=lambda x: x[1], reverse=True)
            shown = ", ".join(f"{k}:{v}" for k, v in top_tools[:8])
            print(f"{self._utc_ts()} Tools used: {shown}")

    def get_research_status(self) -> ResearchMetrics:
        """
        Monitor research progress by examining workspace files.

        Returns:
            ResearchMetrics object with current status
        """
        findings_files = list((self.workspace / "findings").glob("findings_*.json"))

        total_sources = 0
        confidence_scores = []
        last_updated = None

        for file in findings_files:
            try:
                data = json.loads(file.read_text())
                sources = data.get("sources", [])
                total_sources += len(sources)

                # Track confidence scores
                if "confidence" in data:
                    confidence_scores.append(data["confidence"])

                # Track last updated timestamp
                timestamp = data.get("timestamp")
                if timestamp and (not last_updated or timestamp > last_updated):
                    last_updated = timestamp

            except (json.JSONDecodeError, KeyError) as e:
                print(f"{self._utc_ts()} Warning: Could not process {file}: {e}")
                continue

        # Calculate duration
        duration = 0.0
        if self.start_time:
            duration = (datetime.now() - self.start_time).total_seconds()

        return ResearchMetrics(
            active_research_areas=len(findings_files),
            total_sources=total_sources,
            last_updated=last_updated,
            confidence_avg=sum(confidence_scores) / len(confidence_scores) if confidence_scores else 0.0,
            research_duration_seconds=duration
        )

    def list_findings(self) -> List[Dict]:
        """
        List all research findings with summary information.

        Returns:
            List of finding summaries
        """
        findings = []

        for file in (self.workspace / "findings").glob("findings_*.json"):
            try:
                data = json.loads(file.read_text())
                summary = {
                    "file": file.name,
                    "topic": data.get("topic", "Unknown"),
                    "agent_id": data.get("agent_id", "Unknown"),
                    "source_count": len(data.get("sources", [])),
                    "confidence": data.get("confidence", 0.0),
                    "timestamp": data.get("timestamp", "Unknown")
                }
                findings.append(summary)
            except (json.JSONDecodeError, KeyError) as e:
                print(f"{self._utc_ts()} Warning: Could not process {file}: {e}")
                continue

        return sorted(findings, key=lambda x: x["timestamp"], reverse=True)

    def clear_workspace(self, confirm: bool = False) -> None:
        """
        Clear the research workspace (use with caution).

        Args:
            confirm: Must be True to actually clear workspace
        """
        if not confirm:
            print(f"{self._utc_ts()} ❌ Must set confirm=True to clear workspace")
            return

        import shutil

        for subdir in ["findings", "reports"]:
            subdir_path = self.workspace / subdir
            if subdir_path.exists():
                shutil.rmtree(subdir_path)
                subdir_path.mkdir()

        # Remove synthesis and error files
        draft = self.workspace / "synthesis_draft.md"
        if draft.exists():
            draft.unlink()
        for file in self.workspace.glob("error_*.txt"):
            file.unlink()

        print(f"{self._utc_ts()} 🗑️  Workspace cleared: {self.workspace}")

    def _debug_workspace(self) -> str:
        """Generate debug information about current workspace state."""
        debug_info = [f"Workspace: {self.workspace}"]

        for subdir in ["findings", "reports", "agents"]:
            subdir_path = self.workspace / subdir
            if subdir_path.exists():
                files = list(subdir_path.glob("*"))
                debug_info.append(f"{subdir}/: {len(files)} files")
                for file in files[:5]:  # Show first 5 files
                    debug_info.append(f"  - {file.name}")
                if len(files) > 5:
                    debug_info.append(f"  - ... and {len(files) - 5} more")
            else:
                debug_info.append(f"{subdir}/: missing")

        return "\n".join(debug_info)


# Utility functions for common operations
async def quick_research(query: str, workspace_dir: str = None) -> str:
    """
    Convenience function for one-off research queries.

    Args:
        query: Research question
        workspace_dir: Optional custom workspace directory

    Returns:
        Final research report
    """
    if workspace_dir is None:
        # Create unique workspace based on query hash
        query_hash = hashlib.md5(query.encode()).hexdigest()[:8]
        workspace_dir = f"./research_{query_hash}"

    system = ResearchSystem(workspace_dir)
    return await system.research(query)


async def simple_research(query: str) -> str:
    """Simpler one-pass research: query in, markdown out. Writes to reports/simple_report_*.md."""
    ws = os.getenv("RESEARCH_WORKSPACE") or f"./research_{hashlib.md5(query.encode()).hexdigest()[:8]}"
    system = ResearchSystem(ws)
    prompt = f"""
Research the following topic and produce a single, well-structured markdown report with clear sections (Executive Summary, Findings, Analysis, Implications). Use web tools and subagents if helpful. Do not include system or tool logs, only the final report text.

Topic: {query}
"""
    async with ClaudeSDKClient(options=system._build_client_options()) as client:
        text = await system._query_text(client, prompt)
    text = system._sanitize_text(text)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = Path(ws) / "reports" / f"simple_report_{ts}.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(text)
    print(f"{ResearchSystem._utc_ts()} ✅ Simple report saved to: {out}")
    return text

async def compare_research(queries: List[str], workspace_dir: str = "./comparative_research") -> str:
    """
    Perform comparative research across multiple related queries.

    Args:
        queries: List of research questions to compare
        workspace_dir: Workspace for comparative analysis

    Returns:
        Comparative analysis report
    """
    # Research each query in its own isolated workspace to avoid cross-contamination
    results = []
    for i, query in enumerate(queries):
        print("\n" + f"{self._utc_ts()} 🔍 Researching query {i+1}/{len(queries)}: {query}")
        q_workspace = Path(workspace_dir) / f"q_{i+1}"
        q_system = ResearchSystem(str(q_workspace))
        result = await q_system.research(query)
        results.append({"query": query, "result": result})

    # Generate comparative analysis
    comparison_prompt = f"""
Perform a comparative analysis of these research results:

{json.dumps(results, indent=2)}

Create a comprehensive comparison that:
1. Identifies common themes and differences
2. Highlights conflicting findings
3. Synthesizes insights across all queries
4. Notes research gaps and future directions
5. Provides a unified conclusion

Structure as a formal comparative research report.
"""

    # Use a lightweight client in the root comparative workspace
    async with ClaudeSDKClient(options=ClaudeCodeOptions(cwd=str(workspace_dir))) as client:
        comparison = await ResearchSystem(str(workspace_dir))._query_text(client, comparison_prompt)

    # Save comparison report
    comparison_path = Path(workspace_dir) / "reports" / "comparative_analysis.md"
    comparison_path.write_text(comparison)

    return comparison


if __name__ == "__main__":
    import sys

    async def main():
        if len(sys.argv) < 2:
            print(f"{ResearchSystem._utc_ts()} Usage: python research_system.py [--simple|--cite] 'Your research query here'")
            print(f"{ResearchSystem._utc_ts()} Example: python research_system.py 'What are the latest developments in quantum computing?'")
            return

        args = sys.argv[1:]
        mode = os.getenv("RESEARCH_MODE", "").lower()
        simple = False
        cite_only = False
        if args and args[0] in ("--simple", "--cite"):
            if args[0] == "--simple":
                simple = True
            elif args[0] == "--cite":
                cite_only = True
            args = args[1:]
        if mode == "simple":
            simple = True
        elif mode == "cite":
            cite_only = True

        query = " ".join(args)

        if cite_only:
            # Apply citations only to existing synthesis_draft.md
            ws = os.getenv("RESEARCH_WORKSPACE") or "./research_workspace"
            system = ResearchSystem(ws)
            draft = Path(ws) / "synthesis_draft.md"
            if not draft.exists():
                print(f"{ResearchSystem._utc_ts()} ❌ No synthesis_draft.md found in {ws}")
                return
            text = draft.read_text()
            async with ClaudeSDKClient(options=system._build_client_options()) as client:
                final = await system._execute_citation_phase(client, text)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            out = Path(ws) / "reports" / f"research_report_{ts}.md"
            out.write_text(final)
            print(f"{ResearchSystem._utc_ts()} ✅ Citation-only report saved to: {out}")
            return

        if simple:
            text = await simple_research(query)
            print("\n" + f"{ResearchSystem._utc_ts()} " + "="*64)
            print(f"{ResearchSystem._utc_ts()} FINAL REPORT (SIMPLE MODE)")
            print(f"{ResearchSystem._utc_ts()} " + "="*64)
            print(text)
            return

        result = await quick_research(query)
        print("\n" + f"{ResearchSystem._utc_ts()} " + "="*64)
        print(f"{ResearchSystem._utc_ts()} FINAL RESEARCH REPORT")
        print(f"{ResearchSystem._utc_ts()} " + "="*64)
        print(result)

    asyncio.run(main())
