from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def get_main_menu_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    """
    Возвращает основное меню бота.
    Кнопка админ-панели отображается только для администраторов.
    """
    keyboard = [
        [InlineKeyboardButton("🔄 Обновить", callback_data='menu_refresh')]
    ]
    if is_admin:
        keyboard.insert(0, [InlineKeyboardButton("👑 Админ-панель", callback_data='admin_panel')])
    
    return InlineKeyboardMarkup(keyboard)


def get_admin_panel_keyboard(is_radio_on: bool) -> InlineKeyboardMarkup:
    """
    Возвращает клавиатуру админ-панели.
    """
    radio_button = (
        InlineKeyboardButton("⏹️ Выключить радио", callback_data='radio_off')
        if is_radio_on
        else InlineKeyboardButton("▶️ Включить радио", callback_data='radio_on')
    )
    
    keyboard = [
        [radio_button],
        [InlineKeyboardButton("⏭️ Следующий трек", callback_data='radio_skip')],
        [InlineKeyboardButton("↩️ Назад в меню", callback_data='menu_main')]
    ]
    return InlineKeyboardMarkup(keyboard)