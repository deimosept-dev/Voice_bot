import asyncio
import os
import sqlite3
import httpx
from contextlib import closing

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message

BOT_TOKEN = os.getenv("BOT_TOKEN")
ZVENO_API_KEY = os.getenv("ZVENO_API_KEY")
DB_PATH = os.getenv("DB_PATH", "bot.db")

# Бесплатная модель ZvenoAI
MODEL_NAME = "cohere/north-mini-code:free"

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
    import datetime
    today = datetime.date.today().isoformat()
    with closing(db()) as conn:
        conn.execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)", (user_id,))
        conn.commit()
        row = conn.execute("SELECT requests_today, last_request_date FROM users WHERE user_id=?", (user_id,)).fetchone()
        if row["last_request_date"] != today:
            conn.execute("UPDATE users SET requests_today=0, last_request_date=? WHERE user_id=?", (today, user_id))
            conn.commit()
            return True
        return row["requests_today"] < 3 # 3 бесплатных решения в день

def add_request(user_id):
    with closing(db()) as conn:
        conn.execute("UPDATE users SET requests_today = requests_today + 1 WHERE user_id=?", (user_id,))
        conn.commit()

dp = Dispatcher()

@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "👋 Привет! Я твой умный помощник по домашке.\n\n"
        "📝 Отправь мне текст задачи, и я решу её по шагам!\n"
        "🎁 Доступно 3 бесплатных решения в день."
    )

@dp.message(F.text)
async def handle_homework(message: Message):
    text = message.text.strip()
    if text.startswith("/"):
        return
    if not can_solve(message.from_user.id):
        await message.answer("😔 Лимит на сегодня исчерпан. Возвращайся завтра!")
        return

    status_msg = await message.answer("🧠 Думаю над решением...")

    headers = {
        "Authorization": f"Bearer {ZVENO_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": "Ты — школьный помощник. Решай задачи по шагам, объясняя простым языком."},
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
        response.raise_for_status()
        answer = response.json()["choices"][0]["message"]["content"]

        if len(answer) > 4000:
            for i in range(0, len(answer), 4000):
                await message.answer(answer[i:i+4000])
        else:
            await message.answer(answer)

        add_request(message.from_user.id)
        await status_msg.delete()

    except Exception as e:
        print("AI error:", repr(e))
        await status_msg.edit_text("❌ Ошибка при решении. Проверь ключ или попробуй позже.")

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
