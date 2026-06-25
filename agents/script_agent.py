"""Script Agent — writes the video script in the channel's style.

Takes the topic dict from the Research Agent and produces a clean, voiceover-
ready script (plain text, 750-850 words) using Claude. The channel style is
loaded from config/style_profile.md and injected into the system prompt so the
written rules in that file stay authoritative.

Output: output/script.txt (also returned as a string).

Run standalone:
    python -m agents.script_agent --topic "Dyatlov Pass Incident"
"""
from __future__ import annotations

import argparse
import json
import re

from agents.common import (
    OUTPUT_DIR,
    STYLE_PROFILE_FILE,
    anthropic_client,
    anthropic_model,
    get_logger,
    load_env,
)

log = get_logger("script")

# Embedded verbatim from the handoff — the non-negotiable scriptwriting rules.
BASE_SYSTEM_PROMPT = """You are a YouTube scriptwriter for a mystery channel. Write scripts that:
- Start with a HOOK: an intriguing question or shocking fact (first 15 seconds)
- Structure: Hook -> Background -> Evidence -> Theories -> Cliffhanger ending
- Length: exactly 750-850 words (for ~6-7 min video)
- Tone: mysterious, authoritative, never sensationalist
- End with: "What do YOU think happened? Let us know in the comments."
- Never mention real living people by name
- All facts must be from the provided source summary
- Write for voiceover: short sentences, no bullet points, flowing prose"""

WORD_MIN, WORD_MAX = 750, 850


def _load_style_profile() -> str:
    """Return the channel style profile, or empty string if missing."""
    if STYLE_PROFILE_FILE.exists():
        return STYLE_PROFILE_FILE.read_text(encoding="utf-8")
    log.warning("style_profile.md not found — using base prompt only.")
    return ""


def _word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def _build_system_prompt() -> str:
    style = _load_style_profile()
    if not style:
        return BASE_SYSTEM_PROMPT
    return (
        BASE_SYSTEM_PROMPT
        + "\n\nFollow this channel style profile as well:\n\n"
        + style
    )


def _generate(topic: dict, system_prompt: str, *, retry_hint: str = "") -> str:
    client = anthropic_client()
    user_prompt = (
        f"Write the script for this topic.\n\n"
        f"TOPIC: {topic['topic']}\n\n"
        f"SOURCE SUMMARY (use only these facts):\n{topic.get('summary', '')}\n\n"
        "Output ONLY the script text — no title, no headings, no notes, no "
        "word count. Plain flowing prose ready to be read aloud."
    )
    if retry_hint:
        user_prompt += f"\n\nIMPORTANT: {retry_hint}"

    resp = client.messages.create(
        model=anthropic_model(),
        max_tokens=2000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return resp.content[0].text.strip()


def run(topic: dict) -> str:
    """Generate the script for a topic dict and save it to output/script.txt."""
    load_env()
    if not topic.get("summary"):
        log.warning("Topic has no summary — script quality will suffer.")

    system_prompt = _build_system_prompt()
    script = _generate(topic, system_prompt)
    words = _word_count(script)
    log.info("Draft script: %d words.", words)

    # One corrective retry if length is out of the target band.
    if not (WORD_MIN <= words <= WORD_MAX):
        direction = "shorter" if words > WORD_MAX else "longer"
        hint = (
            f"The previous draft was {words} words. Rewrite it {direction} so it "
            f"lands between {WORD_MIN} and {WORD_MAX} words."
        )
        log.info("Retrying for length (%s).", direction)
        script = _generate(topic, system_prompt, retry_hint=hint)
        log.info("Revised script: %d words.", _word_count(script))

    OUTPUT_DIR.mkdir(exist_ok=True)
    script_path = OUTPUT_DIR / "script.txt"
    script_path.write_text(script, encoding="utf-8")
    log.info("Script written to %s", script_path)
    return script


def main() -> None:
    parser = argparse.ArgumentParser(description="Script agent for mystery videos.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--topic", help="Topic title (summary fetched via research).")
    group.add_argument("--topic-json", help="Path to a topic JSON file from research.")
    args = parser.parse_args()

    if args.topic_json:
        with open(args.topic_json, encoding="utf-8") as fh:
            topic = json.load(fh)
    else:
        # Reuse the research agent to fetch a summary for the given topic.
        from agents import research_agent

        topic = research_agent.run(topic_override=args.topic)

    script = run(topic)
    print(script)


if __name__ == "__main__":
    main()
