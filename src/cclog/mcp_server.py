"""MCP server exposing cclog session search/retrieval to Claude Code."""

import json
import time
from datetime import date, datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from cclog.config import load_config
from cclog.digest import build_daily_digest, format_digest_markdown, parse_date_arg
from cclog.indexer import Indexer
from cclog.models import Session

mcp = FastMCP("cclog", instructions="Search and retrieve Claude Code session history from the cclog database.")

_last_indexed: float = 0.0
_FRESHNESS_TTL = 300  # 5 minutes


def _get_indexer(ensure_fresh: bool = True) -> tuple[Indexer, bool]:
    """Create an Indexer instance, auto-refreshing if stale.

    Returns (indexer, was_refreshed).
    """
    global _last_indexed
    config = load_config()
    indexer = Indexer(config)
    was_refreshed = False

    if ensure_fresh and (time.time() - _last_indexed) > _FRESHNESS_TTL:
        indexer.build()
        _last_indexed = time.time()
        was_refreshed = True

    return indexer, was_refreshed


def _session_to_dict(s: Session, brief: bool = True) -> dict:
    """Convert a Session to a JSON-serializable dict."""
    d = {
        "session_id": s.session_id[:8],
        "full_id": s.session_id,
        "date": s.start_time.strftime("%Y-%m-%d") if s.start_time else None,
        "time": s.start_time.strftime("%H:%M") if s.start_time else None,
        "project": s.project,
        "duration_minutes": s.duration_minutes,
        "title": s.title,
        "summary": s.summary,
        "category": s.category,
    }
    if brief:
        d["tools_used"] = s.tools_used[:8] if s.tools_used else []
        d["files_modified_count"] = len(s.files_modified) if s.files_modified else 0
    else:
        d["project_path"] = s.project_path
        d["end_time"] = s.end_time.isoformat() if s.end_time else None
        d["message_count"] = s.message_count
        d["user_message_count"] = s.user_message_count
        d["model"] = s.model
        d["tokens"] = {
            "input": s.tokens.input_tokens,
            "output": s.tokens.output_tokens,
            "cache_read": s.tokens.cache_read_tokens,
            "cache_creation": s.tokens.cache_creation_tokens,
            "total": s.tokens.total,
        }
        d["tools_used"] = s.tools_used
        d["files_modified"] = s.files_modified
        d["outcomes"] = s.outcomes
        d["learnings"] = s.learnings
        d["git_branch"] = s.git_branch
        d["slug"] = s.slug
    return d


@mcp.tool()
def search_sessions(
    query: str | None = None,
    date: str | None = None,
    since: str | None = None,
    category: str | None = None,
    limit: int = 10,
) -> str:
    """Search past Claude Code sessions.

    Args:
        query: Project name or keyword to match in title/summary (optional).
        date: Filter by date in YYYY-MM-DD format (optional).
        since: Show sessions after this ISO date (optional).
        category: Filter by category (optional).
        limit: Maximum number of results (default 10).

    Returns:
        JSON list of matching sessions with key fields.
    """
    try:
        indexer, was_refreshed = _get_indexer()
        try:
            # Use query as project filter if provided
            sessions = indexer.list_sessions(
                project=query,
                date=date,
                since=since,
                category=category,
                limit=limit,
            )

            # If query provided, also do text matching on title/summary
            if query and not sessions:
                # Fallback: search all and filter by title/summary
                all_sessions = indexer.list_sessions(limit=500)
                q_lower = query.lower()
                sessions = [
                    s for s in all_sessions
                    if (s.title and q_lower in s.title.lower())
                    or (s.summary and q_lower in s.summary.lower())
                ][:limit]

            results = [_session_to_dict(s, brief=True) for s in sessions]
            total = indexer.conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            output = {
                "_meta": {
                    "db_last_indexed": indexer.get_last_indexed_at(),
                    "total_sessions": total,
                    "auto_refreshed": was_refreshed,
                },
                "sessions": results,
            }
            return json.dumps(output, ensure_ascii=False, indent=2)
        finally:
            indexer.close()
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def get_session_detail(session_id: str) -> str:
    """Get full details of a specific Claude Code session.

    Args:
        session_id: Session ID (prefix match supported, e.g. first 8 chars).

    Returns:
        JSON with all session fields including summary, outcomes, learnings, tokens.
    """
    try:
        indexer, _ = _get_indexer()
        try:
            session = indexer.get_session(session_id)
            if not session:
                return json.dumps({"error": f"Session not found: {session_id}"})
            return json.dumps(_session_to_dict(session, brief=False), ensure_ascii=False, indent=2)
        finally:
            indexer.close()
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def get_session_stats() -> str:
    """Get overall cclog statistics.

    Returns:
        JSON with total sessions, projects, hours, tokens, date range.
    """
    try:
        indexer, _ = _get_indexer()
        try:
            stats = indexer.get_stats()
            total_minutes = stats.get("total_minutes") or 0
            result = {
                "total_sessions": stats["total_sessions"],
                "total_projects": stats["total_projects"],
                "total_hours": round(total_minutes / 60, 1),
                "total_input_tokens": stats.get("total_input_tokens") or 0,
                "total_output_tokens": stats.get("total_output_tokens") or 0,
                "summarized_sessions": stats.get("summarized_sessions") or 0,
                "earliest_session": stats.get("earliest_session"),
                "latest_session": stats.get("latest_session"),
            }
            return json.dumps(result, ensure_ascii=False, indent=2)
        finally:
            indexer.close()
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def get_daily_digest(date: str | None = None) -> str:
    """Get a formatted daily summary of Claude Code sessions.

    Args:
        date: Date in YYYY-MM-DD format (defaults to today).

    Returns:
        Markdown formatted daily digest.
    """
    try:
        indexer, _ = _get_indexer()
        try:
            target = parse_date_arg(date) if date else parse_date_arg("today")
            digest = build_daily_digest(indexer, target)
            if not digest.sessions:
                return f"No sessions found for {target.isoformat()}."
            return format_digest_markdown(digest)
        finally:
            indexer.close()
    except Exception as e:
        return json.dumps({"error": str(e)})


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from markdown text. Returns (metadata, content)."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta = {}
    for line in parts[1].strip().splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    content = parts[2].strip()
    return meta, content


