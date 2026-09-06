import json
from pathlib import Path
from dataclasses import asdict
import logging

from mutagen.id3 import ID3, TXXX, ID3NoHeaderError

logger = logging.getLogger(__name__)

from save_music.config import HISTORY_DIR


def get_custom_tag(tags, name):
    for tag in tags.getall("TXXX"):
        if tag.desc == name:
            return tag.text[0] if tag.text else None
    return None


def scan_existing_music(output_path):
    existing_ids = {}

    for path in Path(output_path).rglob("*.mp3"):
        try:
            tags = ID3(path)
        except (ID3NoHeaderError, Exception):
            continue

        track_id = get_custom_tag(tags, "Track ID")
        if track_id:
            existing_ids[track_id] = path

    return existing_ids


def check_metadata_for_dupes(output_path, songs):
    existing_ids = scan_existing_music(output_path)
    dupes = [
        (song, existing_ids[song.id])
        for song in songs
        if song.id in existing_ids
    ]
    return dupes


def save_history(history, history_file):
    with open(history_file, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, default=str)


def load_history(playlist_name, output_path, songs):
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    history_file = HISTORY_DIR / f"{playlist_name}.json"

    duplicates = check_metadata_for_dupes(output_path, songs)

    if not history_file.exists():
        history_file.write_text("[]", encoding="utf-8")
        return [], history_file, []

    save_history([asdict(d[0]) for d in duplicates], history_file)

    try:
        with open(history_file, "r", encoding="utf-8") as f:
            return json.load(f), history_file, duplicates
    except (json.JSONDecodeError, OSError):
        logger.warning(
            "Could not read %s — starting with empty history", history_file
        )
        return [], history_file, []