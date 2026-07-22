import re
import json
import logging
import os
import html
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Optional, List

import aiosqlite
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError, Forbidden
from telegram.ext import (
    Application,
    MessageHandler,
    filters,
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler
)

load_dotenv()

# ========================= КОНФИГ =========================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
UZCARD_REQS = os.environ.get("UZCARD_REQS", "8600 0000 0000 0000 (Имя Получателя)")

SOURCE_CHAT_ID = -1003469691743
CHECK_RANGE = 4  # Основная игра + 3 догона

# ⚙️ Настройка смещения для мастей (на какую игру вперед давать прогноз):
SUIT_OFFSET = int(os.environ.get("SUIT_OFFSET", 1))

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)
DB_FILE = os.path.join(DATA_DIR, "bot_database.db")
LOG_FILE = os.path.join(DATA_DIR, "pro_predictor.log")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ========================= МАТРИЦА МАСТЕЙ =========================
SUIT_MATRIX = {
    ('♣', '♦'): '♠', ('♣', '♠'): '♣', ('♣', '♣'): '♠', ('♥', '♠'): '♥',
    ('♥', '♣'): '♠', ('♥', '♦'): '♦', ('♥', '♥'): '♦', ('♣', '♥'): '♠',
    ('♠', '♥'): '♦', ('♠', '♣'): '♦', ('♠', '♦'): '♥', ('♠', '♠'): '♥',
    ('♦', '♠'): '♠', ('♦', '♣'): '♣', ('♦', '♥'): '♦', ('♦', '♦'): '♥'
}

game_history: List[Dict] = []


