import asyncio
import logging

from telegram import Update, ForceReply, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from config import Settings
from keyboards import (
    get_main_menu_keyboard, get_admin_panel_keyboard, get_track_control_keyboard,
    get_genre_choice_keyboard, get_genre_voting_keyboard, get_voting_in_progress_keyboard
)
from constants import AdminCallback, MenuCallback, TrackCallback, GenreCallback, VoteCallback
from downloaders import YouTubeDownloader
from radio import RadioService

logger = logging.getLogger(__name__)


class BaseHandler:
    def __init__(self, settings: Settings, radio_service: RadioService = None, downloader: YouTubeDownloader = None):
        self._settings = settings
        self._radio = radio_service
        self._downloader = downloader

    def is_admin(self, update: Update) -> bool:
        if not update.effective_user:
            return False
        return update.effective_user.id in self._settings.ADMIN_ID_LIST

    async def handle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        raise NotImplementedError


class StartHandler(BaseHandler):
    async def handle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🎛️ **Главное меню**\n\nИспользуйте кнопки ниже, чтобы управлять ботом.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_main_menu_keyboard(self.is_admin(update)),
        )


class PlayHandler(BaseHandler):
    async def handle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.message.text if update.message.reply_to_message else " ".join(context.args)
        if not query:
            await update.message.reply_text("⚠️ Укажите название трека.")
            return

        search_msg = await update.message.reply_text(f"🔍 Ищу: `{query}`...", parse_mode=ParseMode.MARKDOWN)
        result = await self._downloader.download_with_retry(query)

        if result.success:
            try:
                with open(result.file_path, "rb") as audio:
                    await context.bot.send_audio(
                        chat_id=update.effective_chat.id, audio=audio,
                        title=result.track_info.title, performer=result.track_info.artist,
                        duration=result.track_info.duration, caption=f"✅ `{result.track_info.display_name}`",
                        parse_mode=ParseMode.MARKDOWN, reply_markup=get_track_control_keyboard(),
                    )
                await search_msg.delete()
            except Exception:
                await search_msg.edit_text("❌ Ошибка при отправке файла.")
        else:
            await search_msg.edit_text(f"❌ Не удалось найти `{query}`. {result.error}")


class MenuHandler(BaseHandler):
    async def handle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🎛️ **Главное меню**\n\nИспользуйте кнопки ниже, чтобы управлять ботом.",
            reply_markup=get_main_menu_keyboard(self.is_admin(update)),
            parse_mode=ParseMode.MARKDOWN,
        )


class AdminPanelHandler(BaseHandler):
    async def handle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update):
            await update.message.reply_text("⛔ Только для администраторов.")
            return
        
        await update.message.reply_text(
            "👑 **Админ-панель**",
            reply_markup=get_admin_panel_keyboard(self._radio.is_on),
            parse_mode=ParseMode.MARKDOWN,
        )


class ArtistCommandHandler(BaseHandler):
    async def handle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update):
            await update.message.reply_text("⛔ Только для администраторов.")
            return
        
        artist = " ".join(context.args)
        if not artist:
            await update.message.reply_text("⚠️ Укажите имя артиста. `/artist <имя>`")
            return
        
        await self._radio.set_artist_mode(artist, update.effective_chat.id)
        await update.message.reply_text(f"✅ Включаю режим артиста: **{artist}**", parse_mode=ParseMode.MARKDOWN)


class AdminCallbackHandler(BaseHandler):
    async def handle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        if not self.is_admin(update):
            await query.answer("⛔ Только для администраторов.", show_alert=True)
            return

        action = query.data
        if action == AdminCallback.RADIO_ON:
            await self._radio.start(update.effective_chat.id)
        elif action == AdminCallback.RADIO_OFF:
            await self._radio.stop()
        elif action == AdminCallback.RADIO_SKIP:
            await self._radio.skip()
            await query.answer("⏭️ Пропускаю трек...")
            return
        elif action == AdminCallback.CHANGE_GENRE:
            await query.edit_message_text(
                "🎶 **Выберите жанр для радио:**",
                reply_markup=get_genre_choice_keyboard(),
                parse_mode=ParseMode.MARKDOWN,
            )
            return # Return to prevent redrawing the admin panel
        
        await query.edit_message_text(
            "👑 **Админ-панель**",
            reply_markup=get_admin_panel_keyboard(self._radio.is_on),
            parse_mode=ParseMode.MARKDOWN,
        )


