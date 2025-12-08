from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from constants import AdminCallback, MenuCallback


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
        [radio_button],
        [InlineKeyboardButton("⏭️ Следующий трек", callback_data=AdminCallback.RADIO_SKIP)],
        [InlineKeyboardButton("↩️ Назад в меню", callback_data=AdminCallback.MAIN_MENU)],
    ]
    return InlineKeyboardMarkup(keyboard)