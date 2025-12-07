
import asyncio
import hashlib

import aiohttp

from base import BaseDownloader, DownloadResult
from config import settings, TrackInfo, Source
from logger import logger
from cache import CacheManager


class DeezerDownloader(BaseDownloader):
    """
    Загрузчик для Deezer.
    Использует официальное API для поиска и скачивания 30-секундных превью.
    """
    def __init__(self):
        super().__init__()
        self.api_url = "https://api.deezer.com"
        self.cache = CacheManager()
        self.session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Инициализирует и возвращает aiohttp сессию."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=20)
            )
        return self.session

    async def download(self, query: str, is_long: bool = False) -> DownloadResult:
        """
        Ищет трек на Deezer и скачивает его превью.
        Длинный поиск не поддерживается, поэтому is_long игнорируется.
        """
        cached = await self.cache.get(query, Source.DEEZER)
        if cached:
            return cached

        logger.info(f"[{self.name}] Поиск превью для '{query}'...")
        
        try:
            session = await self._get_session()
            search_params = {"q": query, "limit": 1}
            
            async with session.get(f"{self.api_url}/search", params=search_params) as response:
                response.raise_for_status()
                data = await response.json()

            if not data or not data.get("data"):
                return DownloadResult(success=False, error="Трек не найден на Deezer.")

            track_data = data["data"][0]
            preview_url = track_data.get("preview")

            if not preview_url:
                return DownloadResult(success=False, error="Для этого трека нет превью.")

            # Скачиваем аудио
            async with session.get(preview_url) as audio_response:
                audio_response.raise_for_status()
                audio_content = await audio_response.read()

            # Сохраняем файл
            file_hash = hashlib.md5(preview_url.encode()).hexdigest()[:10]
            file_path = settings.DOWNLOADS_DIR / f"deezer_{file_hash}.mp3"
            with open(file_path, "wb") as f:
                f.write(audio_content)
                
            track_info = TrackInfo(
                title=f"{track_data.get('title', 'Unknown')} (Preview)",
                artist=track_data.get('artist', {}).get('name', 'Unknown'),
                duration=int(track_data.get('duration', 30)),
                source=Source.DEEZER.value
            )
            
            result = DownloadResult(success=True, file_path=str(file_path), track_info=track_info)
            await self.cache.set(query, Source.DEEZER, result)
            return result

        except aiohttp.ClientError as e:
            logger.error(f"[{self.name}] Ошибка сети при обращении к Deezer API: {e}")
            return DownloadResult(success=False, error="Ошибка сети при доступе к Deezer.")
        except Exception as e:
            logger.error(f"[{self.name}] Непредвиденная ошибка: {e}", exc_info=True)
            return DownloadResult(success=False, error=f"Внутренняя ошибка: {e}")

    async def close_session(self):
        """Закрывает aiohttp сессию, если она была открыта."""
        if self.session and not self.session.closed:
            await self.session.close()
            logger.info(f"[{self.name}] HTTP сессия закрыта.")

