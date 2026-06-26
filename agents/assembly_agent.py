"""Assembly Agent — turns scenes + narration into the final video (FFmpeg).

Pipeline (from HANDOFF):
  1. Concatenate the stickman scenes into one clip.
  2. Mux the narration audio onto the merged video.
  3. Transcribe the narration with Whisper and burn timed subtitles in.
  4. Mix quiet background music underneath (optional).

Each stage is optional-aware: if Whisper isn't installed or no music is found,
that stage is skipped with a warning rather than failing the whole pipeline.

Inputs:
    scenes — ordered list of scene .mp4 paths (from the animation agent)
    audio  — path to narration.wav (from the tts agent)
Output: output/final_video.mp4  (1920x1080, H.264)  — also returned.

Run standalone (after animation + tts have produced their files):
    python -m agents.assembly_agent
"""
from __future__ import annotations

import argparse
import glob
import os
import subprocess

from agents.common import ASSETS_DIR, OUTPUT_DIR, get_logger, load_env

log = get_logger("assembly")

# Intermediate + final artifact paths.
SCENES_LIST = OUTPUT_DIR / "scenes_list.txt"
MERGED = OUTPUT_DIR / "scenes_merged.mp4"
WITH_AUDIO = OUTPUT_DIR / "with_audio.mp4"
SRT_FILE = OUTPUT_DIR / "narration.srt"
WITH_SUBS = OUTPUT_DIR / "with_subtitles.mp4"
FINAL = OUTPUT_DIR / "final_video.mp4"

# Subtitle styling (matches config/style_profile.md: white, bold, lower third).
SUBTITLE_STYLE = "FontName=Arial,Bold=1,FontSize=18,PrimaryColour=&H00FFFFFF,Outline=1,Shadow=0"

# Background music: quiet so narration stays clear.
MUSIC_VOLUME = float(os.environ.get("MUSIC_VOLUME", "0.08"))
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "base")


def _run_ffmpeg(args: list[str], cwd: str | None = None) -> None:
    """Run an ffmpeg command, raising with captured output on failure."""
    cmd = ["ffmpeg", "-y", "-loglevel", "error", *args]
    log.info("ffmpeg %s", " ".join(args[:6]) + (" ..." if len(args) > 6 else ""))
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr.strip()[:500]}")


def _concat_scenes(scenes: list[str]) -> None:
    """Concatenate scene clips into MERGED using the concat demuxer."""
    if not scenes:
        raise ValueError("No scenes provided to assemble.")
    lines = []
    for path in scenes:
        abspath = os.path.abspath(path)
        if not os.path.exists(abspath):
            raise FileNotFoundError(f"Scene file missing: {abspath}")
        # Escape single quotes for the concat list format.
        safe = abspath.replace("'", "'\\''")
        lines.append(f"file '{safe}'")
    SCENES_LIST.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Scenes share identical codec params (all from manim), so stream-copy.
    _run_ffmpeg([
        "-f", "concat", "-safe", "0", "-i", str(SCENES_LIST),
        "-c", "copy", str(MERGED),
    ])


def _add_narration(audio: str) -> None:
    """Mux narration audio onto the merged video (truncate to shorter stream)."""
    if not os.path.exists(audio):
        raise FileNotFoundError(f"Narration audio missing: {audio}")
    _run_ffmpeg([
        "-i", str(MERGED), "-i", str(audio),
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(WITH_AUDIO),
    ])


def _make_subtitles(audio: str) -> bool:
    """Transcribe narration to an SRT with Whisper. Returns True on success."""
    if os.environ.get("SUBTITLES", "1") == "0":
        log.info("Subtitles disabled via SUBTITLES=0.")
        return False
    try:
        import whisper  # heavy (torch); imported lazily
        from whisper.utils import get_writer
    except ImportError:
        log.warning("whisper not installed — skipping subtitles.")
        return False

    log.info("Transcribing narration with Whisper model '%s'.", WHISPER_MODEL)
    model = whisper.load_model(WHISPER_MODEL)
    result = model.transcribe(audio, language="en", verbose=False)
    writer = get_writer("srt", str(OUTPUT_DIR))
    # Writer names the file after the audio stem; normalize to SRT_FILE.
    writer(result, audio)
    produced = OUTPUT_DIR / (os.path.splitext(os.path.basename(audio))[0] + ".srt")
    if produced != SRT_FILE and produced.exists():
        produced.replace(SRT_FILE)
    return SRT_FILE.exists()


def _burn_subtitles() -> bool:
    """Burn SRT_FILE into the video. Returns True if subtitles were applied."""
    if not SRT_FILE.exists():
        return False
    # Run with cwd=OUTPUT_DIR and a bare filename so ffmpeg's subtitles filter
    # doesn't choke on absolute-path colons.
    _run_ffmpeg(
        [
            "-i", str(WITH_AUDIO),
            "-vf", f"subtitles={SRT_FILE.name}:force_style='{SUBTITLE_STYLE}'",
            "-c:a", "copy", str(WITH_SUBS),
        ],
        cwd=str(OUTPUT_DIR),
    )
    return True


def _find_music() -> str | None:
    """Return a background music file path, or None if none is available."""
    env_music = os.environ.get("MUSIC_FILE")
    if env_music and os.path.exists(env_music):
        return env_music
    for ext in ("mp3", "wav", "m4a", "ogg"):
        matches = sorted(glob.glob(str(ASSETS_DIR / "music" / f"*.{ext}")))
        if matches:
            return matches[0]
    return None


def _mix_music(video_in: str) -> bool:
    """Mix quiet background music under the narration. Returns True if applied."""
    music = _find_music()
    if not music:
        log.warning("No background music found in assets/music — skipping.")
        return False
    log.info("Mixing background music: %s (volume %.2f)", music, MUSIC_VOLUME)
    _run_ffmpeg([
        "-i", str(video_in), "-i", music,
        "-filter_complex",
        f"[1:a]volume={MUSIC_VOLUME}[bg];[0:a][bg]amix=inputs=2:duration=shortest",
        "-c:v", "copy", str(FINAL),
    ])
    return True


def run(scenes: list[str], audio: str) -> str:
    """Assemble scenes + narration (+ subtitles + music) into the final video."""
    load_env()
    OUTPUT_DIR.mkdir(exist_ok=True)

    log.info("Assembling %d scenes with narration %s", len(scenes), audio)
    _concat_scenes(scenes)
    _add_narration(audio)

    # Subtitles (optional). If they fail/skip, carry the audio-only video forward.
    have_subs = _make_subtitles(audio) and _burn_subtitles()
    current = WITH_SUBS if have_subs else WITH_AUDIO

    # Background music (optional). If skipped, the current video is the final.
    if not _mix_music(str(current)):
        # No music: promote the current video to the final output.
        os.replace(current, FINAL)

    log.info("Final video written to %s", FINAL)
    return str(FINAL)


def main() -> None:
    parser = argparse.ArgumentParser(description="Assemble the final mystery video.")
    parser.add_argument("--audio", default=str(OUTPUT_DIR / "narration.wav"),
                        help="Narration audio (default output/narration.wav).")
    parser.add_argument("--scenes-glob", default=str(OUTPUT_DIR / "scene_*.mp4"),
                        help="Glob for scene clips (default output/scene_*.mp4).")
    args = parser.parse_args()

    scenes = sorted(glob.glob(args.scenes_glob))
    if not scenes:
        parser.error(f"No scenes matched: {args.scenes_glob}")
    out = run(scenes, args.audio)
    print(out)


if __name__ == "__main__":
    main()
