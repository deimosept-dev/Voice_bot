import asyncio
import os
import sqlite3
import json
from contextlib import closing
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, WebAppInfo, ReplyKeyboardMarkup, KeyboardButton
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_PATH = os.getenv("DB_PATH", "bot.db")
WEBAPP_URL = "https://deimosept-dev.github.io/Voice_bot/"
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
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🚀 Открыть калькулятор", web_app=WebAppInfo(url=WEBAPP_URL))]],
        resize_keyboard=True
    )
    await message.answer(
        "👋 Привет! Нажми на кнопку внизу, чтобы открыть калькулятор.\n\n"
        "Введи свои данные, и я рассчитаю точную стоимость аккаунта.",
        reply_markup=kb
    )

@dp.message(F.web_app_data)
async def handle_webapp(message: Message):
    try:
        payload = json.loads(message.web_app_data.data)
        if payload.get("action") == "calculate_manual":
            d = payload["data"]
            
            # --- МАТЕМАТИКА ---
            base = 1500 # База
            bonuses = 0
            details = []

            # 1. Ранг
            if d["rank"] == "immortal":
                bonuses += 11500
                details.append("• Ранг: <b>Immortal</b> (+11 500 ₽)")
            elif d["rank"] == "glory":
                bonuses += 5750
                details.append("• Ранг: <b>Mythical Glory</b> (+5 750 ₽)")

            # 2. Винрейт (если больше 60% и матчей больше 1000)
            if d["winrate"] >= 60 and d["matches"] >= 1000:
                wr_bonus = int((d["winrate"] - 60) * 300) # Примерно 300 руб за 1%
                bonuses += wr_bonus
                details.append(f"• Винрейт: {d['winrate']}% (+{wr_bonus} ₽)")

            # 3. Скины
            skins = d["skins"]
            skin_prices = {
                "supreme": (410, "Легендарные"),
                "grand": (307, "Гранд"),
                "exquisite": (205, "Изысканные"),
                "deluxe": (41, "Роскошные"),
                "exceptional": (20, "Исключительные"),
                "common": (10, "Обычные")
            }

            for key, (price, name) in skin_prices.items():
                count = skins.get(key, 0)
                if count > 0:
                    total = count * price
                    bonuses += total
                    details.append(f"• {name}: {count} шт. (+{total} ₽)")

            total_price = base + bonuses
            
            # Если совсем ничего нет
            if not details:
                details.append("• Базовый аккаунт без выдающихся заслуг.")

            details_text = "\n".join(details)
            
            answer = (
                f"<b>📊 Оценка аккаунта готова!</b>\n\n"
                f"{details_text}\n\n"
                f"<b>💰 Итоговая стоимость: {total_price} рублей</b>\n\n"
                f"<i>Совет: Чтобы продать быстрее, выставьте цену на 10-15% ниже оценки.</i>"
            )
            
            await message.answer(answer, parse_mode="HTML")
            log_action(message.from_user.id, "calculated_manual")

    except Exception as e:
        print("WebApp error:", e)
        await message.answer("❌ Ошибка при расчете. Попробуй еще раз.")

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    with closing(db()) as conn:
        total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_calcs = conn.execute("SELECT COUNT(*) FROM stats WHERE action='calculated_manual'").fetchone()[0]
    await message.answer(
        f"📊 <b>Статистика:</b>\n\n"
        f"👥 Пользователей: {total_users}\n"
        f"💰 Сделали расчет: {total_calcs}",
        parse_mode="HTML"
    )

async def main():
    if not BOT_TOKEN:
        return
    init_db()
    bot = Bot(BOT_TOKEN)
    print("🚀 Бот-калькулятор запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
