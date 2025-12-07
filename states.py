
import asyncio
from dataclasses import dataclass, field
from typing import Optional, List
from asyncio import Future

from config import Source, TrackInfo
from base import DownloadResult


@dataclass
class RadioState:
    """Хранит состояние радио-режима."""
    is_on: bool = False
    current_genre: Optional[str] = None
    skip_event: asyncio.Event = field(default_factory=asyncio.Event)
    playlist: List[TrackInfo] = field(default_factory=list)
    next_track_result: Optional[DownloadResult] = None
    next_track_future: Optional[Future] = None


@dataclass
class BotState:
    """
    Хранит глобальное состояние бота, которое может меняться во время работы.
    """
    source: Source = Source.YOUTUBE
    radio: RadioState = field(default_factory=RadioState)

