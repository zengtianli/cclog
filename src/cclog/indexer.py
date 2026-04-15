"""Build and maintain a SQLite index of all Claude Code sessions."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from cclog.config import Config
from cclog.models import Session, TokenUsage
from cclog.parser import parse_metadata
from cclog.scanner import ScannedFile, scan_projects

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    project TEXT,
    project_path TEXT,
    start_time TEXT,
    end_time TEXT,
    duration_minutes INTEGER,
    message_count INTEGER,
    user_message_count INTEGER,
    model TEXT,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cache_read_tokens INTEGER DEFAULT 0,
    cache_creation_tokens INTEGER DEFAULT 0,
    tools_used TEXT,
    files_modified TEXT,
    title TEXT,
    summary TEXT,
    category TEXT,
    outcomes TEXT,
    learnings TEXT,
    slug TEXT,
    git_branch TEXT,
    file_path TEXT,
    file_size_kb INTEGER,
    mtime REAL
);

CREATE INDEX IF NOT EXISTS idx_start_time ON sessions(start_time);
CREATE INDEX IF NOT EXISTS idx_project ON sessions(project);
CREATE INDEX IF NOT EXISTS idx_category ON sessions(category);

CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


class Indexer:
    """Manages the SQLite session index."""

    def __init__(self, config: Config):
        self.config = config
        self.config.cache_dir.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(config.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._ensure_schema()

    def _ensure_schema(self):
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self):
        self.conn.close()

    # --- Build / Update ---

    def build(self, full: bool = False) -> tuple[int, int, int]:
        """Scan, parse, and index all sessions.

        Returns (total_scanned, new_indexed, skipped).
        """
        if full:
            self.conn.execute("DELETE FROM sessions")
            self.conn.commit()

        # 1. Bootstrap from session_index.json if DB is empty
        bootstrapped = self._bootstrap_from_session_index()

        # 2. Scan filesystem
        scanned = scan_projects(self.config.projects_dir)

        # 3. Get existing entries for incremental check
        existing = self._get_existing_mtimes()

        new_count = 0
        skip_count = 0

        for sf in scanned:
            sid = sf.path.stem  # session UUID is the filename without .jsonl

            # Skip if already indexed with same mtime
            if not full and sid in existing:
                stored_mtime = existing[sid]
                if abs(stored_mtime - sf.mtime) < 0.01:
                    skip_count += 1
                    continue

            # Parse metadata
            session = parse_metadata(sf.path)
            if session is None:
                continue

            self._upsert_session(session, preserve_summary=True)
            new_count += 1

        self.conn.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES ('last_indexed_at', ?)",
            (datetime.now(timezone.utc).isoformat(),),
        )
        self.conn.commit()
        return len(scanned), new_count + bootstrapped, skip_count

    def _bootstrap_from_session_index(self) -> int:
        """Import existing summaries from ~/.claude/session_index.json."""
        index_path = self.config.session_index_path
        if not index_path.exists():
            return 0

        # Only bootstrap if DB is empty or has no summaries
        count = self.conn.execute("SELECT COUNT(*) FROM sessions WHERE summary IS NOT NULL").fetchone()[0]
        if count > 0:
            return 0

        try:
            with open(index_path, "r", encoding="utf-8") as f:
                entries = json.load(f)
        except (json.JSONDecodeError, OSError):
            return 0

        imported = 0
        for entry in entries:
            sid = entry.get("session_id")
            if not sid:
                continue

            # Check if already exists
            row = self.conn.execute("SELECT session_id FROM sessions WHERE session_id = ?", (sid,)).fetchone()
            if row:
                # Update summary fields only
                self.conn.execute(
                    """UPDATE sessions SET summary = ?, category = ?, outcomes = ?
                       WHERE session_id = ? AND summary IS NULL""",
                    (entry.get("summary"), entry.get("category"), entry.get("outcomes"), sid),
                )
            else:
                # Insert minimal record from index
                self.conn.execute(
                    """INSERT OR IGNORE INTO sessions
                       (session_id, project, project_path, start_time, duration_minutes,
                        message_count, title, file_size_kb, summary, category, outcomes)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        sid,
                        _decode_project_name(entry.get("project", "")),
                        entry.get("cwd", ""),
                        entry.get("start_time"),
                        entry.get("duration_minutes", 0),
                        entry.get("message_count", 0),
                        entry.get("title"),
                        entry.get("file_size_kb", 0),
                        entry.get("summary"),
                        entry.get("category"),
                        entry.get("outcomes"),
                    ),
                )
                imported += 1

        self.conn.commit()
        return imported

    def _get_existing_mtimes(self) -> dict[str, float]:
        """Get session_id -> mtime mapping for incremental check."""
        rows = self.conn.execute("SELECT session_id, mtime FROM sessions WHERE mtime IS NOT NULL").fetchall()
        return {row["session_id"]: row["mtime"] for row in rows}

    def _upsert_session(self, s: Session, preserve_summary: bool = False):
        """Insert or update a session record."""
        if preserve_summary:
            # Check if there's an existing summary we should keep
            row = self.conn.execute(
                "SELECT summary, category, outcomes, learnings FROM sessions WHERE session_id = ?",
                (s.session_id,),
            ).fetchone()
            if row and row["summary"]:
                s.summary = row["summary"]
                s.category = row["category"]
                s.outcomes = row["outcomes"]
                learnings_json = row["learnings"]
                if learnings_json:
                    try:
                        s.learnings = json.loads(learnings_json)
                    except json.JSONDecodeError:
                        pass

        self.conn.execute(
            """INSERT OR REPLACE INTO sessions
               (session_id, project, project_path, start_time, end_time,
                duration_minutes, message_count, user_message_count, model,
                input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens,
                tools_used, files_modified, title, summary, category, outcomes, learnings,
                slug, git_branch, file_path, file_size_kb, mtime)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                s.session_id,
                s.project,
                s.project_path,
                s.start_time.isoformat() if s.start_time else None,
                s.end_time.isoformat() if s.end_time else None,
                s.duration_minutes,
                s.message_count,
                s.user_message_count,
                s.model,
                s.tokens.input_tokens,
                s.tokens.output_tokens,
                s.tokens.cache_read_tokens,
                s.tokens.cache_creation_tokens,
                json.dumps(s.tools_used),
                json.dumps(s.files_modified),
                s.title,
                s.summary,
                s.category,
                s.outcomes,
                json.dumps(s.learnings) if s.learnings else None,
                s.slug,
                s.git_branch,
                str(s.file_path),
                s.file_size_kb,
                s.mtime,
            ),
        )

    def get_last_indexed_at(self) -> str | None:
        """Return ISO timestamp of the last successful index run."""
        row = self.conn.execute(
            "SELECT value FROM metadata WHERE key = 'last_indexed_at'"
        ).fetchone()
        return row[0] if row else None

    # --- Query ---

    def list_sessions(
        self,
        project: str | None = None,
        date: str | None = None,
        since: str | None = None,
        category: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Session]:
        """Query sessions with optional filters."""
        conditions = []
        params: list = []

        if project:
            conditions.append("project LIKE ?")
            params.append(f"%{project}%")

        if date:
            conditions.append("start_time LIKE ?")
            params.append(f"{date}%")

        if since:
            conditions.append("start_time >= ?")
            params.append(since)

        if category:
            conditions.append("category = ?")
            params.append(category)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"SELECT * FROM sessions {where} ORDER BY start_time DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = self.conn.execute(query, params).fetchall()
        return [_row_to_session(row) for row in rows]

    def get_session(self, session_id: str) -> Session | None:
        """Get a single session by ID (supports prefix match)."""
        # Try exact match first
        row = self.conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        if row:
            return _row_to_session(row)

        # Try prefix match
        row = self.conn.execute(
            "SELECT * FROM sessions WHERE session_id LIKE ? LIMIT 1", (f"{session_id}%",)
        ).fetchone()
        if row:
            return _row_to_session(row)

        return None

    def get_stats(self) -> dict:
        """Get aggregate statistics."""
        row = self.conn.execute(
            """SELECT
                COUNT(*) as total_sessions,
                COUNT(DISTINCT project) as total_projects,
                SUM(duration_minutes) as total_minutes,
                SUM(input_tokens) as total_input_tokens,
                SUM(output_tokens) as total_output_tokens,
                COUNT(CASE WHEN summary IS NOT NULL THEN 1 END) as summarized_sessions,
                MIN(start_time) as earliest_session,
                MAX(start_time) as latest_session
            FROM sessions"""
        ).fetchone()
        return dict(row)

    def get_sessions_for_date(self, date_str: str) -> list[Session]:
        """Get all sessions for a specific date."""
        return self.list_sessions(date=date_str, limit=1000)

    def get_unsummarized_sessions(self, since: str | None = None, limit: int = 100) -> list[Session]:
        """Get sessions that haven't been summarized yet."""
        conditions = ["summary IS NULL"]
        params: list = []

        if since:
            conditions.append("start_time >= ?")
            params.append(since)

        where = f"WHERE {' AND '.join(conditions)}"
        query = f"SELECT * FROM sessions {where} ORDER BY start_time DESC LIMIT ?"
        params.append(limit)

        rows = self.conn.execute(query, params).fetchall()
        return [_row_to_session(row) for row in rows]

    def update_summary(self, session_id: str, summary: str, category: str, outcomes: str, learnings: list[str]):
        """Update AI-generated summary fields for a session."""
        self.conn.execute(
            """UPDATE sessions SET summary = ?, category = ?, outcomes = ?, learnings = ?
               WHERE session_id = ?""",
            (summary, category, outcomes, json.dumps(learnings) if learnings else None, session_id),
        )
        self.conn.commit()

    # --- Delete / Clean ---

    _JUNK_TITLES = {"hi", "hello", "test", "你好", "config", "init", "hey", "hola"}

    def find_junk_sessions(self, aggressive: bool = False) -> list[Session]:
        """Find sessions matching junk criteria.

        Default: empty/test titles + zero-duration with ≤5 messages.
        Aggressive: also includes sessions ≤2 minutes.
        """
        all_sessions = self.list_sessions(limit=10000)
        junk = []

        for s in all_sessions:
            title = (s.title or "").strip().lower()

            # Rule 1: completely empty title + short
            if not title and s.duration_minutes <= 5:
                junk.append(s)
                continue

            # Rule 2: known test titles + short duration + few messages
            if title in self._JUNK_TITLES and s.duration_minutes <= 5 and s.message_count <= 20:
                junk.append(s)
                continue

            # Rule 3: zero duration + very few messages (abandoned sessions)
            if s.duration_minutes == 0 and s.message_count <= 3:
                junk.append(s)
                continue

            # Rule 4 (aggressive): ≤2 min and ≤10 messages
            if aggressive and s.duration_minutes <= 2 and s.message_count <= 10:
                junk.append(s)
                continue

        return junk

    def delete_session(self, session_id: str, delete_files: bool = True) -> bool:
        """Delete a session from the index and optionally its .jsonl file.

        Returns True if the session was found and deleted.
        """
        session = self.get_session(session_id)
        if not session:
            return False

        # Delete from SQLite
        self.conn.execute("DELETE FROM sessions WHERE session_id = ?", (session.session_id,))
        self.conn.commit()

        if delete_files and session.file_path:
            fp = Path(session.file_path)

            # Delete .jsonl file (safety: only delete actual files, not directories)
            if fp.is_file() and fp.suffix == ".jsonl":
                fp.unlink()

            # Delete associated subdirectory (subagents/, tool-results/)
            subdir = fp.parent / fp.stem
            if subdir.is_dir():
                import shutil

                shutil.rmtree(subdir, ignore_errors=True)

        return True


def _row_to_session(row: sqlite3.Row) -> Session:
    """Convert a database row to a Session object."""
    from datetime import datetime, timezone

    start_time = datetime.now(timezone.utc)
    if row["start_time"]:
        try:
            st = row["start_time"]
            if st.endswith("Z"):
                st = st[:-1] + "+00:00"
            start_time = datetime.fromisoformat(st)
        except (ValueError, TypeError):
            pass

    end_time = None
    if row["end_time"]:
        try:
            et = row["end_time"]
            if et.endswith("Z"):
                et = et[:-1] + "+00:00"
            end_time = datetime.fromisoformat(et)
        except (ValueError, TypeError):
            pass

    tools = []
    if row["tools_used"]:
        try:
            tools = json.loads(row["tools_used"])
        except json.JSONDecodeError:
            pass

    files = []
    if row["files_modified"]:
        try:
            files = json.loads(row["files_modified"])
        except json.JSONDecodeError:
            pass

    learnings = []
    if row["learnings"]:
        try:
            learnings = json.loads(row["learnings"])
        except json.JSONDecodeError:
            pass

    return Session(
        session_id=row["session_id"],
        project=row["project"] or "unknown",
        project_path=row["project_path"] or "",
        start_time=start_time,
        end_time=end_time,
        duration_minutes=row["duration_minutes"] or 0,
        message_count=row["message_count"] or 0,
        user_message_count=row["user_message_count"] or 0,
        model=row["model"],
        tokens=TokenUsage(
            input_tokens=row["input_tokens"] or 0,
            output_tokens=row["output_tokens"] or 0,
            cache_read_tokens=row["cache_read_tokens"] or 0,
            cache_creation_tokens=row["cache_creation_tokens"] or 0,
        ),
        tools_used=tools,
        files_modified=files,
        title=row["title"],
        slug=row["slug"],
        git_branch=row["git_branch"],
        file_path=Path(row["file_path"]) if row["file_path"] else Path(),
        file_size_kb=row["file_size_kb"] or 0,
        summary=row["summary"],
        category=row["category"],
        outcomes=row["outcomes"],
        learnings=learnings,
        mtime=row["mtime"] or 0.0,
    )


def _decode_project_name(encoded: str) -> str:
    """Decode project directory name to short readable name."""
    from cclog.scanner import decode_project_dir

    full_path = decode_project_dir(encoded)
    home = str(Path.home())
    if full_path.startswith(home):
        return full_path[len(home) :].lstrip("/") or "~"
    return full_path
