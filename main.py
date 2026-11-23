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

BASE_PRICE = 0
PRICE_PER_1000_PTS = 102.44

RANKS = {
    "none": ("Ниже Epic", 0),
    "epic": ("Epic", 51),
    "legend": ("Legend", 256),
    "mythic": ("Mythic", 768),
    "honor": ("Mythical Honor", 1537),
    "glory": ("Mythical Glory", 5122),
    "immortal": ("Mythical Immortal", 10244),
}

SKIN_LABELS = {
    "legendary": "Легендарные",
    "exquisite_grace": "Изящные",
    "exquisite": "Изысканные",
    "deluxe": "Роскошные",
    "exceptional": "Исключительные",
    "common": "Обычные",
    "painted": "Окраски для обликов",
    "grand_appearance": "Великолепный облик",
}


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


def _winrate_bonus(winrate: float, matches: int) -> int:
    if winrate <= 60 or matches <= 0:
        return 0
    match_factor = min(matches / 3000.0, 1.0)
    extra_wr = min(winrate - 60.0, 20.0)
    return round(extra_wr * 163.8 * match_factor)


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
        "👋 Привет! Нажми кнопку внизу, чтобы открыть калькулятор MLBB.\n\n"
        "Укажи очки коллекции, ранг и статистику — я рассчитаю примерную стоимость.",
        reply_markup=kb,
    )


@dp.message(F.web_app_data)
async def handle_webapp(message: Message):
    try:
        payload = json.loads(message.web_app_data.data)
        if not isinstance(payload, dict) or payload.get("action") != "calculate_manual":
            return

        d = payload.get("data") if isinstance(payload.get("data"), dict) else {}

        collection_points = max(0, int(_num(d.get("collection_points"), 0)))
        rank_key = str(d.get("rank") or "none")
        winrate = max(0.0, min(100.0, _num(d.get("winrate"), 0.0)))
        matches = max(0, int(_num(d.get("matches"), 0)))

        bonuses = 0
        details = []

        if collection_points > 0:
            col_rub = round((collection_points / 1000.0) * PRICE_PER_1000_PTS)
            bonuses += col_rub
            details.append(f"• Очки коллекции ({collection_points:,} pts): <b>+{col_rub:,} ₽</b>".replace(",", " "))

        rank_name, rank_price = RANKS.get(rank_key, RANKS["none"])
        if rank_price > 0:
            bonuses += rank_price
            details.append(f"• Ранг ({rank_name}): <b>+{rank_price:,} ₽</b>".replace(",", " "))

        wr_bonus = _winrate_bonus(winrate, matches)
        if wr_bonus > 0:
            bonuses += wr_bonus
            details.append(f"• Винрейт ({winrate:g}%, {matches:,} матчей): <b>+{wr_bonus:,} ₽</b>".replace(",", " "))

        skins = d.get("skins") if isinstance(d.get("skins"), dict) else {}
        chosen = []
        for key, label in SKIN_LABELS.items():
            cnt = max(0, int(_num(skins.get(key), 0)))
            if cnt > 0:
                chosen.append(f"{label}: {cnt}")
        if chosen:
            details.append("• Облики: " + ", ".join(chosen))

        total_price = BASE_PRICE + bonuses

        if not details:
            details.append("• Пустой аккаунт без очков коллекции и бонусов.")

        details_text = "\n".join(details)
        total_formatted = f"{total_price:,}".replace(",", " ")

        answer = (
            f"<b>📊 Оценка аккаунта MLBB</b>\n\n"
            f"{details_text}\n\n"
            f"<b>💰 Итоговая оценка: {total_formatted} ₽</b>\n\n"
            f"<i>Совет: Для быстрой продажи ориентируйтесь на цену на 10–15% ниже оценки.</i>"
        )

        await message.answer(answer, parse_mode="HTML")
        if message.from_user:
            log_action(message.from_user.id, "calculated_manual")

    except Exception as e:
        print("WebApp error:", e)
        await message.answer("❌ Не удалось выполнить расчёт. Попробуй ещё раз.")


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
        f"💰 Сделали расчёт: {total_calcs}",
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
