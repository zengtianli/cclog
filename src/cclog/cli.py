"""CLI entry point for cclog."""

import argparse
import json
import sys
import time
from datetime import datetime

from cclog import __version__
from cclog.config import load_config
from cclog.indexer import Indexer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cclog",
        description="Browse, summarize, and review your Claude Code sessions",
    )
    parser.add_argument("-V", "--version", action="version", version=f"cclog {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    # --- index ---
    p_index = subparsers.add_parser("index", help="Build or update session index")
    p_index.add_argument("--full", action="store_true", help="Force full re-index")
    p_index.set_defaults(func=cmd_index)

    # --- list ---
    p_list = subparsers.add_parser("list", help="List sessions")
    p_list.add_argument("--project", "-p", help="Filter by project name")
    p_list.add_argument("--date", "-d", help="Filter by date (YYYY-MM-DD)")
    p_list.add_argument("--since", help="Sessions since date (YYYY-MM-DD)")
    p_list.add_argument("--category", "-c", help="Filter by category")
    p_list.add_argument("--limit", "-n", type=int, default=20, help="Number of results (default: 20)")
    p_list.add_argument("--format", choices=["table", "json"], default="table", help="Output format")
    p_list.set_defaults(func=cmd_list)

    # --- show ---
    p_show = subparsers.add_parser("show", help="Show session details")
    p_show.add_argument("session_id", help="Session ID (or prefix)")
    p_show.add_argument("--full", action="store_true", help="Include conversation text")
    p_show.set_defaults(func=cmd_show)

    # --- stats ---
    p_stats = subparsers.add_parser("stats", help="Show usage statistics")
    p_stats.set_defaults(func=cmd_stats)

    # --- summarize (placeholder for Phase 2) ---
    p_sum = subparsers.add_parser("summarize", help="Generate AI summaries for sessions")
    p_sum.add_argument("session_id", nargs="?", help="Session ID (or summarize all unsummarized)")
    p_sum.add_argument("--since", help="Summarize sessions since date")
    p_sum.add_argument("--backend", choices=["claude-cli", "api"], default="claude-cli")
    p_sum.add_argument("--limit", "-n", type=int, default=10, help="Max sessions to summarize")
    p_sum.set_defaults(func=cmd_summarize)

    # --- digest (placeholder for Phase 3) ---
    p_digest = subparsers.add_parser("digest", help="Generate daily/weekly digest")
    p_digest.add_argument("date", nargs="?", default="today", help="Date or 'today'/'yesterday'")
    p_digest.add_argument("--week", action="store_true", help="Generate weekly digest")
    p_digest.set_defaults(func=cmd_digest)

    # --- clean ---
    p_clean = subparsers.add_parser("clean", help="Find and remove junk sessions")
    p_clean.add_argument("--execute", action="store_true", help="Actually delete (default: dry-run preview)")
    p_clean.add_argument("--aggressive", action="store_true", help="Also remove sessions ≤2 minutes")
    p_clean.set_defaults(func=cmd_clean)

    # --- delete ---
    p_del = subparsers.add_parser("delete", help="Delete a specific session")
    p_del.add_argument("session_id", help="Session ID (or prefix)")
    p_del.add_argument("--yes", "-y", action="store_true", help="Skip confirmation")
    p_del.set_defaults(func=cmd_delete)

    # --- site ---
    p_site = subparsers.add_parser("site", help="Generate static HTML site")
    p_site.add_argument("--output", "-o", type=str, default="./cclog-site", help="Output directory")
    p_site.add_argument("--open", action="store_true", help="Open in browser after generating")
    p_site.set_defaults(func=cmd_site)

    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    return args.func(args)


# --- Command implementations ---


def cmd_index(args) -> int:
    config = load_config()
    indexer = Indexer(config)

    t0 = time.time()
    total, indexed, skipped = indexer.build(full=args.full)
    elapsed = time.time() - t0

    indexer.close()

    print(f"Scanned {total} files in {elapsed:.1f}s")
    print(f"  Indexed: {indexed} sessions")
    print(f"  Skipped: {skipped} (unchanged)")
    print(f"  Database: {config.db_path}")
    return 0


def cmd_list(args) -> int:
    config = load_config()
    indexer = Indexer(config)

    sessions = indexer.list_sessions(
        project=args.project,
        date=args.date,
        since=args.since,
        category=args.category,
        limit=args.limit,
    )

    indexer.close()

    if not sessions:
        print("No sessions found.")
        return 0

    if args.format == "json":
        data = [_session_to_dict(s) for s in sessions]
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
        return 0

    # Table format
    _print_session_table(sessions)
    return 0


def cmd_show(args) -> int:
    config = load_config()
    indexer = Indexer(config)

    session = indexer.get_session(args.session_id)
    indexer.close()

    if not session:
        print(f"Session not found: {args.session_id}")
        return 1

    _print_session_detail(session)

    if args.full and session.file_path and session.file_path.exists():
        from cclog.parser import parse_conversation_text

        print("\n--- Conversation ---\n")
        text = parse_conversation_text(session.file_path)
        print(text)

    return 0


def cmd_stats(args) -> int:
    config = load_config()
    indexer = Indexer(config)
    stats = indexer.get_stats()
    indexer.close()

    total_hours = (stats["total_minutes"] or 0) / 60
    total_input_m = (stats["total_input_tokens"] or 0) / 1_000_000
    total_output_m = (stats["total_output_tokens"] or 0) / 1_000_000

    print("=== cclog Statistics ===\n")
    print(f"  Sessions:     {stats['total_sessions']}")
    print(f"  Projects:     {stats['total_projects']}")
    print(f"  Summarized:   {stats['summarized_sessions']}")
    print(f"  Total time:   {total_hours:.1f} hours")
    print(f"  Input tokens:  {total_input_m:.1f}M")
    print(f"  Output tokens: {total_output_m:.1f}M")
    print(f"  Date range:   {_short_date(stats['earliest_session'])} ~ {_short_date(stats['latest_session'])}")
    return 0


def cmd_summarize(args) -> int:
    from cclog.summarizer import summarize_session

    config = load_config()
    if args.backend:
        config.llm_backend = args.backend

    indexer = Indexer(config)

    if args.session_id:
        # Summarize single session
        session = indexer.get_session(args.session_id)
        if not session:
            print(f"Session not found: {args.session_id}")
            indexer.close()
            return 1
        sessions = [session]
    else:
        sessions = indexer.get_unsummarized_sessions(since=args.since, limit=args.limit)

    if not sessions:
        print("No sessions to summarize.")
        indexer.close()
        return 0

    print(f"Summarizing {len(sessions)} session(s) via {config.llm_backend}...\n")

    success = 0
    for i, s in enumerate(sessions, 1):
        label = s.summary and "(re-summarize)" or ""
        print(f"  [{i}/{len(sessions)}] {s.project} {s.start_time.strftime('%Y-%m-%d') if s.start_time else '?'} {label}")

        result = summarize_session(s, config)
        if result:
            indexer.update_summary(
                s.session_id,
                result["summary"],
                result["category"],
                result["outcomes"],
                result["learnings"],
            )
            print(f"    -> {result['summary'][:60]}")
            success += 1
        else:
            print("    -> (failed)")

    indexer.close()
    print(f"\nDone: {success}/{len(sessions)} summarized")
    return 0


def cmd_digest(args) -> int:
    from cclog.digest import (
        build_daily_digest,
        build_weekly_digest,
        format_digest_markdown,
        format_weekly_markdown,
        parse_date_arg,
    )

    config = load_config()
    indexer = Indexer(config)

    target_date = parse_date_arg(args.date)

    if args.week:
        digests = build_weekly_digest(indexer, target_date, config.timezone)
        indexer.close()
        if not digests:
            print("No sessions found for this week.")
            return 0
        print(format_weekly_markdown(digests))
    else:
        digest = build_daily_digest(indexer, target_date, config.timezone)
        indexer.close()
        if not digest.sessions:
            print(f"No sessions found for {target_date.isoformat()}")
            return 0
        print(format_digest_markdown(digest))

    return 0


def cmd_clean(args) -> int:
    config = load_config()
    indexer = Indexer(config)

    junk = indexer.find_junk_sessions(aggressive=args.aggressive)

    if not junk:
        print("No junk sessions found.")
        indexer.close()
        return 0

    mode = "aggressive" if args.aggressive else "standard"
    print(f"Found {len(junk)} junk session(s) ({mode} mode):\n")
    print(f"{'Date':<12} {'Dur':>5} {'Msgs':>5} {'Project':<22} {'Title'}")
    print("-" * 80)

    for s in junk:
        date_str = s.start_time.strftime("%Y-%m-%d") if s.start_time else "-"
        title = (s.title or "(empty)")[:35]
        print(f"{date_str:<12} {s.duration_minutes:>4}m {s.message_count:>5} {s.project[:21]:<22} {title}")

    if not args.execute:
        print(f"\nDry run: {len(junk)} sessions would be deleted.")
        print("Run with --execute to actually delete.")
        indexer.close()
        return 0

    # Execute deletion
    deleted = 0
    for s in junk:
        if indexer.delete_session(s.session_id, delete_files=True):
            deleted += 1

    indexer.close()
    print(f"\nDeleted {deleted}/{len(junk)} sessions (index + files).")
    return 0


def cmd_delete(args) -> int:
    config = load_config()
    indexer = Indexer(config)

    session = indexer.get_session(args.session_id)
    if not session:
        print(f"Session not found: {args.session_id}")
        indexer.close()
        return 1

    print(f"Session:  {session.session_id}")
    print(f"Project:  {session.project}")
    print(f"Date:     {session.start_time.strftime('%Y-%m-%d %H:%M') if session.start_time else '-'}")
    print(f"Title:    {session.title or '(empty)'}")
    print(f"File:     {session.file_path}")

    if not args.yes:
        confirm = input("\nDelete this session? [y/N] ").strip().lower()
        if confirm != "y":
            print("Cancelled.")
            indexer.close()
            return 0

    if indexer.delete_session(session.session_id, delete_files=True):
        print("Deleted.")
    else:
        print("Failed to delete.")

    indexer.close()
    return 0


def cmd_site(args) -> int:
    import webbrowser
    from pathlib import Path

    from cclog.site import generate_site

    config = load_config()
    output_dir = Path(args.output).resolve()
    generate_site(config, output_dir)

    if args.open:
        index_path = output_dir / "index.html"
        webbrowser.open(f"file://{index_path}")

    return 0


# --- Formatting helpers ---


def _print_session_table(sessions: list) -> None:
    """Print sessions as a formatted table."""
    # Header
    print(f"{'Date':<12} {'Duration':>8} {'Msgs':>5} {'Project':<25} {'Title / Summary'}")
    print("-" * 100)

    for s in sessions:
        date_str = _short_date(s.start_time.isoformat() if s.start_time else "")
        dur = f"{s.duration_minutes}m" if s.duration_minutes else "-"
        project = s.project[:24] if s.project else "-"
        desc = s.summary or s.title or "-"
        if len(desc) > 50:
            desc = desc[:47] + "..."

        print(f"{date_str:<12} {dur:>8} {s.message_count:>5} {project:<25} {desc}")

    print(f"\n  ({len(sessions)} sessions)")


def _print_session_detail(s) -> None:
    """Print detailed session info."""
    print(f"Session:   {s.session_id}")
    print(f"Slug:      {s.slug or '-'}")
    print(f"Project:   {s.project}")
    print(f"Path:      {s.project_path}")
    print(f"Date:      {s.start_time.strftime('%Y-%m-%d %H:%M') if s.start_time else '-'}")
    print(f"Duration:  {s.duration_minutes} min")
    print(f"Messages:  {s.message_count} ({s.user_message_count} user)")
    print(f"Model:     {s.model or '-'}")
    print(f"Branch:    {s.git_branch or '-'}")
    print(f"File:      {s.file_path} ({s.file_size_kb} KB)")

    if s.tokens.total > 0:
        print(f"Tokens:    {s.tokens.input_tokens:,} in / {s.tokens.output_tokens:,} out")

    if s.tools_used:
        print(f"Tools:     {', '.join(s.tools_used)}")

    if s.files_modified:
        print(f"Files modified: {len(s.files_modified)}")
        for f in s.files_modified[:10]:
            print(f"  - {f}")
        if len(s.files_modified) > 10:
            print(f"  ... and {len(s.files_modified) - 10} more")

    if s.summary:
        print(f"\nSummary:   {s.summary}")
    if s.category:
        print(f"Category:  {s.category}")
    if s.outcomes:
        print(f"Outcomes:  {s.outcomes}")
    if s.learnings:
        print("Learnings:")
        for l in s.learnings:
            print(f"  - {l}")


def _session_to_dict(s) -> dict:
    """Convert session to JSON-serializable dict."""
    return {
        "session_id": s.session_id,
        "project": s.project,
        "start_time": s.start_time.isoformat() if s.start_time else None,
        "duration_minutes": s.duration_minutes,
        "message_count": s.message_count,
        "model": s.model,
        "title": s.title,
        "summary": s.summary,
        "category": s.category,
        "outcomes": s.outcomes,
        "tools_used": s.tools_used,
    }


def _short_date(iso_str: str | None) -> str:
    """Extract YYYY-MM-DD from an ISO timestamp."""
    if not iso_str:
        return "-"
    return iso_str[:10]


if __name__ == "__main__":
    sys.exit(main())
