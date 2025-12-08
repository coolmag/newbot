import asyncio
import json
import hashlib
import logging
from typing import Optional

import aiosqlite

from config import Settings
from models import DownloadResult, Source, TrackInfo

logger = logging.getLogger(__name__)


class CacheService:
    """
    Асинхронный менеджер кэша на основе aiosqlite.
    Кэширует результаты загрузок, чтобы избежать повторных обращений к API.
    """

    def __init__(self, settings: Settings):
        self._settings = settings
        self._db_path = settings.CACHE_DB_PATH
        self._ttl = settings.CACHE_TTL_DAYS * 86400  # in seconds
        self._is_initialized = False
        self._init_lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None

    async def initialize(self):
        """Инициализирует базу данных и запускает задачу очистки."""
        async with self._init_lock:
            if not self._is_initialized:
                try:
                    async with aiosqlite.connect(self._db_path) as db:
                        await db.execute(
                            """
                            CREATE TABLE IF NOT EXISTS cache (
                                id TEXT PRIMARY KEY,
                                query TEXT NOT NULL,
                                source TEXT NOT NULL,
                                result_json TEXT NOT NULL,
                                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                            )
                            """
                        )
                        await db.execute(
                            "CREATE INDEX IF NOT EXISTS idx_query_source ON cache(query, source)"
                        )
                        await db.commit()
                    self._is_initialized = True
                    self._cleanup_task = asyncio.create_task(self._cleanup_loop())
                    logger.info("База данных кэша инициализирована.")
                except Exception as e:
                    logger.error(f"Не удалось инициализировать БД кэша: {e}", exc_info=True)

    async def close(self):
        """Закрывает задачу очистки."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        logger.info("Сервис кэша остановлен.")

    def _get_cache_id(self, query: str, source: Source) -> str:
        """Создает уникальный ID для записи в кэше."""
        key = f"{source.value.lower()}:{query.lower().strip()}"
        return hashlib.md5(key.encode()).hexdigest()

    async def get(self, query: str, source: Source) -> Optional[DownloadResult]:
        """Ищет результат в кэше."""
        if not self._is_initialized:
            return None

        cache_id = self._get_cache_id(query, source)
        try:
            async with aiosqlite.connect(self._db_path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    "SELECT result_json, created_at FROM cache WHERE id = ?", (cache_id,)
                )
                row = await cursor.fetchone()

                if not row:
                    return None

                result_data = json.loads(row["result_json"])
                track_info = TrackInfo(**result_data["track_info"])
                return DownloadResult(
                    success=result_data["success"],
                    file_path=result_data["file_path"],
                    track_info=track_info,
                    error=result_data.get("error"),
                )

        except Exception as e:
            logger.warning(f"Ошибка при чтении из кэша: {e}")
            return None

    async def set(self, query: str, source: Source, result: DownloadResult):
        """Сохраняет успешный результат в кэш."""
        if not self._is_initialized or not result.success or not result.track_info:
            return

        cache_id = self._get_cache_id(query, source)
        result_dict = {
            "success": result.success,
            "file_path": result.file_path,
            "track_info": result.track_info.__dict__,
            "error": result.error,
        }
        result_json = json.dumps(result_dict)

        try:
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute(
                    "INSERT OR REPLACE INTO cache (id, query, source, result_json) VALUES (?, ?, ?, ?)",
                    (cache_id, query, source.value, result_json),
                )
                await db.commit()
                logger.info(f"Результат для '{query}' ({source.value}) сохранен в кэш.")
        except Exception as e:
            logger.warning(f"Ошибка при записи в кэш: {e}")

    async def _cleanup_loop(self):
        """Периодически удаляет устаревшие записи из кэша."""
        while True:
            await asyncio.sleep(3600)  # Каждый час
            try:
                async with aiosqlite.connect(self._db_path) as db:
                    cursor = await db.execute(
                        "DELETE FROM cache WHERE (julianday('now') - julianday(created_at)) * 86400 > ?",
                        (self._ttl,),
                    )
                    await db.commit()
                    logger.info(f"{cursor.rowcount} устаревших записей удалено из кэша.")
            except Exception as e:
                logger.error(f"Ошибка при очистке кэша: {e}")
