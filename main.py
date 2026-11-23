import asyncio
import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup, WebAppInfo

BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_PATH = os.getenv("DB_PATH", "bot.db")
WEBAPP_URL = "https://deimosept-dev.github.io/Voice_bot/"
ADMIN_ID = int(os.getenv("ADMIN_ID", "1636139244"))

# Базовая цена аккаунта и стоимость за 1 000 очков коллекции (в рублях)
BASE_PRICE = 1500
PRICE_PER_1000_PTS = 102.44


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


def _num(val, default=0.0):
    try:
        return float(val) if val is not None else default
    except (TypeError, ValueError):
        return default


dp = Dispatcher()


@dp.message(CommandStart())
async def cmd_start(message: Message):
    if message.from_user:
        log_action(message.from_user.id, "start")
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🚀 Открыть калькулятор", web_app=WebAppInfo(url=WEBAPP_URL))]],
        resize_keyboard=True,
    )
    await message.answer(
        "👋 Привет! Нажми на кнопку внизу, чтобы открыть калькулятор.\n\n"
        "Введи свои данные, и я рассчитаю стоимость аккаунта.",
        reply_markup=kb,
    )


@dp.message(F.web_app_data)
async def handle_webapp(message: Message):
    try:
        payload = json.loads(message.web_app_data.data)
        if not isinstance(payload, dict) or payload.get("action") != "calculate_manual":
            return

        d = payload.get("data") if isinstance(payload.get("data"), dict) else {}

        bonuses = 0
        details = []

        rank = d.get("rank")
        if rank == "immortal":
            bonuses += 11500
            details.append("• Ранг: <b>Immortal</b> (+11 500 ₽)")
        elif rank == "glory":
            bonuses += 5750
            details.append("• Ранг: <b>Mythical Glory</b> (+5 750 ₽)")

        winrate = max(0.0, min(100.0, _num(d.get("winrate"), 0.0)))
        matches = max(0, int(_num(d.get("matches"), 0)))
        if winrate >= 60 and matches >= 1000 and winrate > 60:
            wr_bonus = int((winrate - 60) * 300)
            if wr_bonus > 0:
                bonuses += wr_bonus
                details.append(f"• Винрейт: {winrate:g}% (+{wr_bonus} ₽)")

        collection_points = max(0, int(_num(d.get("collection_points"), 0)))
        if collection_points > 0:
            collection_price = round((collection_points / 1000) * PRICE_PER_1000_PTS)
            bonuses += collection_price
            details.append(f"• Очки коллекции: {collection_points} pts (+{collection_price} ₽)")

        skins = d.get("skins") if isinstance(d.get("skins"), dict) else {}
        skin_names = {
            "legendary": "Легендарные",
            "exquisite_grace": "Изящные",
            "exquisite": "Изысканные",
            "deluxe": "Роскошные",
            "exceptional": "Исключительные",
            "common": "Обычные",
            "painted": "Окраски для обликов",
            "grand_appearance": "Великолепный облик",
        }
        chosen_skins = []
        for key, label in skin_names.items():
            cnt = max(0, int(_num(skins.get(key), 0)))
            if cnt > 0:
                chosen_skins.append(f"{label}: {cnt}")
        if chosen_skins:
            details.append("• Облики: " + ", ".join(chosen_skins))

        total_price = BASE_PRICE + bonuses

        if not details:
            details.append("• Базовый аккаунт без выдающихся заслуг.")

        details_text = "\n".join(details)

        answer = (
            f"<b>📊 Оценка аккаунта готова!</b>\n\n"
            f"• Базовая цена: {BASE_PRICE} ₽\n"
            f"{details_text}\n\n"
            f"<b>💰 Итоговая стоимость: {total_price} рублей</b>\n\n"
            f"<i>Совет: Чтобы продать быстрее, выставьте цену на 10-15% ниже оценки.</i>"
        )

        await message.answer(answer, parse_mode="HTML")
        if message.from_user:
            log_action(message.from_user.id, "calculated_manual")

    except Exception as e:
        print("WebApp error:", e)
        await message.answer("❌ Ошибка при расчете. Попробуй еще раз.")


@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if not message.from_user or message.from_user.id != ADMIN_ID:
        return
    with closing(db()) as conn:
        total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_calcs = conn.execute("SELECT COUNT(*) FROM stats WHERE action='calculated_manual'").fetchone()[0]
    await message.answer(
        f"📊 <b>Статистика:</b>\n\n"
        f"👥 Пользователей: {total_users}\n"
        f"💰 Сделали расчет: {total_calcs}",
        parse_mode="HTML",
    )


async def main():
    if not BOT_TOKEN:
        print("BOT_TOKEN is not set")
        return
    init_db()
    bot = Bot(BOT_TOKEN)
    print("🚀 Бот-калькулятор запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
