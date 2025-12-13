import asyncio
import glob
import logging
import random
import re
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
    async def search(
        self,
        query: str,
        limit: int = 30,
        min_duration: Optional[int] = None,
        max_duration: Optional[int] = None,
        min_views: Optional[int] = None,
        min_likes: Optional[int] = None,
        min_like_ratio: Optional[float] = None,
    ) -> List[TrackInfo]:
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
                
                if result and result.error and "503" in result.error:
                    logger.warning("[Downloader] Получен код 503 от сервера. Большая пауза...")
                    await asyncio.sleep(60 * (attempt + 1))

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
    Улучшенный загрузчик для YouTube с интеллектуальным поиском.
    """

    def __init__(self, settings: Settings, cache_service: CacheService):
        super().__init__(settings, cache_service)

    def _get_ydl_options(
        self, 
        is_search: bool, 
        match_filter: Optional[str] = None,
        min_duration: Optional[int] = None,
        max_duration: Optional[int] = None,
    ) -> Dict[str, Any]:
        options = {
            "quiet": True,
            "no_warnings": True,
            "socket_timeout": 30,
            "source_address": "0.0.0.0",
            "user_agent": "Mozilla/5.0",
            "no_check_certificate": True,
            "prefer_insecure": True,
            "noplaylist": True,
        }
        if is_search:
            options["extract_flat"] = True
            
            filters = []
            if match_filter:
                filters.append(match_filter)
            if min_duration is not None:
                filters.append(f"duration >= {min_duration}")
            if max_duration is not None:
                filters.append(f"duration <= {max_duration}")
            
            if filters:
                combined_filter = " & ".join(filters)
                options["match_filter"] = yt_dlp.utils.match_filter_func(combined_filter)
        else:
            options["format"] = "bestaudio/best"
            options["postprocessors"] = [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}
            ]
            options["outtmpl"] = str(self._settings.DOWNLOADS_DIR / "% (id)s.%(ext)s")
            if self._settings.COOKIES_FILE and self._settings.COOKIES_FILE.exists():
                options["cookiefile"] = str(self._settings.COOKIES_FILE)
        return options

    async def _extract_info(self, query: str, ydl_opts: Dict) -> Dict:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, lambda: yt_dlp.YoutubeDL(ydl_opts).extract_info(query, download=False)
        )

    async def _find_best_match(
        self, 
        query: str, 
        min_duration: Optional[int] = None, 
        max_duration: Optional[int] = None
    ) -> Optional[TrackInfo]:
        """
        Интеллектуальный поиск лучшего трека с фильтрацией в Python.
        """
        logger.info(f"[SmartSearch] Начинаю интеллектуальный поиск для: '{query}'")
        
        search_query_parts = [query]
        if "советск" in query.lower() or "ссср" in query.lower():
            search_query_parts.extend(["гостелерадиофонд", "эстрада", "песня года"])
        else:
            search_query_parts.extend(["official audio", "topic", "lyrics", "альбом"])
        smart_query = " ".join(search_query_parts)

        # --- Python-based Quality Filter ---
        def is_high_quality(e: Dict[str, Any]) -> bool:
            title = e.get('title', '').lower()
            channel = e.get('channel', '').lower()
            
            is_good_title = any(kw in title for kw in ['audio', 'lyric', 'альбом', 'album'])
            is_topic_channel = channel.endswith(' - topic')
            is_bad_title = any(kw in title for kw in [
                'live', 'short', 'концерт', 'выступление', 'official video', 
                'music video', 'full show', 'interview', 'parody', 'влог', 
                'vlog', 'топ 10', 'mix', 'сборник', 'playlist'
            ])
            
            return (is_good_title or is_topic_channel) and not is_bad_title

        def is_valid_video_entry(e: Dict[str, Any]) -> bool:
            """Проверяет, что ID похож на ID видео, а не канала."""
            entry_id = e.get('id')
            return entry_id and len(entry_id) == 11

        # --- Попытка 1: строгий поиск ---
        logger.debug(f"[SmartSearch] Попытка 1: строгий поиск с запросом '{smart_query}'")
        ydl_opts_strict = self._get_ydl_options(
            is_search=True,
            min_duration=min_duration,
            max_duration=max_duration,
        )
        
        try:
            info = await self._extract_info(f"ytsearch5:{smart_query}", ydl_opts_strict)
            if info and info.get("entries"):
                entries = info["entries"]
                
                # Применяем фильтры в Python
                valid_entries = [e for e in entries if is_valid_video_entry(e)]
                high_quality_entries = [e for e in valid_entries if is_high_quality(e)]

                # Сначала ищем в музыкальной категории качественных треков
                music_entries = [e for e in high_quality_entries if isinstance(e.get("categories"), list) and "Music" in e.get("categories", [])]
                if music_entries:
                    entry = music_entries[0]
                    logger.info(f"[SmartSearch] Успех (строгий поиск, high quality, music)! Найден: {entry['title']}")
                    return TrackInfo(
                        title=entry["title"], artist=entry.get("channel", entry.get("uploader", "Unknown")),
                        duration=int(entry.get("duration", 0)), source=Source.YOUTUBE.value, identifier=entry["id"])

                # Если не нашли, ищем любой качественный
                if high_quality_entries:
                    entry = high_quality_entries[0]
                    logger.info(f"[SmartSearch] Успех (строгий поиск, high quality)! Найден: {entry['title']}")
                    return TrackInfo(
                        title=entry["title"], artist=entry.get("channel", entry.get("uploader", "Unknown")),
                        duration=int(entry.get("duration", 0)), source=Source.YOUTUBE.value, identifier=entry["id"])

        except Exception as e:
            logger.warning(f"[SmartSearch] Ошибка на этапе строгого поиска: {e}")

        # --- Попытка 2: обычный поиск ---
        logger.info("[SmartSearch] Строгий поиск не дал результатов, перехожу к обычному поиску.")
        ydl_opts_fallback = self._get_ydl_options(
            is_search=True,
            min_duration=min_duration,
            max_duration=max_duration,
        )
        try:
            info = await self._extract_info(f"ytsearch1:{query}", ydl_opts_fallback)
            if info and info.get("entries"):
                # Применяем только фильтр на валидность видео
                valid_entries = [e for e in info["entries"] if is_valid_video_entry(e)]
                
                if not valid_entries:
                    logger.warning(f"[SmartSearch] Обычный поиск по запросу '{query}' не дал валидных видео.")
                    return None

                # Ищем музыкальные треки
                music_entries = [e for e in valid_entries if isinstance(e.get("categories"), list) and "Music" in e.get("categories", [])]
                if music_entries:
                    entry = music_entries[0]
                    logger.info(f"[SmartSearch] Успех (обычный поиск, music)! Найден: {entry['title']}")
                    return TrackInfo(
                        title=entry["title"], artist=entry.get("channel", entry.get("uploader", "Unknown")),
                        duration=int(entry.get("duration", 0)), source=Source.YOUTUBE.value, identifier=entry["id"])

                # Берем просто первое валидное видео
                entry = valid_entries[0]
                logger.info(f"[SmartSearch] Музыкальных треков не найдено (обычный поиск), беру первый результат: {entry['title']}")
                return TrackInfo(
                    title=entry["title"], artist=entry.get("channel", entry.get("uploader", "Unknown")),
                    duration=int(entry.get("duration", 0)), source=Source.YOUTUBE.value, identifier=entry["id"])
        
        except Exception as e:
            logger.error(f"[SmartSearch] Ошибка на этапе обычного поиска: {e}")
            return None
        
        logger.warning(f"[SmartSearch] Поиск по запросу '{query}' не дал никаких результатов.")
        return None

    async def download(self, query_or_id: str) -> DownloadResult:
        is_id = re.match(r"^[a-zA-Z0-9_-]{11}$", query_or_id) is not None
        
        cache_key = query_or_id if is_id else f"search:{query_or_id}"
        cached = await self._cache.get(cache_key, Source.YOUTUBE)
        if cached:
            return cached

        try:
            if is_id:
                track_identifier = query_or_id
            else:
                track_info_for_dl = await self._find_best_match(
                    query_or_id,
                    min_duration=self._settings.PLAY_MIN_DURATION_S,
                    max_duration=self._settings.PLAY_MAX_DURATION_S
                )
                if not track_info_for_dl:
                    return DownloadResult(success=False, error="Ничего не найдено.")
                track_identifier = track_info_for_dl.identifier

            ydl_opts_download = self._get_ydl_options(is_search=False)
            ydl_opts_download["max_filesize"] = self._settings.PLAY_MAX_FILE_SIZE_MB * 1024 * 1024

            try:
                # Добавляем таймаут, чтобы не зависать на стримах
                info = await asyncio.wait_for(
                    self._extract_info(track_identifier, ydl_opts_download),
                    timeout=30.0
                )
            except asyncio.TimeoutError:
                logger.error(f"Таймаут при получении информации о треке {track_identifier}. Вероятно, это стрим.")
                return DownloadResult(success=False, error="Таймаут получения информации о видео.")
            
            track_info = TrackInfo(
                title=info.get("title", "Unknown"),
                artist=info.get("channel", info.get("uploader", "Unknown")),
                duration=int(info.get("duration", 0)),
                source=Source.YOUTUBE.value,
                identifier=info["id"],
            )

            if track_info.duration > self._settings.PLAY_MAX_DURATION_S:
                err_msg = f"Найденный трек слишком длинный ({track_info.format_duration()})."
                logger.warning(err_msg)
                return DownloadResult(success=False, error=err_msg)

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                lambda: yt_dlp.YoutubeDL(ydl_opts_download).download([track_identifier]),
            )

            mp3_file = next(
                iter(glob.glob(str(self._settings.DOWNLOADS_DIR / f"{track_identifier}.mp3"))),
                None,
            )
            if not mp3_file:
                return DownloadResult(success=False, error="Файл не найден после скачивания.")

            result = DownloadResult(True, mp3_file, track_info)
            await self._cache.set(cache_key, Source.YOUTUBE, result)
            return result
        except Exception as e:
            logger.error(f"Ошибка скачивания с YouTube: {e}", exc_info=True)
            # Проверяем, не было ли это ошибкой размера файла
            if "File is larger than max-filesize" in str(e):
                return DownloadResult(success=False, error=f"Файл слишком большой ( > {self._settings.PLAY_MAX_FILE_SIZE_MB}MB).")
            return DownloadResult(success=False, error=str(e))

    async def search(
        self,
        query: str,
        limit: int = 30,
        min_duration: Optional[int] = None,
        max_duration: Optional[int] = None,
        min_views: Optional[int] = None,
        min_likes: Optional[int] = None,
        min_like_ratio: Optional[float] = None,
        # Мягкий фильтр для радио, чтобы предпочитать муз. контент
        match_filter: Optional[str] = None
    ) -> List[TrackInfo]:
        search_query = f"ytsearch{limit}:{query}"
        ydl_opts = self._get_ydl_options(
            is_search=True, 
            match_filter=match_filter,
            min_duration=min_duration,
            max_duration=max_duration,
        )
        
        try:
            info = await self._extract_info(search_query, ydl_opts)
            if not info:
                logger.warning(f"[YouTube] Поиск для '{query}' не вернул информации.")
                return []
            
            entries = info.get("entries", []) or []

            # --- НОВАЯ ЛОГИКА ФИЛЬТРАЦИИ В PYTHON ---
            BANNED_WORDS = [
                'ai cover', 'suno', 'udio', 'ai version', 'karaoke', 'караоке',
                'ии кавер', 'сгенерировано ии', 'ai generated', '24/7', 'live radio'
            ]
            
            filtered_entries = []
            for e in entries:
                if not (e and e.get("title")):
                    continue
                
                # Явная проверка на флаг is_live
                if e.get('is_live') is True:
                    logger.warning(f"Пропущен LIVE трек (по флагу is_live): {e.get('title')}")
                    continue

                title_lower = e.get("title", "").lower()
                if any(banned in title_lower for banned in BANNED_WORDS):
                    logger.warning(f"Пропущен трек по стоп-слову '{[b for b in BANNED_WORDS if b in title_lower][0]}': {e.get('title')}")
                    continue
                
                filtered_entries.append(e)
            
            if not filtered_entries and entries:
                logger.warning(
                    f"[YouTube Search] Фильтрация по стоп-словам удалила все результаты для '{query}'. "
                    f"Продолжаю с исходным списком, чтобы не оставить пользователя ни с чем."
                )
                final_entries = entries
            else:
                final_entries = filtered_entries
            # --- КОНЕЦ НОВОЙ ЛОГИКИ ---

            # Сначала отфильтровываем по категории "Music"
            music_entries = [
                e for e in final_entries 
                if e and isinstance(e.get("categories"), list) and "Music" in e.get("categories", [])
            ]
            
            # Если после фильтрации ничего не осталось, используем оригинальный список
            if not music_entries:
                logger.warning(f"[YouTube Search] Не найдено треков с категорией 'Music' для запроса '{query}'. Использую все результаты.")
                music_entries = final_entries

            results = []
            for e in music_entries:
                if e.get('is_live'):
                    logger.debug(f"[YouTube Search Debug] Пропущен трек '{e.get('title')}' - это прямая трансляция.")
                    continue

                if not (e and e.get("id") and e.get("title")):
                    logger.debug(f"[YouTube Search Debug] Пропущен трек (без названия или ID): {e}")
                    continue
                
                raw_duration = e.get("duration")
                duration = int(raw_duration or 0)
                
                logger.debug(f"[YouTube Search Debug] Трек: '{e.get('title')}' (ID: {e.get('id')}), Длительность (raw): {raw_duration}, Длительность (int): {duration}")

                if min_duration and duration < min_duration:
                    logger.debug(f"[YouTube Search Debug] Пропущен трек '{e.get('title')}' (ID: {e.get('id')}) - слишком короткий ({duration} < {min_duration}).")
                    continue
                if max_duration and duration > max_duration:
                    logger.debug(f"[YouTube Search Debug] Пропущен трек '{e.get('title')}' (ID: {e.get('id')}) - слишком длинный ({duration} > {max_duration}).")
                    continue

                if min_views and (e.get("view_count") is None or e.get("view_count") < min_views):
                    logger.debug(f"[YouTube Search Debug] Пропущен трек '{e.get('title')}' (ID: {e.get('id')}) - недостаточно просмотров ({e.get('view_count')} < {min_views}).")
                    continue

                if min_likes and (e.get("like_count") is None or e.get("like_count") < min_likes):
                    logger.debug(f"[YouTube Search Debug] Пропущен трек '{e.get('title')}' (ID: {e.get('id')}) - недостаточно лайков ({e.get('like_count')} < {min_likes}).")
                    continue
                
                results.append(TrackInfo(
                    title=e["title"],
                    artist=e.get("uploader", "Unknown"),
                    duration=duration,
                    source=Source.YOUTUBE.value,
                    identifier=e.get("id"),
                    view_count=e.get("view_count"),
                    like_count=e.get("like_count"),
                ))
            return results
        except Exception as e:
            logger.error(f"[YouTube] Ошибка поиска для '{query}': {e}", exc_info=True)
            return []


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

    async def search(
        self, query: str, limit: int = 30, min_duration: Optional[int] = None, 
        max_duration: Optional[int] = None, min_views: Optional[int] = None, 
        min_likes: Optional[int] = None, min_like_ratio: Optional[float] = None
    ) -> List[TrackInfo]:
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
            
            results = []
            for doc in data.get("response", {}).get("docs", []):
                duration = int(float(doc.get("length", 0)))
                if duration <= 0 or \
                   (min_duration and duration < min_duration) or \
                   (max_duration and duration > max_duration):
                    continue
                
                results.append(TrackInfo(
                    title=doc.get("title", "Unknown"),
                    artist=doc.get("creator", "Unknown"),
                    duration=duration,
                    source=Source.INTERNET_ARCHIVE.value,
                    identifier=doc.get("identifier"),
                ))
            return results
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
