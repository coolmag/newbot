import asyncio
import os
import sys
import time

from telegram import Update, Message
from telegram.ext import Application, ContextTypes, CommandHandler, CallbackQueryHandler, ChatMemberHandler
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.error import BadRequest, Forbidden

from config import settings
from keyboards import get_main_menu_keyboard, get_admin_panel_keyboard
from states import BotState
from youtube import YouTubeDownloader
from internet_archive_downloader import InternetArchiveDownloader # Добавляем импорт
from base import DownloadResult
from radio import RadioService
from logger import logger

def is_admin(user_id: int) -> bool:
    """Проверяет, является ли пользователь администратором."""
    return user_id in settings.ADMIN_IDS

def validate_query(query: str, command: str) -> tuple[bool, str]:
    """Валидирует поисковый запрос."""
    if not query:
        return False, f"⚠️ Укажите название.\nПример: `/{command} Queen - Bohemian Rhapsody`"
    
    clean_query = query.strip()
    if len(clean_query) < 2:
        return False, "⚠️ Запрос слишком короткий (минимум 2 символа)."
    
    if len(clean_query) > settings.MAX_QUERY_LENGTH:
        return False, f"⚠️ Запрос слишком длинный (макс. {settings.MAX_QUERY_LENGTH} символов)."
        
    return True, clean_query


