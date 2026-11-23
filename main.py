import asyncio
import html
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
WINRATE_START = 60.0
WINRATE_RUB_PER_PCT = 163.8
WINRATE_MAX_MATCHES = 3000.0
QUICK_SALE_FACTOR = 0.85

RANKS = {
    "none": ("Ниже Epic", 0),
    "epic": ("Epic", 51),
    "legend": ("Legend", 256),
    "mythic": ("Mythic", 768),
    "honor": ("Mythical Honor", 1537),
    "glory": ("Mythical Glory", 5122),
    "immortal": ("Mythical Immortal", 10244),
}

SKIN_SPECS = {
    "legendary":        ("Легендарные", 4000, 410, True),
    "exquisite_grace":  ("Изящные", 3000, 307, True),
    "exquisite":        ("Изысканные", 2000, 205, True),
    "deluxe":           ("Роскошные", 400, 41, True),
    "exceptional":      ("Исключительные", 200, 20, True),
    "common":           ("Обычные", 100, 10, True),
    "painted":          ("Окраски для обликов", 40, 4, True),
    "grand_appearance": ("Великолепный облик", 0, 0, False),
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
    if winrate <= WINRATE_START or matches <= 0:
        return 0
    match_factor = min(matches / WINRATE_MAX_MATCHES, 1.0)
    extra_wr = min(winrate - WINRATE_START, 20.0)
    return round(extra_wr * WINRATE_RUB_PER_PCT * match_factor)


def _fmt_rub(amount: int) -> str:
    return f"{amount:,}".replace(",", " ") + " ₽"


def _fmt_int(amount: int) -> str:
    return f"{amount:,}".replace(",", " ")


def build_valuation(data: dict) -> dict:
    collection_points = max(0, int(_num(data.get("collection_points"), 0)))
    rank_key = str(data.get("rank") or "none")
    winrate = max(0.0, min(100.0, _num(data.get("winrate"), 0.0)))
    matches = max(0, int(_num(data.get("matches"), 0)))

    skins_raw = data.get("skins") if isinstance(data.get("skins"), dict) else {}
    skins_pts = 0
    skins_rub = 0
    chosen_skins = []

    for key, (label, pts_per_one, rub_per_one, _) in SKIN_SPECS.items():
        cnt = max(0, int(_num(skins_raw.get(key), 0)))
        if cnt > 0:
            skins_pts += cnt * pts_per_one
            skins_rub += cnt * rub_per_one
            chosen_skins.append((label, cnt))

    manual_rub = round((collection_points / 1000.0) * PRICE_PER_1000_PTS) if collection_points > 0 else 0
    effective_pts = max(collection_points, skins_pts)
    collection_rub = max(manual_rub, skins_rub)

    rank_name, rank_price = RANKS.get(rank_key, RANKS["none"])
    wr_bonus = _winrate_bonus(winrate, matches)

    total_price = BASE_PRICE + collection_rub + rank_price + wr_bonus
    quick_price = round(total_price * QUICK_SALE_FACTOR)

    return {
        "collection_points": collection_points,
        "effective_pts": effective_pts,
        "collection_rub": collection_rub,
        "rank_key": rank_key,
        "rank_name": rank_name,
        "rank_price": rank_price,
        "winrate": winrate,
        "matches": matches,
        "wr_bonus": wr_bonus,
        "chosen_skins": chosen_skins,
        "total_price": total_price,
        "quick_price": quick_price,
    }


def format_valuation_message(res: dict) -> str:
    breakdown_lines = []

    if res["collection_rub"] > 0:
        breakdown_lines.append(
            f"• Коллекция ({_fmt_int(res['effective_pts'])} pts): <b>+{_fmt_rub(res['collection_rub'])}</b>"
        )

    if res["rank_price"] > 0:
        safe_rank = html.escape(res["rank_name"])
        breakdown_lines.append(
            f"• Ранг ({safe_rank}): <b>+{_fmt_rub(res['rank_price'])}</b>"
        )

    if res["wr_bonus"] > 0:
        breakdown_lines.append(
            f"• Винрейт ({res['winrate']:g}%, {_fmt_int(res['matches'])} матчей): <b>+{_fmt_rub(res['wr_bonus'])}</b>"
        )

    parts = ["💎 <b>Оценка аккаунта MLBB</b>"]

    if breakdown_lines:
        parts.append("<b>Параметры и бонусы</b>\n" + "\n".join(breakdown_lines))
    else:
        parts.append("• Пустой аккаунт без очков коллекции и бонусов.")

    if res["chosen_skins"]:
        skins_str = ", ".join(f"{html.escape(lbl)}: {cnt}" for lbl, cnt in res["chosen_skins"])
        parts.append(f"<b>Облики</b>\n{skins_str}")

    summary_lines = [f"💰 <b>Рыночная оценка: {_fmt_rub(res['total_price'])}</b>"]
    if res["total_price"] > 0:
        summary_lines.append(f"⚡ Быстрая продажа (-15%): <b>{_fmt_rub(res['quick_price'])}</b>")

    parts.append("\n".join(summary_lines))
    return "\n\n".join(parts)


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
        "Укажи очки коллекции, ранг и облики — я рассчитаю примерную стоимость.",
        reply_markup=kb,
    )


@dp.message(F.web_app_data)
async def handle_webapp(message: Message):
    try:
        payload = json.loads(message.web_app_data.data)
        if not isinstance(payload, dict) or payload.get("action") != "calculate_manual":
            return

        d = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        res = build_valuation(d)
        answer = format_valuation_message(res)

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
