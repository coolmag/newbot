
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
from base import BaseDownloader, DownloadResult # Изменяем импорт


class RadioService:
    """
    Сервис для управления фоновым воспроизведением музыки ("радио").
    """
    def __init__(self, state: BotState, bot: Bot, downloader: BaseDownloader): # Изменяем тип
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


    async def _fetch_playlist(self):
        """
        Запрашивает новый плейлист с треками и сохраняет его в состоянии.
        """
        logger.info("[Радио] Обновление плейлиста...")
        
        genres_to_try = list(settings.RADIO_GENRES)
        random.shuffle(genres_to_try)
        
        for genre in genres_to_try:
            self.state.radio.current_genre = genre
            
            playlist = await self.downloader.search(genre, limit=50)
            
            if playlist and len(playlist) >= 5:
                filtered_playlist = [track for track in playlist if 60 <= track.duration <= 1200]
                
                if filtered_playlist:
                    random.shuffle(filtered_playlist)
                    self.state.radio.playlist = filtered_playlist
                    logger.info(f"[Радио] Плейлист обновлен. {len(filtered_playlist)} треков в жанре '{genre}'.")
                    return
            
            logger.warning(f"[Радио] Не удалось получить плейлист для жанра '{genre}'. Пробую следующий...")
            await asyncio.sleep(1)
        
        logger.warning("[Радио] Все жанры вернули пустые результаты. Использую резервный запрос.")
        self.state.radio.current_genre = "music"
        playlist = await self.downloader.search("music collection:opensource_audio", limit=30)
        
        if playlist:
            random.shuffle(playlist)
            self.state.radio.playlist = playlist
            logger.info(f"[Радио] Использую резервный плейлист. {len(playlist)} треков.")
        else:
            logger.error("[Радио] Не удалось получить ни один плейлист.")
            self.state.radio.playlist = []

    async def _radio_loop(self, chat_id: int):
        """
        Основной цикл радио: берет трек из плейлиста, скачивает, отправляет
        и ждет перед повторением.
        """
        logger.info(f"▶️ Радио-цикл запущен для чата {chat_id}.")
        await asyncio.sleep(2)

        status_message = None
        while self.state.radio.is_on:
            try:
                # 1. Проверяем и при необходимости обновляем плейлист
                if not self.state.radio.playlist:
                    try:
                        if status_message:
                            await status_message.edit_text("🎵 Обновляю плейлист радио...")
                        else:
                            status_message = await self.bot.send_message(chat_id, "🎵 Обновляю плейлист радио...")
                    except TelegramError:
                        status_message = await self.bot.send_message(chat_id, "🎵 Обновляю плейлист радио...")
                    
                    await self._fetch_playlist()
                    
                    if not self.state.radio.playlist:
                        try:
                            if status_message:
                                await status_message.edit_text("😔 Не удалось обновить плейлист. Повторю через 1 минуту.")
                        except TelegramError:
                            pass
                        await asyncio.sleep(60)
                        continue

                # 2. Берем следующий трек из плейлиста
                track_to_play = self.state.radio.playlist.pop(0)
                
                try:
                    if status_message:
                        await status_message.edit_text(f"🎵 Скачиваю: {track_to_play.display_name}...")
                except TelegramError:
                    status_message = await self.bot.send_message(chat_id, f"🎵 Скачиваю: {track_to_play.display_name}...")
                
                # 3. Скачиваем трек
                if settings.RADIO_SOURCE == "internet_archive" and track_to_play.identifier:
                    query = track_to_play.identifier
                else:
                    query = f"{track_to_play.artist} - {track_to_play.title}"
                result = await self.downloader.download_with_retry(query)

                if result and result.success:
                    try:
                        if status_message:
                            await status_message.edit_text("📤 Отправляю трек...")
                    except TelegramError:
                        pass
                    
                    caption = f"🎶 *Радио | {self.state.radio.current_genre.capitalize()}*\n\n`{track_to_play.display_name}`"
                    await self._send_radio_audio(chat_id, result, caption)
                    
                    if status_message:
                        await status_message.delete()
                        status_message = None
                    
                    # 4. Ожидаем кулдаун или событие пропуска
                    try:
                        await asyncio.wait_for(
                            self.state.radio.skip_event.wait(),
                            timeout=settings.RADIO_COOLDOWN_S
                        )
                    except asyncio.TimeoutError:
                        pass # Нормальное завершение
                    
                    if self.state.radio.skip_event.is_set():
                        logger.info("[Радио] Трек пропущен. Запускаю следующий.")
                        self.state.radio.skip_event.clear()
                else:
                    logger.warning(f"Не удалось скачать трек: {track_to_play.display_name}. Пропускаю.")
                    try:
                        if status_message:
                            await status_message.edit_text(f"⚠️ Не удалось скачать трек. Пропускаю...")
                    except TelegramError:
                        pass

            except asyncio.CancelledError:
                logger.info("Радио-цикл отменен.")
                break
            except TelegramError as e:
                if "Message to edit not found" in str(e):
                    logger.warning("Сообщение для редактирования не найдено, возможно, оно было удалено.")
                    status_message = None # Сбрасываем, чтобы отправить новое
                else:
                    logger.error(f"Ошибка Telegram в радио-цикле: {e}. Радио остановлено.")
                    await self.stop()
            except Exception as e:
                logger.critical(f"Критическая ошибка в радио-цикле: {e}", exc_info=True)
                await asyncio.sleep(60)
            finally:
                if status_message:
                    try:
                        await status_message.delete()
                    except TelegramError:
                        pass
        
        logger.info(f"⏹️ Радио-цикл завершен для чата {chat_id}.")
        self.state.radio.is_on = False
        self.state.radio.current_genre = None

