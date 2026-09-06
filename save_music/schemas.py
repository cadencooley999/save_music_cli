from dataclasses import dataclass
from datetime import datetime

@dataclass
class Song:
    title: str
    artist: str 
    length: float 
    id: str
    album: str | None = None
    release_date: datetime | None = None

@dataclass
class YouTubeCandidate:
    title: str
    url: str
    channel: str | None
    duration: float | None