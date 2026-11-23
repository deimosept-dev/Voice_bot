import asyncio
import os
import sqlite3
import json
from contextlib import closing
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_PATH = os.getenv("DB_PATH", "bot.db")
WEBAPP_URL = "https://deimosept-dev.github.io/Voice_bot/"

# Твой ID вписан сюда
ADMIN_ID = 1636139244 

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
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Открыть калькулятор", web_app=WebAppInfo(url=WEBAPP_URL))]
    ])
    
    await message.answer(
        "👋 Привет! Это автоматический оценщик аккаунтов Mobile Legends.\n\n"
        "Загрузи скриншоты своего профиля, и я посчитаю, за сколько его можно продать.",
        reply_markup=kb
    )

@dp.message(F.web_app_data)
async def handle_webapp(message: Message):
    try:
        data = json.loads(message.web_app_data.data)
        if data.get("action") == "calculate":
            files_count = data.get("files_count", 0)
            log_action(message.from_user.id, f"calculate_click_{files_count}")
            
            await message.answer(
                f"✅ Ты загрузил {files_count} фото в калькулятор!\n\n"
                "**Отправь эти фотографии прямо сюда в чат** (можно альбомом).\n"
                "Я распознаю скины, ранг и винрейт, а затем пришлю итоговую стоимость."
            )
    except Exception as e:
        print("WebApp error:", e)

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
        
    with closing(db()) as conn:
        total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_starts = conn.execute("SELECT COUNT(*) FROM stats WHERE action='start'").fetchone()[0]
        total_calcs = conn.execute("SELECT COUNT(*) FROM stats WHERE action LIKE 'calculate%'").fetchone()[0]
        
    await message.answer(
        f"📊 **Статистика бота:**\n\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"🚀 Запустили бота: {total_starts}\n"
        f"💰 Нажали 'Рассчитать': {total_calcs}"
    )

async def main():
    if not BOT_TOKEN:
        return
    init_db()
    bot = Bot(BOT_TOKEN)
    print("🚀 Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
