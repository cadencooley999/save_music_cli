import json
from save_music.schemas import Song
from dataclasses import asdict
import plistlib
from pathlib import Path

from save_music.config import INGESTED_DIR


def ingest_apple_music(f):
    data = plistlib.load(f)

    songs = [
        Song(
            title=s["Name"],
            album=s.get("Album"),
            artist=s["Artist"],
            id=s["Persistent ID"],
            release_date=s.get("Release Date"),
            length=(s.get("Total Time") or 0) / 1000
        )
        for s in data["Tracks"].values()
    ]

    return songs


def dump_songs(songs, filename):
    filepath = INGESTED_DIR / f"{filename}.json"
    filepath.parent.mkdir(parents=True, exist_ok=True)
    
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump([asdict(song) for song in songs], f, indent=2, default=str)


def ingest(filepath, filename, source_type):
    with open(filepath, "rb") as f:
        if source_type == "AppleMusic":
            songs = ingest_apple_music(f)
            dump_songs(songs, filename)
            return songs

    return []