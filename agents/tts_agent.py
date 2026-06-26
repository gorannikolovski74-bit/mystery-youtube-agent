"""TTS Agent — turns the script into narration audio.

Supports two backends (set TTS_BACKEND in config/apis.env):

  edge  (default) — Microsoft Edge TTS, free, no model files, works anywhere.
                    pip install edge-tts
                    Voice: TTS_VOICE=en-US-GuyNeural  (or any Edge voice)

  kokoro          — Local Kokoro ONNX model, no API limits, higher quality.
                    Requires kokoro-v1.0.onnx + voices.bin (see README).
                    pip install kokoro-onnx soundfile numpy

Output: output/narration.wav  (also returned as a string path).

Run standalone:
    python -m agents.tts_agent
    python -m agents.tts_agent --script output/script.txt --voice en-GB-RyanNeural
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re

from agents.common import OUTPUT_DIR, get_logger, load_env

log = get_logger("tts")

OUTPUT_WAV = OUTPUT_DIR / "narration.wav"
OUTPUT_MP3 = OUTPUT_DIR / "narration.mp3"

MAX_CHUNK_CHARS = 600


def _split_into_chunks(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if not sentence:
            continue
        if len(sentence) > max_chars:
            if current:
                chunks.append(current.strip())
                current = ""
            chunks.append(sentence.strip())
            continue
        if len(current) + len(sentence) + 1 <= max_chars:
            current = f"{current} {sentence}".strip()
        else:
            chunks.append(current.strip())
            current = sentence
    if current.strip():
        chunks.append(current.strip())
    return chunks


def _load_script_text(script: str | None) -> str:
    if script and not script.strip().endswith(".txt"):
        if "\n" in script or len(script) > 200:
            return script.strip()
    path = script if script else str(OUTPUT_DIR / "script.txt")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    if script:
        return script.strip()
    raise FileNotFoundError(f"No script text and {path} does not exist.")


# --- Edge TTS backend --------------------------------------------------------

async def _edge_synthesize(text: str, voice: str, output_path: str) -> None:
    import edge_tts
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)


def _run_edge(text: str) -> str:
    try:
        import edge_tts  # noqa: F401
    except ImportError:
        raise RuntimeError(
            "edge-tts is not installed. Run:  pip install edge-tts"
        )

    voice = os.environ.get("TTS_VOICE", "en-US-GuyNeural")
    out = str(OUTPUT_MP3)
    log.info("Edge TTS: voice=%s, output=%s", voice, out)
    OUTPUT_DIR.mkdir(exist_ok=True)
    asyncio.run(_edge_synthesize(text, voice, out))
    log.info("Narration written to %s", out)
    return out


# --- Kokoro backend ----------------------------------------------------------

def _run_kokoro(text: str) -> str:
    DEFAULT_MODEL = "kokoro-v1.0.onnx"
    DEFAULT_VOICES = "voices.bin"
    model = os.environ.get("KOKORO_MODEL", DEFAULT_MODEL)
    voices = os.environ.get("KOKORO_VOICES", DEFAULT_VOICES)
    missing = [p for p in (model, voices) if not os.path.exists(p)]
    if missing:
        raise FileNotFoundError(
            "Kokoro model file(s) not found: " + ", ".join(missing) +
            ". Download kokoro-v1.0.onnx and voices.bin or set KOKORO_MODEL/KOKORO_VOICES."
        )

    import numpy as np
    import soundfile as sf
    from kokoro_onnx import Kokoro

    voice = os.environ.get("KOKORO_VOICE", "af_sky")
    speed = float(os.environ.get("KOKORO_SPEED", "0.95"))
    lang = os.environ.get("KOKORO_LANG", "en-us")

    kokoro = Kokoro(model, voices)
    chunks = _split_into_chunks(text)
    log.info("Kokoro TTS: %d chunk(s), voice=%s, speed=%.2f", len(chunks), voice, speed)

    audio_parts: list = []
    sample_rate = 24000
    for i, chunk in enumerate(chunks, 1):
        samples, sample_rate = kokoro.create(chunk, voice=voice, speed=speed, lang=lang)
        audio_parts.append(samples)
        audio_parts.append(np.zeros(int(sample_rate * 0.25), dtype=samples.dtype))
        log.info("  chunk %d/%d done.", i, len(chunks))

    narration = np.concatenate(audio_parts)
    OUTPUT_DIR.mkdir(exist_ok=True)
    out = str(OUTPUT_WAV)
    sf.write(out, narration, sample_rate)
    log.info("Narration written to %s (%.1fs)", out, len(narration) / sample_rate)
    return out


# --- Public entry point ------------------------------------------------------

def run(script: str | None = None) -> str:
    """Synthesize narration from the script; return the output audio path."""
    load_env()
    text = _load_script_text(script)
    if not text:
        raise ValueError("Script text is empty — nothing to synthesize.")

    backend = os.environ.get("TTS_BACKEND", "edge").lower()
    if backend == "kokoro":
        return _run_kokoro(text)
    return _run_edge(text)


def main() -> None:
    parser = argparse.ArgumentParser(description="TTS narration generator.")
    parser.add_argument("--script", help="Script text or path (default output/script.txt).")
    parser.add_argument("--voice", help="Voice name (Edge: en-US-GuyNeural, Kokoro: af_sky).")
    parser.add_argument("--backend", help="TTS backend: edge (default) or kokoro.")
    args = parser.parse_args()

    if args.voice:
        os.environ["TTS_VOICE"] = args.voice
    if args.backend:
        os.environ["TTS_BACKEND"] = args.backend

    out = run(args.script)
    print(out)


if __name__ == "__main__":
    main()
