import asyncio
import glob
import logging
import random
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import aiohttp
import yt_dlp

from config import Settings
from models import DownloadResult, Source, TrackInfo
from cache_service import CacheService

logger = logging.getLogger(__name__)


class BaseDownloader(ABC):
    """
    Абстрактный базовый класс для всех загрузчиков.
    Предоставляет общий интерфейс и логику повторных попыток.
    """

    def __init__(self, settings: Settings, cache_service: CacheService):
        self._settings = settings
        self._cache = cache_service
        self.name = self.__class__.__name__
        self.semaphore = asyncio.Semaphore(3)

    @abstractmethod
    async def search(self, query: str, limit: int = 30, max_duration: Optional[int] = None) -> List[TrackInfo]:
        raise NotImplementedError

    @abstractmethod
    async def download(self, query: str) -> DownloadResult:
        raise NotImplementedError

    async def download_with_retry(self, query: str) -> DownloadResult:
        for attempt in range(self._settings.MAX_RETRIES):
            try:
                async with self.semaphore:
                    result = await self.download(query)
                if result and result.success:
                    return result
                
                # Если yt-dlp вернул ошибку, содержащую код 503, делаем большую паузу
                if result and result.error and "503" in result.error:
                    logger.warning("[Downloader] Получен код 503 от сервера. Большая пауза...")
                    await asyncio.sleep(60 * (attempt + 1)) # Пауза 1-3 минуты

            except (asyncio.TimeoutError, Exception) as e:
                logger.error(f"[Downloader] Исключение при загрузке: {e}", exc_info=True)
            
            if attempt < self._settings.MAX_RETRIES - 1:
                await asyncio.sleep(self._settings.RETRY_DELAY_S * (attempt + 1))

        return DownloadResult(
            success=False,
            error=f"Не удалось скачать после {self._settings.MAX_RETRIES} попыток.",
        )


class YouTubeDownloader(BaseDownloader):
    """
    Загрузчик для YouTube.
    """

    def __init__(self, settings: Settings, cache_service: CacheService):
        super().__init__(settings, cache_service)
        self._ydl_opts_search = self._get_ydl_options(is_search=True)
        self._ydl_opts_download = self._get_ydl_options(is_search=False)

    def _get_ydl_options(self, is_search: bool) -> Dict[str, Any]:
        options = {
            "quiet": False,
            "no_warnings": False,
            "ignoreerrors": False,
            "socket_timeout": 30,
            "source_address": "0.0.0.0",
            "user_agent": "Mozilla/5.0",
            "no_check_certificate": True,
            "prefer_insecure": True,
            # Явно запрещаем обработку плейлистов
            "noplaylist": True,
            # Фильтруем по категории "Музыка"
            "match_filter": yt_dlp.utils.match_filter_func("category = 'Music'"),
        }
        if is_search:
            # "extract_flat": True заставляет yt-dlp не лезть вглубь, а просто отдать список видео
            options["extract_flat"] = True
        else:
            options["format"] = "bestaudio/best"
            options["max_filesize"] = self._settings.MAX_FILE_SIZE_MB * 1024 * 1024
            options["postprocessors"] = [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}
            ]
            options["outtmpl"] = str(self._settings.DOWNLOADS_DIR / "%(id)s.%(ext)s")
            if self._settings.COOKIES_FILE and self._settings.COOKIES_FILE.exists():
                options["cookiefile"] = str(self._settings.COOKIES_FILE)
        return options

    async def _extract_info(self, query: str, ydl_opts: Dict) -> Dict:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, lambda: yt_dlp.YoutubeDL(ydl_opts).extract_info(query, download=False)
        )

    async def search(self, query: str, limit: int = 30, max_duration: Optional[int] = None) -> List[TrackInfo]:
        search_query = f"ytsearch{limit}:{query}"
        try:
            info = await self._extract_info(search_query, self._ydl_opts_search)
            if not info:
                logger.warning(f"[YouTube] Поиск для '{query}' не вернул информации.")
                return []
            
            entries = info.get("entries", []) or []
            
            results = []
            for e in entries:
                if not (e and e.get("id") and e.get("title")):
                    continue
                
                duration = int(e.get("duration") or 0)
                if duration <= 0:
                    continue

                if max_duration and duration > max_duration:
                    continue

                results.append(TrackInfo(
                    title=e["title"],
                    artist=e.get("uploader", "Unknown"),
                    duration=duration,
                    source=Source.YOUTUBE.value,
                    identifier=e.get("id"),
                ))
            return results
        except Exception as e:
            logger.error(f"[YouTube] Ошибка поиска для '{query}': {e}", exc_info=True)
            return []

    async def download(self, query_or_id: str) -> DownloadResult:
        # Если это похоже на ID, а не на поисковый запрос, кешируем по ID
        # Это важно для радио, чтобы не кешировать один и тот же трек под разными поисковыми запросами
        is_id = " " not in query_or_id and len(query_or_id) < 20 
        cache_key = query_or_id if is_id else f"search:{query_or_id}"
        
        cached = await self._cache.get(cache_key, Source.YOUTUBE)
        if cached:
            return cached
            
        try:
            # Если это не ID, делаем поиск
            if not is_id:
                info = await self._extract_info(f"ytsearch1:{query_or_id}", self._ydl_opts_download)
                video_info = info["entries"][0]
            else: # Если это ID, получаем информацию напрямую
                info = await self._extract_info(query_or_id, self._ydl_opts_download)
                video_info = info

            video_id = video_info["id"]
            
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                lambda: yt_dlp.YoutubeDL(self._ydl_opts_download).download([video_id]),
            )
            mp3_file = next(
                iter(glob.glob(str(self._settings.DOWNLOADS_DIR / f"{video_id}.mp3"))),
                None,
            )
            if not mp3_file:
                return DownloadResult(success=False, error="Файл не найден.")
            
            track_info = TrackInfo(
                title=video_info.get("title", "Unknown"),
                artist=video_info.get("channel", video_info.get("uploader", "Unknown")),
                duration=int(video_info.get("duration") or 0),
                source=Source.YOUTUBE.value,
                identifier=video_id,
            )
            result = DownloadResult(True, mp3_file, track_info)
            await self._cache.set(cache_key, Source.YOUTUBE, result)
            return result
        except Exception as e:
            logger.error(f"Ошибка скачивания с YouTube: {e}", exc_info=True)
            return DownloadResult(success=False, error=str(e))


