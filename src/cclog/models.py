"""Data models for cclog."""

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path


@dataclass
class TokenUsage:
    """Accumulated token usage for a session."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class Session:
    """A single Claude Code session."""

    session_id: str
    project: str  # Human-readable project name (e.g., "Dev/scripts")
    project_path: str  # Full cwd path
    start_time: datetime
    file_path: Path

    # Optional metadata
    end_time: datetime | None = None
    duration_minutes: int = 0
    message_count: int = 0
    user_message_count: int = 0
    model: str | None = None
    tokens: TokenUsage = field(default_factory=TokenUsage)
    tools_used: list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    title: str | None = None
    slug: str | None = None
    git_branch: str | None = None
    file_size_kb: int = 0

    # AI-generated (nullable until summarized)
    summary: str | None = None
    category: str | None = None
    outcomes: str | None = None
    learnings: list[str] = field(default_factory=list)

    # Index tracking
    mtime: float = 0.0


@dataclass
class DailyDigest:
    """Aggregated view of sessions for a single day."""

    date: date
    sessions: list[Session] = field(default_factory=list)

    @property
    def total_duration_minutes(self) -> int:
        return sum(s.duration_minutes for s in self.sessions)

    @property
    def total_tokens(self) -> TokenUsage:
        t = TokenUsage()
        for s in self.sessions:
            t.input_tokens += s.tokens.input_tokens
            t.output_tokens += s.tokens.output_tokens
            t.cache_read_tokens += s.tokens.cache_read_tokens
            t.cache_creation_tokens += s.tokens.cache_creation_tokens
        return t

    @property
    def projects_touched(self) -> list[str]:
        seen = []
        for s in self.sessions:
            if s.project not in seen:
                seen.append(s.project)
        return seen

    # AI-generated
    summary: str | None = None
