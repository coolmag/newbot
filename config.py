from pathlib import Path
from typing import List, Optional, Dict

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
    RADIO_MAX_DURATION_S: int = 600   # 10 минут
    RADIO_MIN_DURATION_S: int = 60    # 1 минута
    RADIO_MIN_VIEWS: Optional[int] = 10000
    RADIO_MIN_LIKES: Optional[int] = 500
    RADIO_MIN_LIKE_RATIO: Optional[float] = 0.75 # Например, 0.75 для 75% лайков
    RADIO_GENRES: List[str] = [
        # --- Рок ---
        "rock", "classic rock", "psychedelic rock", "indie rock", "alternative rock", "hard rock", 
        "post-punk", "metal", "industrial", "gothic rock", "punk rock", "progressive rock",
        "pop rock", "alternative rock", "grunge", "britpop", "emo", "indie rock",
        "rock and roll",

        # --- Поп и танцевальная ---
        "pop", "new wave", "disco", "r&b", "traditional pop", "synth-pop", "latin pop", "k-pop",
        
        # --- Соул, Фанк, Грув ---
        "soul", "funk", "soul groove", "jazz-funk", "rare groove", "modern soul", "neo-soul",
        
        # --- Джаз и Блюз ---
        "jazz", "blues", "doo-wop",

        # --- Электроника (общая) ---
        "electronic", "ambient", "chillwave", "lofi hip-hop", "downtempo", "edm (electronic dance music)",
        "trap", "hyperpop", "synthwave",

        # --- Танцевальная электроника (House, Techno и др.) ---
        "house", "deep house", "deep tech house", "progressive house", "tech house", "chill house", "tropical house",
        "techno", "minimal techno", "trance", "drum and bass", "dubstep", "uk garage", 
        "breakbeat", "hardstyle", "phonk", "future bass", "ambient house", "trip-hop",

        # --- DJ-сеты и ремиксы ---
        "extended mix", "kraken music", "craken remix", "club mix", "dj set",
        "hardwell", "armin van buuren", "tiesto", "david guetta", "daft punk",
        
        # --- Хип-хоп / Рэп ---
        "hip-hop", "rap", "drill",
        
        # --- Классика, фолк и этника ---
        "classical", "orchestral", "soundtrack", "folk", "country", "reggae", "latin", "world music", "afrobeats", "reggaeton", "ska",

        # --- Русскоязычные (поп и рок) ---
        "русская поп-музыка", "русский рок", "русский панк-рок", "русский пост-панк",

        # --- Русскоязычные (хип-хоп) ---
        "русский рэп", "русский хип-хоп", "кальянный рэп",

        # --- Советская эстрада, джаз, грув ---
        "советский грув", "советский фанк", "советский джаз", "советская эстрада",

        # --- Русскоязычные (авторское и шансон) ---
        "шансон", "бардовская песня", "авторская песня", "русские романсы",
        
        # --- Дополнительные ---
        "bedroom pop"
    ]

    RADIO_MOODS: Dict[str, List[str]] = {
        "энергичное": ["pop", "house", "hardstyle", "drum and bass", "hip-hop", "rock", "эстрада 80-90х"],
        "спокойное": ["ambient", "lofi hip-hop", "chillwave", "jazz", "classical", "downtempo"],
        "веселое": ["disco", "funk", "pop", "tropical house", "latin", "эстрада"],
        "грустное": ["blues", "indie rock", "alternative rock", "русские романсы"],
        "фокус": ["ambient", "lofi hip-hop", "minimal techno"],
        "драйв": ["hard rock", "metal", "phonk", "techno", "trance"],
        "ностальгия": ["synthwave", "retrowave", "classic rock", "советская эстрада", "эстрада 80-90х"],
        "русское": ["русская поп-музыка", "русский рок", "русский рэп", "шансон", "бардовская песня", "советская эстрада"]
    }

    # --- Настройки кэша ---
    CACHE_TTL_DAYS: int = 7


def get_settings() -> Settings:
    return Settings()
