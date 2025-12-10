from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Source(str, Enum):
    """Перечисление доступных источников музыки."""
    YOUTUBE = "YouTube"
    YOUTUBE_MUSIC = "YouTube Music"
    INTERNET_ARCHIVE = "Internet Archive"


@dataclass
class DownloadResult:
    """
    Результат операции загрузки. Содержит либо информацию о треке, либо ошибку.
    """
    success: bool
    file_path: Optional[str] = None
    track_info: Optional["TrackInfo"] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        """Сериализует объект в словарь для сохранения в JSON."""
        return {
            "success": self.success,
            "file_path": self.file_path,
            "track_info": self.track_info.__dict__ if self.track_info else None,
            "error": self.error,
        }

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
    view_count: Optional[int] = None
    like_count: Optional[int] = None

    @property
    def display_name(self) -> str:
        """Возвращает форматированное имя для отображения."""
        return f"{self.artist} - {self.title}"

    def format_duration(self) -> str:
        """Форматирует длительность из секунд в строку MM:SS."""
        if not self.duration or self.duration < 0:
            return "00:00"
        minutes, seconds = divmod(self.duration, 60)
        return f"{minutes:02d}:{seconds:02d}"
