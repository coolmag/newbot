import asyncio
import logging
import random
import os
from typing import Optional, Set

from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError

from config import Settings
from models import DownloadResult, TrackInfo
from downloaders import BaseDownloader
from keyboards import get_track_control_keyboard

logger = logging.getLogger(__name__)


class RadioService:
    """
    Сервис для управления фоновым воспроизведением музыки ("радио").
    """

    def __init__(self, settings: Settings, bot: Bot, downloader: BaseDownloader):
        self._settings = settings
        self._bot = bot
        self._downloader = downloader
        self._task: Optional[asyncio.Task] = None
        self._is_on = False
        self._skip_event = asyncio.Event()
        self._playlist: list[TrackInfo] = []
        self._played_ids: Set[str] = set()
        self._current_genre: Optional[str] = None
        self.error_count = 0

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def start(self, chat_id: int):
        """Запускает фоновую задачу радио."""
        if self._task and not self._task.done():
            return

        self._is_on = True
        self._skip_event.clear()
        self.error_count = 0
        self._playlist = []
        self._played_ids = set()
        self._task = asyncio.create_task(self._radio_loop(chat_id))
        logger.info(f"✅ Радио-задача создана и запущена для чата {chat_id}.")


    async def stop(self):
        """Останавливает радио."""
        self._is_on = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("⏹️ Радио остановлено.")

    async def skip(self):
        """Пропускает текущий трек."""
        if self._is_on:
            self._skip_event.set()

    def set_genre(self, genre: str):
        """Принудительно устанавливает жанр для следующего поиска."""
        if genre in self._settings.RADIO_GENRES:
            self._current_genre = genre
            self._playlist = []  # Очищаем плейлист, чтобы сразу начать поиск по новому жанру
            self._skip_event.set() # Прерываем ожидание, чтобы цикл начался заново
            logger.info(f"[Радио] Установлен новый жанр: {genre}")
            return True
        return False

    async def _fetch_playlist(self):
        """
        Запрашивает новый плейлист, используя более "умные" поисковые запросы.
        """
        # Если жанр не установлен (первый запуск), выбираем случайный
        if not self._current_genre:
            self._current_genre = random.choice(self._settings.RADIO_GENRES)

        query_templates = [
            f"{self._current_genre} official audio",
            f"{self._current_genre} song",
            f"Top {self._current_genre} music",
        ]
        search_query = random.choice(query_templates)
        
        logger.info(f"[Радио] Ищу треки по запросу: '{search_query}'")
        
        # Первая попытка с фильтрами популярности
        new_tracks = await self._downloader.search(
            search_query, 
            limit=50, 
            max_duration=self._settings.RADIO_MAX_DURATION_S,
            min_views=self._settings.RADIO_MIN_VIEWS,
            min_likes=self._settings.RADIO_MIN_LIKES,
            min_like_ratio=self._settings.RADIO_MIN_LIKE_RATIO,
        )
        
        if not new_tracks and (self._settings.RADIO_MIN_VIEWS is not None or 
                               self._settings.RADIO_MIN_LIKES is not None or 
                               self._settings.RADIO_MIN_LIKE_RATIO is not None):
            logger.warning(f"[Радио] Поиск '{search_query}' с фильтрами популярности не дал результатов. Пробую без фильтров.")
            # Вторая попытка без фильтров популярности (механизм отката)
            new_tracks = await self._downloader.search(
                search_query, 
                limit=50, 
                max_duration=self._settings.RADIO_MAX_DURATION_S,
                min_views=None,
                min_likes=None,
                min_like_ratio=None,
            )

        if new_tracks:
            # Фильтруем треки, которые уже были в плейлисте
            unique_tracks = [track for track in new_tracks if track.identifier not in self._played_ids]
            self._playlist.extend(unique_tracks)
            logger.info(f"[Радио] Добавлено {len(unique_tracks)} уникальных треков в плейлист. Всего: {len(self._playlist)}")
        else:
            logger.warning(f"[Радио] Не удалось получить плейлист для запроса '{search_query}'.")
            self.error_count += 1

    async def _send_audio(self, chat_id: int, result: DownloadResult):
        """Отправляет аудиофайл в чат и удаляет его после отправки."""
        if not result.file_path or not os.path.exists(result.file_path):
            logger.error(f"[Радио] Файл для отправки не найден: {result.file_path}")
            return

        try:
            with open(result.file_path, "rb") as audio_file:
                await self._bot.send_audio(
                    chat_id=chat_id,
                    audio=audio_file,
                    title=result.track_info.title,
                    performer=result.track_info.artist,
                    duration=result.track_info.duration,
                    caption=f"🎶 *Радио | {self._current_genre}*\n\n`{result.track_info.display_name}`",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=get_track_control_keyboard(),
                )
        except TelegramError as e:
            logger.error(f"Ошибка Telegram при отправке радио-аудио: {e}")
            # Не увеличиваем счетчик ошибок, если это проблема с Telegram
        finally:
            try:
                os.remove(result.file_path)
            except OSError as e:
                logger.error(f"Не удалось удалить файл {result.file_path}: {e}")

    async def _radio_loop(self, chat_id: int):
        """Основной цикл радио с проактивной подгрузкой и отказоустойчивостью."""
        await self._bot.send_message(chat_id, "🎵 Радио запускается...")
        
        while self._is_on and self.error_count < 10:
            try:
                # Если плейлист почти пуст, пытаемся его пополнить
                if len(self._playlist) < 10:
                    logger.info("[Радио] Плейлист на исходе, запускаю пополнение...")
                    # Делаем несколько попыток с разными запросами, прежде чем сдаться
                    for attempt in range(3):
                        await self._fetch_playlist()
                        if self._playlist: # Если удалось что-то найти, выходим из цикла попыток
                            break
                        logger.warning(f"[Радио] Попытка пополнения #{attempt + 1} не дала результатов.")
                        await asyncio.sleep(2) # Небольшая пауза между попытками
                
                # Если после всех попыток плейлист все еще пуст, берем большую паузу
                if not self._playlist:
                    logger.warning(f"[Радио] Плейлист пуст. Беру паузу. Общее число ошибок: {self.error_count + 1}/10")
                    await asyncio.sleep(self._settings.RETRY_DELAY_S * (self.error_count + 1))
                    continue
                
                track_to_play = self._playlist.pop(0)
                
                if track_to_play.identifier:
                    self._played_ids.add(track_to_play.identifier)
                    if len(self._played_ids) > 200:
                        self._played_ids.pop()

                logger.info(f"[Радио] Скачиваю: {track_to_play.display_name} (ID: {track_to_play.identifier})")
                result = await self._downloader.download_with_retry(track_to_play.identifier)

                if result.success:
                    await self._send_audio(chat_id, result)
                    self.error_count = 0
                    
                    try:
                        await asyncio.wait_for(
                            self._skip_event.wait(), timeout=self._settings.RADIO_COOLDOWN_S
                        )
                        self._skip_event.clear()
                        logger.info("[Радио] Трек пропущен по запросу.")
                    except asyncio.TimeoutError:
                        pass
                else:
                    logger.warning(f"[Радио] Ошибка скачивания: {result.error}")
                    self.error_count += 1
                    await asyncio.sleep(3)


            except asyncio.CancelledError:
                logger.info("[Радио] Цикл остановлен.")
                break
            except Exception as e:
                logger.error(f"Непредвиденная ошибка в цикле радио: {e}", exc_info=True)
                self.error_count += 1
                await asyncio.sleep(5)

        if self.error_count >= 10:
            logger.error("[Радио] Превышено максимальное количество ошибок. Радио остановлено.")
            await self._bot.send_message(
                chat_id,
                "⚠️ Радио было остановлено из-за большого количества ошибок при скачивании."
            )
        
        self._is_on = False
        logger.info(f"⏹️ Радио-цикл завершен для чата {chat_id}.")