# ========================= БАЗА ДАННЫХ (SQLITE) =========================
async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                selected_mode TEXT DEFAULT 'off',
                free_two INTEGER DEFAULT 3,
                free_three INTEGER DEFAULT 3,
                free_player_itm_5_5 INTEGER DEFAULT 3,
                free_natural INTEGER DEFAULT 3,
                free_suit_p INTEGER DEFAULT 3,
                free_suit_b INTEGER DEFAULT 3,
                subscription_until TEXT,
                referrer_id INTEGER,
                is_active INTEGER DEFAULT 1
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS stats (
                mode TEXT PRIMARY KEY,
                success INTEGER DEFAULT 0,
                fail INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS active_predictions (
                user_id INTEGER PRIMARY KEY,
                target_raw INTEGER,
                mode TEXT,
                title TEXT,
                target_suit TEXT,
                msg_id INTEGER
            )
        """)
        await db.commit()


async def get_user(user_id: int) -> dict:
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)

            await db.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
            await db.commit()

            async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor2:
                return dict(await cursor2.fetchone())


async def update_user(user_id: int, **kwargs):
    fields = ", ".join([f"{k} = ?" for k in kwargs.keys()])
    values = list(kwargs.values()) + [user_id]
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(f"UPDATE users SET {fields} WHERE user_id = ?", values)
        await db.commit()


async def get_stats() -> dict:
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM stats") as cursor:
            rows = await cursor.fetchall()
            return {r['mode']: {'success': r['success'], 'fail': r['fail']} for r in rows}


async def update_stat(mode: str, is_success: bool):
    field = "success" if is_success else "fail"
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(f"""
            INSERT INTO stats (mode, {field}) VALUES (?, 1)
            ON CONFLICT(mode) DO UPDATE SET {field} = {field} + 1
        """, (mode,))
        await db.commit()


# ========================= УТИЛИТЫ =========================
def is_subscribed(user: dict) -> bool:
    until = user.get("subscription_until")
    if not until:
        return False
    try:
        return datetime.fromisoformat(until) > datetime.now()
    except ValueError:
        return False


def extract_ranks_and_suits(cards_str: str):
    cleaned = re.sub(r'[🔰✅🟩]', '', cards_str)
    matches = re.findall(r'([A-Z\d]+)\s*([♣♦♥♠])', cleaned)
    return [m[0] for m in matches], [m[1] for m in matches]


def parse_game(text: str) -> Optional[Dict]:
    if not text or '#N' not in text:
        return None

    # Очищаем от временных меток телеграма, если они есть
    text_clean = re.sub(r'^\[\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2}\]\s*[^:]+:\s*', '', text)

    # Гибкий шаблон: ищет номер игры #N... и счет с картами
    pattern = r'#N(\d+)\.\s*(?:✅|🔰)?\s*(\d+)\s*\(([^)]+)\)\s*(?:✅|🔰)?\s*(\d+)\s*\(([^)]+)\)'
    m = re.search(pattern, text_clean)

    if m:
        raw_id = int(m.group(1))
        p_score, p_str = int(m.group(2)), m.group(3)
        b_score, b_str = int(m.group(4)), m.group(5)

        p_ranks, p_suits = extract_ranks_and_suits(p_str)
        b_ranks, b_suits = extract_ranks_and_suits(b_str)

        return {
            "raw_id": raw_id,
            "player_score": p_score,
            "banker_score": b_score,
            "player_ranks": p_ranks,
            "player_suits": p_suits,
            "banker_ranks": b_ranks,
            "banker_suits": b_suits,
            "player_count": len(p_ranks),
            "banker_count": len(b_ranks),
            "is_natural": "#R" in text
        }
    return None


def get_last_two_suits(suits_list: List[str]) -> Optional[tuple]:
    if len(suits_list) >= 3:
        return (suits_list[1], suits_list[2])
    elif len(suits_list) == 2:
        return (suits_list[0], suits_list[1])
    return None


# ========================= КЛАВИАТУРЫ =========================
def main_menu(current_mode: str = "off"):
    def mark(mode_name):
        return " 🟢 (Активен)" if current_mode == mode_name else ""

    keyboard = [
        [InlineKeyboardButton(f"🎯 2 карты {mark('two')}", callback_data="select_two")],
        [InlineKeyboardButton(f"🎯 3 карты {mark('three')}", callback_data="select_three")],
        [InlineKeyboardButton(f"📉 ИТМ 5.5 Игрока {mark('player_itm_5_5')}", callback_data="select_player_itm_5_5")],
        [InlineKeyboardButton(f"⚡ Натурал {mark('natural')}", callback_data="select_natural")],
        [InlineKeyboardButton(f"🎴 Масть Игрока {mark('suit_p')}", callback_data="select_suit_p")],
        [InlineKeyboardButton(f"🎴 Масть Банкира {mark('suit_b')}", callback_data="select_suit_b")],
        [InlineKeyboardButton("🛑 Остановить авто-прогнозы", callback_data="stop_mode")],
        [InlineKeyboardButton("💎 Купить подписку", callback_data="subscribe")],
        [InlineKeyboardButton("👥 Рефералы", callback_data="referral")],
        [InlineKeyboardButton("📊 Статистика", callback_data="stats")]
    ]
    return InlineKeyboardMarkup(keyboard)


def back_menu():
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Главное меню", callback_data="main_menu")]])


def admin_confirm_keyboard(user_id: int):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("1 день", callback_data=f"adm_grant_{user_id}_1"),
            InlineKeyboardButton("7 дней", callback_data=f"adm_grant_{user_id}_7"),
            InlineKeyboardButton("30 дней", callback_data=f"adm_grant_{user_id}_30")
        ],
        [InlineKeyboardButton("❌ Отклонить", callback_data=f"adm_reject_{user_id}")]
    ])


# ========================= ОБРАБОТКА ИГР =========================
async def handle_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.channel_post or update.edited_channel_post or update.message or update.edited_message
    if not msg or msg.chat.id != SOURCE_CHAT_ID or not msg.text:
        return

    game = parse_game(msg.text)
    if not game:
        return

    raw_id = game["raw_id"]
    if game_history and game_history[-1]["raw_id"] == raw_id:
        return

    # === 1. ПРОВЕРКА АКТИВНЫХ ПРОГНОЗОВ В БД ===
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM active_predictions") as cursor:
            active_preds = [dict(r) for r in await cursor.fetchall()]

    for pred in active_preds:
        uid = pred["user_id"]
        target_raw = pred["target_raw"]
        offset = raw_id - target_raw

        if 0 <= offset < CHECK_RANGE:
            p_type = pred["mode"]
            target_suit = pred.get("target_suit")
            is_success = False

            if p_type == "two" and game["player_count"] == 2:
                is_success = True
            elif p_type == "three" and game["player_count"] >= 3:
                is_success = True
            elif p_type == "player_itm_5_5" and game["player_score"] <= 5:
                is_success = True
            elif p_type == "natural" and game["is_natural"]:
                is_success = True
            elif p_type == "suit_p" and target_suit in game["player_suits"]:
                is_success = True
            elif p_type == "suit_b" and target_suit in game["banker_suits"]:
                is_success = True

            if is_success:
                emoji = ["0️⃣", "1️⃣", "2️⃣", "3️⃣"][offset]
                await update_stat(p_type, True)
                async with aiosqlite.connect(DB_FILE) as db:
                    await db.execute("DELETE FROM active_predictions WHERE user_id = ?", (uid,))
                    await db.commit()

                try:
                    await context.bot.edit_message_text(
                        chat_id=uid, message_id=pred["msg_id"],
                        text=f"✅ **#{target_raw}** ➔ **{pred['title']}** [Зашел на #{raw_id} {emoji}]",
                        parse_mode='Markdown'
                    )
                except TelegramError:
                    pass

            elif offset == CHECK_RANGE - 1:
                await update_stat(p_type, False)
                async with aiosqlite.connect(DB_FILE) as db:
                    await db.execute("DELETE FROM active_predictions WHERE user_id = ?", (uid,))
                    await db.commit()

                try:
                    await context.bot.edit_message_text(
                        chat_id=uid, message_id=pred["msg_id"],
                        text=f"❌ **#{target_raw}** ➔ **{pred['title']}** [3/3 Минус 💥]",
                        parse_mode='Markdown'
                    )
                except TelegramError:
                    pass

    # === 2. ИСТОРИЯ ===
    game_history.append(game)
    if len(game_history) > 10: game_history.pop(0)

    # === 3. АСИНХРОННАЯ РАССЫЛКА СИГНАЛОВ ПОЛЬЗОВАТЕЛЯМ ===
    has_6 = '6' in game["player_ranks"]
    has_7 = '7' in game["player_ranks"]
    avoid_card_conflict = has_6 and has_7

    last_2_naturals = [g["is_natural"] for g in game_history[-2:]] if len(game_history) >= 2 else []

    # ЛОГИКА МАСТЕЙ
    b_last_suits = get_last_two_suits(game["banker_suits"])
    pred_suit_p = SUIT_MATRIX.get(b_last_suits) if b_last_suits else None

    p_last_suits = get_last_two_suits(game["player_suits"])
    pred_suit_b = SUIT_MATRIX.get(p_last_suits) if p_last_suits else None

    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE selected_mode != 'off' AND is_active = 1") as cursor:
            active_users = [dict(r) for r in await cursor.fetchall()]

    async def send_signal(user):
        uid = user["user_id"]
        mode = user["selected_mode"]

        async with aiosqlite.connect(DB_FILE) as db:
            async with db.execute("SELECT 1 FROM active_predictions WHERE user_id = ?", (uid,)) as cursor:
                if await cursor.fetchone(): return

        signal_matched = False
        title, target_suit = "", None
        target_raw = raw_id + 1

        if mode == "two" and has_6 and not avoid_card_conflict:
            signal_matched, title = True, "6️⃣ Игрок 2 карты"
        elif mode == "three" and has_7 and not avoid_card_conflict:
            signal_matched, title = True, "7️⃣ Игрок 3 карты"
        elif mode == "player_itm_5_5" and game["player_score"] > 5:
            signal_matched, title = True, "📉 Игрок ИТМ 5.5"
        elif mode == "natural" and last_2_naturals == [False, False]:
            signal_matched, title = True, "⚡ Натурал (#R)"
        elif mode == "suit_p" and pred_suit_p:
            signal_matched, target_suit = True, pred_suit_p
            target_raw = raw_id + SUIT_OFFSET
            title = f"{pred_suit_p} Игрок"
        elif mode == "suit_b" and pred_suit_b:
            signal_matched, target_suit = True, pred_suit_b
            target_raw = raw_id + SUIT_OFFSET
            title = f"{pred_suit_b} Банкир"

        if signal_matched:
            if not is_subscribed(user):
                limit_key = f"free_{mode}"
                if user.get(limit_key, 0) <= 0:
                    try:
                        await context.bot.send_message(
                            uid, "⚠️ **Авто-режим остановлен:** закончились попытки!",
                            reply_markup=InlineKeyboardMarkup(
                                [[InlineKeyboardButton("💎 Купить подписку", callback_data="subscribe")]]),
                            parse_mode='Markdown'
                        )
                    except Forbidden:
                        await update_user(uid, is_active=0)
                    except TelegramError:
                        pass
                    await update_user(uid, selected_mode="off")
                    return

                await update_user(uid, **{limit_key: user[limit_key] - 1})

            try:
                sent_msg = await context.bot.send_message(
                    uid,
                    f"⚡ **Игра #{target_raw}** ➔ **{title}**\n🔄 В игре (#{target_raw}–#{target_raw + 3})",
                    parse_mode='Markdown'
                )

                async with aiosqlite.connect(DB_FILE) as db:
                    await db.execute("""
                        INSERT OR REPLACE INTO active_predictions (user_id, target_raw, mode, title, target_suit, msg_id)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (uid, target_raw, mode, title, target_suit, sent_msg.message_id))
                    await db.commit()

            except Forbidden:
                await update_user(uid, selected_mode="off", is_active=0)
            except TelegramError as e:
                logger.error(f"Ошибка отправки прогноза {uid}: {e}")

    if active_users:
        await asyncio.gather(*(send_signal(u) for u in active_users), return_exceptions=True)


