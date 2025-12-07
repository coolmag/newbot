
import asyncio
import os
import sys

from telegram import Update, Message
from telegram.ext import Application, ContextTypes, CommandHandler, CallbackQueryHandler, ChatMemberHandler
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.error import BadRequest, Forbidden

from config import settings, Source
from keyboards import get_main_keyboard, get_source_keyboard
from states import BotState
from youtube import YouTubeDownloader
from deezer import DeezerDownloader
from base import DownloadResult
from radio import RadioService
from logger import logger


def is_admin(update: Update) -> bool:
    """Проверяет, является ли пользователь администратором."""
    return update.effective_user.id in settings.ADMIN_IDS


def validate_query(query: str) -> tuple[bool, str]:
    """Валидирует поисковый запрос."""
    if not query:
        return False, "⚠️ Укажите название трека или книги.\nПример: `/play a-ha take on me`"
    
    clean_query = query.strip()
    if len(clean_query) < 2:
        return False, "⚠️ Запрос слишком короткий. Введите минимум 2 символа."
    
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
        self.deezer = DeezerDownloader()
        self.radio = RadioService(self.state, app.bot, self.youtube)

    async def register(self):
        """Регистрирует все обработчики в приложении."""
        from telegram.ext import MessageHandler, filters
        
        handlers = [
            CommandHandler("start", self.start),
            CommandHandler("menu", self.show_menu),
            CommandHandler(["play", "p"], self.handle_play),
            CommandHandler(["audiobook", "ab"], self.handle_audiobook),
            CommandHandler("radio", self.handle_radio),
            CommandHandler(["source", "src"], self.handle_source),
            CommandHandler(["status", "stat"], self.handle_status),
            CommandHandler("help", self.handle_help),
            CallbackQueryHandler(self.handle_callback),
            ChatMemberHandler(self.handle_chat_member, ChatMemberHandler.MY_CHAT_MEMBER),
            # Обработчик для логирования всех сообщений (для отладки)
            MessageHandler(filters.COMMAND, self.handle_unknown_command),
        ]
        for handler in handlers:
            self.app.add_handler(handler)
        logger.info("✅ Обработчики команд зарегистрированы.")

    async def cleanup(self):
        """Очищает ресурсы при завершении работы бота."""
        try:
            await self.radio.stop()
            await self.deezer.close_session()
            logger.info("✅ Ресурсы очищены.")
        except Exception as e:
            logger.error(f"⚠️ Ошибка при очистке ресурсов: {e}")

    async def handle_chat_member(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обрабатывает событие добавления/удаления бота в канал/группу."""
        if not update.my_chat_member:
            return
        
        chat = update.effective_chat
        old_status = update.my_chat_member.old_chat_member.status
        new_status = update.my_chat_member.new_chat_member.status
        
        # Если бота только что добавили (был LEFT, стал MEMBER или ADMINISTRATOR)
        if old_status == ChatMemberStatus.LEFT and new_status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR]:
            logger.info(f"Бот добавлен в {chat.type}: {chat.title or chat.username} (ID: {chat.id})")
            
            welcome_text = (
                "🎵 **Музыкальный бот запущен!**\n\n"
                "Привет! Я готов помочь вам найти и скачать музыку.\n\n"
                "**Основные команды:**\n"
                "• `/play <название>` - Найти и скачать трек\n"
                "• `/audiobook <название>` - Найти аудиокнигу\n"
                "• `/menu` - Показать меню\n"
                "• `/help` - Справка по командам\n\n"
                "Используйте кнопки ниже для быстрого доступа к функциям."
            )
            
            try:
                await context.bot.send_message(
                    chat_id=chat.id,
                    text=welcome_text,
                    reply_markup=get_main_keyboard(),
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as e:
                logger.error(f"Не удалось отправить приветствие в чат {chat.id}: {e}")
        
        # Если бота удалили
        elif new_status == ChatMemberStatus.LEFT:
            logger.info(f"Бот удален из {chat.type}: {chat.title or chat.username} (ID: {chat.id})")

    async def handle_unknown_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обрабатывает неизвестные команды."""
        try:
            if update.message and update.message.text:
                command = update.message.text.split()[0] if update.message.text else "unknown"
                logger.warning(f"Получена неизвестная команда: {command} от пользователя {update.effective_user.id} в чате {update.effective_chat.id}")
                # Не отвечаем на неизвестные команды, чтобы не спамить
        except Exception as e:
            logger.error(f"Ошибка в handle_unknown_command: {e}", exc_info=True)

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            user = update.effective_user
            chat = update.effective_chat
            logger.info(f"Получена команда /start от пользователя {user.full_name} ({user.id}) в чате {chat.type} {chat.id}")
            
            welcome_text = (
                f"👋 Привет, {user.first_name}!\n\n"
                "Я — музыкальный бот. Я помогу тебе найти и скачать музыку.\n\n"
                "Просто отправь мне команду /play с названием трека, и я найду его для тебя.\n\n"
                "Используй /help, чтобы увидеть все команды."
            )
            await update.message.reply_text(welcome_text, reply_markup=get_main_keyboard())
        except Exception as e:
            logger.error(f"Ошибка в команде /start: {e}", exc_info=True)
            if update.message:
                try:
                    await update.message.reply_text("❌ Произошла ошибка при обработке команды.")
                except:
                    pass

    async def show_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            logger.info(f"Получена команда /menu от пользователя {update.effective_user.id} в чате {update.effective_chat.id}")
            status_text = await self._get_status_text()
            await update.message.reply_text(
                status_text,
                reply_markup=get_main_keyboard(),
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            logger.error(f"Ошибка в команде /menu: {e}", exc_info=True)
            if update.message:
                try:
                    await update.message.reply_text("❌ Произошла ошибка при обработке команды.")
                except:
                    pass

    async def handle_play(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        is_valid, query_or_error = validate_query(" ".join(context.args))
        if not is_valid:
            await update.message.reply_text(query_or_error)
            return

        search_msg = await update.message.reply_text(f"🔍 Ищу трек: `{query_or_error}`...", parse_mode=ParseMode.MARKDOWN)
        
        downloader = self.youtube if self.state.source != Source.DEEZER else self.deezer
        result = await downloader.download_with_retry(query_or_error)
        
        # Если первый источник не справился, пробуем другой
        if not result or not result.success:
            logger.warning(f"Источник {downloader.name} не нашел '{query_or_error}'. Пробую YouTube.")
            result = await self.youtube.download_with_retry(query_or_error)

        if result and result.success:
            await self._send_audio(context, update.effective_chat.id, search_msg, result)
        else:
            await search_msg.edit_text(f"❌ Не удалось найти трек `{query_or_error}`.", parse_mode=ParseMode.MARKDOWN)

    async def handle_audiobook(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        is_valid, query_or_error = validate_query(" ".join(context.args))
        if not is_valid:
            await update.message.reply_text(query_or_error)
            return

        search_msg = await update.message.reply_text(f"📚 Ищу аудиокнигу: `{query_or_error}`...", parse_mode=ParseMode.MARKDOWN)
        
        result = await self.youtube.download_long(f"{query_or_error} аудиокнига")
        
        if result and result.success:
            await self._send_audio(context, update.effective_chat.id, search_msg, result)
        else:
            await search_msg.edit_text(f"❌ Не удалось найти аудиокнигу `{query_or_error}`.", parse_mode=ParseMode.MARKDOWN)

    async def handle_radio(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_admin(update):
            await update.message.reply_text("⛔ Эта команда доступна только администраторам.")
            return

        if not context.args:
            await update.message.reply_text("▶️ Укажите действие: `/radio on` или `/radio off`.")
            return
            
        action = context.args[0].lower()
        if action == "on":
            await self.radio.start(update.effective_chat.id)
            await update.message.reply_text("✅ Радио включено. Музыка скоро начнет играть.")
        elif action == "off":
            await self.radio.stop()
            await update.message.reply_text("✅ Радио выключено.")
        else:
            await update.message.reply_text("⚠️ Неизвестная команда. Используйте `/radio on` или `/radio off`.")

    async def handle_source(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            logger.info(f"Получена команда /source от пользователя {update.effective_user.id} в чате {update.effective_chat.id}")
            await update.message.reply_text("💿 Выберите источник для поиска:", reply_markup=get_source_keyboard())
        except Exception as e:
            logger.error(f"Ошибка в команде /source: {e}", exc_info=True)
            if update.message:
                try:
                    await update.message.reply_text("❌ Произошла ошибка при обработке команды.")
                except:
                    pass

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not query:
            return
        
        await query.answer()
        
        action = query.data
        if not action:
            return
            
        chat_id = update.effective_chat.id

        source_map = {
            'source_youtube': Source.YOUTUBE,
            'source_ytmusic': Source.YOUTUBE_MUSIC,
            'source_deezer': Source.DEEZER,
        }

        if action == 'source_select':
            await query.edit_message_text("💿 Выберите источник для поиска:", reply_markup=get_source_keyboard())
        elif action in source_map:
            self.state.source = source_map[action]
            await query.edit_message_text(f"✅ Источник изменен на: **{self.state.source.value}**", parse_mode=ParseMode.MARKDOWN)
        
        elif action == 'menu_refresh':
            try:
                status_text = await self._get_status_text()
                await query.edit_message_text(status_text, reply_markup=get_main_keyboard(), parse_mode=ParseMode.MARKDOWN)
            except BadRequest:  # Сообщение не изменилось
                pass
        
        elif action.startswith("radio_") or action == "next_track":
            if not is_admin(update):
                await query.answer("⛔ Доступно только администраторам.", show_alert=True)
                return

            if action == "radio_on":
                await self.radio.start(chat_id)
                await query.edit_message_text("✅ Радио включено.")
            elif action == "radio_off":
                await self.radio.stop()
                await query.edit_message_text("✅ Радио выключено.")
            elif action == "next_track":
                await self.radio.skip()
                await query.answer("⏭️ Пропускаю трек...")

    async def handle_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        status_text = await self._get_status_text()
        await update.message.reply_text(status_text, parse_mode=ParseMode.MARKDOWN)

    async def handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        help_text = (
            "**ℹ️ Справка по командам**\n\n"
            "*/play, /p* <название> - Поиск и загрузка трека.\n\n"
            "*/audiobook, /ab* <название> - Поиск аудиокниги.\n\n"
            "*/radio <on/off>* - Включить или выключить радио (только для админов).\n\n"
            "*/source, /src* - Выбрать источник поиска (YouTube, Deezer).\n\n"
            "*/status, /stat* - Показать текущий статус бота.\n\n"
            "*/menu* - Показать главное меню.\n\n"
            "*/help* - Показать это сообщение."
        )
        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

    async def _get_status_text(self) -> str:
        radio_status = '🟢 Включено' if self.state.radio.is_on else '🔴 Выключено'
        if self.state.radio.is_on and self.state.radio.current_genre:
            radio_status += f" (жанр: *{self.state.radio.current_genre}*)"

        try:
            import psutil
            cpu = psutil.cpu_percent()
            mem = psutil.virtual_memory().percent
            sys_status = f"• CPU: `{cpu:.1f}%`\n• RAM: `{mem:.1f}%`"
        except (ImportError, FileNotFoundError):
            sys_status = "• `psutil` не установлен, системная информация недоступна."

        return (
            f"**⚙️ Статус Бота**\n\n"
            f"*Система:*\n{sys_status}\n\n"
            f"*Бот:*\n"
            f"• Источник: `{self.state.source.value}`\n"
            f"• Радио: {radio_status}"
        )

    async def _send_audio(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int, search_msg: Message, result: DownloadResult):
        """Отправляет аудиофайл и удаляет временные файлы."""
        file_size_mb = 0
        try:
            # Проверяем размер файла перед отправкой
            if os.path.exists(result.file_path):
                file_size_mb = os.path.getsize(result.file_path) / (1024 * 1024)
                if file_size_mb > 50:  # Telegram лимит ~50MB
                    await search_msg.edit_text(
                        f"❌ Файл слишком большой ({file_size_mb:.1f} MB). "
                        f"Максимальный размер: 50 MB.",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return
            
            with open(result.file_path, "rb") as audio:
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
        except Forbidden:
            logger.warning(f"Не удалось отправить аудио в чат {chat_id}: бот заблокирован или не имеет прав.")
            await search_msg.edit_text("❌ Ошибка: Не могу отправить аудио. Возможно, бот заблокирован или у него нет прав на отправку файлов.")
        except BadRequest as e:
            logger.error(f"BadRequest при отправке аудио в чат {chat_id}: {e}")
            error_msg = str(e) if hasattr(e, '__str__') else "Неизвестная ошибка Telegram"
            await search_msg.edit_text(f"❌ Ошибка Telegram: {error_msg}")
        finally:
            if result.file_path and os.path.exists(result.file_path):
                try:
                    os.remove(result.file_path)
                except OSError as e:
                    logger.error(f"Не удалось удалить файл {result.file_path}: {e}")

