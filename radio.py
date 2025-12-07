import asyncio
import random
import os
import time
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
        self.last_error_time = 0
        self.error_count = 0
        self.max_errors = 5

    async def start(self, chat_id: int):
        """Запускает фоновую задачу радио, если она еще не активна."""
        if self._task and not self._task.done():
            logger.warning(f"Попытка запустить радио, когда оно уже работает в чате {chat_id}.")
            return

        self.state.radio.is_on = True
        self.state.radio.skip_event.clear()
        self.error_count = 0
        self._task = asyncio.create_task(self._radio_loop(chat_id))
        logger.info(f"✅ Радио-задача создана и запущена для чата {chat_id}.")

    async def stop(self):
        """Останавливает радио, отменяя фоновую задачу."""
        self.state.radio.is_on = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("⏹️ Радио остановлено.")

    async def skip(self):
        """Пропускает текущий трек в режиме радио."""
        if self.state.radio.is_on:
            self.state.radio.skip_event.set()
            logger.info("⏭️ Получен запрос на пропуск трека.")

    async def stop_for_chat(self, chat_id: int):
        """Останавливает радио для конкретного чата."""
        logger.info(f"⏹️ Останавливаю радио для чата {chat_id}")
        await self.stop()

    async def _send_radio_audio(self, chat_id: int, result: DownloadResult, caption: str):
        """Отправляет аудиофайл в чат для радио и удаляет временные файлы."""
        try:
            if not os.path.exists(result.file_path):
                logger.error(f"Файл радио не найден для отправки: {result.file_path}")
                return

            file_size_mb = os.path.getsize(result.file_path) / (1024 * 1024)
            if file_size_mb > 49.5:
                logger.error(f"Файл слишком большой для отправки: {file_size_mb:.1f} МБ")
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
            raise
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
        
        # Выбираем случайный жанр для плейлиста
        genre = random.choice(settings.RADIO_GENRES)
        self.state.radio.current_genre = genre
        
        # Используем шаблоны поиска для жанра
        playlists = []
        for pattern in settings.RADIO_SEARCH_PATTERNS:
            if len(playlists) >= 15:
                break
                
            search_query = pattern.format(genre=genre)
            try:
                found_tracks = await self.downloader.search(search_query, limit=10)
                if found_tracks:
                    playlists.extend(found_tracks)
            except Exception as e:
                logger.warning(f"[Радио] Ошибка поиска по шаблону '{search_query}': {e}")
        
        if playlists:
            # Убираем дубликаты по названию
            seen_titles = set()
            unique_playlist = []
            for track in playlists:
                if track.display_name not in seen_titles:
                    seen_titles.add(track.display_name)
                    unique_playlist.append(track)
            
            random.shuffle(unique_playlist)
            self.state.radio.playlist = unique_playlist[:20]  # Ограничиваем размер плейлиста
            logger.info(f"[Радио] Плейлист обновлен. {len(self.state.radio.playlist)} треков в жанре '{genre}'.")
        else:
            logger.warning(f"[Радио] Не удалось получить плейлист для жанра '{genre}'.")
            self.state.radio.playlist = []

    async def _radio_loop(self, chat_id: int):
        """
        Основной цикл радио с обработкой ошибок.
        """
        logger.info(f"▶️ Радио-цикл запущен для чата {chat_id}.")
        
        status_message = None
        
        while self.state.radio.is_on and self.error_count < self.max_errors:
            try:
                # 1. Проверяем и при необходимости обновляем плейлист
                if not self.state.radio.playlist or len(self.state.radio.playlist) < 5:
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
                                await status_message.edit_text("😔 Не удалось обновить плейлист. Повторю через 10 секунд.")
                        except TelegramError:
                            pass
                        await asyncio.sleep(10)
                        continue
                    
                    if status_message:
                        try:
                            await status_message.delete()
                        except:
                            pass
                        status_message = None

                # 2. Берем следующий трек из плейлиста
                track_to_play = self.state.radio.playlist.pop(0)
                
                # 3. Скачиваем трек
                query = f"{track_to_play.artist} - {track_to_play.title}"
                logger.info(f"[Радио] Скачиваю: {track_to_play.display_name}")
                
                result = await self.downloader.download_with_retry(query)

                if result and result.success:
                    # 4. Отправляем трек
                    caption = f"🎶 *Радио | {self.state.radio.current_genre}*\n\n`{track_to_play.display_name}`"
                    await self._send_radio_audio(chat_id, result, caption)
                    
                    # 5. Ожидаем кулдаун или событие пропуска
                    try:
                        await asyncio.wait_for(
                            self.state.radio.skip_event.wait(),
                            timeout=settings.RADIO_COOLDOWN_S
                        )
                        self.state.radio.skip_event.clear()
                        logger.info("[Радио] Трек пропущен по запросу.")
                    except asyncio.TimeoutError:
                        pass  # Нормальное завершение
                    
                    # Сбрасываем счетчик ошибок после успешного трека
                    self.error_count = 0
                    
                else:
                    error_msg = result.error if result else "Неизвестная ошибка"
                    logger.warning(f"[Радио] Не удалось скачать трек: {track_to_play.display_name}. Ошибка: {error_msg}")
                    self.error_count += 1
                    
                    if status_message:
                        try:
                            await status_message.edit_text(f"⚠️ Ошибка скачивания. Пропускаю трек...")
                            await asyncio.sleep(2)
                            await status_message.delete()
                            status_message = None
                        except:
                            pass
                    
                    if self.error_count >= 3:
                        logger.warning(f"[Радио] Много ошибок ({self.error_count}). Очищаю плейлист.")
                        self.state.radio.playlist = []

            except asyncio.CancelledError:
                logger.info("[Радио] Цикл отменен.")
                break
            except TelegramError as e:
                if "Message to edit not found" in str(e):
                    status_message = None
                elif "Forbidden" in str(e):
                    logger.error(f"[Радио] Бот заблокирован в чате {chat_id}. Останавливаю радио.")
                    await self.stop()
                    break
                else:
                    logger.error(f"[Радио] Ошибка Telegram: {e}")
                    self.error_count += 1
                    await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"[Радио] Непредвиденная ошибка: {e}", exc_info=True)
                self.error_count += 1
                await asyncio.sleep(5)
            finally:
                if status_message:
                    try:
                        await status_message.delete()
                    except:
                        pass
                    status_message = None
        
        # Если превышено количество ошибок
        if self.error_count >= self.max_errors:
            logger.error(f"[Радио] Превышено максимальное количество ошибок ({self.error_count}). Останавливаю радио.")
            try:
                await self.bot.send_message(
                    chat_id,
                    "⚠️ Радио остановлено из-за слишком большого количества ошибок. "
                    "Используйте команду /admin чтобы перезапустить."
                )
            except:
                pass
        
        logger.info(f"⏹️ Радио-цикл завершен для чата {chat_id}.")
        self.state.radio.is_on = False
        self.state.radio.current_genre = None