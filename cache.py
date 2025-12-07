
import json
import hashlib
import asyncio
import os
from typing import Optional

import aiosqlite

from base import DownloadResult
from config import settings, Source, TrackInfo
from logger import logger


class CacheManager:
    """
    Асинхронный менеджер кэша на основе aiosqlite.
    Кэширует результаты загрузок, чтобы избежать повторных обращений к API.
    """
    _instance = None
    _lock = asyncio.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(CacheManager, cls).__new__(cls)
            cls._instance.initialized = False
        return cls._instance

    async def _init_db(self):
        """Инициализирует базу данных и таблицу для кэша, если это еще не сделано."""
        async with self._lock:
            if not self.initialized:
                try:
                    async with aiosqlite.connect(settings.CACHE_DB_PATH) as db:
                        await db.execute("""
                            CREATE TABLE IF NOT EXISTS cache (
                                id TEXT PRIMARY KEY,
                                query TEXT NOT NULL,
                                source TEXT NOT NULL,
                                result_json TEXT NOT NULL,
                                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                            )
                        """)
                        await db.execute("CREATE INDEX IF NOT EXISTS idx_query_source ON cache(query, source)")
                        await db.commit()
                    self.initialized = True
                    logger.info("✅ База данных кэша инициализирована.")
                except Exception as e:
                    logger.error(f"❌ Не удалось инициализировать БД кэша: {e}", exc_info=True)

    def _get_cache_id(self, query: str, source: Source) -> str:
        """Создает уникальный ID для записи в кэше на основе запроса и источника."""
        key = f"{source.value.lower()}:{query.lower().strip()}"
        return hashlib.md5(key.encode()).hexdigest()

    async def get(self, query: str, source: Source) -> Optional[DownloadResult]:
        """
        Ищет результат в кэше. Если запись устарела, удаляет ее.
        """
        await self._init_db()
        if not self.initialized:
            return None

        cache_id = self._get_cache_id(query, source)
        try:
            async with aiosqlite.connect(settings.CACHE_DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                # Проверяем срок годности прямо в запросе
                query_sql = """
                    SELECT result_json FROM cache 
                    WHERE id = ? AND (julianday('now') - julianday(created_at)) * 86400 < ?
                """
                cursor = await db.execute(query_sql, (cache_id, settings.CACHE_TTL_DAYS * 86400))
                row = await cursor.fetchone()

                if row:
                    result_data = json.loads(row['result_json'])
                    
                    # Проверяем существование файла перед возвратом из кэша
                    file_path = result_data.get("file_path")
                    if file_path and not os.path.exists(file_path):
                        # Файл был удален, удаляем запись из кэша
                        await db.execute("DELETE FROM cache WHERE id = ?", (cache_id,))
                        await db.commit()
                        logger.info(f"⚠️ Файл из кэша не найден, запись удалена: '{query}' ({source.value}).")
                        return None
                    
                    logger.info(f"✅ Кэш найден для '{query}' ({source.value}).")
                    
                    # Восстанавливаем TrackInfo
                    track_info_data = result_data.pop("track_info", None)
                    if track_info_data:
                        result_data["track_info"] = TrackInfo(**track_info_data)
                        
                    return DownloadResult(**result_data)
                else:
                    # Если запись не найдена (возможно, из-за срока годности), удаляем ее
                    await db.execute("DELETE FROM cache WHERE id = ?", (cache_id,))
                    await db.commit()
                    
        except Exception as e:
            logger.warning(f"⚠️ Ошибка при чтении из кэша: {e}")
        
        return None

    async def set(self, query: str, source: Source, result: DownloadResult):
        """
        Сохраняет успешный результат в кэш.
        """
        if not result.success or not result.track_info:
            return

        await self._init_db()
        if not self.initialized:
            return

        cache_id = self._get_cache_id(query, source)
        
        # Преобразуем TrackInfo в словарь для JSON-сериализации
        track_info_dict = {
            "title": result.track_info.title,
            "artist": result.track_info.artist,
            "duration": result.track_info.duration,
            "source": result.track_info.source,
        }
        
        result_dict = {
            "success": result.success,
            "file_path": result.file_path,
            "track_info": track_info_dict,
            "error": result.error,
        }
        result_json = json.dumps(result_dict)

        try:
            async with aiosqlite.connect(settings.CACHE_DB_PATH) as db:
                await db.execute(
                    "INSERT OR REPLACE INTO cache (id, query, source, result_json) VALUES (?, ?, ?, ?)",
                    (cache_id, query, source.value, result_json)
                )
                await db.commit()
                logger.info(f"💿 Результат для '{query}' ({source.value}) сохранен в кэш.")
        except Exception as e:
            logger.warning(f"⚠️ Ошибка при записи в кэш: {e}")

