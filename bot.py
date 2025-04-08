import os
import logging
import requests
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.ext import ApplicationBuilder

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
VK_TOKEN = os.getenv("VK_GROUP_TOKEN")
VK_GROUP_ID = -229574072
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = os.getenv("WEBHOOK_URL") + WEBHOOK_PATH

app = FastAPI()
application: Application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bot")

# Хендлеры
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("▶ Получена команда /start")
    await update.message.reply_text("Привет! Я бот-помощник Etronics 🚀")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("/start — запуск\n/help — помощь\n/post <текст> — пост в ВК")

async def post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Укажи текст поста после /post")
        return

    message = ' '.join(context.args)
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
        await update.message.reply_text("✅ Пост опубликован в ВКонтакте!")
    else:
        error = response.get("error", {}).get("error_msg", "Ошибка")
        await update.message.reply_text(f"❌ Ошибка при публикации: {error}")

application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("help", help_command))
application.add_handler(CommandHandler("post", post))

@app.on_event("startup")
async def startup():
    await application.initialize()
    await application.bot.delete_webhook(drop_pending_updates=True)
    await application.bot.set_webhook(url=WEBHOOK_URL)
    logger.info(f"✅ Webhook установлен: {WEBHOOK_URL}")

@app.post(WEBHOOK_PATH)
async def process_webhook(request: Request):
    try:
        raw_data = await request.body()
        logger.info(f"📩 Сырое тело запроса: {raw_data}")
        json_data = await request.json()
        update = Update.de_json(json_data, application.bot)
        await application.process_update(update)
        logger.info("✅ Обновление обработано")
        return {"ok": True}
    except Exception as e:
        logger.error(f"❌ Ошибка обработки webhook: {e}")
        return {"error": str(e)}