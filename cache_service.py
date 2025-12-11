import asyncio
import json
import hashlib
import logging
from typing import Optional, List, Tuple

import aiosqlite

from config import Settings
from models import DownloadResult, Source, TrackInfo

logger = logging.getLogger(__name__)


class CacheService:
    """
    Асинхронный сервис для управления кэшем загрузок, рейтингами треков и избранным.
    """

    def __init__(self, settings: Settings):
        self._settings = settings
        self._db_path = settings.CACHE_DB_PATH
        self._ttl = settings.CACHE_TTL_DAYS * 86400  # in seconds
        self._is_initialized = False
        self._init_lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None

    async def initialize(self):
        """Инициализирует таблицы БД и запускает задачу очистки кэша."""
        async with self._init_lock:
            if not self._is_initialized:
                try:
                    async with aiosqlite.connect(self._db_path) as db:
                        # Таблица для кэша загрузок
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
                        await db.execute("CREATE INDEX IF NOT EXISTS idx_query_source ON cache(query, source)")

                        # Таблица для рейтингов (лайки/дизлайки)
                        await db.execute(
                            """
                            CREATE TABLE IF NOT EXISTS track_ratings (
                                user_id INTEGER NOT NULL,
                                track_id TEXT NOT NULL,
                                rating INTEGER NOT NULL,
                                PRIMARY KEY (user_id, track_id)
                            )
                            """
                        )
                        await db.execute("CREATE INDEX IF NOT EXISTS idx_track_id ON track_ratings(track_id)")

                        # Таблица для избранных треков пользователей
                        await db.execute(
                            """
                            CREATE TABLE IF NOT EXISTS user_favorites (
                                user_id INTEGER NOT NULL,
                                track_id TEXT NOT NULL,
                                title TEXT NOT NULL,
                                artist TEXT,
                                duration INTEGER,
                                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                PRIMARY KEY (user_id, track_id)
                            )
                            """
                        )
                        
                        # Таблица для закрепленных сообщений бота
                        await db.execute(
                            """
                            CREATE TABLE IF NOT EXISTS pinned_messages (
                                chat_id INTEGER PRIMARY KEY,
                                message_id INTEGER NOT NULL,
                                message_type TEXT NOT NULL
                            )
                            """
                        )
                        await db.commit()

                    self._is_initialized = True
                    self._cleanup_task = asyncio.create_task(self._cleanup_loop())
                    logger.info("База данных кэша, рейтингов и избранного инициализирована.")
                except Exception as e:
                    logger.error(f"Не удалось инициализировать БД: {e}", exc_info=True)

    async def close(self):
        """Останавливает фоновые задачи сервиса."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        logger.info("Сервис кэша остановлен.")

    # --- Методы для кэша загрузок ---

    def _get_cache_id(self, query: str, source: Source) -> str:
        key = f"{source.value.lower()}:{query.lower().strip()}"
        return hashlib.md5(key.encode()).hexdigest()

    async def get(self, query: str, source: Source) -> Optional[DownloadResult]:
        if not self._is_initialized: return None
        cache_id = self._get_cache_id(query, source)
        try:
            async with aiosqlite.connect(self._db_path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute("SELECT result_json FROM cache WHERE id = ?", (cache_id,))
                row = await cursor.fetchone()
                if not row: return None
                
                result_data = json.loads(row["result_json"])
                return DownloadResult(
                    success=result_data["success"],
                    file_path=result_data["file_path"],
                    track_info=TrackInfo(**result_data["track_info"]),
                    error=result_data.get("error"),
                )
        except Exception as e:
            logger.warning(f"Ошибка при чтении из кэша: {e}")
            return None

    async def set(self, query: str, source: Source, result: DownloadResult):
        if not self._is_initialized or not result.success or not result.track_info: return
        cache_id = self._get_cache_id(query, source)
        result_json = json.dumps(result.to_dict())
        try:
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute("INSERT OR REPLACE INTO cache (id, query, source, result_json) VALUES (?, ?, ?, ?)",
                                 (cache_id, query, source.value, result_json))
                await db.commit()
                logger.info(f"Результат для '{query}' ({source.value}) сохранен в кэш.")
        except Exception as e:
            logger.warning(f"Ошибка при записи в кэш: {e}")

    # --- Методы для рейтингов ---

    async def update_rating(self, user_id: int, track_id: str, rating: int) -> Tuple[int, int]:
        """Обновляет рейтинг трека. rating: 1 для лайка, -1 для дизлайка."""
        try:
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute(
                    "INSERT OR REPLACE INTO track_ratings (user_id, track_id, rating) VALUES (?, ?, ?)",
                    (user_id, track_id, rating)
                )
                await db.commit()
            return await self.get_ratings(track_id)
        except Exception as e:
            logger.error(f"Ошибка при обновлении рейтинга для track_id {track_id}: {e}", exc_info=True)
            return 0, 0

    async def get_ratings(self, track_id: str) -> Tuple[int, int]:
        """Возвращает кортеж (лайки, дизлайки) для трека."""
        try:
            async with aiosqlite.connect(self._db_path) as db:
                cursor = await db.execute(
                    "SELECT rating, COUNT(*) FROM track_ratings WHERE track_id = ? GROUP BY rating",
                    (track_id,)
                )
                rows = await cursor.fetchall()
                likes = sum(row[1] for row in rows if row[0] == 1)
                dislikes = sum(row[1] for row in rows if row[0] == -1)
                return likes, dislikes
        except Exception as e:
            logger.error(f"Ошибка при получении рейтинга для track_id {track_id}: {e}", exc_info=True)
            return 0, 0
            
    # --- Методы для избранного ---

    async def add_to_favorites(self, user_id: int, track_info: TrackInfo) -> bool:
        """Добавляет трек в избранное пользователя."""
        try:
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute(
                    "INSERT OR IGNORE INTO user_favorites (user_id, track_id, title, artist, duration) VALUES (?, ?, ?, ?, ?)",
                    (user_id, track_info.identifier, track_info.title, track_info.artist, track_info.duration)
                )
                await db.commit()
            logger.info(f"Трек {track_info.identifier} добавлен в избранное для user_id {user_id}")
            return True
        except Exception as e:
            logger.error(f"Ошибка при добавлении в избранное для user_id {user_id}: {e}", exc_info=True)
            return False

    async def remove_from_favorites(self, user_id: int, track_id: str) -> bool:
        """Удаляет трек из избранного пользователя."""
        try:
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute(
                    "DELETE FROM user_favorites WHERE user_id = ? AND track_id = ?",
                    (user_id, track_id)
                )
                await db.commit()
            logger.info(f"Трек {track_id} удален из избранного для user_id {user_id}")
            return True
        except Exception as e:
            logger.error(f"Ошибка при удалении из избранного для user_id {user_id}: {e}", exc_info=True)
            return False

    async def get_favorites(self, user_id: int) -> List[TrackInfo]:
        """Возвращает список избранных треков пользователя."""
        favorites = []
        try:
            async with aiosqlite.connect(self._db_path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    "SELECT track_id, title, artist, duration FROM user_favorites WHERE user_id = ? ORDER BY added_at DESC",
                    (user_id,)
                )
                rows = await cursor.fetchall()
                for row in rows:
                    favorites.append(TrackInfo(
                        identifier=row["track_id"],
                        title=row["title"],
                        artist=row["artist"],
                        duration=row["duration"],
                        source=Source.YOUTUBE.value # Предполагаем, что все избранное с YouTube
                    ))
        except Exception as e:
            logger.error(f"Ошибка при получении избранного для user_id {user_id}: {e}", exc_info=True)
        return favorites

    async def is_in_favorites(self, user_id: int, track_id: str) -> bool:
        """Проверяет, находится ли трек в избранном у пользователя."""
        try:
            async with aiosqlite.connect(self._db_path) as db:
                cursor = await db.execute(
                    "SELECT 1 FROM user_favorites WHERE user_id = ? AND track_id = ?",
                    (user_id, track_id)
                )
                return await cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"Ошибка при проверке избранного для user_id {user_id}: {e}", exc_info=True)
            return False
            
    # --- Методы для закрепленных сообщений ---
    async def set_pinned_help_message_info(self, chat_id: int, message_id: int):
        """Сохраняет ID закрепленного сообщения справки для чата."""
        try:
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute(
                    "INSERT OR REPLACE INTO pinned_messages (chat_id, message_id, message_type) VALUES (?, ?, ?)",
                    (chat_id, message_id, 'help')
                )
                await db.commit()
        except Exception as e:
            logger.error(f"Ошибка при сохранении информации о закрепленном сообщении: {e}", exc_info=True)

    async def get_pinned_help_message_info(self, chat_id: int) -> Optional[dict]:
        """Возвращает информацию о закрепленном сообщении справки для чата."""
        try:
            async with aiosqlite.connect(self._db_path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    "SELECT message_id FROM pinned_messages WHERE chat_id = ? AND message_type = ?",
                    (chat_id, 'help')
                )
                row = await cursor.fetchone()
                if row:
                    return {"message_id": row["message_id"]}
                return None
        except Exception as e:
            logger.error(f"Ошибка при получении информации о закрепленном сообщении: {e}", exc_info=True)
            return None

    # --- Фоновые задачи ---

    async def _cleanup_loop(self):
        """Периодически удаляет устаревшие записи из кэша загрузок."""
        while True:
            await asyncio.sleep(3600)  # Каждый час
            try:
                async with aiosqlite.connect(self._db_path) as db:
                    cursor = await db.execute(
                        "DELETE FROM cache WHERE (julianday('now') - julianday(created_at)) * 86400 > ?",
                        (self._ttl,),
                    )
                    await db.commit()
                    deleted_count = cursor.rowcount
                    if deleted_count > 0:
                        logger.info(f"{deleted_count} устаревших записей удалено из кэша.")
            except Exception as e:
                logger.error(f"Ошибка при очистке кэша: {e}")