def _dir_to_project(dirname: str) -> str:
    """Convert directory name like '-Users-tianli-Dev-cclog' to 'Dev/cclog'."""
    prefix = "-Users-tianli-"
    name = dirname
    if name.startswith(prefix):
        name = name[len(prefix):]
    return name.replace("-", "/")


@mcp.tool()
def search_memories(
    query: str,
    type: str | None = None,
    project: str | None = None,
) -> str:
    """Search memory files across all Claude Code projects.

    Memory files contain persistent knowledge, user preferences, project notes,
    and feedback accumulated across Claude Code sessions.

    Args:
        query: Keyword to search in memory content, name, or description (case-insensitive).
        type: Filter by memory type: "user", "feedback", "project", "reference" (optional).
        project: Filter by project name, substring match on directory path (optional).

    Returns:
        JSON list of matching memories sorted by relevance.
    """
    try:
        base = Path.home() / ".claude" / "projects"
        if not base.exists():
            return json.dumps([])

        q = query.lower()
        results = []

        for memory_dir in base.glob("*/memory"):
            project_dir = memory_dir.parent.name
            project_name = _dir_to_project(project_dir)

            # Project filter
            if project and project.lower() not in project_name.lower():
                continue

            for md_file in memory_dir.glob("*.md"):
                # Skip MEMORY.md index files
                if md_file.name == "MEMORY.md":
                    continue

                try:
                    text = md_file.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue

                meta, content = _parse_frontmatter(text)

                # Type filter
                if type and meta.get("type", "").lower() != type.lower():
                    continue

                # Compute relevance score
                name = meta.get("name", "")
                description = meta.get("description", "")
                score = 0
                if q in name.lower():
                    score += 3
                if q in description.lower():
                    score += 2
                if q in content.lower():
                    score += 1

                if score == 0:
                    continue

                results.append({
                    "file_path": str(md_file),
                    "project": project_name,
                    "name": name,
                    "description": description,
                    "type": meta.get("type", ""),
                    "content": content,
                    "relevance": score,
                })

        # Sort by relevance descending, then by name
        results.sort(key=lambda r: (-r["relevance"], r["name"]))
        return json.dumps(results[:10], ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def search_knowledge(
    query: str,
    sources: str | None = None,
) -> str:
    """Search across all CC knowledge stores: memories, skill tracker, tasks, and feedback logs.

    Unified search that queries 4 data sources simultaneously and returns
    ranked results. Use this when you need to find information that might
    be in any of the CC knowledge stores.

    Args:
        query: Keyword to search across all sources (case-insensitive).
        sources: Comma-separated source filter: "memory,skills,tasks,reflect" (optional, defaults to all).

    Returns:
        JSON list of matching results sorted by relevance, each with source, title, content, date.
    """
    try:
        from cclog.knowledge import search_knowledge as _search

        source_list = [s.strip() for s in sources.split(",")] if sources else None
        results = _search(query, source_list)
        return json.dumps(results, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def get_evolution_status() -> str:
    """Get CC ecosystem health report: stale memories, unused commands, matured skill candidates.

    Use this to check the overall health of the Claude Code configuration ecosystem.
    Returns actionable items: memories that need verification, commands with zero usage,
    and skill candidates ready for promotion.

    Returns:
        JSON with stale_memories, unused_commands, matured_candidates, memory_stats.
    """
    try:
        from cclog.knowledge import get_evolution_status as _status

        result = _status()
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


if __name__ == "__main__":
    mcp.run()
