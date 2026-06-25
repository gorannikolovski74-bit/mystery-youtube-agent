"""TTS Agent — turns the script into narration audio with Kokoro TTS.

Kokoro is an open-source ONNX TTS model: free, runs locally on the Droplet,
no API limits. This agent reads the script text, synthesizes speech in chunks
(so very long scripts don't hit model input limits), concatenates the audio,
and writes output/narration.wav.

Model files (download once, see README / HANDOFF):
    kokoro-v1.0.onnx
    voices.bin
Their location is configurable via env:
    KOKORO_MODEL=/path/to/kokoro-v1.0.onnx
    KOKORO_VOICES=/path/to/voices.bin
    KOKORO_VOICE=af_sky        # voice id (e.g. af_sky, am_michael)
    KOKORO_SPEED=0.95          # 1.0 = normal; slightly slower suits mystery

Run standalone:
    python -m agents.tts_agent                       # reads output/script.txt
    python -m agents.tts_agent --script output/script.txt --voice am_michael
"""
from __future__ import annotations

import argparse
import os
import re

from agents.common import OUTPUT_DIR, get_logger, load_env

log = get_logger("tts")

# Defaults — overridable via env (see module docstring).
DEFAULT_MODEL = "kokoro-v1.0.onnx"
DEFAULT_VOICES = "voices.bin"
DEFAULT_VOICE = "af_sky"
DEFAULT_SPEED = 0.95
DEFAULT_LANG = "en-us"

# Keep each synthesis chunk well under the model's input limit while ending
# chunks on sentence boundaries for natural prosody.
MAX_CHUNK_CHARS = 600

OUTPUT_WAV = OUTPUT_DIR / "narration.wav"


def _resolve_paths() -> tuple[str, str]:
    """Return (model_path, voices_path), erroring early if they're missing."""
    model = os.environ.get("KOKORO_MODEL", DEFAULT_MODEL)
    voices = os.environ.get("KOKORO_VOICES", DEFAULT_VOICES)
    missing = [p for p in (model, voices) if not os.path.exists(p)]
    if missing:
        raise FileNotFoundError(
            "Kokoro model file(s) not found: "
            + ", ".join(missing)
            + ". Download kokoro-v1.0.onnx and voices.bin (see README) or set "
            "KOKORO_MODEL / KOKORO_VOICES."
        )
    return model, voices


def _split_into_chunks(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split text into chunks that end on sentence boundaries where possible."""
    # Split on sentence-ending punctuation, keeping the punctuation attached.
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if not sentence:
            continue
        # A single very long sentence still has to be emitted on its own.
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
    """Accept the script text directly, or fall back to output/script.txt."""
    if script and not script.strip().endswith(".txt"):
        # Treat as raw script text when it's clearly not a path.
        if "\n" in script or len(script) > 200:
            return script.strip()
    path = script if script else str(OUTPUT_DIR / "script.txt")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    # Last resort: the argument *was* the script text.
    if script:
        return script.strip()
    raise FileNotFoundError(f"No script text and {path} does not exist.")


def run(script: str | None = None) -> str:
    """Synthesize narration from the script and return the output WAV path."""
    load_env()
    text = _load_script_text(script)
    if not text:
        raise ValueError("Script text is empty — nothing to synthesize.")

    model_path, voices_path = _resolve_paths()
    voice = os.environ.get("KOKORO_VOICE", DEFAULT_VOICE)
    speed = float(os.environ.get("KOKORO_SPEED", DEFAULT_SPEED))
    lang = os.environ.get("KOKORO_LANG", DEFAULT_LANG)

    # Imported lazily so the rest of the pipeline doesn't require these deps.
    import numpy as np
    import soundfile as sf
    from kokoro_onnx import Kokoro

    kokoro = Kokoro(model_path, voices_path)

    chunks = _split_into_chunks(text)
    log.info("Synthesizing %d chunk(s) with voice '%s' at speed %.2f.",
             len(chunks), voice, speed)

    audio_parts: list = []
    sample_rate = 24000  # Kokoro default; overwritten by the real value below.
    for i, chunk in enumerate(chunks, 1):
        samples, sample_rate = kokoro.create(
            chunk, voice=voice, speed=speed, lang=lang
        )
        audio_parts.append(samples)
        # A short silence between chunks keeps sentence transitions natural.
        audio_parts.append(np.zeros(int(sample_rate * 0.25), dtype=samples.dtype))
        log.info("  chunk %d/%d done (%d chars).", i, len(chunks), len(chunk))

    narration = np.concatenate(audio_parts)
    OUTPUT_DIR.mkdir(exist_ok=True)
    sf.write(str(OUTPUT_WAV), narration, sample_rate)

    duration = len(narration) / sample_rate
    log.info("Narration written to %s (%.1f s).", OUTPUT_WAV, duration)
    return str(OUTPUT_WAV)


def main() -> None:
    parser = argparse.ArgumentParser(description="Kokoro TTS narration generator.")
    parser.add_argument("--script", help="Script text or path (default output/script.txt).")
    parser.add_argument("--voice", help="Override KOKORO_VOICE (e.g. af_sky, am_michael).")
    parser.add_argument("--speed", type=float, help="Override KOKORO_SPEED.")
    args = parser.parse_args()

    if args.voice:
        os.environ["KOKORO_VOICE"] = args.voice
    if args.speed:
        os.environ["KOKORO_SPEED"] = str(args.speed)

    out = run(args.script)
    print(out)


if __name__ == "__main__":
    main()
