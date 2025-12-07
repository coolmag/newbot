import asyncio
import os
import glob
import time
from typing import Any, Dict, List

import yt_dlp

from base import BaseDownloader, DownloadResult
from config import settings, TrackInfo, Source
from logger import logger
from cache import CacheManager


class YouTubeDownloader(BaseDownloader):
    """
    Загрузчик для YouTube.
    Использует yt-dlp для поиска и скачивания аудио.
    """
    def __init__(self):
        super().__init__()
        self.cache = CacheManager()
        self._check_ffmpeg()
        # Кэш для результатов поиска
        self.search_cache = {}
        self.search_cache_ttl = 600  # 10 минут

    def _check_ffmpeg(self):
        """Проверяет доступность FFmpeg при инициализации."""
        try:
            import subprocess
            result = subprocess.run(
                ["ffmpeg", "-version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5
            )
            if result.returncode == 0:
                logger.info("✅ FFmpeg найден.")
            else:
                logger.warning("⚠️ FFmpeg не найден. Возможны проблемы с конвертацией аудио.")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            logger.warning("⚠️ FFmpeg не найден или недоступен. Убедитесь, что FFmpeg установлен.")
        except Exception as e:
            logger.warning(f"⚠️ Ошибка при проверке FFmpeg: {e}")

    def _get_ydl_options_for_search(self) -> Dict[str, Any]:
        """Упрощенные опции для поиска."""
        options = {
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": True,
            "socket_timeout": 30,
            "retries": 3,
            "noplaylist": True,
            "source_address": "0.0.0.0",
            "max_filesize": settings.MAX_FILE_SIZE_MB * 1024 * 1024,
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "referer": "https://www.youtube.com/",
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "web"],
                    "player_skip": ["webpage"],
                }
            },
            "no_check_certificate": True,
            "prefer_insecure": True,
            "extract_flat": True,  # Не скачиваем, только метаданные
        }
        
        # Для поиска не используем cookies - они могут мешать
        return options

    def _get_ydl_options_for_download(self) -> Dict[str, Any]:
        """Опции для скачивания."""
        out_template = settings.DOWNLOADS_DIR / "%(id)s.%(ext)s"
        
        options = {
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
            "outtmpl": str(out_template),
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": True,
            "socket_timeout": 60,
            "retries": 3,
            "noplaylist": True,
            "source_address": "0.0.0.0",
            "max_filesize": settings.MAX_FILE_SIZE_MB * 1024 * 1024,
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "referer": "https://www.youtube.com/",
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "web"],
                    "player_skip": ["webpage"],
                }
            },
            "no_check_certificate": True,
            "prefer_insecure": True,
        }
        
        # Используем cookies только для скачивания, если файл существует
        if settings.COOKIES_FILE and os.path.exists(settings.COOKIES_FILE):
            options["cookiefile"] = settings.COOKIES_FILE
            logger.info(f"✅ Использую cookies файл для скачивания: {settings.COOKIES_FILE}")
        
        return options

    async def _extract_info(self, query: str, ydl_opts: Dict) -> Dict:
        """Асинхронно запускает yt-dlp для извлечения информации."""
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(
                None,
                lambda: yt_dlp.YoutubeDL(ydl_opts).extract_info(query, download=False)
            )
        except Exception as e:
            logger.error(f"Ошибка при извлечении информации: {e}")
            raise

    async def search(self, query: str, limit: int = 30) -> List[TrackInfo]:
        """
        Ищет видео на YouTube и возвращает список треков.
        """
        logger.info(f"[{self.name}] Поиск видео для '{query}'...")
        
        # Проверяем кэш
        cache_key = f"search:{query}:{limit}"
        current_time = time.time()
        
        if cache_key in self.search_cache:
            cache_time, playlist = self.search_cache[cache_key]
            if current_time - cache_time < self.search_cache_ttl:
                logger.info(f"[{self.name}] Использую кэшированные результаты для '{query}'")
                return playlist
        
        try:
            # Создаем опции для поиска
            ydl_opts = self._get_ydl_options_for_search()
            
            # Для поиска используем простой запрос
            search_query = f"ytsearch{limit}:{query}"
            
            # Выполняем поиск с увеличенным таймаутом
            info = await asyncio.wait_for(
                self._extract_info(search_query, ydl_opts),
                timeout=45
            )
            
            # Обрабатываем результаты
            entries = info.get('entries', []) if info else []
            if not entries:
                logger.warning(f"Не найдено видео для '{query}'.")
                # Не кэшируем пустые результаты
                return []
            
            playlist = []
            
            for entry in entries:
                if not entry:
                    continue
                
                # Проверяем базовые поля
                if not entry.get("id"):
                    continue
                
                # Получаем информацию о треке
                title = entry.get("title", "").strip()
                if not title or title == "Unknown Title":
                    continue
                
                # Получаем артиста
                artist = entry.get("uploader", "Unknown Artist")
                if "Topic" in artist:
                    artist = artist.replace(" - Topic", "").strip()
                
                # Получаем длительность
                duration = int(entry.get("duration", 0))
                if duration <= 0:
                    continue
                
                track_info = TrackInfo(
                    title=title[:200],
                    artist=artist[:100],
                    duration=duration,
                    source=Source.YOUTUBE.value,
                )
                playlist.append(track_info)
                
                if len(playlist) >= limit:
                    break
            
            logger.info(f"Найдено {len(playlist)} видео для '{query}'.")
            
            # Сохраняем в кэш только если нашли треки
            if playlist:
                self.search_cache[cache_key] = (current_time, playlist)
            
            return playlist

        except asyncio.TimeoutError:
            logger.error(f"[{self.name}] Таймаут поиска для '{query}'")
            return []
        except yt_dlp.utils.DownloadError as e:
            logger.error(f"[{self.name}] Ошибка yt-dlp при поиске '{query}': {e}")
            return []
        except Exception as e:
            logger.error(f"[{self.name}] Ошибка поиска: {e}", exc_info=True)
            return []

    async def download(self, query: str) -> DownloadResult:
        """
        Основной метод для поиска и скачивания с YouTube.
        """
        source = Source.YOUTUBE
        cached = await self.cache.get(query, source)
        if cached:
            return cached
            
        logger.info(f"[{self.name}] Поиск трека для '{query}'...")

        try:
            # Используем опции для скачивания
            ydl_opts = self._get_ydl_options_for_download()
            
            # Ищем трек
            info = await asyncio.wait_for(
                self._extract_info(query, ydl_opts),
                timeout=60
            )

            entries = info.get('entries', []) if info else []
            if not entries:
                logger.warning(f"Не найдено результатов для запроса: {query}")
                return DownloadResult(success=False, error="Ничего не найдено. Попробуйте другой запрос.")
            
            video_info = entries[0]
            
            if not video_info or not video_info.get("id"):
                return DownloadResult(success=False, error="Не удалось получить информацию о видео.")
            
            # Скачиваем видео
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: yt_dlp.YoutubeDL(ydl_opts).download([video_info['webpage_url']])
            )
            
            video_id = video_info["id"]
            
            # Ищем скачанный файл
            downloaded_files = glob.glob(str(settings.DOWNLOADS_DIR / f"{video_id}.*"))
            
            if not downloaded_files:
                return DownloadResult(success=False, error="Файл не был создан после загрузки.")
            
            # Находим MP3 файл
            mp3_files = [f for f in downloaded_files if f.endswith('.mp3')]
            if not mp3_files:
                # Если нет MP3, берем первый файл
                actual_file_path = downloaded_files[0]
                logger.warning(f"MP3 не найден, использую {actual_file_path}")
            else:
                actual_file_path = mp3_files[0]

            track_info = TrackInfo(
                title=video_info.get("title", "Unknown Title"),
                artist=video_info.get("channel") or video_info.get("uploader", "Unknown Artist"),
                duration=int(video_info.get("duration", 0)),
                source=source.value,
            )
            
            result = DownloadResult(success=True, file_path=str(actual_file_path), track_info=track_info)
            await self.cache.set(query, source, result)
            return result

        except asyncio.TimeoutError:
            return DownloadResult(success=False, error="Таймаут во время операции с YouTube.")
        except yt_dlp.utils.DownloadError as e:
            err_str = str(e).lower()
            if "sign in to confirm" in err_str or "bot" in err_str:
                logger.error(f"[{self.name}] YouTube требует подтверждение. Нужны cookies.")
                return DownloadResult(success=False, error="YouTube требует подтверждение.")
            if "blocked" in err_str or "unavailable" in err_str:
                logger.error(f"[{self.name}] Запрос заблокирован YouTube.")
                return DownloadResult(success=False, error="Запрос заблокирован YouTube.")
            logger.error(f"[{self.name}] Ошибка yt-dlp: {e}")
            return DownloadResult(success=False, error=f"Ошибка загрузки: {str(e)[:100]}")
        except Exception as e:
            logger.error(f"[{self.name}] Непредвиденная ошибка: {e}", exc_info=True)
            return DownloadResult(success=False, error=f"Внутренняя ошибка: {e}")