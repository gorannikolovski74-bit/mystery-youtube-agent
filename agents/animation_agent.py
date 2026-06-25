"""Animation Agent — renders a topic-relevant stickman scene per paragraph.

For each script paragraph the agent renders a short animated scene chosen from
a small visual vocabulary (intro, journey, night camp, discovery,
investigation, theory, conclusion) — each with a background, props and motion
(see assets/stickman/scenes.py). Claude acts as a "director", mapping every
paragraph to the most fitting scene; a deterministic narrative arc is used as a
fallback when Claude is unavailable.

Scene length is estimated from the paragraph's word count so the merged video
roughly matches the narration. Full subtitles are added later by Whisper in the
assembly agent.

Output: output/scene_01.mp4, output/scene_02.mp4, ...
Returns: the ordered list of scene file paths.

Run standalone:
    python -m agents.animation_agent                     # uses output/script.txt
    python -m agents.animation_agent --script output/script.txt
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil

from agents.common import (
    OUTPUT_DIR,
    anthropic_client,
    anthropic_model,
    get_logger,
    load_env,
)

log = get_logger("animation")

BG_COLOR = "#1a1a2e"

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
    parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(parts) > 1:
        return parts
    parts = [p.strip() for p in text.split("\n") if p.strip()]
    if len(parts) > 1:
        return parts
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


def _choose_templates(paragraphs: list[str]) -> list[str]:
    """Map each paragraph to a scene template, using Claude when available."""
    from assets.stickman.scenes import (
        TEMPLATE_DESCRIPTIONS,
        TEMPLATES,
        default_template_for,
    )

    total = len(paragraphs)
    fallback = [default_template_for(i, total) for i in range(total)]

    try:
        client = anthropic_client()
        catalog = "\n".join(f"- {k}: {v}" for k, v in TEMPLATE_DESCRIPTIONS.items())
        numbered = "\n".join(
            f"{i}. {p[:200]}" for i, p in enumerate(paragraphs)
        )
        prompt = (
            "You are a visual director for a faceless stickman mystery video. "
            "For each script paragraph, choose the single best scene template "
            "from this catalog (use the exact keys):\n"
            f"{catalog}\n\n"
            "Guidance: the first paragraph is usually 'intro' and the last is "
            "'conclusion'. Match the paragraph's content to the scene.\n\n"
            f"PARAGRAPHS:\n{numbered}\n\n"
            "Reply with ONLY a JSON array of template keys, one per paragraph, "
            f"length exactly {total}."
        )
        resp = client.messages.create(
            model=anthropic_model(),
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        start, end = text.find("["), text.rfind("]")
        chosen = json.loads(text[start : end + 1])
        result = []
        for i in range(total):
            key = str(chosen[i]).strip() if i < len(chosen) else fallback[i]
            result.append(key if key in TEMPLATES else fallback[i])
        log.info("Director scene plan: %s", result)
        return result
    except Exception as exc:
        log.warning("Claude director unavailable (%s) — using default arc.", exc)
        return fallback


def _build_scene_class(template_key: str, duration: float):
    """Create a Manim Scene that renders the chosen template for `duration` s."""
    from manim import Scene

    from assets.stickman.scenes import TEMPLATES

    builder = TEMPLATES[template_key]

    class _MysteryScene(Scene):
        def construct(self):
            self.camera.background_color = BG_COLOR
            builder(self, duration)

    return _MysteryScene


def run(script: str | None = None) -> list[str]:
    """Render one topic-relevant scene per paragraph; return the scene paths."""
    load_env()
    text = _load_script_text(script)
    paragraphs = _split_into_paragraphs(text)
    if not paragraphs:
        raise ValueError("Script produced no paragraphs to animate.")
    log.info("Rendering %d scene(s).", len(paragraphs))

    try:
        from manim import tempconfig
    except ImportError as exc:
        raise RuntimeError(
            "manim is not installed. Run `pip install manim` before using the "
            "animation agent."
        ) from exc

    templates = _choose_templates(paragraphs)

    OUTPUT_DIR.mkdir(exist_ok=True)
    media_dir = OUTPUT_DIR / "manim_media"

    scene_paths: list[str] = []
    for i, paragraph in enumerate(paragraphs, 1):
        duration = _estimate_seconds(paragraph)
        template_key = templates[i - 1]
        scene_name = f"scene_{i:02d}"
        log.info("  %s [%s] — ~%.1fs (%d words).", scene_name, template_key,
                 duration, len(paragraph.split()))

        SceneClass = _build_scene_class(template_key, duration)
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
