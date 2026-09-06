import argparse
from pathlib import Path
import sys
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)

from save_music.downloader import download, DEFAULT_PATH
from save_music.ingester import ingest
from save_music.config import INGESTED_DIR


def main():
    parser = argparse.ArgumentParser(
        description="Download an Apple Music playlist from YouTube."
    )

    parser.add_argument(
        "playlist_path",
        help="Path to the exported Apple Music playlist file",
    )

    parser.add_argument(
        "--platform",
        default="AppleMusic",
        help="Platform the playlist was exported from (default: AppleMusic)",
    )

    parser.add_argument(
        "--song-limit",
        type=int,
        default=10,
        help="Maximum number of songs to download from the playlist",
    )

    parser.add_argument(
        "--structure",
        choices=["aa", "a", "s"],
        default="aa",
        help="Output folder structure: 'aa' = artist/album, 'a' = artist/, 's' = flat",
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_PATH,
        help="Directory to save downloaded music (default: ~/Downloads/savedmusic)",
    )

    parser.add_argument(
        "--storage-limit",
        type=float,
        default=None,
        help="Stop after approximately this many GB have been downloaded",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed progress including search results and match scores",
    )

    parser.add_argument(
        "--dry",
        action="store_true",
        help="Simulate the download to see what would happen",
    )

    args = parser.parse_args()
    args.playlist_path = Path(args.playlist_path)
    filename = args.playlist_path.stem

    if not args.playlist_path.exists():
        logger.error("Playlist file not found: %s", args.playlist_path)
        sys.exit(1)

    ingested_file = INGESTED_DIR / f"{filename}.json"

    logger.info("Ingesting %s", filename)

    try:
        ingest(args.playlist_path, filename, args.platform)
    except Exception as e:
        logger.error("Failed to ingest %s: %s", filename, e)
        sys.exit(1)

    if not ingested_file.exists():
        logger.error("Ingested file not found: %s", ingested_file)
        sys.exit(1)

    logger.info("Ingested %s — starting download", filename)

    download(
        playlist_name=filename,
        output_path=args.output,
        input_path=args.playlist_path,
        song_limit=args.song_limit,
        storage_limit=args.storage_limit,
        structure=args.structure,
        dry=args.dry,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main()