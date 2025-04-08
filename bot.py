import os
import logging
import requests
from fastapi import FastAPI, Request
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

# Токены и конфиг
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
VK_TOKEN = os.getenv("VK_GROUP_TOKEN")
VK_GROUP_ID = -229574072
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = os.getenv("WEBHOOK_URL") + WEBHOOK_PATH

# FastAPI + Telegram
app = FastAPI()
application: Application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bot")

# Память сообщений пользователя
user_drafts = {}

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["📤 Пост в ВК", "ℹ️ Помощь"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        "Привет! Я бот-помощник Etronics 🚀\n\nВыбери действие ниже:",
        reply_markup=reply_markup
    )

# Команда /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start — запуск\n/help — помощь\n/post <текст> — пост в ВК\n\n"
        "Или воспользуйся кнопками ⬇️"
    )

# Классическая команда /post
async def post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Укажи текст поста после /post")
        return

    message = ' '.join(context.args)
    await confirm_post(update, context, message)

# Обработка reply-кнопок
async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == "ℹ️ Помощь":
        await help_command(update, context)

    elif text == "📤 Пост в ВК":
        await update.message.reply_text("Напиши текст поста, и я предложу его опубликовать 👇")
        context.user_data["waiting_for_post"] = True

# Получаем текст поста вручную
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("waiting_for_post"):
        context.user_data["waiting_for_post"] = False
        user_drafts[update.effective_user.id] = update.message.text
        await confirm_post(update, context, update.message.text)

# Подтверждение перед публикацией
async def confirm_post(update: Update, context: ContextTypes.DEFAULT_TYPE, message: str):
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_post"),
            InlineKeyboardButton("❌ Отмена", callback_data="cancel_post"),
        ]
    ])
    await update.message.reply_text(
        f"Вот текст поста:\n\n{message}\n\nОпубликовать в ВК?",
        reply_markup=keyboard
    )

# Обработка инлайн-кнопок
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    message = user_drafts.get(user_id)

    if query.data == "confirm_post":
        if not message:
            await query.edit_message_text("❌ Ошибка: пост не найден.")
            return

        logger.info(f"📬 Публикуем пост: {message}")
        url = "https://api.vk.com/method/wall.post"
        params = {
            "access_token": VK_TOKEN,
            "v": "5.131",
            "owner_id": VK_GROUP_ID,
            "from_group": 1,
            "message": message
        }
        response = requests.post(url, params=params).json()

        if "response" in response:
            await query.edit_message_text("✅ Пост опубликован в ВКонтакте!")
        else:
            error = response.get("error", {}).get("error_msg", "Ошибка")
            await query.edit_message_text(f"❌ Ошибка при публикации: {error}")

        user_drafts.pop(user_id, None)

    elif query.data == "cancel_post":
        await query.edit_message_text("🚫 Публикация отменена.")
        user_drafts.pop(user_id, None)

# Хендлеры
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("help", help_command))
application.add_handler(CommandHandler("post", post))
application.add_handler(MessageHandler(filters.Regex("^(📤 Пост в ВК|ℹ️ Помощь)$"), handle_buttons))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
application.add_handler(CallbackQueryHandler(handle_callback))

# Webhook init
@app.on_event("startup")
async def startup():
    await application.initialize()
    await application.bot.delete_webhook(drop_pending_updates=True)
    await application.bot.set_webhook(url=WEBHOOK_URL)
    logger.info(f"✅ Webhook установлен: {WEBHOOK_URL}")

# Webhook endpoint
@app.post(WEBHOOK_PATH)
async def process_webhook(request: Request):
    try:
        raw_data = await request.body()
        json_data = await request.json()
        update = Update.de_json(json_data, application.bot)
        await application.process_update(update)
        logger.info("✅ Обновление обработано")
        return {"ok": True}
    except Exception as e:
        logger.error(f"❌ Ошибка обработки webhook: {e}")
        return {"error": str(e)}