class InternetArchiveDownloader(BaseDownloader):
    """
    Загрузчик для Internet Archive.
    """

    API_URL = "https://archive.org/advancedsearch.php"

    def __init__(self, settings: Settings, cache_service: CacheService):
        super().__init__(settings, cache_service)
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def search(self, query: str, limit: int = 30, max_duration: Optional[int] = None) -> List[TrackInfo]:
        params = {
            "q": f'mediatype:audio AND (subject:("{query}") OR title:("{query}"))',
            "fl[]": "identifier,title,creator,length",
            "rows": limit,
            "page": random.randint(1, 5),
            "output": "json",
        }
        try:
            session = await self._get_session()
            async with session.get(self.API_URL, params=params) as response:
                data = await response.json()
            return [
                TrackInfo(
                    title=doc.get("title", "Unknown"),
                    artist=doc.get("creator", "Unknown"),
                    duration=int(float(doc.get("length", 0))),
                    source=Source.INTERNET_ARCHIVE.value,
                    identifier=doc.get("identifier"),
                )
                for doc in data.get("response", {}).get("docs", [])
                if doc.get("length") and int(float(doc.get("length", 0))) > 0
            ]
        except Exception:
            return []

    async def download(self, query: str) -> DownloadResult:
        cached = await self._cache.get(query, Source.INTERNET_ARCHIVE)
        if cached:
            return cached
        
        search_results = await self.search(query, limit=1)
        if not search_results:
            return DownloadResult(success=False, error="Ничего не найдено.")

        track = search_results[0]
        identifier = track.identifier
        try:
            session = await self._get_session()
            metadata_url = f"https://archive.org/metadata/{identifier}"
            async with session.get(metadata_url) as response:
                metadata = await response.json()

            mp3_file = next(
                (f for f in metadata.get("files", []) if f.get("format", "").startswith("VBR MP3")), 
                None
            )
            if not mp3_file:
                return DownloadResult(success=False, error="MP3 файл не найден.")

            file_path = self._settings.DOWNLOADS_DIR / f"{identifier}.mp3"
            download_url = f"https://archive.org/download/{identifier}/{mp3_file['name']}"
            
            async with session.get(download_url) as response:
                with open(file_path, "wb") as f:
                    while chunk := await response.content.read(1024):
                        f.write(chunk)
            
            result = DownloadResult(True, str(file_path), track)
            await self._cache.set(query, Source.INTERNET_ARCHIVE, result)
            return result
        except Exception as e:
            return DownloadResult(success=False, error=str(e))

    async def close(self):
        if self._session:
            await self._session.close()