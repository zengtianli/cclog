"""MCP server exposing cclog session search/retrieval to Claude Code."""

import json
from datetime import date, datetime

from mcp.server.fastmcp import FastMCP

from cclog.config import load_config
from cclog.digest import build_daily_digest, format_digest_markdown, parse_date_arg
from cclog.indexer import Indexer
from cclog.models import Session

mcp = FastMCP("cclog", instructions="Search and retrieve Claude Code session history from the cclog database.")


def _get_indexer() -> Indexer:
    """Create an Indexer instance from default config."""
    config = load_config()
    return Indexer(config)


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
        indexer = _get_indexer()
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
            return json.dumps(results, ensure_ascii=False, indent=2)
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
        indexer = _get_indexer()
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
        indexer = _get_indexer()
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
        indexer = _get_indexer()
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


if __name__ == "__main__":
    mcp.run()
