
import asyncio
import os
import glob # Добавляем импорт glob
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

    def _get_ydl_options(self) -> Dict[str, Any]:
        """Формирует опции для yt-dlp."""
        out_template = settings.DOWNLOADS_DIR / "%(id)s.%(ext)s"
        
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
            "retries": 3,
            "noplaylist": True,
            "default_search": "ytsearch",
            "source_address": "0.0.0.0",
            "max_filesize": settings.MAX_FILE_SIZE_MB * 1024 * 1024,
            "user_agent": user_agent,
            "referer": "https://www.youtube.com/",
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "web"],
                    "player_skip": ["webpage", "configs"],
                }
            },
            "no_check_certificate": False,
            "prefer_insecure": False,
        }
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

    async def search(self, query: str, limit: int = 30) -> List[TrackInfo]:
        """
        Ищет видео на YouTube и возвращает список треков.
        """
        logger.info(f"[{self.name}] Поиск видео для '{query}'...")
        
        try:
            ydl_opts = self._get_ydl_options()
            
            # Упрощаем фильтры для радио - только базовая проверка
            ydl_opts['match_filter'] = yt_dlp.utils.match_filter_func(
                "duration > 60 & !is_live"
            )
            
            # Для радио используем более конкретные запросы
            # Добавляем ключевые слова для музыки
            search_queries = [
                f"{query} music official audio",
                f"{query} song",
                f"{query} track",
                f"{query} instrumental",
                f"{query}"
            ]
            
            all_entries = []
            
            for search_query in search_queries:
                if len(all_entries) >= limit:
                    break
                    
                ydl_opts["default_search"] = f"ytsearch{10}:{search_query}"
                
                try:
                    info = await self._extract_info(search_query, ydl_opts)
                    entries = info.get('entries', []) if info else []
                    
                    for entry in entries:
                        if not entry:
                            continue
                        
                        # Базовая проверка на валидность
                        if not entry.get("id"):
                            continue
                        
                        # Пропускаем слишком длинные видео (>30 минут)
                        duration = int(entry.get("duration", 0))
                        if duration > 1800:  # 30 минут
                            continue
                        
                        # Проверяем наличие названия
                        title = entry.get("title", "")
                        if not title or title.lower() == "unknown title":
                            continue
                        
                        all_entries.append(entry)
                        
                except Exception as e:
                    logger.warning(f"Поиск по запросу '{search_query}' не удался: {e}")
                    continue
            
            if not all_entries:
                logger.warning(f"Не найдено видео для '{query}'.")
                return []

            # Преобразуем в TrackInfo
            playlist = []
            seen_ids = set()
            
            for entry in all_entries:
                if len(playlist) >= limit:
                    break
                    
                video_id = entry.get("id")
                if video_id in seen_ids:
                    continue
                    
                seen_ids.add(video_id)
                
                track_info = TrackInfo(
                    title=entry.get("title", "Unknown Title"),
                    artist=entry.get("channel") or entry.get("uploader", "Unknown Artist"),
                    duration=int(entry.get("duration", 0)),
                    source=Source.YOUTUBE.value,
                    identifier=video_id
                )
                playlist.append(track_info)
            
            logger.info(f"Найдено {len(playlist)} треков для '{query}'.")
            return playlist

        except Exception as e:
            logger.error(f"[{self.name}] Непредвиденная ошибка при поиске: {e}", exc_info=True)
            return []

    async def download(self, query: str) -> DownloadResult:
        """
        Скачивает трек с YouTube.
        Если query - это id видео, скачивает напрямую.
        Иначе - ищет и скачивает первый результат.
        """
        source = Source.YOUTUBE
        cached = await self.cache.get(query, source)
        if cached:
            return cached
            
        logger.info(f"[{self.name}] Скачивание трека '{query}' с YouTube...")

        try:
            ydl_opts = self._get_ydl_options()
            
            is_id = " " not in query and len(query) < 20
            
            if is_id:
                search_query = query
            else:
                search_query = f"ytsearch1:{query}"

            info = await asyncio.wait_for(
                self._extract_info(search_query, ydl_opts),
                timeout=settings.DOWNLOAD_TIMEOUT_S
            )

            entries = info.get('entries', []) if info else []
            if not entries:
                if is_id:
                    return DownloadResult(success=False, error=f"Не удалось найти видео с id: {query}")
                logger.warning(f"Не найдено результатов для запроса: {query}")
                return DownloadResult(success=False, error="Ничего не найдено. Попробуйте другой запрос.")
            
            video_info = entries[0]
            
            if not video_info or not video_info.get("id"):
                return DownloadResult(success=False, error="Не удалось получить информацию о видео.")

            await asyncio.wait_for(
                self._download_info(video_info, ydl_opts),
                timeout=settings.DOWNLOAD_TIMEOUT_S
            )
            
            video_id = video_info["id"]
            
            # Ждем немного, чтобы FFmpeg успел завершить конвертацию
            await asyncio.sleep(2)
            
            # Ищем .mp3 файл
            expected_path = settings.DOWNLOADS_DIR / f"{video_id}.mp3"
            
            if not expected_path.exists():
                logger.error(f"Файл {expected_path} не был создан после скачивания и конвертации.")
                
                # Попробуем найти другие файлы, чтобы понять, что пошло не так
                other_files = glob.glob(str(settings.DOWNLOADS_DIR / f"{video_id}.*"))
                if other_files:
                    logger.warning(f"Найдены другие файлы: {other_files}. Возможно, проблема с FFmpeg.")
                
                return DownloadResult(success=False, error="Ошибка конвертации в MP3.")

            track_info = TrackInfo(
                title=video_info.get("title", "Unknown Title"),
                artist=video_info.get("channel") or video_info.get("uploader", "Unknown Artist"),
                duration=int(video_info.get("duration", 0)),
                source=source.value,
                identifier=video_id,
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
                return DownloadResult(success=False, error="YouTube требует подтверждение.")
            if "blocked" in err_str or "unavailable" in err_str or "429" in err_str:
                logger.error(f"[{self.name}] Запрос заблокирован YouTube. Проверьте IP или cookies.")
                return DownloadResult(success=False, error="Запрос заблокирован YouTube.")
            logger.error(f"[{self.name}] Ошибка yt-dlp: {e}")
            return DownloadResult(success=False, error=f"Ошибка загрузки: {str(e)[:100]}")
        except Exception as e:
            logger.error(f"[{self.name}] Непредвиденная ошибка: {e}", exc_info=True)
            return DownloadResult(success=False, error=f"Внутренняя ошибка: {e}")
