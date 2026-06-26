"""Higgsfield Agent — cinematic AI video scenes via Higgsfield MCP server.

Claude connects to the Higgsfield MCP server (https://mcp.higgsfield.ai/mcp)
and calls its video-generation tools directly. For each script paragraph Claude
writes a cinematic prompt and generates a short video clip saved as scene_NN.mp4.

Setup in config/apis.env:
  VISUAL_MODE=higgsfield
  HIGGSFIELD_MCP_URL=https://mcp.higgsfield.ai/mcp
  HIGGSFIELD_API_KEY=<key>        # higgsfield.ai -> Settings -> API Keys

Optional tunables:
  HIGGSFIELD_ASPECT=16:9
  HIGGSFIELD_DURATION=5           # seconds per clip (default: estimated from words)
  HIGGSFIELD_TIMEOUT=300          # max seconds to wait per clip

Output: output/scene_01.mp4, ... ; returns ordered scene paths.

Run standalone:
    python -m agents.higgsfield_agent --topic "Dyatlov Pass incident"
    python -m agents.higgsfield_agent --script output/script.txt --topic "..."
"""
from __future__ import annotations

import argparse
import os
import re

import requests

from agents.animation_agent import (
    _estimate_seconds,
    _load_script_text,
    _split_into_paragraphs,
)
from agents.common import (
    OUTPUT_DIR,
    anthropic_client,
    anthropic_model,
    get_logger,
    load_env,
)

log = get_logger("higgsfield")

STYLE_SUFFIX = (
    ", cinematic documentary style, dark moody atmosphere, dramatic lighting, "
    "4K quality, no text overlays, no visible human faces"
)

HTTP = requests.Session()
HTTP.headers.update({"User-Agent": "mystery-agent/1.0"})


def _higgsfield_key() -> str:
    key = os.environ.get("HIGGSFIELD_API_KEY", "")
    if not key:
        raise RuntimeError(
            "HIGGSFIELD_API_KEY is not set. Add it to config/apis.env.\n"
            "Get your key at higgsfield.ai -> Settings -> API Keys."
        )
    return key


def _mcp_url() -> str:
    return os.environ.get("HIGGSFIELD_MCP_URL", "https://mcp.higgsfield.ai/mcp")


# --- Core: Claude + Higgsfield MCP -------------------------------------------

def _generate_scene_via_mcp(
    scene_name: str,
    video_prompt: str,
    duration: float,
    dest: str,
) -> None:
    """Ask Claude to generate one video clip using the Higgsfield MCP server."""
    client = anthropic_client()
    aspect = os.environ.get("HIGGSFIELD_ASPECT", "16:9")
    clip_seconds = max(2, min(10, round(duration)))
    timeout = int(os.environ.get("HIGGSFIELD_TIMEOUT", "300"))

    full_prompt = video_prompt + STYLE_SUFFIX

    task = (
        f"Generate a {clip_seconds}-second cinematic video clip using the Higgsfield "
        f"video generation tool. Use this prompt exactly:\n\n"
        f'"{full_prompt}"\n\n'
        f"Aspect ratio: {aspect}. Duration: {clip_seconds} seconds.\n"
        f"Wait for the generation to complete (poll if needed, up to {timeout}s), "
        f"then return ONLY the final video download URL — nothing else."
    )

    resp = client.beta.messages.create(
        model=anthropic_model(),
        max_tokens=1024,
        messages=[{"role": "user", "content": task}],
        mcp_servers=[
            {
                "type": "url",
                "url": _mcp_url(),
                "name": "higgsfield",
                "authorization_token": _higgsfield_key(),
            }
        ],
        betas=["mcp-client-2025-04-04"],
    )

    # Extract the video URL from Claude's final text response.
    video_url = None
    for block in resp.content:
        if hasattr(block, "text"):
            urls = re.findall(r"https?://\S+\.mp4\S*", block.text)
            if urls:
                video_url = urls[0].rstrip(".,)")
                break
            # Fallback: grab any https URL in the reply.
            urls = re.findall(r"https?://\S+", block.text)
            if urls:
                video_url = urls[0].rstrip(".,)")
                break

    if not video_url:
        raw = " | ".join(
            getattr(b, "text", repr(b))[:200] for b in resp.content
        )
        raise RuntimeError(
            f"Higgsfield MCP returned no video URL for {scene_name}. "
            f"Claude response: {raw}"
        )

    log.info("    downloading %s from %s", scene_name, video_url[:80])
    r = HTTP.get(video_url, timeout=300, stream=True)
    r.raise_for_status()
    with open(dest, "wb") as fh:
        for chunk in r.iter_content(chunk_size=1 << 16):
            fh.write(chunk)


# --- Prompt generation -------------------------------------------------------

def _video_prompts(topic_hint: str, paragraphs: list[str]) -> list[str]:
    """Use Claude to write one cinematic video prompt per paragraph."""
    import json
    fallback = [f"{topic_hint}, mysterious cinematic scene" for _ in paragraphs]
    try:
        client = anthropic_client()
        numbered = "\n".join(f"{i}. {p[:220]}" for i, p in enumerate(paragraphs))
        prompt = (
            "You write text-to-video prompts for a faceless mystery documentary "
            "on YouTube. For each paragraph write ONE vivid, concrete prompt "
            "describing a short cinematic video clip: atmosphere, location, "
            "motion, lighting. No real or named people, no on-screen text. "
            "Keep each prompt under 30 words.\n\n"
            f"TOPIC: {topic_hint}\n\nPARAGRAPHS:\n{numbered}\n\n"
            "Reply with ONLY a JSON array of prompt strings, length exactly "
            f"{len(paragraphs)}."
        )
        resp = client.messages.create(
            model=anthropic_model(),
            max_tokens=1200,
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


# --- Public entry point ------------------------------------------------------

def run(script: str | None = None, topic_hint: str = "") -> list[str]:
    """Generate Higgsfield video scenes for the script; return scene file paths."""
    load_env()
    text = _load_script_text(script)
    paragraphs = _split_into_paragraphs(text)
    if not paragraphs:
        raise ValueError("Script produced no paragraphs.")

    log.info(
        "Generating %d Higgsfield scene(s) via MCP (%s).",
        len(paragraphs), _mcp_url(),
    )

    prompts = _video_prompts(topic_hint, paragraphs)
    OUTPUT_DIR.mkdir(exist_ok=True)

    scene_paths: list[str] = []
    for i, paragraph in enumerate(paragraphs, 1):
        duration = _estimate_seconds(paragraph)
        prompt = prompts[i - 1]
        scene_name = f"scene_{i:02d}"
        dest = str(OUTPUT_DIR / f"{scene_name}.mp4")
        log.info("  %s — '%s' (~%.1fs).", scene_name, prompt[:60], duration)
        _generate_scene_via_mcp(scene_name, prompt, duration, dest)
        scene_paths.append(dest)
        log.info("    saved → %s", dest)

    log.info("Generated %d scenes into %s.", len(scene_paths), OUTPUT_DIR)
    return scene_paths


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Higgsfield AI video scene generator (Claude MCP)."
    )
    parser.add_argument(
        "--script", help="Script text or path (default output/script.txt)."
    )
    parser.add_argument("--topic", default="", help="Topic hint for prompts.")
    args = parser.parse_args()
    for p in run(args.script, topic_hint=args.topic):
        print(p)


if __name__ == "__main__":
    main()