# ========================= КОМАНДЫ И КНОПКИ =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await get_user(user_id)

    if context.args and context.args[0].startswith("ref_"):
        try:
            ref_id = int(context.args[0].split("_")[1])
            if ref_id != user_id and not user.get("referrer_id"):
                await update_user(user_id, referrer_id=ref_id)
        except ValueError:
            pass

    await update.message.reply_text(
        "👋 **Добро пожаловать в Predictor Pro!**\n\nВыберите алгоритм для запуска авто-прогнозов.",
        reply_markup=main_menu(user["selected_mode"]), parse_mode='Markdown'
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = await get_user(user_id)

    try:
        if query.data == "main_menu":
            await query.edit_message_text(
                "👋 **Главное меню**\nВыберите алгоритм 👇",
                reply_markup=main_menu(user["selected_mode"]), parse_mode='Markdown'
            )

        elif query.data == "stop_mode":
            await update_user(user_id, selected_mode="off")
            await query.edit_message_text(
                "🛑 **Авто-выдача прогнозов остановлена.**",
                reply_markup=main_menu("off"), parse_mode='Markdown'
            )

        elif query.data in ["select_two", "select_three", "select_player_itm_5_5", "select_natural", "select_suit_p",
                            "select_suit_b"]:
            mode_map = {
                "select_two": ("two", "2 карты"), "select_three": ("three", "3 карты"),
                "select_player_itm_5_5": ("player_itm_5_5", "ИТМ 5.5 Игрока"),
                "select_natural": ("natural", "Натурал"), "select_suit_p": ("suit_p", "Масть Игрока"),
                "select_suit_b": ("suit_b", "Масть Банкира")
            }
            mode_code, mode_title = mode_map[query.data]

            if user.get(f"free_{mode_code}", 0) <= 0 and not is_subscribed(user):
                await offer_subscription(query, is_limit=True)
                return

            await update_user(user_id, selected_mode=mode_code)
            await query.edit_message_text(
                f"🎯 **Авто-режим включён!**\n\nВыбран алгоритм: **{mode_title}**",
                reply_markup=main_menu(mode_code), parse_mode='Markdown'
            )

        elif query.data == "subscribe":
            await offer_subscription(query)

        elif query.data == "referral":
            bot_username = (await context.bot.get_me()).username
            await query.edit_message_text(
                f"👥 **Реферальная система**\n\nСсылка: `https://t.me/{bot_username}?start=ref_{user_id}`\n\n+3 дня VIP за друга!",
                parse_mode='Markdown', reply_markup=main_menu(user["selected_mode"])
            )

        elif query.data == "stats":
            stats = await get_stats()
            text = "📊 **Статистика алгоритмов**\n\n"
            titles = {
                "two": "2 карты", "three": "3 карты", "player_itm_5_5": "ИТМ 5.5 Игрока",
                "natural": "Натурал (#R)", "suit_p": "Масть Игрока", "suit_b": "Масть Банкира"
            }
            for k, name in titles.items():
                st = stats.get(k, {"success": 0, "fail": 0})
                tot = st["success"] + st["fail"]
                rate = (st["success"] / tot * 100) if tot > 0 else 0
                text += f"▪️ **{name}:** {st['success']}/{tot} ({rate:.1f}%)\n"

            await query.edit_message_text(text, parse_mode='Markdown', reply_markup=main_menu(user["selected_mode"]))

        elif query.data.startswith("adm_grant_"):
            if user_id != ADMIN_ID: return
            _, _, t_uid, days = query.data.split("_")
            await grant_subscription(context, int(t_uid), int(days))
            await query.edit_message_caption(
                caption=f"✅ Подписка на {days} дн. выдана пользователю <code>{t_uid}</code>", parse_mode='HTML')

        elif query.data.startswith("adm_reject_"):
            if user_id != ADMIN_ID: return
            t_uid = query.data.split("_")[2]
            await query.edit_message_caption(caption=f"❌ Заявка пользователя <code>{t_uid}</code> отклонена.",
                                             parse_mode='HTML')

    except TelegramError as e:
        if "Message is not modified" not in str(e):
            logger.error(f"Ошибка кнопки: {e}")


async def offer_subscription(query_or_update, is_limit=False):
    prefix = "⚠️ **Бесплатные попытки закончились!**\n\n" if is_limit else ""
    text = (
        f"{prefix}💎 **Оформление VIP-подписки**\n\n"
        f"💳 **Uzcard:** `{UZCARD_REQS}`\n\n"
        f"📌 **Тарифы:**\n▪️ 1 день — 30 000 UZS/200 руб\n▪️ 7 дней — 70 000 UZS/500 руб\n▪️ 30 дней — 150 000 UZS/1000 руб\n\n"
        f"📸 **После оплаты просто отправьте скриншот чека в этот чат.**"
    )
    try:
        if hasattr(query_or_update, "edit_message_text"):
            await query_or_update.edit_message_text(text, parse_mode='Markdown', reply_markup=back_menu())
        else:
            await query_or_update.message.reply_text(text, parse_mode='Markdown', reply_markup=back_menu())
    except TelegramError:
        pass


async def handle_payment_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username
    tag = f"@{html.escape(username)}" if username else f"ID <code>{user_id}</code>"

    if ADMIN_ID != 0:
        try:
            await context.bot.send_photo(
                chat_id=ADMIN_ID,
                photo=update.message.photo[-1].file_id,
                caption=f"📥 <b>Новый чек!</b>\nОт: {tag}\nUser ID: <code>{user_id}</code>",
                parse_mode='HTML',
                reply_markup=admin_confirm_keyboard(user_id)
            )
            user = await get_user(user_id)
            await update.message.reply_text("✅ Чек отправлен администратору!",
                                            reply_markup=main_menu(user["selected_mode"]))
        except Exception as e:
            logger.error(f"Ошибка чека: {e}")


async def grant_subscription(context: ContextTypes.DEFAULT_TYPE, user_id: int, days: int):
    user = await get_user(user_id)
    now = datetime.now()
    if user.get("subscription_until"):
        try:
            curr = datetime.fromisoformat(user["subscription_until"])
            if curr > now: now = curr
        except ValueError:
            pass

    until = (now + timedelta(days=days)).isoformat()
    await update_user(user_id, subscription_until=until)

    try:
        await context.bot.send_message(user_id, f"🎉 **Подписка активирована до {until.split('T')[0]}!**",
                                       parse_mode='Markdown')
    except TelegramError:
        pass


def main():
    if not BOT_TOKEN: return

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(init_db())

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, handle_payment_screenshot))
    app.add_handler(
        MessageHandler((filters.Chat(SOURCE_CHAT_ID) & filters.TEXT) | filters.UpdateType.EDITED_CHANNEL_POST,
                       handle_game))

    logger.info("🚀 Бот обновлен и готов к работе!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
