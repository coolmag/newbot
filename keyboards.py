from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from constants import AdminCallback, MenuCallback, TrackCallback, GenreCallback
from config import get_settings


def get_main_menu_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    """
    Возвращает основное меню бота.
    """
    keyboard = [[InlineKeyboardButton("🔄 Обновить", callback_data=MenuCallback.REFRESH)]]
    if is_admin:
        keyboard.insert(
            0, [InlineKeyboardButton("👑 Админ-панель", callback_data=MenuCallback.ADMIN_PANEL)]
        )
    return InlineKeyboardMarkup(keyboard)


def get_admin_panel_keyboard(is_radio_on: bool) -> InlineKeyboardMarkup:
    """
    Возвращает клавиатуру админ-панели.
    """
    radio_button = (
        InlineKeyboardButton("⏹️ Выключить радио", callback_data=AdminCallback.RADIO_OFF)
        if is_radio_on
        else InlineKeyboardButton("▶️ Включить радио", callback_data=AdminCallback.RADIO_ON)
    )
    keyboard = [
        [radio_button, InlineKeyboardButton("🎶 Сменить жанр", callback_data=AdminCallback.CHANGE_GENRE)],
        [InlineKeyboardButton("⏭️ Следующий трек", callback_data=AdminCallback.RADIO_SKIP)],
        [InlineKeyboardButton("↩️ Назад в меню", callback_data=AdminCallback.MAIN_MENU)],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_track_control_keyboard() -> InlineKeyboardMarkup:
    """
    Возвращает клавиатуру для управления треком.
    """
    keyboard = [
        [
            InlineKeyboardButton("❤️", callback_data=TrackCallback.LIKE),
            InlineKeyboardButton("💔", callback_data=TrackCallback.DISLIKE),
            InlineKeyboardButton("➕ В плейлист", callback_data=TrackCallback.ADD_TO_PLAYLIST),
            InlineKeyboardButton("🗑️", callback_data=TrackCallback.DELETE),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_genre_choice_keyboard() -> InlineKeyboardMarkup:
    """
    Создает клавиатуру для выбора жанра радио.
    """
    settings = get_settings()
    buttons = [
        InlineKeyboardButton(
            text=genre.capitalize(), 
            callback_data=f"{GenreCallback.PREFIX}{genre}"
        ) 
        for genre in settings.RADIO_GENRES
    ]
    # Группируем кнопки по 3 в ряд
    keyboard = [buttons[i:i + 3] for i in range(0, len(buttons), 3)]
    keyboard.append([InlineKeyboardButton("↩️ Назад в админ-панель", callback_data=MenuCallback.ADMIN_PANEL)])
    return InlineKeyboardMarkup(keyboard)


