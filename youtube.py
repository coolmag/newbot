
import asyncio
import os
from typing import Any, Dict

import yt_dlp

from base import BaseDownloader, DownloadResult
from config import settings, TrackInfo, Source
from logger import logger
from cache import CacheManager


class YouTubeDownloader(BaseDownloader):
    """
    Загрузчик для YouTube и YouTube Music.
    Использует yt-dlp для поиска и скачивания аудио.
    """
    def __init__(self):
        super().__init__()
        self.cache = CacheManager()
        self._check_ffmpeg()

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

    def _get_ydl_options(self, query: str, is_long: bool = False) -> Dict[str, Any]:
        """Формирует опции для yt-dlp с улучшенными настройками для обхода блокировки."""
        out_template = settings.DOWNLOADS_DIR / "%(id)s.%(ext)s"
        
        # User-Agent для обхода блокировки
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        
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
            "socket_timeout": 30,
            "retries": 3,  # Увеличено количество попыток
            "noplaylist": not is_long,
            "default_search": "ytsearch",
            "source_address": "0.0.0.0",
            "max_filesize": settings.MAX_FILE_SIZE_MB * 1024 * 1024,
            # Опции для обхода блокировки
            "user_agent": user_agent,
            "referer": "https://www.youtube.com/",
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "web"],
                    "player_skip": ["webpage", "configs"],
                }
            },
            # Дополнительные опции
            "no_check_certificate": False,
            "prefer_insecure": False,
        }

        # Фильтр по длительности для обычного поиска (не для аудиокниг)
        if not is_long:
            options['match_filter'] = yt_dlp.utils.match_filter_func("duration < 900")

        # Используем cookies, если они указаны
        # if settings.COOKIES_FILE and os.path.exists(settings.COOKIES_FILE):
        #     options["cookiefile"] = settings.COOKIES_FILE
        #     logger.info(f"Используются cookies из файла: {settings.COOKIES_FILE}")
        
        # Для аудиокниг ищем больше результатов и берем самый длинный
        if is_long:
            options["default_search"] = "ytsearch10"
            options["extract_flat"] = True

        return options

    async def _extract_info(self, query: str, ydl_opts: Dict) -> Dict:
        """Асинхронно запускает yt-dlp для извлечения информации."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: yt_dlp.YoutubeDL(ydl_opts).extract_info(query, download=False)
        )

    async def _download_info(self, info: Dict, ydl_opts: Dict) -> Dict:
        """Асинхронно запускает yt-dlp для скачивания на основе извлеченной информации."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: yt_dlp.YoutubeDL(ydl_opts).process_info(info)
        )

    async def download(self, query: str, is_long: bool = False) -> DownloadResult:
        """
        Основной метод для поиска и скачивания с YouTube.
        """
        source = Source.YOUTUBE
        cached = await self.cache.get(query, source)
        if cached:
            return cached
            
        logger.info(f"[{self.name}] Поиск {'длинного видео' if is_long else 'трека'} для '{query}'...")

        try:
            # 1. Формируем опции и извлекаем информацию
            ydl_opts = self._get_ydl_options(query, is_long=is_long)
            info = await asyncio.wait_for(
                self._extract_info(query, ydl_opts),
                timeout=settings.DOWNLOAD_TIMEOUT_S
            )

            # Обрабатываем разные форматы ответа от yt-dlp
            entries = []
            if isinstance(info, dict):
                if "entries" in info:
                    entries = info["entries"]
                elif "id" in info:
                    # Если это одно видео, а не список
                    entries = [info]
            
            # Фильтруем None значения
            entries = [e for e in entries if e and e.get("id")]
            
            if not entries:
                logger.warning(f"Не найдено результатов для запроса: {query}")
                return DownloadResult(success=False, error="Ничего не найдено. Попробуйте другой запрос.")
            
            # 2. Выбираем подходящее видео
            video_info = None
            if is_long:
                # Для аудиокниг выбираем самое длинное видео
                video_info = max(entries, key=lambda e: e.get("duration", 0) if e else 0)
            else:
                # Для обычных треков берем первое
                video_info = entries[0]
            
            if not video_info or not video_info.get("id"):
                return DownloadResult(success=False, error="Не удалось получить информацию о видео.")

            # 3. Скачиваем выбранное видео
            ydl_opts["extract_flat"] = False # Отключаем 'flat' для скачивания
            await asyncio.wait_for(
                self._download_info(video_info, ydl_opts),
                timeout=settings.DOWNLOAD_TIMEOUT_S
            )
            
            # 4. Формируем результат
            video_id = video_info["id"]
            expected_path = settings.DOWNLOADS_DIR / f"{video_id}.mp3"
            
            if not expected_path.exists():
                return DownloadResult(success=False, error="Файл не был создан после загрузки.")

            track_info = TrackInfo(
                title=video_info.get("title", "Unknown Title"),
                artist=video_info.get("channel") or video_info.get("uploader", "Unknown Artist"),
                duration=int(video_info.get("duration", 0)),
                source=source.value,
            )
            
            result = DownloadResult(success=True, file_path=str(expected_path), track_info=track_info)
            await self.cache.set(query, source, result)
            return result

        except asyncio.TimeoutError:
            return DownloadResult(success=False, error="Таймаут во время операции с YouTube.")
        except yt_dlp.utils.DownloadError as e:
            err_str = str(e).lower()
            if "sign in to confirm" in err_str or "bot" in err_str:
                logger.error(f"[{self.name}] YouTube требует подтверждение. Нужны cookies.")
                return DownloadResult(
                    success=False, 
                    error="YouTube требует подтверждение. Добавьте cookies файл в настройки (COOKIES_FILE)."
                )
            if "blocked" in err_str or "unavailable" in err_str or "429" in err_str:
                logger.error(f"[{self.name}] Запрос заблокирован YouTube. Проверьте IP или cookies.")
                return DownloadResult(success=False, error="Запрос заблокирован YouTube (возможно, нужен VPN или cookies).")
            logger.error(f"[{self.name}] Ошибка yt-dlp: {e}")
            return DownloadResult(success=False, error=f"Ошибка загрузки: {str(e)[:100]}")
        except Exception as e:
            logger.error(f"[{self.name}] Непредвиденная ошибка: {e}", exc_info=True)
            return DownloadResult(success=False, error=f"Внутренняя ошибка: {e}")
            
    async def download_long(self, query: str) -> DownloadResult:
        """Переопределенный метод для поиска длинного видео."""
        return await self.download(query, is_long=True)

    async def search_playlist(self, query: str) -> list:
        """Ищет плейлисты и возвращает список глав первого найденного плейлиста."""
        logger.info(f"[{self.name}] Поиск плейлиста для '{query}'...")
        ydl_opts = {
            "extract_flat": True,
            "default_search": "ytsearch15",
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": True,
        }
        
        try:
            info = await self._extract_info(f"{query} аудиокнига плейлист", ydl_opts)
            
            if not info or 'entries' not in info:
                return []
            
            # Ищем первый плейлист в результатах
            for entry in info['entries']:
                if entry and entry.get('_type') == 'playlist':
                    playlist_info = await self._extract_info(entry['url'], {"extract_flat": True, "quiet": True})
                    return playlist_info.get('entries', [])
            return []
        except Exception as e:
            logger.error(f"[{self.name}] Ошибка при поиске плейлиста: {e}", exc_info=True)
            return []

    async def download_single_video(self, video_id: str) -> DownloadResult:
        """Скачивает одно видео по его ID."""
        logger.info(f"[{self.name}] Скачивание видео по ID: {video_id}...")
        try:
            ydl_opts = self._get_ydl_options(video_id, is_long=False)
            ydl_opts['noplaylist'] = True # Убедимся, что скачивается только одно видео

            info = await self._extract_info(f"https://www.youtube.com/watch?v={video_id}", ydl_opts)

            if not info or info.get('id') != video_id:
                return DownloadResult(success=False, error="Не удалось получить информацию о видео.")

            await self._download_info(info, ydl_opts)
            
            expected_path = settings.DOWNLOADS_DIR / f"{video_id}.mp3"
            if not expected_path.exists():
                return DownloadResult(success=False, error="Файл не был создан после загрузки.")

            track_info = TrackInfo(
                title=info.get("title", "Unknown Title"),
                artist=info.get("channel") or info.get("uploader", "Unknown Artist"),
                duration=int(info.get("duration", 0)),
                source=Source.YOUTUBE.value,
            )
            
            return DownloadResult(success=True, file_path=str(expected_path), track_info=track_info)

        except Exception as e:
            logger.error(f"[{self.name}] Ошибка при скачивании видео по ID: {e}", exc_info=True)
            return DownloadResult(success=False, error=f"Внутренняя ошибка: {e}")
