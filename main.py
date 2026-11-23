import asyncio
import os
import sqlite3
import httpx
import base64
from contextlib import closing
from datetime import date

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message

BOT_TOKEN = os.getenv("BOT_TOKEN")
ZVENO_API_KEY = os.getenv("ZVENO_API_KEY")
DB_PATH = os.getenv("DB_PATH", "bot.db")

# Модель, которая умеет распознавать картинки (VL - Vision Language)
MODEL_NAME = "nvidia/nemotron-3.5-super-vl:free"

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with closing(db()) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                requests_today INTEGER DEFAULT 0,
                last_request_date TEXT DEFAULT ''
            )
        """)
        conn.commit()

def can_solve(user_id):
    today = date.today().isoformat()
    with closing(db()) as conn:
        conn.execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)", (user_id,))
        conn.commit()
        row = conn.execute("SELECT requests_today, last_request_date FROM users WHERE user_id=?", (user_id,)).fetchone()
        
        if row["last_request_date"] != today:
            conn.execute("UPDATE users SET requests_today=0, last_request_date=? WHERE user_id=?", (today, user_id))
            conn.commit()
            return True
        return row["requests_today"] < 5

def add_request(user_id):
    with closing(db()) as conn:
        conn.execute("UPDATE users SET requests_today = requests_today + 1 WHERE user_id=?", (user_id,))
        conn.commit()

def get_remaining(user_id):
    today = date.today().isoformat()
    with closing(db()) as conn:
        row = conn.execute("SELECT requests_today, last_request_date FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not row or row["last_request_date"] != today:
            return 5
        return max(0, 5 - row["requests_today"])

dp = Dispatcher()

@dp.message(CommandStart())
async def cmd_start(message: Message):
    remaining = get_remaining(message.from_user.id)
    await message.answer(
        "👋 Привет! Я твой умный помощник по домашке.\n\n"
        "📝 Отправь мне текст задачи или **фотографию** задания, и я решу её по шагам!\n\n"
        f"🎁 У тебя осталось {remaining} из 5 бесплатных решений на сегодня."
    )

# Функция для отправки запроса к нейросети
async def ask_ai(message: Message, text_prompt: str, image_b64: str = None):
    if not can_solve(message.from_user.id):
        await message.answer("😔 На сегодня лимит (5 решений) исчерпан. Возвращайся завтра!")
        return

    status_msg = await message.answer("🧠 Думаю над решением... Это займет пару секунд.")

    headers = {
        "Authorization": f"Bearer {ZVENO_API_KEY}",
        "Content-Type": "application/json"
    }
    
    # Формируем сообщение для нейросети
    user_content = []
    if text_prompt:
        user_content.append({"type": "text", "text": text_prompt})
    if image_b64:
        user_content.append({
            "type": "image_url", 
            "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}
        })

    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": "Ты — школьный помощник. Решай задачи по шагам, объясняя простым языком. Если на фото несколько задач, реши первую."},
            {"role": "user", "content": user_content}
        ]
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.zveno.ai/v1/chat/completions",
                headers=headers,
                json=payload
            )
        
        if response.status_code != 200:
            raise Exception(f"Код {response.status_code}: {response.text}")

        result = response.json()
        answer = result["choices"][0]["message"]["content"]

        if len(answer) > 4000:
            for i in range(0, len(answer), 4000):
                await message.answer(answer[i:i+4000])
        else:
            await message.answer(answer)

        add_request(message.from_user.id)
        remaining = get_remaining(message.from_user.id)
        await message.answer(f"📊 Осталось решений на сегодня: {remaining}/5")
        await status_msg.delete()

    except Exception as e:
        error_text = str(e)
        await status_msg.edit_text(f"❌ Ошибка API:\n{error_text[:400]}")
        print("AI error:", repr(e))


# Обработка текстовых задач
@dp.message(F.text)
async def handle_text(message: Message):
    text = message.text.strip()
    if text.startswith("/"):
        return
    await ask_ai(message, text_prompt=text)

# Обработка фотографий с задачами
@dp.message(F.photo)
async def handle_photo(message: Message):
    await message.answer("📸 Фото получено! Распознаю текст и решаю...")
    
    # Скачиваем фото в максимальном качестве
    file_info = await message.bot.get_file(message.photo[-1].file_id)
    downloaded_file = await message.bot.download_file(file_info.file_path)
    
    # Переводим картинку в формат base64
    image_b64 = base64.b64encode(downloaded_file.read()).decode('utf-8')
    
    # Отправляем в нейросеть
    await ask_ai(message, text_prompt="Реши задачу на этом фото.", image_b64=image_b64)

async def main():
    if not BOT_TOKEN or not ZVENO_API_KEY:
        return
    init_db()
    bot = Bot(BOT_TOKEN)
    print("🚀 Бот-помощник (с распознаванием фото) запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
