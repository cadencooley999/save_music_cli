import json
import re
import time
from dataclasses import asdict
from pathlib import Path
import logging

from mutagen.id3 import ID3, TXXX, ID3NoHeaderError, TALB, TIT2, TPE1
import yt_dlp

logger = logging.getLogger(__name__)

from save_music.schemas import Song, YouTubeCandidate
from save_music.history import save_history, load_history
from save_music.config import INGESTED_DIR, HISTORY_DIR

DEFAULT_PATH = Path.home() / "Downloads" / "savedmusic"
AVERAGE_STORAGE_PER_SECOND_KB = 24
SLEEP_BETWEEN_SONGS = 5
PROGRESS_INTERVAL = 10
SEPARATOR = "─" * 40


def delete_file_and_empty_parents(file_path):
    path = Path(file_path).resolve()

    if path.is_file():
        path.unlink()
    else:
        return

    for parent in path.parents:
        try:
            parent.rmdir()
        except OSError:
            break


def format_duration(seconds):
    seconds = int(seconds)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)

    if hours:
        return f"{hours}:{minutes:02}:{seconds:02}"
    return f"{minutes}:{seconds:02}"


def format_size(kb):
    if kb >= 1024 * 1024:
        return f"{kb / (1024 * 1024):.2f} GB"
    if kb >= 1024:
        return f"{kb / 1024:.2f} MB"
    return f"{kb:.2f} KB"


def safe_filename(name):
    if not name:
        return "Unknown"
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    return name.rstrip(" .")


def search_youtube(query, limit=5):
    options = {"quiet": True, "extract_flat": True}

    with yt_dlp.YoutubeDL(options) as ydl:
        results = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)

    entries = results.get("entries", [])
    return [
        YouTubeCandidate(
            title=entry.get("title"),
            url=entry.get("url"),
            channel=entry.get("channel"),
            duration=entry.get("duration"),
        )
        for entry in entries
    ]


def rank_candidates(results, song, verbose=False):
    """Score and rank all candidates. Returns sorted list of (YouTubeCandidate, score)."""
    song_title = (song.title or "").lower().strip()
    song_artist = (song.artist or "").lower().strip()
    song_album = (song.album or "").lower().strip()

    scored = []

    for r in results:
        title = (r.title or "").lower().strip()
        channel = (r.channel or "").lower().strip()
        duration = r.duration

        if not title:
            continue

        score = 0

        if title == song_title:
            score += 3
        elif song_title in title:
            score += 1

        if song_artist:
            if song_artist in title:
                score += 1
            elif song_artist in channel:
                score += 0.75

        if song_album and song_album in title:
            score += 0.25

        if duration is not None and song.length is not None:
            diff = abs(duration - song.length)
            if diff <= 2:
                score += 1
            elif diff <= 5:
                score += 0.75
            elif diff <= 10:
                score += 0.5
            elif diff <= 30:
                score += 0.25
            else:
                score -= 1

        if "cover" in title and "cover" not in song_title:
            score -= 3
        if "live" in title and "live" not in song_title:
            score -= 1
        if "karaoke" in title:
            score -= 3
        if "remix" in title and "remix" not in song_title:
            score -= 2
        if "8d" in title:
            score -= 2
        if "sped up" in title:
            score -= 2
        if "slowed" in title:
            score -= 2
        if "reverb" in title:
            score -= 2

        scored.append((r, score))

        if verbose:
            logger.info("  Candidate: \"%s\" — score %.1f", title, score)

    scored.sort(key=lambda x: x[1], reverse=True)
    ranked = [(r, s) for r, s in scored if s >= 0]

    if verbose:
        if ranked:
            logger.info(
                "  Top pick: \"%s\" (score %.1f)", ranked[0][0].title, ranked[0][1]
            )
        else:
            logger.info("  No candidate passed the threshold")

    return ranked


AGE_RESTRICTED_PHRASES = [
    "age-restricted",
    "age restriction",
    "sign in to confirm your age",
    "this video is private",
]


def _is_age_restricted_error(err_str):
    err_lower = str(err_str).lower()
    return any(phrase in err_lower for phrase in AGE_RESTRICTED_PHRASES)


def download_mp3(url, output_path, song):
    options = {
        "format": "bestaudio/best",
        "outtmpl": str(output_path),
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
        "quiet": True,
        "no_warnings": True,
    }

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download([url])

        actual_path = Path(str(output_path).replace(".%(ext)s", ".mp3"))
        add_metadata(actual_path, song, url)
        return True, False

    except Exception as e:
        err_str = str(e)
        is_age = _is_age_restricted_error(err_str)
        if is_age:
            logger.warning(
                "Age-restricted video for \"%s\" — trying next candidate", song.title
            )
        else:
            logger.warning(
                "Download error for \"%s\": %s — may be rate limiting, just wait and try again",
                song.title,
                e,
            )
        return False, is_age


