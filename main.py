import asyncio
import os
import sqlite3
import httpx
from contextlib import closing
from datetime import date

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message

BOT_TOKEN = os.getenv("BOT_TOKEN")
ZVENO_API_KEY = os.getenv("ZVENO_API_KEY")
DB_PATH = os.getenv("DB_PATH", "bot.db")

# Бесплатная модель ZvenoAI (Llama 3.3 70B - очень умная)
MODEL_NAME = "meta-llama/llama-3.3-70b-instruct:free"

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
            
        return row["requests_today"] < 5 # Изменили на 5 задач в день

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
        "📝 Отправь мне текст задачи (математика, физика, химия, сочинения), и я решу её по шагам!\n\n"
        f"🎁 У тебя осталось {remaining} из 5 бесплатных решений на сегодня."
    )

@dp.message(F.text)
async def handle_homework(message: Message):
    text = message.text.strip()
    if text.startswith("/"):
        return

    if not can_solve(message.from_user.id):
        await message.answer("😔 На сегодня лимит (5 решений) исчерпан. Возвращайся завтра!")
        return

    status_msg = await message.answer("🧠 Думаю над решением... Это займет пару секунд.")

    headers = {
        "Authorization": f"Bearer {ZVENO_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": "Ты — школьный помощник. Решай задачи по шагам, объясняя простым языком, чтобы школьник понял."},
            {"role": "user", "content": text}
        ]
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://api.zveno.ai/v1/chat/completions",
                headers=headers,
                json=payload
            )
        
        # Если API вернул ошибку, мы покажем её прямо в телеграме
        if response.status_code != 200:
            error_details = response.text
            raise Exception(f"Код {response.status_code}: {error_details}")

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
        # Выводим ошибку прямо в чат, чтобы мы сразу поняли причину
        error_text = str(e)
        await status_msg.edit_text(f"❌ Ошибка API:\n{error_text[:400]}")
        print("AI error:", repr(e))

async def main():
    if not BOT_TOKEN or not ZVENO_API_KEY:
        print("❌ ОШИБКА: Не заданы BOT_TOKEN или ZVENO_API_KEY!")
        return
    init_db()
    bot = Bot(BOT_TOKEN)
    print("🚀 Бот-помощник (ZvenoAI) запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
