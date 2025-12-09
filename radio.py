import asyncio
import logging
import random
import os
from datetime import datetime, timedelta
from typing import Optional, Set, Dict, Tuple

from telegram import Bot, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import TelegramError

from config import Settings
from models import DownloadResult, TrackInfo
from downloaders import BaseDownloader
# get_track_control_keyboard будет использоваться для сообщений о голосовании
from keyboards import get_track_control_keyboard, get_genre_voting_keyboard, get_voting_in_progress_keyboard

logger = logging.getLogger(__name__)


class RadioService:
    """
    Сервис для управления фоновым воспроизведением музыки ("радио") 
    с системой голосования и режимом артиста.
    """

    def __init__(self, settings: Settings, bot: Bot, downloader: BaseDownloader):
        self._settings = settings
        self._bot = bot
        self._downloader = downloader
        
        # --- Состояние радио ---
        self._task: Optional[asyncio.Task] = None
        self._is_on = False
        self._skip_event = asyncio.Event()
        self.error_count = 0
        
        # --- Состояние плейлиста ---
        self._playlist: list[TrackInfo] = []
        self._played_ids: Set[str] = set()

        # --- Состояние режимов (голосование/артист) ---
        self.current_mode_message_info: Optional[Tuple[int, int]] = None # (chat_id, message_id)
        self.artist_mode: Optional[str] = None
        self.winning_genre: str = "rock"  # Начинаем с рока по умолчанию
        self.mode_end_time: Optional[datetime] = None

        # --- Состояние голосования ---
        self._vote_in_progress: bool = False
        self._votes: Dict[str, Set[int]] = {} # {genre: {user_id_1, user_id_2}}

    @property
    def is_on(self) -> bool:
        return self._is_on

    @property
    def is_vote_in_progress(self) -> bool:
        return self._vote_in_progress

    # --- Управление радио ---

    async def start(self, chat_id: int):
        """Запускает фоновую задачу радио."""
        if self._task and not self._task.done():
            return

        self._is_on = True
        self._skip_event.clear()
        self.error_count = 0
        self._playlist = []
        self._played_ids = set()
        self.mode_end_time = None # Сбрасываем таймер, чтобы голосование началось сразу
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

    # --- Управление режимами ---
    async def set_admin_genre(self, genre: str, chat_id: int):
        """Принудительно устанавливает жанр админом."""
        self.winning_genre = genre
        self.artist_mode = None
        self.mode_end_time = datetime.now() + timedelta(hours=1)
        self._playlist = []

        # Если идет голосование, его нужно прервать
        if self._vote_in_progress:
            self._vote_in_progress = False
            if self.current_mode_message_info:
                try:
                    await self._bot.edit_message_text(
                        chat_id=self.current_mode_message_info[0],
                        message_id=self.current_mode_message_info[1],
                        text=f"🗳️ Голосование было отменено.\nАдминистратор установил жанр: **{genre.capitalize()}**",
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=None
                    )
                except TelegramError as e:
                    logger.warning(f"Не удалось отменить сообщение о голосовании: {e}")
        
        await self._bot.send_message(
            chat_id,
            f"✅ Жанр принудительно изменен на **{genre.capitalize()}**. Этот жанр будет играть следующий час.",
            parse_mode=ParseMode.MARKDOWN,
        )

        logger.info(f"[Режим] Админ установил жанр: {genre} на 1 час.")
        self.skip()

    async def set_artist_mode(self, artist: str, chat_id: int):
        """Включает режим проигрывания одного артиста на час."""
        self.artist_mode = artist
        self.winning_genre = None # Отключаем жанр
        self.mode_end_time = datetime.now() + timedelta(hours=1)
        self._playlist = []
        logger.info(f"[Режим] Включен режим артиста: {artist} на 1 час.")
        
        try:
            await self._bot.send_message(
                chat_id,
                f"🎤 Следующий час играет: **{artist}**!",
                parse_mode=ParseMode.MARKDOWN
            )
        except TelegramError as e:
            logger.error(f"Не удалось отправить сообщение о режиме артиста: {e}")

        self.skip() # Пропускаем текущий трек, чтобы сразу начать новый режим

    # --- Логика голосования ---

    async def start_genre_vote(self, chat_id: int):
        """Начинает 5-минутное голосование за жанр."""
        if self._vote_in_progress:
            return

        logger.info("[Голосование] Начинается голосование за жанр.")
        self._vote_in_progress = True
        self._votes = {}
        self.artist_mode = None # Голосование отменяет режим артиста

        try:
            vote_message = await self._bot.send_message(
                chat_id,
                "📢 **Началось голосование за жанр!**\n\nВыберите, что будет играть следующий час. "
                "Голосование продлится 5 минут.",
                reply_markup=get_genre_voting_keyboard(),
                parse_mode=ParseMode.MARKDOWN
            )
            self.current_mode_message_info = (vote_message.chat_id, vote_message.message_id)
        except TelegramError as e:
            logger.error(f"Не удалось отправить сообщение о голосовании: {e}")
            self._vote_in_progress = False # Откатываем состояние
            return

        await asyncio.sleep(300) # 5 минут на голосование
        if self._vote_in_progress: # Проверяем, не было ли отменено голосование
            await self.end_genre_vote(chat_id)

    async def register_vote(self, genre: str, user_id: int) -> bool:
        """Регистрирует голос пользователя."""
        if not self._vote_in_progress:
            return False
        
        # Убираем старый голос пользователя, если он был
        for g in self._votes:
            self._votes[g].discard(user_id)
            
        # Добавляем новый голос
        if genre not in self._votes:
            self._votes[genre] = set()
        self._votes[genre].add(user_id)
        
        logger.debug(f"[Голосование] Пользователь {user_id} проголосовал за {genre}.")
        return True

    async def end_genre_vote(self, chat_id: int):
        """Подводит итоги голосования."""
        if not self._vote_in_progress:
            return
            
        logger.info("[Голосование] Голосование завершено. Подвожу итоги.")
        self._vote_in_progress = False

        # Подсчет голосов
        if self._votes:
            winner = max(self._votes, key=lambda g: len(self._votes[g]))
            self.winning_genre = winner
        else:
            self.winning_genre = "rock" # Значение по умолчанию
        
        self.mode_end_time = datetime.now() + timedelta(hours=1)
        self._playlist = [] # Очищаем плейлист
        
        announcement = f"🎉 **Голосование завершено!**\n\nСледующий час играет: **{self.winning_genre.capitalize()}**"
        logger.info(f"[Режим] По результатам голосования установлен жанр: {self.winning_genre}")

        try:
            if self.current_mode_message_info:
                await self._bot.edit_message_text(
                    chat_id=self.current_mode_message_info[0],
                    message_id=self.current_mode_message_info[1],
                    text=announcement,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=None # Убираем кнопки
                )
            else:
                 await self._bot.send_message(chat_id, announcement, parse_mode=ParseMode.MARKDOWN)
        except TelegramError as e:
            logger.warning(f"Не удалось обновить сообщение о голосовании: {e}")
            # Все равно отправляем новое, если не получилось отредактировать
            await self._bot.send_message(chat_id, announcement, parse_mode=ParseMode.MARKDOWN)

        self.skip() # Запускаем новый трек

    # --- Внутренний цикл радио ---

    async def _get_next_query(self) -> str:
        """Определяет, какой поисковый запрос использовать, на основе текущего режима."""
        if self.artist_mode:
            return self.artist_mode
        
        # Если жанр не определен или это первый запуск, используем дефолтный
        current_genre = self.winning_genre or "rock"

        query_templates = [
            f"{current_genre} official audio",
            f"best of {current_genre}",
            f"{current_genre} music",
        ]
        return random.choice(query_templates)

    async def _fetch_playlist(self, query: str):
        """Запрашивает новый плейлист по заданному запросу."""
        logger.info(f"[Радио] Ищу треки по запросу: '{query}'")
        
        new_tracks = await self._downloader.search(
            query, 
            limit=50, 
            max_duration=self._settings.RADIO_MAX_DURATION_S,
            min_views=self._settings.RADIO_MIN_VIEWS,
            min_likes=self._settings.RADIO_MIN_LIKES,
        )
        
        if not new_tracks and (self._settings.RADIO_MIN_VIEWS or self._settings.RADIO_MIN_LIKES):
            logger.warning(f"[Радио] Поиск '{query}' с фильтрами не дал результатов. Пробую без них.")
            new_tracks = await self._downloader.search(
                query, limit=50, max_duration=self._settings.RADIO_MAX_DURATION_S
            )

        if new_tracks:
            unique_tracks = [track for track in new_tracks if track.identifier not in self._played_ids]
            random.shuffle(unique_tracks)
            self._playlist.extend(unique_tracks)
            logger.info(f"[Радио] Добавлено {len(unique_tracks)} уник. треков. Всего в плейлисте: {len(self._playlist)}")
        else:
            logger.warning(f"[Радио] Не удалось получить плейлист для запроса '{query}'.")
            self.error_count += 1

    async def _send_audio(self, chat_id: int, result: DownloadResult):
        """Отправляет аудиофайл в чат."""
        if not result.file_path or not os.path.exists(result.file_path):
            logger.error(f"[Радио] Файл для отправки не найден: {result.file_path}")
            return
        
        caption_mode = self.artist_mode or self.winning_genre.capitalize()
        caption = f"🎶 *Радио | {caption_mode}*\n\n`{result.track_info.display_name}`"

        try:
            with open(result.file_path, "rb") as audio_file:
                await self._bot.send_audio(
                    chat_id=chat_id, audio=audio_file, title=result.track_info.title,
                    performer=result.track_info.artist, duration=result.track_info.duration,
                    caption=caption, parse_mode=ParseMode.MARKDOWN,
                    reply_markup=get_track_control_keyboard(),
                )
        except TelegramError as e:
            logger.error(f"Ошибка Telegram при отправке радио-аудио: {e}")
        finally:
            try:
                os.remove(result.file_path)
            except OSError as e:
                logger.error(f"Не удалось удалить файл {result.file_path}: {e}")

    async def _radio_loop(self, chat_id: int):
        """Основной цикл радио с проактивной подгрузкой и голосованием."""
        await self._bot.send_message(chat_id, "🎵 Радио запускается...")
        
        while self._is_on and self.error_count < 10:
            try:
                # Проверяем, не пора ли запустить новое голосование
                if not self._vote_in_progress and (self.mode_end_time is None or datetime.now() >= self.mode_end_time):
                    # Запускаем голосование в фоновой задаче, чтобы не прерывать музыку
                    asyncio.create_task(self.start_genre_vote(chat_id))
                    # Сразу устанавливаем следующий "конец режима", чтобы избежать повторного запуска
                    self.mode_end_time = datetime.now() + timedelta(hours=1)
                
                # Если плейлист почти пуст, пополняем его
                if len(self._playlist) < 5:
                    query = await self._get_next_query()
                    await self._fetch_playlist(query)
                
                if not self._playlist:
                    logger.warning("[Радио] Плейлист пуст. Беру паузу.")
                    await asyncio.sleep(self._settings.RETRY_DELAY_S)
                    continue
                
                track_to_play = self._playlist.pop(0)
                if track_to_play.identifier in self._played_ids:
                    continue # Пропускаем, если трек уже играл
                
                self._played_ids.add(track_to_play.identifier)
                if len(self._played_ids) > 500: # Ограничиваем историю
                    self._played_ids.pop()

                logger.info(f"[Радио] Скачиваю: {track_to_play.display_name}")
                result = await self._downloader.download_with_retry(track_to_play.identifier)

                if result.success:
                    self.error_count = 0
                    await self._send_audio(chat_id, result)
                    
                    try:
                        # Ожидаем команду skip или кулдаун
                        await asyncio.wait_for(
                            self._skip_event.wait(), timeout=self._settings.RADIO_COOLDOWN_S
                        )
                        self._skip_event.clear()
                        logger.info("[Радио] Трек пропущен по запросу.")
                    except asyncio.TimeoutError:
                        pass # Просто продолжаем
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
            logger.error("[Радио] Превышено макс. кол-во ошибок. Радио остановлено.")
            await self._bot.send_message(chat_id, "⚠️ Радио остановлено из-за ошибок.")
        
        self._is_on = False
        logger.info(f"⏹️ Радио-цикл завершен для чата {chat_id}.")
