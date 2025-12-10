import asyncio
import logging

from telegram import Update, ForceReply, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from telegram.error import BadRequest

from config import Settings
from keyboards import (
    get_main_menu_keyboard, get_admin_panel_keyboard, get_track_control_keyboard,
    get_genre_choice_keyboard, get_mood_choice_keyboard
)
from constants import AdminCallback, MenuCallback, TrackCallback, GenreCallback, VoteCallback, MoodCallback
from cache_service import CacheService
from downloaders import YouTubeDownloader
from radio import RadioService
from models import TrackInfo

logger = logging.getLogger(__name__)


class BaseHandler:
    def __init__(self, settings: Settings, radio_service: "RadioService" = None, downloader: "YouTubeDownloader" = None, cache_service: "CacheService" = None):
        self._settings = settings
        self._radio = radio_service
        self._downloader = downloader
        self._cache = cache_service

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
        query = ""
        # Проверяем, ждет ли бот название трека (после нажатия кнопки "Заказать трек")
        if context.user_data.get("waiting_for_track_name"):
            if update.message and update.message.text:
                query = update.message.text
                context.user_data["waiting_for_track_name"] = False  # Сбрасываем флаг после получения запроса
            else:
                await update.message.reply_text("⚠️ Пожалуйста, введите название трека после запроса.")
                return
        elif update.message.text and update.message.text.startswith('/play') or update.message.text.startswith('/p'): # Если это команда /play
            query = " ".join(context.args)
        else: # Если это простое сообщение, не являющееся командой и не ответ на ForceReply, то игнорируем
            return
        
        if not query:
            await update.message.reply_text("⚠️ Укажите название трека.")
            return

        search_msg = await update.message.reply_text(f"🔍 Ищу: `{query}`...", parse_mode=ParseMode.MARKDOWN)
        result = await self._downloader.download_with_retry(query)

        if result.success:
            try:
                is_in_favs = await self._cache.is_in_favorites(update.effective_user.id, result.track_info.identifier)
                likes, dislikes = await self._cache.get_ratings(result.track_info.identifier)
                
                caption = (
                    f"✅ `{result.track_info.display_name}`\n\n"
                    f"❤️ {likes}  💔 {dislikes}"
                )
                
                with open(result.file_path, "rb") as audio:
                    await context.bot.send_audio(
                        chat_id=update.effective_chat.id, audio=audio,
                        title=result.track_info.title, performer=result.track_info.artist,
                        duration=result.track_info.duration, caption=caption,
                        parse_mode=ParseMode.MARKDOWN, 
                        reply_markup=get_track_control_keyboard(result.track_info.identifier, is_in_favs),
                    )
                await search_msg.delete()
            except Exception as e:
                logger.error(f"Ошибка при отправке файла: {e}", exc_info=True)
                await search_msg.edit_text("❌ Ошибка при отправке файла.")
        else:
            await search_msg.edit_text(f"❌ Не удалось найти `{query}`. {result.error}")


class DedicateHandler(BaseHandler):
    async def handle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        sender = update.effective_user
        if not context.args or len(context.args) < 2:
            await update.message.reply_text("⚠️ Неправильный формат. Используйте: `/d @username <название песни>`", parse_mode=ParseMode.MARKDOWN)
            return

        recipient, query_list = context.args[0], context.args[1:]
        if not recipient.startswith('@'):
            await update.message.reply_text("⚠️ Неправильный формат. Первым должно идти имя пользователя, начиная с @.", parse_mode=ParseMode.MARKDOWN)
            return
            
        query = " ".join(query_list)
        search_msg = await update.message.reply_text(f"🔍 Ищу '{query}' для {recipient}...", parse_mode=ParseMode.MARKDOWN)
        result = await self._downloader.download_with_retry(query)

        if result.success:
            try:
                is_in_favs = await self._cache.is_in_favorites(update.effective_user.id, result.track_info.identifier)
                likes, dislikes = await self._cache.get_ratings(result.track_info.identifier)

                caption = (
                    f"🎧 Этот трек для {recipient} от {sender.mention_markdown()}!\n\n"
                    f"✅ `{result.track_info.display_name}`\n\n"
                    f"❤️ {likes}  💔 {dislikes}"
                )
                with open(result.file_path, "rb") as audio:
                    await context.bot.send_audio(
                        chat_id=update.effective_chat.id, audio=audio,
                        title=result.track_info.title, performer=result.track_info.artist,
                        duration=result.track_info.duration, caption=caption,
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=get_track_control_keyboard(result.track_info.identifier, is_in_favs),
                    )
                await search_msg.delete()
            except Exception as e:
                logger.error(f"Ошибка при отправке трека-посвящения: {e}", exc_info=True)
                await search_msg.edit_text("❌ Ошибка при отправке файла.")
        else:
            await search_msg.edit_text(f"❌ Не удалось найти `{query}`. {result.error}")


class PlaylistHandler(BaseHandler):
    async def handle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        favorites = await self._cache.get_favorites(user_id)

        if not favorites:
            await update.message.reply_text("✨ Ваше 'Избранное' пока пусто. Добавляйте треки кнопкой '➕ В избранное' под плеером.")
            return
        
        message_parts = ["**✨ Ваше избранное:**\n"]
        for i, track in enumerate(favorites, 1):
            message_parts.append(f"{i}. `{track.display_name}` ({track.format_duration()})")
        
        # Разделяем сообщение, если оно слишком длинное
        full_message = "\n".join(message_parts)
        if len(full_message) > 4096:
            # TODO: Добавить постраничную навигацию для очень больших плейлистов
            await update.message.reply_text("\n".join(message_parts[:50]))
        else:
            await update.message.reply_text(full_message, parse_mode=ParseMode.MARKDOWN)


