"""
Telegram Bot для интернет-магазина
с оплатой наличными или переводом на карту

Установка: pip install python-telegram-bot==20.7
Запуск:    python bot.py
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)

# ══════════════════════════════════════════════
#  НАСТРОЙКИ — замени на свои
# ══════════════════════════════════════════════
BOT_TOKEN  = "7591066854:AAE6REPo-oQQZB1GzLo3RVNfP0LlGIeUkCs"
ADMIN_ID   = 1649383849          # твой Telegram ID (узнать у @userinfobot)

# Реквизиты для оплаты
CARD_NUMBER   = "8600 1234 5678 9012"   # номер карты Uzcard/Humo
CARD_HOLDER   = "Qudratov Sunnatullo"
PHONE_PAYMENT = "+998 93 466 13 01"     # номер для перевода

# ══════════════════════════════════════════════
#  КАТАЛОГ ТОВАРОВ
# ══════════════════════════════════════════════
PRODUCTS = {
    "socks_white": {
        "name": "Носки белые",
        "price": 15_000,
        "description": "Классические белые носки, хлопок 100%\nРазмеры: 36-40, 41-45",
        "emoji": "🧦",
    },
    "tshirt_base": {
        "name": "Футболка базовая",
        "price": 89_000,
        "description": "Оверсайз футболка\nЦвета: белый, чёрный, серый",
        "emoji": "👕",
    },
    "hoodie": {
        "name": "Худи",
        "price": 189_000,
        "description": "Тёплое худи с карманом кенгуру\nЦвета: чёрный, бежевый",
        "emoji": "🧥",
    },
}

# Шаги оформления заказа
ASK_NAME, ASK_PHONE, ASK_ADDRESS, ASK_PAYMENT, WAIT_RECEIPT = range(5)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════
#  ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ══════════════════════════════════════════════

def get_cart(context) -> dict:
    return context.user_data.setdefault("cart", {})

def cart_total(cart: dict) -> int:
    return sum(PRODUCTS[pid]["price"] * qty
               for pid, qty in cart.items() if pid in PRODUCTS)

def fmt_price(amount: int) -> str:
    return f"{amount:,} сум".replace(",", " ")

def format_cart(cart: dict) -> str:
    if not cart:
        return "🛒 Корзина пуста"
    lines = ["🛒 *Ваша корзина:*\n"]
    for pid, qty in cart.items():
        p = PRODUCTS[pid]
        lines.append(f"{p['emoji']} {p['name']} × {qty} = {fmt_price(p['price'] * qty)}")
    lines.append(f"\n💰 *Итого: {fmt_price(cart_total(cart))}*")
    return "\n".join(lines)


# ══════════════════════════════════════════════
#  КЛАВИАТУРЫ
# ══════════════════════════════════════════════

def kb_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛍 Каталог",  callback_data="catalog")],
        [InlineKeyboardButton("🛒 Корзина",  callback_data="cart")],
        [InlineKeyboardButton("📞 Контакты", callback_data="contact")],
    ])

def kb_catalog():
    rows = [[InlineKeyboardButton(
                f"{p['emoji']} {p['name']} — {fmt_price(p['price'])}",
                callback_data=f"product_{pid}")]
            for pid, p in PRODUCTS.items()]
    rows.append([InlineKeyboardButton("◀️ Назад", callback_data="main_menu")])
    return InlineKeyboardMarkup(rows)

def kb_product(pid: str, qty: int):
    label = f"🛒 В корзине: {qty} шт." if qty else "🛒 Добавить в корзину"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➖", callback_data=f"remove_{pid}"),
            InlineKeyboardButton(str(qty) if qty else "0", callback_data="noop"),
            InlineKeyboardButton("➕", callback_data=f"add_{pid}"),
        ],
        [InlineKeyboardButton(label, callback_data="cart")],
        [InlineKeyboardButton("◀️ Каталог", callback_data="catalog")],
    ])

def kb_cart():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Оформить заказ", callback_data="checkout")],
        [InlineKeyboardButton("🗑 Очистить",        callback_data="clear_cart")],
        [InlineKeyboardButton("◀️ Каталог",         callback_data="catalog")],
    ])

def kb_payment_method():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💵 Наличные при получении", callback_data="pay_cash")],
        [InlineKeyboardButton("💳 Перевод на карту",       callback_data="pay_card")],
    ])

def kb_cancel():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Отменить заказ", callback_data="cancel_order")]
    ])


# ══════════════════════════════════════════════
#  ОСНОВНЫЕ ХЭНДЛЕРЫ
# ══════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Добро пожаловать в наш магазин!\n\nВыберите раздел:",
        reply_markup=kb_main()
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = q.data
    cart = get_cart(context)

    if d == "main_menu":
        await q.edit_message_text("🏠 Главное меню:", reply_markup=kb_main())

    elif d == "catalog":
        await q.edit_message_text(
            "🛍 *Наш каталог:*\nВыберите товар:",
            reply_markup=kb_catalog(), parse_mode="Markdown")

    elif d.startswith("product_"):
        pid = d[8:]
        p   = PRODUCTS[pid]
        qty = cart.get(pid, 0)
        await q.edit_message_text(
            f"{p['emoji']} *{p['name']}*\n\n"
            f"💰 Цена: *{fmt_price(p['price'])}*\n\n"
            f"📋 {p['description']}",
            reply_markup=kb_product(pid, qty), parse_mode="Markdown")

    elif d.startswith("add_"):
        pid = d[4:]
        cart[pid] = cart.get(pid, 0) + 1
        await q.edit_message_reply_markup(kb_product(pid, cart[pid]))

    elif d.startswith("remove_"):
        pid = d[7:]
        if cart.get(pid, 0) > 0:
            cart[pid] -= 1
            if cart[pid] == 0:
                del cart[pid]
        await q.edit_message_reply_markup(kb_product(pid, cart.get(pid, 0)))

    elif d == "cart":
        if cart:
            await q.edit_message_text(
                format_cart(cart), reply_markup=kb_cart(), parse_mode="Markdown")
        else:
            await q.edit_message_text(
                "🛒 Корзина пуста\n\nДобавьте товары из каталога!",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🛍 Каталог", callback_data="catalog")]]))

    elif d == "clear_cart":
        context.user_data["cart"] = {}
        await q.edit_message_text(
            "🗑 Корзина очищена",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛍 Каталог", callback_data="catalog")]]))

    elif d == "contact":
        await q.edit_message_text(
            "📞 *Свяжитесь с нами:*\n\n"
            f"📱 Telegram: @yourshop\n"
            f"📞 Телефон: {PHONE_PAYMENT}\n"
            "🕐 Работаем: 9:00 – 21:00",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ Назад", callback_data="main_menu")]]),
            parse_mode="Markdown")

    elif d == "cancel_order":
        await q.edit_message_text("❌ Заказ отменён", reply_markup=kb_main())
        return ConversationHandler.END

    elif d == "noop":
        pass

    # Шаг выбора способа оплаты — внутри ConversationHandler
    elif d in ("pay_cash", "pay_card"):
        return await handle_payment_choice(update, context)


# ══════════════════════════════════════════════
#  ОФОРМЛЕНИЕ ЗАКАЗА (ConversationHandler)
# ══════════════════════════════════════════════

async def checkout_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Точка входа — нажатие кнопки «Оформить заказ»"""
    q = update.callback_query
    await q.answer()
    cart = get_cart(context)
    if not cart:
        await q.answer("Корзина пуста!", show_alert=True)
        return ConversationHandler.END

    context.user_data["order_cart"] = dict(cart)
    await q.edit_message_text(
        "📝 *Оформление заказа — шаг 1/4*\n\nВведите ваше *имя и фамилию:*",
        parse_mode="Markdown")
    return ASK_NAME

