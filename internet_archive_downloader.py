import asyncio
import aiohttp
import os
import random
from typing import Dict, Any

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

    async def download(self, query: str) -> DownloadResult:
        """
        Ищет и скачивает аудиофайл с Internet Archive по жанру.
        """
        source = Source.INTERNET_ARCHIVE  # Предполагаем, что Source будет расширен
        cached = await self.cache.get(query, source)
        if cached:
            return cached

        logger.info(f"[{self.name}] Поиск аудио в жанре '{query}' на Internet Archive...")

        try:
            # 1. Поиск аудиофайлов по жанру
            search_params = {
                "q": f"mediatype:audio AND subject:\"{query}\"",
                "fl[]": ["identifier", "title", "creator", "length"],
                "rows": 50,
                "page": random.randint(1, 5), # Добавляем случайности
                "output": "json"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(self.API_URL, params=search_params) as response:
                    response.raise_for_status()
                    data = await response.json()
            
            docs = data.get("response", {}).get("docs", [])
            if not docs:
                return DownloadResult(success=False, error=f"Не найдено аудио в жанре '{query}'.")

            # 2. Выбор случайного трека и получение информации о нем
            selected_doc = random.choice(docs)
            identifier = selected_doc.get("identifier")
            if not identifier:
                return DownloadResult(success=False, error="Не удалось получить идентификатор трека.")

            # 3. Получение метаданных файла для поиска MP3
            metadata_url = f"https://archive.org/metadata/{identifier}"
            async with aiohttp.ClientSession() as session:
                async with session.get(metadata_url) as response:
                    response.raise_for_status()
                    metadata = await response.json()
            
            files = metadata.get("files", [])
            mp3_files = [f for f in files if f.get("format") == "VBR MP3"]
            if not mp3_files:
                return DownloadResult(success=False, error="Не найдено MP3 файлов для данного трека.")

            # 4. Скачивание MP3 файла
            mp3_file_info = random.choice(mp3_files)
            file_name = mp3_file_info.get("name")
            download_url = f"https://archive.org/download/{identifier}/{file_name}"
            
            file_path = settings.DOWNLOADS_DIR / f"{identifier}_{file_name}"

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
