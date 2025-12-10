import asyncio
import logging
import random
import os
from datetime import datetime, timedelta
from typing import Optional, Set, Dict, Tuple, List

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
        self._status_message_info: Optional[Tuple[int, int]] = None
        
        # --- Состояние плейлиста ---
        self._playlist: list[TrackInfo] = []
        self._played_ids: Set[str] = set()

        # --- Состояние режимов (голосование/артист) ---
        self.artist_mode: Optional[str] = None
        self.winning_genre: str = "rock"  # Начинаем с рока по умолчанию
        self.current_mood: Optional[str] = None # Новое поле для текущего настроения
        self.mode_end_time: Optional[datetime] = None

        # --- Состояние голосования ---
        self._vote_in_progress: bool = False
        self._votes: Dict[str, Set[int]] = {} # {genre: {user_id_1, user_id_2}}
        self._current_vote_genres: List[str] = []
        # ID сообщения, в котором идет голосование (отдельно от статуса)
        self.current_vote_message_info: Optional[Tuple[int, int]] = None 
        self._vote_task: Optional[asyncio.Task] = None

    @property
    def is_on(self) -> bool:
        return self._is_on

    @property
    def is_vote_in_progress(self) -> bool:
        return self._vote_in_progress

    # --- Управление радио ---

    async def start(self, chat_id: int):
        """Запускает фоновую задачу радио и создает/закрепляет статус-сообщение."""
        if self._task and not self._task.done():
            return

        # Отправляем и закрепляем статус-сообщение
        try:
            status_message = await self._bot.send_message(
                chat_id, "🎵 Радио запускается... Ожидание первого трека..."
            )
            await self._bot.pin_chat_message(
                chat_id, status_message.message_id, disable_notification=True
            )
            self._status_message_info = (chat_id, status_message.message_id)
        except TelegramError as e:
            logger.error(f"Не удалось отправить или закрепить статус-сообщение: {e}")
            return

        self._is_on = True
        self._skip_event.clear()
        self.error_count = 0
        self._playlist = []
        self._played_ids = set()

        if self.current_mood or self.winning_genre != "rock" or self.artist_mode:
            self.mode_end_time = datetime.now() + timedelta(hours=1)
        else:
            self.mode_end_time = None

        self._task = asyncio.create_task(self._radio_loop(chat_id))
        logger.info(f"✅ Радио-задача создана и запущена для чата {chat_id}.")

    async def stop(self):
        """Останавливает радио и открепляет статус-сообщение."""
        self._is_on = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        
        if self._vote_task:
            self._vote_task.cancel()
            self._vote_task = None
        
        if self.current_vote_message_info:
            try:
                await self._bot.delete_message(self.current_vote_message_info[0], self.current_vote_message_info[1])
            except TelegramError:
                pass
            self.current_vote_message_info = None

        if self._status_message_info:
            chat_id, message_id = self._status_message_info
            try:
                await self._bot.unpin_chat_message(chat_id, message_id)
                await self._update_status_message("⏹️ Радио остановлено.")
            except TelegramError as e:
                logger.warning(f"Не удалось открепить или обновить статус-сообщение: {e}")
        
        self._status_message_info = None
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
        self.current_mood = None
        self.mode_end_time = datetime.now() + timedelta(hours=1)
        self._playlist = []

        if self._vote_task:
            self._vote_task.cancel()
            self._vote_task = None

        if self.current_vote_message_info:
            try:
                chat_id_vote, msg_id_vote = self.current_vote_message_info
                await self._bot.edit_message_text(
                    chat_id=chat_id_vote,
                    message_id=msg_id_vote,
                    text=f"🗳️ Голосование отменено.\nАдмин установил жанр: **{genre.capitalize()}**",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=None
                )
            except TelegramError as e:
                logger.warning(f"Не удалось изменить сообщение о голосовании: {e}")
            self.current_vote_message_info = None

        self._vote_in_progress = False
        
        await self._bot.send_message(
            chat_id,
            f"✅ Жанр принудительно изменен на **{genre.capitalize()}**. Этот жанр будет играть следующий час.",
            parse_mode=ParseMode.MARKDOWN,
        )
        await self._update_status_message(f"🎶 Режим Радио: **{genre.capitalize()}**")
        logger.info(f"[Режим] Админ установил жанр: {genre} на 1 час.")
        await self.skip()

    async def set_artist_mode(self, artist: str, chat_id: int):
        self.artist_mode = artist
        self.winning_genre = None
        self.current_mood = None
        self.mode_end_time = datetime.now() + timedelta(hours=1)
        self._playlist = []
        logger.info(f"[Режим] Включен режим артиста: {artist} на 1 час.")
        
        await self._update_status_message(f"🎤 Режим Артиста: **{artist}**")
        await self.skip()

    async def set_mood(self, mood: str, chat_id: int):
        if mood not in self._settings.RADIO_MOODS:
            logger.warning(f"[Режим] Попытка установить несуществующее настроение: {mood}")
            return
        
        self.current_mood = mood
        self.artist_mode = None
        self.winning_genre = None
        self.mode_end_time = datetime.now() + timedelta(hours=1)
        self._playlist = []
        
        await self._bot.send_message(
            chat_id,
            f"✅ Установлено настроение: **{mood.capitalize()}**. "
            f"Следующий час бот будет подбирать музыку под это настроение!",
            parse_mode=ParseMode.MARKDOWN,
        )
        await self._update_status_message(f"😊 Режим Настроения: **{mood.capitalize()}**")
        logger.info(f"[Режим] Установлено настроение: {mood} на 1 час.")
        await self.skip()


    # --- Логика голосования ---
    async def _run_vote_lifecycle(self, chat_id: int):
        """Полный жизненный цикл голосования: отправка, ожидание, завершение."""
        if self._vote_in_progress:
            return

        logger.info("[Голосование] Начинается голосование за жанр.")
        self._vote_in_progress = True
        self._votes = {}
        self.artist_mode = None
        self.current_mood = None

        all_genres = self._settings.RADIO_GENRES
        sample_size = min(len(all_genres), 16)
        self._current_vote_genres = sorted(random.sample(all_genres, sample_size))

        try:
            vote_message = await self._bot.send_message(
                chat_id=chat_id,
                text="📢 **Началось голосование за жанр!**\n\nВыберите, что будет играть следующий час. Голосование продлится 5 минут.",
                reply_markup=get_genre_voting_keyboard(self._current_vote_genres, self._votes),
                parse_mode=ParseMode.MARKDOWN,
            )
            self.current_vote_message_info = (chat_id, vote_message.message_id)
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение для голосования: {e}")
            self._vote_in_progress = False
            return

        await asyncio.sleep(300)  # 5 минут на голосование
        if self._vote_in_progress:
            await self.end_genre_vote(chat_id)

    def start_genre_vote(self, chat_id: int):
        """Запускает задачу жизненного цикла голосования."""
        if self._vote_task and not self._vote_task.done():
            logger.warning("[Голосование] Попытка запустить голосование, когда оно уже идет.")
            return
        self._vote_task = asyncio.create_task(self._run_vote_lifecycle(chat_id))


    def register_vote(self, genre: str, user_id: int) -> bool:
        if not self._vote_in_progress:
            return False
        
        for g in self._votes:
            self._votes[g].discard(user_id)
            
        if genre not in self._votes:
            self._votes[genre] = set()
        self._votes[genre].add(user_id)
        
        logger.debug(f"[Голосование] Пользователь {user_id} проголосовал за {genre}.")
        return True

    async def update_vote_keyboard(self):
        if not self._vote_in_progress or not self.current_vote_message_info:
            return
        
        chat_id, message_id = self.current_vote_message_info
        try:
            await self._bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=get_genre_voting_keyboard(self._current_vote_genres, self._votes)
            )
        except TelegramError as e:
            if "not modified" not in str(e):
                logger.warning(f"Не удалось обновить клавиатуру голосования: {e}")


    async def end_genre_vote(self, chat_id: int):
        if not self.current_vote_message_info:
            return

        logger.info("[Голосование] Голосование завершено. Подвожу итоги.")
        
        if self._votes:
            winner = max(self._votes, key=lambda g: len(self._votes[g]))
            self.winning_genre = winner
        else:
            self.winning_genre = random.choice(self._current_vote_genres)
        
        self.mode_end_time = datetime.now() + timedelta(hours=1)
        self._playlist = []
        
        announcement = f"🎉 **Голосование завершено!**\n\nСледующий час играет: **{self.winning_genre.capitalize()}**"
        logger.info(f"[Режим] По результатам голосования установлен жанр: {self.winning_genre}")

        chat_id_vote, msg_id_vote = self.current_vote_message_info
        try:
            await self._bot.edit_message_text(
                chat_id=chat_id_vote, message_id=msg_id_vote,
                text=announcement, parse_mode=ParseMode.MARKDOWN, reply_markup=None
            )
        except TelegramError as e:
            logger.warning(f"Не удалось обновить сообщение о голосовании результатами: {e}")

        # Сбрасываем состояние голосования
        self.current_vote_message_info = None
        self._vote_in_progress = False
        self._vote_task = None

        await self._update_status_message(f"🎶 Режим Радио: **{self.winning_genre.capitalize()}**")
        await self.skip()

    # --- Внутренний цикл радио ---
    
    async def _update_status_message(self, text: str, reply_markup: InlineKeyboardMarkup = None):
        if not self._status_message_info:
            return
        
        chat_id, message_id = self._status_message_info
        try:
            await self._bot.edit_message_text(
                chat_id=chat_id, message_id=message_id,
                text=text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup
            )
        except TelegramError as e:
            if "not modified" not in str(e):
                logger.warning(f"Не удалось обновить статус-сообщение: {e}")

    async def _get_next_query(self) -> str:
        if self.artist_mode:
            return self.artist_mode
        
        if self.current_mood:
            genres_for_mood = self._settings.RADIO_MOODS.get(self.current_mood, ["music"])
            selected_genre = random.choice(genres_for_mood)
        else:
            selected_genre = self.winning_genre or "rock"

        query_templates = [
            f"{selected_genre} official audio",
            f"best of {selected_genre}",
            f"{selected_genre} music",
        ]
        return random.choice(query_templates)

    async def _fetch_playlist(self, query: str):
        logger.info(f"[Радио] Ищу треки по запросу: '{query}'")
        
        new_tracks = await self._downloader.search(
            query, 
            limit=100,
            min_duration=self._settings.RADIO_MIN_DURATION_S,
            max_duration=self._settings.RADIO_MAX_DURATION_S,
            min_views=self._settings.RADIO_MIN_VIEWS,
            min_likes=self._settings.RADIO_MIN_LIKES,
        )
        
        if not new_tracks and (self._settings.RADIO_MIN_VIEWS or self._settings.RADIO_MIN_LIKES):
            logger.warning(f"[Радио] Поиск '{query}' с фильтрами не дал результатов. Пробую без них.")
            new_tracks = await self._downloader.search(
                query, limit=100, 
                min_duration=self._settings.RADIO_MIN_DURATION_S,
                max_duration=self._settings.RADIO_MAX_DURATION_S
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
        if not result.file_path or not os.path.exists(result.file_path):
            logger.error(f"[Радио] Файл для отправки не найден: {result.file_path}")
            return
        
        try:
            with open(result.file_path, "rb") as audio_file:
                await self._bot.send_audio(
                    chat_id=chat_id, audio=audio_file, title=result.track_info.title,
                    performer=result.track_info.artist, duration=result.track_info.duration,
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
        while self._is_on and self.error_count < 10:
            try:
                if not self._vote_in_progress and (self.mode_end_time is None or datetime.now() >= self.mode_end_time):
                    self.start_genre_vote(chat_id)
                    self.mode_end_time = datetime.now() + timedelta(hours=1)
                
                if len(self._playlist) < 5:
                    query = await self._get_next_query()
                    await self._fetch_playlist(query)
                
                if not self._playlist:
                    await self._update_status_message("📻 Плейлист пуст, ищу новую музыку...")
                    await asyncio.sleep(self._settings.RETRY_DELAY_S)
                    continue
                
                track_to_play_index = random.randint(0, len(self._playlist) - 1)
                track_to_play = self._playlist.pop(track_to_play_index)
                if track_to_play.identifier in self._played_ids:
                    continue 
                
                self._played_ids.add(track_to_play.identifier)
                if len(self._played_ids) > 500:
                    self._played_ids.pop()

                await self._update_status_message(f"⏳ Скачиваю: `{track_to_play.display_name}`")
                result = await self._downloader.download_with_retry(track_to_play.identifier)

                if result.success:
                    self.error_count = 0
                    
                    mode_text = ""
                    if self.artist_mode:
                        mode_text = f"🎤 Артист: {self.artist_mode}"
                    elif self.current_mood:
                        mode_text = f"😊 Настроение: {self.current_mood.capitalize()}"
                    else:
                        genre_text = self.winning_genre or "rock"
                        mode_text = f"🎶 Жанр: {genre_text.capitalize()}"

                    status_text = (
                        f"📻 **Сейчас в эфире | {mode_text}**\n\n"
                        f"`{result.track_info.display_name}`"
                    )
                    await self._update_status_message(status_text)
                    await self._send_audio(chat_id, result)
                    
                    try:
                        await asyncio.wait_for(self._skip_event.wait(), timeout=90)
                        self._skip_event.clear()
                        logger.info("[Радио] Трек пропущен или его время истекло.")
                    except asyncio.TimeoutError:
                        logger.info("[Радио] 90 секунд истекли, переключаюсь на следующий трек.")
                else:
                    logger.warning(f"[Радио] Ошибка скачивания: {result.error}")
                    self.error_count += 1
                    await self._update_status_message(f"⚠️ Ошибка скачивания, пробую следующий трек...")
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
            await self._update_status_message("⚠️ Радио было остановлено из-за большого количества ошибок.")
        
        elif not self._is_on:
             await self._update_status_message("⏹️ Радио остановлено.")

        if self._status_message_info:
            try:
                await self._bot.unpin_chat_message(self._status_message_info[0])
            except TelegramError as e:
                logger.warning(f"Не удалось открепить сообщение в конце сессии: {e}")
        
        self._is_on = False
        self._status_message_info = None
        logger.info(f"⏹️ Радио-цикл завершен для чата {chat_id}.")
