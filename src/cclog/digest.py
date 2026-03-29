"""Daily and weekly digest aggregation."""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from cclog.config import Config
from cclog.indexer import Indexer
from cclog.models import DailyDigest, Session


def build_daily_digest(indexer: Indexer, target_date: date, tz: str = "UTC") -> DailyDigest:
    """Build a digest for a single date."""
    date_str = target_date.isoformat()
    sessions = indexer.get_sessions_for_date(date_str)
    digest = DailyDigest(date=target_date, sessions=sessions)
    return digest


def build_weekly_digest(indexer: Indexer, ref_date: date, tz: str = "UTC") -> list[DailyDigest]:
    """Build digests for the week containing ref_date (Mon-Sun)."""
    monday = ref_date - timedelta(days=ref_date.weekday())
    digests = []
    for i in range(7):
        d = monday + timedelta(days=i)
        if d > date.today():
            break
        digest = build_daily_digest(indexer, d, tz)
        if digest.sessions:
            digests.append(digest)
    return digests


def parse_date_arg(arg: str) -> date:
    """Parse date argument: 'today', 'yesterday', or 'YYYY-MM-DD'."""
    if arg == "today":
        return date.today()
    elif arg == "yesterday":
        return date.today() - timedelta(days=1)
    else:
        return date.fromisoformat(arg)


def format_digest_markdown(digest: DailyDigest) -> str:
    """Format a daily digest as Markdown."""
    lines = [f"# {digest.date.isoformat()} Daily Digest\n"]

    # Stats
    tokens = digest.total_tokens
    lines.append(f"**Sessions:** {len(digest.sessions)} | "
                 f"**Duration:** {digest.total_duration_minutes} min | "
                 f"**Projects:** {', '.join(digest.projects_touched)}\n")

    if tokens.total > 0:
        lines.append(f"**Tokens:** {tokens.input_tokens:,} in / {tokens.output_tokens:,} out\n")

    # Sessions
    lines.append("## Sessions\n")

    for s in digest.sessions:
        time_str = s.start_time.strftime("%H:%M") if s.start_time else "?"
        dur = f"{s.duration_minutes}m" if s.duration_minutes else "-"
        lines.append(f"### {time_str} - {s.project} ({dur})\n")

        if s.summary:
            lines.append(f"{s.summary}\n")
        elif s.title:
            lines.append(f"_{s.title}_\n")

        if s.outcomes:
            lines.append(f"**Outcomes:** {s.outcomes}\n")

        if s.learnings:
            lines.append("**Learnings:**")
            for l in s.learnings:
                lines.append(f"- {l}")
            lines.append("")

        if s.tools_used:
            lines.append(f"**Tools:** {', '.join(s.tools_used[:8])}\n")

    return "\n".join(lines)


def format_weekly_markdown(digests: list[DailyDigest]) -> str:
    """Format a weekly digest as Markdown."""
    if not digests:
        return "No sessions found for this week.\n"

    first = digests[0].date
    last = digests[-1].date
    lines = [f"# Week of {first.isoformat()} ~ {last.isoformat()}\n"]

    # Aggregate stats
    total_sessions = sum(len(d.sessions) for d in digests)
    total_minutes = sum(d.total_duration_minutes for d in digests)
    all_projects: list[str] = []
    for d in digests:
        for p in d.projects_touched:
            if p not in all_projects:
                all_projects.append(p)

    lines.append(f"**Total:** {total_sessions} sessions | {total_minutes} min | {len(all_projects)} projects\n")

    # Per-day summary
    lines.append("## Daily Breakdown\n")
    for d in digests:
        weekday = d.date.strftime("%A")
        lines.append(f"### {d.date.isoformat()} ({weekday})\n")
        lines.append(f"{len(d.sessions)} sessions, {d.total_duration_minutes} min\n")

        for s in d.sessions:
            desc = s.summary or s.title or "-"
            if len(desc) > 80:
                desc = desc[:77] + "..."
            lines.append(f"- **{s.project}**: {desc}")

        lines.append("")

    return "\n".join(lines)
