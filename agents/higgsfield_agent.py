"""Higgsfield Agent — cinematic AI video scenes via Higgsfield.ai API.

Drop-in alternative to animation/stock/image agents: for each script paragraph
Claude writes a cinematic video prompt, Higgsfield generates a short video clip,
and the clips are saved as scene_NN.mp4 for the assembly agent.

Setup:
  HIGGSFIELD_API_KEY=<key>   # higgsfield.ai -> Settings -> API Keys
  VISUAL_MODE=higgsfield     # in config/apis.env

Optional tunables:
  HIGGSFIELD_MODEL=higgsfield-1          # or higgsfield-1-turbo for speed
  HIGGSFIELD_ASPECT=16:9
  HIGGSFIELD_POLL_INTERVAL=5             # seconds between status polls
  HIGGSFIELD_TIMEOUT=300                 # max seconds to wait per clip

Output: output/scene_01.mp4, ... ; returns ordered scene paths.

Run standalone:
    python -m agents.higgsfield_agent --topic "Dyatlov Pass incident"
    python -m agents.higgsfield_agent --script output/script.txt --topic "..."
"""
from __future__ import annotations

import argparse
import json
import os
import time

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

API_BASE = "https://api.higgsfield.ai/v1"
HTTP_TIMEOUT = 60

# Cinematic style appended to every prompt — keeps mystery atmosphere consistent.
STYLE_SUFFIX = (
    ", cinematic documentary style, dark moody atmosphere, dramatic lighting, "
    "high quality, no text overlays, no people faces visible"
)

HTTP = requests.Session()


def _auth_headers() -> dict[str, str]:
    key = os.environ.get("HIGGSFIELD_API_KEY", "")
    if not key:
        raise RuntimeError(
            "HIGGSFIELD_API_KEY is not set. Add it to config/apis.env."
        )
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


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


# --- Higgsfield API ----------------------------------------------------------

def _submit_generation(prompt: str, duration: float) -> str:
    """Submit a video generation job; return the job id."""
    model = os.environ.get("HIGGSFIELD_MODEL", "higgsfield-1")
    aspect = os.environ.get("HIGGSFIELD_ASPECT", "16:9")
    # Higgsfield accepts duration in whole seconds (min 2, max 10 per clip).
    clip_seconds = max(2, min(10, round(duration)))

    payload = {
        "prompt": prompt + STYLE_SUFFIX,
        "model": model,
        "aspect_ratio": aspect,
        "duration": clip_seconds,
    }
    resp = HTTP.post(
        f"{API_BASE}/video/generate",
        headers=_auth_headers(),
        json=payload,
        timeout=HTTP_TIMEOUT,
    )
    if not resp.ok:
        raise RuntimeError(
            f"Higgsfield submit failed ({resp.status_code}): {resp.text[:300]}"
        )
    data = resp.json()
    job_id = data.get("id") or data.get("job_id") or data.get("generation_id")
    if not job_id:
        raise RuntimeError(f"No job id in Higgsfield response: {data}")
    return str(job_id)


def _poll_until_done(job_id: str) -> str:
    """Poll the job status until complete; return the video URL."""
    interval = float(os.environ.get("HIGGSFIELD_POLL_INTERVAL", "5"))
    timeout = float(os.environ.get("HIGGSFIELD_TIMEOUT", "300"))
    deadline = time.time() + timeout

    while time.time() < deadline:
        resp = HTTP.get(
            f"{API_BASE}/video/status/{job_id}",
            headers=_auth_headers(),
            timeout=HTTP_TIMEOUT,
        )
        if not resp.ok:
            raise RuntimeError(
                f"Higgsfield status check failed ({resp.status_code}): {resp.text[:200]}"
            )
        data = resp.json()
        status = (data.get("status") or "").lower()

        if status in ("completed", "succeeded", "success", "done"):
            url = (
                data.get("video_url")
                or data.get("output_url")
                or (data.get("output") or [None])[0]
            )
            if not url:
                raise RuntimeError(f"Job done but no video URL found: {data}")
            return str(url)

        if status in ("failed", "error", "cancelled"):
            raise RuntimeError(f"Higgsfield generation {job_id} failed: {data}")

        log.info("    [%s] status=%s — waiting %.0fs…", job_id[:8], status, interval)
        time.sleep(interval)

    raise TimeoutError(
        f"Higgsfield job {job_id} did not complete within {timeout}s."
    )


def _download(url: str, dest: str) -> None:
    resp = HTTP.get(url, timeout=300, stream=True)
    resp.raise_for_status()
    with open(dest, "wb") as fh:
        for chunk in resp.iter_content(chunk_size=1 << 16):
            fh.write(chunk)


# --- Public entry point ------------------------------------------------------

def run(script: str | None = None, topic_hint: str = "") -> list[str]:
    """Generate Higgsfield video scenes for the script; return scene file paths."""
    load_env()
    text = _load_script_text(script)
    paragraphs = _split_into_paragraphs(text)
    if not paragraphs:
        raise ValueError("Script produced no paragraphs.")

    model = os.environ.get("HIGGSFIELD_MODEL", "higgsfield-1")
    log.info(
        "Generating %d Higgsfield scene(s) with model=%s.", len(paragraphs), model
    )

    prompts = _video_prompts(topic_hint, paragraphs)
    OUTPUT_DIR.mkdir(exist_ok=True)

    scene_paths: list[str] = []
    for i, paragraph in enumerate(paragraphs, 1):
        duration = _estimate_seconds(paragraph)
        prompt = prompts[i - 1]
        scene_name = f"scene_{i:02d}"
        log.info("  %s — '%s' (~%.1fs).", scene_name, prompt[:60], duration)

        try:
            job_id = _submit_generation(prompt, duration)
            log.info("    submitted job %s.", job_id[:16])
            video_url = _poll_until_done(job_id)
            dest = str(OUTPUT_DIR / f"{scene_name}.mp4")
            _download(video_url, dest)
            scene_paths.append(dest)
            log.info("    saved → %s", dest)
        except Exception as exc:
            log.error("  Scene %s failed: %s", scene_name, exc)
            raise

    log.info("Generated %d Higgsfield scenes into %s.", len(scene_paths), OUTPUT_DIR)
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
