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
        self.search_cache_ttl = 300  # 5 минут

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

    def _get_search_options(self) -> Dict[str, Any]:
        """Опции для поиска (без cookies, чтобы избежать блокировки)."""
        out_template = settings.DOWNLOADS_DIR / "%(id)s.%(ext)s"
        
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        
        options = {
            "format": "bestaudio/best",
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": True,
            "socket_timeout": 15,
            "retries": 2,
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
            'match_filter': yt_dlp.utils.match_filter_func(
                f"duration < {settings.RADIO_MAX_DURATION_S} & !is_live & !playlist"
            ),
        }
        
        # НЕ используем cookies для поиска, чтобы избежать блокировки
        return options

    def _get_download_options(self) -> Dict[str, Any]:
        """Опции для скачивания (с cookies, если есть)."""
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
            'match_filter': yt_dlp.utils.match_filter_func(
                f"duration < {settings.RADIO_MAX_DURATION_S} & !is_live & !playlist"
            ),
        }
        
        # Используем cookies только для скачивания, если файл существует
        if settings.COOKIES_FILE and os.path.exists(settings.COOKIES_FILE):
            options["cookiefile"] = settings.COOKIES_FILE
            logger.info(f"✅ Использую cookies файл для скачивания: {settings.COOKIES_FILE}")
        
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
        
        # Используем кэш поиска
        cache_key = f"search:{query}:{limit}"
        if cache_key in self.search_cache:
            cache_time, playlist = self.search_cache[cache_key]
            if time.time() - cache_time < self.search_cache_ttl:
                logger.info(f"[{self.name}] Использую кэшированные результаты для '{query}'")
                return playlist
        
        try:
            # Используем опции для поиска (без cookies)
            ydl_opts = self._get_search_options()
            ydl_opts["default_search"] = f"ytsearch{limit * 2}"
            
            # Устанавливаем таймаут для поиска
            info = await asyncio.wait_for(
                self._extract_info(query, ydl_opts),
                timeout=20
            )
            
            entries = info.get('entries', []) if info else []
            if not entries:
                logger.warning(f"Не найдено видео для '{query}'.")
                # Сохраняем пустой результат в кэш, чтобы не пытаться снова
                self.search_cache[cache_key] = (time.time(), [])
                return []

            playlist = []
            seen_ids = set()
            
            for entry in entries:
                if not entry:
                    continue
                
                video_id = entry.get("id")
                if not video_id or video_id in seen_ids:
                    continue
                
                # Проверяем, что это видео (а не плейлист или трансляция)
                if entry.get('_type') in ['playlist', 'url']:
                    continue
                
                # Проверяем длительность
                duration = int(entry.get("duration", 0))
                if duration < 30:  # Минимум 30 секунд
                    continue
                
                seen_ids.add(video_id)
                
                # Форматируем название и исполнителя
                title = entry.get("title", "Unknown Title")
                artist = entry.get("channel") or entry.get("uploader", "Unknown Artist")
                
                # Убираем [Official Audio] и подобное из названия
                if title and "[" in title and "]" in title:
                    title = title.split("[")[0].strip()
                
                track_info = TrackInfo(
                    title=title[:200],  # Ограничиваем длину
                    artist=artist[:100],
                    duration=duration,
                    source=Source.YOUTUBE.value,
                )
                playlist.append(track_info)
                
                if len(playlist) >= limit:
                    break
            
            logger.info(f"Найдено {len(playlist)} видео для '{query}'.")
            
            # Сохраняем в кэш
            if playlist:
                self.search_cache[cache_key] = (time.time(), playlist)
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
            # Используем опции для скачивания (с cookies)
            ydl_opts = self._get_download_options()
            
            info = await asyncio.wait_for(
                self._extract_info(query, ydl_opts),
                timeout=25
            )

            entries = info.get('entries', []) if info else []
            if not entries:
                logger.warning(f"Не найдено результатов для запроса: {query}")
                return DownloadResult(success=False, error="Ничего не найдено. Попробуйте другой запрос.")
            
            video_info = entries[0]
            
            if not video_info or not video_info.get("id"):
                return DownloadResult(success=False, error="Не удалось получить информацию о видео.")
            
            # Проверяем размер файла перед скачиванием
            filesize = video_info.get('filesize') or video_info.get('filesize_approx')
            if filesize and filesize > settings.MAX_FILE_SIZE_MB * 1024 * 1024:
                return DownloadResult(
                    success=False, 
                    error=f"Файл слишком большой ({filesize // (1024*1024)} МБ). Лимит: {settings.MAX_FILE_SIZE_MB} МБ."
                )

            await asyncio.wait_for(
                self._download_info(video_info, ydl_opts),
                timeout=settings.DOWNLOAD_TIMEOUT_S
            )
            
            video_id = video_info["id"]
            
            # Ищем скачанный файл
            downloaded_files = glob.glob(str(settings.DOWNLOADS_DIR / f"{video_id}.mp3"))
            
            if not downloaded_files:
                # Если .mp3 не найден, ищем любой файл с этим ID
                downloaded_files = glob.glob(str(settings.DOWNLOADS_DIR / f"{video_id}.*"))
                if not downloaded_files:
                    # Ищем частично скачанные файлы
                    downloaded_files = glob.glob(str(settings.DOWNLOADS_DIR / f"{video_id}*.part"))
                    if downloaded_files:
                        # Переименовываем .part файл в .mp3
                        part_file = downloaded_files[0]
                        mp3_path = part_file.replace('.part', '.mp3')
                        try:
                            os.rename(part_file, mp3_path)
                            downloaded_files = [mp3_path]
                        except Exception as e:
                            logger.error(f"Ошибка переименования файла: {e}")
                    
                    if not downloaded_files:
                        return DownloadResult(success=False, error="Файл не был создан после загрузки.")
                
                # Пробуем конвертировать найденный файл
                found_file = downloaded_files[0]
                if not found_file.endswith('.mp3'):
                    logger.warning(f"Найден файл {found_file} вместо .mp3. Пробую конвертировать...")
                    
                    # Создаем путь для MP3
                    mp3_path = settings.DOWNLOADS_DIR / f"{video_id}.mp3"
                    
                    try:
                        import subprocess
                        result = subprocess.run(
                            ["ffmpeg", "-i", found_file, "-codec:a", "libmp3lame", "-q:a", "2", str(mp3_path)],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            timeout=30
                        )
                        
                        if result.returncode != 0 or not os.path.exists(mp3_path):
                            # Если конвертация не удалась, пробуем другой метод
                            logger.warning("Конвертация не удалась, использую исходный файл")
                            mp3_path = found_file
                        else:
                            # Удаляем исходный файл
                            try:
                                os.remove(found_file)
                            except:
                                pass
                        
                        downloaded_files = [str(mp3_path)]
                        
                    except Exception as e:
                        logger.error(f"Ошибка конвертации: {e}")
                        downloaded_files = [found_file]
            
            actual_file_path = downloaded_files[0]

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
                return DownloadResult(success=False, error="YouTube требует подтверждение. Добавьте файл cookies.txt.")
            if "blocked" in err_str or "unavailable" in err_str or "429" in err_str:
                logger.error(f"[{self.name}] Запрос заблокирован YouTube. Проверьте IP или cookies.")
                return DownloadResult(success=False, error="Запрос заблокирован YouTube.")
            logger.error(f"[{self.name}] Ошибка yt-dlp: {e}")
            return DownloadResult(success=False, error=f"Ошибка загрузки: {str(e)[:100]}")
        except Exception as e:
            logger.error(f"[{self.name}] Непредвиденная ошибка: {e}", exc_info=True)
            return DownloadResult(success=False, error=f"Внутренняя ошибка: {e}")