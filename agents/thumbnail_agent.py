"""Thumbnail Agent — generates a 1280x720 thumbnail with Pillow.

Style (config/style_profile.md):
  * Dark background (#0d0d0d).
  * Large bold white title, max 5 words.
  * Gold (#FFD700) question mark accent.
  * No faces (faceless channel).

The short title is written by Claude in the "UNSOLVED: [short question]?"
format, with a deterministic fallback when Claude is unavailable.

Output: output/thumbnail.png — also returned.

Run standalone:
    python -m agents.thumbnail_agent --topic "Dyatlov Pass incident"
"""
from __future__ import annotations

import argparse
import os

from agents.common import (
    ASSETS_DIR,
    OUTPUT_DIR,
    anthropic_client,
    anthropic_model,
    get_logger,
    load_env,
)

log = get_logger("thumbnail")

WIDTH, HEIGHT = 1280, 720
BG_COLOR = (13, 13, 13)        # #0d0d0d
TEXT_COLOR = (255, 255, 255)   # white
ACCENT_COLOR = (255, 215, 0)   # #FFD700 gold
MARGIN = 80
MAX_TITLE_WORDS = 5

OUTPUT_PNG = OUTPUT_DIR / "thumbnail.png"


def _resolve_font_path() -> str:
    """Find a bold TTF: env override, bundled asset, then system DejaVu."""
    candidates = [
        os.environ.get("THUMBNAIL_FONT", ""),
        str(ASSETS_DIR / "fonts" / "title.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return ""  # signals: fall back to PIL's default bitmap font


def _make_title(topic: dict) -> str:
    """Ask Claude for a punchy <=5 word thumbnail title; fall back if needed."""
    name = topic.get("topic", "Unknown Mystery")
    try:
        client = anthropic_client()
        prompt = (
            "Write a YouTube thumbnail title for a mystery video about: "
            f"'{name}'.\n"
            "Rules: format 'UNSOLVED: <short question>?', MAX 5 words total, "
            "all caps allowed, punchy and curiosity-driven, no names of living "
            "people. Reply with ONLY the title text."
        )
        resp = client.messages.create(
            model=anthropic_model(),
            max_tokens=40,
            messages=[{"role": "user", "content": prompt}],
        )
        title = resp.content[0].text.strip().strip('"')
        # Enforce the word cap defensively.
        words = title.split()
        if len(words) > MAX_TITLE_WORDS + 1:  # +1 to allow "UNSOLVED:" prefix
            title = " ".join(words[: MAX_TITLE_WORDS + 1])
        if title:
            return title
    except Exception as exc:
        log.warning("Claude title generation failed (%s) — using fallback.", exc)

    # Deterministic fallback: short, capitalized topic name.
    short = " ".join(name.split()[:MAX_TITLE_WORDS])
    return f"UNSOLVED: {short.upper()}"


def _load_font(size: int):
    from PIL import ImageFont

    path = _resolve_font_path()
    if path:
        return ImageFont.truetype(path, size)
    log.warning("No TTF font found — using PIL default (small).")
    return ImageFont.load_default()


def _wrap_to_width(draw, text: str, font, max_width: int) -> list[str]:
    """Greedy word-wrap so each line fits within max_width."""
    words = text.split()
    lines, current = [], ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def run(topic: dict) -> str:
    """Render the thumbnail for a topic dict and return the PNG path."""
    load_env()
    from PIL import Image, ImageDraw

    title = _make_title(topic)
    log.info("Thumbnail title: %s", title)

    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Large gold question mark as a background accent in the lower-right.
    q_font = _load_font(520)
    draw.text((WIDTH - 300, HEIGHT - 470), "?", font=q_font, fill=ACCENT_COLOR)

    # Fit the title: shrink font until the wrapped block fits the safe area.
    max_text_width = WIDTH - 2 * MARGIN
    max_text_height = HEIGHT - 2 * MARGIN
    for size in range(150, 40, -6):
        font = _load_font(size)
        lines = _wrap_to_width(draw, title, font, max_text_width)
        line_h = size + 14
        block_h = line_h * len(lines)
        widest = max((draw.textlength(ln, font=font) for ln in lines), default=0)
        if block_h <= max_text_height and widest <= max_text_width:
            break

    # Vertically center the text block, left-aligned within the margin.
    y = (HEIGHT - block_h) // 2
    for line in lines:
        # Subtle shadow for legibility over the gold accent.
        draw.text((MARGIN + 3, y + 3), line, font=font, fill=(0, 0, 0))
        draw.text((MARGIN, y), line, font=font, fill=TEXT_COLOR)
        y += line_h

    OUTPUT_DIR.mkdir(exist_ok=True)
    img.save(OUTPUT_PNG)
    log.info("Thumbnail written to %s (%dx%d).", OUTPUT_PNG, WIDTH, HEIGHT)
    return str(OUTPUT_PNG)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a YouTube thumbnail.")
    parser.add_argument("--topic", required=True, help="Topic title.")
    args = parser.parse_args()
    out = run({"topic": args.topic})
    print(out)


if __name__ == "__main__":
    main()
