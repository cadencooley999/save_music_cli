from pathlib import Path

# Data directory for ingested playlists and download history
# Uses ~/.local/share/save-music/ per XDG convention on Linux/macOS
DATA_DIR = Path.home() / ".local" / "share" / "save-music"

INGESTED_DIR = DATA_DIR / "ingested_playlists"
HISTORY_DIR = DATA_DIR / "downloaded_songs"