import asyncio
import os
import sqlite3
import json
import base64
import httpx
from contextlib import closing
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, WebAppInfo, ReplyKeyboardMarkup, KeyboardButton
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ZVENO_API_KEY = os.getenv("ZVENO_API_KEY")
DB_PATH = os.getenv("DB_PATH", "bot.db")
WEBAPP_URL = "https://deimosept-dev.github.io/Voice_bot/"

# Твой ID
ADMIN_ID = 1636139244 

# Модель для распознавания картинок
MODEL_NAME = "nvidia/nemotron-3.5-super-vl:free"

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with closing(db()) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                action TEXT,
                created_at TEXT
            )
        """)
        conn.commit()

def log_action(user_id, action):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with closing(db()) as conn:
        conn.execute("INSERT INTO users(user_id) VALUES(?) ON CONFLICT DO NOTHING", (user_id,))
        conn.execute("INSERT INTO stats(user_id, action, created_at) VALUES(?, ?, ?)", (user_id, action, now))
        conn.commit()

dp = Dispatcher()

@dp.message(CommandStart())
async def cmd_start(message: Message):
    log_action(message.from_user.id, "start")
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🚀 Открыть калькулятор", web_app=WebAppInfo(url=WEBAPP_URL))]],
        resize_keyboard=True
    )
    await message.answer(
        "👋 Привет! Нажми на кнопку внизу, чтобы открыть калькулятор.\n\n"
        "После того как выберешь фото в приложении, **пришли их сюда в чат**, и я оценю аккаунт.",
        reply_markup=kb
    )

@dp.message(F.web_app_data)
async def handle_webapp(message: Message):
    try:
        data = json.loads(message.web_app_data.data)
        if data.get("action") == "calculate":
            await message.answer("✅ Отлично! Теперь отправь скриншоты прямо сюда в чат (можно альбомом).")
    except Exception as e:
        print("WebApp error:", e)

# --- ОБРАБОТКА ФОТО И ОЦЕНКА ---
@dp.message(F.photo)
async def handle_photo(message: Message):
    log_action(message.from_user.id, "photo_uploaded")
    status_msg = await message.answer("🔍 Распознаю данные с экрана... Это займет около 15 секунд.")

    try:
        # Скачиваем фото
        file_info = await message.bot.get_file(message.photo[-1].file_id)
        downloaded_file = await message.bot.download_file(file_info.file_path)
        image_b64 = base64.b64encode(downloaded_file.read()).decode('utf-8')

        # Запрос к нейросети (Vision)
        prompt = (
            "Ты — профессиональный оценщик аккаунтов Mobile Legends. "
            "Посмотри на скриншот и вытащи данные: Максимальный ранг (например, Mythical Glory), "
            "Количество матчей, Процент побед (винрейт), Количество скинов (если видно). "
            "Затем рассчитай примерную стоимость аккаунта в рублях по формуле: "
            "Mythical Glory = +5750 руб, Immortal = +11500 руб. Каждый Supreme скин = +400 руб. "
            "Выдай ответ красиво: что ты нашел на скрине, и итоговую цену."
        )
        
        headers = {"Authorization": f"Bearer {ZVENO_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": MODEL_NAME,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}}
                ]
            }]
        }

        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post("https://api.zveno.ai/v1/chat/completions", headers=headers, json=payload)
            response.raise_for_status()
            answer = response.json()["choices"][0]["message"]["content"]

        await message.answer(answer)
        await status_msg.delete()

    except Exception as e:
        print("AI error:", repr(e))
        await status_msg.edit_text("❌ Не удалось распознать фото. Попробуй сделать скриншот более четким.")

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    with closing(db()) as conn:
        total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_starts = conn.execute("SELECT COUNT(*) FROM stats WHERE action='start'").fetchone()[0]
        total_photos = conn.execute("SELECT COUNT(*) FROM stats WHERE action='photo_uploaded'").fetchone()[0]
    await message.answer(
        f"📊 **Статистика:**\n\n"
        f"👥 Пользователей: {total_users}\n"
        f"🚀 Запустили бота: {total_starts}\n"
        f"📸 Загрузили фото на оценку: {total_photos}"
    )

async def main():
    if not BOT_TOKEN or not ZVENO_API_KEY:
        return
    init_db()
    bot = Bot(BOT_TOKEN)
    print("🚀 Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