async def ask_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["order_name"] = update.message.text.strip()
    await update.message.reply_text(
        "📱 *Шаг 2/4* — Введите ваш *номер телефона:*",
        parse_mode="Markdown")
    return ASK_PHONE

async def ask_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["order_phone"] = update.message.text.strip()
    await update.message.reply_text(
        "📍 *Шаг 3/4* — Введите *адрес доставки:*",
        parse_mode="Markdown")
    return ASK_ADDRESS

async def ask_payment_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["order_address"] = update.message.text.strip()
    total = cart_total(context.user_data["order_cart"])
    await update.message.reply_text(
        f"💳 *Шаг 4/4* — Выберите способ оплаты:\n\n"
        f"💰 Сумма к оплате: *{fmt_price(total)}*",
        reply_markup=kb_payment_method(),
        parse_mode="Markdown")
    return ASK_PAYMENT

async def handle_payment_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    await q.answer()
    method = q.data  # "pay_cash" или "pay_card"
    context.user_data["order_payment"] = method
    total = cart_total(context.user_data["order_cart"])

    if method == "pay_cash":
        # Наличные — сразу подтверждаем
        await q.edit_message_text(
            "✅ *Заказ принят!*\n\n"
            "💵 Оплата: *наличными при получении*\n\n"
            "Мы свяжемся с вами в течение 30 минут для подтверждения. 🚀",
            parse_mode="Markdown",
            reply_markup=kb_main())
        await send_admin_notification(context, method="Наличные при получении")
        context.user_data["cart"] = {}
        return ConversationHandler.END

    else:
        # Карта — показываем реквизиты и просим скрин
        await q.edit_message_text(
            f"💳 *Оплата переводом на карту*\n\n"
            f"Переведите *{fmt_price(total)}* на карту:\n\n"
            f"🏦 Номер карты: `{CARD_NUMBER}`\n"
            f"👤 Получатель: *{CARD_HOLDER}*\n\n"
            f"После перевода отправьте *скриншот чека* в этот чат.\n\n"
            f"⏱ Ожидаем подтверждение в течение 24 часов.",
            reply_markup=kb_cancel(),
            parse_mode="Markdown")
        return WAIT_RECEIPT

