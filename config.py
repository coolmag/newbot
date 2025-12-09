from pathlib import Path
from typing import List, Optional

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
    RADIO_COOLDOWN_S: int = 120
    RADIO_MAX_DURATION_S: int = 1200  # 20 минут
    RADIO_MIN_VIEWS: Optional[int] = 10000
    RADIO_MIN_LIKES: Optional[int] = 500
    RADIO_MIN_LIKE_RATIO: Optional[float] = 0.75 # Например, 0.75 для 75% лайков
    RADIO_GENRES: List[str] = [
        # --- Популярные международные ---
        "pop", "rock", "indie rock", "alternative rock", "new wave", "post-punk", 
        "folk", "country", "blues", "jazz", "soul", "funk", "disco", "r&b",

        # --- Электроника (общая) ---
        "electronic", "ambient", "chillwave", "lofi hip-hop", "downtempo",

        # --- Танцевальная электроника ---
        "house", "deep house", "techno", "trance", "drum and bass", "dubstep", "uk garage", 
        "breakbeat", "hardstyle", "phonk",

        # --- Ретро и синт-поп ---
        "synthwave", "retrowave", "cyberpunk",

        # --- Хип-хоп / Рэп ---
        "hip-hop", "rap", 

        # --- Тяжелая музыка ---
        "metal", "hard rock", "industrial", "gothic rock",

        # --- Классика и инструментальная ---
        "classical", "orchestral", "soundtrack",

        # --- Регги и этника ---
        "reggae", "latin", "world music",

        # --- Русскоязычные (поп и рок) ---
        "русская поп-музыка", "эстрада 80-90х", "современная эстрада", 
        "русский рок", "русский панк-рок", "русский пост-панк",

        # --- Русскоязычные (хип-хоп) ---
        "русский рэп", "русский хип-хоп", "кальянный рэп",

        # --- Русскоязычные (авторское и шансон) ---
        "шансон", "бардовская песня", "авторская песня", "русские романсы"
    ]

    # --- Настройки кэша ---
    CACHE_TTL_DAYS: int = 7


def get_settings() -> Settings:
    return Settings()
