import os
from enum import Enum
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass

from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()


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


class Settings:
    """
    Класс для хранения всех настроек приложения.
    Настройки загружаются из переменных окружения.
    """
    # --- Обязательные переменные ---
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    
    # --- Необязательные переменные ---
    # ID администраторов через запятую (e.g., "12345,67890")
    ADMIN_IDS: List[int] = [
        int(admin_id.strip())
        for admin_id in os.getenv("ADMIN_IDS", "").split(",")
        if admin_id.strip()
    ]
    
    # Файл cookies для yt-dlp. Может быть путем к файлу или содержимым файла.
    COOKIES_FILE: str = os.getenv("COOKIES_FILE", "")

    # --- Пути ---
    # Используем pathlib для кросс-платформенности
    BASE_DIR: Path = Path(__file__).resolve().parent
    DOWNLOADS_DIR: Path = BASE_DIR / "downloads"
    CACHE_DB_PATH: Path = BASE_DIR / "cache.db"

    # --- Настройки загрузчика ---
    MAX_QUERY_LENGTH: int = 150
    MAX_FILE_SIZE_MB: int = 30  # Уменьшено с 50 для радио
    DOWNLOAD_TIMEOUT_S: int = 30  # Уменьшено с 180 для радио

    # --- Настройки повторных попыток ---
    MAX_RETRIES: int = 2
    RETRY_DELAY_S: float = 1.5

    # --- Настройки радио ---
    RADIO_SOURCE: str = "youtube"
    RADIO_COOLDOWN_S: int = 15  # Уменьшено с 240
    RADIO_MAX_DURATION_S: int = int(os.getenv("RADIO_MAX_DURATION_S", 600))  # 10 минут
    RADIO_GENRES: List[str] = [
        "lofi hip hop",
        "synthwave",
        "chill music",
        "jazz",
        "ambient",
        "electronic",
        "retrowave",
        "cyberpunk music",
        "indie pop",
        "rock music"
    ]
    RADIO_SEARCH_PATTERNS: List[str] = [
        "{genre} music",
        "{genre} song",
        "{genre} track",
        "{genre} official audio",
        "{genre}",
    ]

    # --- Настройки кэша ---
    CACHE_TTL_DAYS: int = 7

    def __init__(self):
        """Создает необходимые директории при инициализации."""
        self.DOWNLOADS_DIR.mkdir(exist_ok=True)


# Создаем единственный экземпляр настроек
settings = Settings()