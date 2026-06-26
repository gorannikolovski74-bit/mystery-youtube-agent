"""Download free royalty-free ambient/mystery background music.

Sources used: Free Music Archive (FMA) and other CC0/public domain tracks
suitable for mystery YouTube content.

Run:
    python scripts/download_music.py
"""
from __future__ import annotations

import os
import sys
import urllib.request
from pathlib import Path

MUSIC_DIR = Path(__file__).resolve().parent.parent / "assets" / "music"

# CC0 / Public Domain ambient tracks from Free Music Archive and similar.
TRACKS = [
    {
        "name": "dark_ambient_mystery.mp3",
        "url": "https://files.freemusicarchive.org/storage-freemusicarchive-org/music/no_curator/Kai_Engel/Satin/Kai_Engel_-_09_-_Intermezzo.mp3",
        "desc": "Kai Engel - Intermezzo (CC BY)",
    },
    {
        "name": "ambient_tension.mp3",
        "url": "https://files.freemusicarchive.org/storage-freemusicarchive-org/music/ccCommunity/Kai_Engel/Satin/Kai_Engel_-_04_-_Satin.mp3",
        "desc": "Kai Engel - Satin (CC BY)",
    },
]


def download(url: str, dest: Path) -> None:
    print(f"  Downloading {dest.name} ...", end=" ", flush=True)
    headers = {"User-Agent": "mystery-agent/1.0 (music downloader)"}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as fh:
        fh.write(resp.read())
    size_kb = dest.stat().st_size // 1024
    print(f"done ({size_kb} KB)")


def main() -> None:
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Music directory: {MUSIC_DIR}\n")
    failed = []
    for track in TRACKS:
        dest = MUSIC_DIR / track["name"]
        if dest.exists():
            print(f"  {track['name']} already exists — skipping.")
            continue
        try:
            download(track["url"], dest)
        except Exception as exc:
            print(f"FAILED: {exc}")
            failed.append(track["name"])
            if dest.exists():
                dest.unlink()

    if failed:
        print(f"\nFailed to download: {failed}")
        print("You can manually add any MP3 to assets/music/ folder.")
        sys.exit(1)
    else:
        print(f"\nAll tracks downloaded to {MUSIC_DIR}")
        print("The assembly agent will automatically use the first track found.")


if __name__ == "__main__":
    main()
