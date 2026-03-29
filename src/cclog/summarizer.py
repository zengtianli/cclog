"""LLM summarization pipeline for Claude Code sessions."""

import json
import subprocess
from pathlib import Path
from string import Template

from cclog.config import Config
from cclog.models import Session
from cclog.parser import parse_conversation_text

_TEMPLATE_PATH = Path(__file__).parent / "templates" / "summarize_prompt.txt"


def summarize_session(session: Session, config: Config) -> dict | None:
    """Generate AI summary for a session.

    Returns dict with keys: summary, category, outcomes, learnings.
    Returns None if summarization fails.
    """
    # Extract conversation text
    file_path = session.file_path
    if not file_path or not file_path.exists():
        return None

    conversation = parse_conversation_text(file_path, max_chars=50000)
    if not conversation.strip():
        return None

    # Build prompt
    prompt = _build_prompt(session, conversation)

    # Call LLM backend
    if config.llm_backend == "claude-cli":
        raw = _call_claude_cli(prompt, config.llm_model)
    elif config.llm_backend == "anthropic-api":
        raw = _call_anthropic_api(prompt, config)
    else:
        return None

    if not raw:
        return None

    # Parse JSON response
    return _parse_response(raw)


def _build_prompt(session: Session, conversation: str) -> str:
    """Build the summarization prompt from template."""
    template_text = _TEMPLATE_PATH.read_text(encoding="utf-8")
    tmpl = Template(template_text)

    return tmpl.safe_substitute(
        project=session.project,
        date=session.start_time.strftime("%Y-%m-%d") if session.start_time else "unknown",
        duration=str(session.duration_minutes),
        message_count=str(session.message_count),
        tools=", ".join(session.tools_used) if session.tools_used else "none",
        conversation=conversation,
    )


def _call_claude_cli(prompt: str, model: str = "sonnet") -> str | None:
    """Call claude -p for summarization using CC subscription."""
    try:
        result = subprocess.run(
            [
                "claude",
                "-p", prompt,
                "--model", model,
                "--no-session-persistence",
                "--output-format", "text",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def _call_anthropic_api(prompt: str, config: Config) -> str | None:
    """Call Anthropic API directly (requires `anthropic` package)."""
    try:
        from anthropic import Anthropic
    except ImportError:
        print("Error: anthropic package not installed. Run: pip install cclog[api]")
        return None

    import os

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY not set")
        return None

    try:
        client = Anthropic(api_key=api_key)
        message = client.messages.create(
            model=config.llm_model if "/" in config.llm_model else f"claude-{config.llm_model}-4-6",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}],
        )
        if message.content:
            return message.content[0].text
    except Exception:
        return None

    return None


def _parse_response(raw: str) -> dict | None:
    """Parse LLM response as JSON, handling common formatting issues."""
    text = raw.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last lines (fences)
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON object in the response
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start:end])
            except json.JSONDecodeError:
                return None
        else:
            return None

    # Validate expected fields
    result = {
        "summary": data.get("summary", ""),
        "category": data.get("category", ""),
        "outcomes": data.get("outcomes", ""),
        "learnings": data.get("learnings", []),
    }

    if not result["summary"]:
        return None

    # Normalize category
    valid_categories = {"development", "configuration", "debugging", "writing", "analysis", "learning", "discussion", "organization"}
    if result["category"] not in valid_categories:
        result["category"] = "development"

    # Ensure learnings is a list
    if isinstance(result["learnings"], str):
        result["learnings"] = [result["learnings"]] if result["learnings"] else []

    return result
