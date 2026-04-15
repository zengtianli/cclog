"""Cross-source knowledge search for the unified CC MCP.

Searches across 5 data sources:
- cclog DB (session history)
- Memory files (~/.claude/projects/*/memory/*.md)
- skill-tracker.json (command usage stats)
- tasks.json (task status)
- reflect-flags.log (feedback signals)
"""

import json
import re
from datetime import date, datetime
from pathlib import Path


MEMORY_BASE = Path.home() / ".claude" / "projects"
SKILL_TRACKER = Path.home() / "Dev" / "cc-configs" / "skill-tracker.json"
TASKS_FILE = Path.home() / "Dev" / "configs" / "tasks.json"
REFLECT_LOG = Path.home() / "Dev" / "devtools" / "logs" / "reflect-flags.log"
SKILL_CANDIDATES = Path.home() / "Dev" / "cc-configs" / "skill-candidates.md"


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from markdown text."""
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
    return meta, parts[2].strip()


def _dir_to_project(dirname: str) -> str:
    prefix = "-Users-tianli-"
    name = dirname
    if name.startswith(prefix):
        name = name[len(prefix):]
    return name.replace("-", "/")


def search_knowledge(query: str, sources: list[str] | None = None) -> list[dict]:
    """Search across all knowledge stores.

    Args:
        query: Search keyword (case-insensitive).
        sources: Optional filter: ["memory", "skills", "tasks", "reflect", "sessions"].

    Returns:
        List of {source, title, content, date, relevance} dicts, sorted by relevance.
    """
    q = query.lower()
    results = []
    all_sources = sources or ["memory", "skills", "tasks", "reflect"]

    # 1. Memory files
    if "memory" in all_sources:
        for memory_dir in MEMORY_BASE.glob("*/memory"):
            project = _dir_to_project(memory_dir.parent.name)
            for md_file in memory_dir.glob("*.md"):
                if md_file.name == "MEMORY.md":
                    continue
                try:
                    text = md_file.read_text(encoding="utf-8")
                except Exception:
                    continue
                meta, content = _parse_frontmatter(text)
                name = meta.get("name", "")
                desc = meta.get("description", "")
                score = 0
                if q in name.lower():
                    score += 3
                if q in desc.lower():
                    score += 2
                if q in content.lower():
                    score += 1
                if score > 0:
                    results.append({
                        "source": "memory",
                        "title": name,
                        "content": desc,
                        "project": project,
                        "file": str(md_file),
                        "date": meta.get("last_verified", ""),
                        "relevance": score,
                    })

    # 2. Skill tracker
    if "skills" in all_sources and SKILL_TRACKER.exists():
        try:
            data = json.loads(SKILL_TRACKER.read_text(encoding="utf-8"))
            for name, info in data.items():
                score = 0
                if q in name.lower():
                    score += 3
                notes_text = " ".join(info.get("notes", []))
                if q in notes_text.lower():
                    score += 1
                if score > 0:
                    results.append({
                        "source": "skill-tracker",
                        "title": name,
                        "content": f"uses={info.get('use_count', 0)}, corrections={info.get('correction_count', 0)}",
                        "date": info.get("last_used", ""),
                        "relevance": score,
                    })
        except Exception:
            pass

    # 3. Tasks
    if "tasks" in all_sources and TASKS_FILE.exists():
        try:
            data = json.loads(TASKS_FILE.read_text(encoding="utf-8"))
            for t in data.get("tasks", []):
                title = t.get("title", "")
                outcome = t.get("outcome", "")
                repo = t.get("repo", "")
                score = 0
                if q in title.lower():
                    score += 3
                if q in outcome.lower():
                    score += 2
                if q in repo.lower():
                    score += 1
                if score > 0:
                    results.append({
                        "source": "tasks",
                        "title": title,
                        "content": f"[{t.get('status', '')}] {outcome or t.get('next_step', '')}",
                        "date": t.get("analyzed_at", "")[:10],
                        "relevance": score,
                    })
        except Exception:
            pass

    # 4. Reflect flags log
    if "reflect" in all_sources and REFLECT_LOG.exists():
        try:
            lines = REFLECT_LOG.read_text(encoding="utf-8").splitlines()
            for line in reversed(lines[-100:]):
                if q in line.lower():
                    parts = line.split("|")
                    results.append({
                        "source": "reflect-log",
                        "title": parts[2].strip() if len(parts) > 2 else "signal",
                        "content": line.strip()[:200],
                        "date": parts[0].strip()[:10] if parts else "",
                        "relevance": 1,
                    })
        except Exception:
            pass

    results.sort(key=lambda r: -r["relevance"])
    return results[:20]


def get_evolution_status() -> dict:
    """System health report for the CC evolution ecosystem.

    Returns:
        Dict with stale_memories, unused_commands, matured_candidates, stats.
    """
    today = date.today()
    status = {
        "stale_memories": [],
        "unused_commands": [],
        "matured_candidates": [],
        "memory_stats": {"total": 0, "fresh": 0, "aging": 0, "stale": 0},
    }

    # 1. Stale memories
    dev_memory = MEMORY_BASE / "-Users-tianli-Dev" / "memory"
    if dev_memory.exists():
        for f in dev_memory.glob("*.md"):
            if f.name == "MEMORY.md":
                continue
            status["memory_stats"]["total"] += 1
            try:
                text = f.read_text(encoding="utf-8")[:500]
                meta, _ = _parse_frontmatter(text)
                lv = meta.get("last_verified", "")
                dd = meta.get("decay_days", "")
                if lv and dd:
                    last = date.fromisoformat(lv)
                    decay = int(dd)
                    age = (today - last).days
                    if age > decay:
                        status["stale_memories"].append({
                            "file": f.name,
                            "days_overdue": age - decay,
                            "last_verified": lv,
                        })
                        status["memory_stats"]["stale"] += 1
                    elif age > decay * 0.7:
                        status["memory_stats"]["aging"] += 1
                    else:
                        status["memory_stats"]["fresh"] += 1
                else:
                    status["memory_stats"]["fresh"] += 1
            except Exception:
                status["memory_stats"]["fresh"] += 1

    # 2. Unused commands
    if SKILL_TRACKER.exists():
        try:
            data = json.loads(SKILL_TRACKER.read_text(encoding="utf-8"))
            for name, info in data.items():
                if info.get("use_count", 0) == 0:
                    status["unused_commands"].append(name)
        except Exception:
            pass

    # 3. Matured skill candidates
    if SKILL_CANDIDATES.exists():
        try:
            text = SKILL_CANDIDATES.read_text(encoding="utf-8")
            current_name = ""
            has_status = False
            for line in text.splitlines():
                if line.startswith("##"):
                    current_name = line.lstrip("#").strip()
                    has_status = False
                if re.search(r"状态[:：]", line):
                    has_status = True
                m = re.search(r"出现次数[:：]\s*(\d+)", line)
                if m and int(m.group(1)) >= 3 and not has_status:
                    status["matured_candidates"].append(current_name)
        except Exception:
            pass

    return status