async def receive_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получаем скрин чека (фото или документ)"""
    has_photo = bool(update.message.photo)
    has_doc   = bool(update.message.document)

    if not (has_photo or has_doc):
        await update.message.reply_text(
            "📸 Пожалуйста, отправьте *скриншот* перевода (фото или файл).",
            parse_mode="Markdown")
        return WAIT_RECEIPT

    await update.message.reply_text(
        "✅ *Чек получен! Заказ оформлен.*\n\n"
        "Мы проверим оплату и свяжемся с вами в течение 30 минут. 🚀",
        reply_markup=kb_main(),
        parse_mode="Markdown")

    # Пересылаем чек админу
    await send_admin_notification(context, method="Карта (перевод)", receipt_msg=update.message)
    context.user_data["cart"] = {}
    return ConversationHandler.END

async def send_admin_notification(context, method: str, receipt_msg=None):
    """Отправляет уведомление о заказе администратору"""
    cart    = context.user_data.get("order_cart", {})
    name    = context.user_data.get("order_name", "—")
    phone   = context.user_data.get("order_phone", "—")
    address = context.user_data.get("order_address", "—")
    total   = cart_total(cart)

    text = (
        "🔔 *НОВЫЙ ЗАКАЗ!*\n\n"
        f"👤 Имя: {name}\n"
        f"📱 Телефон: {phone}\n"
        f"📍 Адрес: {address}\n"
        f"💳 Оплата: {method}\n\n"
        f"{format_cart(cart)}\n\n"
        f"💰 К оплате: *{fmt_price(total)}*"
    )
    try:
        await context.bot.send_message(ADMIN_ID, text, parse_mode="Markdown")
        if receipt_msg:
            await receipt_msg.forward(ADMIN_ID)
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления: {e}")

async def cancel_conv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Заказ отменён.", reply_markup=kb_main())
    return ConversationHandler.END


# ══════════════════════════════════════════════
#  ЗАПУСК
# ══════════════════════════════════════════════

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(checkout_start, pattern="^checkout$")],
        states={
            ASK_NAME:    [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_phone)],
            ASK_PHONE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_address)],
            ASK_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_payment_method)],
            ASK_PAYMENT: [CallbackQueryHandler(handle_payment_choice, pattern="^pay_(cash|card)$"),
                          CallbackQueryHandler(button_handler, pattern="^cancel_order$")],
            WAIT_RECEIPT:[
                MessageHandler(filters.PHOTO | filters.Document.ALL, receive_receipt),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_receipt),
                CallbackQueryHandler(button_handler, pattern="^cancel_order$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(button_handler))

    print("🤖 Бот запущен! Ctrl+C для остановки.")
    app.run_polling()

if __name__ == "__main__":
    main()
