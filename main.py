import asyncio
import os
import sqlite3
import json
import httpx
import io
import pytesseract
from PIL import Image
from contextlib import closing
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, WebAppInfo, ReplyKeyboardMarkup, KeyboardButton
)

# --- НАСТРОЙКИ ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
ZVENO_API_KEY = os.getenv("ZVENO_API_KEY")
DB_PATH = os.getenv("DB_PATH", "bot.db")
WEBAPP_URL = "https://deimosept-dev.github.io/Voice_bot/"
ADMIN_ID = 1636139244 

# Текстовая модель (для анализа данных)
MODEL_NAME = "nvidia/nemotron-3-ultra-550b-a55b:free"

# --- БАЗА ДАННЫХ И СТАТИСТИКА ---
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

# --- ХЕНДЛЕРЫ БОТА ---
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
            await message.answer("✅ Отлично! Теперь отправь скриншоты прямо сюда в чат.")
    except Exception as e:
        print("WebApp error:", e)

@dp.message(F.photo)
async def handle_photo(message: Message):
    log_action(message.from_user.id, "photo_uploaded")
    status_msg = await message.answer("📊 Анализирую данные аккаунта...")

    try:
        # Скачиваем фото
        file_info = await message.bot.get_file(message.photo[-1].file_id)
        downloaded_file = await message.bot.download_file(file_info.file_path)

        # Читаем текст с картинки локально (OCR)
        image = Image.open(io.BytesIO(downloaded_file.read()))
        extracted_text = pytesseract.image_to_string(image, lang='rus+eng')

        if len(extracted_text.strip()) < 10:
            raise Exception("Не удалось разглядеть текст. Сделай скриншот почётче.")

        await status_msg.edit_text("💰 Формирую оценку стоимости...")

        # Промпт для профессионального ответа
        prompt = (
            f"Ты — профессиональный оценщик аккаунтов Mobile Legends с большим опытом. "
            f"Твоя задача — сделать быструю и четкую оценку на основе распознанного текста со скринов.\n\n"
            f"Текст со скринов:\n{extracted_text}\n\n"
            f"ПРАВИЛА ОТВЕТА:\n"
            f"1. Пиши как опытный человек, а не как робот. Используй деловой, но живой стиль. Без лишних вступлений.\n"
            f"2. Используй HTML-теги для оформления: <b>жирный</b> для заголовков и цифр. НЕ ИСПОЛЬЗУЙ символы *, **, # или слэши.\n"
            f"3. Кратко перечисли найденные параметры (ранг, винрейт, кол-во матчей, скины, если есть).\n"
            f"4. Если каких-то данных нет (например, не загружен скрин со скинами), просто напиши 'Данные по скинам не предоставлены'.\n"
            f"5. В конце четко выдели итоговую стоимость: <b>Примерная стоимость: XXXX рублей</b>.\n"
            f"6. Добавь один короткий совет по продаже аккаунта."
        )
        
        headers = {"Authorization": f"Bearer {ZVENO_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": MODEL_NAME,
            "messages": [{"role": "user", "content": prompt}]
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post("https://api.zveno.ai/v1/chat/completions", headers=headers, json=payload)
            
            if response.status_code != 200:
                raise Exception(f"API Error {response.status_code}: {response.text}")

            answer = response.json()["choices"][0]["message"]["content"]

        # Отправляем с HTML-форматированием
        await message.answer(answer, parse_mode="HTML")
        await status_msg.delete()

    except Exception as e:
        error_text = str(e)
        await status_msg.edit_text(f"❌ Ошибка:\n{error_text[:300]}")
        print("Error:", repr(e))

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    with closing(db()) as conn:
        total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_starts = conn.execute("SELECT COUNT(*) FROM stats WHERE action='start'").fetchone()[0]
        total_photos = conn.execute("SELECT COUNT(*) FROM stats WHERE action='photo_uploaded'").fetchone()[0]
    await message.answer(
        f"📊 <b>Статистика:</b>\n\n"
        f"👥 Пользователей: {total_users}\n"
        f"🚀 Запустили бота: {total_starts}\n"
        f"📸 Загрузили фото на оценку: {total_photos}",
        parse_mode="HTML"
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
