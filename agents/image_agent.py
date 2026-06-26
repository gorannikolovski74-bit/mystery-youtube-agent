"""AI Image Agent — builds scenes from generated images + motion (option A).

A drop-in alternative to the animation/stock agents: for each script paragraph
Claude writes a cinematic image prompt, an image is generated, and a slow
"Ken Burns" zoom/pan turns it into a 1920x1080 H.264 clip for that paragraph.
Output scene_NN.mp4 files are uniform so the assembly agent narrates them
exactly as before.

Image provider (env IMAGE_PROVIDER):
  * "pollinations" (default) — free, no API key (Flux-based).
  * "openai"  — needs OPENAI_API_KEY (gpt-image-1). Higher quality, paid.
  * Both honor IMAGE_MODEL when relevant.

Output: output/scene_01.mp4, ... ; returns the ordered scene paths.

Run standalone:
    python -m agents.image_agent --topic "Dyatlov Pass incident"
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import tempfile
import urllib.parse

import requests

from agents.animation_agent import _estimate_seconds, _split_into_paragraphs
from agents.common import (
    OUTPUT_DIR,
    anthropic_client,
    anthropic_model,
    get_logger,
    load_env,
)

log = get_logger("image")

PIXEL_WIDTH = 1920
PIXEL_HEIGHT = 1080
FRAME_RATE = 30
HTTP_TIMEOUT = 120

HTTP = requests.Session()
HTTP.headers.update({"User-Agent": "mystery-agent/1.0 (image fetcher)"})

STYLE_SUFFIX = (
    ", dark moody cinematic atmosphere, dramatic lighting, photorealistic, "
    "highly detailed, no text, no watermark, no people faces"
)


# --- Prompts -----------------------------------------------------------------
def _image_prompts(topic_hint: str, paragraphs: list[str]) -> list[str]:
    """One cinematic image prompt per paragraph."""
    fallback = [f"{topic_hint}, mysterious dark scene" for _ in paragraphs]
    try:
        client = anthropic_client()
        numbered = "\n".join(f"{i}. {p[:220]}" for i, p in enumerate(paragraphs))
        prompt = (
            "You write image-generation prompts for a faceless mystery "
            "documentary. For each paragraph, write ONE vivid, concrete scene "
            "description (a place, object, or atmosphere) — landscapes, weather, "
            "objects, interiors. No real or named people, no on-screen text. "
            "Keep each under 25 words.\n\n"
            f"TOPIC: {topic_hint}\n\nPARAGRAPHS:\n{numbered}\n\n"
            "Reply with ONLY a JSON array of prompt strings, length exactly "
            f"{len(paragraphs)}."
        )
        resp = client.messages.create(
            model=anthropic_model(), max_tokens=1200,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        start, end = text.find("["), text.rfind("]")
        arr = json.loads(text[start : end + 1])
        return [
            (str(arr[i]).strip() if i < len(arr) and str(arr[i]).strip() else fallback[i])
            for i in range(len(paragraphs))
        ]
    except Exception as exc:
        log.warning("Claude prompt generation failed (%s) — using topic hint.", exc)
        return fallback


# --- Image providers ---------------------------------------------------------
def _fetch_pollinations(prompt: str, seed: int, dest: str) -> None:
    import time
    encoded = urllib.parse.quote(prompt + STYLE_SUFFIX)
    url = f"https://image.pollinations.ai/prompt/{encoded}"
    for attempt in range(4):
        try:
            resp = HTTP.get(
                url,
                params={"width": 1280, "height": 720, "nologo": "true",
                        "model": os.environ.get("IMAGE_MODEL", "flux"), "seed": seed + attempt},
                timeout=HTTP_TIMEOUT,
            )
            resp.raise_for_status()
            with open(dest, "wb") as fh:
                fh.write(resp.content)
            return
        except Exception as exc:
            if attempt == 3:
                raise
            wait = 2 ** attempt
            log.warning("Pollinations attempt %d failed (%s) — retrying in %ds.", attempt + 1, exc, wait)
            time.sleep(wait)


def _fetch_openai(prompt: str, seed: int, dest: str) -> None:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY not set for IMAGE_PROVIDER=openai.")
    resp = HTTP.post(
        "https://api.openai.com/v1/images/generations",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": os.environ.get("IMAGE_MODEL", "gpt-image-1"),
            "prompt": prompt + STYLE_SUFFIX,
            "size": "1536x1024",
            "n": 1,
        },
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    b64 = resp.json()["data"][0]["b64_json"]
    with open(dest, "wb") as fh:
        fh.write(base64.b64decode(b64))


def _fetch_image(prompt: str, seed: int, dest: str) -> None:
    provider = os.environ.get("IMAGE_PROVIDER", "pollinations").lower()
    if provider == "openai":
        _fetch_openai(prompt, seed, dest)
    else:
        _fetch_pollinations(prompt, seed, dest)


# --- Ken Burns motion --------------------------------------------------------
def _kenburns(img: str, dest: str, duration: float, variant: int) -> None:
    """Render a slow zoom/pan clip from a still image (1920x1080, H.264)."""
    frames = max(1, round(duration * FRAME_RATE))
    # A few motion presets for variety; all zoom slightly to keep it alive.
    presets = [
        "z='min(zoom+0.0010,1.30)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'",
        "z='min(zoom+0.0007,1.22)':x='(iw-iw/zoom)*on/{d}':y='ih/2-(ih/zoom/2)'",
        "z='min(zoom+0.0007,1.22)':x='(iw-iw/zoom)*(1-on/{d})':y='ih/2-(ih/zoom/2)'",
        "z='min(zoom+0.0008,1.25)':x='iw/2-(iw/zoom/2)':y='(ih-ih/zoom)*(1-on/{d})'",
    ]
    motion = presets[variant % len(presets)].format(d=max(1, frames - 1))
    vf = (
        f"scale=3840:2160:force_original_aspect_ratio=increase,"
        f"crop=3840:2160,"
        f"zoompan={motion}:d={frames}:s={PIXEL_WIDTH}x{PIXEL_HEIGHT}:fps={FRAME_RATE},"
        f"setsar=1"
    )
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-loop", "1", "-framerate", str(FRAME_RATE), "-i", img,
        "-t", f"{duration:.2f}",
        "-vf", vf, "-an",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-r", str(FRAME_RATE), dest,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg ken-burns failed: {proc.stderr.strip()[:400]}")


# --- Public entry point ------------------------------------------------------
def run(script: str | None = None, topic_hint: str = "") -> list[str]:
    """Build AI-image scenes for the script; return scene file paths."""
    load_env()
    from agents.animation_agent import _load_script_text

    text = _load_script_text(script)
    paragraphs = _split_into_paragraphs(text)
    if not paragraphs:
        raise ValueError("Script produced no paragraphs.")
    log.info("Building %d AI-image scene(s) via %s.", len(paragraphs),
             os.environ.get("IMAGE_PROVIDER", "pollinations"))

    prompts = _image_prompts(topic_hint, paragraphs)
    OUTPUT_DIR.mkdir(exist_ok=True)

    scene_paths: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, paragraph in enumerate(paragraphs, 1):
            duration = _estimate_seconds(paragraph)
            prompt = prompts[i - 1]
            scene_name = f"scene_{i:02d}"
            log.info("  %s — '%s' (~%.1fs).", scene_name, prompt[:60], duration)

            img = os.path.join(tmp, f"{scene_name}.jpg")
            _fetch_image(prompt, seed=1000 + i, dest=img)

            dest = OUTPUT_DIR / f"{scene_name}.mp4"
            _kenburns(img, str(dest), duration, variant=i - 1)
            scene_paths.append(str(dest))

    log.info("Built %d AI-image scenes into %s", len(scene_paths), OUTPUT_DIR)
    return scene_paths


def main() -> None:
    parser = argparse.ArgumentParser(description="AI-image scene builder (Ken Burns).")
    parser.add_argument("--script", help="Script text or path (default output/script.txt).")
    parser.add_argument("--topic", default="", help="Topic hint for prompts.")
    args = parser.parse_args()
    for p in run(args.script, topic_hint=args.topic):
        print(p)


if __name__ == "__main__":
    main()
