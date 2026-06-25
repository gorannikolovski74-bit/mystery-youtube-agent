"""Animation Agent — renders one stickman scene per script paragraph (Manim).

Strategy (from HANDOFF):
  * Split the script into paragraphs.
  * For each paragraph render a short stickman scene on a dark background.
  * Scene length is estimated from the paragraph's word count so the merged
    video roughly matches the narration length.

Full burned-in subtitles are intentionally NOT drawn here — the Assembly Agent
adds accurate, timed subtitles with Whisper. Set ANIMATION_BURN_TEXT=1 to draw
a short caption per scene anyway (off by default to avoid double captions).

Output: output/scene_01.mp4, output/scene_02.mp4, ...
Returns: the ordered list of scene file paths.

Run standalone:
    python -m agents.animation_agent                     # uses output/script.txt
    python -m agents.animation_agent --script output/script.txt
"""
from __future__ import annotations

import argparse
import os
import re
import shutil

from agents.common import OUTPUT_DIR, get_logger, load_env

log = get_logger("animation")

# Visual constants (mirrors config/style_profile.md).
BG_COLOR = "#1a1a2e"
FG_COLOR = "#FFFFFF"
ACCENT_COLOR = "#FFD700"

# Pacing: average narrated speaking rate ~2.5 words/second.
WORDS_PER_SECOND = 2.5
MIN_SCENE_SECONDS = 3.0

# Render settings.
PIXEL_WIDTH = 1920
PIXEL_HEIGHT = 1080
FRAME_RATE = 30


def _split_into_paragraphs(text: str) -> list[str]:
    """Split a script into paragraph-sized blocks for one scene each."""
    text = text.strip()
    # Prefer blank-line separated paragraphs.
    parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(parts) > 1:
        return parts
    # Fall back to single newlines.
    parts = [p.strip() for p in text.split("\n") if p.strip()]
    if len(parts) > 1:
        return parts
    # Last resort: group sentences into blocks of three.
    sentences = re.split(r"(?<=[.!?])\s+", text)
    blocks, current = [], []
    for s in sentences:
        current.append(s)
        if len(current) >= 3:
            blocks.append(" ".join(current))
            current = []
    if current:
        blocks.append(" ".join(current))
    return blocks


def _estimate_seconds(paragraph: str) -> float:
    words = len(re.findall(r"\b\w+\b", paragraph))
    return max(MIN_SCENE_SECONDS, words / WORDS_PER_SECOND)


def _load_script_text(script: str | None) -> str:
    if script and ("\n" in script or len(script) > 200):
        return script.strip()
    path = script if script else str(OUTPUT_DIR / "script.txt")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    if script:
        return script.strip()
    raise FileNotFoundError(f"No script text and {path} does not exist.")


def _short_caption(paragraph: str, max_words: int = 10) -> str:
    words = paragraph.split()
    return " ".join(words[:max_words]) + ("…" if len(words) > max_words else "")


def _build_scene_class(duration: float, caption: str, variant: int):
    """Create a Manim Scene subclass that animates a stickman for `duration` s."""
    # Imported lazily so the rest of the pipeline doesn't require manim.
    from manim import (
        DOWN,
        LEFT,
        RIGHT,
        UP,
        Create,
        FadeIn,
        Scene,
        Text,
        Wiggle,
    )

    from assets.stickman.stickman import Stickman

    burn_text = os.environ.get("ANIMATION_BURN_TEXT", "0") == "1"

    class _MysteryScene(Scene):
        def construct(self):
            self.camera.background_color = BG_COLOR

            stickman = Stickman(color=FG_COLOR)
            self.play(Create(stickman), run_time=1.0)

            # A small idle gesture so the frame isn't completely static.
            # Vary the gesture by scene index for a little visual rhythm.
            gesture_targets = [
                stickman.right_arm.animate.shift(UP * 0.4 + RIGHT * 0.2),
                stickman.left_arm.animate.shift(UP * 0.4 + LEFT * 0.2),
                stickman.animate.shift(LEFT * 0.6),
                stickman.animate.shift(RIGHT * 0.6),
            ]
            self.play(gesture_targets[variant % len(gesture_targets)], run_time=1.0)

            if burn_text and caption:
                subtitle = Text(
                    caption, font="sans-serif", color=FG_COLOR, font_size=28,
                ).to_edge(DOWN, buff=0.5)
                self.play(FadeIn(subtitle), run_time=0.5)

            # Hold the rest of the estimated duration. The create + gesture
            # animations above take ~2.0s; keep the scene slightly long so the
            # video always covers the narration (assembly uses -shortest).
            remaining = max(0.5, duration - 2.0)
            self.play(Wiggle(stickman, scale_value=1.04), run_time=min(remaining, 2.0))
            if remaining > 2.0:
                self.wait(remaining - 2.0)

    return _MysteryScene


def run(script: str | None = None) -> list[str]:
    """Render one stickman scene per paragraph and return the scene paths."""
    load_env()
    text = _load_script_text(script)
    paragraphs = _split_into_paragraphs(text)
    if not paragraphs:
        raise ValueError("Script produced no paragraphs to animate.")
    log.info("Rendering %d scene(s).", len(paragraphs))

    # Lazy import: fail clearly if manim isn't installed.
    try:
        from manim import tempconfig
    except ImportError as exc:
        raise RuntimeError(
            "manim is not installed. Run `pip install manim` before using the "
            "animation agent."
        ) from exc

    OUTPUT_DIR.mkdir(exist_ok=True)
    media_dir = OUTPUT_DIR / "manim_media"

    scene_paths: list[str] = []
    for i, paragraph in enumerate(paragraphs, 1):
        duration = _estimate_seconds(paragraph)
        caption = _short_caption(paragraph)
        scene_name = f"scene_{i:02d}"
        log.info("  %s — ~%.1fs (%d words).", scene_name, duration,
                 len(paragraph.split()))

        SceneClass = _build_scene_class(duration, caption, variant=i - 1)
        with tempconfig(
            {
                "pixel_width": PIXEL_WIDTH,
                "pixel_height": PIXEL_HEIGHT,
                "frame_rate": FRAME_RATE,
                "background_color": BG_COLOR,
                "media_dir": str(media_dir),
                "output_file": scene_name,
                "verbosity": "ERROR",
                "disable_caching": True,
            }
        ):
            scene = SceneClass()
            scene.render()
            rendered = scene.renderer.file_writer.movie_file_path

        # Copy the rendered file to a stable, flat location in output/.
        dest = OUTPUT_DIR / f"{scene_name}.mp4"
        shutil.copyfile(rendered, dest)
        scene_paths.append(str(dest))

    log.info("Rendered %d scenes into %s", len(scene_paths), OUTPUT_DIR)
    return scene_paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Manim stickman scene renderer.")
    parser.add_argument("--script", help="Script text or path (default output/script.txt).")
    args = parser.parse_args()
    paths = run(args.script)
    for p in paths:
        print(p)


if __name__ == "__main__":
    main()