class BotHandlers:
    """
    Класс, инкапсулирующий все обработчики команд и колбэков бота.
    """
    def __init__(self, app: Application):
        self.app = app
        self.state = BotState()
        self.youtube = YouTubeDownloader()
        self.internet_archive = InternetArchiveDownloader()
        
        # Выбираем загрузчик для радио
        if settings.RADIO_SOURCE.lower() == "internet_archive":
            radio_downloader = self.internet_archive
            logger.info("✅ Для радио используется Internet Archive.")
        else:
            radio_downloader = self.youtube
            logger.info("✅ Для радио используется YouTube.")
            
        self.radio = RadioService(self.state, app.bot, radio_downloader)

    async def register(self):
        """Регистрирует все обработчики в приложении."""
        from telegram.ext import MessageHandler, filters
        
        handlers = [
            CommandHandler(["start", "help"], self.show_help),
            CommandHandler("menu", self.show_menu),
            CommandHandler(["play", "p"], self.handle_play),
            CommandHandler("admin", self.show_admin_panel),
            CommandHandler(["status", "stat"], self.handle_status),
            CommandHandler("radio_test", self.radio_test),
            CallbackQueryHandler(self.handle_callback),
            ChatMemberHandler(self.handle_chat_member, ChatMemberHandler.MY_CHAT_MEMBER),
            MessageHandler(filters.COMMAND, self.handle_unknown_command),
        ]
        for handler in handlers:
            self.app.add_handler(handler)
        
        logger.info("✅ Обработчики команд зарегистрированы.")

    async def cleanup(self):
        """Очищает ресурсы при завершении работы бота."""
        await self.radio.stop()
        logger.info("✅ Радио-сервис остановлен, ресурсы очищены.")

    # --- Обработчики команд ---

    async def show_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        logger.info(f"Команда /start или /help от {user.full_name} ({user.id})")
        
        help_text = (
            "🎵 **Добро пожаловать в Groove AI!**\n\n"
            "Я ваш персональный музыкальный ассистент. Вот что я умею:\n\n"
            "**Основные команды:**\n"
            "🎶 `/play` (`/p`) - Найти и скачать трек.\n\n"
            "**Меню и статус:**\n"
            "🎛️ `/menu` - Показать главное меню.\n"
            "📊 `/status` (`/stat`) - Узнать текущий статус.\n\n"
        )
        if is_admin(user.id):
            help_text += (
                "**👑 Для администраторов:**\n"
                "🕹️ `/admin` - Открыть панель управления радио.\n"
            )
        help_text += "\nПросто отправьте команду, и я начну работу!"

        await update.message.reply_text(
            help_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_main_menu_keyboard(is_admin(user.id))
        )

    async def show_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        logger.info(f"Команда /menu от {user_id}")
        
        status_text = await self._get_status_text()
        await update.message.reply_text(
            status_text,
            reply_markup=get_main_menu_keyboard(is_admin(user_id)),
            parse_mode=ParseMode.MARKDOWN,
        )

    async def show_admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not is_admin(user_id):
            await update.message.reply_text("⛔ Эта команда доступна только администраторам.")
            return

        logger.info(f"Команда /admin от {user_id}")
        status_text = await self._get_status_text()
        
        await update.message.reply_text(
            f"👑 **Админ-панель**\n\n{status_text}",
            reply_markup=get_admin_panel_keyboard(self.state.radio.is_on),
            parse_mode=ParseMode.MARKDOWN,
        )

    async def handle_play(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        is_valid, query = validate_query(" ".join(context.args), "play")
        if not is_valid:
            await update.message.reply_text(query, parse_mode=ParseMode.MARKDOWN)
            return

        search_msg = await update.message.reply_text(f"🔍 Ищу трек: `{query}`...", parse_mode=ParseMode.MARKDOWN)
        result = await self.youtube.download_with_retry(query)

        if result.success:
            await self._send_audio(context, update.effective_chat.id, search_msg, result)
        else:
            await search_msg.edit_text(f"❌ Не удалось найти `{query}`. {result.error}", parse_mode=ParseMode.MARKDOWN)
    
    async def handle_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        status_text = await self._get_status_text()
        await update.message.reply_text(status_text, parse_mode=ParseMode.MARKDOWN)

    async def radio_test(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Тест скорости радио."""
        user_id = update.effective_user.id
        if not is_admin(user_id):
            return
        
        test_msg = await update.message.reply_text("⏱️ Тестирование скорости радио...")
        
        # Тест поиска
        start = time.time()
        tracks = await self.youtube.search("synthwave music", limit=5)
        search_time = time.time() - start
        
        # Тест загрузки
        if tracks:
            start = time.time()
            result = await self.youtube.download_with_retry(f"{tracks[0].artist} - {tracks[0].title}")
            download_time = time.time() - start
        
        report = (
            f"📊 **Отчет о скорости:**\n"
            f"• Поиск: {search_time:.1f}с\n"
            f"• Загрузка: {download_time:.1f}с\n"
            f"• Найдено треков: {len(tracks)}\n"
            f"• Источник: {self.state.radio.current_genre or 'не установлен'}"
        )
        
        await test_msg.edit_text(report, parse_mode=ParseMode.MARKDOWN)

    # --- Обработчики колбэков и событий ---

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        action = query.data
        user_id = update.effective_user.id
        is_user_admin = is_admin(user_id)
        
        try:
            # Общие действия
            if action == 'menu_main':
                status_text = await self._get_status_text()
                await query.edit_message_text(
                    status_text,
                    reply_markup=get_main_menu_keyboard(is_user_admin),
                    parse_mode=ParseMode.MARKDOWN
                )
            
            elif action == 'menu_refresh':
                status_text = await self._get_status_text()
                await query.edit_message_text(
                    status_text,
                    reply_markup=query.message.reply_markup, # Оставляем текущую клавиатуру
                    parse_mode=ParseMode.MARKDOWN
                )

            # Админ-действия
            elif action.startswith('admin_') or action.startswith('radio_'):
                if not is_user_admin:
                    await query.answer("⛔ Доступно только администраторам.", show_alert=True)
                    return

                if action == 'admin_panel':
                    status_text = await self._get_status_text()
                    await query.edit_message_text(
                        f"👑 **Админ-панель**\n\n{status_text}",
                        reply_markup=get_admin_panel_keyboard(self.state.radio.is_on),
                        parse_mode=ParseMode.MARKDOWN,
                    )
                elif action == "radio_on":
                    await self.radio.start(update.effective_chat.id)
                    await query.answer("✅ Радио включено.")
                elif action == "radio_off":
                    await self.radio.stop()
                    await query.answer("✅ Радио выключено.")
                elif action == "radio_skip":
                    await self.radio.skip()
                    await query.answer("⏭️ Пропускаю трек...")
                
                # Обновляем админ-панель после действия
                if query.message.text and "Админ-панель" in query.message.text:
                    status_text = await self._get_status_text()
                    await query.edit_message_text(
                        f"👑 **Админ-панель**\n\n{status_text}",
                        reply_markup=get_admin_panel_keyboard(self.state.radio.is_on),
                        parse_mode=ParseMode.MARKDOWN,
                    )

        except BadRequest as e:
            if "Message is not modified" in str(e):
                await query.answer("🔄 Статус не изменился.")
            else:
                logger.warning(f"Ошибка BadRequest в колбэке: {e}")
        except Exception as e:
            logger.error(f"Ошибка в handle_callback: {e}", exc_info=True)

    async def handle_chat_member(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.my_chat_member: return
        
        chat, old_status, new_status = update.effective_chat, update.my_chat_member.old_chat_member.status, update.my_chat_member.new_chat_member.status
        
        if old_status == ChatMemberStatus.LEFT and new_status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR]:
            logger.info(f"Бот добавлен в {chat.type}: {chat.title or chat.username} (ID: {chat.id})")
            await self.show_help(update, context) # Показываем приветствие-справку
        elif new_status == ChatMemberStatus.LEFT:
            logger.info(f"Бот удален из {chat.type}: {chat.title or chat.username} (ID: {chat.id})")
            await self.radio.stop_for_chat(chat.id) # Останавливаем радио для этого чата

    async def handle_unknown_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message and update.message.text:
            command = update.message.text.split()[0]
            logger.warning(f"⚠️ Неизвестная команда: {command} от {update.effective_user.id}")

    # --- Вспомогательные методы ---

    async def _get_status_text(self) -> str:
        radio_status = '🟢 Включено' if self.state.radio.is_on else '🔴 Выключено'
        if self.state.radio.is_on and self.state.radio.current_genre:
            radio_status += f" (жанр: *{self.state.radio.current_genre}*)"

        sys_status = "• `psutil` не установлен, системная инфо недоступна."
        try:
            import psutil
            cpu, mem = psutil.cpu_percent(), psutil.virtual_memory().percent
            sys_status = f"• CPU: `{cpu:.1f}%`\n• RAM: `{mem:.1f}%`"
        except (ImportError, FileNotFoundError):
            pass

        return (
            f"**📊 Статус Бота**\n\n"
            f"*Система:*\n{sys_status}\n\n"
            f"*Радио:*\n• Статус: {radio_status}"
        )

    async def _send_audio(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int, search_msg: Message, result: DownloadResult):
        try:
            file_path = result.file_path
            if not os.path.exists(file_path):
                 await search_msg.edit_text("❌ Ошибка: загруженный файл не найден.")
                 return

            file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
            if file_size_mb > 49.5:
                await search_msg.edit_text(f"❌ Файл слишком большой ({file_size_mb:.1f} МБ). Лимит Telegram ~50 МБ.")
                return
            
            await search_msg.edit_text("📤 Отправляю файл...")
            with open(file_path, "rb") as audio:
                caption = f"✅ `{result.track_info.display_name}`"
                await context.bot.send_audio(
                    chat_id=chat_id,
                    audio=audio,
                    title=result.track_info.title,
                    performer=result.track_info.artist,
                    duration=result.track_info.duration,
                    caption=caption,
                    parse_mode=ParseMode.MARKDOWN,
                )
            await search_msg.delete()
        except Exception as e:
            logger.error(f"Ошибка при отправке аудио в чат {chat_id}: {e}", exc_info=True)
            error_text = f"❌ Произошла ошибка при отправке файла: {e}"
            if "Forbidden" in str(e):
                error_text = "❌ Ошибка: Не могу отправить аудио. Возможно, бот заблокирован или у него нет прав."
            await search_msg.edit_text(error_text)
        finally:
            if result.file_path and os.path.exists(result.file_path):
                try:
                    os.remove(result.file_path)
                except OSError as e:
                    logger.error(f"Не удалось удалить файл {result.file_path}: {e}")