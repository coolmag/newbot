from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Обязательные переменные ---
    BOT_TOKEN: str

    # --- Необязательные переменные ---
    ADMIN_IDS: str = ""
    COOKIES_CONTENT: str = ""

    @property
    def ADMIN_ID_LIST(self) -> List[int]:
        if not self.ADMIN_IDS:
            return []
        return [int(i.strip()) for i in self.ADMIN_IDS.split(",") if i.strip()]

    # --- Пути ---
    BASE_DIR: Path = Path(__file__).resolve().parent
    DOWNLOADS_DIR: Path = BASE_DIR / "downloads"
    CACHE_DB_PATH: Path = BASE_DIR / "cache.db"
    LOG_FILE_PATH: Path = BASE_DIR / "bot.log"
    COOKIES_FILE: Path = BASE_DIR / "cookies.txt"

    # --- Настройки логгера ---
    LOG_LEVEL: str = "INFO"

    # --- Настройки загрузчика ---
    MAX_QUERY_LENGTH: int = 150
    MAX_FILE_SIZE_MB: int = 49
    DOWNLOAD_TIMEOUT_S: int = 120

    # --- Настройки повторных попыток ---
    MAX_RETRIES: int = 5
    RETRY_DELAY_S: float = 5.0

    # --- Настройки радио ---
    RADIO_SOURCE: str = "youtube"
    RADIO_COOLDOWN_S: int = 10
    RADIO_MAX_DURATION_S: int = 1200  # 20 минут
    RADIO_GENRES: List[str] = [
        "music", "chill", "lofi", "jazz", "rock", "pop", "electronic", "ambient",
        "русский рок", "русский поп", "шансон", "бардовская песня", "эстрада",
        "фолк", "классика", "рэп", "инди", "метал", "блюз", "кантри"
    ]

    # --- Настройки кэша ---
    CACHE_TTL_DAYS: int = 7


def get_settings() -> Settings:
    return Settings()
