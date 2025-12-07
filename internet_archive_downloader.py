import asyncio
import aiohttp
import os
import random
from typing import Dict, Any, List

from base import BaseDownloader, DownloadResult
from config import settings, TrackInfo, Source
from logger import logger
from cache import CacheManager

class InternetArchiveDownloader(BaseDownloader):
    """
    Загрузчик для Internet Archive.
    Использует API для поиска и скачивания аудиофайлов.
    """
    
    API_URL = "https://archive.org/advancedsearch.php"

    def __init__(self):
        super().__init__()
        self.cache = CacheManager()

    async def search(self, query: str, limit: int = 30) -> List[TrackInfo]:
        """
        Ищет аудиофайлы на Internet Archive и возвращает список треков.
        """
        logger.info(f"[{self.name}] Поиск плейлиста в жанре '{query}' на Internet Archive...")
        
        try:
            search_params = {
                "q": f"mediatype:audio AND subject:\"{query}\"",
                "fl[]": ["identifier", "title", "creator", "length"],
                "rows": limit,
                "page": random.randint(1, 5),
                "output": "json"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(self.API_URL, params=search_params) as response:
                    response.raise_for_status()
                    data = await response.json()
            
            docs = data.get("response", {}).get("docs", [])
            if not docs:
                logger.warning(f"Не найдено треков в жанре '{query}' на Internet Archive.")
                return []
            
            playlist = []
            for doc in docs:
                # Пропускаем треки без длительности или с некорректной длительностью
                try:
                    duration = int(float(doc.get("length", 0)))
                    if duration <= 0:
                        continue
                except (ValueError, TypeError):
                    continue

                track_info = TrackInfo(
                    title=doc.get("title", "Unknown Title"),
                    artist=doc.get("creator", "Unknown Artist"),
                    duration=duration,
                    source=Source.INTERNET_ARCHIVE.value,
                    identifier=doc.get("identifier"),
                )
                playlist.append(track_info)
            
            logger.info(f"Найдено {len(playlist)} треков в жанре '{query}'.")
            return playlist

        except aiohttp.ClientError as e:
            logger.error(f"[{self.name}] Ошибка сети при поиске на Internet Archive: {e}")
            return []
        except Exception as e:
            logger.error(f"[{self.name}] Непредвиденная ошибка при поиске: {e}", exc_info=True)
            return []

    async def download(self, query: str) -> DownloadResult:
        """
        Ищет и скачивает аудиофайл с Internet Archive.
        Если query - это идентификатор, скачивает напрямую.
        Иначе - ищет по жанру.
        """
        source = Source.INTERNET_ARCHIVE
        cached = await self.cache.get(query, source)
        if cached:
            return cached

        try:
            is_identifier = " " not in query and len(query) > 5

            if is_identifier:
                identifier = query
                logger.info(f"[{self.name}] Скачивание по идентификатору '{identifier}'...")
                
                # Получаем метаданные, чтобы узнать title, artist, duration
                metadata_url = f"https://archive.org/metadata/{identifier}"
                async with aiohttp.ClientSession() as session:
                    async with session.get(metadata_url) as response:
                        response.raise_for_status()
                        metadata = await response.json()
                
                selected_doc = {
                    "title": metadata.get("metadata", {}).get("title", "Unknown Title"),
                    "creator": metadata.get("metadata", {}).get("creator", "Unknown Artist"),
                    "length": metadata.get("metadata", {}).get("length", 0),
                }

            else: # Поиск по жанру
                logger.info(f"[{self.name}] Поиск аудио в жанре '{query}'...")
                search_params = {
                    "q": f"mediatype:audio AND subject:\"{query}\"",
                    "fl[]": ["identifier", "title", "creator", "length"],
                    "rows": 50,
                    "page": random.randint(1, 5),
                    "output": "json"
                }
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(self.API_URL, params=search_params) as response:
                        response.raise_for_status()
                        data = await response.json()
                
                docs = data.get("response", {}).get("docs", [])
                if not docs:
                    return DownloadResult(success=False, error=f"Не найдено аудио в жанре '{query}'.")

                selected_doc = random.choice(docs)
                identifier = selected_doc.get("identifier")
                if not identifier:
                    return DownloadResult(success=False, error="Не удалось получить идентификатор трека.")

                # Получаем метаданные файла, чтобы найти MP3
                metadata_url = f"https://archive.org/metadata/{identifier}"
                async with aiohttp.ClientSession() as session:
                    async with session.get(metadata_url) as response:
                        response.raise_for_status()
                        metadata = await response.json()

            # Общая логика скачивания
            files = metadata.get("files", [])
            mp3_files = [f for f in files if f.get("format") and "MP3" in f.get("format")]
            if not mp3_files:
                return DownloadResult(success=False, error="Не найдено MP3 файлов для данного трека.")

            mp3_file_info = random.choice(mp3_files)
            file_name = mp3_file_info.get("name")
            download_url = f"https://archive.org/download/{identifier}/{file_name}"
            
            file_path = settings.DOWNLOADS_DIR / f"{identifier}_{file_name.replace('/', '_')}"

            async with aiohttp.ClientSession() as session:
                async with session.get(download_url) as response:
                    response.raise_for_status()
                    with open(file_path, "wb") as f:
                        while True:
                            chunk = await response.content.read(1024)
                            if not chunk:
                                break
                            f.write(chunk)
            
            track_info = TrackInfo(
                title=selected_doc.get("title", "Unknown Title"),
                artist=selected_doc.get("creator", "Unknown Artist"),
                duration=int(float(selected_doc.get("length", 0))),
                source=source.value,
                identifier=identifier,
            )

            result = DownloadResult(success=True, file_path=str(file_path), track_info=track_info)
            await self.cache.set(query, source, result)
            return result

        except aiohttp.ClientError as e:
            logger.error(f"[{self.name}] Ошибка сети при работе с Internet Archive: {e}")
            return DownloadResult(success=False, error="Ошибка сети при доступе к Internet Archive.")
        except Exception as e:
            logger.error(f"[{self.name}] Непредвиденная ошибка: {e}", exc_info=True)
            return DownloadResult(success=False, error=f"Внутренняя ошибка: {e}")
