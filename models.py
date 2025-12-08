from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Source(str, Enum):
    """Перечисление доступных источников музыки."""
    YOUTUBE = "YouTube"
    YOUTUBE_MUSIC = "YouTube Music"
    INTERNET_ARCHIVE = "Internet Archive"


@dataclass(frozen=True)
class TrackInfo:
    """
    Структура для хранения информации о треке.
    `frozen=True` делает экземпляры класса неизменяемыми.
    """
    title: str
    artist: str
    duration: int
    source: str
    identifier: Optional[str] = None

    @property
    def display_name(self) -> str:
        """Возвращает форматированное имя для отображения."""
        return f"{self.artist} - {self.title}"


@dataclass
class DownloadResult:
    """
    Результат операции загрузки. Содержит либо информацию о треке, либо ошибку.
    """
    success: bool
    file_path: Optional[str] = None
    track_info: Optional[TrackInfo] = None
    error: Optional[str] = None
