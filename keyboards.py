
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from config import Source


def get_main_keyboard() -> InlineKeyboardMarkup:
    """Возвращает главную клавиатуру с основными действиями."""
    keyboard = [
        [
            InlineKeyboardButton("▶️ Вкл. Радио", callback_data='radio_on'),
            InlineKeyboardButton("⏹️ Выкл. Радио", callback_data='radio_off'),
        ],
        [
            InlineKeyboardButton("⏭️ Пропустить трек", callback_data='next_track'),
            InlineKeyboardButton("💿 Сменить источник", callback_data='source_select'),
        ],
        [
            InlineKeyboardButton("🔄 Обновить статус", callback_data='menu_refresh'),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_source_keyboard() -> InlineKeyboardMarkup:
    """Возвращает клавиатуру для выбора источника музыки."""
    keyboard = [
        [
            InlineKeyboardButton(f"📡 {Source.YOUTUBE.value}", callback_data='source_youtube'),
            InlineKeyboardButton(f"🎶 {Source.YOUTUBE_MUSIC.value}", callback_data='source_ytmusic'),
            InlineKeyboardButton(f"🔵 {Source.DEEZER.value}", callback_data='source_deezer'),
        ],
        [
            InlineKeyboardButton("↩️ Назад в меню", callback_data='menu_refresh'),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

