"""Stream-parse Claude Code session JSONL files."""

import json
from datetime import datetime, timezone
from pathlib import Path

from cclog.models import Session, TokenUsage


def parse_metadata(path: Path) -> Session | None:
    """Fast metadata extraction from a session JSONL file.

    Reads all lines but only extracts lightweight metadata:
    session_id, cwd, timestamps, message counts, model, token totals, tools, slug.

    Skips heavy content: thinking blocks, tool inputs, file-history-snapshot bodies.
    """
    session_id = None
    project_path = ""
    model = None
    git_branch = None
    slug = None
    start_time = None
    end_time = None
    message_count = 0
    user_message_count = 0
    title = None
    tokens = TokenUsage()
    tools_used: set[str] = set()
    files_modified: set[str] = set()

    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                entry_type = entry.get("type")

                # Skip heavy types entirely
                if entry_type in ("file-history-snapshot", "progress", "queue-operation", "last-prompt"):
                    continue

                # Track timestamps
                ts_str = entry.get("timestamp")
                if ts_str:
                    ts = _parse_timestamp(ts_str)
                    if ts:
                        if start_time is None or ts < start_time:
                            start_time = ts
                        if end_time is None or ts > end_time:
                            end_time = ts

                # Extract session metadata from first user message
                if entry_type == "user" and session_id is None:
                    session_id = entry.get("sessionId")
                    project_path = entry.get("cwd", "")
                    git_branch = entry.get("gitBranch")

                if entry_type == "user":
                    message_count += 1
                    user_message_count += 1

                    # First user message text becomes title
                    if title is None:
                        title = _extract_user_text(entry)
                        if title and len(title) > 100:
                            title = title[:100] + "..."

                elif entry_type == "assistant":
                    message_count += 1

                    # Extract slug
                    if slug is None:
                        slug = entry.get("slug")

                    # Extract model
                    msg = entry.get("message", {})
                    if model is None:
                        model = msg.get("model")

                    # Accumulate token usage
                    usage = msg.get("usage", {})
                    tokens.input_tokens += usage.get("input_tokens", 0)
                    tokens.output_tokens += usage.get("output_tokens", 0)
                    tokens.cache_read_tokens += usage.get("cache_read_input_tokens", 0)
                    tokens.cache_creation_tokens += usage.get("cache_creation_input_tokens", 0)

                    # Extract tool names and file paths
                    content = msg.get("content", [])
                    if isinstance(content, list):
                        for item in content:
                            if not isinstance(item, dict):
                                continue
                            if item.get("type") == "tool_use":
                                tool_name = item.get("name", "")
                                if tool_name:
                                    tools_used.add(tool_name)
                                # Track file modifications
                                inp = item.get("input", {})
                                if isinstance(inp, dict):
                                    fp = inp.get("file_path", "")
                                    if fp and tool_name in ("Edit", "Write"):
                                        files_modified.add(fp)

                elif entry_type == "system":
                    message_count += 1

    except OSError:
        return None

    if session_id is None:
        return None

    # Compute duration
    duration = 0
    if start_time and end_time:
        duration = int((end_time - start_time).total_seconds() / 60)

    # Derive human-readable project name from cwd
    project = _derive_project_name(project_path)

    stat = path.stat()

    return Session(
        session_id=session_id,
        project=project,
        project_path=project_path,
        start_time=start_time or datetime.now(timezone.utc),
        end_time=end_time,
        duration_minutes=duration,
        message_count=message_count,
        user_message_count=user_message_count,
        model=model,
        tokens=tokens,
        tools_used=sorted(tools_used),
        files_modified=sorted(files_modified),
        title=title,
        slug=slug,
        git_branch=git_branch,
        file_path=path,
        file_size_kb=stat.st_size // 1024,
        mtime=stat.st_mtime,
    )


def parse_conversation_text(path: Path, max_chars: int = 50000) -> str:
    """Extract conversation text suitable for LLM summarization.

    Returns user prompts and assistant text responses.
    Skips: thinking, tool_use inputs, signatures, file-history-snapshot, progress.
    Truncates if total exceeds max_chars.
    """
    parts: list[str] = []
    total_chars = 0

    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if total_chars >= max_chars:
                    break

                line = line.strip()
                if not line:
                    continue

                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                entry_type = entry.get("type")

                if entry_type == "user":
                    text = _extract_user_text(entry)
                    if text:
                        chunk = f"[User]: {text}\n"
                        parts.append(chunk)
                        total_chars += len(chunk)

                elif entry_type == "assistant":
                    msg = entry.get("message", {})
                    content = msg.get("content", [])
                    if isinstance(content, list):
                        for item in content:
                            if not isinstance(item, dict):
                                continue
                            if item.get("type") == "text":
                                text = item.get("text", "")
                                if text:
                                    chunk = f"[Assistant]: {text}\n"
                                    parts.append(chunk)
                                    total_chars += len(chunk)
                            elif item.get("type") == "tool_use":
                                name = item.get("name", "")
                                inp = item.get("input", {})
                                fp = inp.get("file_path", "") if isinstance(inp, dict) else ""
                                if name:
                                    chunk = f"[Tool: {name}] {fp}\n"
                                    parts.append(chunk)
                                    total_chars += len(chunk)

    except OSError:
        pass

    return "".join(parts)


def _extract_user_text(entry: dict) -> str | None:
    """Extract plain text from a user message entry."""
    msg = entry.get("message", {})
    content = msg.get("content", "")

    if isinstance(content, str):
        return content.strip() if content.strip() else None

    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                t = item.get("text", "").strip()
                if t:
                    texts.append(t)
        return "\n".join(texts) if texts else None

    return None


def _parse_timestamp(ts_str: str) -> datetime | None:
    """Parse ISO 8601 timestamp string."""
    if isinstance(ts_str, (int, float)):
        # Unix timestamp in milliseconds
        return datetime.fromtimestamp(ts_str / 1000, tz=timezone.utc)

    try:
        # Python 3.11+ handles ISO 8601 with fromisoformat
        # Replace trailing Z with +00:00 for compatibility
        if ts_str.endswith("Z"):
            ts_str = ts_str[:-1] + "+00:00"
        return datetime.fromisoformat(ts_str)
    except (ValueError, TypeError):
        return None


def _derive_project_name(cwd: str) -> str:
    """Derive a short project name from the cwd path.

    Example: "/Users/tianli/Dev/tools/scripts" -> "Dev/scripts"
    """
    if not cwd:
        return "unknown"

    home = str(Path.home())
    if cwd.startswith(home):
        relative = cwd[len(home) :].lstrip("/")
        return relative if relative else "~"

    return cwd
