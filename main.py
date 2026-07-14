from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = "8994861475:AAFN9URlfzej_PLldHyGKONmH-1F85TMNRc"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❤️ Привет, Ирина Андреевна.\n\n"
        "Ты уже прошла первый шаг. Теперь второй — наши тёплые воспоминания.\n"
        "Отвечай правильно, чтобы дойти до финала ❤️",
        parse_mode='HTML'
    )
    await ask_question1(update, context)

async def ask_question1(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["Вкусно и точка", "Макдоналдс", "KFC", "Бургер Кинг"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text("<b>Вопрос 1:</b>\nТвой самый любимый фастфуд?", 
                                    reply_markup=reply_markup, parse_mode='HTML')

async def ask_question2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["Наггетсы", "Чизбургер", "Картошка фри", "Крылышки"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text("<b>Вопрос 2:</b>\nЧто ты особенно любишь заказывать во «Вкусно и точка»?", 
                                    reply_markup=reply_markup, parse_mode='HTML')

async def ask_question3(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["Гляссе", "Кола", "Капучино", "Чай"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text("<b>Вопрос 3:</b>\nКакой напиток ты чаще всего брала?", 
                                    reply_markup=reply_markup, parse_mode='HTML')

async def ask_question4(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["Тирамису", "Чизкейк", "Мороженое", "Маффин"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text("<b>Вопрос 4:</b>\nКакой твой самый любимый десерт?", 
                                    reply_markup=reply_markup, parse_mode='HTML')

async def ask_question5(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["Твой кот", "Собака", "Попугай", "Рыбки"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text("<b>Вопрос 5:</b>\nКого ты любишь сильнее всего на свете?", 
                                    reply_markup=reply_markup, parse_mode='HTML')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    current = context.user_data.get('question', 1)

    if current == 1:
        if "вкусно и точка" in text:
            context.user_data['question'] = 2
            await ask_question2(update, context)
        else:
            await update.message.reply_text("Не совсем... Попробуй ещё раз ❤️")

    elif current == 2:
        if "наггетсы" in text:
            context.user_data['question'] = 3
            await ask_question3(update, context)
        else:
            await update.message.reply_text("Не этот вариант... Вспомни наши заказы ❤️")

    elif current == 3:
        if "гляссе" in text or "глясе" in text:
            context.user_data['question'] = 4
            await ask_question4(update, context)
        else:
            await update.message.reply_text("Не этот напиток... Попробуй ещё раз ❤️")

    elif current == 4:
        if "тирамису" in text:
            context.user_data['question'] = 5
            await ask_question5(update, context)
        else:
            await update.message.reply_text("Не этот десерт... Попробуй ещё раз ❤️")

    elif current == 5:
        if "кот" in text or "твой кот" in text:
            await update.message.reply_text(
                "❤️ Правильно! Ты знаешь, как сильно ты любишь своего кота.\n\n"
                "Ты прошла все вопросы. Я очень тобой горжусь.\n\n"
                "Теперь последний шаг — я жду тебя здесь со всей нашей историей:\n\n"
                "🔗 https://kudrathov.github.io/memory-for-irina\n\n"
                "Открывай... там очень много любви от меня ❤️"
            )
            context.user_data.clear()
        else:
            await update.message.reply_text("Не совсем... Кого ты любишь больше всех? ❤️")

async def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("Бот запущен...")
    await app.run_polling()

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
