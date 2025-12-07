
import asyncio
from dataclasses import dataclass, field
from typing import Optional

from config import Source


@dataclass
class RadioState:
    """Хранит состояние радио-режима."""
    is_on: bool = False
    current_genre: Optional[str] = None
    skip_event: asyncio.Event = field(default_factory=asyncio.Event)


@dataclass
class BotState:
    """
    Хранит глобальное состояние бота, которое может меняться во время работы.
    """
    source: Source = Source.YOUTUBE
    radio: RadioState = field(default_factory=RadioState)


