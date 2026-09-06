# Save Music

Download your Apple Music playlists as MP3 files from YouTube.

## Tutorial Video

https://youtu.be/kkGEjll3UuM

## Install

```bash
pip install yt-dlp mutagen
git clone https://github.com/caden999/save-music
cd save-music
pip install .
```

Or in editable mode for development:

```bash
pip install -e .
```

## Usage

1. Export a playlist from Apple Music as an XML/plist file
2. Run:

```bash
save-music path/to/playlist.plist --output ~/Music
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--song-limit` | 10 | Max songs to download |
| `--storage-limit` | — | Stop after ~N GB downloaded (float) |
| `--structure` | aa | Output folder: `aa` (artist/album), `a` (artist), `s` (flat) |
| `--output` | ~/Downloads/savedmusic | Where to save MP3s |
| `--platform` | AppleMusic | Source platform |
| `--verbose` | — | Show detailed match scores and progress |
| `--dry` | — | Preview what would download |

### Output

The tool shows:
- Staging summary before downloading
- Per-song status with match, download, and errors
- Progress every 10 songs
- Final summary with download/skip/fail/no-match counts

If a YouTube video is age-restricted, the tool automatically tries the next best match. Download errors may indicate rate limiting — just wait and try again.

## Storage

Ingested playlists and download history are stored in `~/.local/share/save-music/`.
