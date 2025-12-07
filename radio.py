
import asyncio
import random
import os
from typing import Optional

from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError

from logger import logger
from config import settings
from states import BotState
from base import BaseDownloader, DownloadResult


class RadioService:
    """
    Сервис для управления фоновым воспроизведением музыки ("радио").
    """
    def __init__(self, state: BotState, bot: Bot, downloader: BaseDownloader):
        self.state = state
        self.bot = bot
        self.downloader = downloader
        self._task: Optional[asyncio.Task] = None

    async def start(self, chat_id: int):
        """Запускает фоновую задачу радио, если она еще не активна."""
        if self._task and not self._task.done():
            logger.warning(f"Попытка запустить радио, когда оно уже работает в чате {chat_id}.")
            return

        self.state.radio.is_on = True
        self.state.radio.skip_event.clear()
        self._task = asyncio.create_task(self._radio_loop(chat_id))
        logger.info(f"✅ Радио-задача создана и запущена для чата {chat_id}.")

    async def stop(self):
        """Останавливает радио, отменяя фоновую задачу."""
        self.state.radio.is_on = False
        if self._task:
            self._task.cancel()
            self._task = None
        logger.info("⏹️ Радио остановлено.")

    async def skip(self):
        """Пропускает текущий трек в режиме радио."""
        if self.state.radio.is_on:
            self.state.radio.skip_event.set()
            logger.info("⏭️ Получен запрос на пропуск трека.")

    async def _send_radio_audio(self, chat_id: int, result: DownloadResult, caption: str):
        """Отправляет аудиофайл в чат для радио и удаляет временные файлы."""
        try:
            if not os.path.exists(result.file_path):
                 logger.error(f"Файл радио не найден для отправки: {result.file_path}")
                 return

            with open(result.file_path, 'rb') as audio_file:
                await self.bot.send_audio(
                    chat_id=chat_id,
                    audio=audio_file,
                    title=result.track_info.title,
                    performer=result.track_info.artist,
                    duration=result.track_info.duration,
                    caption=caption,
                    parse_mode=ParseMode.MARKDOWN
                )
        except TelegramError as e:
            logger.error(f"Ошибка Telegram при отправке радио-аудио в чат {chat_id}: {e}")
            raise # Пробрасываем ошибку выше для обработки в _radio_loop
        except Exception as e:
            logger.error(f"Непредвиденная ошибка при отправке радио-аудио {chat_id}: {e}", exc_info=True)
            raise
        finally:
            if result.file_path and os.path.exists(result.file_path):
                try:
                    os.remove(result.file_path)
                except OSError as e:
                    logger.error(f"Не удалось удалить радио-файл {result.file_path}: {e}")


    async def _radio_loop(self, chat_id: int):
        """
        Основной цикл радио: выбирает жанр, скачивает трек, отправляет в чат
        и ждет перед повторением.
        """
        logger.info(f"▶️ Радио-цикл запущен для чата {chat_id}.")
        await asyncio.sleep(2)  # Небольшая задержка перед первым треком

        while self.state.radio.is_on:
            result: Optional[DownloadResult] = None
            try:
                # 1. Выбираем случайный жанр и создаем более точный запрос
                genre = random.choice(settings.RADIO_GENRES)
                self.state.radio.current_genre = genre
                
                # Добавляем уточнения, чтобы избежать длинных миксов
                clarifications = ["audio", "topic", "single track", "official audio"]
                search_query = f"{genre} {random.choice(clarifications)}"
                
                logger.info(f"[Радио] Выбран жанр: '{genre}', поисковый запрос: '{search_query}' для чата {chat_id}.")
                
                # 2. Скачиваем трек
                result = await self.downloader.download_with_retry(search_query)

                if result and result.success:
                    # 3. Отправляем трек в чат через специализированный метод
                    track = result.track_info
                    caption = f"🎶 *Радио | {genre.capitalize()}*\n\n`{track.display_name}`"
                    await self._send_radio_audio(chat_id, result, caption)
                    
                    # 4. Ожидаем кулдаун или событие пропуска
                    try:
                        await asyncio.wait_for(
                            self.state.radio.skip_event.wait(),
                            timeout=settings.RADIO_COOLDOWN_S
                        )
                    except asyncio.TimeoutError:
                        # Нормальное завершение ожидания, просто продолжаем
                        pass
                    
                    if self.state.radio.skip_event.is_set():
                        logger.info("[Радио] Трек пропущен. Запускаю следующий.")
                        self.state.radio.skip_event.clear()
                else:
                    logger.warning(f"[Радио] Не удалось скачать трек для жанра '{genre}'. Пауза 30с.")
                    await asyncio.sleep(30)

            except asyncio.CancelledError:
                logger.info("Радио-цикл отменен.")
                break
            except TelegramError as e:
                logger.error(f"Ошибка Telegram в радио-цикле: {e}. Радио остановлено.")
                await self.stop() # Останавливаем радио при ошибке отправки
            except Exception as e:
                logger.critical(f"Критическая ошибка в радио-цикле: {e}", exc_info=True)
                await asyncio.sleep(60) # Делаем большую паузу в случае серьезного сбоя
            finally:
                # 5. Удаляем скачанный файл (уже сделано в _send_radio_audio)
                pass # Тут не нужно, так как _send_radio_audio уже удалил файл
        
        logger.info(f"⏹️ Радио-цикл завершен для чата {chat_id}.")
        self.state.radio.is_on = False
        self.state.radio.current_genre = None

