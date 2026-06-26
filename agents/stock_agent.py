"""Stock Footage Agent — builds scenes from real stock video clips (option B).

A drop-in alternative to the animation agent: for each script paragraph it asks
Claude for a short visual search query, fetches a matching clip from a free
stock provider (Pexels by default, Pixabay optional), and renders it to a
uniform output/scene_NN.mp4 (1920x1080, H.264, 30 fps, no audio) so the
assembly agent can concatenate + narrate it exactly as it does animation scenes.

Requires a free API key (see DEPLOY.md):
    PEXELS_API_KEY=...        # https://www.pexels.com/api/  (free, instant)
    # or:
    STOCK_SOURCE=pixabay
    PIXABAY_API_KEY=...       # https://pixabay.com/api/docs/

Output: output/scene_01.mp4, output/scene_02.mp4, ...
Returns: the ordered list of scene file paths.

Run standalone:
    python -m agents.stock_agent                     # uses output/script.txt
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile

import requests

from agents.animation_agent import _estimate_seconds, _split_into_paragraphs
from agents.common import (
    OUTPUT_DIR,
    anthropic_client,
    anthropic_model,
    get_logger,
    load_env,
)

log = get_logger("stock")

PIXEL_WIDTH = 1920
PIXEL_HEIGHT = 1080
FRAME_RATE = 30
HTTP_TIMEOUT = 30

HTTP = requests.Session()
HTTP.headers.update({"User-Agent": "mystery-agent/1.0 (stock footage fetcher)"})


# --- Visual search queries ---------------------------------------------------
def _extract_era(topic_hint: str, paragraphs: list[str]) -> str:
    """Guess the historical era from the topic/script for era-aware queries."""
    combined = (topic_hint + " " + " ".join(paragraphs[:3])).lower()
    if any(str(y) in combined for y in range(1900, 1970)):
        return "vintage 1950s archival"
    if any(str(y) in combined for y in range(1970, 1990)):
        return "vintage 1970s archival"
    if "ancient" in combined or "medieval" in combined:
        return "ancient historical"
    return ""


def _search_queries(topic_hint: str, paragraphs: list[str]) -> list[str]:
    """One short stock-search query per paragraph (atmospheric b-roll)."""
    fallback = [topic_hint or "dark mysterious atmosphere"] * len(paragraphs)
    era = _extract_era(topic_hint, paragraphs)
    try:
        client = anthropic_client()
        numbered = "\n".join(f"{i}. {p[:200]}" for i, p in enumerate(paragraphs))
        era_guidance = (
            f"IMPORTANT: This story is set in the era: {era}. "
            "All queries must reflect that time period — no modern technology, "
            "no drones, no SUVs, no modern clothing, no smartphones. "
            "Use: vintage film grain, archival footage, period-appropriate gear, "
            "Soviet-era or mid-century aesthetics where relevant.\n\n"
        ) if era else ""
        prompt = (
            "You pick stock-video b-roll for a faceless mystery documentary. "
            "For each paragraph, give a SHORT search query (2-4 words) for "
            "atmospheric, non-specific footage that fits the mood — e.g. "
            "'snowy mountains night', 'abandoned tent snow', 'dark forest fog', "
            "'old documents desk', 'candle dark room'. Prefer landscapes, "
            "nature, weather, objects; avoid recognizable faces or modern text.\n\n"
            + era_guidance +
            "STRICT RULES:\n"
            "- No drones, no aerial modern shots\n"
            "- No modern vehicles (SUV, cars post-1970)\n"
            "- No modern clothing or gear\n"
            "- Prefer: wilderness, snow, forests, old maps, vintage equipment, "
            "candlelight, fog, mountains, archival textures\n\n"
            f"TOPIC: {topic_hint}\n\nPARAGRAPHS:\n{numbered}\n\n"
            "Reply with ONLY a JSON array of query strings, length exactly "
            f"{len(paragraphs)}."
        )
        resp = client.messages.create(
            model=anthropic_model(), max_tokens=500,
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
        log.warning("Claude query generation failed (%s) — using topic hint.", exc)
        return fallback


# --- Providers ---------------------------------------------------------------
def _pexels_pick(query: str, used: set[int]) -> tuple[int, str] | None:
    """Return (video_id, download_url) for a landscape HD clip from Pexels."""
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        raise RuntimeError(
            "PEXELS_API_KEY is not set. Get a free key at "
            "https://www.pexels.com/api/ and add it to config/apis.env."
        )
    resp = HTTP.get(
        "https://api.pexels.com/videos/search",
        headers={"Authorization": key},
        params={"query": query, "per_page": 15, "orientation": "landscape",
                "size": "medium"},
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    for v in resp.json().get("videos", []):
        if v["id"] in used:
            continue
        # Prefer a file at least 1920 wide, else the widest available.
        files = sorted(v.get("video_files", []),
                       key=lambda f: (f.get("width") or 0), reverse=True)
        hd = [f for f in files if (f.get("width") or 0) >= 1280 and f.get("link")]
        chosen = (hd[0] if hd else (files[0] if files else None))
        if chosen and chosen.get("link"):
            return v["id"], chosen["link"]
    return None


def _pixabay_pick(query: str, used: set[int]) -> tuple[int, str] | None:
    """Return (video_id, download_url) for a clip from Pixabay."""
    key = os.environ.get("PIXABAY_API_KEY")
    if not key:
        raise RuntimeError(
            "PIXABAY_API_KEY is not set. Get a free key at "
            "https://pixabay.com/api/docs/ and add it to config/apis.env."
        )
    resp = HTTP.get(
        "https://pixabay.com/api/videos/",
        params={"key": key, "q": query, "per_page": 15},
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    for v in resp.json().get("hits", []):
        if v["id"] in used:
            continue
        streams = v.get("videos", {})
        for size in ("large", "medium", "small"):
            link = streams.get(size, {}).get("url")
            if link:
                return v["id"], link
    return None


def _pick_clip(query: str, used: set[int]):
    source = os.environ.get("STOCK_SOURCE", "pexels").lower()
    return _pixabay_pick(query, used) if source == "pixabay" else _pexels_pick(query, used)


# --- Clip processing ---------------------------------------------------------
def _download(url: str, dest: str) -> None:
    with HTTP.get(url, stream=True, timeout=HTTP_TIMEOUT) as r:
        r.raise_for_status()
        with open(dest, "wb") as fh:
            for chunk in r.iter_content(chunk_size=1 << 16):
                fh.write(chunk)


def _encode_scene(src: str, dest: str, duration: float) -> None:
    """Normalize a clip to 1920x1080 H.264 30fps, no audio, exact duration.

    Loops the source if it's shorter than the paragraph's narration slot.
    """
    vf = (
        f"scale={PIXEL_WIDTH}:{PIXEL_HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={PIXEL_WIDTH}:{PIXEL_HEIGHT},setsar=1,fps={FRAME_RATE}"
    )
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-stream_loop", "-1", "-i", src,   # loop input as needed
        "-t", f"{duration:.2f}",
        "-vf", vf, "-an",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-r", str(FRAME_RATE), dest,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg encode failed: {proc.stderr.strip()[:400]}")


# --- Public entry point ------------------------------------------------------
def run(script: str | None = None, topic_hint: str = "") -> list[str]:
    """Build stock-footage scenes for the script; return scene file paths."""
    load_env()
    # Reuse the animation agent's loader/splitter for parity.
    from agents.animation_agent import _load_script_text

    text = _load_script_text(script)
    paragraphs = _split_into_paragraphs(text)
    if not paragraphs:
        raise ValueError("Script produced no paragraphs.")
    log.info("Building %d stock scene(s).", len(paragraphs))

    queries = _search_queries(topic_hint, paragraphs)
    OUTPUT_DIR.mkdir(exist_ok=True)

    used: set[int] = set()
    scene_paths: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, paragraph in enumerate(paragraphs, 1):
            duration = _estimate_seconds(paragraph)
            query = queries[i - 1]
            scene_name = f"scene_{i:02d}"
            log.info("  %s — query '%s' (~%.1fs).", scene_name, query, duration)

            pick = _pick_clip(query, used)
            if not pick:  # widen the search if the specific query found nothing
                pick = _pick_clip(topic_hint or "dark atmosphere", used)
            if not pick:
                raise RuntimeError(f"No stock clip found for '{query}'.")

            vid_id, link = pick
            used.add(vid_id)
            raw = os.path.join(tmp, f"{scene_name}.mp4")
            _download(link, raw)

            dest = OUTPUT_DIR / f"{scene_name}.mp4"
            _encode_scene(raw, str(dest), duration)
            scene_paths.append(str(dest))

    log.info("Built %d stock scenes into %s", len(scene_paths), OUTPUT_DIR)
    return scene_paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Stock footage scene builder.")
    parser.add_argument("--script", help="Script text or path (default output/script.txt).")
    parser.add_argument("--topic", default="", help="Topic hint for fallback queries.")
    args = parser.parse_args()
    for p in run(args.script, topic_hint=args.topic):
        print(p)


if __name__ == "__main__":
    main()