class MenuHandler(BaseHandler):
    async def handle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🎛️ **Главное меню**\n\nИспользуйте кнопки ниже, чтобы управлять ботом.",
            reply_markup=get_main_menu_keyboard(self.is_admin(update)),
            parse_mode=ParseMode.MARKDOWN,
        )


class AdminPanelHandler(BaseHandler):
    async def handle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update): return
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
        if not self.is_admin(update): return

        action = query.data
        if action == AdminCallback.RADIO_ON: await self._radio.start(update.effective_chat.id)
        elif action == AdminCallback.RADIO_OFF: await self._radio.stop()
        elif action == AdminCallback.RADIO_SKIP: await self._radio.skip()
        elif action == AdminCallback.CHANGE_GENRE:
            await query.edit_message_text("🎶 **Выберите жанр для радио:**", reply_markup=get_genre_choice_keyboard())
            return
        
        await query.edit_message_text("👑 **Админ-панель**", reply_markup=get_admin_panel_keyboard(self._radio.is_on))


class MenuCallbackHandler(BaseHandler):
    async def handle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        action = query.data
        
        if action == MenuCallback.REFRESH:
            await query.edit_message_text("🎛️ **Главное меню**", reply_markup=get_main_menu_keyboard(self.is_admin(update)))
        elif action == MenuCallback.ADMIN_PANEL:
            if not self.is_admin(update): return
            await query.edit_message_text("👑 **Админ-панель**", reply_markup=get_admin_panel_keyboard(self._radio.is_on))
        elif action == MenuCallback.PLAY_TRACK:
            await query.message.reply_text(text="🎧 Название трека?", reply_markup=ForceReply(selective=True))
            context.user_data["waiting_for_track_name"] = True # Устанавливаем флаг
            await query.message.delete()
        elif action == MenuCallback.CHOOSE_MOOD:
            await query.edit_message_text("😊 **Выберите настроение:**", reply_markup=get_mood_choice_keyboard())


class GenreCallbackHandler(BaseHandler):
    async def handle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        if not self.is_admin(update): return
        
        genre = query.data.split(GenreCallback.PREFIX)[1]
        await self._radio.set_admin_genre(genre, update.effective_chat.id)
        await query.edit_message_text("👑 **Админ-панель**", reply_markup=get_admin_panel_keyboard(self._radio.is_on))


class MoodCallbackHandler(BaseHandler):
    async def handle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        mood = query.data.split(MoodCallback.PREFIX)[1]
        await self._radio.set_mood(mood, update.effective_chat.id)
        await query.edit_message_text("🎛️ **Главное меню**", reply_markup=get_main_menu_keyboard(self.is_admin(update)))


class VoteCallbackHandler(BaseHandler):
    async def handle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not self._radio.is_vote_in_progress:
            await query.answer("⛔ Голосование уже завершено.", show_alert=True)
            return

        genre = query.data.split(VoteCallback.PREFIX)[1]
        user_id = query.from_user.id
        
        if self._radio.register_vote(genre, user_id):
            await query.answer(f"✅ Ваш голос за '{genre.capitalize()}' принят!")
            await self._radio.update_vote_keyboard()


class TrackCallbackHandler(BaseHandler):
    async def handle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        
        try:
            _, action, track_id = query.data.split(":")
        except ValueError:
            if query.data == f"{TrackCallback.PREFIX}{TrackCallback.DELETE}":
                await query.message.delete()
                await query.answer("🗑️ Трек удален.")
            else:
                await query.answer("Ошибка: неверный формат колбэка.", show_alert=True)
            return

        if action == TrackCallback.DELETE:
            await query.message.delete()
            await query.answer("🗑️ Трек удален.")
            return

        rating_changed = False
        if action == TrackCallback.LIKE:
            new_likes, new_dislikes = await self._cache.update_rating(user_id, track_id, 1)
            rating_changed = True
            await query.answer("❤️ Вам понравился трек!")
        elif action == TrackCallback.DISLIKE:
            new_likes, new_dislikes = await self._cache.update_rating(user_id, track_id, -1)
            rating_changed = True
            await query.answer("💔 Вам не понравился трек.")
        
        elif action == TrackCallback.ADD_TO_PLAYLIST:
            is_in_favs = await self._cache.is_in_favorites(user_id, track_id)
            track_info = query.message.audio
            
            if is_in_favs:
                await self._cache.remove_from_favorites(user_id, track_id)
                await query.answer("🗑️ Удалено из избранного.")
            else:
                # Нам нужна полная информация о треке, берем ее из сообщения
                track_info_model = TrackInfo(
                    identifier=track_id, title=track_info.title, 
                    artist=track_info.performer, duration=track_info.duration
                )
                await self._cache.add_to_favorites(user_id, track_info_model)
                await query.answer("⭐ Добавлено в избранное!")
            
            # Обновляем клавиатуру, чтобы показать новый статус кнопки
            new_is_in_favs = not is_in_favs
            new_keyboard = get_track_control_keyboard(track_id, new_is_in_favs)
            try:
                await query.edit_message_reply_markup(reply_markup=new_keyboard)
            except BadRequest as e:
                if "message is not modified" not in str(e): logger.warning(e)
            return

        if rating_changed:
            # Обновляем caption, чтобы показать новый счетчик
            base_caption = "\n".join(query.message.caption.split("\n\n")[:-1])
            new_caption = (
                f"{base_caption}\n\n"
                f"❤️ {new_likes}  💔 {new_dislikes}"
            )
            try:
                await query.edit_message_caption(caption=new_caption, parse_mode=ParseMode.MARKDOWN)
            except BadRequest as e:
                if "message is not modified" not in str(e): logger.warning(e)

        await query.answer()