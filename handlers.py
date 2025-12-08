import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from config import Settings
from keyboards import get_main_menu_keyboard, get_admin_panel_keyboard, get_track_control_keyboard
from constants import AdminCallback, MenuCallback, TrackCallback
from downloaders import YouTubeDownloader
from radio import RadioService

logger = logging.getLogger(__name__)


class BaseHandler:
    def __init__(self, settings: Settings):
        self._settings = settings

    def is_admin(self, update: Update) -> bool:
        if not update.effective_user:
            return False
        return update.effective_user.id in self._settings.ADMIN_ID_LIST

    async def handle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        raise NotImplementedError


class StartHandler(BaseHandler):
    async def handle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        help_text = "🎵 **Groove AI!**\n\n/play <song> - search & download"
        if self.is_admin(update):
            help_text += "\n/admin - admin panel"
        await update.message.reply_text(
            help_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_main_menu_keyboard(self.is_admin(update)),
        )


class PlayHandler(BaseHandler):
    def __init__(self, settings: Settings, downloader: YouTubeDownloader):
        super().__init__(settings)
        self._downloader = downloader

    async def handle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = " ".join(context.args)
        if not query:
            await update.message.reply_text("⚠️ Укажите название трека.")
            return

        search_msg = await update.message.reply_text(f"🔍 Ищу: `{query}`...", parse_mode=ParseMode.MARKDOWN)
        result = await self._downloader.download_with_retry(query)

        if result.success:
            try:
                with open(result.file_path, "rb") as audio:
                    await context.bot.send_audio(
                        chat_id=update.effective_chat.id,
                        audio=audio,
                        title=result.track_info.title,
                        performer=result.track_info.artist,
                        duration=result.track_info.duration,
                        caption=f"✅ `{result.track_info.display_name}`",
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=get_track_control_keyboard(),
                    )
                await search_msg.delete()
            except Exception as e:
                await search_msg.edit_text("❌ Ошибка при отправке файла.")
        else:
            await search_msg.edit_text(f"❌ Не удалось найти `{query}`. {result.error}")


class MenuHandler(BaseHandler):
    async def handle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🎛️ **Главное меню**",
            reply_markup=get_main_menu_keyboard(self.is_admin(update)),
            parse_mode=ParseMode.MARKDOWN,
        )


class AdminPanelHandler(BaseHandler):
    def __init__(self, settings: Settings, radio_service: RadioService):
        super().__init__(settings)
        self._radio = radio_service

    async def handle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update):
            await update.message.reply_text("⛔ Только для администраторов.")
            return
        await update.message.reply_text(
            "👑 **Админ-панель**",
            reply_markup=get_admin_panel_keyboard(self._radio.is_on),
            parse_mode=ParseMode.MARKDOWN,
        )


class AdminCallbackHandler(BaseHandler):
    def __init__(self, settings: Settings, radio_service: RadioService):
        super().__init__(settings)
        self._radio = radio_service

    async def handle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        if not self.is_admin(update):
            return

        action = query.data
        if action == AdminCallback.RADIO_ON:
            await self._radio.start(update.effective_chat.id)
        elif action == AdminCallback.RADIO_OFF:
            await self._radio.stop()
        elif action == AdminCallback.RADIO_SKIP:
            await self._radio.skip()

        await query.edit_message_text(
            "👑 **Админ-панель**",
            reply_markup=get_admin_panel_keyboard(self._radio.is_on),
            parse_mode=ParseMode.MARKDOWN,
        )


class MenuCallbackHandler(BaseHandler):
    def __init__(self, settings: Settings, radio_service: RadioService):
        super().__init__(settings)
        self._radio = radio_service

    async def handle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        action = query.data
        if action == MenuCallback.ADMIN_PANEL:
            if not self.is_admin(update):
                return
            await query.edit_message_text(
                "👑 **Админ-панель**",
                reply_markup=get_admin_panel_keyboard(self._radio.is_on),
                parse_mode=ParseMode.MARKDOWN,
            )
        elif action == MenuCallback.REFRESH:
            # Just edit the message to show it's refreshed
            await query.edit_message_text(
                "🎛️ **Главное меню (обновлено)**",
                reply_markup=get_main_menu_keyboard(self.is_admin(update)),
                parse_mode=ParseMode.MARKDOWN,
            )

class TrackCallbackHandler(BaseHandler):
    async def handle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        action = query.data

        if action == TrackCallback.DELETE:
            await query.message.delete()
            await query.answer("🗑️ Трек удален.")
        elif action == TrackCallback.LIKE:
            await query.answer("❤️ Лайк поставлен (в будущих версиях это будет на что-то влиять)!")
        elif action == TrackCallback.DISLIKE:
            await query.answer("💔 Дизлайк поставлен (в будущих версиях это будет на что-то влиять)!")
        elif action == TrackCallback.ADD_TO_PLAYLIST:
            await query.answer("➕ Трек добавлен в плейлист (пока не реализовано).")
        else:
            await query.answer()