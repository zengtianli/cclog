"""Discover Claude Code session JSONL files across all projects."""

from dataclasses import dataclass
from pathlib import Path


@dataclass
class ScannedFile:
    """A discovered session JSONL file with filesystem metadata."""

    path: Path
    project_dir: str  # Encoded directory name (e.g., "-Users-tianli-Dev-scripts")
    mtime: float
    size: int  # bytes

    @property
    def size_kb(self) -> int:
        return self.size // 1024


def scan_projects(projects_dir: Path) -> list[ScannedFile]:
    """Walk all project directories and find session JSONL files.

    Skips:
    - Files inside subdirectories of session UUIDs (subagents, tool-results)
    - Non-.jsonl files

    Returns list sorted by mtime descending (most recent first).
    """
    if not projects_dir.is_dir():
        return []

    results = []

    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        project_name = project_dir.name

        # Only look at direct .jsonl children (not in subdirectories)
        for jsonl_file in project_dir.glob("*.jsonl"):
            try:
                stat = jsonl_file.stat()
                results.append(
                    ScannedFile(
                        path=jsonl_file,
                        project_dir=project_name,
                        mtime=stat.st_mtime,
                        size=stat.st_size,
                    )
                )
            except OSError:
                continue

    results.sort(key=lambda f: f.mtime, reverse=True)
    return results


def decode_project_dir(encoded: str) -> str:
    """Decode project directory name to a readable path.

    Example: "-Users-tianli-Dev-scripts" -> "/Users/tianli/Dev/tools/scripts"

    This is a heuristic — the actual cwd from the JSONL is more reliable.
    """
    if not encoded.startswith("-"):
        return encoded

    # Replace leading dash and subsequent dashes with /
    # Handle special cases: double dash means literal dash in path
    parts = encoded.split("-")
    # First element is empty (from leading dash)
    if parts and parts[0] == "":
        parts = parts[1:]

    return "/" + "/".join(parts)