def add_metadata(path, song, youtube_url=None):
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()

    tags["TIT2"] = TIT2(encoding=3, text=song.title)
    tags["TPE1"] = TPE1(encoding=3, text=song.artist)

    if song.album:
        tags["TALB"] = TALB(encoding=3, text=song.album)

    tags.add(TXXX(encoding=3, desc="Track ID", text=str(song.id)))

    if youtube_url:
        tags.add(TXXX(encoding=3, desc="YouTube ID", text=youtube_url))

    tags.save(path)


def download(
    playlist_name,
    output_path,
    input_path,
    song_limit,
    storage_limit,
    structure,
    dry,
    verbose,
):
    playlist_file = INGESTED_DIR / f"{playlist_name}.json"

    if not playlist_file.exists():
        logger.error("Playlist data not found: %s", playlist_file)
        return

    with open(playlist_file, "r", encoding="utf-8") as f:
        songs = [Song(**song) for song in json.load(f)]

    songs = songs[:song_limit]
    total = len(songs)

    history, history_file, duplicates = load_history(playlist_name, output_path, songs)
    duplicates_map = {song.id: path for song, path in duplicates}

    if verbose and duplicates_map:
        logger.info("Found %d previously downloaded song(s) on disk", len(duplicates_map))

    downloaded_keys = {
        (song["artist"].lower(), song["title"].lower()) for song in history
    }

    processed = 0
    downloaded_count = 0
    skipped_count = 0
    failed_count = 0
    no_match_count = 0
    total_duration = sum(song.length for song in songs)
    estimated_size = format_size(total_duration * AVERAGE_STORAGE_PER_SECOND_KB)
    failed_songs = []
    unmatched_songs = []
    overwrite = False
    consecutive_failures = 0
    storage_limit_kb = storage_limit * 1024 * 1024 if storage_limit else None
    downloaded_bytes = 0

    # ── Staging ──────────────────────────────────────────────────
    print()
    print(f"  {SEPARATOR}")
    print(f"   Save Music — Download Staging")
    print(f"  {SEPARATOR}")
    print()
    print(f"   Playlist     : {playlist_name}")
    print(f"   Songs        : {total}")
    print(f"   Duration     : {format_duration(total_duration)}")
    print(f"   Est. size    : {estimated_size}")
    if storage_limit:
        print(f"   Storage cap  : {storage_limit:.2f} GB")
    print(f"   Output       : {output_path}")
    print(
        f"   Structure    : {{'aa': 'artist/album', 'a': 'artist', 's': 'flat'}}[{structure}]"
    )

    if downloaded_keys:
        print()
        print(f"   {len(downloaded_keys)} previously downloaded song(s) detected.")
        while True:
            response = input("   Overwrite existing files? (y/n, 's' to list): ").lower().strip()
            if response == "y":
                overwrite = True
                break
            elif response == "s":
                for s in history:
                    print(f"     • {s['title']} — {s['artist']}")
                continue
            elif response == "n":
                break
            else:
                continue

    print()
    print(f"  {SEPARATOR}")
    print()

    if dry:
        print("   ⚡ Dry run — no files downloaded")
        print()
        return

    # ── Download loop ────────────────────────────────────────────
    interrupted = False
    try:
        for index, song in enumerate(songs, start=1):
            key = (song.artist.lower(), song.title.lower())

            if key in downloaded_keys and not overwrite:
                skipped_count += 1
                processed += 1
                continue

            print(f"  [{index:>3}/{total:<3}] {song.artist} — {song.title}")

            try:
                query = f"{song.title} - {song.artist} Audio Official"
                if verbose:
                    logger.info("  YouTube search: %s", query)

                results = search_youtube(query)
                ranked = rank_candidates(results, song, verbose=verbose)

                if not ranked:
                    print(f"         ⚠  No good match found")
                    no_match_count += 1
                    unmatched_songs.append(song.title)
                    continue

                def make_output_path():
                    match structure:
                        case "aa":
                            artist_dir = output_path / safe_filename(song.artist)
                            album_dir = (
                                artist_dir / safe_filename(song.album)
                                if song.album
                                else artist_dir
                            )
                            album_dir.mkdir(parents=True, exist_ok=True)
                            return album_dir / f"{safe_filename(song.title)}.%(ext)s"
                        case "a":
                            artist_dir = output_path / safe_filename(song.artist)
                            artist_dir.mkdir(parents=True, exist_ok=True)
                            return artist_dir / f"{safe_filename(song.title)}.%(ext)s"
                        case "s":
                            output_path.mkdir(parents=True, exist_ok=True)
                            return output_path / f"{safe_filename(song.title)}.%(ext)s"

                output_file = make_output_path()

                # Pre-check storage limit
                estimated_song_kb = song.length * AVERAGE_STORAGE_PER_SECOND_KB
                if storage_limit_kb and (downloaded_bytes + estimated_song_kb) > storage_limit_kb:
                    used = format_size(downloaded_bytes)
                    limit_str = format_size(storage_limit_kb)
                    print(f"         ⛁  Storage cap hit ({used} / {limit_str})")
                    break

                # Try candidates in ranked order
                download_ok = False
                for attempt, (candidate, score) in enumerate(ranked):
                    if attempt > 0:
                        print(f"         ↻  Retry with: {candidate.title}")

                    if verbose:
                        logger.info(
                            "  Trying candidate %d/%d: %s (score %.1f)",
                            attempt + 1,
                            len(ranked),
                            candidate.title,
                            score,
                        )

                    success, is_age = download_mp3(candidate.url, str(output_file), song)

                    if success:
                        download_ok = True
                        break

                    if not is_age:
                        break

                if not download_ok:
                    if verbose:
                        logger.info("  All candidates exhausted for \"%s\"", song.title)
                    print(f"         ✗  Download failed — rate limiting may occur, wait and try again")
                    failed_count += 1
                    consecutive_failures += 1

                    if consecutive_failures >= 3:
                        logger.error("%d consecutive download failures — aborting", consecutive_failures)
                        print(f"         ⛔  {consecutive_failures} failures in a row, stopping")
                        break

                    time.sleep(SLEEP_BETWEEN_SONGS)
                    processed += 1
                    continue

                # ── Download succeeded ──
                try:
                    actual_mp3_path = Path(str(output_file).replace(".%(ext)s", ".mp3"))
                    file_size_kb = (
                        actual_mp3_path.stat().st_size / 1024
                        if actual_mp3_path.exists()
                        else 0
                    )
                    downloaded_bytes += file_size_kb

                    old_path = duplicates_map.get(song.id)
                    if old_path and output_file != old_path:
                        delete_file_and_empty_parents(old_path)
                        if verbose:
                            logger.info("  Removed old copy: %s", old_path)

                    history.append(asdict(song))
                    downloaded_keys.add(key)
                    save_history(history, history_file)
                    consecutive_failures = 0
                    downloaded_count += 1

                    size_str = format_size(file_size_kb)
                    print(f"         ✓  Downloaded  ({size_str})")

                    if verbose:
                        logger.info(
                            "  Running total: %s / %s",
                            format_size(downloaded_bytes),
                            format_size(storage_limit_kb) if storage_limit_kb else "unlimited",
                        )

                except KeyboardInterrupt:
                    # Finish saving this song's history before stopping
                    if old_path:
                        delete_file_and_empty_parents(old_path)
                        if verbose:
                            logger.info("  Removed old copy: %s", old_path)
                    history.append(asdict(song))
                    downloaded_keys.add(key)
                    save_history(history, history_file)
                    consecutive_failures = 0
                    downloaded_count += 1

                    print()
                    print(f"   ⏹  Interrupted after finishing {song.title}")
                    print()
                    interrupted = True
                    break

            except Exception as e:
                print(f"         ✗  Error: {e}")
                logger.exception("Unexpected error downloading \"%s\"", song.title)
                failed_count += 1
                failed_songs.append(song.title)
                consecutive_failures += 1

                if consecutive_failures >= 3:
                    logger.error("%d consecutive failures — aborting", consecutive_failures)
                    break

            time.sleep(SLEEP_BETWEEN_SONGS)
            processed += 1

            if processed % PROGRESS_INTERVAL == 0:
                print()
                print(
                    f"   Progress: {processed}/{total}  "
                    f"↓ {downloaded_count}  "
                    f"⏭ {skipped_count}  "
                    f"✗ {failed_count}  "
                    f"⚠ {no_match_count}"
                )
                print()

    except KeyboardInterrupt:
        print()
        print("   ⏹  Interrupted by user")
        print()
        interrupted = True

    # ── Summary ──────────────────────────────────────────────────
    print()
    print(f"  {SEPARATOR}")
    if interrupted:
        print(f"   Interrupted  {processed}/{total}")
    else:
        print(f"   Finished  {processed}/{total}")
    print(f"  {SEPARATOR}")
    print()
    print(f"   Downloaded  : {downloaded_count}")
    print(f"   Skipped     : {skipped_count}")
    print(f"   Failed      : {failed_count}")
    print(f"   No match    : {no_match_count}")
    if failed_songs:
        print(f"   Failed: {', '.join(failed_songs)}")
    if unmatched_songs:
        print(f"   Unmatched: {', '.join(unmatched_songs)}")
    if storage_limit:
        print(
            f"   Storage     : {format_size(downloaded_bytes)} / {format_size(storage_limit_kb)}"
        )
    print()
    print(f"  {SEPARATOR}")
    print()