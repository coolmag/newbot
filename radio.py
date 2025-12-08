import asyncio
import logging
import random
from typing import Optional

from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError

from config import Settings
from models import DownloadResult
from downloaders import BaseDownloader

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
        self._playlist: list = []
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
        self._task = asyncio.create_task(self._radio_loop(chat_id))

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

    async def skip(self):
        """Пропускает текущий трек."""
        if self._is_on:
            self._skip_event.set()

    async def _fetch_playlist(self):
        """Запрашивает новый плейлист."""
        genre = random.choice(self._settings.RADIO_GENRES)
        self._current_genre = genre
        self._playlist = await self._downloader.search(genre, limit=20)
        if not self._playlist:
            self.error_count += 1

    async def _send_audio(self, chat_id: int, result: DownloadResult):
        """Отправляет аудиофайл в чат."""
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
                )
        except TelegramError as e:
            logger.error(f"Ошибка Telegram при отправке радио-аудио: {e}")
            raise
        finally:
            # Clean up the downloaded file
            pass

    async def _radio_loop(self, chat_id: int):
        """Основной цикл радио."""
        await self._bot.send_message(chat_id, "🎵 Радио запускается...")
        while self._is_on and self.error_count < 10:
            try:
                if not self._playlist:
                    await self._fetch_playlist()
                    if not self._playlist:
                        await asyncio.sleep(self._settings.RETRY_DELAY_S)
                        continue

                track_to_play = self._playlist.pop(0)
                result = await self._downloader.download_with_retry(track_to_play.display_name)

                if result.success:
                    await self._send_audio(chat_id, result)
                    self.error_count = 0
                    try:
                        await asyncio.wait_for(
                            self._skip_event.wait(), timeout=self._settings.RADIO_COOLDOWN_S
                        )
                        self._skip_event.clear()
                    except asyncio.TimeoutError:
                        pass
                else:
                    self.error_count += 1
                    await asyncio.sleep(3)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка в цикле радио: {e}", exc_info=True)
                self.error_count += 1
                await asyncio.sleep(5)

        if self.error_count >= 10:
            await self._bot.send_message(
                chat_id,
                "⚠️ Радио остановлено из-за слишком большого количества ошибок.",
            )
        self._is_on = False
