
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
        
        # Пробуем разные жанры, пока не найдем с треками
        genres_to_try = list(settings.RADIO_GENRES)
        random.shuffle(genres_to_try)
        
        for genre in genres_to_try:
            self.state.radio.current_genre = genre
            
            # Для YouTube добавляем ключевые слова для поиска отдельных треков
            search_query = f"{genre} music"
            playlist = await self.downloader.search(search_query, limit=50)
            
            if playlist and len(playlist) >= 5:
                # Фильтруем по длительности
                filtered_playlist = [
                    track for track in playlist 
                    if 120 <= track.duration <= 600  # 2-10 минут
                ]
                
                if filtered_playlist:
                    random.shuffle(filtered_playlist)
                    self.state.radio.playlist = filtered_playlist
                    logger.info(f"[Радио] Плейлист обновлен. {len(filtered_playlist)} треков в жанре '{genre}'.")
                    return
                    
            logger.warning(f"[Радио] Не удалось получить плейлист для жанра '{genre}'. Пробую следующий...")
        
        # Если ничего не найдено, используем общий поиск
        logger.warning("[Радио] Все жанры вернули пустые результаты. Использую общий поиск.")
        self.state.radio.current_genre = "music"
        playlist = await self.downloader.search("music", limit=30)
        
        if playlist:
            random.shuffle(playlist)
            self.state.radio.playlist = playlist
            logger.info(f"[Радио] Использую резервный плейлист. {len(playlist)} треков.")
        else:
            logger.error("[Радио] Не удалось получить ни один плейлист.")
            self.state.radio.playlist = []

    async def _radio_loop(self, chat_id: int):
        """Основной цикл радио с предварительной загрузкой."""
        logger.info(f"▶️ Оптимизированный радио-цикл запущен для чата {chat_id}.")
        
        async def preload_next_track():
            if not self.state.radio.playlist:
                await self._fetch_playlist()
            if self.state.radio.playlist:
                next_track = self.state.radio.playlist[0]
                query = f"{next_track.artist} - {next_track.title}" if next_track.artist != "Unknown Artist" else next_track.title
                return await self.downloader.download_with_retry(query)
            return None
        
        while self.state.radio.is_on:
            try:
                if not self.state.radio.next_track_result:
                    status_msg = await self.bot.send_message(chat_id, "⏳ Загружаю первый трек...")
                    self.state.radio.next_track_result = await preload_next_track()
                    if status_msg:
                        try:
                            await status_msg.delete()
                        except:
                            pass
                
                if self.state.radio.next_track_result and self.state.radio.next_track_result.success:
                    result = self.state.radio.next_track_result
                    
                    if len(self.state.radio.playlist) > 1:
                        self.state.radio.next_track_future = asyncio.create_task(preload_next_track())
                    
                    if self.state.radio.playlist:
                        current_track = self.state.radio.playlist.pop(0)
                        caption = f"🎶 *Радио | {self.state.radio.current_genre}*\n\n`{current_track.display_name}`"
                        await self._send_radio_audio(chat_id, result, caption)
                    
                    if self.state.radio.next_track_future:
                        self.state.radio.next_track_result = await self.state.radio.next_track_future
                        self.state.radio.next_track_future = None
                    else:
                        self.state.radio.next_track_result = await preload_next_track()
                    
                    try:
                        await asyncio.wait_for(
                            self.state.radio.skip_event.wait(),
                            timeout=settings.RADIO_COOLDOWN_S
                        )
                        self.state.radio.skip_event.clear()
                    except asyncio.TimeoutError:
                        continue
                        
                else:
                    logger.error("Не удалось загрузить трек для радио.")
                    await asyncio.sleep(5)
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка в радио-цикле: {e}")
                await asyncio.sleep(5)

