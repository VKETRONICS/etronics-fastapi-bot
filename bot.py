import os
import logging
import requests
import openai
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

# Конфигурация
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
VK_TOKEN = os.getenv("VK_GROUP_TOKEN")
VK_GROUP_ID = -229574072  # ID группы ВКонтакте
WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = os.getenv("WEBHOOK_URL") + WEBHOOK_PATH
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

openai.api_key = OPENAI_API_KEY

app = FastAPI()
application: Application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bot")

# Обработчик ошибок
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Произошла ошибка: {context.error}")
    if update:
        await update.message.reply_text("Произошла ошибка, попробуйте снова позже.")
    else:
        logger.error("Ошибка произошла без update объекта")

# Добавляем обработчик ошибок в приложение
application.add_error_handler(error_handler)

# Команда /start с кнопками
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["✍ Сгенерировать пост", "ℹ️ Помощь"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        "Привет! Я бот-помощник Etronics 🚀\n\nВыбери действие:",
        reply_markup=reply_markup
    )

# Команда /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start — запуск\n/help — помощь\n/generate — авто-пост\n\n"
        "Или нажми кнопку ⬇️"
    )

# Генерация поста
async def generate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    query = "игровой ноутбук"  # Тема для поиска постов

    # Шаг 1 — получаем посты из ВКонтакте
    vk_posts = get_vk_posts(query)
    context.user_data["vk_source"] = vk_posts

    prompt = f"На основе этих постов сгенерируй короткий пост для ВКонтакте от магазина техники:\n\n"
    prompt += "\n\n".join(vk_posts) + "\n\nТолько один пост, 2-3 строки, живо и по делу."

    # Шаг 2 — GPT создаёт текст
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100
        )
        post_text = response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"Ошибка при генерации текста: {e}")
        await update.message.reply_text("Ошибка при генерации текста.")
        return

    # Шаг 3 — DALL·E генерирует изображение
    try:
        dalle = openai.Image.create(
            prompt="futuristic gaming laptop in cyberpunk style, vibrant lighting, 4K",
            n=1,
            size="1024x1024"
        )
        image_url = dalle['data'][0]['url']
    except Exception as e:
        logger.error(f"Ошибка при генерации изображения: {e}")
        await update.message.reply_text("Ошибка при генерации изображения.")
        return

    # Сохраняем черновик
    context.user_data["draft"] = {
        "text": post_text,
        "image_url": image_url,
    }

    # Шаг 4 — показываем пользователю
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Опубликовать", callback_data="confirm_post")],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_post")]
    ])
    await update.message.reply_photo(
        photo=image_url,
        caption=post_text,
        reply_markup=keyboard
    )

# Обработка кнопок
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    draft = context.user_data.get("draft")

    if not draft:
        await query.edit_message_caption("❌ Ошибка: черновик не найден.")
        return

    if query.data == "cancel_post":
        await query.edit_message_caption("🚫 Публикация отменена.")
        context.user_data.pop("draft", None)
        return

    if query.data == "confirm_post":
        post_text = draft["text"]
        image_url = draft["image_url"]

        photo_file = download_image(image_url)
        photo_attachment = upload_photo_to_vk(photo_file)

        if not photo_attachment:
            await query.edit_message_caption("❌ Ошибка при загрузке изображения.")
            return

        result = post_to_vk(post_text, photo_attachment)
        if result:
            await query.edit_message_caption("✅ Пост опубликован в ВКонтакте!")
        else:
            await query.edit_message_caption("❌ Не удалось опубликовать пост.")

        context.user_data.pop("draft", None)

# Загрузка изображения
def download_image(url):
    response = requests.get(url)
    file_path = "temp.jpg"
    with open(file_path, "wb") as f:
        f.write(response.content)
    return file_path

# Загрузка фото в ВК
def upload_photo_to_vk(image_path):
    upload_url = requests.get(
        "https://api.vk.com/method/photos.getWallUploadServer",
        params={
            "access_token": VK_TOKEN,
            "v": "5.131",
            "group_id": abs(VK_GROUP_ID)
        }
    ).json()["response"]["upload_url"]

    with open(image_path, 'rb') as img:
        files = {'photo': img}
        upload_response = requests.post(upload_url, files=files).json()

    save = requests.get(
        "https://api.vk.com/method/photos.saveWallPhoto",
        params={
            "access_token": VK_TOKEN,
            "v": "5.131",
            "group_id": abs(VK_GROUP_ID),
            "photo": upload_response["photo"],
            "server": upload_response["server"],
            "hash": upload_response["hash"]
        }
    ).json()

    if "response" in save:
        photo = save["response"][0]
        return f'photo{photo["owner_id"]}_{photo["id"]}'
    return None

# Публикация в ВК
def post_to_vk(text, attachment):
    url = "https://api.vk.com/method/wall.post"
    params = {
        "access_token": VK_TOKEN,
        "v": "5.131",
        "owner_id": VK_GROUP_ID,
        "from_group": 1,
        "message": text,
        "attachments": attachment
    }
    response = requests.post(url, params=params).json()
    return "response" in response

# Поиск постов в ВК
def get_vk_posts(query):
    url = "https://api.vk.com/method/newsfeed.search"
    params = {
        "access_token": VK_TOKEN,
        "v": "5.131",
        "q": query,
        "count": 5
    }
    response = requests.get(url, params=params).json()
    items = response.get("response", {}).get("items", [])
    return [item.get("text", "") for item in items if item.get("text")]

# Обработчики
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("help", help_command))
application.add_handler(CommandHandler("generate", generate))
application.add_handler(MessageHandler(filters.Regex("^✍ Сгенерировать пост$"), generate))
application.add_handler(CallbackQueryHandler(handle_callback))

# Webhook
@app.on_event("startup")
async def startup():
    await application.initialize()
    await application.bot.delete_webhook(drop_pending_updates=True)
    await application.bot.set_webhook(url=WEBHOOK_URL)
    logger.info(f"✅ Webhook установлен: {WEBHOOK_URL}")

@app.post(WEBHOOK_PATH)
async def process_webhook(request: Request):
    try:
        json_data = await request.json()
        update = Update.de_json(json_data, application.bot)
        await application.process_update(update)
        return {"ok": True}
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return {"error": str(e)}