class MenuCallbackHandler(BaseHandler):
    async def handle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        action = query.data
        
        if action == MenuCallback.REFRESH:
            await query.edit_message_text(
                "🎛️ **Главное меню**",
                reply_markup=get_main_menu_keyboard(self.is_admin(update)),
                parse_mode=ParseMode.MARKDOWN,
            )
        elif action == MenuCallback.ADMIN_PANEL:
            if not self.is_admin(update):
                await query.answer("⛔ Только для администраторов.", show_alert=True)
                return
            await query.edit_message_text(
                "👑 **Админ-панель**",
                reply_markup=get_admin_panel_keyboard(self._radio.is_on),
                parse_mode=ParseMode.MARKDOWN,
            )
        elif action == MenuCallback.PLAY_TRACK:
            await query.message.reply_text(
                text="🎧 Пожалуйста, отправьте мне название песни или исполнителя.",
                reply_markup=ForceReply(selective=True, input_field_placeholder="Название трека...")
            )
            await query.message.delete()
        elif action == MenuCallback.VOTE_FOR_GENRE:
            if self._radio.is_vote_in_progress:
                await query.answer("Голосование уже идет!", show_alert=True)
                # Optionally, resend the voting message
                # await context.bot.send_message(...)
            else:
                next_vote_time = self._radio.mode_end_time
                if next_vote_time:
                    minutes_left = round((next_vote_time - datetime.now()).total_seconds() / 60)
                    await query.answer(f"Следующее голосование начнется через ~{minutes_left} минут.", show_alert=True)
                else:
                    await query.answer("Радио выключено. Голосование начнется после запуска радио.", show_alert=True)


class GenreCallbackHandler(BaseHandler):
    async def handle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        if not self.is_admin(update):
            await query.answer("⛔ Только для администраторов.", show_alert=True)
            return
        
        genre = query.data.split(GenreCallback.PREFIX)[1]
        
        await self._radio.set_admin_genre(genre, update.effective_chat.id)
        
        # The message is now sent from within the service, so we just need to go back
        await query.edit_message_text(
            "👑 **Админ-панель**",
            reply_markup=get_admin_panel_keyboard(self._radio.is_on),
            parse_mode=ParseMode.MARKDOWN,
        )


class VoteCallbackHandler(BaseHandler):
    async def handle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        
        if not self._radio.is_vote_in_progress:
            await query.answer("⛔ Голосование уже завершено.", show_alert=True)
            await query.message.delete()
            return

        genre = query.data.split(VoteCallback.PREFIX)[1]
        user_id = query.from_user.id
        
        if await self._radio.register_vote(genre, user_id):
            await query.answer(f"✅ Ваш голос за '{genre.capitalize()}' принят!")
            # Обновляем клавиатуру с новым количеством голосов
            try:
                await query.edit_message_reply_markup(
                    reply_markup=get_genre_voting_keyboard(
                        self._radio._current_vote_genres, self._radio._votes
                    )
                )
            except Exception as e:
                logger.warning(f"Не удалось обновить клавиатуру для голосования: {e}")
        else:
            await query.answer("Что-то пошло не так.", show_alert=True)


class TrackCallbackHandler(BaseHandler):
    async def handle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        action = query.data

        if action == TrackCallback.DELETE:
            await query.message.delete()
            await query.answer("🗑️ Трек удален.")
        else:
            await query.answer("Эта функция в разработке.", show_alert=True)