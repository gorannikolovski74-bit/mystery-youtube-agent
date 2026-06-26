"""Higgsfield Agent — cinematic AI video scenes via Higgsfield CLI + MCP.

Uses the official @higgsfield/cli tool (OAuth-authenticated) to generate
cinematic video clips for each script paragraph.

One-time setup:
  npm install -g @higgsfield/cli
  higgsfield auth login          # opens browser, saves token locally

Then set in config/apis.env:
  VISUAL_MODE=higgsfield

Optional tunables:
  HIGGSFIELD_MCP_URL=https://mcp.higgsfield.ai/mcp   # default
  HIGGSFIELD_ASPECT=16:9
  HIGGSFIELD_TIMEOUT=300         # max seconds to wait per clip

Output: output/scene_01.mp4, ... ; returns ordered scene paths.

Run standalone:
    python -m agents.higgsfield_agent --topic "Dyatlov Pass incident"
    python -m agents.higgsfield_agent --script output/script.txt --topic "..."
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess

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

MCP_URL = "https://mcp.higgsfield.ai/mcp"

STYLE_SUFFIX = (
    ", cinematic documentary style, dark moody atmosphere, dramatic lighting, "
    "4K quality, no text overlays, no visible human faces"
)

HTTP = requests.Session()
HTTP.headers.update({"User-Agent": "mystery-agent/1.0"})


def _cli_path() -> str:
    """Return the higgsfield CLI path, or raise if not installed."""
    path = shutil.which("higgsfield")
    if not path:
        raise RuntimeError(
            "Higgsfield CLI not found.\n"
            "Install it with:  npm install -g @higgsfield/cli\n"
            "Then auth once:   higgsfield auth login"
        )
    return path


def _mcp_url() -> str:
    return os.environ.get("HIGGSFIELD_MCP_URL", MCP_URL)


def _stored_token() -> str | None:
    """Return the Higgsfield auth token from env or CLI."""
    # Prefer explicit env var (set in config/apis.env).
    token = os.environ.get("HIGGSFIELD_API_KEY", "").strip()
    if token:
        return token

    # Fallback: ask the CLI.
    try:
        result = subprocess.run(
            [_cli_path(), "auth", "token"],
            capture_output=True, text=True, timeout=10,
        )
        token = result.stdout.strip()
        if token and not token.startswith("Error"):
            return token
    except Exception:
        pass

    return None


# --- Prompt generation -------------------------------------------------------

def _video_prompts(topic_hint: str, paragraphs: list[str]) -> list[str]:
    """Use Claude to write one cinematic video prompt per paragraph."""
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


# --- Scene generation --------------------------------------------------------

def _generate_via_mcp_client(
    scene_name: str, video_prompt: str, duration: float, dest: str
) -> None:
    """Use Claude + Higgsfield MCP server (OAuth token from CLI) to generate a clip."""
    client = anthropic_client()
    token = _stored_token()
    if not token:
        raise RuntimeError(
            "No Higgsfield auth token found. Run:  higgsfield auth login"
        )

    aspect = os.environ.get("HIGGSFIELD_ASPECT", "16:9")
    clip_seconds = max(2, min(10, round(duration)))
    timeout = int(os.environ.get("HIGGSFIELD_TIMEOUT", "300"))
    full_prompt = video_prompt + STYLE_SUFFIX

    task = (
        f"Generate a {clip_seconds}-second cinematic video clip using the Higgsfield "
        f"video generation tool. Prompt:\n\n\"{full_prompt}\"\n\n"
        f"Aspect ratio: {aspect}. Duration: {clip_seconds}s. "
        f"Wait for completion (up to {timeout}s), then return ONLY the download URL."
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
                "authorization_token": token,
            }
        ],
        betas=["mcp-client-2025-04-04"],
    )

    video_url = None
    for block in resp.content:
        if hasattr(block, "text"):
            urls = re.findall(r"https?://\S+\.mp4\S*", block.text)
            if urls:
                video_url = urls[0].rstrip(".,)")
                break
            urls = re.findall(r"https?://\S+", block.text)
            if urls:
                video_url = urls[0].rstrip(".,)")
                break

    if not video_url:
        raw = " | ".join(getattr(b, "text", repr(b))[:200] for b in resp.content)
        raise RuntimeError(
            f"No video URL returned for {scene_name}. Claude said: {raw}"
        )

    log.info("    downloading %s from %s", scene_name, video_url[:80])
    r = HTTP.get(video_url, timeout=300, stream=True)
    r.raise_for_status()
    with open(dest, "wb") as fh:
        for chunk in r.iter_content(chunk_size=1 << 16):
            fh.write(chunk)


def _generate_via_cli(
    scene_name: str, video_prompt: str, duration: float, dest: str
) -> None:
    """Fallback: call the higgsfield CLI directly via subprocess."""
    cli = _cli_path()
    clip_seconds = max(2, min(10, round(duration)))
    full_prompt = video_prompt + STYLE_SUFFIX

    cmd = [
        cli, "generate", "video",
        "--prompt", full_prompt,
        "--duration", str(clip_seconds),
        "--output", dest,
    ]
    aspect = os.environ.get("HIGGSFIELD_ASPECT", "16:9")
    cmd += ["--aspect-ratio", aspect]

    timeout = int(os.environ.get("HIGGSFIELD_TIMEOUT", "300"))
    log.info("    CLI: %s", " ".join(cmd[:6]) + " ...")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(
            f"higgsfield CLI failed for {scene_name}:\n{result.stderr[:400]}"
        )
    if not os.path.exists(dest):
        raise RuntimeError(
            f"CLI succeeded but {dest} not found. stdout: {result.stdout[:200]}"
        )


# --- Public entry point ------------------------------------------------------

def run(script: str | None = None, topic_hint: str = "") -> list[str]:
    """Generate Higgsfield video scenes for the script; return scene file paths."""
    load_env()
    text = _load_script_text(script)
    paragraphs = _split_into_paragraphs(text)
    if not paragraphs:
        raise ValueError("Script produced no paragraphs.")

    log.info("Generating %d Higgsfield scene(s).", len(paragraphs))

    prompts = _video_prompts(topic_hint, paragraphs)
    OUTPUT_DIR.mkdir(exist_ok=True)

    # Prefer MCP client (token auto-discovered); fall back to CLI subprocess.
    token = _stored_token()
    use_mcp = token is not None
    if use_mcp:
        log.info("Auth token found — using MCP client.")
    else:
        log.info("No token found — trying CLI subprocess (needs `higgsfield auth login`).")

    scene_paths: list[str] = []
    for i, paragraph in enumerate(paragraphs, 1):
        duration = _estimate_seconds(paragraph)
        prompt = prompts[i - 1]
        scene_name = f"scene_{i:02d}"
        dest = str(OUTPUT_DIR / f"{scene_name}.mp4")
        log.info("  %s — '%s' (~%.1fs).", scene_name, prompt[:60], duration)

        if use_mcp:
            _generate_via_mcp_client(scene_name, prompt, duration, dest)
        else:
            _generate_via_cli(scene_name, prompt, duration, dest)

        scene_paths.append(dest)
        log.info("    saved → %s", dest)

    log.info("Generated %d scenes into %s.", len(scene_paths), OUTPUT_DIR)
    return scene_paths


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Higgsfield AI video scene generator."
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
